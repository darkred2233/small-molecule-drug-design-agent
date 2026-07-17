"""Round + Campaign API router。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from medagent.db.models import CampaignRun, Project, ProjectRound
from medagent.db.session import get_db
from medagent.domain.schemas import (
    CampaignRunRead,
    ProjectRoundRead,
    RoundCreate,
    RoundStartRequest,
)

router = APIRouter(prefix="/projects/{project_id}/rounds", tags=["rounds"])


@router.get("", response_model=list[ProjectRoundRead])
def list_rounds(project_id: str, db: Session = Depends(get_db)) -> list[ProjectRoundRead]:
    """列出项目所有轮次。"""
    _ensure_project(db, project_id)
    rounds = db.query(ProjectRound).filter(
        ProjectRound.project_id == project_id,
    ).order_by(ProjectRound.round_number).all()
    return [_round_to_read(r) for r in rounds]


@router.post("", response_model=ProjectRoundRead, status_code=201)
def create_round(project_id: str, body: RoundCreate, db: Session = Depends(get_db)) -> ProjectRoundRead:
    """创建 round draft。"""
    project = _ensure_project(db, project_id)
    from medagent.pipeline.round_orchestrator import RoundOrchestrator
    from medagent.core.config import get_settings
    orch = RoundOrchestrator(get_settings())
    pr = orch.create_round_draft(
        db, project,
        round_number=body.round_number,
        parent_round_id=body.parent_round_id,
        user_conditions=body.user_conditions_json,
    )
    db.commit()
    return _round_to_read(pr)


@router.get("/{round_id}", response_model=ProjectRoundRead)
def get_round(project_id: str, round_id: str, db: Session = Depends(get_db)) -> ProjectRoundRead:
    """获取单轮详情。"""
    pr = _get_round(db, project_id, round_id)
    return _round_to_read(pr)


@router.put("/{round_id}", response_model=ProjectRoundRead)
def update_round(project_id: str, round_id: str, body: dict[str, Any], db: Session = Depends(get_db)) -> ProjectRoundRead:
    """修改 round 配置（仅 draft 状态可修改）。"""
    pr = _get_round(db, project_id, round_id)
    if pr.status != "draft":
        raise HTTPException(400, f"Cannot modify round in status '{pr.status}'")
    if "user_conditions_json" in body:
        pr.user_conditions_json = body["user_conditions_json"]
    if "run_plan_snapshot_json" in body:
        pr.run_plan_snapshot_json = body["run_plan_snapshot_json"]
    db.commit()
    return _round_to_read(pr)


@router.post("/{round_id}/start")
def start_round(project_id: str, round_id: str, body: RoundStartRequest | None = None, db: Session = Depends(get_db)) -> dict[str, Any]:
    """启动 round 运行。"""
    project = _ensure_project(db, project_id)
    pr = _get_round(db, project_id, round_id)
    if pr.status not in ("draft", "ready"):
        raise HTTPException(400, f"Cannot start round in status '{pr.status}'")

    from medagent.pipeline.round_orchestrator import RoundOrchestrator
    from medagent.core.config import get_settings
    from medagent.domain.schemas import CampaignConfig, RunPlan

    orch = RoundOrchestrator(get_settings())

    run_plan = None
    if body and body.run_plan_override:
        run_plan = RunPlan(**body.run_plan_override)

    campaign_config = CampaignConfig()

    from medagent.db.models import SeedLigand
    seeds_db = db.query(SeedLigand).filter(
        SeedLigand.project_id == project_id,
    ).all()
    seeds = [s.smiles for s in seeds_db if s.smiles]

    result = orch.run_round(
        db, project, pr, campaign_config, run_plan, seeds=seeds
    )
    db.commit()
    return result


@router.get("/{round_id}/campaigns", response_model=list[CampaignRunRead])
def list_campaigns(project_id: str, round_id: str, db: Session = Depends(get_db)) -> list[CampaignRunRead]:
    """获取 round 的 campaign 运行记录。"""
    _get_round(db, project_id, round_id)
    campaigns = db.query(CampaignRun).filter(
        CampaignRun.round_id == round_id,
    ).order_by(CampaignRun.created_at).all()
    return [_campaign_to_read(c) for c in campaigns]


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _ensure_project(db: Session, project_id: str) -> Project:
    project = db.query(Project).filter(Project.project_id == project_id).first()
    if not project:
        raise HTTPException(404, f"Project {project_id} not found")
    return project


def _get_round(db: Session, project_id: str, round_id: str) -> ProjectRound:
    pr = db.query(ProjectRound).filter(
        ProjectRound.round_id == round_id,
        ProjectRound.project_id == project_id,
    ).first()
    if not pr:
        raise HTTPException(404, f"Round {round_id} not found")
    return pr


def _round_to_read(pr: ProjectRound) -> ProjectRoundRead:
    return ProjectRoundRead(
        round_id=pr.round_id,
        project_id=pr.project_id,
        round_number=pr.round_number,
        status=pr.status,
        parent_round_id=pr.parent_round_id,
        user_conditions_json=pr.user_conditions_json,
        run_plan_snapshot_json=pr.run_plan_snapshot_json,
        started_at=pr.started_at,
        completed_at=pr.completed_at,
        created_at=pr.created_at,
    )


def _campaign_to_read(c: CampaignRun) -> CampaignRunRead:
    return CampaignRunRead(
        campaign_run_id=c.campaign_run_id,
        round_id=c.round_id,
        project_id=c.project_id,
        method=c.method,
        status=c.status,
        config_json=c.config_json,
        resource_bundle_json=c.resource_bundle_json,
        input_molecule_ids=c.input_molecule_ids,
        output_molecule_ids=c.output_molecule_ids,
        metrics_json=c.metrics_json,
        warnings_json=c.warnings_json,
        started_at=c.started_at,
        completed_at=c.completed_at,
        created_at=c.created_at,
    )
