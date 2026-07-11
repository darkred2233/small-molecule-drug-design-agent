import math
import shutil
from dataclasses import dataclass, field
from importlib import metadata, util
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from medagent.db.models import (
    ADMETResult,
    AgentRun,
    BindingSite,
    ConformerResult,
    DockingResult,
    Molecule,
    MoleculeProperty,
    Project,
    SynthesisRoute,
)
from medagent.services.admet_adapter import (
    ChempropADMETOutput,
    ChempropADMETRequest,
    SingleADMETResult,
    chemprop_tool_status,
    run_chemprop_admet,
)
from medagent.services.candidate_ranking import generate_project_rankings
from medagent.services.docking_adapters import (
    DockingToolRequest,
    DockingToolResult,
    check_diffdock_available,
    run_external_docking,
    select_docking_tool,
)
from medagent.services.ids import new_id
from medagent.services.molecule_validation import merge_labels
from medagent.services.rdkit_adapter import find_rdkit_filter_matches
from medagent.services.receptor_preparation import resolve_receptor_path


CONFORMER_AGENT_NAME = "conformer_agent"
DOCKING_AGENT_NAME = "docking_agent"
ADMET_AGENT_NAME = "admet_agent"
SYNTHESIS_AGENT_NAME = "synthesis_agent"
ASSESSMENT_ELIGIBLE_STATUSES = {
    "generated",
    "imported_from_seed",
    "structure_validated",
    "passed_filter",
    "candidate_assessed",
}
ASSESSMENT_RUNTIME_ROOT = Path(".local") / "candidate_assessment"


@dataclass
class StageSummary:
    agent_run_id: str
    adapter_mode: str
    requested_count: int
    generated_count: int = 0
    evaluated_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0
    molecule_ids: list[str] = field(default_factory=list)
    skipped_molecule_ids: list[str] = field(default_factory=list)
    failed_molecule_ids: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "agent_run_id": self.agent_run_id,
            "adapter_mode": self.adapter_mode,
            "requested_count": self.requested_count,
            "generated_count": self.generated_count,
            "evaluated_count": self.evaluated_count,
            "skipped_count": self.skipped_count,
            "failed_count": self.failed_count,
            "molecule_ids": self.molecule_ids,
            "skipped_molecule_ids": self.skipped_molecule_ids,
            "failed_molecule_ids": self.failed_molecule_ids,
            "warnings": self.warnings,
        }


@dataclass(frozen=True)
class DescriptorSnapshot:
    mw: float
    logp: float
    tpsa: float
    hbd: int
    hba: int
    heavy_atom_count: int
    rotatable_bond_count: int
    ring_count: int
    aromatic_ring_count: int
    chiral_centers: int
    undefined_stereo_centers: int
    element_counts: dict[str, int]


def run_project_candidate_assessment(
    db: Session,
    project: Project,
    molecule_ids: list[str] | None = None,
    max_molecules: int = 50,
    binding_site_id: str | None = None,
    protein_file: str | None = None,
    prepared_ligand_files: dict[str, str] | None = None,
    grid_center: list[float] | None = None,
    grid_size: list[float] | None = None,
    key_residues: list[str] | None = None,
    admet_properties: list[str] | None = None,
    max_synthesis_steps: int = 5,
    prefer_buyable_building_blocks: bool = True,
) -> dict[str, Any]:
    molecules = _select_assessment_molecules(db, project, molecule_ids, max_molecules)
    tool_status = candidate_assessment_tool_status()
    conformer = generate_project_conformers(db, project, molecules, tool_status)
    docking = run_project_docking(
        db,
        project,
        molecules,
        tool_status,
        binding_site_id=binding_site_id,
        protein_file=protein_file,
        prepared_ligand_files=prepared_ligand_files,
        grid_center=grid_center,
        grid_size=grid_size,
        key_residues=key_residues or [],
    )
    admet = run_project_admet(
        db,
        project,
        molecules,
        tool_status,
        admet_properties=admet_properties or [],
    )
    synthesis = run_project_synthesis(
        db,
        project,
        molecules,
        tool_status,
        max_synthesis_steps=max_synthesis_steps,
        prefer_buyable_building_blocks=prefer_buyable_building_blocks,
    )
    ranking = generate_project_rankings(
        db,
        project,
        molecules=molecules,
        max_molecules=max_molecules,
        top_n=max_molecules,
        tool_status=tool_status,
    )
    project.status = "candidate_assessed"
    db.commit()
    return {
        "project_id": project.project_id,
        "conformer": conformer.as_dict(),
        "docking": docking.as_dict(),
        "admet": admet.as_dict(),
        "synthesis": synthesis.as_dict(),
        "ranking": ranking.as_dict(),
        "tool_status": tool_status,
    }


def generate_project_conformers(
    db: Session,
    project: Project,
    molecules: list[Molecule],
    tool_status: dict[str, Any] | None = None,
) -> StageSummary:
    tool_status = tool_status or candidate_assessment_tool_status()
    agent_run = _create_agent_run(
        db,
        project,
        CONFORMER_AGENT_NAME,
        "rdkit_etkdg_conformer",
        {"molecule_ids": [molecule.molecule_id for molecule in molecules]},
        tool_status,
    )
    summary = StageSummary(
        agent_run_id=agent_run.agent_run_id,
        adapter_mode="rdkit_etkdg_conformer",
        requested_count=len(molecules),
    )

    for molecule in molecules:
        result = _calculate_conformer_result(molecule.smiles)
        conformer = _upsert_conformer_result(db, molecule, result)
        molecule.labels = merge_labels(molecule.labels, conformer.labels)
        if conformer.conformer_generated:
            summary.generated_count += 1
            summary.evaluated_count += 1
            summary.molecule_ids.append(molecule.molecule_id)
        else:
            summary.failed_count += 1
            summary.failed_molecule_ids.append(molecule.molecule_id)

    _finish_agent_run(agent_run, summary, tool_status)
    db.commit()
    return summary


def run_project_docking(
    db: Session,
    project: Project,
    molecules: list[Molecule],
    tool_status: dict[str, Any] | None = None,
    binding_site_id: str | None = None,
    protein_file: str | None = None,
    prepared_ligand_files: dict[str, str] | None = None,
    grid_center: list[float] | None = None,
    grid_size: list[float] | None = None,
    key_residues: list[str] | None = None,
) -> StageSummary:
    tool_status = tool_status or candidate_assessment_tool_status()
    key_residues = key_residues or []
    site_config = _binding_site_docking_config(db, project, binding_site_id)
    if site_config:
        protein_file = protein_file or site_config.get("protein_file")
        grid_center = grid_center or site_config.get("grid_center")
        grid_size = grid_size or site_config.get("grid_size")
        if not key_residues:
            key_residues = site_config.get("key_residues", [])
    agent_run = _create_agent_run(
        db,
        project,
        DOCKING_AGENT_NAME,
        "rdkit_surrogate_docking",
        {
            "molecule_ids": [molecule.molecule_id for molecule in molecules],
            "binding_site_id": binding_site_id,
            "protein_file": protein_file,
            "prepared_ligand_files": prepared_ligand_files or {},
            "grid_center": grid_center,
            "grid_size": grid_size,
            "key_residues": key_residues,
        },
        tool_status,
    )
    summary = StageSummary(
        agent_run_id=agent_run.agent_run_id,
        adapter_mode="rdkit_surrogate_docking",
        requested_count=len(molecules),
        warnings=_external_docking_setup_warnings(
            tool_status,
            protein_file=protein_file,
            prepared_ligand_files=prepared_ligand_files or {},
            grid_center=grid_center,
            grid_size=grid_size,
        ),
    )
    external_adapter_modes: set[str] = set()

    for molecule in molecules:
        conformer = db.query(ConformerResult).filter_by(molecule_id=molecule.molecule_id).one_or_none()
        if conformer is None or not conformer.conformer_generated:
            summary.skipped_count += 1
            summary.skipped_molecule_ids.append(molecule.molecule_id)
            continue

        descriptors = _descriptor_snapshot(molecule.smiles, db, molecule)
        if descriptors is None:
            summary.failed_count += 1
            summary.failed_molecule_ids.append(molecule.molecule_id)
            continue

        external_result = _attempt_external_docking(
            project,
            molecule,
            tool_status,
            protein_file=protein_file,
            prepared_ligand_files=prepared_ligand_files or {},
            grid_center=grid_center,
            grid_size=grid_size,
        )
        if external_result is not None and external_result.success:
            docking = _upsert_external_docking_result(
                db,
                molecule,
                conformer,
                descriptors,
                key_residues=key_residues,
                external_result=external_result,
            )
            external_adapter_modes.add(external_result.adapter_mode)
        else:
            if external_result is not None and external_result.warnings:
                summary.warnings = _dedupe(summary.warnings + external_result.warnings)
            docking = _upsert_docking_result(
                db,
                molecule,
                conformer,
                descriptors,
                key_residues=key_residues,
            )
        molecule.labels = merge_labels(molecule.labels, docking.labels)
        summary.evaluated_count += 1
        summary.generated_count += 1
        summary.molecule_ids.append(molecule.molecule_id)

    if len(external_adapter_modes) == 1:
        summary.adapter_mode = next(iter(external_adapter_modes))
    elif len(external_adapter_modes) > 1:
        summary.adapter_mode = "external_docking_with_rdkit_fallback"

    _finish_agent_run(agent_run, summary, tool_status)
    db.commit()
    return summary


def run_project_admet(
    db: Session,
    project: Project,
    molecules: list[Molecule],
    tool_status: dict[str, Any] | None = None,
    admet_properties: list[str] | None = None,
) -> StageSummary:
    tool_status = tool_status or candidate_assessment_tool_status()

    # Try Chemprop first if available
    chemprop_available = tool_status.get("chemprop", {}).get("available", False)
    adapter_mode = "chemprop_admet" if chemprop_available else "rdkit_surrogate_admet"

    agent_run = _create_agent_run(
        db,
        project,
        ADMET_AGENT_NAME,
        adapter_mode,
        {
            "molecule_ids": [molecule.molecule_id for molecule in molecules],
            "properties": admet_properties or [],
        },
        tool_status,
    )
    summary = StageSummary(
        agent_run_id=agent_run.agent_run_id,
        adapter_mode=adapter_mode,
        requested_count=len(molecules),
        warnings=[],
    )

    if chemprop_available:
        # Use Chemprop for real ADMET predictions
        chemprop_result = _run_chemprop_for_project(db, molecules, tool_status, admet_properties)
        summary.adapter_mode = chemprop_result.adapter_mode
        summary.generated_count = len(chemprop_result.results)
        summary.evaluated_count = len(chemprop_result.results)
        summary.molecule_ids = [r.molecule_id for r in chemprop_result.results]
        summary.warnings.extend(chemprop_result.warnings)

        # Process Chemprop results
        for single_result in chemprop_result.results:
            molecule = next(
                (m for m in molecules if m.molecule_id == single_result.molecule_id), None
            )
            if molecule is None:
                continue

            admet = _upsert_admet_result_from_chemprop(
                db,
                molecule,
                single_result,
                adapter_mode=chemprop_result.adapter_mode,
            )
            molecule.labels = merge_labels(molecule.labels, admet.labels)

        # Fallback to RDKit surrogate for molecules without Chemprop results
        chemprop_ids = {r.molecule_id for r in chemprop_result.results}
        fallback_count = 0
        for molecule in molecules:
            if molecule.molecule_id not in chemprop_ids:
                descriptors = _descriptor_snapshot(molecule.smiles, db, molecule)
                if descriptors is None:
                    summary.failed_count += 1
                    summary.failed_molecule_ids.append(molecule.molecule_id)
                    continue
                admet = _upsert_admet_result(db, molecule, descriptors, tool_status)
                molecule.labels = merge_labels(molecule.labels, admet.labels)
                summary.evaluated_count += 1
                summary.generated_count += 1
                summary.molecule_ids.append(molecule.molecule_id)
                fallback_count += 1

        if fallback_count:
            if chemprop_ids:
                summary.adapter_mode = "chemprop_with_rdkit_surrogate_admet"
                summary.warnings.append("chemprop_partial_fallback_to_rdkit")
            else:
                summary.adapter_mode = "rdkit_surrogate_admet"
                summary.warnings.append("chemprop_model_unavailable_using_rdkit_surrogate")
    else:
        # RDKit surrogate fallback
        summary.warnings.append("external_admet_tools_not_installed")
        for molecule in molecules:
            descriptors = _descriptor_snapshot(molecule.smiles, db, molecule)
            if descriptors is None:
                summary.failed_count += 1
                summary.failed_molecule_ids.append(molecule.molecule_id)
                continue

            admet = _upsert_admet_result(db, molecule, descriptors, tool_status)
            molecule.labels = merge_labels(molecule.labels, admet.labels)
            summary.evaluated_count += 1
            summary.generated_count += 1
            summary.molecule_ids.append(molecule.molecule_id)

    _finish_agent_run(agent_run, summary, tool_status)
    db.commit()
    return summary


def _run_chemprop_for_project(
    db: Session,
    molecules: list[Molecule],
    tool_status: dict[str, Any],
    admet_properties: list[str] | None,
) -> ChempropADMETOutput:
    """Run Chemprop ADMET for all molecules in a project."""
    smiles_list = [m.smiles for m in molecules]
    molecule_ids = [m.molecule_id for m in molecules]

    request = ChempropADMETRequest(
        smiles_list=smiles_list,
        molecule_ids=molecule_ids,
        properties=admet_properties or [
            "hERG", "Ames", "CYP3A4", "CYP2D6", "solubility",
            "permeability", "DILI", "Pgp", "BBB",
        ],
    )

    return run_chemprop_admet(request, tool_status.get("chemprop"))


def _upsert_admet_result_from_chemprop(
    db: Session,
    molecule: Molecule,
    chemprop_result: SingleADMETResult,
    adapter_mode: str = "chemprop_admet",
) -> ADMETResult:
    """Create or update ADMET result from Chemprop prediction."""
    result = db.query(ADMETResult).filter_by(molecule_id=molecule.molecule_id).one_or_none()
    if result is None:
        result = ADMETResult(molecule_id=molecule.molecule_id)
        db.add(result)

    result.hERG_probability = chemprop_result.hERG_probability
    result.hERG_risk = chemprop_result.hERG_risk
    result.Ames_probability = chemprop_result.Ames_probability
    result.Ames_risk = chemprop_result.Ames_risk
    result.solubility = chemprop_result.solubility
    result.permeability = chemprop_result.permeability
    result.admet_risk_score = chemprop_result.admet_risk_score
    result.labels = _dedupe(chemprop_result.labels)
    result.raw_output = {
        "adapter_mode": adapter_mode,
        "tool_name": "chemprop",
        "CYP3A4_inhibition": chemprop_result.CYP3A4_inhibition,
        "CYP3A4_risk": chemprop_result.CYP3A4_risk,
        "CYP2D6_inhibition": chemprop_result.CYP2D6_inhibition,
        "CYP2D6_risk": chemprop_result.CYP2D6_risk,
        "DILI_probability": chemprop_result.DILI_probability,
        "DILI_risk": chemprop_result.DILI_risk,
        "Pgp_substrate": chemprop_result.Pgp_substrate,
        "Pgp_risk": chemprop_result.Pgp_risk,
        "BBB_penetration": chemprop_result.BBB_penetration,
        "BBB_risk": chemprop_result.BBB_risk,
    }
    return result


def run_project_synthesis(
    db: Session,
    project: Project,
    molecules: list[Molecule],
    tool_status: dict[str, Any] | None = None,
    max_synthesis_steps: int = 5,
    prefer_buyable_building_blocks: bool = True,
) -> StageSummary:
    tool_status = tool_status or candidate_assessment_tool_status()
    agent_run = _create_agent_run(
        db,
        project,
        SYNTHESIS_AGENT_NAME,
        "rdkit_surrogate_synthesis",
        {
            "molecule_ids": [molecule.molecule_id for molecule in molecules],
            "max_steps": max_synthesis_steps,
            "prefer_buyable_building_blocks": prefer_buyable_building_blocks,
        },
        tool_status,
    )
    summary = StageSummary(
        agent_run_id=agent_run.agent_run_id,
        adapter_mode="rdkit_surrogate_synthesis",
        requested_count=len(molecules),
        warnings=["external_retrosynthesis_tools_not_installed"]
        if not _external_synthesis_available(tool_status)
        else [],
    )

    for molecule in molecules:
        descriptors = _descriptor_snapshot(molecule.smiles, db, molecule)
        if descriptors is None:
            summary.failed_count += 1
            summary.failed_molecule_ids.append(molecule.molecule_id)
            continue

        route = _upsert_synthesis_route(
            db,
            molecule,
            descriptors,
            tool_status,
            max_synthesis_steps=max_synthesis_steps,
            prefer_buyable_building_blocks=prefer_buyable_building_blocks,
        )
        molecule.labels = merge_labels(molecule.labels, route.labels)
        molecule.status = "candidate_assessed"
        _update_sa_score(db, molecule, route.route_json.get("SA_score"))
        summary.evaluated_count += 1
        summary.generated_count += 1
        summary.molecule_ids.append(molecule.molecule_id)

    _finish_agent_run(agent_run, summary, tool_status)
    db.commit()
    return summary


def list_project_conformer_results(db: Session, project: Project) -> list[ConformerResult]:
    return (
        db.query(ConformerResult)
        .join(Molecule, ConformerResult.molecule_id == Molecule.molecule_id)
        .filter(Molecule.project_id == project.project_id)
        .order_by(Molecule.id.asc())
        .all()
    )


def list_project_docking_results(db: Session, project: Project) -> list[DockingResult]:
    return (
        db.query(DockingResult)
        .join(Molecule, DockingResult.molecule_id == Molecule.molecule_id)
        .filter(Molecule.project_id == project.project_id)
        .order_by(Molecule.id.asc())
        .all()
    )


def list_project_admet_results(db: Session, project: Project) -> list[ADMETResult]:
    return (
        db.query(ADMETResult)
        .join(Molecule, ADMETResult.molecule_id == Molecule.molecule_id)
        .filter(Molecule.project_id == project.project_id)
        .order_by(Molecule.id.asc())
        .all()
    )


def list_project_synthesis_routes(db: Session, project: Project) -> list[SynthesisRoute]:
    return (
        db.query(SynthesisRoute)
        .join(Molecule, SynthesisRoute.molecule_id == Molecule.molecule_id)
        .filter(Molecule.project_id == project.project_id)
        .order_by(Molecule.id.asc())
        .all()
    )


def candidate_assessment_tool_status() -> dict[str, Any]:
    return {
        "rdkit": _package_status("rdkit"),
        "gnina": _executable_status("gnina"),
        "vina": _executable_status("vina"),
        "diffdock": check_diffdock_available(),
        "oddt": _package_status("oddt"),
        "admetlab": _package_status("admetlab"),
        "chemprop": chemprop_tool_status(),
        "deepchem": _package_status("deepchem"),
        "aizynthfinder": _package_status("aizynthfinder"),
        "askcos": _package_status("askcos"),
    }


def _select_assessment_molecules(
    db: Session,
    project: Project,
    molecule_ids: list[str] | None,
    max_molecules: int,
) -> list[Molecule]:
    query = db.query(Molecule).filter_by(project_id=project.project_id)
    if molecule_ids:
        query = query.filter(Molecule.molecule_id.in_(molecule_ids))
    else:
        query = query.filter(Molecule.status.in_(ASSESSMENT_ELIGIBLE_STATUSES))
    return query.order_by(Molecule.id.asc()).limit(max_molecules).all()


def _calculate_conformer_result(smiles: str) -> dict[str, Any]:
    try:
        from rdkit import Chem
        from rdkit.Chem import AllChem
    except ImportError:
        return {
            "conformer_generated": False,
            "labels": ["conformer_failed", "rdkit_unavailable"],
            "raw_output": {"reason": "rdkit_unavailable"},
        }

    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return {
            "conformer_generated": False,
            "labels": ["conformer_failed", "invalid_smiles"],
            "raw_output": {"reason": "rdkit_parse_failed"},
        }

    chiral_centers = Chem.FindMolChiralCenters(mol, includeUnassigned=True)
    undefined_stereo_centers = sum(1 for _idx, label in chiral_centers if label == "?")

    mol_h = Chem.AddHs(mol)
    params = AllChem.ETKDGv3()
    params.randomSeed = 61453
    params.useSmallRingTorsions = True
    conformer_ids = list(AllChem.EmbedMultipleConfs(mol_h, numConfs=3, params=params))
    if not conformer_ids:
        return {
            "conformer_generated": False,
            "conformer_count": 0,
            "chiral_centers": len(chiral_centers),
            "undefined_stereo_centers": undefined_stereo_centers,
            "labels": ["conformer_failed"],
            "raw_output": {"reason": "rdkit_etkdg_failed"},
        }

    energies = _optimize_conformers(mol_h, conformer_ids, AllChem)
    lowest_energy = min(energies) if energies else None
    strain_energy = (max(energies) - min(energies)) if len(energies) > 1 else 0.0
    rmsd = _average_conformer_rmsd(mol_h, conformer_ids, AllChem)
    labels = ["conformer_ok"]
    if strain_energy is not None and strain_energy > 25:
        labels.append("high_strain")
    if undefined_stereo_centers:
        labels.append("stereo_undefined")
    if len(chiral_centers) > 5:
        labels.append("too_many_stereocenters")

    return {
        "conformer_generated": True,
        "conformer_count": len(conformer_ids),
        "lowest_energy": _rounded(lowest_energy),
        "strain_energy": _rounded(strain_energy),
        "rmsd_between_conformers": _rounded(rmsd),
        "chiral_centers": len(chiral_centers),
        "undefined_stereo_centers": undefined_stereo_centers,
        "labels": labels,
        "conformer_file": None,
        "raw_output": {
            "adapter_mode": "rdkit_etkdg_conformer",
            "energies": [_rounded(energy) for energy in energies],
            "conformer_ids": [int(conf_id) for conf_id in conformer_ids],
        },
    }


def _optimize_conformers(mol_h: Any, conformer_ids: list[int], all_chem: Any) -> list[float]:
    energies: list[float] = []
    mmff_props = all_chem.MMFFGetMoleculeProperties(mol_h)
    for conf_id in conformer_ids:
        try:
            if mmff_props is not None:
                force_field = all_chem.MMFFGetMoleculeForceField(
                    mol_h,
                    mmff_props,
                    confId=int(conf_id),
                )
            else:
                force_field = all_chem.UFFGetMoleculeForceField(mol_h, confId=int(conf_id))
            if force_field is None:
                continue
            force_field.Minimize(maxIts=200)
            energies.append(float(force_field.CalcEnergy()))
        except Exception:
            continue
    return energies


def _average_conformer_rmsd(mol_h: Any, conformer_ids: list[int], all_chem: Any) -> float | None:
    if len(conformer_ids) < 2:
        return 0.0
    values: list[float] = []
    for index, first_id in enumerate(conformer_ids):
        for second_id in conformer_ids[index + 1 :]:
            try:
                values.append(float(all_chem.GetConformerRMS(mol_h, int(first_id), int(second_id))))
            except Exception:
                continue
    if not values:
        return None
    return sum(values) / len(values)


def _upsert_conformer_result(
    db: Session,
    molecule: Molecule,
    payload: dict[str, Any],
) -> ConformerResult:
    result = db.query(ConformerResult).filter_by(molecule_id=molecule.molecule_id).one_or_none()
    if result is None:
        result = ConformerResult(molecule_id=molecule.molecule_id)
        db.add(result)

    result.conformer_generated = bool(payload.get("conformer_generated"))
    result.conformer_count = payload.get("conformer_count")
    result.lowest_energy = payload.get("lowest_energy")
    result.strain_energy = payload.get("strain_energy")
    result.rmsd_between_conformers = payload.get("rmsd_between_conformers")
    result.chiral_centers = payload.get("chiral_centers")
    result.undefined_stereo_centers = payload.get("undefined_stereo_centers")
    result.labels = payload.get("labels", [])
    result.conformer_file = payload.get("conformer_file")
    result.raw_output = payload.get("raw_output", {})
    return result


def _upsert_docking_result(
    db: Session,
    molecule: Molecule,
    conformer: ConformerResult,
    descriptors: DescriptorSnapshot,
    key_residues: list[str],
) -> DockingResult:
    key_hbond_count = min(
        len(key_residues) or 2,
        max(0, descriptors.hbd + min(descriptors.hba, 2)),
    )
    clash_count = int(
        ("high_strain" in (conformer.labels or []))
        + (1 if descriptors.rotatable_bond_count > 10 else 0)
        + (1 if descriptors.heavy_atom_count > 60 else 0)
    )
    base_score = (
        -4.5
        - 0.08 * descriptors.heavy_atom_count
        - 0.25 * descriptors.aromatic_ring_count
        - 0.12 * min(descriptors.hba, 6)
        - 0.18 * min(descriptors.hbd, 3)
    )
    penalty = max(descriptors.logp - 5.0, 0.0) * 0.25
    penalty += max(descriptors.tpsa - 140.0, 0.0) * 0.01
    penalty += clash_count * 0.35
    vina_score = round(_clamp(base_score + penalty, -12.5, -3.0), 3)
    cnn_score = round(
        _clamp(0.55 + key_hbond_count * 0.08 - clash_count * 0.08 - penalty * 0.04, 0.05, 0.95),
        3,
    )
    ligand_efficiency = vina_score / max(descriptors.heavy_atom_count, 1)

    labels = ["external_docking_adapter_pending", "rdkit_surrogate_docking"]
    labels.append("docking_strong" if vina_score <= -8.0 else "docking_weak")
    labels.append("pose_confident" if cnn_score >= 0.6 else "pose_uncertain")
    labels.append("key_interaction_present" if key_hbond_count else "key_interaction_missing")
    if clash_count:
        labels.append("steric_clash")
    if clash_count >= 2 or cnn_score < 0.4:
        labels.append("bad_pose")
    if ligand_efficiency <= -0.3:
        labels.append("good_ligand_efficiency")

    result = db.query(DockingResult).filter_by(molecule_id=molecule.molecule_id).one_or_none()
    if result is None:
        result = DockingResult(molecule_id=molecule.molecule_id)
        db.add(result)

    result.tool_run_id = None
    result.vina_score = vina_score
    result.cnn_score = cnn_score
    result.key_hbond_count = key_hbond_count
    result.clash_count = clash_count
    result.pose_file = f"db://conformer_results/{molecule.molecule_id}"
    result.labels = labels
    return result


def _upsert_external_docking_result(
    db: Session,
    molecule: Molecule,
    conformer: ConformerResult,
    descriptors: DescriptorSnapshot,
    key_residues: list[str],
    external_result: DockingToolResult,
) -> DockingResult:
    vina_score = external_result.vina_score
    if vina_score is None:
        vina_score = external_result.cnn_affinity
    cnn_score = external_result.cnn_score
    key_hbond_count = min(
        len(key_residues) or 2,
        max(0, descriptors.hbd + min(descriptors.hba, 2)),
    )
    clash_count = int(
        ("high_strain" in (conformer.labels or []))
        + (1 if descriptors.rotatable_bond_count > 10 else 0)
        + (1 if descriptors.heavy_atom_count > 60 else 0)
    )
    labels = list(external_result.labels or [])
    if not labels:
        labels = ["external_docking_adapter_used", f"{external_result.tool_name}_adapter"]
    labels.append(external_result.adapter_mode)
    if vina_score is not None:
        labels.append("docking_strong" if vina_score <= -8.0 else "docking_weak")
        if vina_score / max(descriptors.heavy_atom_count, 1) <= -0.3:
            labels.append("good_ligand_efficiency")
    if cnn_score is not None:
        labels.append("pose_confident" if cnn_score >= 0.6 else "pose_uncertain")
    labels.append("key_interaction_estimated" if key_hbond_count else "key_interaction_missing")
    if clash_count:
        labels.append("steric_clash")

    result = db.query(DockingResult).filter_by(molecule_id=molecule.molecule_id).one_or_none()
    if result is None:
        result = DockingResult(molecule_id=molecule.molecule_id)
        db.add(result)

    result.tool_run_id = external_result.adapter_mode
    result.vina_score = _rounded(vina_score)
    result.cnn_score = _rounded(cnn_score)
    result.key_hbond_count = key_hbond_count
    result.clash_count = clash_count
    result.pose_file = external_result.pose_file
    result.labels = _dedupe(labels)
    return result


def _upsert_admet_result(
    db: Session,
    molecule: Molecule,
    descriptors: DescriptorSnapshot,
    tool_status: dict[str, Any],
) -> ADMETResult:
    catalog_available, catalog_matches = find_rdkit_filter_matches(molecule.smiles)
    alert_penalty = min(len(catalog_matches) * 0.12, 0.36)
    herg_probability = _clamp(
        0.18
        + max(descriptors.logp - 2.5, 0.0) * 0.08
        + descriptors.aromatic_ring_count * 0.06
        + max(descriptors.tpsa - 110, 0.0) * 0.002,
        0.02,
        0.95,
    )
    ames_probability = _clamp(
        0.12 + descriptors.aromatic_ring_count * 0.08 + alert_penalty,
        0.02,
        0.95,
    )
    solubility = _solubility_class(descriptors)
    permeability = _permeability_class(descriptors)
    admet_risk_score = round((herg_probability + ames_probability) / 2, 3)
    herg_risk = _risk_label(herg_probability)
    ames_risk = _risk_label(ames_probability)

    labels = ["external_admet_adapter_pending", "rdkit_surrogate_admet"]
    labels.extend([herg_risk, ames_risk])
    if herg_risk == "high_risk" or ames_risk == "high_risk":
        labels.append("admet_blocker")
    elif herg_risk == "medium_risk" or ames_risk == "medium_risk":
        labels.append("admet_warning")
    else:
        labels.append("admet_clean")

    result = db.query(ADMETResult).filter_by(molecule_id=molecule.molecule_id).one_or_none()
    if result is None:
        result = ADMETResult(molecule_id=molecule.molecule_id)
        db.add(result)

    result.hERG_probability = round(herg_probability, 3)
    result.hERG_risk = herg_risk
    result.Ames_probability = round(ames_probability, 3)
    result.Ames_risk = ames_risk
    result.solubility = solubility
    result.permeability = permeability
    result.admet_risk_score = admet_risk_score
    result.labels = _dedupe(labels)
    result.raw_output = {
        "adapter_mode": "rdkit_surrogate_admet",
        "tool_status": {
            key: tool_status[key]
            for key in ["admetlab", "chemprop", "deepchem", "rdkit"]
            if key in tool_status
        },
        "catalog_available": catalog_available,
        "catalog_matches": [
            {"catalog": match.catalog, "description": match.description}
            for match in catalog_matches
        ],
        "CYP3A4_inhibition": _risk_label_probability(descriptors.logp / 8.0),
        "CYP2D6_inhibition": _risk_label_probability(
            (descriptors.aromatic_ring_count + descriptors.hba) / 12.0
        ),
        "DILI_risk": _risk_label_probability(admet_risk_score * 0.8),
        "Pgp_substrate": _risk_label_probability(
            (descriptors.mw / 700.0) + max(descriptors.logp - 4, 0.0) * 0.08
        ),
        "BBB_penetration": _risk_label_probability(
            0.75 if descriptors.tpsa < 70 and descriptors.logp > 1 else 0.25
        ),
    }
    return result


def _upsert_synthesis_route(
    db: Session,
    molecule: Molecule,
    descriptors: DescriptorSnapshot,
    tool_status: dict[str, Any],
    max_synthesis_steps: int,
    prefer_buyable_building_blocks: bool,
) -> SynthesisRoute:
    sa_score = _sa_score(descriptors)
    sc_score = round(_clamp(sa_score + descriptors.ring_count * 0.2, 1.0, 10.0), 3)
    route_steps = max(1, min(12, int(math.ceil(sa_score))))
    hazardous_reaction_count = int(descriptors.element_counts.get("Br", 0) > 1)
    hazardous_reaction_count += int(descriptors.element_counts.get("I", 0) > 0)
    protecting_group_count = max(0, descriptors.hbd - 2)
    buyable_blocks = max(
        1,
        min(6, descriptors.ring_count + descriptors.hba // 2 + int(prefer_buyable_building_blocks)),
    )
    route_found = sa_score <= 7.0 and route_steps <= max_synthesis_steps
    route_confidence = round(_clamp(1.05 - sa_score / 10.0 - hazardous_reaction_count * 0.08, 0.05, 0.95), 3)

    labels = []
    if sa_score <= 4.5:
        labels.append("easy_to_synthesize")
    elif sa_score <= 6.5:
        labels.append("moderate_synthesis")
    else:
        labels.append("hard_to_synthesize")
    labels.append("route_found" if route_found else "route_not_found")
    if buyable_blocks:
        labels.append("buyable_blocks_available")
    if route_steps > max_synthesis_steps:
        labels.append("too_many_steps")
    if hazardous_reaction_count:
        labels.append("hazardous_route")
    labels.extend(["external_retrosynthesis_adapter_pending", "rdkit_surrogate_synthesis"])

    result = db.query(SynthesisRoute).filter_by(molecule_id=molecule.molecule_id).one_or_none()
    if result is None:
        result = SynthesisRoute(molecule_id=molecule.molecule_id)
        db.add(result)

    result.route_found = route_found
    result.route_steps = route_steps
    result.route_confidence = route_confidence
    result.buyable_building_blocks = buyable_blocks
    result.labels = _dedupe(labels)
    result.route_json = {
        "adapter_mode": "rdkit_surrogate_synthesis",
        "tool_status": {
            key: tool_status[key]
            for key in ["aizynthfinder", "askcos", "rdkit"]
            if key in tool_status
        },
        "SA_score": sa_score,
        "SCScore": sc_score,
        "hazardous_reaction_count": hazardous_reaction_count,
        "protecting_group_count": protecting_group_count,
        "route_summary": _route_summary(route_found, route_steps, buyable_blocks),
    }
    return result


def _descriptor_snapshot(
    smiles: str,
    db: Session,
    molecule: Molecule,
) -> DescriptorSnapshot | None:
    properties = db.query(MoleculeProperty).filter_by(molecule_id=molecule.molecule_id).one_or_none()
    metadata_dict = properties.tool_metadata if properties is not None else None
    metadata_dict = metadata_dict or {}
    if properties is not None and properties.mw is not None:
        return DescriptorSnapshot(
            mw=float(properties.mw),
            logp=float(properties.logp or 0.0),
            tpsa=float(properties.tpsa or 0.0),
            hbd=int(properties.hbd or 0),
            hba=int(properties.hba or 0),
            heavy_atom_count=int(metadata_dict.get("heavy_atom_count") or 0),
            rotatable_bond_count=int(metadata_dict.get("rotatable_bond_count") or 0),
            ring_count=int(metadata_dict.get("ring_count") or 0),
            aromatic_ring_count=int(metadata_dict.get("aromatic_ring_count") or 0),
            chiral_centers=0,
            undefined_stereo_centers=0,
            element_counts=metadata_dict.get("element_counts") or {},
        )

    try:
        from rdkit import Chem
        from rdkit.Chem import Crippen, Descriptors, Lipinski, rdMolDescriptors
    except ImportError:
        return None

    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return None
    chiral_centers = Chem.FindMolChiralCenters(mol, includeUnassigned=True)
    atom_counts: dict[str, int] = {}
    for atom in mol.GetAtoms():
        symbol = atom.GetSymbol()
        atom_counts[symbol] = atom_counts.get(symbol, 0) + 1
    return DescriptorSnapshot(
        mw=float(Descriptors.MolWt(mol)),
        logp=float(Crippen.MolLogP(mol)),
        tpsa=float(rdMolDescriptors.CalcTPSA(mol)),
        hbd=int(Lipinski.NumHDonors(mol)),
        hba=int(Lipinski.NumHAcceptors(mol)),
        heavy_atom_count=int(mol.GetNumHeavyAtoms()),
        rotatable_bond_count=int(Lipinski.NumRotatableBonds(mol)),
        ring_count=int(mol.GetRingInfo().NumRings()),
        aromatic_ring_count=int(rdMolDescriptors.CalcNumAromaticRings(mol)),
        chiral_centers=len(chiral_centers),
        undefined_stereo_centers=sum(1 for _idx, label in chiral_centers if label == "?"),
        element_counts=dict(sorted(atom_counts.items())),
    )


def _update_sa_score(db: Session, molecule: Molecule, sa_score: Any) -> None:
    properties = db.query(MoleculeProperty).filter_by(molecule_id=molecule.molecule_id).one_or_none()
    if properties is not None and sa_score is not None:
        properties.sa_score = float(sa_score)


def _create_agent_run(
    db: Session,
    project: Project,
    agent_name: str,
    adapter_mode: str,
    input_json: dict[str, Any],
    tool_status: dict[str, Any],
) -> AgentRun:
    run = AgentRun(
        agent_run_id=new_id("RUN"),
        project_id=project.project_id,
        agent_name=agent_name,
        model_name="tool-adapter",
        status="running",
        input_json={
            **input_json,
            "adapter_mode": adapter_mode,
            "tool_status": tool_status,
        },
        output_json={},
    )
    db.add(run)
    db.flush()
    return run


def _finish_agent_run(
    agent_run: AgentRun,
    summary: StageSummary,
    tool_status: dict[str, Any],
) -> None:
    agent_run.status = "success"
    agent_run.output_json = {
        **summary.as_dict(),
        "tool_status": tool_status,
    }


def _solubility_class(descriptors: DescriptorSnapshot) -> str:
    if descriptors.logp < 2.0 and descriptors.mw < 350:
        return "high"
    if descriptors.logp < 4.0 and descriptors.mw < 500:
        return "medium"
    return "low"


def _permeability_class(descriptors: DescriptorSnapshot) -> str:
    if descriptors.tpsa <= 90 and 0.5 <= descriptors.logp <= 5.0:
        return "high"
    if descriptors.tpsa <= 140:
        return "medium"
    return "low"


def _risk_label(probability: float) -> str:
    if probability >= 0.66:
        return "high_risk"
    if probability >= 0.33:
        return "medium_risk"
    return "low_risk"


def _risk_label_probability(probability: float) -> dict[str, Any]:
    value = round(_clamp(probability, 0.02, 0.95), 3)
    return {"probability": value, "risk": _risk_label(value)}


def _sa_score(descriptors: DescriptorSnapshot) -> float:
    hetero_atom_count = sum(
        count
        for element, count in descriptors.element_counts.items()
        if element not in {"C", "H"}
    )
    score = 1.0
    score += descriptors.heavy_atom_count * 0.055
    score += descriptors.ring_count * 0.35
    score += descriptors.chiral_centers * 0.45
    score += hetero_atom_count * 0.08
    score += max(descriptors.rotatable_bond_count - 6, 0) * 0.12
    score += max(descriptors.mw - 500, 0) * 0.006
    score -= min(descriptors.aromatic_ring_count, 3) * 0.12
    return round(_clamp(score, 1.0, 10.0), 3)


def _route_summary(route_found: bool, route_steps: int, buyable_blocks: int) -> str:
    if route_found:
        return f"Surrogate route found in {route_steps} steps with {buyable_blocks} buyable blocks."
    return (
        f"No confident surrogate route within step budget; estimated {route_steps} steps "
        f"and {buyable_blocks} buyable blocks."
    )


def _binding_site_docking_config(
    db: Session,
    project: Project,
    binding_site_id: str | None,
) -> dict[str, Any]:
    if not binding_site_id:
        return {}
    site = db.query(BindingSite).filter_by(binding_site_id=binding_site_id).one_or_none()
    if site is None:
        return {}
    if site.project_id and site.project_id != project.project_id:
        return {}
    if not site.project_id and site.target_id != project.target_id:
        return {}

    grid_box = site.grid_box or {}
    receptor_reference = (
        site.prepared_receptor_file
        or site.receptor_file
        or grid_box.get("prepared_receptor_file")
        or grid_box.get("receptor_file")
    )
    protein_file = resolve_receptor_path(receptor_reference)
    return {
        "protein_file": protein_file,
        "grid_center": grid_box.get("center") or grid_box.get("grid_center"),
        "grid_size": grid_box.get("size") or grid_box.get("grid_size"),
        "key_residues": site.key_residues or [],
    }


def _attempt_external_docking(
    project: Project,
    molecule: Molecule,
    tool_status: dict[str, Any],
    protein_file: str | None,
    prepared_ligand_files: dict[str, str],
    grid_center: list[float] | None,
    grid_size: list[float] | None,
) -> DockingToolResult | None:
    if not _external_docking_ready(tool_status, protein_file, grid_center, grid_size):
        return None
    assert protein_file is not None
    ligand_file = prepared_ligand_files.get(molecule.molecule_id)
    if ligand_file and not Path(ligand_file).exists():
        return DockingToolResult(
            adapter_mode="external_docking_unavailable",
            tool_name="external_docking",
            success=False,
            labels=["external_docking_adapter_failed"],
            warnings=["prepared_ligand_file_not_found"],
        )
    if not ligand_file:
        ligand_file = _write_ligand_sdf(project, molecule)
    if ligand_file is None:
        return DockingToolResult(
            adapter_mode="external_docking_unavailable",
            tool_name="external_docking",
            success=False,
            labels=["external_docking_adapter_failed"],
            warnings=["ligand_sdf_generation_failed"],
        )
    request = DockingToolRequest(
        receptor_file=protein_file,
        ligand_file=ligand_file,
        output_dir=str(ASSESSMENT_RUNTIME_ROOT / _safe_path_part(project.project_id) / "poses"),
        grid_center=grid_center,
        grid_size=grid_size,
        molecule_id=molecule.molecule_id,
    )
    external_result = run_external_docking(request, tool_status)
    if external_result is None:
        selected_tool = select_docking_tool(request, tool_status)
        warning = "external_docking_adapter_unavailable_for_inputs"
        if selected_tool is None and tool_status.get("vina", {}).get("available"):
            warning = "vina_requires_prepared_pdbqt_inputs"
        return DockingToolResult(
            adapter_mode="external_docking_unavailable",
            tool_name="external_docking",
            success=False,
            labels=["external_docking_adapter_failed"],
            warnings=[warning],
        )
    return external_result


def _external_docking_setup_warnings(
    tool_status: dict[str, Any],
    protein_file: str | None,
    prepared_ligand_files: dict[str, str],
    grid_center: list[float] | None,
    grid_size: list[float] | None,
) -> list[str]:
    if not _external_docking_available(tool_status):
        return ["external_docking_tools_not_installed"]

    warnings: list[str] = []
    if not protein_file:
        warnings.append("protein_file_required_for_external_docking")
    elif not Path(protein_file).exists():
        warnings.append("protein_file_not_found")
    if not _is_vector3(grid_center) or not _is_vector3(grid_size):
        warnings.append("grid_center_and_grid_size_required_for_external_docking")
    if (
        tool_status.get("vina", {}).get("available")
        and not tool_status.get("gnina", {}).get("available")
        and not prepared_ligand_files
    ):
        warnings.append("vina_requires_prepared_pdbqt_inputs")
    return warnings


def _external_docking_ready(
    tool_status: dict[str, Any],
    protein_file: str | None,
    grid_center: list[float] | None,
    grid_size: list[float] | None,
) -> bool:
    return bool(
        _external_docking_available(tool_status)
        and protein_file
        and Path(protein_file).exists()
        and _is_vector3(grid_center)
        and _is_vector3(grid_size)
    )


def _write_ligand_sdf(project: Project, molecule: Molecule) -> str | None:
    try:
        from rdkit import Chem
        from rdkit.Chem import AllChem
    except ImportError:
        return None

    try:
        mol = Chem.MolFromSmiles(molecule.smiles)
        if mol is None:
            return None
        mol_h = Chem.AddHs(mol)
        params = AllChem.ETKDGv3()
        params.randomSeed = 61453
        if AllChem.EmbedMolecule(mol_h, params) != 0:
            return None
        try:
            AllChem.MMFFOptimizeMolecule(mol_h, maxIters=200)
        except Exception:
            AllChem.UFFOptimizeMolecule(mol_h, maxIters=200)

        output_dir = ASSESSMENT_RUNTIME_ROOT / _safe_path_part(project.project_id) / "ligands"
        output_dir.mkdir(parents=True, exist_ok=True)
        ligand_file = output_dir / f"{_safe_path_part(molecule.molecule_id)}.sdf"
        writer = Chem.SDWriter(str(ligand_file))
        try:
            writer.write(mol_h)
        finally:
            writer.close()
        return str(ligand_file)
    except Exception:
        return None


def _is_vector3(values: list[float] | None) -> bool:
    return values is not None and len(values) == 3


def _safe_path_part(value: str) -> str:
    safe = "".join(char if char.isalnum() or char in "._-" else "_" for char in value)
    return safe.strip("._") or "item"


def _external_docking_available(tool_status: dict[str, Any]) -> bool:
    return bool(
        tool_status["gnina"]["available"]
        or tool_status["vina"]["available"]
        or tool_status["diffdock"]["available"]
    )


def _external_admet_available(tool_status: dict[str, Any]) -> bool:
    return bool(
        tool_status["admetlab"]["available"]
        or tool_status["chemprop"]["available"]
        or tool_status["deepchem"]["available"]
    )


def _external_synthesis_available(tool_status: dict[str, Any]) -> bool:
    return bool(tool_status["aizynthfinder"]["available"] or tool_status["askcos"]["available"])


def _package_status(package_name: str) -> dict[str, Any]:
    available = util.find_spec(package_name) is not None
    version = None
    if available:
        try:
            version = metadata.version(package_name)
        except metadata.PackageNotFoundError:
            version = None
    return {"available": available, "version": version}


def _executable_status(command: str) -> dict[str, Any]:
    path = shutil.which(command)
    return {"available": path is not None, "path": path}


def _rounded(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 3)


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _dedupe(labels: list[str]) -> list[str]:
    deduped: list[str] = []
    for label in labels:
        if label not in deduped:
            deduped.append(label)
    return deduped
