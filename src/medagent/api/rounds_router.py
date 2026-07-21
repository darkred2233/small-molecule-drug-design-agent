"""Round + Campaign API router。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from medagent.db.models import CampaignRun, Project, ProjectRound, RoundReport
from medagent.db.session import get_db
from medagent.services.ids import new_id
from medagent.domain.schemas import (
    CampaignRunRead,
    ProjectRoundRead,
    RoundCreate,
    RoundStartRequest,
    RoundStrategyConfirmRequest,
    RoundStrategyDraftRead,
    RoundStrategyDraftRequest,
    RoundStrategyExecuteResponse,
    RoundStrategyReviseRequest,
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
    if "execution_config_snapshot_json" in body:
        pr.execution_config_snapshot_json = body["execution_config_snapshot_json"]
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
    orch = RoundOrchestrator(get_settings())

    campaign_config = _campaign_config_from_payload(body.campaign_config if body else None)
    assessment_config = body.assessment_config if body else None

    from medagent.db.models import SeedLigand
    seeds_db = db.query(SeedLigand).filter(
        SeedLigand.project_id == project_id,
    ).all()
    seeds = [s.smiles for s in seeds_db if s.smiles]
    seed_molecule_ids = [s.ligand_id for s in seeds_db if s.smiles]

    result = orch.run_round(
        db,
        project,
        pr,
        campaign_config,
        assessment_config=assessment_config,
        seeds=seeds,
        seed_molecule_ids=seed_molecule_ids,
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


@router.get("/{round_id}/molecules", response_model=list)
def list_round_molecules(
    project_id: str,
    round_id: str,
    db: Session = Depends(get_db),
):
    """获取本轮生成的所有分子。"""
    from medagent.db.models import Molecule
    from medagent.domain.schemas import MoleculeRead

    _get_round(db, project_id, round_id)
    molecules = db.query(Molecule).filter_by(
        project_id=project_id,
        round_id=round_id,
    ).order_by(Molecule.created_at).all()

    return [
        MoleculeRead(
            molecule_id=m.molecule_id,
            smiles=m.smiles,
            scaffold=m.scaffold,
            status=m.status,
            labels=m.labels,
            source_agent=m.source_agent,
            round_id=m.round_id,
            campaign_run_id=m.campaign_run_id,
            generation_method=m.generation_method,
            parent_molecule_ids=m.parent_molecule_ids or [],
            provenance_json=m.provenance_json or {},
            generation_metadata_json=m.generation_metadata_json or {},
        )
        for m in molecules
    ]


@router.get("/{round_id}/rankings", response_model=list)
def list_round_rankings(
    project_id: str,
    round_id: str,
    db: Session = Depends(get_db),
):
    """获取本轮的排名结果。"""
    from medagent.db.models import Ranking
    from medagent.domain.schemas import RankingRead

    _get_round(db, project_id, round_id)
    rankings = db.query(Ranking).filter_by(round_id=round_id).order_by(Ranking.rank.asc()).all()

    return [
        RankingRead(
            molecule_id=r.molecule_id,
            round_id=r.round_id,
            rank=r.rank,
            pro_score=r.pro_score,
            con_score=r.con_score,
            evidence_confidence=r.evidence_confidence,
            overall_score=r.overall_score,
            final_decision=r.final_decision,
            score_breakdown=r.score_breakdown or {},
        )
        for r in rankings
    ]


@router.get("/{round_id}/docking-results", response_model=list)
def list_round_docking_results(
    project_id: str,
    round_id: str,
    db: Session = Depends(get_db),
):
    """获取本轮的对接结果。"""
    from medagent.db.models import DockingResult, Molecule
    from medagent.domain.schemas import DockingResultRead

    _get_round(db, project_id, round_id)
    results = (
        db.query(DockingResult)
        .join(Molecule, DockingResult.molecule_id == Molecule.molecule_id)
        .filter(Molecule.round_id == round_id)
        .order_by(DockingResult.created_at)
        .all()
    )

    return [
        DockingResultRead(
            molecule_id=r.molecule_id,
            round_id=r.round_id,
            vina_score=r.vina_score,
            cnn_score=r.cnn_score,
            diffdock_confidence=r.diffdock_confidence,
            key_hbond_count=r.key_hbond_count,
            clash_count=r.clash_count,
            pose_file=r.pose_file,
            labels=r.labels or [],
            raw_output=r.raw_output or {},
        )
        for r in results
    ]


@router.get("/{round_id}/admet-results", response_model=list)
def list_round_admet_results(
    project_id: str,
    round_id: str,
    db: Session = Depends(get_db),
):
    """获取本轮的 ADMET 结果。"""
    from medagent.db.models import ADMETResult, Molecule
    from medagent.domain.schemas import ADMETResultRead

    _get_round(db, project_id, round_id)
    results = (
        db.query(ADMETResult)
        .join(Molecule, ADMETResult.molecule_id == Molecule.molecule_id)
        .filter(Molecule.round_id == round_id)
        .order_by(ADMETResult.created_at)
        .all()
    )

    return [
        ADMETResultRead(
            molecule_id=r.molecule_id,
            round_id=r.round_id,
            hERG_probability=r.hERG_probability,
            hERG_risk=r.hERG_risk,
            Ames_probability=r.Ames_probability,
            Ames_risk=r.Ames_risk,
            solubility=r.solubility,
            permeability=r.permeability,
            admet_risk_score=r.admet_risk_score,
            labels=r.labels or [],
            raw_output=r.raw_output or {},
        )
        for r in results
    ]


@router.get("/{round_id}/synthesis-routes", response_model=list)
def list_round_synthesis_routes(
    project_id: str,
    round_id: str,
    db: Session = Depends(get_db),
):
    """获取本轮的合成路线。"""
    from medagent.db.models import Molecule, SynthesisRoute
    from medagent.domain.schemas import SynthesisRouteRead

    _get_round(db, project_id, round_id)
    results = (
        db.query(SynthesisRoute)
        .join(Molecule, SynthesisRoute.molecule_id == Molecule.molecule_id)
        .filter(Molecule.round_id == round_id)
        .order_by(SynthesisRoute.created_at)
        .all()
    )

    return [
        SynthesisRouteRead(
            molecule_id=r.molecule_id,
            round_id=r.round_id,
            route_found=r.route_found,
            route_steps=r.route_steps,
            route_confidence=r.route_confidence,
            buyable_building_blocks=r.buyable_building_blocks,
            labels=r.labels or [],
            route_json=r.route_json or {},
        )
        for r in results
    ]


@router.get("/{round_id}/summary")
def get_round_summary(
    project_id: str,
    round_id: str,
    db: Session = Depends(get_db),
):
    """获取本轮的汇总统计。"""
    from medagent.db.models import ADMETResult, DockingResult, Molecule, Ranking, SynthesisRoute

    round_obj = _get_round(db, project_id, round_id)

    # 统计分子数
    molecule_count = db.query(Molecule).filter_by(round_id=round_id).count()

    # 统计评估结果数
    docking_count = (
        db.query(DockingResult)
        .join(Molecule, DockingResult.molecule_id == Molecule.molecule_id)
        .filter(Molecule.round_id == round_id)
        .count()
    )

    admet_count = (
        db.query(ADMETResult)
        .join(Molecule, ADMETResult.molecule_id == Molecule.molecule_id)
        .filter(Molecule.round_id == round_id)
        .count()
    )

    synthesis_count = (
        db.query(SynthesisRoute)
        .join(Molecule, SynthesisRoute.molecule_id == Molecule.molecule_id)
        .filter(Molecule.round_id == round_id)
        .count()
    )

    ranking_count = db.query(Ranking).filter_by(round_id=round_id).count()

    # 获取 Top 5 分子
    top_rankings = db.query(Ranking).filter_by(round_id=round_id).order_by(Ranking.rank.asc()).limit(5).all()
    top_molecules = [
        {
            "molecule_id": r.molecule_id,
            "rank": r.rank,
            "overall_score": r.overall_score,
            "final_decision": r.final_decision,
        }
        for r in top_rankings
    ]

    # 获取 campaign 统计
    campaigns = db.query(CampaignRun).filter_by(round_id=round_id).all()
    campaign_summary = [
        {
            "campaign_run_id": c.campaign_run_id,
            "method": c.method,
            "status": c.status,
            "output_count": len(c.output_molecule_ids or []),
        }
        for c in campaigns
    ]

    return {
        "round_id": round_obj.round_id,
        "round_number": round_obj.round_number,
        "status": round_obj.status,
        "started_at": round_obj.started_at,
        "completed_at": round_obj.completed_at,
        "molecule_count": molecule_count,
        "docking_count": docking_count,
        "admet_count": admet_count,
        "synthesis_count": synthesis_count,
        "ranking_count": ranking_count,
        "top_molecules": top_molecules,
        "campaigns": campaign_summary,
    }


@router.get("/{round_id}/report")
def get_round_report(
    project_id: str,
    round_id: str,
    db: Session = Depends(get_db),
):
    """生成本轮的详细报告。"""
    project = _ensure_project(db, project_id)
    round_obj = _get_round(db, project_id, round_id)

    persisted = db.query(RoundReport).filter_by(round_id=round_id).one_or_none()
    if persisted is not None:
        return persisted.report_json

    from medagent.reporting.round_report import build_round_report

    report_json = build_round_report(db, project, round_obj)
    persisted = RoundReport(
        report_id=new_id("report"),
        project_id=project_id,
        round_id=round_id,
        status=round_obj.status,
        report_json=report_json,
        generated_at=datetime.now(UTC),
    )
    db.add(persisted)
    db.commit()
    return report_json


@router.post("/{round_id}/molecules/{molecule_id}/critique")
def generate_molecule_critique(
    project_id: str,
    round_id: str,
    molecule_id: str,
    db: Session = Depends(get_db),
):
    """为指定分子生成 LLM 反驳意见（仅基于数据库证据）。"""
    from medagent.db.models import AgentRun, Molecule
    from medagent.services.ids import new_id
    from medagent.services.llm_critique import generate_llm_critique

    project = _ensure_project(db, project_id)
    _get_round(db, project_id, round_id)

    # 获取分子
    molecule = db.query(Molecule).filter_by(
        molecule_id=molecule_id,
        project_id=project_id,
        round_id=round_id,
    ).first()

    if not molecule:
        raise HTTPException(404, f"分子 {molecule_id} 不存在或不属于该轮次")

    # 生成反驳
    critique_result = generate_llm_critique(db, project, molecule)

    # 记录审计
    audit_run = AgentRun(
        agent_run_id=new_id("RUN"),
        project_id=project.project_id,
        round_id=round_id,
        agent_name="llm_critique_agent",
        model_name=critique_result.get("llm_model"),
        status="completed" if critique_result.get("has_critique") else "skipped",
        input_json={
            "molecule_id": molecule_id,
            "round_id": round_id,
            "llm_provider": critique_result.get("llm_provider"),
        },
        output_json=critique_result,
    )
    db.add(audit_run)
    db.commit()

    return critique_result


@router.post("/{round_id}/critique-batch")
def generate_batch_critique(
    project_id: str,
    round_id: str,
    molecule_ids: list[str] | None = None,
    top_n: int | None = None,
    db: Session = Depends(get_db),
):
    """批量生成分子的 LLM 反驳意见。

    可以指定 molecule_ids 或 top_n（按排名取前N个）。
    """
    from medagent.db.models import AgentRun, Molecule, Ranking
    from medagent.services.ids import new_id
    from medagent.services.llm_critique import generate_llm_critique

    project = _ensure_project(db, project_id)
    _get_round(db, project_id, round_id)

    # 确定要反驳的分子列表
    if molecule_ids:
        molecules = db.query(Molecule).filter(
            Molecule.molecule_id.in_(molecule_ids),
            Molecule.project_id == project_id,
            Molecule.round_id == round_id,
        ).all()
    elif top_n:
        # 按排名取前 N 个
        rankings = db.query(Ranking).filter_by(
            round_id=round_id
        ).order_by(Ranking.rank.asc()).limit(top_n).all()

        mol_ids = [r.molecule_id for r in rankings]
        molecules = db.query(Molecule).filter(
            Molecule.molecule_id.in_(mol_ids)
        ).all()
    else:
        # 默认取前 10 个
        rankings = db.query(Ranking).filter_by(
            round_id=round_id
        ).order_by(Ranking.rank.asc()).limit(10).all()

        mol_ids = [r.molecule_id for r in rankings]
        molecules = db.query(Molecule).filter(
            Molecule.molecule_id.in_(mol_ids)
        ).all()

    # 批量生成反驳
    results = []
    for molecule in molecules:
        critique_result = generate_llm_critique(db, project, molecule)
        results.append(critique_result)

    # 记录审计
    audit_run = AgentRun(
        agent_run_id=new_id("RUN"),
        project_id=project.project_id,
        round_id=round_id,
        agent_name="llm_critique_batch",
        model_name=next(
            (result.get("llm_model") for result in results if result.get("llm_model")),
            None,
        ),
        status="completed",
        input_json={
            "round_id": round_id,
            "molecule_count": len(molecules),
            "molecule_ids": [m.molecule_id for m in molecules],
            "llm_providers": sorted({
                result["llm_provider"]
                for result in results
                if result.get("llm_provider")
            }),
        },
        output_json={
            "total": len(results),
            "critiqued": sum(1 for r in results if r.get("has_critique")),
            "skipped": sum(1 for r in results if not r.get("has_critique")),
            "results": results,
        },
    )
    db.add(audit_run)
    db.commit()

    return {
        "round_id": round_id,
        "total": len(results),
        "critiqued": sum(1 for r in results if r.get("has_critique")),
        "skipped": sum(1 for r in results if not r.get("has_critique")),
        "results": results,
    }


# ------------------------------------------------------------------
# Strategy API - 策略生成与确认
# ------------------------------------------------------------------

@router.post("/{round_id}/strategy/draft", response_model=RoundStrategyDraftRead, status_code=201)
def generate_strategy_draft(
    project_id: str,
    round_id: str,
    body: RoundStrategyDraftRequest | None = None,
    db: Session = Depends(get_db),
) -> RoundStrategyDraftRead:
    """生成本轮策略草稿。

    中央 LLM 分析项目目标、上轮结果和用户要求，生成策略草稿供用户确认。
    """
    from medagent.db.models import AgentRun

    project = _ensure_project(db, project_id)
    pr = _get_round(db, project_id, round_id)

    if pr.status not in ("draft", "ready"):
        raise HTTPException(400, f"只有 draft 或 ready 状态的 round 可以生成策略草稿，当前状态: {pr.status}")

    # 检测工具可用性
    tool_availability = _detect_tool_availability()

    # 使用 RoundStrategyAgent 生成策略草稿
    from medagent.agents.round_strategy import RoundStrategyAgent
    from medagent.llm.client import get_llm_client

    agent = RoundStrategyAgent(llm_client=get_llm_client())

    # 记录输入摘要（用于审计）
    input_summary = {
        "project_id": project.project_id,
        "round_id": pr.round_id,
        "round_number": pr.round_number,
        "parent_round_id": pr.parent_round_id,
        "user_message": body.user_message if body else None,
        "user_overrides": body.user_overrides if body else None,
        "tool_availability": tool_availability,
    }

    strategy_draft = agent.generate_strategy_draft(
        db=db,
        project=project,
        round_number=pr.round_number,
        parent_round_id=pr.parent_round_id,
        user_message=body.user_message if body else None,
        tool_availability=tool_availability,
    )

    # 校验并修正策略草稿
    from medagent.services.strategy_validator import StrategyValidator
    from medagent.core.config import get_settings

    validator = StrategyValidator(get_settings())
    validated_strategy = validator.validate_and_fix(
        strategy_draft,
        tool_availability=tool_availability,
        user_overrides=body.user_overrides if body else None,
    )

    # 保存策略草稿到 round 的 user_conditions_json
    user_conditions = dict(pr.user_conditions_json or {})
    user_conditions.update({
        "strategy_draft": validated_strategy,
        "tool_availability": tool_availability,
        "generated_at": datetime.now(UTC).isoformat(),
    })
    pr.user_conditions_json = user_conditions
    pr.status = "ready"  # 标记为就绪状态，等待用户确认
    db.flush()

    # 创建审计记录（AgentRun）
    audit_run = AgentRun(
        agent_run_id=new_id("RUN"),
        project_id=project.project_id,
        round_id=pr.round_id,
        agent_name="round_strategy_agent",
        model_name="qwen",  # 或从 settings 获取
        status="completed",
        input_json=input_summary,
        output_json={
            "strategy_draft": validated_strategy,
            "validation_applied": True,
        },
    )
    db.add(audit_run)
    db.commit()

    return RoundStrategyDraftRead(
        round_id=pr.round_id,
        round_number=pr.round_number,
        objective=validated_strategy.get("objective", ""),
        campaign_config=validated_strategy.get("campaign_config", {}),
        seed_policy=validated_strategy.get("seed_policy"),
        property_constraints=validated_strategy.get("property_constraints"),
        assessment_config=validated_strategy.get("assessment_config"),
        rationale=validated_strategy.get("rationale", ""),
        warnings=validated_strategy.get("warnings", []),
        requires_user_confirmation=validated_strategy.get("requires_user_confirmation", True),
        created_at=pr.updated_at or pr.created_at,
    )


@router.get("/{round_id}/strategy", response_model=RoundStrategyDraftRead)
def get_strategy_draft(
    project_id: str,
    round_id: str,
    db: Session = Depends(get_db),
) -> RoundStrategyDraftRead:
    """查看当前策略草稿。"""
    pr = _get_round(db, project_id, round_id)

    user_conditions = pr.user_conditions_json or {}
    strategy_draft = user_conditions.get("strategy_draft")

    if not strategy_draft:
        raise HTTPException(404, "该轮次尚未生成策略草稿")

    return RoundStrategyDraftRead(
        round_id=pr.round_id,
        round_number=pr.round_number,
        objective=strategy_draft.get("objective", ""),
        campaign_config=strategy_draft.get("campaign_config", {}),
        seed_policy=strategy_draft.get("seed_policy"),
        property_constraints=strategy_draft.get("property_constraints"),
        assessment_config=strategy_draft.get("assessment_config"),
        rationale=strategy_draft.get("rationale", ""),
        warnings=strategy_draft.get("warnings", []),
        requires_user_confirmation=strategy_draft.get("requires_user_confirmation", True),
        created_at=pr.updated_at or pr.created_at,
    )


@router.post("/{round_id}/strategy/revise", response_model=RoundStrategyDraftRead)
def revise_strategy_draft(
    project_id: str,
    round_id: str,
    body: RoundStrategyReviseRequest,
    db: Session = Depends(get_db),
) -> RoundStrategyDraftRead:
    """Revise the current strategy through a natural-language user instruction."""
    from medagent.agents.round_strategy import RoundStrategyAgent
    from medagent.core.config import get_settings
    from medagent.db.models import AgentRun
    from medagent.llm.client import get_llm_client
    from medagent.services.strategy_validator import StrategyValidator

    project = _ensure_project(db, project_id)
    pr = _get_round(db, project_id, round_id)
    if pr.status not in ("draft", "ready"):
        raise HTTPException(400, f"只有 draft 或 ready 状态的 round 可以修改策略，当前状态: {pr.status}")

    user_conditions = dict(pr.user_conditions_json or {})
    existing_strategy = user_conditions.get("strategy_draft")
    if not existing_strategy:
        raise HTTPException(400, "该轮次尚未生成策略草稿，请先调用 POST /strategy/draft")

    tool_availability = user_conditions.get("tool_availability") or _detect_tool_availability()
    agent = RoundStrategyAgent(llm_client=get_llm_client())
    revised = agent.generate_strategy_draft(
        db=db,
        project=project,
        round_number=pr.round_number,
        parent_round_id=pr.parent_round_id,
        user_message=body.user_message,
        tool_availability=tool_availability,
        existing_strategy=existing_strategy,
    )
    validated = StrategyValidator(get_settings()).validate_and_fix(
        revised,
        tool_availability=tool_availability,
        user_overrides=body.user_overrides,
    )

    revised_at = datetime.now(UTC).isoformat()
    history = list(user_conditions.get("strategy_revision_history") or [])
    history.append({
        "revised_at": revised_at,
        "user_message": body.user_message,
        "user_overrides": body.user_overrides,
        "previous_strategy": existing_strategy,
    })
    user_conditions.update({
        "strategy_draft": validated,
        "tool_availability": tool_availability,
        "strategy_revision_history": history,
        "revised_at": revised_at,
    })
    pr.user_conditions_json = user_conditions
    pr.status = "ready"
    db.add(AgentRun(
        agent_run_id=new_id("RUN"),
        project_id=project_id,
        round_id=round_id,
        agent_name="round_strategy_revision",
        model_name="llm",
        status="completed",
        input_json={
            "user_message": body.user_message,
            "user_overrides": body.user_overrides,
            "existing_strategy": existing_strategy,
        },
        output_json={"strategy_draft": validated},
    ))
    db.commit()
    return _strategy_to_read(pr, validated)


@router.post("/{round_id}/strategy/confirm", response_model=RoundStrategyExecuteResponse)
def confirm_and_execute_strategy(
    project_id: str,
    round_id: str,
    body: RoundStrategyConfirmRequest,
    db: Session = Depends(get_db),
) -> RoundStrategyExecuteResponse:
    """确认策略并执行本轮。

    用户确认策略草稿后，启动本轮生成、评估、排名流程。
    """
    from medagent.db.models import AgentRun

    project = _ensure_project(db, project_id)
    pr = _get_round(db, project_id, round_id)

    if pr.status not in ("draft", "ready"):
        raise HTTPException(400, f"只有 draft 或 ready 状态的 round 可以确认执行，当前状态: {pr.status}")

    user_conditions = pr.user_conditions_json or {}
    strategy_draft = user_conditions.get("strategy_draft")

    if not strategy_draft:
        raise HTTPException(400, "该轮次尚未生成策略草稿，请先调用 POST /strategy/draft")

    # 记录用户确认审计
    confirmation_audit = {
        "confirmed": body.confirmed,
        "user_modifications": body.user_modifications,
        "confirmed_at": datetime.now(UTC).isoformat(),
        "original_strategy": strategy_draft,
    }

    if not body.confirmed:
        # 用户取消执行，记录审计
        audit_run = AgentRun(
            agent_run_id=new_id("RUN"),
            project_id=project.project_id,
            round_id=pr.round_id,
            agent_name="strategy_confirmation",
            model_name="user_action",
            status="cancelled",
            input_json=confirmation_audit,
            output_json={"action": "cancelled_by_user"},
        )
        db.add(audit_run)
        db.commit()

        return RoundStrategyExecuteResponse(
            round_id=pr.round_id,
            status="cancelled",
            message="用户取消执行",
        )

    # 应用用户修改
    if body.user_modifications:
        from medagent.services.strategy_validator import StrategyValidator
        from medagent.core.config import get_settings

        validator = StrategyValidator(get_settings())
        tool_availability = user_conditions.get("tool_availability", {})
        strategy_draft = validator.validate_and_fix(
            strategy_draft,
            tool_availability=tool_availability,
            user_overrides=body.user_modifications,
        )

        # 更新确认审计记录
        confirmation_audit["modified_strategy"] = strategy_draft

    # 转换策略草稿为执行配置
    campaign_config = _strategy_to_campaign_config(strategy_draft)
    assessment_config = strategy_draft.get("assessment_config", {})

    # 准备种子分子
    seeds, seed_molecule_ids = _prepare_seed_selection(db, project, pr, strategy_draft)

    user_conditions["strategy_draft"] = strategy_draft
    user_conditions["confirmed_at"] = confirmation_audit["confirmed_at"]
    user_conditions["confirmed_seed_molecule_ids"] = seed_molecule_ids
    pr.user_conditions_json = user_conditions

    # 记录用户确认审计（成功）
    audit_run = AgentRun(
        agent_run_id=new_id("RUN"),
        project_id=project.project_id,
        round_id=pr.round_id,
        agent_name="strategy_confirmation",
        model_name="user_action",
        status="confirmed",
        input_json=confirmation_audit,
        output_json={
            "action": "confirmed_and_execute",
            "final_strategy": strategy_draft,
            "seeds_count": len(seeds),
            "seed_molecule_ids": seed_molecule_ids,
        },
    )
    db.add(audit_run)
    db.flush()

    # 执行本轮
    from medagent.pipeline.round_orchestrator import RoundOrchestrator
    from medagent.core.config import get_settings

    orch = RoundOrchestrator(get_settings())

    try:
        result = orch.run_round(
            db,
            project,
            pr,
            campaign_config,
            assessment_config=assessment_config,
            seeds=seeds,
            seed_molecule_ids=seed_molecule_ids,
        )
        db.commit()

        return RoundStrategyExecuteResponse(
            round_id=pr.round_id,
            status="completed",
            message="轮次执行完成",
            result=result,
        )
    except Exception as exc:
        db.rollback()

        # 记录执行失败审计
        failure_audit = AgentRun(
            agent_run_id=new_id("RUN"),
            project_id=project.project_id,
            round_id=pr.round_id,
            agent_name="round_execution",
            model_name="orchestrator",
            status="failed",
            input_json={"round_id": pr.round_id},
            output_json={"error": str(exc)},
        )
        db.add(failure_audit)
        db.commit()

        return RoundStrategyExecuteResponse(
            round_id=pr.round_id,
            status="failed",
            message=f"轮次执行失败: {str(exc)}",
        )


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
        execution_config_snapshot_json=pr.execution_config_snapshot_json,
        started_at=pr.started_at,
        completed_at=pr.completed_at,
        created_at=pr.created_at,
    )


def _strategy_to_read(
    pr: ProjectRound,
    strategy_draft: dict[str, Any],
) -> RoundStrategyDraftRead:
    return RoundStrategyDraftRead(
        round_id=pr.round_id,
        round_number=pr.round_number,
        objective=strategy_draft.get("objective", ""),
        campaign_config=strategy_draft.get("campaign_config", {}),
        seed_policy=strategy_draft.get("seed_policy"),
        property_constraints=strategy_draft.get("property_constraints"),
        assessment_config=strategy_draft.get("assessment_config"),
        rationale=strategy_draft.get("rationale", ""),
        warnings=strategy_draft.get("warnings", []),
        requires_user_confirmation=strategy_draft.get("requires_user_confirmation", True),
        created_at=pr.updated_at or pr.created_at,
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


def _campaign_config_from_payload(payload: dict[str, Any] | None):
    from medagent.domain.schemas import CampaignConfig

    if not payload:
        return CampaignConfig()
    if hasattr(CampaignConfig, "model_validate"):
        return CampaignConfig.model_validate(payload)
    return CampaignConfig.parse_obj(payload)


def _detect_tool_availability() -> dict[str, bool]:
    """检测生成工具的可用性。"""
    availability = {
        "crem": False,
        "reinvent4": False,
        "autogrow4": False,
    }

    # 检测 CReM
    try:
        from medagent.services.molecule_generation import STRATEGY_ADAPTERS
        availability["crem"] = "crem" in STRATEGY_ADAPTERS
    except Exception:
        pass

    # 检测 REINVENT4
    try:
        from medagent.services.reinvent4_adapter import check_reinvent4_available
        availability["reinvent4"] = check_reinvent4_available()
    except Exception:
        pass

    # 检测 AutoGrow4
    try:
        from medagent.services.autogrow4_adapter import check_autogrow4_available
        availability["autogrow4"] = check_autogrow4_available()
    except Exception:
        pass

    return availability


def _strategy_to_campaign_config(strategy_draft: dict[str, Any]):
    """将策略草稿转换为 CampaignConfig。"""
    return _campaign_config_from_payload(strategy_draft.get("campaign_config") or {})


def _prepare_seeds(
    db: Session,
    project: Project,
    round_obj: ProjectRound,
    strategy_draft: dict[str, Any],
) -> list[str]:
    """Compatibility wrapper returning only seed SMILES."""
    return _prepare_seed_selection(db, project, round_obj, strategy_draft)[0]


def _prepare_seed_selection(
    db: Session,
    project: Project,
    round_obj: ProjectRound,
    strategy_draft: dict[str, Any],
) -> tuple[list[str], list[str]]:
    """Resolve seed SMILES and their persisted source identifiers."""
    from medagent.db.models import Molecule, Ranking, SeedLigand

    seed_policy = strategy_draft.get("seed_policy", {})
    source = seed_policy.get("source", "all_seeds")
    explicit_ids = list(dict.fromkeys(str(item) for item in seed_policy.get("molecule_ids") or []))

    seed_ligands = db.query(SeedLigand).filter(
        SeedLigand.project_id == project.project_id,
    ).all()
    builtin_selection = [
        (item.smiles, item.ligand_id)
        for item in seed_ligands
        if item.smiles
    ]

    def molecule_selection(molecule_ids: list[str]) -> list[tuple[str, str]]:
        if not molecule_ids:
            return []
        query = db.query(Molecule).filter(
            Molecule.project_id == project.project_id,
            Molecule.molecule_id.in_(molecule_ids),
        )
        if round_obj.parent_round_id:
            query = query.filter(Molecule.round_id == round_obj.parent_round_id)
        by_id = {item.molecule_id: item for item in query.all()}
        return [
            (by_id[molecule_id].smiles, molecule_id)
            for molecule_id in molecule_ids
            if molecule_id in by_id and by_id[molecule_id].smiles
        ]

    explicit_selection = molecule_selection(explicit_ids)
    if explicit_selection:
        selected = (
            _dedupe_seed_selection([*builtin_selection, *explicit_selection])
            if source == "mixed"
            else explicit_selection
        )
        return [item[0] for item in selected], [item[1] for item in selected]

    if source == "all_seeds":
        selected = builtin_selection

    elif source == "top_from_previous":
        if not round_obj.parent_round_id:
            selected = builtin_selection
        else:
            top_n = int(seed_policy.get("top_n", 10))
            rankings = db.query(Ranking).filter_by(
                project_id=project.project_id,
                round_id=round_obj.parent_round_id,
            ).order_by(Ranking.rank.asc()).limit(top_n).all()
            selected = molecule_selection([item.molecule_id for item in rankings])

    elif source == "mixed":
        previous_selection: list[tuple[str, str]] = []
        if round_obj.parent_round_id:
            top_n = int(seed_policy.get("top_n", 5))
            rankings = db.query(Ranking).filter_by(
                project_id=project.project_id,
                round_id=round_obj.parent_round_id,
            ).order_by(Ranking.rank.asc()).limit(top_n).all()
            previous_selection = molecule_selection([item.molecule_id for item in rankings])
        selected = _dedupe_seed_selection([*builtin_selection, *previous_selection])

    else:
        selected = builtin_selection

    return [item[0] for item in selected], [item[1] for item in selected]


def _dedupe_seed_selection(
    selection: list[tuple[str, str]],
) -> list[tuple[str, str]]:
    seen_smiles: set[str] = set()
    deduped: list[tuple[str, str]] = []
    for smiles, source_id in selection:
        if smiles in seen_smiles:
            continue
        seen_smiles.add(smiles)
        deduped.append((smiles, source_id))
    return deduped
