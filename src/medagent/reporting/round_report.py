"""单轮报告生成服务 - 支持按轮次生成报告。"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from medagent.db.models import (
    ADMETResult,
    CampaignRun,
    DockingResult,
    Molecule,
    Project,
    ProjectRound,
    Ranking,
    SynthesisRoute,
)


def build_round_report(db: Session, project: Project, round_obj: ProjectRound) -> dict[str, Any]:
    """生成单轮报告。

    Args:
        db: 数据库会话
        project: 项目对象
        round_obj: 轮次对象

    Returns:
        单轮报告字典
    """
    # 基本信息
    report = {
        "round_summary": {
            "round_id": round_obj.round_id,
            "round_number": round_obj.round_number,
            "project_id": project.project_id,
            "project_name": project.name,
            "status": round_obj.status,
            "started_at": round_obj.started_at.isoformat() if round_obj.started_at else None,
            "completed_at": round_obj.completed_at.isoformat() if round_obj.completed_at else None,
            "parent_round_id": round_obj.parent_round_id,
        }
    }

    # 策略配置
    user_conditions = round_obj.user_conditions_json or {}
    strategy_draft = user_conditions.get("strategy_draft")
    if strategy_draft:
        report["strategy"] = {
            "objective": strategy_draft.get("objective"),
            "campaign_config": strategy_draft.get("campaign_config"),
            "seed_policy": strategy_draft.get("seed_policy"),
            "property_constraints": strategy_draft.get("property_constraints"),
            "rationale": strategy_draft.get("rationale"),
            "warnings": strategy_draft.get("warnings", []),
        }

    # 执行配置快照
    execution_config = round_obj.execution_config_snapshot_json or {}
    report["execution_config"] = execution_config

    # Campaign 统计
    campaigns = db.query(CampaignRun).filter_by(round_id=round_obj.round_id).all()
    report["campaigns"] = [
        {
            "campaign_run_id": c.campaign_run_id,
            "method": c.method,
            "status": c.status,
            "input_count": len(c.input_molecule_ids or []),
            "output_count": len(c.output_molecule_ids or []),
            "warnings": c.warnings_json or [],
            "started_at": c.started_at.isoformat() if c.started_at else None,
            "completed_at": c.completed_at.isoformat() if c.completed_at else None,
        }
        for c in campaigns
    ]

    # 分子统计
    molecules = db.query(Molecule).filter_by(round_id=round_obj.round_id).all()
    report["molecules"] = {
        "total_count": len(molecules),
        "by_source": _count_by_source(molecules),
        "by_generation_method": _count_by_generation_method(molecules),
        "by_status": _count_by_status(molecules),
    }

    # 评估统计
    molecule_ids = [m.molecule_id for m in molecules]

    if molecule_ids:
        docking_count = (
            db.query(DockingResult)
            .filter(
                DockingResult.molecule_id.in_(molecule_ids),
                DockingResult.round_id == round_obj.round_id,
            )
            .count()
        )
        admet_count = (
            db.query(ADMETResult)
            .filter(
                ADMETResult.molecule_id.in_(molecule_ids),
                ADMETResult.round_id == round_obj.round_id,
            )
            .count()
        )
        synthesis_count = (
            db.query(SynthesisRoute)
            .filter(
                SynthesisRoute.molecule_id.in_(molecule_ids),
                SynthesisRoute.round_id == round_obj.round_id,
            )
            .count()
        )

        report["assessment"] = {
            "docking_count": docking_count,
            "admet_count": admet_count,
            "synthesis_count": synthesis_count,
        }

        # 对接结果分布
        if docking_count > 0:
            docking_results = (
                db.query(DockingResult)
                .filter(
                    DockingResult.molecule_id.in_(molecule_ids),
                    DockingResult.round_id == round_obj.round_id,
                )
                .all()
            )
            report["docking_distribution"] = _docking_score_distribution(docking_results)

        # ADMET 风险分布
        if admet_count > 0:
            admet_results = (
                db.query(ADMETResult)
                .filter(
                    ADMETResult.molecule_id.in_(molecule_ids),
                    ADMETResult.round_id == round_obj.round_id,
                )
                .all()
            )
            report["admet_distribution"] = _admet_risk_distribution(admet_results)

    # 排名结果
    rankings = db.query(Ranking).filter_by(round_id=round_obj.round_id).order_by(Ranking.rank.asc()).all()
    report["ranking"] = {
        "total_count": len(rankings),
        "top_10": [
            {
                "molecule_id": r.molecule_id,
                "rank": r.rank,
                "overall_score": r.overall_score,
                "final_decision": r.final_decision,
                "score_breakdown": r.score_breakdown or {},
            }
            for r in rankings[:10]
        ],
    }

    # 与上一轮对比
    if round_obj.parent_round_id:
        report["comparison_with_previous"] = _compare_with_previous_round(
            db, project, round_obj, round_obj.parent_round_id
        )

    return report


def _count_by_source(molecules: list[Molecule]) -> dict[str, int]:
    """按来源统计分子数。"""
    counts: dict[str, int] = {}
    for mol in molecules:
        source = mol.source_agent or "unknown"
        counts[source] = counts.get(source, 0) + 1
    return counts


def _count_by_status(molecules: list[Molecule]) -> dict[str, int]:
    """按状态统计分子数。"""
    counts: dict[str, int] = {}
    for mol in molecules:
        status = mol.status or "unknown"
        counts[status] = counts.get(status, 0) + 1
    return counts


def _count_by_generation_method(molecules: list[Molecule]) -> dict[str, int]:
    """Count generated molecules by their persisted method provenance."""
    counts: dict[str, int] = {}
    for molecule in molecules:
        method = molecule.generation_method or molecule.source_agent or "unknown"
        counts[method] = counts.get(method, 0) + 1
    return counts


def _docking_score_distribution(docking_results: list[DockingResult]) -> dict[str, Any]:
    """对接分数分布统计。"""
    scores = [r.vina_score for r in docking_results if r.vina_score is not None]
    if not scores:
        return {"count": 0}

    return {
        "count": len(scores),
        "min": min(scores),
        "max": max(scores),
        "mean": sum(scores) / len(scores),
        "median": sorted(scores)[len(scores) // 2],
    }


def _admet_risk_distribution(admet_results: list[ADMETResult]) -> dict[str, Any]:
    """ADMET 风险分布统计。"""
    risk_counts = {"low": 0, "medium": 0, "high": 0, "unknown": 0}

    for result in admet_results:
        labels = set(result.labels or [])
        risks = {
            str(risk).strip().lower()
            for risk in (result.hERG_risk, result.Ames_risk)
            if risk
        }
        if "admet_blocker" in labels or risks & {"high", "high_risk"}:
            risk_counts["high"] += 1
        elif "admet_warning" in labels or risks & {"medium", "medium_risk"}:
            risk_counts["medium"] += 1
        elif "admet_clean" in labels or risks & {"low", "low_risk"}:
            risk_counts["low"] += 1
        else:
            risk_counts["unknown"] += 1

    return risk_counts


def _compare_with_previous_round(
    db: Session,
    project: Project,
    current_round: ProjectRound,
    parent_round_id: str,
) -> dict[str, Any]:
    """与上一轮对比。"""
    parent_round = db.query(ProjectRound).filter_by(round_id=parent_round_id).first()
    if not parent_round:
        return {}

    # 当前轮数据
    current_molecules = db.query(Molecule).filter_by(round_id=current_round.round_id).all()
    current_rankings = (
        db.query(Ranking)
        .filter_by(round_id=current_round.round_id)
        .order_by(Ranking.rank.asc())
        .all()
    )

    # 上一轮数据
    parent_molecules = db.query(Molecule).filter_by(round_id=parent_round_id).all()
    parent_rankings = (
        db.query(Ranking)
        .filter_by(round_id=parent_round_id)
        .order_by(Ranking.rank.asc())
        .all()
    )

    # 对比分子数量
    molecule_count_change = len(current_molecules) - len(parent_molecules)

    # 对比 Top 1 分数
    current_top_score = current_rankings[0].overall_score if current_rankings else None
    parent_top_score = parent_rankings[0].overall_score if parent_rankings else None

    score_improvement = None
    if current_top_score is not None and parent_top_score is not None:
        score_improvement = current_top_score - parent_top_score

    return {
        "parent_round_number": parent_round.round_number,
        "molecule_count_change": molecule_count_change,
        "current_molecule_count": len(current_molecules),
        "parent_molecule_count": len(parent_molecules),
        "current_top_score": current_top_score,
        "parent_top_score": parent_top_score,
        "score_improvement": score_improvement,
    }
