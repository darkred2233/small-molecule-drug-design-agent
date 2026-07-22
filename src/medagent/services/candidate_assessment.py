import math
import os
import shutil
import copy
import hashlib
import subprocess
import tempfile
from dataclasses import dataclass, field, replace
from importlib import metadata, util
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from medagent.db.models import (
    ADMETResult,
    AgentRun,
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
from medagent.services.aizynthfinder_adapter import (
    AiZynthFinderRequest,
    AiZynthFinderResult,
    aizynthfinder_tool_status,
    run_aizynthfinder_retrosynthesis,
)
from medagent.services.candidate_ranking import generate_project_rankings
from medagent.services.docking_adapters import (
    DockingToolRequest,
    DockingToolResult,
    check_gnina_available,
    check_vina_available,
    run_external_docking,
    select_docking_tool,
)
from medagent.services.docking_workflow import (
    prepare_ligand_from_smiles,
)
from medagent.services.ids import new_id
from medagent.services.molecule_validation import merge_labels
from medagent.services.pose_interactions import analyze_pose_interactions
from medagent.services.pdbqt_validation import (
    is_valid_vina_ligand_pdbqt,
    is_valid_vina_receptor_pdbqt,
)
from medagent.services.rdkit_adapter import find_rdkit_filter_matches
from medagent.services.receptor_preparation import project_docking_config, resolve_receptor_path


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
ASSESSMENT_STATUS_LABELS = {
    "assessment_passed",
    "assessment_failed",
    "assessment_bad_pose",
    "assessment_conformer_failed",
    "assessment_admet_blocker",
    "assessment_route_not_found",
}
ASSESSMENT_MODES = {"fast", "external", "full"}
ASSESSMENT_RUNTIME_ROOT = Path(".local") / "candidate_assessment"
COARSE_SCREEN_LABELS = {
    "coarse_screen_passed",
    "coarse_screen_failed",
    "coarse_only_candidate",
    "externally_refined_candidate",
    "external_refinement_attempted",
    "rejected_by_coarse_screen",
}
DOCKING_RESULT_LABELS = {
    "external_docking_adapter_pending",
    "external_docking_adapter_used",
    "external_docking_adapter_failed",
    "external_docking_fallback_used",
    "external_docking_setup_incomplete",
    "external_docking_receptor_missing",
    "external_docking_grid_missing",
    "external_docking_tools_unavailable",
    "rdkit_surrogate_docking",
    "gnina_adapter",
    "vina_adapter",
    "diffdock_adapter",
    "gnina_external_docking",
    "gnina_docker_docking",
    "vina_external_docking",
    "vina_docker_docking",
    "diffdock_external_docking",
    "diffdock_docker_docking",
    "docking_strong",
    "docking_weak",
    "pose_confident",
    "pose_uncertain",
    "key_interaction_present",
    "key_interaction_estimated",
    "key_interaction_missing",
    "good_ligand_efficiency",
    "steric_clash",
    "bad_pose",
}
ADMET_RESULT_LABELS = {
    "external_admet_adapter_pending",
    "external_admet_adapter_used",
    "external_admet_adapter_failed",
    "external_admet_fallback_used",
    "rdkit_surrogate_admet",
    "chemprop_predicted",
    "chemprop_admet",
    "admet_ai_predicted",
    "low_risk",
    "medium_risk",
    "high_risk",
    "admet_clean",
    "admet_warning",
    "admet_blocker",
}
SYNTHESIS_RESULT_LABELS = {
    "external_retrosynthesis_adapter_pending",
    "external_retrosynthesis_adapter_used",
    "external_retrosynthesis_adapter_failed",
    "external_retrosynthesis_fallback_used",
    "rdkit_surrogate_synthesis",
    "aizynthfinder_adapter",
    "askcos_adapter",
    "aizynthfinder_executed",
    "aizynthfinder_route",
    "easy_to_synthesize",
    "moderate_synthesis",
    "hard_to_synthesize",
    "route_found",
    "route_not_found",
    "buyable_blocks_available",
    "too_many_steps",
    "hazardous_route",
}
DEFAULT_ADMET_AI_CPU_MAX_MOLECULES = 5


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
    round_id: str | None = None
    execution_mode: str = "not_run"
    external_tools_requested: bool = False
    external_tools_enabled: bool = False
    external_attempted_count: int = 0
    external_success_count: int = 0
    surrogate_count: int = 0
    fallback_count: int = 0
    fallback_used: bool = False

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
            "round_id": self.round_id,
            "execution_mode": self.execution_mode,
            "external_tools_requested": self.external_tools_requested,
            "external_tools_enabled": self.external_tools_enabled,
            "external_attempted_count": self.external_attempted_count,
            "external_success_count": self.external_success_count,
            "surrogate_count": self.surrogate_count,
            "fallback_count": self.fallback_count,
            "fallback_used": self.fallback_used,
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
    top_n: int | None = None,
    assessment_mode: str = "external",
    external_top_n: int = 10,
    binding_site_id: str | None = None,
    protein_file: str | None = None,
    prepared_ligand_files: dict[str, str] | None = None,
    grid_center: list[float] | None = None,
    grid_size: list[float] | None = None,
    key_residues: list[str] | None = None,
    admet_properties: list[str] | None = None,
    max_synthesis_steps: int = 5,
    prefer_buyable_building_blocks: bool = True,
    enable_external_synthesis_routes: bool = True,
    skip_docking: bool = False,
    skip_admet: bool = False,
    skip_synthesis: bool = False,
    skip_ranking: bool = False,
    round_id: str | None = None,
) -> dict[str, Any]:
    assessment_mode = _normalize_assessment_mode(assessment_mode)
    molecules = _select_assessment_molecules(db, project, molecule_ids, max_molecules, round_id)
    tool_status = candidate_assessment_tool_status()
    ranking_top_n = top_n or max_molecules
    conformer = generate_project_conformers(db, project, molecules, tool_status, round_id=round_id)
    docking = (
        _skipped_stage_summary(molecules, "docking", round_id)
        if skip_docking
        else run_project_docking(
            db,
            project,
            molecules,
            tool_status,
            allow_external_tools=False,
            binding_site_id=binding_site_id,
            protein_file=protein_file,
            prepared_ligand_files=prepared_ligand_files,
            grid_center=grid_center,
            grid_size=grid_size,
            key_residues=key_residues or [],
            round_id=round_id,
        )
    )
    admet = (
        _skipped_stage_summary(molecules, "admet", round_id)
        if skip_admet
        else run_project_admet(
            db,
            project,
            molecules,
            tool_status,
            allow_external_tools=False,
            admet_properties=admet_properties or [],
            round_id=round_id,
        )
    )
    synthesis = (
        _skipped_stage_summary(molecules, "synthesis", round_id)
        if skip_synthesis
        else run_project_synthesis(
            db,
            project,
            molecules,
            tool_status,
            allow_external_tools=False,
            max_synthesis_steps=max_synthesis_steps,
            prefer_buyable_building_blocks=prefer_buyable_building_blocks,
            round_id=round_id,
        )
    )
    coarse_screen = _apply_coarse_screen_labels(db, molecules, round_id=round_id)
    ranking = _skipped_ranking_summary(molecules, ranking_top_n, round_id=round_id) if skip_ranking else generate_project_rankings(
        db,
        project,
        molecules=molecules,
        max_molecules=max_molecules,
        top_n=ranking_top_n,
        tool_status=tool_status,
        round_id=round_id,
    )
    if assessment_mode in {"external", "full"}:
        coarse_passed_ids = set(coarse_screen["passed_molecule_ids"])
        coarse_passed_molecules = [
            molecule
            for molecule in molecules
            if molecule.molecule_id in coarse_passed_ids
        ]
        refinement_molecules = _top_ranked_molecules_for_external_refinement(
            coarse_passed_molecules,
            ranking,
            external_top_n=external_top_n if assessment_mode == "external" else len(coarse_passed_molecules),
        )
        if not skip_docking:
            _mark_coarse_screen_summary(docking, coarse_screen, assessment_mode, len(refinement_molecules))
        if not skip_admet:
            _mark_coarse_screen_summary(admet, coarse_screen, assessment_mode, len(refinement_molecules))
        if not skip_synthesis:
            _mark_coarse_screen_summary(synthesis, coarse_screen, assessment_mode, len(refinement_molecules))
        if refinement_molecules:
            docking_refinement = None
            if not skip_docking:
                docking_refinement = run_project_docking(
                    db,
                    project,
                    refinement_molecules,
                    tool_status,
                    allow_external_tools=True,
                    binding_site_id=binding_site_id,
                    protein_file=protein_file,
                    prepared_ligand_files=prepared_ligand_files,
                    grid_center=grid_center,
                    grid_size=grid_size,
                    key_residues=key_residues or [],
                    round_id=round_id,
                )
            admet_refinement = None
            if not skip_admet:
                admet_refinement = run_project_admet(
                    db,
                    project,
                    refinement_molecules,
                    tool_status,
                    allow_external_tools=True,
                    admet_properties=admet_properties or [],
                    round_id=round_id,
                )
            synthesis_refinement = None
            if not skip_synthesis and enable_external_synthesis_routes:
                synthesis_refinement = run_project_synthesis(
                    db,
                    project,
                    refinement_molecules,
                    tool_status,
                    allow_external_tools=True,
                    max_synthesis_steps=max_synthesis_steps,
                    prefer_buyable_building_blocks=prefer_buyable_building_blocks,
                    round_id=round_id,
                )
            elif not skip_synthesis:
                synthesis.warnings = _dedupe(
                    synthesis.warnings
                    + ["external_retrosynthesis_skipped_by_synthesis_route_scope"]
                )
            _apply_external_refinement_labels(db, coarse_passed_molecules, refinement_molecules, round_id=round_id)
            refinement_scope = "top_n" if assessment_mode == "external" else "full"
            if docking_refinement is not None:
                _mark_external_refinement_summary(docking, docking_refinement, refinement_scope=refinement_scope)
            if admet_refinement is not None:
                _mark_external_refinement_summary(admet, admet_refinement, refinement_scope=refinement_scope)
            if synthesis_refinement is not None:
                _mark_external_refinement_summary(
                    synthesis,
                    synthesis_refinement,
                    refinement_scope=refinement_scope,
                )
            if not skip_ranking:
                ranking = generate_project_rankings(
                    db,
                    project,
                    molecules=molecules,
                    max_molecules=max_molecules,
                    top_n=ranking_top_n,
                    tool_status=tool_status,
                    round_id=round_id,
                )
    project.status = "candidate_assessed"
    db.commit()
    return {
        "project_id": project.project_id,
        "round_id": round_id,
        "assessment_mode": assessment_mode,
        "external_top_n": external_top_n,
        "external_synthesis_routes_enabled": enable_external_synthesis_routes,
        "skipped_stages": [
            stage
            for stage, skipped in (
                ("docking", skip_docking),
                ("admet", skip_admet),
                ("synthesis", skip_synthesis),
            )
            if skipped
        ],
        "ranking_skipped": skip_ranking,
        "runtime_policy": _assessment_runtime_policy(
            assessment_mode=assessment_mode,
            external_top_n=external_top_n,
            enable_external_synthesis_routes=enable_external_synthesis_routes,
        ),
        "conformer": conformer.as_dict(),
        "docking": docking.as_dict(),
        "admet": admet.as_dict(),
        "synthesis": synthesis.as_dict(),
        "ranking": ranking.as_dict(),
        "coarse_screen": coarse_screen,
        "tool_status": tool_status,
    }


def generate_project_conformers(
    db: Session,
    project: Project,
    molecules: list[Molecule],
    tool_status: dict[str, Any] | None = None,
    round_id: str | None = None,
) -> StageSummary:
    tool_status = tool_status or candidate_assessment_tool_status()
    agent_run = _create_agent_run(
        db,
        project,
        CONFORMER_AGENT_NAME,
        "rdkit_etkdg_conformer",
        {"molecule_ids": [molecule.molecule_id for molecule in molecules]},
        tool_status,
        round_id=round_id,
    )
    summary = StageSummary(
        agent_run_id=agent_run.agent_run_id,
        adapter_mode="rdkit_etkdg_conformer",
        requested_count=len(molecules),
        round_id=round_id,
        execution_mode="local_tool",
    )
    _update_agent_run_progress(
        db,
        agent_run,
        summary,
        phase="running",
        message="正在用 RDKit 生成候选分子构象。",
        completed_count=0,
    )

    for index, molecule in enumerate(molecules, start=1):
        _update_agent_run_progress(
            db,
            agent_run,
            summary,
            phase="running",
            message=f"正在生成构象 {index}/{len(molecules)}。",
            completed_count=index - 1,
            current_molecule_id=molecule.molecule_id,
        )
        result = _calculate_conformer_result(molecule.smiles)
        conformer = _upsert_conformer_result(db, molecule, result, round_id=round_id)
        molecule.labels = merge_labels(molecule.labels, conformer.labels)
        if conformer.conformer_generated:
            summary.generated_count += 1
            summary.evaluated_count += 1
            summary.molecule_ids.append(molecule.molecule_id)
        else:
            summary.failed_count += 1
            summary.failed_molecule_ids.append(molecule.molecule_id)
        _update_agent_run_progress(
            db,
            agent_run,
            summary,
            phase="running",
            message=f"已完成构象 {index}/{len(molecules)}。",
            completed_count=index,
            current_molecule_id=molecule.molecule_id,
        )

    _finish_agent_run(agent_run, summary, tool_status)
    db.commit()
    return summary


def run_project_docking(
    db: Session,
    project: Project,
    molecules: list[Molecule],
    tool_status: dict[str, Any] | None = None,
    allow_external_tools: bool = True,
    binding_site_id: str | None = None,
    protein_file: str | None = None,
    prepared_ligand_files: dict[str, str] | None = None,
    grid_center: list[float] | None = None,
    grid_size: list[float] | None = None,
    key_residues: list[str] | None = None,
    round_id: str | None = None,
) -> StageSummary:
    tool_status = tool_status or candidate_assessment_tool_status()
    key_residues = key_residues or []
    site_config = _binding_site_docking_config(db, project, binding_site_id)
    if site_config:
        binding_site_id = binding_site_id or site_config.get("binding_site_id")
        if not protein_file:
            protein_file = (
                site_config.get("raw_receptor_file")
                if _gnina_gpu_docking_available(tool_status)
                else site_config.get("prepared_receptor_file")
            ) or site_config.get("protein_file")
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
        round_id=round_id,
    )
    external_ready = allow_external_tools and _external_docking_ready(
        tool_status,
        protein_file,
        grid_center,
        grid_size,
    )
    summary = StageSummary(
        agent_run_id=agent_run.agent_run_id,
        adapter_mode="rdkit_surrogate_docking",
        requested_count=len(molecules),
        round_id=round_id,
        execution_mode="surrogate_only",
        external_tools_requested=allow_external_tools,
        external_tools_enabled=bool(external_ready),
        warnings=_external_docking_setup_warnings(
            tool_status,
            protein_file=protein_file,
            prepared_ligand_files=prepared_ligand_files or {},
            grid_center=grid_center,
            grid_size=grid_size,
        ),
    )
    if not allow_external_tools:
        summary.warnings = ["external_docking_skipped_by_assessment_mode"]
    external_adapter_modes: set[str] = set()
    _update_agent_run_progress(
        db,
        agent_run,
        summary,
        phase="running",
        message=(
            "正在运行外部对接细筛。"
            if allow_external_tools
            else "正在运行 RDKit 替代对接粗筛。"
        ),
        completed_count=0,
        extra={"external_tools_enabled": allow_external_tools},
    )

    for index, molecule in enumerate(molecules, start=1):
        _update_agent_run_progress(
            db,
            agent_run,
            summary,
            phase="running",
            message=f"正在处理对接 {index}/{len(molecules)}。",
            completed_count=index - 1,
            current_molecule_id=molecule.molecule_id,
            extra={"external_tools_enabled": allow_external_tools},
        )
        conformer = db.query(ConformerResult).filter_by(molecule_id=molecule.molecule_id).one_or_none()
        if conformer is None or not conformer.conformer_generated:
            summary.skipped_count += 1
            summary.skipped_molecule_ids.append(molecule.molecule_id)
            _update_agent_run_progress(
                db,
                agent_run,
                summary,
                phase="running",
                message=f"已跳过对接 {index}/{len(molecules)}：缺少可用构象。",
                completed_count=index,
                current_molecule_id=molecule.molecule_id,
                extra={"external_tools_enabled": allow_external_tools},
            )
            continue

        descriptors = _descriptor_snapshot(molecule.smiles, db, molecule)
        if descriptors is None:
            summary.failed_count += 1
            summary.failed_molecule_ids.append(molecule.molecule_id)
            _update_agent_run_progress(
                db,
                agent_run,
                summary,
                phase="running",
                message=f"对接 {index}/{len(molecules)} 失败：缺少描述符。",
                completed_count=index,
                current_molecule_id=molecule.molecule_id,
                extra={"external_tools_enabled": allow_external_tools},
            )
            continue

        external_result = None
        if allow_external_tools:
            if external_ready:
                summary.external_attempted_count += 1
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
                receptor_file=protein_file,
                round_id=round_id,
            )
            external_adapter_modes.add(external_result.adapter_mode)
            summary.external_success_count += 1
        else:
            if external_result is not None and external_result.warnings:
                summary.warnings = _dedupe(summary.warnings + external_result.warnings)
            docking = _upsert_docking_result(
                db,
                molecule,
                conformer,
                descriptors,
                key_residues=key_residues,
                fallback_warnings=summary.warnings if allow_external_tools else [],
                external_tools_requested=allow_external_tools,
                round_id=round_id,
            )
            summary.surrogate_count += 1
            if allow_external_tools:
                summary.fallback_count += 1
        molecule.labels = _replace_result_labels(molecule.labels, DOCKING_RESULT_LABELS, docking.labels)
        summary.evaluated_count += 1
        summary.generated_count += 1
        summary.molecule_ids.append(molecule.molecule_id)
        _update_agent_run_progress(
            db,
            agent_run,
            summary,
            phase="running",
            message=f"已完成对接 {index}/{len(molecules)}。",
            completed_count=index,
            current_molecule_id=molecule.molecule_id,
            extra={"external_tools_enabled": allow_external_tools},
        )

    if len(external_adapter_modes) == 1:
        summary.adapter_mode = next(iter(external_adapter_modes))
    elif len(external_adapter_modes) > 1:
        summary.adapter_mode = "external_docking_with_rdkit_fallback"
    _finalize_stage_execution_mode(summary, surrogate_mode="rdkit_surrogate_docking")

    _finish_agent_run(agent_run, summary, tool_status)
    db.commit()
    return summary


def run_project_admet(
    db: Session,
    project: Project,
    molecules: list[Molecule],
    tool_status: dict[str, Any] | None = None,
    allow_external_tools: bool = True,
    admet_properties: list[str] | None = None,
    round_id: str | None = None,
) -> StageSummary:
    tool_status = tool_status or candidate_assessment_tool_status()

    external_admet_skip_warning = (
        _external_admet_skip_warning(tool_status, len(molecules))
        if allow_external_tools
        else None
    )
    chemprop_available = (
        allow_external_tools
        and tool_status.get("chemprop", {}).get("available", False)
        and external_admet_skip_warning is None
    )
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
        round_id=round_id,
    )
    summary = StageSummary(
        agent_run_id=agent_run.agent_run_id,
        adapter_mode=adapter_mode,
        requested_count=len(molecules),
        round_id=round_id,
        execution_mode="external_tool" if chemprop_available else "surrogate_only",
        external_tools_requested=allow_external_tools,
        external_tools_enabled=bool(chemprop_available),
        warnings=[],
    )
    _update_agent_run_progress(
        db,
        agent_run,
        summary,
        phase="running",
        message=(
            "正在运行 Chemprop/ADMET 外部预测。"
            if chemprop_available
            else "正在运行 RDKit 替代 ADMET 粗筛。"
        ),
        completed_count=0,
        extra={"external_tools_enabled": chemprop_available},
    )

    if chemprop_available:
        # Use Chemprop for real ADMET predictions
        summary.external_attempted_count = len(molecules)
        try:
            chemprop_result = _run_chemprop_for_project(
                db,
                molecules,
                tool_status,
                admet_properties,
            )
        except Exception as exc:
            chemprop_result = ChempropADMETOutput(
                adapter_mode="chemprop_adapter_exception",
                tool_name="chemprop",
                success=False,
                warnings=[
                    f"chemprop_external_adapter_exception:{type(exc).__name__}",
                    "use_rdkit_surrogate_fallback",
                ],
            )
        summary.adapter_mode = chemprop_result.adapter_mode
        summary.generated_count = len(chemprop_result.results)
        summary.evaluated_count = len(chemprop_result.results)
        summary.molecule_ids = [r.molecule_id for r in chemprop_result.results]
        summary.warnings.extend(chemprop_result.warnings)
        if chemprop_result.success:
            summary.external_success_count = len(chemprop_result.results)

        # Process Chemprop results
        for index, single_result in enumerate(chemprop_result.results, start=1):
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
                adapter_output=chemprop_result,
                tool_status=tool_status.get("chemprop", {}),
                round_id=round_id,
            )
            molecule.labels = _replace_result_labels(molecule.labels, ADMET_RESULT_LABELS, admet.labels)
            _update_agent_run_progress(
                db,
                agent_run,
                summary,
                phase="running",
                message=f"已完成 ADMET 预测 {index}/{len(molecules)}。",
                completed_count=min(index, len(molecules)),
                current_molecule_id=molecule.molecule_id,
                extra={"external_tools_enabled": chemprop_available},
            )

        # Fallback to RDKit surrogate for molecules without Chemprop results
        chemprop_ids = {r.molecule_id for r in chemprop_result.results}
        fallback_count = 0
        for index, molecule in enumerate(molecules, start=1):
            if molecule.molecule_id not in chemprop_ids:
                descriptors = _descriptor_snapshot(molecule.smiles, db, molecule)
                if descriptors is None:
                    summary.failed_count += 1
                    summary.failed_molecule_ids.append(molecule.molecule_id)
                    continue
                admet = _upsert_admet_result(
                    db,
                    molecule,
                    descriptors,
                    tool_status,
                    external_tools_requested=True,
                    fallback_warnings=summary.warnings,
                    round_id=round_id,
                )
                molecule.labels = _replace_result_labels(molecule.labels, ADMET_RESULT_LABELS, admet.labels)
                summary.evaluated_count += 1
                summary.generated_count += 1
                summary.molecule_ids.append(molecule.molecule_id)
                fallback_count += 1
                summary.surrogate_count += 1
            _update_agent_run_progress(
                db,
                agent_run,
                summary,
                phase="running",
                message=f"已完成 ADMET 预测 {index}/{len(molecules)}。",
                completed_count=index,
                current_molecule_id=molecule.molecule_id,
                extra={"external_tools_enabled": chemprop_available},
            )

        if fallback_count:
            summary.fallback_count += fallback_count
            if chemprop_ids:
                summary.adapter_mode = "chemprop_with_rdkit_surrogate_admet"
                summary.warnings.append("chemprop_partial_fallback_to_rdkit")
            else:
                summary.adapter_mode = "rdkit_surrogate_admet"
                summary.warnings.append("chemprop_model_unavailable_using_rdkit_surrogate")
    else:
        # RDKit surrogate fallback
        if allow_external_tools:
            summary.warnings.append(
                external_admet_skip_warning or "external_admet_tools_not_installed"
            )
        else:
            summary.warnings.append("external_admet_skipped_by_assessment_mode")
        for index, molecule in enumerate(molecules, start=1):
            _update_agent_run_progress(
                db,
                agent_run,
                summary,
                phase="running",
                message=f"正在处理 ADMET {index}/{len(molecules)}。",
                completed_count=index - 1,
                current_molecule_id=molecule.molecule_id,
                extra={"external_tools_enabled": False},
            )
            descriptors = _descriptor_snapshot(molecule.smiles, db, molecule)
            if descriptors is None:
                summary.failed_count += 1
                summary.failed_molecule_ids.append(molecule.molecule_id)
                _update_agent_run_progress(
                    db,
                    agent_run,
                    summary,
                    phase="running",
                    message=f"ADMET {index}/{len(molecules)} 失败：缺少描述符。",
                    completed_count=index,
                    current_molecule_id=molecule.molecule_id,
                    extra={"external_tools_enabled": False},
                )
                continue

            admet = _upsert_admet_result(
                db,
                molecule,
                descriptors,
                tool_status,
                external_tools_requested=allow_external_tools,
                fallback_warnings=summary.warnings if allow_external_tools else [],
                round_id=round_id,
            )
            molecule.labels = _replace_result_labels(molecule.labels, ADMET_RESULT_LABELS, admet.labels)
            summary.evaluated_count += 1
            summary.generated_count += 1
            summary.molecule_ids.append(molecule.molecule_id)
            summary.surrogate_count += 1
            if allow_external_tools:
                summary.fallback_count += 1
            _update_agent_run_progress(
                db,
                agent_run,
                summary,
                phase="running",
                message=f"已完成 ADMET {index}/{len(molecules)}。",
                completed_count=index,
                current_molecule_id=molecule.molecule_id,
                extra={"external_tools_enabled": False},
            )

    _finalize_stage_execution_mode(summary, surrogate_mode="rdkit_surrogate_admet")
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
    adapter_output: ChempropADMETOutput | None = None,
    tool_status: dict[str, Any] | None = None,
    round_id: str | None = None,
) -> ADMETResult:
    """Create or update ADMET result from Chemprop prediction."""
    result = (
        db.query(ADMETResult)
        .filter_by(molecule_id=molecule.molecule_id, round_id=round_id)
        .one_or_none()
    )
    if result is None:
        result = ADMETResult(molecule_id=molecule.molecule_id, round_id=round_id)
        db.add(result)

    result.hERG_probability = chemprop_result.hERG_probability
    result.hERG_risk = chemprop_result.hERG_risk
    result.Ames_probability = chemprop_result.Ames_probability
    result.Ames_risk = chemprop_result.Ames_risk
    result.solubility = chemprop_result.solubility
    result.permeability = chemprop_result.permeability
    result.admet_risk_score = chemprop_result.admet_risk_score
    result.labels = _dedupe(
        [
            "external_admet_adapter_used",
            *chemprop_result.labels,
            adapter_mode,
        ]
    )
    tool_status = tool_status or {}
    tool_name = adapter_output.tool_name if adapter_output is not None else "chemprop"
    result.raw_output = {
        "adapter_mode": adapter_mode,
        "tool_name": tool_name,
        "tool_version": tool_status.get("version"),
        "model_name": (
            "ADMET-AI bundled Chemprop ensemble"
            if tool_status.get("mode") == "admet_ai"
            else tool_status.get("model_name")
        ),
        "model_count": tool_status.get("model_count"),
        "compute_device": (
            adapter_output.compute_device
            if adapter_output is not None
            else tool_status.get("device")
        ),
        "input_hash": _smiles_input_hash(molecule.smiles),
        "status": "success",
        "execution_mode": "external_tool",
        "evidence_tier": "predictive_model",
        "external_tool_requested": True,
        "external_tool_used": True,
        "surrogate_used": False,
        "fallback_used": False,
        "result_kind": "model_prediction",
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
    allow_external_tools: bool = True,
    max_synthesis_steps: int = 5,
    prefer_buyable_building_blocks: bool = True,
    round_id: str | None = None,
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
        round_id=round_id,
    )
    external_available = allow_external_tools and _external_synthesis_available(tool_status)
    summary = StageSummary(
        agent_run_id=agent_run.agent_run_id,
        adapter_mode="rdkit_surrogate_synthesis",
        requested_count=len(molecules),
        round_id=round_id,
        execution_mode="surrogate_only",
        external_tools_requested=allow_external_tools,
        external_tools_enabled=bool(external_available),
        warnings=["external_retrosynthesis_tools_not_installed"]
        if allow_external_tools and not _external_synthesis_available(tool_status)
        else [],
    )
    if not allow_external_tools:
        summary.warnings = ["external_retrosynthesis_skipped_by_assessment_mode"]
    external_adapter_modes: set[str] = set()
    fallback_count = 0
    _update_agent_run_progress(
        db,
        agent_run,
        summary,
        phase="running",
        message=(
            "正在运行 AiZynthFinder 外部逆合成细筛。"
            if allow_external_tools
            else "正在运行 RDKit 替代合成可行性粗筛。"
        ),
        completed_count=0,
        extra={"external_tools_enabled": allow_external_tools},
    )

    for index, molecule in enumerate(molecules, start=1):
        _update_agent_run_progress(
            db,
            agent_run,
            summary,
            phase="running",
            message=f"正在处理合成可行性 {index}/{len(molecules)}。",
            completed_count=index - 1,
            current_molecule_id=molecule.molecule_id,
            extra={"external_tools_enabled": allow_external_tools},
        )
        descriptors = _descriptor_snapshot(molecule.smiles, db, molecule)
        if descriptors is None:
            summary.failed_count += 1
            summary.failed_molecule_ids.append(molecule.molecule_id)
            _update_agent_run_progress(
                db,
                agent_run,
                summary,
                phase="running",
                message=f"合成可行性 {index}/{len(molecules)} 失败：缺少描述符。",
                completed_count=index,
                current_molecule_id=molecule.molecule_id,
                extra={"external_tools_enabled": allow_external_tools},
            )
            continue

        external_result = None
        if allow_external_tools:
            if external_available:
                summary.external_attempted_count += 1
            external_result = _attempt_external_retrosynthesis(
                project,
                molecule,
                tool_status,
                max_synthesis_steps=max_synthesis_steps,
            )
        if external_result is not None and external_result.success:
            route = _upsert_external_synthesis_route(
                db,
                molecule,
                descriptors,
                tool_status,
                external_result=external_result,
                max_synthesis_steps=max_synthesis_steps,
                prefer_buyable_building_blocks=prefer_buyable_building_blocks,
                round_id=round_id,
            )
            external_adapter_modes.add(external_result.adapter_mode)
            summary.external_success_count += 1
            if external_result.warnings:
                summary.warnings = _dedupe(summary.warnings + external_result.warnings)
        else:
            if external_result is not None and external_result.warnings:
                summary.warnings = _dedupe(summary.warnings + external_result.warnings)
            route = _upsert_synthesis_route(
                db,
                molecule,
                descriptors,
                tool_status,
                max_synthesis_steps=max_synthesis_steps,
                prefer_buyable_building_blocks=prefer_buyable_building_blocks,
                external_tools_requested=allow_external_tools,
                fallback_warnings=summary.warnings if allow_external_tools else [],
                round_id=round_id,
            )
            summary.surrogate_count += 1
            fallback_count += 1
        molecule.labels = _replace_result_labels(molecule.labels, SYNTHESIS_RESULT_LABELS, route.labels)
        failure_reasons = _assessment_failure_reasons(
            db,
            molecule,
            synthesis_route=route,
            round_id=round_id,
        )
        _apply_assessment_status(molecule, failure_reasons)
        _update_sa_score(db, molecule, route.route_json.get("SA_score"))
        summary.evaluated_count += 1
        if failure_reasons:
            summary.failed_count += 1
            summary.failed_molecule_ids.append(molecule.molecule_id)
        else:
            summary.generated_count += 1
            summary.molecule_ids.append(molecule.molecule_id)
        _update_agent_run_progress(
            db,
            agent_run,
            summary,
            phase="running",
            message=f"已完成合成可行性 {index}/{len(molecules)}。",
            completed_count=index,
            current_molecule_id=molecule.molecule_id,
            extra={"external_tools_enabled": allow_external_tools},
        )

    if len(external_adapter_modes) == 1 and fallback_count == 0:
        summary.adapter_mode = next(iter(external_adapter_modes))
    elif external_adapter_modes:
        summary.adapter_mode = "aizynthfinder_with_rdkit_surrogate_fallback"
    summary.fallback_count += fallback_count if allow_external_tools else 0
    _finalize_stage_execution_mode(summary, surrogate_mode="rdkit_surrogate_synthesis")

    _finish_agent_run(agent_run, summary, tool_status)
    db.commit()
    return summary


def list_project_conformer_results(
    db: Session,
    project: Project,
    round_id: str | None = None,
) -> list[ConformerResult]:
    query = (
        db.query(ConformerResult)
        .join(Molecule, ConformerResult.molecule_id == Molecule.molecule_id)
        .filter(Molecule.project_id == project.project_id)
    )
    if round_id is not None:
        query = query.filter(ConformerResult.round_id == round_id)
    return query.order_by(Molecule.id.asc()).all()


def list_project_docking_results(
    db: Session,
    project: Project,
    round_id: str | None = None,
) -> list[DockingResult]:
    query = (
        db.query(DockingResult)
        .join(Molecule, DockingResult.molecule_id == Molecule.molecule_id)
        .filter(Molecule.project_id == project.project_id)
    )
    if round_id is not None:
        query = query.filter(DockingResult.round_id == round_id)
    return query.order_by(Molecule.id.asc()).all()


def list_project_admet_results(
    db: Session,
    project: Project,
    round_id: str | None = None,
) -> list[ADMETResult]:
    query = (
        db.query(ADMETResult)
        .join(Molecule, ADMETResult.molecule_id == Molecule.molecule_id)
        .filter(Molecule.project_id == project.project_id)
    )
    if round_id is not None:
        query = query.filter(ADMETResult.round_id == round_id)
    return query.order_by(Molecule.id.asc()).all()


def list_project_synthesis_routes(
    db: Session,
    project: Project,
    round_id: str | None = None,
) -> list[SynthesisRoute]:
    query = (
        db.query(SynthesisRoute)
        .join(Molecule, SynthesisRoute.molecule_id == Molecule.molecule_id)
        .filter(Molecule.project_id == project.project_id)
    )
    if round_id is not None:
        query = query.filter(SynthesisRoute.round_id == round_id)
    return query.order_by(Molecule.id.asc()).all()


def candidate_assessment_tool_status() -> dict[str, Any]:
    return copy.deepcopy({
        "rdkit": _package_status("rdkit"),
        "gnina": check_gnina_available(),
        "vina": check_vina_available(),
        "diffdock": {
            "available": False,
            "disabled_by_policy": True,
            "warning": "diffdock_removed_from_default_assessment_path",
        },
        "oddt": _package_status("oddt"),
        "admetlab": _package_status("admetlab"),
        "chemprop": chemprop_tool_status(),
        "deepchem": _package_status("deepchem"),
        "aizynthfinder": aizynthfinder_tool_status(),
        "askcos": _package_status("askcos"),
    })


def _select_assessment_molecules(
    db: Session,
    project: Project,
    molecule_ids: list[str] | None,
    max_molecules: int,
    round_id: str | None = None,
) -> list[Molecule]:
    query = db.query(Molecule).filter_by(project_id=project.project_id)
    if round_id is not None:
        query = query.filter_by(round_id=round_id)
    if molecule_ids:
        query = query.filter(Molecule.molecule_id.in_(molecule_ids))
    else:
        query = query.filter(Molecule.status.in_(ASSESSMENT_ELIGIBLE_STATUSES))
    return query.order_by(Molecule.id.asc()).limit(max_molecules).all()


def _normalize_assessment_mode(mode: str) -> str:
    normalized = (mode or "external").strip().lower()
    if normalized not in ASSESSMENT_MODES:
        raise ValueError(f"Unsupported candidate assessment mode: {mode}")
    return normalized


def _assessment_runtime_policy(
    *,
    assessment_mode: str,
    external_top_n: int,
    enable_external_synthesis_routes: bool,
) -> dict[str, Any]:
    if assessment_mode == "fast":
        return {
            "mode": "fast",
            "coarse_screen": "surrogate_only",
            "external_refinement": "disabled",
            "external_top_n": 0,
            "external_synthesis_routes_enabled": False,
        }
    if assessment_mode == "external":
        return {
            "mode": "external",
            "coarse_screen": "surrogate_first",
            "external_refinement": "top_n_after_coarse_screen",
            "external_top_n": external_top_n,
            "external_synthesis_routes_enabled": enable_external_synthesis_routes,
        }
    return {
        "mode": "full",
        "coarse_screen": "surrogate_first",
        "external_refinement": "all_coarse_passed_candidates",
        "external_top_n": None,
        "external_synthesis_routes_enabled": enable_external_synthesis_routes,
    }


def _finalize_stage_execution_mode(summary: StageSummary, surrogate_mode: str) -> None:
    summary.fallback_used = summary.fallback_count > 0
    if summary.external_success_count and summary.surrogate_count:
        summary.execution_mode = "mixed_external_surrogate"
        if summary.adapter_mode == surrogate_mode:
            summary.adapter_mode = f"{surrogate_mode}_with_external_refinement"
        return
    if summary.external_success_count:
        summary.execution_mode = "external_only"
        return
    if summary.surrogate_count and summary.external_tools_requested:
        summary.execution_mode = "surrogate_fallback"
        summary.adapter_mode = surrogate_mode
        return
    if summary.surrogate_count:
        summary.execution_mode = "surrogate_only"
        summary.adapter_mode = surrogate_mode
        return
    if summary.skipped_count == summary.requested_count:
        summary.execution_mode = "skipped"


def _external_admet_skip_warning(
    tool_status: dict[str, Any],
    molecule_count: int,
) -> str | None:
    chemprop_status = tool_status.get("chemprop") or {}
    if not chemprop_status.get("available"):
        return None
    if chemprop_status.get("mode") != "admet_ai":
        return None
    if bool(chemprop_status.get("gpu_available")):
        return None
    if molecule_count <= _admet_ai_cpu_max_molecules():
        return None
    return "admet_ai_cpu_batch_too_large_using_rdkit_surrogate"


def _admet_ai_cpu_max_molecules() -> int:
    raw_value = os.environ.get("MEDAGENT_ADMET_AI_CPU_MAX_MOLECULES")
    try:
        parsed = int(raw_value) if raw_value is not None else DEFAULT_ADMET_AI_CPU_MAX_MOLECULES
    except ValueError:
        parsed = DEFAULT_ADMET_AI_CPU_MAX_MOLECULES
    return max(1, parsed)


def _skipped_ranking_summary(
    molecules: list[Molecule],
    top_n: int,
    round_id: str | None = None,
) -> StageSummary:
    ordered_ids = [molecule.molecule_id for molecule in molecules]
    return StageSummary(
        agent_run_id="RUN-RANKING-SKIPPED",
        adapter_mode="ranking_skipped",
        requested_count=len(molecules),
        skipped_count=len(molecules),
        molecule_ids=ordered_ids[:top_n],
        skipped_molecule_ids=ordered_ids,
        warnings=["ranking_skipped_by_request"],
        round_id=round_id,
        execution_mode="skipped",
    )


def _skipped_stage_summary(
    molecules: list[Molecule],
    stage: str,
    round_id: str | None = None,
) -> StageSummary:
    molecule_ids = [molecule.molecule_id for molecule in molecules]
    return StageSummary(
        agent_run_id=f"RUN-{stage.upper()}-SKIPPED",
        adapter_mode=f"{stage}_skipped",
        requested_count=len(molecules),
        skipped_count=len(molecules),
        skipped_molecule_ids=molecule_ids,
        warnings=[f"{stage}_skipped_by_strategy"],
        round_id=round_id,
        execution_mode="skipped",
    )


def _top_ranked_molecules_for_external_refinement(
    molecules: list[Molecule],
    ranking: Any,
    external_top_n: int,
) -> list[Molecule]:
    molecule_by_id = {molecule.molecule_id: molecule for molecule in molecules}
    limit = max(0, external_top_n)
    selected_ids = [
        molecule_id
        for molecule_id in ranking.molecule_ids
        if molecule_id in molecule_by_id
    ][:limit]
    if len(selected_ids) < limit:
        selected_set = set(selected_ids)
        for molecule in molecules:
            if molecule.molecule_id in selected_set:
                continue
            selected_ids.append(molecule.molecule_id)
            selected_set.add(molecule.molecule_id)
            if len(selected_ids) >= limit:
                break
    return [molecule_by_id[molecule_id] for molecule_id in selected_ids if molecule_id in molecule_by_id]


def _apply_coarse_screen_labels(
    db: Session,
    molecules: list[Molecule],
    round_id: str | None = None,
) -> dict[str, Any]:
    passed_ids: list[str] = []
    failed_ids: list[str] = []
    failure_reasons_by_id: dict[str, list[str]] = {}

    for molecule in molecules:
        failure_reasons = _assessment_failure_reasons(db, molecule, round_id=round_id)
        failure_reasons_by_id[molecule.molecule_id] = failure_reasons
        molecule.labels = [label for label in (molecule.labels or []) if label not in COARSE_SCREEN_LABELS]
        if failure_reasons:
            failed_ids.append(molecule.molecule_id)
            molecule.labels = merge_labels(
                molecule.labels,
                ["coarse_screen_failed", "rejected_by_coarse_screen"],
            )
        else:
            passed_ids.append(molecule.molecule_id)
            molecule.labels = merge_labels(
                molecule.labels,
                ["coarse_screen_passed", "coarse_only_candidate"],
            )

    db.commit()
    return {
        "requested_count": len(molecules),
        "passed_count": len(passed_ids),
        "failed_count": len(failed_ids),
        "passed_molecule_ids": passed_ids,
        "failed_molecule_ids": failed_ids,
        "failure_reasons_by_id": failure_reasons_by_id,
    }


def _mark_coarse_screen_summary(
    summary: StageSummary,
    coarse_screen: dict[str, Any],
    assessment_mode: str,
    refinement_count: int,
) -> None:
    failed_count = int(coarse_screen.get("failed_count") or 0)
    passed_count = int(coarse_screen.get("passed_count") or 0)
    summary.warnings = _dedupe(
        summary.warnings
        + [
            f"assessment_mode={assessment_mode}",
            f"coarse_screen_passed={passed_count}",
            f"coarse_screen_failed_skip_external={failed_count}",
            f"external_refinement_selected={refinement_count}",
        ]
    )


def _apply_external_refinement_labels(
    db: Session,
    coarse_passed_molecules: list[Molecule],
    refinement_molecules: list[Molecule],
    round_id: str | None = None,
) -> None:
    refinement_ids = {molecule.molecule_id for molecule in refinement_molecules}
    for molecule in coarse_passed_molecules:
        labels = [label for label in (molecule.labels or []) if label not in {"coarse_only_candidate", "externally_refined_candidate", "external_refinement_attempted"}]
        if molecule.molecule_id not in refinement_ids:
            molecule.labels = merge_labels(labels, ["coarse_only_candidate"])
            continue
        evidence_labels = _external_evidence_labels(db, molecule, round_id=round_id)
        if evidence_labels:
            molecule.labels = merge_labels(labels, ["external_refinement_attempted", "externally_refined_candidate"])
        else:
            molecule.labels = merge_labels(labels, ["external_refinement_attempted", "coarse_only_candidate"])
    db.commit()


def _external_evidence_labels(
    db: Session,
    molecule: Molecule,
    round_id: str | None = None,
) -> list[str]:
    labels: list[str] = []
    docking = (
        db.query(DockingResult)
        .filter_by(molecule_id=molecule.molecule_id, round_id=round_id)
        .one_or_none()
    )
    if docking is not None and not _is_surrogate_docking_result(docking):
        docking_labels = docking.labels or []
        if "external_docking_adapter_used" in docking_labels:
            labels.append("external_docking_adapter_used")
    admet = (
        db.query(ADMETResult)
        .filter_by(molecule_id=molecule.molecule_id, round_id=round_id)
        .one_or_none()
    )
    if admet is not None and not _is_surrogate_admet_result(admet):
        admet_labels = admet.labels or []
        if "admet_ai_predicted" in admet_labels or "chemprop_predicted" in admet_labels:
            labels.append("external_admet_adapter_used")
    synthesis = (
        db.query(SynthesisRoute)
        .filter_by(molecule_id=molecule.molecule_id, round_id=round_id)
        .one_or_none()
    )
    if synthesis is not None:
        synthesis_labels = synthesis.labels or []
        if "external_retrosynthesis_adapter_used" in synthesis_labels:
            labels.append("external_retrosynthesis_adapter_used")
    return labels


def _mark_external_refinement_summary(
    base: StageSummary,
    refinement: StageSummary,
    refinement_scope: str = "top_n",
) -> None:
    base_surrogate_mode = base.adapter_mode
    refined_count = refinement.evaluated_count
    base.external_tools_requested = base.external_tools_requested or refinement.external_tools_requested
    base.external_tools_enabled = base.external_tools_enabled or refinement.external_tools_enabled
    base.external_attempted_count += refinement.external_attempted_count
    base.external_success_count += refinement.external_success_count
    base.fallback_count += refinement.fallback_count
    if refinement.external_success_count:
        base.surrogate_count = max(0, base.surrogate_count - refinement.external_success_count)
    base.fallback_used = base.fallback_count > 0
    if refined_count == 0:
        base.warnings = _dedupe(base.warnings + refinement.warnings + ["external_refinement_no_candidates"])
        _finalize_stage_execution_mode(base, surrogate_mode=base_surrogate_mode)
        return

    if refinement.adapter_mode.startswith("rdkit_surrogate"):
        base.warnings = _dedupe(
            base.warnings
            + refinement.warnings
            + [
                f"external_refinement_{refinement_scope}={refined_count}",
                "external_refinement_no_external_results",
            ]
        )
        _finalize_stage_execution_mode(base, surrogate_mode=refinement.adapter_mode)
        return

    base.adapter_mode = (
        refinement.adapter_mode
        if refinement_scope == "full"
        else f"{refinement.adapter_mode}_{refinement_scope}_refinement"
    )
    base.warnings = _dedupe(
        base.warnings
        + refinement.warnings
        + [
            f"external_refinement_{refinement_scope}={refined_count}",
            f"external_refinement_adapter_mode={refinement.adapter_mode}",
        ]
    )
    _finalize_stage_execution_mode(base, surrogate_mode=base_surrogate_mode)


def _assessment_failure_reasons(
    db: Session,
    molecule: Molecule,
    synthesis_route: SynthesisRoute | None = None,
    round_id: str | None = None,
) -> list[str]:
    reasons: list[str] = []
    conformer = (
        db.query(ConformerResult)
        .filter_by(molecule_id=molecule.molecule_id, round_id=round_id)
        .one_or_none()
    )
    if conformer is None or not conformer.conformer_generated:
        reasons.append("assessment_conformer_failed")

    docking = (
        db.query(DockingResult)
        .filter_by(molecule_id=molecule.molecule_id, round_id=round_id)
        .one_or_none()
    )
    if docking is not None and not _is_surrogate_docking_result(docking):
        docking_labels = docking.labels or []
        if "bad_pose" in docking_labels or (docking.clash_count or 0) >= 2:
            reasons.append("assessment_bad_pose")
        elif docking.cnn_score is not None and float(docking.cnn_score) < 0.35:
            reasons.append("assessment_bad_pose")

    admet = (
        db.query(ADMETResult)
        .filter_by(molecule_id=molecule.molecule_id, round_id=round_id)
        .one_or_none()
    )
    if admet is not None and not _is_surrogate_admet_result(admet):
        admet_labels = admet.labels or []
        if "admet_blocker" in admet_labels or admet.hERG_risk == "high_risk" or admet.Ames_risk == "high_risk":
            reasons.append("assessment_admet_blocker")

    synthesis = synthesis_route or (
        db.query(SynthesisRoute)
        .filter_by(molecule_id=molecule.molecule_id, round_id=round_id)
        .one_or_none()
    )
    if synthesis is not None and not _is_surrogate_synthesis_result(synthesis) and not synthesis.route_found:
        reasons.append("assessment_route_not_found")

    return _dedupe(reasons)


def _is_surrogate_docking_result(result: DockingResult) -> bool:
    raw_output = result.raw_output or {}
    return raw_output.get("status") == "surrogate_only" or "rdkit_surrogate_docking" in (
        result.labels or []
    )


def _is_surrogate_admet_result(result: ADMETResult) -> bool:
    raw_output = result.raw_output or {}
    return raw_output.get("status") == "surrogate_only" or "rdkit_surrogate_admet" in (
        result.labels or []
    )


def _is_surrogate_synthesis_result(result: SynthesisRoute) -> bool:
    route_json = result.route_json or {}
    return route_json.get("status") == "surrogate_only" or "rdkit_surrogate_synthesis" in (
        result.labels or []
    )


def _apply_assessment_status(molecule: Molecule, failure_reasons: list[str]) -> None:
    molecule.labels = [label for label in (molecule.labels or []) if label not in ASSESSMENT_STATUS_LABELS]
    if failure_reasons:
        molecule.status = "failed_assessment"
        molecule.labels = merge_labels(molecule.labels, ["assessment_failed", *failure_reasons])
    else:
        molecule.status = "candidate_assessed"
        molecule.labels = merge_labels(molecule.labels, ["assessment_passed"])


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
    round_id: str | None = None,
) -> ConformerResult:
    result = (
        db.query(ConformerResult)
        .filter_by(molecule_id=molecule.molecule_id, round_id=round_id)
        .one_or_none()
    )
    if result is None:
        result = ConformerResult(molecule_id=molecule.molecule_id, round_id=round_id)
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
    fallback_warnings: list[str] | None = None,
    external_tools_requested: bool = False,
    round_id: str | None = None,
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
    if external_tools_requested:
        labels.append("external_docking_adapter_failed")
        labels.append("external_docking_fallback_used")
    labels.extend(_external_docking_fallback_labels(fallback_warnings or []))
    labels.append("docking_strong" if vina_score <= -8.0 else "docking_weak")
    labels.append("pose_confident" if cnn_score >= 0.6 else "pose_uncertain")
    labels.append("key_interaction_present" if key_hbond_count else "key_interaction_missing")
    if clash_count:
        labels.append("steric_clash")
    if clash_count >= 2 or cnn_score < 0.4:
        labels.append("bad_pose")
    if ligand_efficiency <= -0.3:
        labels.append("good_ligand_efficiency")

    result = (
        db.query(DockingResult)
        .filter_by(molecule_id=molecule.molecule_id, round_id=round_id)
        .one_or_none()
    )
    if result is None:
        result = DockingResult(molecule_id=molecule.molecule_id, round_id=round_id)
        db.add(result)

    result.tool_run_id = None
    result.vina_score = None
    result.cnn_score = None
    result.diffdock_confidence = None
    result.key_hbond_count = None
    result.clash_count = None
    result.pose_file = None
    result.labels = labels
    result.raw_output = {
        "adapter_mode": "rdkit_surrogate_docking",
        "tool_name": "rdkit",
        "tool_version": _package_status("rdkit").get("version"),
        "model_name": None,
        "input_hash": _smiles_input_hash(molecule.smiles),
        "status": "surrogate_only",
        "execution_mode": "surrogate_fallback" if external_tools_requested else "surrogate_only",
        "evidence_tier": "surrogate",
        "external_tool_requested": external_tools_requested,
        "external_tool_used": False,
        "surrogate_used": True,
        "fallback_used": external_tools_requested,
        "result_kind": "non_docking_coarse_estimate",
        "estimated_affinity_like_score": vina_score,
        "estimated_pose_confidence": cnn_score,
        "estimated_key_hbond_count": key_hbond_count,
        "estimated_clash_count": clash_count,
        "warnings": fallback_warnings or [],
    }
    return result


def _external_docking_fallback_labels(warnings: list[str]) -> list[str]:
    labels: list[str] = []
    warning_set = set(warnings or [])
    if "external_docking_tools_not_installed" in warning_set:
        labels.append("external_docking_tools_unavailable")
    if {
        "protein_file_required_for_external_docking",
        "protein_file_not_found",
    } & warning_set:
        labels.extend(["external_docking_setup_incomplete", "external_docking_receptor_missing"])
    if "grid_center_and_grid_size_required_for_external_docking" in warning_set:
        labels.extend(["external_docking_setup_incomplete", "external_docking_grid_missing"])
    if "external_docking_adapter_unavailable_for_inputs" in warning_set:
        labels.append("external_docking_tools_unavailable")
    if "vina_inputs_preparation_failed" in warning_set:
        labels.append("external_docking_setup_incomplete")
    return _dedupe(labels)


def _upsert_external_docking_result(
    db: Session,
    molecule: Molecule,
    conformer: ConformerResult,
    descriptors: DescriptorSnapshot,
    key_residues: list[str],
    external_result: DockingToolResult,
    receptor_file: str | None,
    round_id: str | None = None,
) -> DockingResult:
    vina_score = external_result.vina_score
    if vina_score is None:
        vina_score = external_result.cnn_affinity
    cnn_score = external_result.cnn_score
    diffdock_confidence = external_result.diffdock_confidence
    labels = list(external_result.labels or [])
    if not labels:
        labels = ["external_docking_adapter_used", f"{external_result.tool_name}_adapter"]
    elif "external_docking_adapter_used" not in labels:
        labels.append("external_docking_adapter_used")
    labels.append(external_result.adapter_mode)
    if vina_score is not None:
        labels.append("docking_strong" if vina_score <= -8.0 else "docking_weak")
        if vina_score / max(descriptors.heavy_atom_count, 1) <= -0.3:
            labels.append("good_ligand_efficiency")
    if cnn_score is not None:
        labels.append("pose_confident" if cnn_score >= 0.6 else "pose_uncertain")
    if diffdock_confidence is not None:
        labels.append("diffdock_confidence_recorded")
    interaction_summary = analyze_pose_interactions(
        pose_file=external_result.pose_file,
        receptor_file=receptor_file,
        key_residues=key_residues,
    )
    labels.extend(interaction_summary["labels"])
    interaction_warnings = interaction_summary["warnings"]

    result = (
        db.query(DockingResult)
        .filter_by(molecule_id=molecule.molecule_id, round_id=round_id)
        .one_or_none()
    )
    if result is None:
        result = DockingResult(molecule_id=molecule.molecule_id, round_id=round_id)
        db.add(result)

    result.tool_run_id = external_result.adapter_mode
    result.vina_score = _rounded(vina_score)
    result.cnn_score = _rounded(cnn_score)
    result.diffdock_confidence = _rounded(diffdock_confidence)
    result.key_hbond_count = interaction_summary["key_hbond_count"]
    result.clash_count = interaction_summary["clash_count"]
    result.pose_file = external_result.pose_file
    result.labels = _dedupe(labels)
    result.raw_output = {
        "adapter_mode": external_result.adapter_mode,
        "tool_name": external_result.tool_name,
        "input_hash": _smiles_input_hash(molecule.smiles),
        "status": "success",
        "execution_mode": "external_tool",
        "evidence_tier": "external_tool",
        "external_tool_requested": True,
        "external_tool_used": True,
        "surrogate_used": False,
        "fallback_used": False,
        "result_kind": "external_docking",
        "cnn_affinity": external_result.cnn_affinity,
        "diffdock_confidence": external_result.diffdock_confidence,
        "diffdock_confidence_semantics": (
            "model_specific_uncalibrated_score_higher_is_better"
            if external_result.diffdock_confidence is not None
            else None
        ),
        "selected_pose_rank": external_result.selected_pose_rank,
        "pose_count": external_result.pose_count,
        "pose_selection_method": external_result.pose_selection_method,
        "best_pose_confirmed": external_result.best_pose_confirmed,
        "runtime_seconds": round(external_result.runtime_seconds, 3),
        "exit_code": external_result.exit_code,
        "warnings": _dedupe([*external_result.warnings, *interaction_warnings]),
        "command": external_result.command,
        "provenance": external_result.provenance,
        "pose_interactions_computed": interaction_summary["computed"],
        "pose_interactions": interaction_summary,
    }
    return result


def _upsert_admet_result(
    db: Session,
    molecule: Molecule,
    descriptors: DescriptorSnapshot,
    tool_status: dict[str, Any],
    external_tools_requested: bool = False,
    fallback_warnings: list[str] | None = None,
    round_id: str | None = None,
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
    if external_tools_requested:
        labels.extend(["external_admet_adapter_failed", "external_admet_fallback_used"])
    labels.extend([herg_risk, ames_risk])
    if herg_risk == "high_risk" or ames_risk == "high_risk":
        labels.append("admet_blocker")
    elif herg_risk == "medium_risk" or ames_risk == "medium_risk":
        labels.append("admet_warning")
    else:
        labels.append("admet_clean")

    result = (
        db.query(ADMETResult)
        .filter_by(molecule_id=molecule.molecule_id, round_id=round_id)
        .one_or_none()
    )
    if result is None:
        result = ADMETResult(molecule_id=molecule.molecule_id, round_id=round_id)
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
        "tool_name": "rdkit",
        "tool_version": tool_status.get("rdkit", {}).get("version"),
        "model_name": None,
        "input_hash": _smiles_input_hash(molecule.smiles),
        "status": "surrogate_only",
        "execution_mode": "surrogate_fallback" if external_tools_requested else "surrogate_only",
        "evidence_tier": "surrogate",
        "external_tool_requested": external_tools_requested,
        "external_tool_used": False,
        "surrogate_used": True,
        "fallback_used": external_tools_requested,
        "result_kind": "non_admet_coarse_estimate",
        "warnings": fallback_warnings or [],
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


def _attempt_external_retrosynthesis(
    project: Project,
    molecule: Molecule,
    tool_status: dict[str, Any],
    max_synthesis_steps: int,
) -> AiZynthFinderResult | None:
    aizynthfinder_status = tool_status.get("aizynthfinder", {})
    if not aizynthfinder_status.get("available"):
        return None

    output_dir = (
        ASSESSMENT_RUNTIME_ROOT
        / _safe_path_part(project.project_id)
        / "retrosynthesis"
        / _safe_path_part(molecule.molecule_id)
    )
    return run_aizynthfinder_retrosynthesis(
        AiZynthFinderRequest(
            smiles=molecule.smiles,
            output_dir=str(output_dir),
            max_steps=max_synthesis_steps,
            docker_image=aizynthfinder_status.get("docker_image") or "aizynthfinder:latest",
            timeout_seconds=_retrosynthesis_timeout_seconds(),
        ),
        aizynthfinder_status,
    )


def _retrosynthesis_timeout_seconds() -> int:
    raw_value = os.environ.get("MEDAGENT_AIZYNTHFINDER_TIMEOUT_SECONDS", "90")
    try:
        return max(10, min(int(raw_value), 900))
    except (TypeError, ValueError):
        return 90


def _upsert_external_synthesis_route(
    db: Session,
    molecule: Molecule,
    descriptors: DescriptorSnapshot,
    tool_status: dict[str, Any],
    external_result: AiZynthFinderResult,
    max_synthesis_steps: int,
    prefer_buyable_building_blocks: bool,
    round_id: str | None = None,
) -> SynthesisRoute:
    sa_score = _sa_score(descriptors)
    sc_score = round(_clamp(sa_score + descriptors.ring_count * 0.2, 1.0, 10.0), 3)
    estimated_steps = max(1, min(12, int(math.ceil(sa_score))))
    route_steps = external_result.num_steps or estimated_steps
    route_found = bool(external_result.route_found)
    buyable_blocks = _external_buyable_block_count(external_result)
    route_confidence = _external_route_confidence(external_result, route_found)
    route_plan = external_result.route_plan or []
    starting_materials = external_result.starting_materials or []
    has_route_details = bool(route_plan or starting_materials or external_result.route_trees)

    labels = _synthesis_difficulty_labels(sa_score)
    labels.append("route_found" if route_found else "route_not_found")
    if route_steps > max_synthesis_steps:
        labels.append("too_many_steps")
    labels.extend(
        [
            "external_retrosynthesis_adapter_used",
            f"{external_result.tool_name}_adapter",
            *external_result.labels,
        ]
    )

    result = (
        db.query(SynthesisRoute)
        .filter_by(molecule_id=molecule.molecule_id, round_id=round_id)
        .one_or_none()
    )
    if result is None:
        result = SynthesisRoute(molecule_id=molecule.molecule_id, round_id=round_id)
        db.add(result)

    result.route_found = route_found
    result.route_steps = route_steps
    result.route_confidence = route_confidence
    result.buyable_building_blocks = buyable_blocks
    result.labels = _dedupe(labels)
    result.route_json = {
        "adapter_mode": external_result.adapter_mode,
        "tool_name": external_result.tool_name,
        "tool_status": {
            key: tool_status[key]
            for key in ["aizynthfinder", "askcos", "rdkit"]
            if key in tool_status
        },
        "SA_score": sa_score,
        "SCScore": sc_score,
        "route_score": external_result.route_score,
        "route_summary": external_result.route_summary
        or _external_route_summary(route_found, route_steps),
        "route_plan": route_plan,
        "starting_materials": starting_materials,
        "route_trees": external_result.route_trees,
        "stock_info": external_result.stock_info,
        "route_metadata": external_result.route_metadata,
        "route_risks": _external_route_risks(
            route_found=route_found,
            route_steps=route_steps,
            max_synthesis_steps=max_synthesis_steps,
            warnings=external_result.warnings,
        ),
        "external_warnings": external_result.warnings,
        "exit_code": external_result.exit_code,
        "runtime_seconds": round(external_result.runtime_seconds, 3),
        "route_note": (
            "AiZynthFinder route tree parsed with stock-matched starting materials."
            if has_route_details
            else (
                "AiZynthFinder summary parsed; reaction tree, starting materials, and stock hits "
                "were not present in the adapter output."
            )
        ),
        "input_hash": _smiles_input_hash(molecule.smiles),
        "status": "success" if external_result.success else "failed",
        "execution_mode": "external_tool",
        "evidence_tier": "retrosynthesis_tool",
        "external_tool_requested": True,
        "external_tool_used": True,
        "surrogate_used": False,
        "fallback_used": False,
        "result_kind": (
            "external_retrosynthesis_route"
            if has_route_details
            else "external_retrosynthesis_summary"
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
    external_tools_requested: bool = False,
    fallback_warnings: list[str] | None = None,
    round_id: str | None = None,
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
    labels.append("surrogate_synthesis_estimate")
    if route_steps > max_synthesis_steps:
        labels.append("too_many_steps")
    if hazardous_reaction_count:
        labels.append("hazardous_route")
    labels.extend(["external_retrosynthesis_adapter_pending", "rdkit_surrogate_synthesis"])
    if external_tools_requested:
        labels.extend(["external_retrosynthesis_adapter_failed", "external_retrosynthesis_fallback_used"])

    result = (
        db.query(SynthesisRoute)
        .filter_by(molecule_id=molecule.molecule_id, round_id=round_id)
        .one_or_none()
    )
    if result is None:
        result = SynthesisRoute(molecule_id=molecule.molecule_id, round_id=round_id)
        db.add(result)

    result.route_found = False
    result.route_steps = None
    result.route_confidence = None
    result.buyable_building_blocks = None
    result.labels = _dedupe(labels)
    result.route_json = {
        "adapter_mode": "rdkit_surrogate_synthesis",
        "tool_name": "rdkit",
        "tool_version": tool_status.get("rdkit", {}).get("version"),
        "model_name": None,
        "input_hash": _smiles_input_hash(molecule.smiles),
        "status": "surrogate_only",
        "execution_mode": "surrogate_fallback" if external_tools_requested else "surrogate_only",
        "evidence_tier": "surrogate",
        "external_tool_requested": external_tools_requested,
        "external_tool_used": False,
        "surrogate_used": True,
        "fallback_used": external_tools_requested,
        "result_kind": "non_retrosynthesis_coarse_estimate",
        "warnings": fallback_warnings or [],
        "tool_status": {
            key: tool_status[key]
            for key in ["aizynthfinder", "askcos", "rdkit"]
            if key in tool_status
        },
        "SA_score": sa_score,
        "SCScore": sc_score,
        "estimated_route_feasible": route_found,
        "estimated_route_steps": route_steps,
        "estimated_route_confidence": route_confidence,
        "estimated_buyable_building_blocks": buyable_blocks,
        "hazardous_reaction_count": hazardous_reaction_count,
        "protecting_group_count": protecting_group_count,
        "route_summary": _route_summary(route_found, route_steps, buyable_blocks),
        "route_risks": _route_risks(
            route_found=route_found,
            route_steps=route_steps,
            max_synthesis_steps=max_synthesis_steps,
            hazardous_reaction_count=hazardous_reaction_count,
            protecting_group_count=protecting_group_count,
        ),
        "route_note": (
            "Fallback route blueprint inferred from RDKit descriptors. "
            "Provide AiZynthFinder model config for reaction-level retrosynthesis."
        ),
    }
    return result


def _descriptor_snapshot(
    smiles: str,
    db: Session,
    molecule: Molecule,
) -> DescriptorSnapshot | None:
    properties = db.query(MoleculeProperty).filter_by(molecule_id=molecule.molecule_id).one_or_none()
    properties_incomplete = properties is None or any(
        getattr(properties, field_name) is None
        for field_name in ("mw", "logp", "tpsa", "hbd", "hba")
    )
    if properties_incomplete:
        from medagent.services.molecule_validation import ensure_molecule_property_record

        validation = ensure_molecule_property_record(db, molecule)
        if validation.valid:
            db.flush()
            properties = (
                db.query(MoleculeProperty)
                .filter_by(molecule_id=molecule.molecule_id)
                .one_or_none()
            )
        else:
            return None
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
    round_id: str | None = None,
) -> AgentRun:
    run = AgentRun(
        agent_run_id=new_id("RUN"),
        project_id=project.project_id,
        round_id=round_id,
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


def _update_agent_run_progress(
    db: Session,
    agent_run: AgentRun,
    summary: StageSummary,
    *,
    phase: str,
    message: str,
    completed_count: int,
    current_molecule_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    agent_run.output_json = {
        **summary.as_dict(),
        "progress": _progress_payload(
            agent_run=agent_run,
            summary=summary,
            phase=phase,
            message=message,
            completed_count=completed_count,
            current_molecule_id=current_molecule_id,
            extra=extra,
        ),
    }
    db.commit()


def _finish_agent_run(
    agent_run: AgentRun,
    summary: StageSummary,
    tool_status: dict[str, Any],
) -> None:
    agent_run.status = "success"
    agent_run.output_json = {
        **summary.as_dict(),
        "progress": _progress_payload(
            agent_run=agent_run,
            summary=summary,
            phase="completed",
            message="步骤已完成。",
            completed_count=summary.requested_count,
        ),
        "tool_status": tool_status,
    }


def _progress_payload(
    agent_run: AgentRun,
    summary: StageSummary,
    *,
    phase: str,
    message: str,
    completed_count: int,
    current_molecule_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    total = max(summary.requested_count, 0)
    completed = max(0, min(completed_count, total)) if total else 0
    percent = 100 if total == 0 else round(completed / total * 100, 1)
    payload = {
        "stage": _progress_stage_name(agent_run.agent_name),
        "phase": phase,
        "message": message,
        "total_molecules": total,
        "completed_molecules": completed,
        "percent": percent,
        "current_molecule_id": current_molecule_id,
        "adapter_mode": summary.adapter_mode,
        "execution_mode": summary.execution_mode,
        "external_tools_requested": summary.external_tools_requested,
        "external_tools_enabled": summary.external_tools_enabled,
        "external_attempted_count": summary.external_attempted_count,
        "external_success_count": summary.external_success_count,
        "surrogate_count": summary.surrogate_count,
        "fallback_count": summary.fallback_count,
        "fallback_used": summary.fallback_used,
        "evaluated_count": summary.evaluated_count,
        "passed_count": summary.generated_count,
        "failed_count": summary.failed_count,
        "skipped_count": summary.skipped_count,
        "warnings": summary.warnings,
    }
    if extra:
        payload.update(extra)
    return payload


def _progress_stage_name(agent_name: str) -> str:
    return {
        CONFORMER_AGENT_NAME: "构象生成",
        DOCKING_AGENT_NAME: "分子对接",
        ADMET_AGENT_NAME: "ADMET 预测",
        SYNTHESIS_AGENT_NAME: "逆合成分析",
    }.get(agent_name, agent_name)


def _replace_result_labels(
    existing: list[str] | None,
    stale_labels: set[str],
    new_labels: list[str],
) -> list[str]:
    cleaned = [label for label in (existing or []) if label not in stale_labels]
    return merge_labels(cleaned, new_labels)


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


def _synthesis_difficulty_labels(sa_score: float) -> list[str]:
    if sa_score <= 4.5:
        return ["easy_to_synthesize"]
    if sa_score <= 6.5:
        return ["moderate_synthesis"]
    return ["hard_to_synthesize"]


def _external_buyable_block_count(external_result: AiZynthFinderResult) -> int | None:
    metadata = external_result.route_metadata or {}
    count = metadata.get("number_of_precursors_in_stock")
    if count is not None:
        try:
            return int(count)
        except (TypeError, ValueError):
            pass
    if external_result.starting_materials:
        return len(external_result.starting_materials)
    return None


def _external_route_confidence(
    external_result: AiZynthFinderResult,
    route_found: bool,
) -> float:
    if external_result.route_score is not None:
        return round(_clamp(float(external_result.route_score), 0.05, 0.99), 3)
    return 0.72 if route_found else 0.28


def _route_summary(route_found: bool, route_steps: int, buyable_blocks: int) -> str:
    if route_found:
        return (
            "RDKit descriptor heuristic suggests moderate synthetic accessibility "
            f"(estimated {route_steps} steps; {buyable_blocks} fragment equivalents)."
        )
    return (
        "RDKit descriptor heuristic suggests difficult synthetic accessibility "
        f"(estimated {route_steps} steps; no reaction route was generated)."
    )


def _external_route_summary(route_found: bool, route_steps: int) -> str:
    if route_found:
        return f"AiZynthFinder found a retrosynthesis route in {route_steps} steps."
    return "AiZynthFinder completed, but no solved route was found within constraints."


def _route_risks(
    route_found: bool,
    route_steps: int,
    max_synthesis_steps: int,
    hazardous_reaction_count: int,
    protecting_group_count: int,
) -> list[str]:
    risks: list[str] = []
    if not route_found:
        risks.append("No confident route within configured step budget.")
    if route_steps > max_synthesis_steps:
        risks.append(f"Estimated route length {route_steps} exceeds max step budget {max_synthesis_steps}.")
    if hazardous_reaction_count:
        risks.append("Halogen-heavy pattern may require hazardous or low-yield coupling conditions.")
    if protecting_group_count:
        risks.append("Multiple donors may require protecting-group strategy.")
    if not risks:
        risks.append("No major surrogate route risk detected.")
    return risks


def _external_route_risks(
    route_found: bool,
    route_steps: int,
    max_synthesis_steps: int,
    warnings: list[str],
) -> list[str]:
    risks: list[str] = []
    if not route_found:
        risks.append("AiZynthFinder did not provide a solved route within the configured constraints.")
    if route_steps > max_synthesis_steps:
        risks.append(f"AiZynthFinder route length {route_steps} exceeds max step budget {max_synthesis_steps}.")
    for warning in warnings:
        risks.append(f"AiZynthFinder warning: {warning}")
    if not risks:
        risks.append("No major AiZynthFinder route risk detected.")
    return risks


def _binding_site_docking_config(
    db: Session,
    project: Project,
    binding_site_id: str | None,
) -> dict[str, Any]:
    return project_docking_config(
        db,
        project,
        binding_site_id,
        path_resolver=resolve_receptor_path,
    )


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
    preparation_warnings: list[str] = []
    attempted_vina_preparation = _should_prepare_vina_inputs(
        tool_status,
        protein_file,
        ligand_file,
        grid_center,
        grid_size,
    )
    if attempted_vina_preparation:
        protein_file, ligand_file, preparation_warnings = _prepare_vina_docking_inputs(
            project,
            molecule,
            receptor_file=protein_file,
            ligand_file=ligand_file,
        )
    if not ligand_file:
        ligand_file = _write_ligand_sdf(project, molecule)
    if ligand_file is None:
        return DockingToolResult(
            adapter_mode="external_docking_unavailable",
            tool_name="external_docking",
            success=False,
            labels=["external_docking_adapter_failed"],
            warnings=_dedupe(preparation_warnings + ["ligand_sdf_generation_failed"]),
        )
    request = DockingToolRequest(
        receptor_file=protein_file,
        ligand_file=ligand_file,
        output_dir=str(ASSESSMENT_RUNTIME_ROOT / _safe_path_part(project.project_id) / "poses"),
        grid_center=grid_center,
        grid_size=grid_size,
        timeout_seconds=_docking_timeout_seconds(),
        molecule_id=molecule.molecule_id,
    )
    selected_tool = select_docking_tool(request, tool_status)
    if selected_tool:
        request = replace(
            request,
            timeout_seconds=_docking_timeout_seconds(
                tool_status.get(selected_tool, {}).get("configured_timeout_seconds")
            ),
        )
    external_result = run_external_docking(request, tool_status)
    if (
        external_result is not None
        and not external_result.success
        and selected_tool == "gnina"
        and tool_status.get("vina", {}).get("available")
    ):
        vina_receptor, vina_ligand, fallback_preparation_warnings = _prepare_vina_docking_inputs(
            project,
            molecule,
            receptor_file=protein_file,
            ligand_file=prepared_ligand_files.get(molecule.molecule_id),
        )
        fallback_request = replace(
            request,
            receptor_file=vina_receptor,
            ligand_file=vina_ligand or request.ligand_file,
            timeout_seconds=_docking_timeout_seconds(
                tool_status.get("vina", {}).get("configured_timeout_seconds")
            ),
        )
        fallback_tool_status = copy.deepcopy(tool_status)
        fallback_tool_status["gnina"] = {
            **fallback_tool_status.get("gnina", {}),
            "available": False,
        }
        if select_docking_tool(fallback_request, fallback_tool_status) == "vina":
            vina_result = run_external_docking(fallback_request, fallback_tool_status)
            if vina_result is not None and vina_result.success:
                return _mark_vina_cpu_fallback(
                    vina_result,
                    reason="gnina_execution_failed_vina_cpu_fallback",
                    source_result=external_result,
                    preparation_warnings=[*preparation_warnings, *fallback_preparation_warnings],
                )
        external_result = replace(
            external_result,
            warnings=_dedupe(
                [
                    *preparation_warnings,
                    *fallback_preparation_warnings,
                    *external_result.warnings,
                    "gnina_execution_failed_vina_cpu_fallback_failed",
                ]
            ),
        )
    if external_result is None:
        selected_tool = select_docking_tool(request, tool_status)
        warning = "external_docking_adapter_unavailable_for_inputs"
        if selected_tool is None and tool_status.get("vina", {}).get("available"):
            warning = (
                "vina_inputs_preparation_failed"
                if preparation_warnings
                else "vina_requires_prepared_pdbqt_inputs"
            )
        return DockingToolResult(
            adapter_mode="external_docking_unavailable",
            tool_name="external_docking",
            success=False,
            labels=["external_docking_adapter_failed"],
            warnings=_dedupe(preparation_warnings + [warning]),
        )
    if preparation_warnings:
        external_result = replace(
            external_result,
            warnings=_dedupe(preparation_warnings + external_result.warnings),
        )
    if external_result.success and selected_tool == "vina":
        gnina_status = tool_status.get("gnina", {})
        reason = (
            "gnina_gpu_unavailable_vina_cpu_fallback"
            if gnina_status.get("available") and gnina_status.get("gpu_available") is False
            else "gnina_unavailable_vina_cpu_fallback"
        )
        return _mark_vina_cpu_fallback(
            external_result,
            reason=reason,
            source_result=None,
            preparation_warnings=preparation_warnings,
        )
    return external_result


def _should_prepare_vina_inputs(
    tool_status: dict[str, Any],
    receptor_file: str,
    ligand_file: str | None,
    grid_center: list[float] | None,
    grid_size: list[float] | None,
) -> bool:
    if not tool_status.get("vina", {}).get("available"):
        return False
    if _gnina_gpu_docking_available(tool_status):
        return False
    receptor_ready = is_valid_vina_receptor_pdbqt(Path(receptor_file))
    ligand_ready = bool(ligand_file) and is_valid_vina_ligand_pdbqt(Path(ligand_file))
    return not (receptor_ready and ligand_ready)


def _mark_vina_cpu_fallback(
    result: DockingToolResult,
    *,
    reason: str,
    source_result: DockingToolResult | None,
    preparation_warnings: list[str],
) -> DockingToolResult:
    fallback = {
        "from_tool": source_result.tool_name if source_result is not None else "gnina",
        "to_tool": "vina",
        "reason": reason,
        "source_exit_code": source_result.exit_code if source_result is not None else None,
    }
    return replace(
        result,
        labels=_dedupe([*(result.labels or []), "vina_cpu_fallback"]),
        warnings=_dedupe([*preparation_warnings, *(result.warnings or []), reason]),
        provenance={
            **(result.provenance or {}),
            "gpu_used": False,
            "fallback": fallback,
        },
    )


def _prepare_vina_docking_inputs(
    project: Project,
    molecule: Molecule,
    receptor_file: str,
    ligand_file: str | None,
) -> tuple[str, str | None, list[str]]:
    warnings: list[str] = []
    prepared_receptor_file = receptor_file
    prepared_ligand_file = ligand_file

    receptor_path = Path(receptor_file)
    receptor_dir = ASSESSMENT_RUNTIME_ROOT / _safe_path_part(project.project_id) / "receptors"
    if not is_valid_vina_receptor_pdbqt(receptor_path):
        existing_receptor = _existing_vina_receptor_file(receptor_path, receptor_dir)
        if existing_receptor is not None:
            prepared_receptor_file = str(existing_receptor)
        else:
            receptor_pdbqt, receptor_warnings = _prepare_vina_receptor_file(
                receptor_path,
                receptor_dir,
            )
            if receptor_pdbqt is not None:
                prepared_receptor_file = receptor_pdbqt
            else:
                warnings.extend(receptor_warnings)

    if not prepared_ligand_file or not is_valid_vina_ligand_pdbqt(Path(prepared_ligand_file)):
        ligand_dir = ASSESSMENT_RUNTIME_ROOT / _safe_path_part(project.project_id) / "ligands"
        existing_ligand = _existing_vina_ligand_file(molecule, ligand_dir)
        if existing_ligand is not None:
            prepared_ligand_file = str(existing_ligand)
        else:
            try:
                ligand_result = prepare_ligand_from_smiles(
                    molecule.smiles,
                    ligand_dir,
                    _safe_path_part(molecule.molecule_id),
                    target_format="pdbqt",
                    add_hydrogens=True,
                    generate_3d=True,
                    num_conformers=1,
                )
                if _is_successful_pdbqt_result(ligand_result.ligand_file, ligand_result.format):
                    prepared_ligand_file = str(ligand_result.ligand_file)
                else:
                    warnings.extend(
                        _vina_preparation_warnings(
                            "vina_ligand_pdbqt_preparation_failed",
                            ligand_result.warnings,
                        )
                    )
            except Exception as exc:
                warnings.extend(
                    _vina_preparation_warnings(
                        "vina_ligand_pdbqt_preparation_failed",
                        [type(exc).__name__],
                    )
                )

    if not (
        _is_valid_vina_receptor_path(prepared_receptor_file)
        and _is_existing_pdbqt_path(prepared_ligand_file)
    ):
        return receptor_file, ligand_file, _dedupe(warnings)
    return prepared_receptor_file, prepared_ligand_file, _dedupe(warnings)


def _existing_vina_receptor_file(receptor_path: Path, output_dir: Path) -> Path | None:
    candidates = [
        receptor_path,
        output_dir / f"{_safe_path_part(receptor_path.stem)}.pdbqt",
        output_dir / f"{receptor_path.stem}_prepared.pdbqt",
        output_dir / f"{receptor_path.stem}_temp.pdbqt",
        output_dir / f"{receptor_path.stem}.pdbqt",
    ]
    return _first_existing_pdbqt_file(candidates, validator=is_valid_vina_receptor_pdbqt)


def _prepare_vina_receptor_file(receptor_path: Path, output_dir: Path) -> tuple[str | None, list[str]]:
    obabel = shutil.which("obabel")
    if obabel is None:
        return None, _vina_preparation_warnings(
            "vina_receptor_pdbqt_preparation_failed",
            ["obabel_not_available"],
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    input_format = receptor_path.suffix.lstrip(".") or "pdb"
    output_path = output_dir / f"{_safe_path_part(receptor_path.stem)}.pdbqt"
    temp_handle = tempfile.NamedTemporaryFile(
        prefix=f".{_safe_path_part(receptor_path.stem)}.",
        suffix=".pdbqt",
        dir=output_dir,
        delete=False,
    )
    temp_path = Path(temp_handle.name)
    temp_handle.close()
    temp_path.unlink(missing_ok=True)
    command = [
        obabel,
        f"-i{input_format}",
        str(receptor_path),
        "-opdbqt",
        "-O",
        str(temp_path),
        "-xr",
    ]

    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except subprocess.TimeoutExpired:
        temp_path.unlink(missing_ok=True)
        return None, _vina_preparation_warnings(
            "vina_receptor_pdbqt_preparation_failed",
            ["obabel_timeout"],
        )
    except OSError as exc:
        temp_path.unlink(missing_ok=True)
        return None, _vina_preparation_warnings(
            "vina_receptor_pdbqt_preparation_failed",
            [type(exc).__name__],
        )

    try:
        if completed.returncode != 0:
            return None, _vina_preparation_warnings(
                "vina_receptor_pdbqt_preparation_failed",
                [f"obabel_exit_code_{completed.returncode}"],
            )
        if not is_valid_vina_receptor_pdbqt(temp_path):
            return None, _vina_preparation_warnings(
                "vina_receptor_pdbqt_preparation_failed",
                ["invalid_rigid_receptor_pdbqt"],
            )
        temp_path.replace(output_path)
        return str(output_path), []
    finally:
        temp_path.unlink(missing_ok=True)


def _existing_vina_ligand_file(molecule: Molecule, output_dir: Path) -> Path | None:
    safe_molecule_id = _safe_path_part(molecule.molecule_id)
    candidates = [
        output_dir / f"{safe_molecule_id}_ligand.pdbqt",
        output_dir / f"{safe_molecule_id}.pdbqt",
    ]
    return _first_existing_pdbqt_file(candidates, validator=is_valid_vina_ligand_pdbqt)


def _first_existing_pdbqt_file(
    candidates: list[Path],
    validator=None,
) -> Path | None:
    for candidate in candidates:
        if candidate.suffix.lower() != ".pdbqt" or not candidate.exists():
            continue
        if validator is None or validator(candidate):
            return candidate
    return None


def _is_successful_pdbqt_result(file_path: str | None, file_format: str | None) -> bool:
    if file_format != "pdbqt" or not file_path:
        return False
    return is_valid_vina_ligand_pdbqt(Path(file_path))


def _is_existing_pdbqt_path(file_path: str | None) -> bool:
    if not file_path:
        return False
    return is_valid_vina_ligand_pdbqt(Path(file_path))


def _is_valid_vina_receptor_path(file_path: str | None) -> bool:
    return bool(file_path) and is_valid_vina_receptor_pdbqt(Path(file_path))


def _docking_timeout_seconds(configured_timeout: Any = None) -> int:
    raw_value = os.environ.get("MEDAGENT_DOCKING_TIMEOUT_SECONDS")
    if raw_value is None:
        raw_value = configured_timeout if configured_timeout is not None else 900
    try:
        return max(30, int(raw_value))
    except (TypeError, ValueError):
        return 900


def _vina_preparation_warnings(prefix: str, details: list[str] | None) -> list[str]:
    warnings = [prefix]
    warnings.extend(f"{prefix}:{detail}" for detail in details or [] if detail)
    return warnings


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


def _diffdock_ligand_file(
    project: Project,
    molecule: Molecule,
    ligand_file: str | None,
) -> str | None:
    if ligand_file and Path(ligand_file).suffix.lower() == ".sdf":
        return ligand_file
    return _write_ligand_sdf(project, molecule)


def _is_vector3(values: list[float] | None) -> bool:
    return values is not None and len(values) == 3


def _safe_path_part(value: str) -> str:
    safe = "".join(char if char.isalnum() or char in "._-" else "_" for char in value)
    return safe.strip("._") or "item"


def _smiles_input_hash(smiles: str) -> str:
    return hashlib.sha256(smiles.encode("utf-8")).hexdigest()


def _external_docking_available(tool_status: dict[str, Any]) -> bool:
    return bool(
        _gnina_gpu_docking_available(tool_status)
        or tool_status["vina"]["available"]
    )


def _gnina_gpu_docking_available(tool_status: dict[str, Any]) -> bool:
    gnina_status = tool_status.get("gnina", {})
    return bool(
        gnina_status.get("available")
        and not (
            gnina_status.get("mode") == "docker"
            and gnina_status.get("gpu_available") is False
        )
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
