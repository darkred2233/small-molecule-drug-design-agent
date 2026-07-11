from typing import Any

from sqlalchemy.orm import Session

from medagent.db.models import (
    ADMETResult,
    AdvisorSuggestion,
    Critique,
    Molecule,
    OptimizationConstraint,
    Project,
    Ranking,
    RuleFilterResult,
    SynthesisRoute,
)
from medagent.services.ids import new_id


def generate_project_advice(db: Session, project: Project) -> dict[str, Any]:
    rankings = (
        db.query(Ranking)
        .filter_by(project_id=project.project_id)
        .order_by(Ranking.rank.asc(), Ranking.id.asc())
        .all()
    )
    molecules = _molecules_by_id(db, project)
    critiques = _critiques_by_molecule_id(db, project)
    suggestions = _build_suggestions(db, rankings, molecules, critiques)
    next_round_constraints = _next_round_constraints(suggestions)
    suggested_generation_config = _suggested_generation_config(rankings, suggestions)
    _replace_advisor_constraints(db, project, next_round_constraints)
    summary = _summary(project, rankings, suggestions)
    advisor = _upsert_advisor_suggestion(
        db,
        project,
        summary,
        suggestions,
        next_round_constraints,
        suggested_generation_config,
    )
    db.commit()

    return {
        "project_id": project.project_id,
        "suggestion_id": advisor.suggestion_id,
        "summary": advisor.summary,
        "suggestion_count": len(advisor.suggestions or []),
        "suggestions": advisor.suggestions or [],
        "next_round_constraints": advisor.next_round_constraints or [],
        "suggested_generation_config": advisor.suggested_generation_config or {},
    }


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
        .all()
    )
    return {critique.molecule_id: critique for critique in critiques}


def _build_suggestions(
    db: Session,
    rankings: list[Ranking],
    molecules: dict[str, Molecule],
    critiques: dict[str, Critique],
) -> list[dict[str, Any]]:
    suggestions: list[dict[str, Any]] = []
    top_rankings = rankings[:3]
    top_ids = [ranking.molecule_id for ranking in top_rankings]

    if top_rankings:
        suggestions.append(
            {
                "priority": "high",
                "action": "advance_top_ranked_candidates",
                "target_molecule_ids": top_ids,
                "rationale": (
                    "Use the ranked shortlist as the next experimental or higher-fidelity "
                    "computational batch before broadening exploration."
                ),
                "source": "ranking",
            }
        )

    admet_focus = _admet_focus(db, rankings, top_ids)
    if admet_focus:
        suggestions.append(admet_focus)

    synthesis_focus = _synthesis_focus(db, rankings, top_ids)
    if synthesis_focus:
        suggestions.append(synthesis_focus)

    filter_focus = _filter_focus(db, rankings, top_ids)
    if filter_focus:
        suggestions.append(filter_focus)

    critique_focus = _critique_focus(critiques, top_ids)
    if critique_focus:
        suggestions.append(critique_focus)

    evidence_focus = _evidence_focus(rankings, top_ids)
    if evidence_focus:
        suggestions.append(evidence_focus)

    if len(suggestions) < 3:
        fallback_ids = top_ids or list(molecules.keys())[:3]
        suggestions.extend(_fallback_suggestions(fallback_ids, needed=3 - len(suggestions)))

    return suggestions[:6]


def _admet_focus(
    db: Session,
    rankings: list[Ranking],
    top_ids: list[str],
) -> dict[str, Any] | None:
    ranked_ids = [ranking.molecule_id for ranking in rankings]
    results = (
        db.query(ADMETResult)
        .filter(ADMETResult.molecule_id.in_(ranked_ids))
        .all()
    )
    risky_ids = [
        result.molecule_id
        for result in results
        if result.hERG_risk in {"medium_risk", "high_risk"}
        or result.Ames_risk in {"medium_risk", "high_risk"}
        or result.solubility == "low"
    ]
    if not risky_ids:
        return None
    return {
        "priority": "high",
        "action": "reduce_admet_liabilities",
        "target_molecule_ids": _ordered_subset(ranked_ids, risky_ids)[:3] or top_ids,
        "rationale": (
            "Counter-screen analogs for hERG, Ames, and solubility before expanding "
            "around otherwise attractive scaffolds."
        ),
        "source": "admet",
    }


def _synthesis_focus(
    db: Session,
    rankings: list[Ranking],
    top_ids: list[str],
) -> dict[str, Any] | None:
    ranked_ids = [ranking.molecule_id for ranking in rankings]
    routes = (
        db.query(SynthesisRoute)
        .filter(SynthesisRoute.molecule_id.in_(ranked_ids))
        .all()
    )
    hard_ids = [
        route.molecule_id
        for route in routes
        if not route.route_found or (route.route_steps is not None and route.route_steps > 5)
    ]
    if not hard_ids:
        return None
    return {
        "priority": "medium",
        "action": "simplify_synthesis_route",
        "target_molecule_ids": _ordered_subset(ranked_ids, hard_ids)[:3] or top_ids,
        "rationale": (
            "Prefer analogs with fewer surrogate route steps and buyable building blocks "
            "before committing expensive chemistry cycles."
        ),
        "source": "synthesis",
    }


def _filter_focus(
    db: Session,
    rankings: list[Ranking],
    top_ids: list[str],
) -> dict[str, Any] | None:
    ranked_ids = [ranking.molecule_id for ranking in rankings]
    results = (
        db.query(RuleFilterResult)
        .filter(RuleFilterResult.molecule_id.in_(ranked_ids))
        .all()
    )
    failed_ids = [result.molecule_id for result in results if result.failed_rules]
    if not failed_ids:
        return None
    return {
        "priority": "medium",
        "action": "repair_rule_filter_failures",
        "target_molecule_ids": _ordered_subset(ranked_ids, failed_ids)[:3] or top_ids,
        "rationale": (
            "Use failed drug-likeness and alert rules as design constraints for the next "
            "generation pass."
        ),
        "source": "rule_filter",
    }


def _critique_focus(
    critiques: dict[str, Critique],
    top_ids: list[str],
) -> dict[str, Any] | None:
    risky_top_ids = [
        molecule_id
        for molecule_id in top_ids
        if critiques.get(molecule_id) is not None
        and critiques[molecule_id].risk_level in {"medium", "high"}
    ]
    if not risky_top_ids:
        return None
    return {
        "priority": "high",
        "action": "resolve_self_refutation_findings",
        "target_molecule_ids": risky_top_ids,
        "rationale": (
            "Do not advance a top-ranked molecule until the explicit counter-evidence "
            "has either been resolved or accepted as a known risk."
        ),
        "source": "self_refutation",
    }


def _evidence_focus(
    rankings: list[Ranking],
    top_ids: list[str],
) -> dict[str, Any] | None:
    low_confidence_ids = [
        ranking.molecule_id
        for ranking in rankings
        if (ranking.evidence_confidence or 0) < 0.7
    ]
    if not low_confidence_ids:
        return None
    return {
        "priority": "medium",
        "action": "increase_evidence_confidence",
        "target_molecule_ids": _ordered_subset([r.molecule_id for r in rankings], low_confidence_ids)[:3]
        or top_ids,
        "rationale": (
            "Fill missing docking, ADMET, synthesis, or RAG evidence before treating the "
            "rank order as stable."
        ),
        "source": "evidence",
    }


def _fallback_suggestions(target_ids: list[str], needed: int) -> list[dict[str, Any]]:
    fallbacks = [
        {
            "priority": "medium",
            "action": "run_confirmatory_docking",
            "target_molecule_ids": target_ids,
            "rationale": "Confirm surrogate docking trends with prepared receptor and ligand files.",
            "source": "fallback",
        },
        {
            "priority": "medium",
            "action": "expand_near_top_scaffolds",
            "target_molecule_ids": target_ids,
            "rationale": "Generate close analogs around the best current scaffolds.",
            "source": "fallback",
        },
        {
            "priority": "low",
            "action": "capture_assay_assumptions",
            "target_molecule_ids": target_ids,
            "rationale": "Record assay, species, and target-context assumptions for later review.",
            "source": "fallback",
        },
    ]
    return fallbacks[:needed]


def _upsert_advisor_suggestion(
    db: Session,
    project: Project,
    summary: str,
    suggestions: list[dict[str, Any]],
    next_round_constraints: list[dict[str, Any]],
    suggested_generation_config: dict[str, Any],
) -> AdvisorSuggestion:
    records = (
        db.query(AdvisorSuggestion)
        .filter_by(project_id=project.project_id)
        .order_by(AdvisorSuggestion.id.asc())
        .all()
    )
    advisor = records[0] if records else None
    if advisor is None:
        advisor = AdvisorSuggestion(
            suggestion_id=new_id("ADV"),
            project_id=project.project_id,
            summary=summary,
            suggestions=suggestions,
            next_round_constraints=next_round_constraints,
            suggested_generation_config=suggested_generation_config,
        )
        db.add(advisor)
    else:
        advisor.summary = summary
        advisor.suggestions = suggestions
        advisor.next_round_constraints = next_round_constraints
        advisor.suggested_generation_config = suggested_generation_config

    for stale in records[1:]:
        db.delete(stale)
    return advisor


def _next_round_constraints(suggestions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    constraints: list[dict[str, Any]] = []
    for suggestion in suggestions:
        action = suggestion.get("action")
        if action == "reduce_admet_liabilities":
            constraints.extend(
                [
                    _constraint("advisor_admet_hERG", "hERG_risk", "!=", "high_risk", 90),
                    _constraint("advisor_admet_Ames", "Ames_risk", "!=", "high_risk", 88),
                    _constraint("advisor_solubility", "solubility", "!=", "low", 72),
                ]
            )
        elif action == "simplify_synthesis_route":
            constraints.append(_constraint("advisor_synthesis_steps", "route_steps", "<=", "5", 74))
        elif action == "repair_rule_filter_failures":
            constraints.append(_constraint("advisor_rule_filters", "failed_rules", "avoid", "drug_likeness_alerts", 70))
        elif action == "resolve_self_refutation_findings":
            constraints.append(_constraint("advisor_refutation", "refutation_decision", "=", "pass", 86))
        elif action == "increase_evidence_confidence":
            constraints.append(_constraint("advisor_evidence_confidence", "evidence_confidence", ">=", "0.7", 65))

    if not constraints:
        constraints.append(_constraint("advisor_evidence_confidence", "evidence_confidence", ">=", "0.7", 65))
    return _dedupe_constraints(constraints)


def _constraint(label: str, field: str, operator: str, value: str, priority: int) -> dict[str, Any]:
    return {
        "label": label,
        "field": field,
        "operator": operator,
        "value": value,
        "priority": priority,
    }


def _suggested_generation_config(
    rankings: list[Ranking],
    suggestions: list[dict[str, Any]],
) -> dict[str, Any]:
    seed_ids = [ranking.molecule_id for ranking in rankings[:5]]
    actions = [str(suggestion.get("action")) for suggestion in suggestions]
    return {
        "seed_molecule_ids": seed_ids,
        "generation_size": 50,
        "strategies": ["crem"],
        "avoid_refutation_decisions": ["reject"],
        "prioritize_actions": actions[:5],
        "rerank_after_generation": True,
    }


def _replace_advisor_constraints(
    db: Session,
    project: Project,
    constraints: list[dict[str, Any]],
) -> None:
    db.query(OptimizationConstraint).filter(
        OptimizationConstraint.project_id == project.project_id,
        OptimizationConstraint.label.like("advisor_%"),
    ).delete(synchronize_session=False)
    for item in constraints:
        db.add(
            OptimizationConstraint(
                constraint_id=new_id("CON"),
                project_id=project.project_id,
                label=str(item["label"]),
                field=str(item["field"]),
                operator=str(item["operator"]),
                value=str(item["value"]),
                priority=int(item["priority"]),
                source_message_id="advisor_agent",
            )
        )


def _dedupe_constraints(constraints: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str, str]] = set()
    deduped: list[dict[str, Any]] = []
    for item in constraints:
        key = (
            str(item["label"]),
            str(item["field"]),
            str(item["operator"]),
            str(item["value"]),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _summary(
    project: Project,
    rankings: list[Ranking],
    suggestions: list[dict[str, Any]],
) -> str:
    top = rankings[0].molecule_id if rankings else "no ranked molecule"
    return (
        f"{project.name}: generated {len(suggestions)} next-step suggestions; "
        f"current top candidate is {top}."
    )


def _ordered_subset(ordered_ids: list[str], selected_ids: list[str]) -> list[str]:
    selected = set(selected_ids)
    return [molecule_id for molecule_id in ordered_ids if molecule_id in selected]
