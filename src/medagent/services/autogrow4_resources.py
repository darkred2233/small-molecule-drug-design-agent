"""AutoGrow4 资源解析器。

由 RoundOrchestrator 在调用 AutoGrow4Agent 之前调用，负责：
- 选择 receptor / pocket
- 构建 source pool
- 标准化、去重、写 source_compounds.smi
- 生成 docking config
- 估算计算量
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from medagent.db.models import (
    BindingSite,
    Molecule,
    Project,
    ProjectResource,
    ProjectRound,
    Ranking,
    SeedLigand,
    TargetDrugLibrary,
)
from medagent.domain.schemas import AutoGrow4CampaignConfig, AutoGrow4ResourceBundle
from medagent.services.pdbqt_validation import is_valid_vina_receptor_pdbqt


def resolve_autogrow4_resources(
    db: Session,
    project: Project,
    config: AutoGrow4CampaignConfig,
    *,
    source_compounds: list[tuple[str, str]] | None = None,
    parent_round_id: str | None = None,
    artifact_id: str | None = None,
) -> AutoGrow4ResourceBundle:
    """解析 AutoGrow4 运行所需的所有资源。"""
    # 1. 解析 receptor / binding site
    (
        receptor_file,
        prepared_receptor_file,
        grid_center,
        grid_size,
        binding_site_id,
    ) = _resolve_receptor_and_grid(db, project, config)

    # 2. 构建 source pool
    if source_compounds is None:
        source_compounds, provenance = _build_source_pool(
            db, project, config, parent_round_id=parent_round_id
        )
    else:
        source_compounds = _dedupe_compounds(source_compounds)
        provenance = {
            "policy": config.source_pool_policy,
            "sources": [{"type": "confirmed_execution_snapshot", "count": len(source_compounds)}],
            "total_unique": len(source_compounds),
            "parent_round_id": parent_round_id,
        }

    # 3. 写 source_compounds.smi
    source_file = _write_source_compounds(project, source_compounds, artifact_id=artifact_id)

    # 4. 构建 docking config
    docking_config = _build_docking_config(config)

    return AutoGrow4ResourceBundle(
        receptor_file=receptor_file,
        prepared_receptor_file=prepared_receptor_file,
        binding_site_id=binding_site_id,
        grid_center=grid_center,
        grid_size=grid_size,
        source_compounds_file=str(source_file),
        source_compound_count=len(source_compounds),
        docking_config=docking_config,
        provenance=provenance,
    )


def eligible_autogrow4_source_count(db: Session, project: Project) -> int:
    """Count unique compounds available through any supported source-pool policy."""
    auto_compounds, _ = _build_source_pool(
        db,
        project,
        AutoGrow4CampaignConfig(source_pool_policy="auto"),
    )
    previous_compounds = _previous_top_compounds(db, project, 200)
    return len({smiles for smiles, _ in [*auto_compounds, *previous_compounds]})


def resolve_autogrow4_seed_plan(
    db: Session,
    project: Project,
    config: AutoGrow4CampaignConfig,
    *,
    parent_round_id: str | None,
) -> dict[str, Any]:
    """Resolve AutoGrow inputs once, before the execution snapshot is sealed."""
    compounds, provenance = _build_source_pool(
        db,
        project,
        config,
        parent_round_id=parent_round_id,
    )
    return {
        "smiles": [smiles for smiles, _ in compounds],
        "molecule_ids": [molecule_id for _, molecule_id in compounds],
        "provenance": provenance,
    }


def _resolve_receptor_and_grid(
    db: Session,
    project: Project,
    config: AutoGrow4CampaignConfig,
) -> tuple[str, str | None, list[float], list[float], str | None]:
    """解析 receptor 文件和 grid 配置。"""
    # 优先使用 config 指定的 binding_site_id
    binding_site_id = config.binding_site_id

    if binding_site_id:
        site = db.query(BindingSite).filter(
            BindingSite.binding_site_id == binding_site_id,
            BindingSite.project_id == project.project_id,
        ).first()
        if site and project.active_structure_id and site.structure_id != project.active_structure_id:
            raise ValueError("AutoGrow4 selected binding site is not from the active project structure")
        if site and _source_pdb(site) and _prepared_pdbqt(site):
            grid = _binding_site_grid(site)
            if grid is None:
                raise ValueError("AutoGrow4 selected binding site has no valid docking grid")
            center, size = grid
            return _source_pdb(site), _prepared_pdbqt(site), center, size, binding_site_id

    # 尝试使用 ProjectResource 中的 receptor
    if config.receptor_resource_id:
        resource = db.query(ProjectResource).filter(
            ProjectResource.resource_id == config.receptor_resource_id,
            ProjectResource.project_id == project.project_id,
            ProjectResource.resource_type == "receptor",
        ).first()
        if resource and resource.file_path:
            metadata = resource.metadata_json or {}
            center = metadata.get("grid_center")
            size = metadata.get("grid_size")
            if not _valid_grid(center, size):
                raise ValueError("AutoGrow4 receptor resource has no valid P2Rank-derived docking grid")
            receptor_file = _local_file_path(resource.file_path)
            if _is_valid_pdb_file(receptor_file):
                return receptor_file, None, center, size, None

    raise ValueError(
        "AutoGrow4 requires receptor + binding pocket. "
        "Provide binding_site_id or receptor_resource_id in config, "
        "or ensure the project has a binding site with a source PDB and prepared PDBQT receptor."
    )


def _binding_site_grid(site: BindingSite) -> tuple[list[float], list[float]] | None:
    grid_box = site.grid_box or {}
    center = grid_box.get("center")
    size = grid_box.get("size")
    if not isinstance(center, list) or not isinstance(size, list):
        return None
    if len(center) != 3 or len(size) != 3:
        return None
    try:
        center_values = [float(value) for value in center]
        size_values = [float(value) for value in size]
    except (TypeError, ValueError):
        return None
    if not all(value > 0 for value in size_values):
        return None
    return center_values, size_values


def _valid_grid(center: Any, size: Any) -> bool:
    if not isinstance(center, list) or not isinstance(size, list):
        return False
    if len(center) != 3 or len(size) != 3:
        return False
    try:
        return all(float(value) > 0 for value in size) and len([float(value) for value in center]) == 3
    except (TypeError, ValueError):
        return False


def _local_file_path(path: str) -> str:
    return path.removeprefix("local://")


def _prepared_pdbqt(site: BindingSite) -> str | None:
    candidate = site.prepared_receptor_file
    if not candidate:
        return None
    path = _local_file_path(candidate)
    return path if _is_valid_pdbqt_file(path) else None


def _source_pdb(site: BindingSite) -> str | None:
    if not site.receptor_file:
        return None
    path = _local_file_path(site.receptor_file)
    return path if _is_valid_pdb_file(path) else None


def _is_valid_pdb_file(path: str) -> bool:
    candidate = Path(path)
    return candidate.suffix.lower() == ".pdb" and candidate.is_file()


def _is_valid_pdbqt_file(path: str) -> bool:
    candidate = Path(path)
    return candidate.suffix.lower() == ".pdbqt" and is_valid_vina_receptor_pdbqt(candidate)


def _build_source_pool(
    db: Session,
    project: Project,
    config: AutoGrow4CampaignConfig,
    *,
    parent_round_id: str | None = None,
) -> tuple[list[tuple[str, str]], dict[str, Any]]:
    """构建 source pool，返回 ([(smiles, compound_id), ...], provenance)。"""
    compounds: list[tuple[str, str]] = []
    provenance: dict[str, Any] = {"sources": []}

    policy = config.source_pool_policy

    if policy == "previous_top":
        compounds = _previous_top_compounds(
            db,
            project,
            config.previous_top_n,
            parent_round_id=parent_round_id,
        )
        provenance["sources"].append({"type": "previous_top", "count": len(compounds)})
    elif policy in ("auto", "user_uploaded"):
        # 用户上传的 seed ligands
        seeds = db.query(SeedLigand).filter(
            SeedLigand.project_id == project.project_id,
        ).all()
        for seed in seeds:
            if seed.smiles:
                compounds.append((seed.smiles, seed.ligand_id))
        provenance["sources"].append({
            "type": "user_seeds",
            "count": len(seeds),
        })

    if policy in ("auto", "target_ligands") and project.target_id:
        # 靶点已知药物
        drugs = db.query(TargetDrugLibrary).filter(
            TargetDrugLibrary.target_id == project.target_id,
        ).all()
        for drug in drugs:
            smiles = drug.isomeric_smiles or drug.canonical_smiles or drug.smiles
            if smiles:
                compounds.append((smiles, f"drug_{drug.drug_name}"))
        provenance["sources"].append({
            "type": "target_drug_library",
            "count": len(drugs),
        })

    unique_compounds = _dedupe_compounds(compounds)

    provenance["total_unique"] = len(unique_compounds)
    provenance["policy"] = policy

    return unique_compounds, provenance


def _previous_top_compounds(
    db: Session,
    project: Project,
    limit: int,
    *,
    parent_round_id: str | None = None,
) -> list[tuple[str, str]]:
    previous_round = None
    if parent_round_id:
        previous_round = db.query(ProjectRound).filter_by(
            project_id=project.project_id,
            round_id=parent_round_id,
        ).one_or_none()
    else:
        previous_round = (
            db.query(ProjectRound)
            .filter(ProjectRound.project_id == project.project_id, ProjectRound.status == "completed")
            .order_by(ProjectRound.round_number.desc(), ProjectRound.id.desc())
            .first()
        )
    if previous_round is None:
        return []
    rows = (
        db.query(Molecule, Ranking)
        .join(
            Ranking,
            (Ranking.molecule_id == Molecule.molecule_id)
            & (Ranking.round_id == previous_round.round_id),
        )
        .filter(Molecule.project_id == project.project_id, Molecule.round_id == previous_round.round_id)
        .order_by(Ranking.rank.asc(), Molecule.molecule_id.asc())
        .limit(limit)
        .all()
    )
    return [(molecule.smiles, molecule.molecule_id) for molecule, _ in rows if molecule.smiles]


def _dedupe_compounds(compounds: list[tuple[str, str]]) -> list[tuple[str, str]]:
    seen_smiles: set[str] = set()
    unique: list[tuple[str, str]] = []
    for smiles, compound_id in compounds:
        if smiles in seen_smiles:
            continue
        seen_smiles.add(smiles)
        unique.append((smiles, compound_id))
    return unique


def _write_source_compounds(
    project: Project,
    compounds: list[tuple[str, str]],
    *,
    artifact_id: str | None = None,
) -> Path:
    """写 source_compounds.smi 文件。"""
    output_dir = Path(".local/projects") / project.project_id / "autogrow4"
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = "source_compounds.smi" if artifact_id is None else f"source_compounds_{artifact_id}.smi"
    source_file = output_dir / filename

    with open(source_file, "w", encoding="utf-8") as f:
        for smiles, compound_id in compounds:
            f.write(f"{smiles}\t{compound_id}\n")

    return source_file


def _build_docking_config(config: AutoGrow4CampaignConfig) -> dict[str, Any]:
    """构建 docking 配置。"""
    return {
        "search_intensity": config.search_intensity,
        "generations": config.generations,
    }
