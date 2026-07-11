import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from medagent.db.models import (
    AdvisorSuggestion,
    Critique,
    DecisionCard,
    EvidenceLink,
    Molecule,
    OptimizationConstraint,
    Project,
    Ranking,
    ReasoningTrace,
)


REPORT_SECTIONS = [
    "project_summary",
    "input_information",
    "rag_evidence_overview",
    "target_and_pocket_analysis",
    "candidate_molecules",
    "filtering_statistics",
    "docking_overview",
    "admet_overview",
    "synthesis_overview",
    "self_refutation",
    "advisor_suggestions",
    "top_candidates",
    "evidence_links",
    "technical_appendix",
]


def build_project_report(db: Session, project: Project) -> dict[str, Any]:
    constraints = _constraints(db, project)
    rankings = _rankings(db, project)
    molecules = _molecules_by_id(db, project)
    critiques = _critiques_by_molecule_id(db, project)
    advisor = _latest_advisor_suggestion(db, project)
    decision_cards = _decision_cards(db, project)
    traces = _reasoning_traces(db, project)
    evidence_links = _evidence_links_by_molecule_id(db, molecules)

    report = {
        "project_summary": {
            "project_id": project.project_id,
            "name": project.name,
            "target_id": project.target_id,
            "objective": project.objective,
            "status": project.status,
        },
        "constraints": [
            {
                "constraint_id": item.constraint_id,
                "label": item.label,
                "field": item.field,
                "operator": item.operator,
                "value": item.value,
                "priority": item.priority,
            }
            for item in constraints
        ],
        "candidate_summary": {
            "molecule_count": len(molecules),
            "ranking_count": len(rankings),
            "top_molecule_count": min(len(rankings), 50),
            "decision_card_count": len(decision_cards),
            "reasoning_trace_count": len(traces),
        },
        "top_candidates": _top_candidates(rankings, molecules, critiques, evidence_links),
        "self_refutation": _self_refutation_summary(critiques),
        "advisor_suggestions": {
            "suggestion_id": advisor.suggestion_id if advisor else None,
            "summary": advisor.summary if advisor else None,
            "suggestions": advisor.suggestions if advisor else [],
            "next_round_constraints": advisor.next_round_constraints if advisor else [],
            "suggested_generation_config": advisor.suggested_generation_config if advisor else {},
        },
        "evidence_links": _flatten_evidence_links(evidence_links),
        "refutation_chains": _refutation_chains(critiques),
        "decision_cards": [
            {
                "decision_id": card.decision_id,
                "molecule_id": card.molecule_id,
                "decision": card.decision,
                "confidence": card.confidence,
            }
            for card in decision_cards
        ],
        "sections": REPORT_SECTIONS,
        "technical_appendix": {
            "generated_at": datetime.now(UTC).isoformat(),
            "source": "project_report_service",
        },
    }
    report_file = _write_report_file(project, report)
    report["report_file"] = report_file
    return report


def _constraints(db: Session, project: Project) -> list[OptimizationConstraint]:
    return (
        db.query(OptimizationConstraint)
        .filter_by(project_id=project.project_id)
        .order_by(OptimizationConstraint.priority.desc(), OptimizationConstraint.id.asc())
        .all()
    )


def _rankings(db: Session, project: Project) -> list[Ranking]:
    return (
        db.query(Ranking)
        .filter_by(project_id=project.project_id)
        .order_by(Ranking.rank.asc(), Ranking.id.asc())
        .all()
    )


def _molecules_by_id(db: Session, project: Project) -> dict[str, Molecule]:
    molecules = (
        db.query(Molecule)
        .filter_by(project_id=project.project_id)
        .order_by(Molecule.id.asc())
        .all()
    )
    return {molecule.molecule_id: molecule for molecule in molecules}


def _critiques_by_molecule_id(db: Session, project: Project) -> dict[str, Critique]:
    critiques = (
        db.query(Critique)
        .join(Molecule, Critique.molecule_id == Molecule.molecule_id)
        .filter(Molecule.project_id == project.project_id)
        .order_by(Molecule.id.asc(), Critique.id.asc())
        .all()
    )
    return {critique.molecule_id: critique for critique in critiques}


def _latest_advisor_suggestion(db: Session, project: Project) -> AdvisorSuggestion | None:
    return (
        db.query(AdvisorSuggestion)
        .filter_by(project_id=project.project_id)
        .order_by(AdvisorSuggestion.updated_at.desc(), AdvisorSuggestion.id.desc())
        .first()
    )


def _evidence_links_by_molecule_id(
    db: Session,
    molecules: dict[str, Molecule],
) -> dict[str, list[EvidenceLink]]:
    if not molecules:
        return {}
    links = (
        db.query(EvidenceLink)
        .filter(EvidenceLink.molecule_id.in_(list(molecules.keys())))
        .order_by(EvidenceLink.created_at.asc(), EvidenceLink.id.asc())
        .all()
    )
    by_molecule: dict[str, list[EvidenceLink]] = {molecule_id: [] for molecule_id in molecules}
    for link in links:
        if link.molecule_id is not None:
            by_molecule.setdefault(link.molecule_id, []).append(link)
    return by_molecule


def _decision_cards(db: Session, project: Project) -> list[DecisionCard]:
    return (
        db.query(DecisionCard)
        .filter_by(project_id=project.project_id)
        .order_by(DecisionCard.created_at.asc(), DecisionCard.id.asc())
        .all()
    )


def _reasoning_traces(db: Session, project: Project) -> list[ReasoningTrace]:
    return (
        db.query(ReasoningTrace)
        .filter_by(project_id=project.project_id)
        .order_by(ReasoningTrace.created_at.asc(), ReasoningTrace.id.asc())
        .all()
    )


def _top_candidates(
    rankings: list[Ranking],
    molecules: dict[str, Molecule],
    critiques: dict[str, Critique],
    evidence_links: dict[str, list[EvidenceLink]],
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for ranking in rankings[:50]:
        molecule = molecules.get(ranking.molecule_id)
        critique = critiques.get(ranking.molecule_id)
        candidates.append(
            {
                "rank": ranking.rank,
                "molecule_id": ranking.molecule_id,
                "smiles": molecule.smiles if molecule else None,
                "overall_score": ranking.overall_score,
                "final_decision": ranking.final_decision,
                "risk_level": critique.risk_level if critique else None,
                "refutation_decision": critique.refutation_decision if critique else None,
                "evidence_chain": _evidence_chain(evidence_links.get(ranking.molecule_id, [])),
                "refutation_chain": _refutation_chain(critique),
            }
        )
    return candidates


def _evidence_chain(links: list[EvidenceLink]) -> list[dict[str, Any]]:
    return [
        {
            "evidence_id": link.evidence_id,
            "chunk_id": link.chunk_id,
            "claim_type": link.claim_type,
            "confidence": link.confidence,
            "rationale": link.rationale,
        }
        for link in links
    ]


def _refutation_chain(critique: Critique | None) -> dict[str, Any] | None:
    if critique is None:
        return None
    return {
        "critique_id": critique.critique_id,
        "con_score": critique.con_score,
        "risk_level": critique.risk_level,
        "refutation_decision": critique.refutation_decision,
        "reason": critique.reason,
        "evidence_ids": critique.evidence_ids or [],
    }


def _flatten_evidence_links(
    evidence_links: dict[str, list[EvidenceLink]],
) -> list[dict[str, Any]]:
    flattened: list[dict[str, Any]] = []
    for molecule_id, links in evidence_links.items():
        for item in _evidence_chain(links):
            flattened.append({"molecule_id": molecule_id, **item})
    return flattened


def _refutation_chains(critiques: dict[str, Critique]) -> list[dict[str, Any]]:
    chains: list[dict[str, Any]] = []
    for molecule_id, critique in critiques.items():
        chain = _refutation_chain(critique)
        if chain is not None:
            chains.append({"molecule_id": molecule_id, **chain})
    return chains


def _self_refutation_summary(critiques: dict[str, Critique]) -> dict[str, Any]:
    risk_counts = {"low": 0, "medium": 0, "high": 0}
    decisions: dict[str, int] = {}
    for critique in critiques.values():
        if critique.risk_level in risk_counts:
            risk_counts[critique.risk_level] += 1
        decision = critique.refutation_decision or "unspecified"
        decisions[decision] = decisions.get(decision, 0) + 1
    return {
        "critique_count": len(critiques),
        "risk_counts": risk_counts,
        "decision_counts": decisions,
    }


def _write_report_file(project: Project, report: dict[str, Any]) -> str:
    output_dir = Path(".local") / "reports" / _safe_path_part(project.project_id)
    output_dir.mkdir(parents=True, exist_ok=True)
    report_file = output_dir / "report.json"
    report["report_file"] = str(report_file.resolve())
    report_file.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(report_file.resolve())


def _safe_path_part(value: str) -> str:
    safe = "".join(char if char.isalnum() or char in "._-" else "_" for char in value)
    return safe.strip("._") or "project"
