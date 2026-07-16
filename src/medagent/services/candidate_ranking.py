import math
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from medagent.db.models import (
    ADMETResult,
    AgentRun,
    Critique,
    DockingResult,
    EvidenceLink,
    Molecule,
    MoleculeProperty,
    Project,
    Ranking,
    RuleFilterResult,
    SynthesisRoute,
)
from medagent.services.ids import new_id
from medagent.services.molecule_validation import merge_labels


RANKING_AGENT_NAME = "ranking_agent"
RANKING_ADAPTER_MODE = "heuristic_candidate_ranking"
TERMINAL_FAILURE_STATUSES = {"invalid_structure", "failed_filter", "failed_assessment"}
RANKING_ELIGIBLE_STATUSES = {
    "generated",
    "imported_from_seed",
    "structure_validated",
    "passed_filter",
    "candidate_assessed",
}


@dataclass
class RankingSummary:
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
class EvidenceBundle:
    properties: MoleculeProperty | None
    rule_filter: RuleFilterResult | None
    docking: DockingResult | None
    admet: ADMETResult | None
    synthesis: SynthesisRoute | None
    critique: Critique | None
    rag_evidence: list[EvidenceLink]


@dataclass(frozen=True)
class ComponentScore:
    available: bool
    positive: float
    risk: float
    details: dict[str, Any]
    blockers: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ScoredMolecule:
    molecule: Molecule
    pro_score: float
    con_score: float
    evidence_confidence: float
    overall_score: float
    final_decision: str
    score_breakdown: dict[str, Any]


def generate_project_rankings(
    db: Session,
    project: Project,
    molecules: list[Molecule] | None = None,
    molecule_ids: list[str] | None = None,
    max_molecules: int = 50,
    top_n: int | None = None,
    tool_status: dict[str, Any] | None = None,
) -> RankingSummary:
    selected_molecules = molecules or _select_ranking_molecules(db, project, molecule_ids, max_molecules)
    top_n = top_n or max_molecules
    selected_ids = [molecule.molecule_id for molecule in selected_molecules]
    external_refinement_present = any(
        _is_externally_refined_candidate(molecule) for molecule in selected_molecules
    )
    agent_run = _create_agent_run(
        db,
        project,
        {
            "molecule_ids": selected_ids,
            "max_molecules": max_molecules,
            "top_n": top_n,
            "source": "candidate_assessment",
            "tool_status": tool_status or {},
        },
    )
    summary = RankingSummary(
        agent_run_id=agent_run.agent_run_id,
        adapter_mode=RANKING_ADAPTER_MODE,
        requested_count=len(selected_molecules),
    )

    try:
        scored_molecules: list[ScoredMolecule] = []
        warnings: list[str] = []
        for molecule in selected_molecules:
            bundle = _load_evidence_bundle(db, molecule)
            scored = _score_molecule(
                molecule,
                bundle,
                external_refinement_present=external_refinement_present,
            )
            scored_molecules.append(scored)
            warnings.extend(_missing_evidence_warnings(scored.score_breakdown))
            summary.evaluated_count += 1

        ranked = sorted(
            scored_molecules,
            key=lambda item: (
                _refinement_sort_tier(item, external_refinement_present),
                -item.overall_score,
                item.con_score,
                item.molecule.molecule_id,
            ),
        )
        stored = ranked[:top_n]
        _replace_project_rankings(db, project, stored)

        summary.generated_count = len(stored)
        summary.molecule_ids = [item.molecule.molecule_id for item in stored]
        summary.warnings = _dedupe(warnings)
        _finish_agent_run(agent_run, summary)
        db.commit()
        return summary
    except Exception as exc:
        _fail_agent_run(db, agent_run, exc)
        raise


def list_project_rankings(db: Session, project: Project) -> list[Ranking]:
    return (
        db.query(Ranking)
        .filter(Ranking.project_id == project.project_id)
        .order_by(Ranking.rank.asc(), Ranking.id.asc())
        .all()
    )


def _select_ranking_molecules(
    db: Session,
    project: Project,
    molecule_ids: list[str] | None,
    max_molecules: int,
) -> list[Molecule]:
    query = db.query(Molecule).filter_by(project_id=project.project_id)
    if molecule_ids:
        query = query.filter(Molecule.molecule_id.in_(molecule_ids))
    else:
        query = query.filter(Molecule.status.in_(RANKING_ELIGIBLE_STATUSES))
    return query.order_by(Molecule.id.asc()).limit(max_molecules).all()


def _load_evidence_bundle(db: Session, molecule: Molecule) -> EvidenceBundle:
    return EvidenceBundle(
        properties=db.query(MoleculeProperty).filter_by(molecule_id=molecule.molecule_id).one_or_none(),
        rule_filter=db.query(RuleFilterResult).filter_by(molecule_id=molecule.molecule_id).one_or_none(),
        docking=db.query(DockingResult).filter_by(molecule_id=molecule.molecule_id).one_or_none(),
        admet=db.query(ADMETResult).filter_by(molecule_id=molecule.molecule_id).one_or_none(),
        synthesis=db.query(SynthesisRoute).filter_by(molecule_id=molecule.molecule_id).one_or_none(),
        critique=db.query(Critique).filter_by(molecule_id=molecule.molecule_id).one_or_none(),
        rag_evidence=(
            db.query(EvidenceLink)
            .filter_by(molecule_id=molecule.molecule_id)
            .order_by(EvidenceLink.created_at.asc(), EvidenceLink.id.asc())
            .all()
        ),
    )


def _score_molecule(
    molecule: Molecule,
    bundle: EvidenceBundle,
    external_refinement_present: bool = False,
) -> ScoredMolecule:
    docking = _score_docking(bundle.docking)
    admet = _score_admet(bundle.admet)
    synthesis = _score_synthesis(bundle.synthesis)
    rule_filter = _score_rule_filter(bundle.rule_filter)
    properties = _score_properties(bundle.properties)
    critique = _score_critique(bundle.critique)
    rag_evidence = _score_rag_evidence(bundle.rag_evidence)
    components = {
        "docking": docking,
        "admet": admet,
        "synthesis": synthesis,
        "rule_filter": rule_filter,
        "properties": properties,
        "critique": critique,
        "rag_evidence": rag_evidence,
    }

    pro_score = round(
        100
        * (
            docking.positive * 0.35
            + admet.positive * 0.25
            + synthesis.positive * 0.20
            + rule_filter.positive * 0.10
            + properties.positive * 0.10
        ),
        3,
    )
    con_score = round(
        100
        * _clamp(
            docking.risk * 0.25
            + admet.risk * 0.35
            + synthesis.risk * 0.20
            + rule_filter.risk * 0.10
            + properties.risk * 0.10
            + critique.risk * 0.20,
            0,
            1,
        ),
        3,
    )
    evidence_confidence = _evidence_confidence(components)
    critique_penalty = _critique_overall_penalty(critique)
    base_overall_score = round(
        _clamp(pro_score - con_score * 0.55 + evidence_confidence * 8 - critique_penalty, 0, 100),
        3,
    )
    refinement_context = _refinement_context(molecule, external_refinement_present)
    overall_score = round(
        _clamp(base_overall_score - refinement_context["provisional_penalty"], 0, 100),
        3,
    )
    blockers = _dedupe(
        docking.blockers
        + admet.blockers
        + synthesis.blockers
        + rule_filter.blockers
        + properties.blockers
    )
    final_decision = _final_decision(
        molecule,
        overall_score=overall_score,
        con_score=con_score,
        evidence_confidence=evidence_confidence,
        blockers=blockers,
        critique=critique,
    )
    score_breakdown = {
        "adapter_mode": RANKING_ADAPTER_MODE,
        "weights": {
            "pro": {
                "docking": 0.35,
                "admet": 0.25,
                "synthesis": 0.20,
                "rule_filter": 0.10,
                "properties": 0.10,
                "critique": 0.00,
            },
            "con": {
                "docking": 0.25,
                "admet": 0.35,
                "synthesis": 0.20,
                "rule_filter": 0.10,
                "properties": 0.10,
                "critique": 0.20,
            },
        },
        "docking": docking.details,
        "admet": admet.details,
        "synthesis": synthesis.details,
        "rule_filter": rule_filter.details,
        "properties": properties.details,
        "critique": critique.details,
        "critique_overall_penalty": critique_penalty,
        "rag_evidence": rag_evidence.details,
        "blockers": blockers,
        "base_overall_score": base_overall_score,
        "refinement": refinement_context,
        "molecule_labels": molecule.labels or [],
    }
    return ScoredMolecule(
        molecule=molecule,
        pro_score=pro_score,
        con_score=con_score,
        evidence_confidence=evidence_confidence,
        overall_score=overall_score,
        final_decision=final_decision,
        score_breakdown=score_breakdown,
    )


def _is_externally_refined_candidate(molecule: Molecule) -> bool:
    return "externally_refined_candidate" in (molecule.labels or [])


def _refinement_context(
    molecule: Molecule,
    external_refinement_present: bool,
) -> dict[str, Any]:
    labels = set(molecule.labels or [])
    if not external_refinement_present:
        return {
            "external_refinement_present": False,
            "state": "not_applicable",
            "sort_tier": 0,
            "provisional_penalty": 0.0,
        }
    if "externally_refined_candidate" in labels:
        return {
            "external_refinement_present": True,
            "state": "externally_refined",
            "sort_tier": 0,
            "provisional_penalty": 0.0,
        }
    if "external_refinement_attempted" in labels:
        return {
            "external_refinement_present": True,
            "state": "external_refinement_attempted_without_external_evidence",
            "sort_tier": 1,
            "provisional_penalty": 25.0,
        }
    if "coarse_only_candidate" in labels:
        return {
            "external_refinement_present": True,
            "state": "coarse_only",
            "sort_tier": 2,
            "provisional_penalty": 40.0,
        }
    if "coarse_screen_failed" in labels or "rejected_by_coarse_screen" in labels:
        return {
            "external_refinement_present": True,
            "state": "coarse_screen_failed",
            "sort_tier": 3,
            "provisional_penalty": 55.0,
        }
    return {
        "external_refinement_present": True,
        "state": "unrefined",
        "sort_tier": 2,
        "provisional_penalty": 40.0,
    }


def _refinement_sort_tier(
    scored: ScoredMolecule,
    external_refinement_present: bool,
) -> int:
    if not external_refinement_present:
        return 0
    refinement = scored.score_breakdown.get("refinement") or {}
    return int(refinement.get("sort_tier", 2))


def _score_docking(result: DockingResult | None) -> ComponentScore:
    if result is None:
        return ComponentScore(
            available=False,
            positive=0.45,
            risk=0.25,
            details={"available": False, "reason": "missing_docking_result"},
        )

    raw_output = result.raw_output or {}
    surrogate = raw_output.get("status") == "surrogate_only" or "rdkit_surrogate_docking" in (
        result.labels or []
    )
    vina_score = (
        raw_output.get("estimated_affinity_like_score") if surrogate else result.vina_score
    )
    cnn_score = raw_output.get("estimated_pose_confidence") if surrogate else result.cnn_score
    diffdock_confidence = None if surrogate else result.diffdock_confidence
    key_hbond_count = (
        raw_output.get("estimated_key_hbond_count") if surrogate else result.key_hbond_count
    )
    clash_count = raw_output.get("estimated_clash_count") if surrogate else result.clash_count
    affinity_score = 0.5 if vina_score is None else _clamp((-float(vina_score) - 4.0) / 6.0, 0, 1)
    if cnn_score is not None:
        pose_score = _clamp(float(cnn_score), 0, 1)
        pose_score_method = "gnina_cnn_score"
    elif diffdock_confidence is not None:
        pose_score = _diffdock_confidence_ranking_score(float(diffdock_confidence))
        pose_score_method = "uncalibrated_sigmoid_for_within_project_ranking_only"
    else:
        pose_score = 0.55
        pose_score_method = "neutral_missing_pose_confidence"
    interaction_score = _clamp(float(key_hbond_count or 0) / 3.0, 0, 1)
    clash_risk = _clamp(float(clash_count or 0) * 0.25, 0, 1)
    pose_risk = 0.20 if "pose_uncertain" in (result.labels or []) else 0.0
    positive = _clamp(affinity_score * 0.70 + pose_score * 0.20 + interaction_score * 0.10, 0, 1)
    risk = _clamp(clash_risk + pose_risk, 0, 1)
    blockers = []
    if not surrogate and clash_count and clash_count >= 2:
        blockers.append("steric_clash")
    if not surrogate and cnn_score is not None and cnn_score < 0.35:
        blockers.append("low_pose_confidence")

    confidence_credit = 0.15 if surrogate else (0.9 if diffdock_confidence is not None else 1.0)

    return ComponentScore(
        available=True,
        positive=positive,
        risk=risk,
        details={
            "available": True,
            "evidence_tier": "surrogate" if surrogate else "external_tool",
            "confidence_credit": confidence_credit,
            "positive_score": round(positive, 3),
            "risk_score": round(risk, 3),
            "vina_score": vina_score,
            "cnn_score": None if surrogate else result.cnn_score,
            "diffdock_confidence": diffdock_confidence,
            "pose_score_method": pose_score_method,
            "estimated_pose_confidence": cnn_score if surrogate else None,
            "key_hbond_count": None if surrogate else result.key_hbond_count,
            "estimated_key_hbond_count": key_hbond_count if surrogate else None,
            "clash_count": None if surrogate else result.clash_count,
            "estimated_clash_count": clash_count if surrogate else None,
            "labels": result.labels or [],
        },
        blockers=blockers,
    )


def _diffdock_confidence_ranking_score(value: float) -> float:
    """Map an uncalibrated DiffDock score monotonically for ranking, never as probability."""
    if value >= 60:
        return 1.0
    if value <= -60:
        return 0.0
    return _clamp(1.0 / (1.0 + math.exp(-value)), 0, 1)


def _score_admet(result: ADMETResult | None) -> ComponentScore:
    if result is None:
        return ComponentScore(
            available=False,
            positive=0.45,
            risk=0.35,
            details={"available": False, "reason": "missing_admet_result"},
        )

    raw_output = result.raw_output or {}
    surrogate = raw_output.get("status") == "surrogate_only" or "rdkit_surrogate_admet" in (
        result.labels or []
    )
    risk = result.admet_risk_score
    if risk is None:
        probabilities = [value for value in [result.hERG_probability, result.Ames_probability] if value is not None]
        risk = sum(probabilities) / len(probabilities) if probabilities else 0.45
    solubility_bonus = {"high": 0.08, "medium": 0.03, "low": -0.08}.get(result.solubility or "", 0.0)
    permeability_bonus = {"high": 0.07, "medium": 0.03, "low": -0.07}.get(result.permeability or "", 0.0)
    positive = _clamp(1.0 - float(risk) + solubility_bonus + permeability_bonus, 0, 1)
    blockers = []
    if not surrogate and result.hERG_risk == "high_risk":
        blockers.append("high_hERG_risk")
    if not surrogate and result.Ames_risk == "high_risk":
        blockers.append("high_Ames_risk")
    if not surrogate and "admet_blocker" in (result.labels or []):
        blockers.append("admet_blocker")

    return ComponentScore(
        available=True,
        positive=positive,
        risk=_clamp(float(risk), 0, 1),
        details={
            "available": True,
            "evidence_tier": "surrogate" if surrogate else "predictive_model",
            "confidence_credit": 0.25 if surrogate else 1.0,
            "positive_score": round(positive, 3),
            "risk_score": round(_clamp(float(risk), 0, 1), 3),
            "hERG_probability": result.hERG_probability,
            "hERG_risk": result.hERG_risk,
            "Ames_probability": result.Ames_probability,
            "Ames_risk": result.Ames_risk,
            "solubility": result.solubility,
            "permeability": result.permeability,
            "labels": result.labels or [],
        },
        blockers=blockers,
    )


def _score_synthesis(result: SynthesisRoute | None) -> ComponentScore:
    if result is None:
        return ComponentScore(
            available=False,
            positive=0.45,
            risk=0.30,
            details={"available": False, "reason": "missing_synthesis_route"},
        )

    route_json = result.route_json or {}
    surrogate = route_json.get("status") == "surrogate_only" or "rdkit_surrogate_synthesis" in (
        result.labels or []
    )
    if surrogate:
        confidence = float(route_json.get("estimated_route_confidence") or 0.35)
        route_steps = int(route_json.get("estimated_route_steps") or 0)
        route_feasible = bool(route_json.get("estimated_route_feasible"))
        route_found_bonus = 0.05 if route_feasible else -0.10
    else:
        confidence = float(result.route_confidence or 0.35)
        route_steps = int(result.route_steps or 0)
        route_feasible = bool(result.route_found)
        route_found_bonus = 0.25 if route_feasible else -0.15
    step_penalty = _clamp(max(route_steps - 5, 0) * 0.08, 0, 0.35)
    hazard_penalty = _clamp(float(route_json.get("hazardous_reaction_count") or 0) * 0.18, 0, 0.45)
    positive = _clamp(confidence + route_found_bonus - step_penalty - hazard_penalty, 0, 1)
    base_risk = (0.25 if route_feasible else 0.45) if surrogate else (0.15 if route_feasible else 0.50)
    risk = _clamp(base_risk + step_penalty + hazard_penalty, 0, 1)
    blockers = []
    if not surrogate and not result.route_found:
        blockers.append("route_not_found")
    if not surrogate and route_steps > 8:
        blockers.append("long_synthesis_route")
    if not surrogate and hazard_penalty > 0:
        blockers.append("hazardous_route")

    return ComponentScore(
        available=True,
        positive=positive,
        risk=risk,
        details={
            "available": True,
            "evidence_tier": "surrogate" if surrogate else "retrosynthesis_tool",
            "confidence_credit": 0.25 if surrogate else 1.0,
            "positive_score": round(positive, 3),
            "risk_score": round(risk, 3),
            "route_found": result.route_found if not surrogate else None,
            "route_steps": result.route_steps if not surrogate else None,
            "route_confidence": result.route_confidence if not surrogate else None,
            "buyable_building_blocks": (
                result.buyable_building_blocks if not surrogate else None
            ),
            "estimated_route_feasible": route_feasible if surrogate else None,
            "estimated_route_steps": route_steps if surrogate else None,
            "estimated_route_confidence": confidence if surrogate else None,
            "SA_score": route_json.get("SA_score"),
            "SCScore": route_json.get("SCScore"),
            "hazardous_reaction_count": route_json.get("hazardous_reaction_count"),
            "labels": result.labels or [],
        },
        blockers=blockers,
    )


def _score_rule_filter(result: RuleFilterResult | None) -> ComponentScore:
    if result is None:
        return ComponentScore(
            available=False,
            positive=0.55,
            risk=0.25,
            details={"available": False, "reason": "missing_rule_filter_result"},
        )

    failed_count = len(result.failed_rules or [])
    warning_count = len(result.warnings or [])
    if result.decision == "passed":
        positive = 0.90
        risk = 0.05
    elif result.decision == "passed_with_warnings":
        positive = _clamp(0.78 - warning_count * 0.025, 0.55, 0.78)
        risk = _clamp(0.12 + warning_count * 0.035, 0.12, 0.45)
    elif result.decision == "failed":
        positive = _clamp(0.65 - failed_count * 0.15, 0.10, 0.65)
        risk = _clamp(0.40 + failed_count * 0.12, 0, 1)
    else:
        positive = 0.40
        risk = 0.35
    blockers = list(result.failed_rules or [])

    return ComponentScore(
        available=True,
        positive=positive,
        risk=risk,
        details={
            "available": True,
            "positive_score": round(positive, 3),
            "risk_score": round(risk, 3),
            "decision": result.decision,
            "failed_rules": result.failed_rules or [],
            "warnings": result.warnings or [],
            "warning_count": warning_count,
            "labels": result.labels or [],
        },
        blockers=blockers,
    )


def _score_properties(result: MoleculeProperty | None) -> ComponentScore:
    if result is None:
        return ComponentScore(
            available=False,
            positive=0.50,
            risk=0.30,
            details={"available": False, "reason": "missing_molecule_properties"},
        )

    penalties: dict[str, float] = {}
    _add_penalty(penalties, "mw_gt_500", result.mw, 500, 250, 0.30)
    _add_penalty(penalties, "logp_gt_5", result.logp, 5, 3, 0.30)
    _add_penalty(penalties, "tpsa_gt_140", result.tpsa, 140, 100, 0.25)
    _add_penalty(penalties, "hbd_gt_5", result.hbd, 5, 5, 0.20)
    _add_penalty(penalties, "hba_gt_10", result.hba, 10, 8, 0.20)
    _add_penalty(penalties, "sa_score_gt_6_5", result.sa_score, 6.5, 3.5, 0.25)
    penalty_total = _clamp(sum(penalties.values()), 0, 1)
    positive = _clamp(1.0 - penalty_total, 0, 1)
    blockers = [key for key, penalty in penalties.items() if penalty >= 0.12]

    return ComponentScore(
        available=True,
        positive=positive,
        risk=penalty_total,
        details={
            "available": True,
            "positive_score": round(positive, 3),
            "risk_score": round(penalty_total, 3),
            "mw": result.mw,
            "logp": result.logp,
            "tpsa": result.tpsa,
            "hbd": result.hbd,
            "hba": result.hba,
            "sa_score": result.sa_score,
            "penalties": penalties,
        },
        blockers=blockers,
    )


def _score_critique(result: Critique | None) -> ComponentScore:
    if result is None:
        return ComponentScore(
            available=False,
            positive=0.50,
            risk=0.15,
            details={"available": False, "reason": "missing_self_refutation_result"},
        )

    con_score = _clamp(float(result.con_score or 0.0) / 100.0, 0, 1)
    decision = result.refutation_decision or "reserve"
    if decision == "reject":
        positive = 0.05
        risk = 0.95
    elif decision == "reserve":
        positive = 0.35
        risk = _clamp(0.45 + con_score * 0.40, 0, 1)
    else:
        positive = 0.90
        risk = 0.10

    return ComponentScore(
        available=True,
        positive=positive,
        risk=risk,
        details={
            "available": True,
            "positive_score": round(positive, 3),
            "risk_score": round(risk, 3),
            "con_score": round(float(result.con_score or 0.0), 3),
            "risk_level": result.risk_level,
            "refutation_decision": decision,
            "reason": result.reason,
            "evidence_ids": result.evidence_ids or [],
        },
        blockers=["self_refutation_reject"] if decision == "reject" else [],
    )


def _critique_overall_penalty(critique: ComponentScore) -> float:
    decision = critique.details.get("refutation_decision")
    if decision == "reject":
        return 30.0
    if decision == "reserve":
        return 12.0
    return 0.0


def _score_rag_evidence(links: list[EvidenceLink]) -> ComponentScore:
    if not links:
        return ComponentScore(
            available=False,
            positive=0.0,
            risk=0.0,
            details={"available": False, "reason": "missing_rag_evidence"},
        )

    confidences = [float(link.confidence) for link in links if link.confidence is not None]
    confidence = sum(confidences) / len(confidences) if confidences else 0.55
    return ComponentScore(
        available=True,
        positive=_clamp(confidence, 0, 1),
        risk=0.0,
        details={
            "available": True,
            "evidence_count": len(links),
            "confidence": round(_clamp(confidence, 0, 1), 3),
            "evidence_ids": [link.evidence_id for link in links],
            "chunk_ids": [link.chunk_id for link in links],
            "claim_types": _dedupe([link.claim_type for link in links]),
        },
    )


def _add_penalty(
    penalties: dict[str, float],
    name: str,
    value: float | int | None,
    threshold: float,
    span: float,
    maximum: float,
) -> None:
    if value is None or float(value) <= threshold:
        return
    penalties[name] = round(_clamp((float(value) - threshold) / span, 0, maximum), 3)


def _evidence_confidence(components: dict[str, ComponentScore]) -> float:
    weights = {
        "docking": 0.25,
        "admet": 0.25,
        "synthesis": 0.20,
        "rule_filter": 0.15,
        "properties": 0.15,
    }
    confidence = sum(
        weight * float(components[key].details.get("confidence_credit", 1.0))
        for key, weight in weights.items()
        if components[key].available
    )
    if components.get("rag_evidence") and components["rag_evidence"].available:
        confidence += 0.10
    return round(_clamp(confidence, 0, 1), 3)


def _final_decision(
    molecule: Molecule,
    overall_score: float,
    con_score: float,
    evidence_confidence: float,
    blockers: list[str],
    critique: ComponentScore,
) -> str:
    labels = set(molecule.labels or [])
    hard_blockers = {
        "high_hERG_risk",
        "high_Ames_risk",
        "admet_blocker",
        "route_not_found",
    }
    has_hard_blocker = bool(hard_blockers.intersection(blockers))
    if "invalid_structure" in labels:
        return "reject"
    if critique.details.get("refutation_decision") == "reject":
        return "reject"
    if critique.details.get("refutation_decision") == "reserve":
        if overall_score >= 70 and evidence_confidence >= 0.55:
            return "watch"
        return "reserve"
    if con_score >= 70 or (has_hard_blocker and overall_score < 45):
        return "reject"
    if overall_score >= 70 and con_score <= 35 and evidence_confidence >= 0.65 and not has_hard_blocker:
        return "advance"
    if overall_score >= 50 and evidence_confidence >= 0.40:
        return "watch"
    return "deprioritize"


def _replace_project_rankings(
    db: Session,
    project: Project,
    ranked_molecules: list[ScoredMolecule],
) -> None:
    db.query(Ranking).filter(Ranking.project_id == project.project_id).delete(synchronize_session=False)
    for index, scored in enumerate(ranked_molecules, start=1):
        if scored.final_decision == "reject":
            if scored.molecule.status not in TERMINAL_FAILURE_STATUSES:
                scored.molecule.status = "rejected_by_ranking"
            scored.molecule.labels = merge_labels(scored.molecule.labels, ["ranking_reject"])
        elif scored.final_decision == "deprioritize":
            scored.molecule.labels = merge_labels(scored.molecule.labels, ["ranking_deprioritize"])
        elif scored.final_decision in {"advance", "watch", "reserve"}:
            scored.molecule.labels = merge_labels(scored.molecule.labels, [f"ranking_{scored.final_decision}"])
        db.add(
            Ranking(
                project_id=project.project_id,
                molecule_id=scored.molecule.molecule_id,
                rank=index,
                pro_score=scored.pro_score,
                con_score=scored.con_score,
                evidence_confidence=scored.evidence_confidence,
                overall_score=scored.overall_score,
                final_decision=scored.final_decision,
                score_breakdown=scored.score_breakdown,
            )
        )


def _missing_evidence_warnings(score_breakdown: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    for key in ["docking", "admet", "synthesis", "rule_filter", "properties"]:
        component = score_breakdown.get(key) or {}
        if not component.get("available"):
            warnings.append(f"missing_{key}_evidence")
    return warnings


def _create_agent_run(db: Session, project: Project, input_json: dict[str, Any]) -> AgentRun:
    run = AgentRun(
        agent_run_id=new_id("RUN"),
        project_id=project.project_id,
        agent_name=RANKING_AGENT_NAME,
        model_name="heuristic-ranker",
        status="running",
        input_json={
            **input_json,
            "adapter_mode": RANKING_ADAPTER_MODE,
        },
        output_json={},
    )
    db.add(run)
    db.flush()
    return run


def _finish_agent_run(agent_run: AgentRun, summary: RankingSummary) -> None:
    agent_run.status = "success"
    agent_run.output_json = summary.as_dict()


def _fail_agent_run(db: Session, agent_run: AgentRun, exc: Exception) -> None:
    agent_run_id = agent_run.agent_run_id
    project_id = agent_run.project_id
    input_json = dict(agent_run.input_json or {})
    error_message = str(exc)
    db.rollback()
    failed_run = db.query(AgentRun).filter_by(agent_run_id=agent_run_id).one_or_none()
    if failed_run is None:
        failed_run = AgentRun(
            agent_run_id=agent_run_id,
            project_id=project_id,
            agent_name=RANKING_AGENT_NAME,
            model_name="heuristic-ranker",
            input_json=input_json,
        )
        db.add(failed_run)
    failed_run.status = "failed"
    failed_run.error_message = error_message
    failed_run.output_json = {"error": error_message}
    db.commit()


def _dedupe(values: list[str]) -> list[str]:
    deduped: list[str] = []
    for value in values:
        if value not in deduped:
            deduped.append(value)
    return deduped


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))
