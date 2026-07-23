"""Persistence primitives for immutable workflow packets and audited stage runs."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from medagent.db.models import (
    ApprovalEvent,
    CapabilitySnapshotRecord,
    ExecutionManifest,
    ExecutionPlanRecord,
    ScientificArtifact,
    ScientificJob,
    WorkflowPacket,
)
from medagent.services.ids import new_id
from medagent.services.scientific_execution import (
    CapabilitySnapshot,
    ExecutionPlan,
    ScientificResult,
    canonical_json_hash,
)


JOB_TRANSITIONS = {
    "queued": {"claimed", "cancelled"},
    "claimed": {"running", "queued", "cancelled"},
    "running": {"succeeded", "failed", "cancelled", "interrupted"},
    "interrupted": {"queued", "cancelled"},
    "succeeded": set(),
    "failed": set(),
    "cancelled": set(),
}


def persist_capability_snapshot(
    db: Session,
    snapshot: CapabilitySnapshot,
    *,
    project_id: str | None = None,
    round_id: str | None = None,
) -> CapabilitySnapshotRecord:
    record = (
        db.query(CapabilitySnapshotRecord)
        .filter_by(snapshot_hash=snapshot.snapshot_hash)
        .one_or_none()
    )
    if record is None:
        record = CapabilitySnapshotRecord(
            snapshot_id=snapshot.snapshot_id,
            snapshot_hash=snapshot.snapshot_hash,
            project_id=project_id,
            round_id=round_id,
            snapshot_json=snapshot.as_dict(),
        )
        db.add(record)
        db.flush()
    return record


def persist_execution_plan(
    db: Session,
    plan: ExecutionPlan,
    *,
    project_id: str | None = None,
    round_id: str | None = None,
) -> ExecutionPlanRecord:
    payload = plan.as_dict()
    plan_hash = canonical_json_hash(payload)
    record = db.query(ExecutionPlanRecord).filter_by(plan_hash=plan_hash).one_or_none()
    if record is None:
        record = ExecutionPlanRecord(
            plan_id=new_id("PLAN"),
            plan_hash=plan_hash,
            project_id=project_id,
            round_id=round_id,
            capability_snapshot_id=plan.capability_snapshot_id,
            status="blocked" if not plan.formal_round_allowed else "planned",
            plan_json=payload,
        )
        db.add(record)
        db.flush()
    return record


def create_workflow_packet(
    db: Session,
    *,
    packet_type: str,
    project_id: str,
    round_id: str | None,
    payload: dict[str, Any],
    parameter_snapshot: dict[str, Any] | None = None,
    evidence_summary: dict[str, Any] | None = None,
    parent_packet_id: str | None = None,
) -> WorkflowPacket:
    """Create, never mutate, a versioned data hand-off between workflow stages."""
    parameters = dict(parameter_snapshot or {})
    evidence = dict(evidence_summary or {})
    input_hash = canonical_json_hash(
        {
            "packet_type": packet_type,
            "payload": payload,
            "parameter_snapshot": parameters,
            "evidence_summary": evidence,
            "parent_packet_id": parent_packet_id,
        }
    )
    packet = WorkflowPacket(
        packet_id=new_id("PACKET"),
        packet_type=packet_type,
        packet_version=1,
        parent_packet_id=parent_packet_id,
        project_id=project_id,
        round_id=round_id,
        input_hash=input_hash,
        parameter_snapshot_json=parameters,
        evidence_summary_json=evidence,
        payload_json=dict(payload),
    )
    db.add(packet)
    db.flush()
    return packet


def create_job(
    db: Session,
    *,
    project_id: str,
    stage: str,
    input_snapshot: dict[str, Any],
    round_id: str | None = None,
) -> ScientificJob:
    job = ScientificJob(
        job_id=new_id("JOB"),
        project_id=project_id,
        round_id=round_id,
        stage=stage,
        status="queued",
        input_snapshot_json=dict(input_snapshot),
    )
    db.add(job)
    db.flush()
    return job


def transition_job(
    db: Session,
    job: ScientificJob,
    status: str,
    *,
    worker_id: str | None = None,
    result: dict[str, Any] | None = None,
    error_message: str | None = None,
) -> ScientificJob:
    """Move a durable job through the only allowed state transitions."""
    if status not in JOB_TRANSITIONS.get(job.status, set()):
        raise ValueError(f"Cannot transition job {job.job_id} from {job.status} to {status}")
    now = datetime.now(UTC)
    job.status = status
    if status == "claimed":
        job.claimed_by = worker_id
        job.claimed_at = now
        job.attempt += 1
    elif status == "running":
        job.started_at = now
    elif status in {"succeeded", "failed", "cancelled", "interrupted"}:
        job.completed_at = now
    if result is not None:
        job.result_json = dict(result)
    if error_message is not None:
        job.error_message = error_message
    db.flush()
    return job


def persist_scientific_result(
    db: Session,
    result: ScientificResult,
    *,
    snapshot: CapabilitySnapshot,
    request: dict[str, Any],
    project_id: str | None = None,
    round_id: str | None = None,
    job_id: str | None = None,
    policy_name: str = "scientific_execution",
    policy_version: str = "1.0",
) -> ExecutionManifest:
    """Persist an auditable manifest and materialize any real output artifacts."""
    input_artifacts = _persist_artifacts(db, result.input_artifacts, result.tool_name, result.tool_version)
    output_artifacts = _persist_artifacts(db, result.output_artifacts, result.tool_name, result.tool_version)
    result.input_artifacts = input_artifacts
    result.output_artifacts = output_artifacts
    manifest_payload = result.manifest_payload()
    manifest_hash = canonical_json_hash(
        {
            "request": request,
            "result": manifest_payload,
            "snapshot_hash": snapshot.snapshot_hash,
            "policy_name": policy_name,
            "policy_version": policy_version,
        }
    )
    manifest = db.query(ExecutionManifest).filter_by(manifest_hash=manifest_hash).one_or_none()
    if manifest is not None:
        return manifest

    provenance = dict(result.provenance or {})
    started_at = datetime.now(UTC)
    manifest = ExecutionManifest(
        manifest_id=new_id("MANIFEST"),
        manifest_hash=manifest_hash,
        project_id=project_id,
        round_id=round_id,
        job_id=job_id,
        stage=result.stage,
        status=result.status,
        request_hash=canonical_json_hash(request),
        policy_name=policy_name,
        policy_version=policy_version,
        capability_snapshot_hash=snapshot.snapshot_hash,
        source_release_ids=list(snapshot.source_release_ids),
        command=list(provenance.get("command") or []),
        environment_json=dict(snapshot.runtime or {}),
        input_artifacts=input_artifacts,
        output_artifacts=output_artifacts,
        stdout=_truncate(provenance.get("stdout")),
        stderr=_truncate(provenance.get("stderr")),
        started_at=started_at,
        completed_at=datetime.now(UTC),
        exit_code=provenance.get("exit_code"),
        result_json=result.as_dict(),
    )
    db.add(manifest)
    db.flush()
    return manifest


def request_approval(
    db: Session,
    *,
    project_id: str,
    event_type: str,
    request: dict[str, Any],
    round_id: str | None = None,
    requested_by: str | None = None,
) -> ApprovalEvent:
    approval = ApprovalEvent(
        approval_id=new_id("APPROVAL"),
        project_id=project_id,
        round_id=round_id,
        event_type=event_type,
        status="pending",
        requested_by=requested_by,
        request_json=dict(request),
    )
    db.add(approval)
    db.flush()
    return approval


def decide_approval(
    db: Session,
    approval: ApprovalEvent,
    *,
    approved: bool,
    decided_by: str,
    rationale: str | None = None,
    decision: dict[str, Any] | None = None,
) -> ApprovalEvent:
    if approval.status != "pending":
        raise ValueError(f"Approval {approval.approval_id} is already {approval.status}")
    approval.status = "approved" if approved else "rejected"
    approval.decided_by = decided_by
    approval.rationale = rationale
    approval.decision_json = dict(decision or {})
    approval.decided_at = datetime.now(UTC)
    db.flush()
    return approval


def _persist_artifacts(
    db: Session,
    artifacts: dict[str, dict[str, Any]],
    tool_name: str | None,
    tool_version: str | None,
) -> dict[str, dict[str, Any]]:
    persisted: dict[str, dict[str, Any]] = {}
    for role, artifact in artifacts.items():
        uri = str(artifact.get("uri") or "")
        sha256 = str(artifact.get("sha256") or "")
        if not uri or not sha256:
            continue
        record = (
            db.query(ScientificArtifact)
            .filter_by(uri=uri, sha256=sha256)
            .one_or_none()
        )
        if record is None:
            record = ScientificArtifact(
                artifact_id=new_id("ART"),
                artifact_type=_artifact_type(uri),
                uri=uri,
                sha256=sha256,
                size_bytes=int(artifact.get("size_bytes") or 0),
                producer_tool=tool_name,
                producer_version=tool_version,
            )
            db.add(record)
            db.flush()
        persisted[role] = {**artifact, "artifact_id": record.artifact_id}
    return persisted


def _artifact_type(uri: str) -> str:
    suffix = Path(uri).suffix.lower().lstrip(".")
    return suffix or "artifact"


def _truncate(value: Any, limit: int = 20000) -> str | None:
    text = str(value or "")
    return text[:limit] if text else None
