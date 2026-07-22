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

from medagent.db.models import BindingSite, Project, ProjectResource, SeedLigand, TargetDrugLibrary
from medagent.domain.schemas import AutoGrow4CampaignConfig, AutoGrow4ResourceBundle


# search_intensity 映射
INTENSITY_PROFILES: dict[str, dict[str, int]] = {
    "quick": {
        "generations": 3,
        "population_size": 30,
        "mutants": 15,
        "crossovers": 15,
        "top_mols": 15,
        "max_variants": 2,
    },
    "normal": {
        "generations": 5,
        "population_size": 50,
        "mutants": 25,
        "crossovers": 25,
        "top_mols": 30,
        "max_variants": 3,
    },
    "heavy": {
        "generations": 10,
        "population_size": 100,
        "mutants": 50,
        "crossovers": 50,
        "top_mols": 50,
        "max_variants": 5,
    },
}


def resolve_autogrow4_resources(
    db: Session,
    project: Project,
    config: AutoGrow4CampaignConfig,
) -> AutoGrow4ResourceBundle:
    """解析 AutoGrow4 运行所需的所有资源。"""
    # 1. 解析 receptor / binding site
    receptor_file, grid_center, grid_size, binding_site_id = _resolve_receptor_and_grid(
        db, project, config
    )

    # 2. 构建 source pool
    source_compounds, provenance = _build_source_pool(db, project, config)

    # 3. 写 source_compounds.smi
    source_file = _write_source_compounds(project, source_compounds)

    # 4. 构建 docking config
    docking_config = _build_docking_config(config)

    return AutoGrow4ResourceBundle(
        receptor_file=receptor_file,
        prepared_receptor_file=None,
        binding_site_id=binding_site_id,
        grid_center=grid_center,
        grid_size=grid_size,
        source_compounds_file=str(source_file),
        source_compound_count=len(source_compounds),
        docking_config=docking_config,
        provenance=provenance,
    )


def intensity_profile(search_intensity: str) -> dict[str, int]:
    """获取搜索强度对应的参数 profile。"""
    return INTENSITY_PROFILES.get(search_intensity, INTENSITY_PROFILES["normal"])


def estimate_docking_jobs(generations: int, population_size: int, max_variants: int = 3) -> int:
    """估算 docking 计算量。"""
    return generations * population_size * max_variants


def _resolve_receptor_and_grid(
    db: Session,
    project: Project,
    config: AutoGrow4CampaignConfig,
) -> tuple[str, list[float], list[float], str | None]:
    """解析 receptor 文件和 grid 配置。"""
    # 优先使用 config 指定的 binding_site_id
    binding_site_id = config.binding_site_id

    if binding_site_id:
        site = db.query(BindingSite).filter(
            BindingSite.binding_site_id == binding_site_id,
        ).first()
        if site and site.receptor_file:
            grid = _binding_site_grid(site)
            if grid is None:
                raise ValueError("AutoGrow4 selected binding site has no valid docking grid")
            center, size = grid
            return _local_file_path(site.receptor_file), center, size, binding_site_id

    # Prefer an actually prepared, grid-defined site. Projects can retain an
    # earlier uploaded-only site alongside the prepared receptor.
    sites = (
        db.query(BindingSite)
        .filter(BindingSite.project_id == project.project_id)
        .order_by(BindingSite.created_at.desc(), BindingSite.id.desc())
        .all()
    )
    sites.sort(key=lambda site: site.preparation_status != "prepared")
    for site in sites:
        if not site.receptor_file:
            continue
        grid = _binding_site_grid(site)
        if grid is None:
            continue
        center, size = grid
        return _local_file_path(site.receptor_file), center, size, site.binding_site_id

    # 尝试使用 ProjectResource 中的 receptor
    if config.receptor_resource_id:
        resource = db.query(ProjectResource).filter(
            ProjectResource.resource_id == config.receptor_resource_id,
            ProjectResource.resource_type == "receptor",
        ).first()
        if resource and resource.file_path:
            metadata = resource.metadata_json or {}
            center = metadata.get("grid_center", [0, 0, 0])
            size = metadata.get("grid_size", [20, 20, 20])
            return _local_file_path(resource.file_path), center, size, None

    raise ValueError(
        "AutoGrow4 requires receptor + binding pocket. "
        "Provide binding_site_id or receptor_resource_id in config, "
        "or ensure the project has a binding site with receptor file."
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


def _local_file_path(path: str) -> str:
    return path.removeprefix("local://")


def _build_source_pool(
    db: Session,
    project: Project,
    config: AutoGrow4CampaignConfig,
) -> tuple[list[tuple[str, str]], dict[str, Any]]:
    """构建 source pool，返回 ([(smiles, compound_id), ...], provenance)。"""
    compounds: list[tuple[str, str]] = []
    provenance: dict[str, Any] = {"sources": []}

    policy = config.source_pool_policy

    if policy in ("auto", "user_uploaded"):
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

    # 去重（按 SMILES）
    seen_smiles: set[str] = set()
    unique_compounds: list[tuple[str, str]] = []
    for smiles, compound_id in compounds:
        if smiles not in seen_smiles:
            seen_smiles.add(smiles)
            unique_compounds.append((smiles, compound_id))

    provenance["total_unique"] = len(unique_compounds)
    provenance["policy"] = policy

    return unique_compounds, provenance


def _write_source_compounds(
    project: Project,
    compounds: list[tuple[str, str]],
) -> Path:
    """写 source_compounds.smi 文件。"""
    output_dir = Path(".local/projects") / project.project_id / "autogrow4"
    output_dir.mkdir(parents=True, exist_ok=True)
    source_file = output_dir / "source_compounds.smi"

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
