"""Preflight and stage-gating helpers for the reproducible round workflow."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from medagent.db.models import (
    BindingSite,
    Project,
    ProjectRound,
    ProjectStructure,
    ScientificArtifact,
    UploadedFile,
)
from medagent.services.scientific_execution import (
    CapabilitySnapshot,
    build_execution_plan,
    sha256_file,
)
from medagent.services.scientific_persistence import (
    create_job,
    create_workflow_packet,
    persist_scientific_result,
    persist_capability_snapshot,
    persist_execution_plan,
    transition_job,
)
from medagent.services.scientific_execution import EvidenceKind, EvidenceLevel, ScientificResult
from medagent.services.target_resource_packages import (
    seed_golden_target_resource_packages,
    target_resource_readiness,
)


def collect_tool_capabilities() -> dict[str, dict[str, Any]]:
    """Probe local runtime adapters once and preserve their exact status in a snapshot."""
    from medagent.services.admet_adapter import check_chemprop_available
    from medagent.services.aizynthfinder_adapter import aizynthfinder_tool_status
    from medagent.services.autogrow4_adapter import autogrow4_tool_status
    from medagent.services.docking_adapters import check_gnina_available, check_vina_available
    from medagent.services.molecule_generation import generation_tool_status
    from medagent.services.p2rank_adapter import p2rank_tool_status
    from medagent.services.targetdiff_adapter import targetdiff_tool_status

    generation = generation_tool_status()
    chemprop = check_chemprop_available()
    return {
        "crem": dict(generation.get("crem") or {}),
        "targetdiff": dict(targetdiff_tool_status() or {}),
        "p2rank": dict(p2rank_tool_status() or {}),
        "autogrow4": dict(autogrow4_tool_status() or {}),
        "vina": dict(check_vina_available() or {}),
        "gnina": dict(check_gnina_available() or {}),
        "admet_ai": dict(chemprop),
        "chemprop": dict(chemprop),
        "aizynthfinder": dict(aizynthfinder_tool_status() or {}),
        "rdkit": _rdkit_capability(),
    }


def prepare_round_preflight(
    db: Session,
    project: Project,
    round_obj: ProjectRound | None = None,
    *,
    formal_round: bool = False,
    tool_capabilities: dict[str, dict[str, Any]] | None = None,
    require_external_evidence_for_ranking: bool = False,
) -> dict[str, Any]:
    """Freeze capability/resource state and create immutable hand-off packets."""
    seed_golden_target_resource_packages(db)
    resource, release_ids = target_resource_readiness(db, project.target_id)
    resource = _overlay_project_predicted_pocket(db, project, resource)
    tools = collect_tool_capabilities() if tool_capabilities is None else tool_capabilities
    runtime = {
        "wsl_available": any(
            tool.get("runtime_scope") == "wsl" or tool.get("runtime") == "wsl"
            for tool in tools.values()
        ),
        "gpu_available": any(bool(tool.get("gpu_available")) for tool in tools.values()),
    }
    snapshot = CapabilitySnapshot.create(
        tools=tools,
        source_release_ids=release_ids,
        target_resource=resource,
        runtime=runtime,
    )
    plan = build_execution_plan(
        snapshot,
        formal_round=formal_round,
        require_external_evidence_for_ranking=require_external_evidence_for_ranking,
    )
    round_id = round_obj.round_id if round_obj else None
    snapshot_record = persist_capability_snapshot(
        db, snapshot, project_id=project.project_id, round_id=round_id
    )
    plan_record = persist_execution_plan(db, plan, project_id=project.project_id, round_id=round_id)
    target_packet = create_workflow_packet(
        db,
        packet_type="target_resource_packet",
        project_id=project.project_id,
        round_id=round_id,
        payload=resource,
        parameter_snapshot={"source_release_ids": release_ids},
        evidence_summary={"package_status": resource.get("package_status")},
    )
    strategy_packet = create_workflow_packet(
        db,
        packet_type="strategy_packet",
        project_id=project.project_id,
        round_id=round_id,
        parent_packet_id=target_packet.packet_id,
        payload=plan.as_dict(),
        parameter_snapshot={"formal_round": formal_round},
        evidence_summary={"formal_round_allowed": plan.formal_round_allowed},
    )
    return {
        "snapshot": snapshot.as_dict(),
        "plan": plan.as_dict(),
        "snapshot_record_id": snapshot_record.snapshot_id,
        "plan_id": plan_record.plan_id,
        "target_resource_packet_id": target_packet.packet_id,
        "strategy_packet_id": strategy_packet.packet_id,
    }


def stage_permissions(preflight: dict[str, Any] | None) -> dict[str, bool]:
    """Extract explicit external-stage permissions from a stored preflight plan."""
    if not preflight:
        return {}
    plan = preflight.get("plan") or preflight
    stages = plan.get("stages") or []
    by_name = {stage.get("stage"): stage for stage in stages}

    def external(stage_name: str) -> bool:
        stage = by_name.get(stage_name) or {}
        return bool(stage.get("allowed")) and stage.get("evidence_level") in {"L2", "L3"}

    return {
        "docking": external("vina_screen") or external("gnina_refine"),
        "admet": external("admet_batch"),
        "synthesis": external("retrosynthesis_batch"),
        "ranking": bool((by_name.get("ranking") or {"allowed": True}).get("allowed")),
    }


def queue_round_jobs(
    db: Session,
    project: Project,
    round_obj: ProjectRound,
    preflight: dict[str, Any],
) -> dict[str, Any]:
    """Create one durable job per planned stage before any stage starts."""
    jobs: dict[str, Any] = {}
    plan = preflight["plan"]
    for stage_plan in plan.get("stages", []):
        stage = str(stage_plan["stage"])
        job = create_job(
            db,
            project_id=project.project_id,
            round_id=round_obj.round_id,
            stage=stage,
            input_snapshot={
                "capability_snapshot_hash": preflight["snapshot"]["snapshot_hash"],
                "plan_stage": stage_plan,
            },
        )
        if not stage_plan.get("allowed"):
            transition_job(
                db,
                job,
                "cancelled",
                result={"reason_codes": stage_plan.get("reason_codes", [])},
            )
        jobs[stage] = job
    return jobs


def start_round_stage_job(db: Session, job: Any) -> None:
    if job.status != "queued":
        return
    transition_job(db, job, "claimed", worker_id="round_orchestrator")
    transition_job(db, job, "running")


def record_round_stage_outcome(
    db: Session,
    *,
    project: Project,
    round_obj: ProjectRound,
    preflight: dict[str, Any],
    stage: str,
    payload: dict[str, Any],
    job: Any | None = None,
    parent_packet_id: str | None = None,
) -> dict[str, str | None]:
    """Store an immutable packet and manifest for a completed or downgraded stage."""
    stage_plan = next(
        (item for item in preflight["plan"].get("stages", []) if item.get("stage") == stage),
        None,
    )
    if stage_plan is None:
        raise KeyError(stage)
    result = _stage_result(stage, stage_plan, payload)
    snapshot = CapabilitySnapshot.create(
        tools=preflight["snapshot"].get("tools") or {},
        source_release_ids=preflight["snapshot"].get("source_release_ids") or [],
        target_resource=preflight["snapshot"].get("target_resource") or {},
        runtime=preflight["snapshot"].get("runtime") or {},
        licenses=preflight["snapshot"].get("licenses") or {},
        budget=preflight["snapshot"].get("budget") or {},
        estimated_runtime=preflight["snapshot"].get("estimated_runtime") or {},
    )
    # Recreating the value object is safe: its hash covers the immutable capability fields.
    manifest = persist_scientific_result(
        db,
        result,
        snapshot=snapshot,
        request={"stage": stage, "payload": payload},
        project_id=project.project_id,
        round_id=round_obj.round_id,
        job_id=job.job_id if job else None,
    )
    packet = create_workflow_packet(
        db,
        packet_type=_packet_type(stage),
        project_id=project.project_id,
        round_id=round_obj.round_id,
        parent_packet_id=parent_packet_id,
        payload=payload,
        parameter_snapshot={"manifest_id": manifest.manifest_id, "manifest_hash": manifest.manifest_hash},
        evidence_summary={
            "evidence_level": result.evidence_level.value,
            "execution_mode": result.execution_mode,
            "status": result.status,
        },
    )
    if job is not None and job.status == "running":
        transition_job(
            db,
            job,
            "succeeded" if result.status == "succeeded" else "failed",
            result={"manifest_id": manifest.manifest_id, "packet_id": packet.packet_id},
        )
    return {"manifest_id": manifest.manifest_id, "packet_id": packet.packet_id}


def _stage_result(stage: str, stage_plan: dict[str, Any], payload: dict[str, Any]) -> ScientificResult:
    execution_mode = str(payload.get("execution_mode") or stage_plan.get("execution_mode") or "reporting")
    external_success_count = int(payload.get("external_success_count") or 0)
    adapter_mode = str(payload.get("adapter_mode") or "")
    if payload.get("status") == "not_executed":
        return ScientificResult.unavailable(
            stage=stage,
            tool_name=stage_plan.get("tool_name"),
            status="not_executed",
            warnings=list(payload.get("warnings") or []),
        )
    if not stage_plan.get("allowed"):
        return ScientificResult.unavailable(
            stage=stage,
            tool_name=stage_plan.get("tool_name"),
            status="blocked",
            warnings=list(stage_plan.get("reason_codes") or []) + list(stage_plan.get("warnings") or []),
        )
    if (
        external_success_count
        or "local" in adapter_mode
        or (stage == "generate_candidates" and int(payload.get("completed_campaign_count") or 0))
    ):
        return ScientificResult(
            stage=stage,
            status="succeeded",
            evidence_level=EvidenceLevel.L2,
            evidence_kind=EvidenceKind.COMPUTATIONAL,
            execution_mode=execution_mode,
            tool_name=stage_plan.get("tool_name"),
            warnings=list(payload.get("warnings") or []),
            payload=payload,
        )
    return ScientificResult.surrogate(
        stage=stage,
        tool_name=stage_plan.get("tool_name") or "internal_rules",
        payload=payload,
        warnings=list(stage_plan.get("warnings") or []) + list(payload.get("warnings") or []),
    )


def _packet_type(stage: str) -> str:
    return {
        "prepare_target_resource": "target_resource_packet",
        "generate_candidates": "generation_packet",
        "vina_screen": "screening_packet",
        "gnina_refine": "external_evaluation_packet",
        "admet_batch": "external_evaluation_packet",
        "retrosynthesis_batch": "external_evaluation_packet",
        "ranking": "ranking_packet",
        "build_round_report": "report_packet",
    }.get(stage, "workflow_packet")


def _rdkit_capability() -> dict[str, Any]:
    try:
        import rdkit

        return {"available": True, "version": getattr(rdkit, "__version__", None)}
    except ImportError:
        return {"available": False, "warning": "rdkit_not_installed"}


def _overlay_project_predicted_pocket(
    db: Session,
    project: Project,
    resource: dict[str, Any],
) -> dict[str, Any]:
    """Freeze the explicitly selected project structure and P2Rank pocket.

    Predicted pockets are deliberately project-scoped: an uploaded receptor is
    not promoted into the target's shared resource package merely by running a
    computational predictor.
    """
    effective_resource = dict(resource)
    if not project.active_structure_id or not project.active_binding_site_id:
        return effective_resource

    structure = (
        db.query(ProjectStructure)
        .filter_by(
            project_id=project.project_id,
            target_id=project.target_id,
            structure_id=project.active_structure_id,
        )
        .one_or_none()
    )
    site = (
        db.query(BindingSite)
        .filter_by(
            project_id=project.project_id,
            target_id=project.target_id,
            structure_id=project.active_structure_id,
            binding_site_id=project.active_binding_site_id,
            preparation_status="pocket_predicted",
        )
        .one_or_none()
    )
    if structure is None or site is None:
        return effective_resource

    source_file = (
        db.query(UploadedFile)
        .filter_by(project_id=project.project_id, file_id=structure.source_file_id)
        .one_or_none()
    )
    artifact = (
        db.query(ScientificArtifact).filter_by(artifact_id=site.artifact_id).one_or_none()
        if site.artifact_id
        else None
    )
    grid = dict(site.grid_box or {})
    source_path = _local_artifact_path(source_file.storage_path if source_file else None)
    pocket_path = _local_artifact_path(grid.get("pocket_file"))
    prepared_path = _local_artifact_path(structure.prepared_receptor_file)
    source_metadata = dict(source_file.metadata_json or {}) if source_file else {}

    source_hash = _verified_hash(source_path, source_metadata.get("sha256"))
    pocket_hash = _verified_hash(pocket_path, artifact.sha256 if artifact else None)
    prepared_hash = _verified_hash(prepared_path, structure.prepared_receptor_sha256)
    if source_hash is None or pocket_hash is None:
        return effective_resource

    warnings = list(effective_resource.get("warnings") or [])
    if "predicted_not_experimentally_validated" not in warnings:
        warnings.append("predicted_not_experimentally_validated")
    effective_resource.update(
        {
            "package_status": "pocket_predicted",
            "structure_id": structure.structure_id,
            "binding_site_id": site.binding_site_id,
            "pocket_predicted": True,
            "targetdiff_pocket": True,
            "prepared_receptor": prepared_hash is not None,
            "source_receptor": {
                "file_id": source_file.file_id if source_file else None,
                "uri": source_file.storage_path if source_file else None,
                "sha256": source_hash,
                "size_bytes": source_path.stat().st_size if source_path else None,
            },
            "pocket_file": grid.get("pocket_file"),
            "pocket_pdb": {
                "artifact_id": artifact.artifact_id if artifact else None,
                "uri": grid.get("pocket_file"),
                "sha256": pocket_hash,
                "size_bytes": pocket_path.stat().st_size if pocket_path else None,
            },
            "prepared_receptor_pdbqt": (
                {
                    "uri": structure.prepared_receptor_file,
                    "sha256": prepared_hash,
                    "size_bytes": prepared_path.stat().st_size if prepared_path else None,
                }
                if prepared_hash is not None
                else None
            ),
            "grid": {"center": grid.get("center"), "size": grid.get("size")},
            "artifact_hashes_complete": prepared_hash is not None,
            "warnings": warnings,
        }
    )
    return effective_resource


def _local_artifact_path(uri: str | None) -> Path | None:
    if not uri:
        return None
    return Path(uri.removeprefix("local://"))


def _verified_hash(path: Path | None, expected: Any) -> str | None:
    if path is None or not path.is_file() or not isinstance(expected, str) or not expected:
        return None
    actual = sha256_file(path)
    return actual if actual == expected else None
