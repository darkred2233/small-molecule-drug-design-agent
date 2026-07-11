import json
from typing import Any

from sqlalchemy.orm import Session

from medagent.db.models import (
    ADMETResult,
    AgentRun,
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


class AdvisorSuggestionNotFoundError(LookupError):
    """Raised when a project has no Advisor output to apply."""


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


def apply_latest_advisor_suggestion(db: Session, project: Project) -> dict[str, Any]:
    advisor = _latest_advisor_suggestion(db, project)
    if advisor is None:
        raise AdvisorSuggestionNotFoundError(
            f"No advisor suggestion is available for project {project.project_id}."
        )

    next_round_constraints = _normalize_constraint_items(advisor.next_round_constraints or [])
    sync_summary = _sync_advisor_constraints(db, project, advisor, next_round_constraints)
    generation_payload = _build_next_round_generation_payload(
        project,
        advisor,
        next_round_constraints,
    )
    agent_run = _record_apply_agent_run(
        db,
        project,
        advisor,
        sync_summary,
        generation_payload,
    )
    db.commit()

    return {
        "status": "applied",
        "project_id": project.project_id,
        "suggestion_id": advisor.suggestion_id,
        "agent_run_id": agent_run.agent_run_id,
        "applied_constraint_count": len(next_round_constraints),
        "created_constraint_count": sync_summary["created_constraint_count"],
        "updated_constraint_count": sync_summary["updated_constraint_count"],
        "unchanged_constraint_count": sync_summary["unchanged_constraint_count"],
        "removed_constraint_count": sync_summary["removed_constraint_count"],
        "applied_constraint_ids": sync_summary["applied_constraint_ids"],
        "next_round_constraints": next_round_constraints,
        "suggested_generation_config": advisor.suggested_generation_config or {},
        "generation_payload": generation_payload,
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


def _latest_advisor_suggestion(db: Session, project: Project) -> AdvisorSuggestion | None:
    return (
        db.query(AdvisorSuggestion)
        .filter_by(project_id=project.project_id)
        .order_by(AdvisorSuggestion.updated_at.desc(), AdvisorSuggestion.id.desc())
        .first()
    )


def _normalize_constraint_items(constraints: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(constraints, start=1):
        name = _optional_str(item.get("name"))
        label = str(item.get("label") or name or f"advisor_constraint_{index}").strip()
        if not label.startswith("advisor_"):
            label = f"advisor_{label}"
        normalized.append(
            {
                "label": label,
                "field": _optional_str(item.get("field")) or name,
                "operator": _optional_str(item.get("operator"))
                or _operator_from_constraint_type(item),
                "value": _constraint_value(item),
                "priority": _normalize_priority(item.get("priority")),
            }
        )
    return _dedupe_constraints(normalized)


def _sync_advisor_constraints(
    db: Session,
    project: Project,
    advisor: AdvisorSuggestion,
    constraints: list[dict[str, Any]],
) -> dict[str, Any]:
    existing_constraints = (
        db.query(OptimizationConstraint)
        .filter(
            OptimizationConstraint.project_id == project.project_id,
            OptimizationConstraint.label.like("advisor_%"),
        )
        .order_by(OptimizationConstraint.id.asc())
        .all()
    )
    desired_signatures = {_constraint_signature(item) for item in constraints}
    existing_by_signature = {
        _constraint_signature_from_model(item): item
        for item in existing_constraints
    }

    removed_count = 0
    for item in existing_constraints:
        signature = _constraint_signature_from_model(item)
        if signature not in desired_signatures:
            db.delete(item)
            removed_count += 1

    created_count = 0
    updated_count = 0
    unchanged_count = 0
    applied_constraint_ids: list[str] = []

    for item in constraints:
        signature = _constraint_signature(item)
        existing = existing_by_signature.get(signature)
        if existing is None:
            existing = OptimizationConstraint(
                constraint_id=new_id("CON"),
                project_id=project.project_id,
                label=str(item["label"]),
                field=item["field"],
                operator=item["operator"],
                value=item["value"],
                priority=int(item["priority"]),
                source_message_id=advisor.suggestion_id,
            )
            db.add(existing)
            created_count += 1
        else:
            changed = False
            if existing.priority != int(item["priority"]):
                existing.priority = int(item["priority"])
                changed = True
            if existing.source_message_id != advisor.suggestion_id:
                existing.source_message_id = advisor.suggestion_id
                changed = True
            if changed:
                updated_count += 1
            else:
                unchanged_count += 1
        applied_constraint_ids.append(existing.constraint_id)

    db.flush()
    return {
        "created_constraint_count": created_count,
        "updated_constraint_count": updated_count,
        "unchanged_constraint_count": unchanged_count,
        "removed_constraint_count": removed_count,
        "applied_constraint_ids": applied_constraint_ids,
    }


def _build_next_round_generation_payload(
    project: Project,
    advisor: AdvisorSuggestion,
    constraints: list[dict[str, Any]],
) -> dict[str, Any]:
    config = advisor.suggested_generation_config or {}
    generation_size = _normalize_generation_size(config.get("generation_size"))
    generation_constraints = _generation_constraints_from_config(config)
    if constraints:
        generation_constraints = {
            **generation_constraints,
            "advisor_constraints": constraints,
        }
    return {
        "project_id": project.project_id,
        "source_suggestion_id": advisor.suggestion_id,
        "generation_request": {
            "generation_size": generation_size,
            "strategies": _normalize_generation_strategies(config.get("strategies")),
            "constraints": generation_constraints,
            "include_target_library_seeds": True,
        },
        "generation_config_normalization": {
            "requested_generation_size": config.get("generation_size"),
            "applied_generation_size": generation_size,
            "max_generation_size": 500,
        },
        "seed_molecule_ids": _normalize_string_list(config.get("seed_molecule_ids")),
        "post_generation_constraints": constraints,
        "prioritize_actions": _normalize_string_list(config.get("prioritize_actions")),
        "avoid_refutation_decisions": _normalize_string_list(
            config.get("avoid_refutation_decisions")
        ),
        "rerank_after_generation": bool(config.get("rerank_after_generation", True)),
    }


def _record_apply_agent_run(
    db: Session,
    project: Project,
    advisor: AdvisorSuggestion,
    sync_summary: dict[str, Any],
    generation_payload: dict[str, Any],
) -> AgentRun:
    agent_run = AgentRun(
        agent_run_id=new_id("RUN"),
        project_id=project.project_id,
        agent_name="advisor_apply_agent",
        model_name="deterministic-planner",
        status="completed",
        input_json={
            "project_id": project.project_id,
            "suggestion_id": advisor.suggestion_id,
            "next_round_constraint_count": len(advisor.next_round_constraints or []),
        },
        output_json={
            "status": "applied",
            **sync_summary,
            "suggested_generation_config": advisor.suggested_generation_config or {},
            "generation_payload": generation_payload,
        },
    )
    db.add(agent_run)
    db.flush()
    return agent_run


def _constraint_signature(item: dict[str, Any]) -> tuple[str, str | None, str | None, str | None]:
    return (
        str(item["label"]),
        item.get("field"),
        item.get("operator"),
        item.get("value"),
    )


def _constraint_signature_from_model(
    constraint: OptimizationConstraint,
) -> tuple[str, str | None, str | None, str | None]:
    return (
        constraint.label,
        constraint.field,
        constraint.operator,
        constraint.value,
    )


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _operator_from_constraint_type(item: dict[str, Any]) -> str | None:
    constraint_type = _optional_str(item.get("constraint_type"))
    if constraint_type == "hard_constraint":
        return "="
    if constraint_type == "soft_constraint":
        return "target_range" if item.get("target_range") is not None else "prefer"
    if constraint_type == "penalty":
        return "penalty"
    if constraint_type == "editable_region":
        return "prefer"
    return None


def _constraint_value(item: dict[str, Any]) -> str | None:
    for key in ["value", "target_range", "preferred_substituents", "weight"]:
        if key in item:
            return _json_string(item[key])
    return None


def _json_string(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _generation_constraints_from_config(config: dict[str, Any]) -> dict[str, Any]:
    reserved_keys = {
        "generation_size",
        "strategies",
        "seed_molecule_ids",
        "avoid_refutation_decisions",
        "prioritize_actions",
        "rerank_after_generation",
    }
    return {
        key: value
        for key, value in config.items()
        if key not in reserved_keys
    }


def _normalize_priority(value: Any) -> int:
    try:
        priority = int(value)
    except (TypeError, ValueError):
        priority = 50
    return max(0, min(priority, 100))


def _normalize_generation_size(value: Any) -> int:
    try:
        generation_size = int(value)
    except (TypeError, ValueError):
        generation_size = 50
    return max(1, min(generation_size, 500))


def _normalize_generation_strategies(value: Any) -> list[str]:
    allowed = {"reinvent4", "crem", "autogrow4"}
    if not isinstance(value, list):
        return ["crem"]
    strategies = [
        str(item).lower().strip()
        for item in value
        if str(item).lower().strip() in allowed
    ]
    return _dedupe(strategies) or ["crem"]


def _normalize_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return _dedupe([str(item).strip() for item in value if str(item).strip()])


def _dedupe_constraints(constraints: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str | None, str | None, str | None]] = set()
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


def _dedupe(values: list[str]) -> list[str]:
    deduped: list[str] = []
    for value in values:
        if value in deduped:
            continue
        deduped.append(value)
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
