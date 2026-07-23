"""API surface for capability preflight, audit manifests and human approvals."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from medagent.db.models import ApprovalEvent, ExecutionManifest, Project, ProjectRound, TargetResourcePackage
from medagent.db.session import get_db
from medagent.services.scientific_persistence import decide_approval, request_approval
from medagent.services.scientific_workflow import prepare_round_preflight
from medagent.services.target_resource_packages import target_resource_readiness


router = APIRouter(prefix="/scientific", tags=["Scientific execution"])


class PreflightRequest(BaseModel):
    round_id: str | None = None
    formal_round: bool = False
    require_external_evidence_for_ranking: bool = False


class ApprovalRequest(BaseModel):
    event_type: str = Field(min_length=3, max_length=120)
    request: dict[str, Any] = Field(default_factory=dict)
    round_id: str | None = None
    requested_by: str | None = None


class ApprovalDecisionRequest(BaseModel):
    approved: bool
    decided_by: str = Field(min_length=1, max_length=120)
    rationale: str | None = None
    decision: dict[str, Any] = Field(default_factory=dict)


@router.get("/targets/{target_id}/resource-package")
def get_target_resource_package(target_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    resource, release_ids = target_resource_readiness(db, target_id)
    if resource.get("package_status") == "missing":
        raise HTTPException(404, "Target resource package not found")
    package = db.query(TargetResourcePackage).filter_by(target_id=target_id, package_version="v1").one()
    return {
        "package_id": package.package_id,
        "target_id": package.target_id,
        "status": package.status,
        "resource": resource,
        "source_release_ids": release_ids,
        "warnings": package.warnings or [],
    }


@router.post("/projects/{project_id}/preflight")
def create_preflight(
    project_id: str,
    body: PreflightRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    project = db.query(Project).filter_by(project_id=project_id).one_or_none()
    if project is None:
        raise HTTPException(404, "Project not found")
    round_obj = None
    if body.round_id:
        round_obj = (
            db.query(ProjectRound)
            .filter_by(project_id=project_id, round_id=body.round_id)
            .one_or_none()
        )
        if round_obj is None:
            raise HTTPException(404, "Round not found")
    output = prepare_round_preflight(
        db,
        project,
        round_obj,
        formal_round=body.formal_round,
        require_external_evidence_for_ranking=body.require_external_evidence_for_ranking,
    )
    db.commit()
    return output


@router.get("/projects/{project_id}/execution-manifests")
def list_execution_manifests(
    project_id: str,
    round_id: str | None = None,
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    query = db.query(ExecutionManifest).filter_by(project_id=project_id)
    if round_id:
        query = query.filter_by(round_id=round_id)
    manifests = query.order_by(ExecutionManifest.created_at.desc()).all()
    return [
        {
            "manifest_id": manifest.manifest_id,
            "manifest_hash": manifest.manifest_hash,
            "stage": manifest.stage,
            "status": manifest.status,
            "request_hash": manifest.request_hash,
            "capability_snapshot_hash": manifest.capability_snapshot_hash,
            "source_release_ids": manifest.source_release_ids or [],
            "input_artifacts": manifest.input_artifacts or {},
            "output_artifacts": manifest.output_artifacts or {},
            "result": manifest.result_json or {},
            "created_at": manifest.created_at,
        }
        for manifest in manifests
    ]


@router.post("/projects/{project_id}/approvals")
def create_approval(
    project_id: str,
    body: ApprovalRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    if db.query(Project).filter_by(project_id=project_id).one_or_none() is None:
        raise HTTPException(404, "Project not found")
    approval = request_approval(
        db,
        project_id=project_id,
        round_id=body.round_id,
        event_type=body.event_type,
        request=body.request,
        requested_by=body.requested_by,
    )
    db.commit()
    return {"approval_id": approval.approval_id, "status": approval.status}


@router.post("/approvals/{approval_id}/decision")
def decide_approval_event(
    approval_id: str,
    body: ApprovalDecisionRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    approval = db.query(ApprovalEvent).filter_by(approval_id=approval_id).one_or_none()
    if approval is None:
        raise HTTPException(404, "Approval not found")
    try:
        decide_approval(
            db,
            approval,
            approved=body.approved,
            decided_by=body.decided_by,
            rationale=body.rationale,
            decision=body.decision,
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    db.commit()
    return {"approval_id": approval.approval_id, "status": approval.status}
