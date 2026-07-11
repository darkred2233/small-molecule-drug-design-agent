from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from medagent.core.config import Settings
from medagent.db.models import (
    ADMETResult,
    Critique,
    DockingResult,
    EvidenceLink,
    Molecule,
    Project,
    Ranking,
    RuleFilterResult,
    SynthesisRoute,
)
from medagent.services.ids import new_id
from medagent.services.rag import query_project_rag


HARD_BLOCKERS = {"high_hERG_risk", "high_Ames_risk", "admet_blocker", "route_not_found"}


@dataclass(frozen=True)
class CritiqueBlueprint:
    con_score: float
    risk_level: str
    reason: str
    evidence_ids: list[str]
    refutation_decision: str
    warnings: list[str]


def generate_project_critiques(
    db: Session,
    project: Project,
    settings: Settings | None = None,
    max_molecules: int = 50,
) -> dict[str, Any]:
    candidates = _select_candidates(db, project, max_molecules=max_molecules)
    critique_ids: list[str] = []
    con_scores: list[float] = []
    risk_counts = {"low": 0, "medium": 0, "high": 0}
    decision_counts = {"pass": 0, "reserve": 0, "reject": 0}
    evidence_ids: list[str] = []
    warnings: list[str] = []

    for molecule, ranking in candidates:
        blueprint = _build_critique_blueprint(db, project, settings, molecule, ranking)
        critique = _upsert_critique(db, molecule, blueprint)
        critique_ids.append(critique.critique_id)
        con_scores.append(blueprint.con_score)
        risk_counts[blueprint.risk_level] += 1
        decision_counts[blueprint.refutation_decision] += 1
        evidence_ids.extend(blueprint.evidence_ids)
        warnings.extend(blueprint.warnings)

    db.commit()
    return {
        "project_id": project.project_id,
        "evaluated_count": len(candidates),
        "critique_count": len(critique_ids),
        "critique_ids": critique_ids,
        "average_con_score": round(sum(con_scores) / len(con_scores), 3) if con_scores else 0.0,
        "risk_counts": risk_counts,
        "decision_counts": decision_counts,
        "evidence_ids": _dedupe(evidence_ids),
        "warnings": _dedupe(warnings),
    }


def list_project_critiques(db: Session, project: Project) -> list[Critique]:
    return (
        db.query(Critique)
        .join(Molecule, Critique.molecule_id == Molecule.molecule_id)
        .filter(Molecule.project_id == project.project_id)
        .order_by(Molecule.id.asc(), Critique.id.asc())
        .all()
    )


def _select_candidates(
    db: Session,
    project: Project,
    max_molecules: int,
) -> list[tuple[Molecule, Ranking | None]]:
    rankings = (
        db.query(Ranking)
        .filter_by(project_id=project.project_id)
        .order_by(Ranking.rank.asc(), Ranking.id.asc())
        .limit(max_molecules)
        .all()
    )
    if rankings:
        molecule_ids = [ranking.molecule_id for ranking in rankings]
        molecules = db.query(Molecule).filter(Molecule.molecule_id.in_(molecule_ids)).all()
        molecule_by_id = {molecule.molecule_id: molecule for molecule in molecules}
        return [
            (molecule_by_id[ranking.molecule_id], ranking)
            for ranking in rankings
            if ranking.molecule_id in molecule_by_id
        ]

    molecules = (
        db.query(Molecule)
        .filter_by(project_id=project.project_id)
        .order_by(Molecule.id.asc())
        .limit(max_molecules)
        .all()
    )
    return [(molecule, None) for molecule in molecules]


def _build_critique_blueprint(
    db: Session,
    project: Project,
    settings: Settings | None,
    molecule: Molecule,
    ranking: Ranking | None,
) -> CritiqueBlueprint:
    admet = db.query(ADMETResult).filter_by(molecule_id=molecule.molecule_id).one_or_none()
    docking = db.query(DockingResult).filter_by(molecule_id=molecule.molecule_id).one_or_none()
    rule_filter = (
        db.query(RuleFilterResult)
        .filter_by(molecule_id=molecule.molecule_id)
        .one_or_none()
    )
    synthesis = db.query(SynthesisRoute).filter_by(molecule_id=molecule.molecule_id).one_or_none()
    existing_links = (
        db.query(EvidenceLink)
        .filter_by(molecule_id=molecule.molecule_id)
        .order_by(EvidenceLink.id.asc())
        .all()
    )

    blockers = _ranking_blockers(ranking)
    warnings = _missing_evidence_warnings(ranking, admet, docking, rule_filter, synthesis)
    risk_factors = _risk_factors(ranking, admet, docking, rule_filter, synthesis, blockers)
    rag_evidence_ids, rag_warnings = _retrieve_counter_evidence(
        db,
        settings,
        project,
        molecule,
        risk_factors + blockers + warnings,
    )
    warnings.extend(rag_warnings)
    evidence_ids = _evidence_ids(
        molecule,
        ranking,
        admet,
        docking,
        rule_filter,
        synthesis,
        existing_links,
        rag_evidence_ids,
    )
    con_score = _con_score(ranking, risk_factors, blockers, warnings, rag_evidence_ids)
    risk_level = _risk_level(con_score)
    refutation_decision = _refutation_decision(ranking, con_score, blockers, warnings)
    reason = _reason(molecule, ranking, con_score, refutation_decision, risk_factors, blockers, warnings)

    return CritiqueBlueprint(
        con_score=con_score,
        risk_level=risk_level,
        reason=reason,
        evidence_ids=evidence_ids,
        refutation_decision=refutation_decision,
        warnings=warnings,
    )


def _retrieve_counter_evidence(
    db: Session,
    settings: Settings | None,
    project: Project,
    molecule: Molecule,
    risk_terms: list[str],
) -> tuple[list[str], list[str]]:
    if settings is None:
        return [], ["rag_settings_not_available_for_counter_evidence"]

    query = _counter_evidence_query(project, molecule, risk_terms)
    try:
        result = query_project_rag(
            db,
            settings,
            project,
            query=query,
            query_type="counter_evidence",
            top_k=3,
            molecule_id=molecule.molecule_id,
            create_evidence=True,
        )
    except Exception as exc:
        return [], [f"rag_counter_evidence_failed:{exc}"]

    evidence_ids = [str(evidence_id) for evidence_id in result.get("evidence_ids") or []]
    warnings = [str(item) for item in result.get("missing_information") or []]
    if not evidence_ids:
        warnings.append("rag_counter_evidence_no_links")
    return evidence_ids, warnings


def _counter_evidence_query(
    project: Project,
    molecule: Molecule,
    risk_terms: list[str],
) -> str:
    terms = ", ".join(_dedupe(risk_terms)[:8]) or "unknown liabilities"
    return (
        f"Find counter-evidence against advancing molecule {molecule.molecule_id} "
        f"with SMILES {molecule.smiles} for project target {project.target_id or 'unknown target'}. "
        f"Focus on liability terms: {terms}; hERG, Ames, off-target, solubility, docking pose, "
        "synthetic accessibility, and scaffold risk."
    )


def _upsert_critique(
    db: Session,
    molecule: Molecule,
    blueprint: CritiqueBlueprint,
) -> Critique:
    critique = db.query(Critique).filter_by(molecule_id=molecule.molecule_id).one_or_none()
    if critique is None:
        critique = Critique(
            critique_id=new_id("CRT"),
            molecule_id=molecule.molecule_id,
            con_score=blueprint.con_score,
            risk_level=blueprint.risk_level,
            reason=blueprint.reason,
        )
        db.add(critique)

    critique.con_score = blueprint.con_score
    critique.risk_level = blueprint.risk_level
    critique.reason = blueprint.reason
    critique.evidence_ids = blueprint.evidence_ids
    critique.refutation_decision = blueprint.refutation_decision
    return critique


def _ranking_blockers(ranking: Ranking | None) -> list[str]:
    if ranking is None:
        return []
    breakdown = ranking.score_breakdown or {}
    blockers = breakdown.get("blockers") or []
    return [str(blocker) for blocker in blockers]


def _missing_evidence_warnings(
    ranking: Ranking | None,
    admet: ADMETResult | None,
    docking: DockingResult | None,
    rule_filter: RuleFilterResult | None,
    synthesis: SynthesisRoute | None,
) -> list[str]:
    warnings: list[str] = []
    if ranking is None:
        warnings.append("missing_ranking")
    if admet is None:
        warnings.append("missing_admet_result")
    if docking is None:
        warnings.append("missing_docking_result")
    if rule_filter is None:
        warnings.append("missing_rule_filter_result")
    if synthesis is None:
        warnings.append("missing_synthesis_route")
    if ranking is not None and (ranking.evidence_confidence or 0) < 0.5:
        warnings.append("low_evidence_confidence")
    return warnings


def _evidence_ids(
    molecule: Molecule,
    ranking: Ranking | None,
    admet: ADMETResult | None,
    docking: DockingResult | None,
    rule_filter: RuleFilterResult | None,
    synthesis: SynthesisRoute | None,
    existing_links: list[EvidenceLink],
    rag_evidence_ids: list[str],
) -> list[str]:
    evidence_ids = [f"DB:MOL:{molecule.molecule_id}"]
    if ranking is not None:
        evidence_ids.append(f"DB:RANK:{molecule.molecule_id}")
    if admet is not None:
        evidence_ids.append(f"DB:ADMET:{molecule.molecule_id}")
    if docking is not None:
        evidence_ids.append(f"DB:DOCK:{molecule.molecule_id}")
    if rule_filter is not None:
        evidence_ids.append(f"DB:FILTER:{rule_filter.filter_result_id}")
    if synthesis is not None:
        evidence_ids.append(f"DB:SYNTH:{molecule.molecule_id}")
    evidence_ids.extend(link.evidence_id for link in existing_links)
    evidence_ids.extend(rag_evidence_ids)
    return _dedupe(evidence_ids)


def _risk_factors(
    ranking: Ranking | None,
    admet: ADMETResult | None,
    docking: DockingResult | None,
    rule_filter: RuleFilterResult | None,
    synthesis: SynthesisRoute | None,
    blockers: list[str],
) -> list[str]:
    factors: list[str] = []
    if ranking is not None:
        if ranking.final_decision in {"reject", "deprioritize", "reserve"}:
            factors.append(f"ranker_decision={ranking.final_decision}")
        if ranking.con_score is not None and ranking.con_score >= 40:
            factors.append(f"con_score={round(ranking.con_score, 3)}")
        if ranking.overall_score is not None and ranking.overall_score < 55:
            factors.append(f"overall_score={round(ranking.overall_score, 3)}")
    if admet is not None:
        if admet.hERG_risk in {"medium_risk", "high_risk"}:
            factors.append(f"hERG={admet.hERG_risk}")
        if admet.Ames_risk in {"medium_risk", "high_risk"}:
            factors.append(f"Ames={admet.Ames_risk}")
        if admet.solubility == "low":
            factors.append("low_solubility")
    if docking is not None:
        if docking.clash_count and docking.clash_count > 0:
            factors.append(f"clash_count={docking.clash_count}")
        if docking.cnn_score is not None and docking.cnn_score < 0.4:
            factors.append(f"low_pose_confidence={round(docking.cnn_score, 3)}")
    if rule_filter is not None and rule_filter.failed_rules:
        factors.extend(f"failed_rule={rule}" for rule in rule_filter.failed_rules)
    if synthesis is not None:
        if not synthesis.route_found:
            factors.append("route_not_found")
        if synthesis.route_steps is not None and synthesis.route_steps > 6:
            factors.append(f"long_route={synthesis.route_steps}")
    factors.extend(f"blocker={blocker}" for blocker in blockers)
    return _dedupe(factors)


def _con_score(
    ranking: Ranking | None,
    risk_factors: list[str],
    blockers: list[str],
    warnings: list[str],
    rag_evidence_ids: list[str],
) -> float:
    score = 20.0 if ranking is None else min(float(ranking.con_score or 0.0), 100.0) * 0.45
    if ranking is not None:
        if ranking.final_decision == "reject":
            score += 25
        elif ranking.final_decision == "deprioritize":
            score += 16
        elif ranking.final_decision == "watch":
            score += 8
        if ranking.overall_score is not None and ranking.overall_score < 55:
            score += min((55 - float(ranking.overall_score)) * 0.4, 14)

    for factor in risk_factors:
        if "high_risk" in factor or factor in {"route_not_found", "low_solubility"}:
            score += 14
        elif factor.startswith("failed_rule=") or factor.startswith("blocker="):
            score += 8
        else:
            score += 4
    if HARD_BLOCKERS.intersection(blockers):
        score += 18
    if "low_evidence_confidence" in warnings:
        score += 12
    if rag_evidence_ids:
        score += min(len(rag_evidence_ids) * 3, 9)
    return round(_clamp(score, 0, 100), 3)


def _risk_level(con_score: float) -> str:
    if con_score >= 65:
        return "high"
    if con_score >= 35:
        return "medium"
    return "low"


def _refutation_decision(
    ranking: Ranking | None,
    con_score: float,
    blockers: list[str],
    warnings: list[str],
) -> str:
    overall_score = ranking.overall_score if ranking is not None else None
    if con_score >= 70 or (HARD_BLOCKERS.intersection(blockers) and (overall_score or 0) < 55):
        return "reject"
    if con_score >= 35 or "low_evidence_confidence" in warnings:
        return "reserve"
    return "pass"


def _reason(
    molecule: Molecule,
    ranking: Ranking | None,
    con_score: float,
    refutation_decision: str,
    risk_factors: list[str],
    blockers: list[str],
    warnings: list[str],
) -> str:
    score_part = "no ranking score"
    if ranking is not None:
        score_part = (
            f"overall={ranking.overall_score}, con={ranking.con_score}, "
            f"decision={ranking.final_decision}"
        )
    factors = risk_factors[:5] or blockers[:5] or warnings[:5] or ["no major counter-evidence found"]
    return (
        f"Self-refutation for {molecule.molecule_id}: {score_part}; "
        f"refutation_con_score={con_score}, decision={refutation_decision}. "
        f"Counter-evidence checked: {', '.join(factors)}."
    )


def _dedupe(values: list[str]) -> list[str]:
    deduped: list[str] = []
    for value in values:
        if value not in deduped:
            deduped.append(value)
    return deduped


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))
