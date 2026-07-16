import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from medagent.data.target_metadata import get_target_admet_risks, get_target_sar_rules
from medagent.db.models import (
    ADMETResult,
    AgentRun,
    AdvisorSuggestion,
    BindingSite,
    Critique,
    DecisionCard,
    DockingResult,
    EvidenceLink,
    Molecule,
    OptimizationConstraint,
    Project,
    RagChunk,
    RagDocument,
    Ranking,
    ReasoningTrace,
    RuleFilterResult,
    SeedLigand,
    SynthesisRoute,
    Target,
)
from medagent.services.docking_adapters import (
    pose_artifact_available,
    pose_coordinates_from_file,
)
from medagent.services.narrative import attach_narrative_layer


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
    "molecule_narratives",
    "final_report",
    "evidence_links",
    "technical_appendix",
]


def build_project_report(db: Session, project: Project) -> dict[str, Any]:
    constraints = _constraints(db, project)
    target = _target(db, project)
    binding_sites = _binding_sites(db, project)
    seed_ligands = _seed_ligands(db, project)
    rankings = _rankings(db, project)
    molecules = _molecules_by_id(db, project)
    rule_filters = _rule_filters_by_molecule_id(db, molecules)
    docking_results = _docking_results_by_molecule_id(db, molecules)
    admet_results = _admet_results_by_molecule_id(db, molecules)
    synthesis_routes = _synthesis_routes_by_molecule_id(db, molecules)
    critiques = _critiques_by_molecule_id(db, project)
    advisor = _latest_advisor_suggestion(db, project)
    decision_cards = _decision_cards(db, project)
    traces = _reasoning_traces(db, project)
    evidence_links = _evidence_links_by_molecule_id(db, molecules)
    evidence_context = _rag_evidence_context(db, evidence_links)
    target_agent_analysis = _latest_agent_output(db, project, "target_agent")
    sar_agent_analysis = _latest_agent_output(db, project, "sar_agent")
    iterative_orchestrator_output = _latest_agent_output(
        db,
        project,
        "iterative_orchestrator_agent",
    )

    report = {
        "project_summary": {
            "project_id": project.project_id,
            "name": project.name,
            "target_id": project.target_id,
            "target_name": target.name if target else None,
            "objective": project.objective,
            "status": project.status,
        },
        "target_and_pocket_analysis": _target_and_pocket_analysis(
            project,
            target,
            binding_sites,
            seed_ligands,
            target_agent_analysis,
        ),
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
            "seed_ligand_count": len(seed_ligands),
            "binding_site_count": len(binding_sites),
            "rule_filter_count": sum(len(items) for items in rule_filters.values()),
            "admet_result_count": len(admet_results),
            "synthesis_route_count": len(synthesis_routes),
        },
        "sar_overview": _sar_overview(project, rule_filters, sar_agent_analysis),
        "admet_overview": _admet_overview(project, admet_results),
        "synthesis_overview": _synthesis_overview(synthesis_routes),
        "top_candidates": _top_candidates(
            rankings,
            molecules,
            critiques,
            evidence_links,
            evidence_context,
            rule_filters,
            docking_results,
            admet_results,
            synthesis_routes,
        ),
        "self_refutation": _self_refutation_summary(critiques),
        "advisor_suggestions": {
            "suggestion_id": advisor.suggestion_id if advisor else None,
            "summary": advisor.summary if advisor else None,
            "suggestions": advisor.suggestions if advisor else [],
            "next_round_constraints": advisor.next_round_constraints if advisor else [],
            "suggested_generation_config": advisor.suggested_generation_config if advisor else {},
        },
        "evidence_links": _flatten_evidence_links(evidence_links, evidence_context),
        "refutation_chains": _refutation_chains(critiques),
        "decision_cards": [
            {
                "decision_id": card.decision_id,
                "molecule_id": card.molecule_id,
                "decision": card.decision,
                "confidence": card.confidence,
                "claim_status": (card.provenance or {}).get("claim_status"),
                "confidence_semantics": (card.provenance or {}).get("confidence_semantics"),
                "evidence_ids": card.evidence_ids or [],
                "provenance": card.provenance or {},
            }
            for card in decision_cards
        ],
        "sections": REPORT_SECTIONS,
        "technical_appendix": {
            "generated_at": datetime.now(UTC).isoformat(),
            "source": "project_report_service",
            "report_schema_version": "2.0",
            "score_semantics": "heuristic_not_probability_unless_explicitly_stated",
            "iterative_orchestrator": iterative_orchestrator_output,
        },
    }
    attach_narrative_layer(report)
    report_file = _write_report_file(project, report)
    report["report_file"] = report_file
    return report


def _target(db: Session, project: Project) -> Target | None:
    if not project.target_id:
        return None
    return db.query(Target).filter_by(target_id=project.target_id).one_or_none()


def _latest_agent_output(
    db: Session,
    project: Project,
    agent_name: str,
) -> dict[str, Any] | None:
    run = (
        db.query(AgentRun)
        .filter_by(
            project_id=project.project_id,
            agent_name=agent_name,
            status="completed",
        )
        .order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
        .first()
    )
    if run is None or not isinstance(run.output_json, dict):
        return None
    return run.output_json


def _binding_sites(db: Session, project: Project) -> list[BindingSite]:
    project_sites = (
        db.query(BindingSite)
        .filter_by(project_id=project.project_id)
        .order_by(BindingSite.created_at.asc(), BindingSite.id.asc())
        .all()
    )
    target_sites: list[BindingSite] = []
    if project.target_id:
        target_sites = (
            db.query(BindingSite)
            .filter(BindingSite.project_id.is_(None), BindingSite.target_id == project.target_id)
            .order_by(BindingSite.created_at.asc(), BindingSite.id.asc())
            .all()
        )
    by_id: dict[str, BindingSite] = {}
    for site in project_sites + target_sites:
        by_id[site.binding_site_id] = site
    return list(by_id.values())


def _seed_ligands(db: Session, project: Project) -> list[SeedLigand]:
    return (
        db.query(SeedLigand)
        .filter_by(project_id=project.project_id)
        .order_by(SeedLigand.id.asc())
        .all()
    )


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


def _rule_filters_by_molecule_id(
    db: Session,
    molecules: dict[str, Molecule],
) -> dict[str, list[RuleFilterResult]]:
    if not molecules:
        return {}
    results = (
        db.query(RuleFilterResult)
        .filter(RuleFilterResult.molecule_id.in_(list(molecules.keys())))
        .order_by(RuleFilterResult.created_at.asc(), RuleFilterResult.id.asc())
        .all()
    )
    by_molecule: dict[str, list[RuleFilterResult]] = {molecule_id: [] for molecule_id in molecules}
    for result in results:
        by_molecule.setdefault(result.molecule_id, []).append(result)
    return by_molecule


def _docking_results_by_molecule_id(
    db: Session,
    molecules: dict[str, Molecule],
) -> dict[str, DockingResult]:
    if not molecules:
        return {}
    results = (
        db.query(DockingResult)
        .filter(DockingResult.molecule_id.in_(list(molecules.keys())))
        .order_by(DockingResult.created_at.asc(), DockingResult.id.asc())
        .all()
    )
    return {result.molecule_id: result for result in results}


def _admet_results_by_molecule_id(
    db: Session,
    molecules: dict[str, Molecule],
) -> dict[str, ADMETResult]:
    if not molecules:
        return {}
    results = (
        db.query(ADMETResult)
        .filter(ADMETResult.molecule_id.in_(list(molecules.keys())))
        .order_by(ADMETResult.created_at.asc(), ADMETResult.id.asc())
        .all()
    )
    return {result.molecule_id: result for result in results}


def _synthesis_routes_by_molecule_id(
    db: Session,
    molecules: dict[str, Molecule],
) -> dict[str, SynthesisRoute]:
    if not molecules:
        return {}
    results = (
        db.query(SynthesisRoute)
        .filter(SynthesisRoute.molecule_id.in_(list(molecules.keys())))
        .order_by(SynthesisRoute.created_at.asc(), SynthesisRoute.id.asc())
        .all()
    )
    return {result.molecule_id: result for result in results}


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


def _rag_evidence_context(
    db: Session,
    evidence_links: dict[str, list[EvidenceLink]],
) -> dict[str, dict[str, Any]]:
    chunk_ids = {
        link.chunk_id
        for links in evidence_links.values()
        for link in links
        if link.chunk_id is not None
    }
    if not chunk_ids:
        return {}
    chunks = db.query(RagChunk).filter(RagChunk.chunk_id.in_(chunk_ids)).all()
    document_ids = {chunk.document_id for chunk in chunks}
    documents = (
        db.query(RagDocument).filter(RagDocument.document_id.in_(document_ids)).all()
        if document_ids
        else []
    )
    documents_by_id = {document.document_id: document for document in documents}
    context: dict[str, dict[str, Any]] = {}
    for chunk in chunks:
        document = documents_by_id.get(chunk.document_id)
        metadata = document.metadata_json or {} if document is not None else {}
        context[chunk.chunk_id] = {
            "document_id": chunk.document_id,
            "document_title": document.title if document is not None else None,
            "document_source": document.source if document is not None else None,
            "document_type": document.document_type if document is not None else None,
            "filename": metadata.get("filename"),
            "page_number": chunk.page_number,
            "section": chunk.section,
            "content": chunk.content,
            "chunk_index": (chunk.metadata_json or {}).get("chunk_index"),
            "embedding_model": chunk.embedding_model,
            "embedding_ref": chunk.embedding_ref,
        }
    return context


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


def _target_and_pocket_analysis(
    project: Project,
    target: Target | None,
    binding_sites: list[BindingSite],
    seed_ligands: list[SeedLigand],
    target_agent_analysis: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "target": {
            "target_id": project.target_id,
            "name": target.name if target else project.target_id,
            "aliases": target.aliases if target else [],
            "uniprot_id": target.uniprot_id if target else None,
            "species": target.species if target else None,
            "pdb_ids": target.pdb_ids if target else [],
            "summary": target.summary if target else None,
            "pocket_summary": target.pocket_summary if target else None,
        },
        "binding_sites": [_binding_site_summary(site) for site in binding_sites],
        "seed_ligands": [
            {
                "ligand_id": ligand.ligand_id,
                "name": ligand.name,
                "smiles": ligand.smiles,
                "activity_value": ligand.activity_value,
                "activity_unit": ligand.activity_unit,
                "source": ligand.source,
            }
            for ligand in seed_ligands
        ],
        "counts": {
            "binding_site_count": len(binding_sites),
            "seed_ligand_count": len(seed_ligands),
        },
        "agent_analysis": target_agent_analysis,
    }


def _binding_site_summary(site: BindingSite) -> dict[str, Any]:
    grid_box = site.grid_box or {}
    preparation_json = site.preparation_json or {}
    return {
        "binding_site_id": site.binding_site_id,
        "target_id": site.target_id,
        "project_id": site.project_id,
        "pdb_id": site.pdb_id,
        "site_name": grid_box.get("site_name"),
        "reference_ligand": grid_box.get("reference_ligand"),
        "source_url": grid_box.get("source_url"),
        "preparation_status": site.preparation_status,
        "key_residues": site.key_residues or [],
        "grid_box": {
            "center": grid_box.get("center") or grid_box.get("grid_center"),
            "size": grid_box.get("size") or grid_box.get("grid_size"),
            "unit": grid_box.get("unit"),
            "method": grid_box.get("method"),
        },
        "labels": preparation_json.get("labels", []),
        "warnings": preparation_json.get("warnings", []),
    }


def _sar_overview(
    project: Project,
    rule_filters: dict[str, list[RuleFilterResult]],
    sar_agent_analysis: dict[str, Any] | None,
) -> dict[str, Any]:
    all_results = [result for results in rule_filters.values() for result in results]
    failed_rule_counts: dict[str, int] = {}
    warning_counts: dict[str, int] = {}
    decision_counts: dict[str, int] = {}
    for result in all_results:
        decision_counts[result.decision] = decision_counts.get(result.decision, 0) + 1
        for rule_name in result.failed_rules or []:
            failed_rule_counts[rule_name] = failed_rule_counts.get(rule_name, 0) + 1
        for warning in result.warnings or []:
            warning_counts[warning] = warning_counts.get(warning, 0) + 1

    return {
        "agent_analysis": sar_agent_analysis,
        "target_sar_rules": get_target_sar_rules(project.target_id),
        "rule_filter_statistics": {
            "result_count": len(all_results),
            "decision_counts": decision_counts,
            "failed_rule_counts": failed_rule_counts,
            "warning_counts": warning_counts,
        },
        "molecule_rule_findings": [
            _rule_filter_summary(result)
            for result in all_results
            if result.failed_rules or result.warnings or result.labels
        ],
    }


def _admet_overview(
    project: Project,
    admet_results: dict[str, ADMETResult],
) -> dict[str, Any]:
    herg_counts: dict[str, int] = {}
    ames_counts: dict[str, int] = {}
    solubility_counts: dict[str, int] = {}
    permeability_counts: dict[str, int] = {}
    raw_risk_counts: dict[str, dict[str, int]] = {}
    high_risk_molecules: list[dict[str, Any]] = []

    for molecule_id, result in admet_results.items():
        _count(herg_counts, result.hERG_risk)
        _count(ames_counts, result.Ames_risk)
        _count(solubility_counts, result.solubility)
        _count(permeability_counts, result.permeability)
        raw_output = result.raw_output or {}
        for key in ("CYP3A4_inhibition", "CYP2D6_inhibition", "DILI_risk", "Pgp_substrate", "BBB_penetration"):
            risk = _raw_risk_label(raw_output.get(key))
            if risk:
                raw_risk_counts.setdefault(key, {})
                raw_risk_counts[key][risk] = raw_risk_counts[key].get(risk, 0) + 1
        if result.hERG_risk == "high_risk" or result.Ames_risk == "high_risk":
            high_risk_molecules.append(_admet_summary(molecule_id, result))

    return {
        "target_admet_risks": get_target_admet_risks(project.target_id),
        "result_count": len(admet_results),
        "risk_counts": {
            "hERG": herg_counts,
            "Ames": ames_counts,
            "solubility": solubility_counts,
            "permeability": permeability_counts,
            **raw_risk_counts,
        },
        "high_risk_molecules": high_risk_molecules,
    }


def _synthesis_overview(synthesis_routes: dict[str, SynthesisRoute]) -> dict[str, Any]:
    route_found_count = sum(1 for route in synthesis_routes.values() if route.route_found)
    route_step_values = [
        route.route_steps for route in synthesis_routes.values() if route.route_steps is not None
    ]
    confidence_values = [
        route.route_confidence
        for route in synthesis_routes.values()
        if route.route_confidence is not None
    ]
    label_counts: dict[str, int] = {}
    for route in synthesis_routes.values():
        for label in route.labels or []:
            label_counts[label] = label_counts.get(label, 0) + 1

    return {
        "result_count": len(synthesis_routes),
        "route_found_count": route_found_count,
        "route_missing_count": len(synthesis_routes) - route_found_count,
        "average_route_steps": _average(route_step_values),
        "average_route_confidence": _average(confidence_values),
        "label_counts": label_counts,
        "routes": [
            _synthesis_summary(molecule_id, route)
            for molecule_id, route in synthesis_routes.items()
        ],
    }


def _top_candidates(
    rankings: list[Ranking],
    molecules: dict[str, Molecule],
    critiques: dict[str, Critique],
    evidence_links: dict[str, list[EvidenceLink]],
    evidence_context: dict[str, dict[str, Any]],
    rule_filters: dict[str, list[RuleFilterResult]],
    docking_results: dict[str, DockingResult],
    admet_results: dict[str, ADMETResult],
    synthesis_routes: dict[str, SynthesisRoute],
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
                "generation_source_agent": molecule.source_agent if molecule else None,
                "generation_method": _generation_method(molecule),
                "overall_score": ranking.overall_score,
                "pro_score": ranking.pro_score,
                "con_score": ranking.con_score,
                "evidence_confidence": ranking.evidence_confidence,
                "ranking_score_semantics": "heuristic_not_probability",
                "evidence_confidence_semantics": "heuristic_completeness_not_probability",
                "final_decision": ranking.final_decision,
                "risk_level": critique.risk_level if critique else None,
                "refutation_decision": critique.refutation_decision if critique else None,
                "rule_filter": [
                    _rule_filter_summary(result)
                    for result in rule_filters.get(ranking.molecule_id, [])
                ],
                "docking": _docking_summary(docking_results.get(ranking.molecule_id)),
                "admet": _admet_summary(
                    ranking.molecule_id,
                    admet_results.get(ranking.molecule_id),
                ),
                "synthesis": _synthesis_summary(
                    ranking.molecule_id,
                    synthesis_routes.get(ranking.molecule_id),
                ),
                "evidence_chain": _evidence_chain(
                    evidence_links.get(ranking.molecule_id, []),
                    evidence_context,
                ),
                "refutation_chain": _refutation_chain(critique),
            }
        )
    return candidates


def _generation_method(molecule: Molecule | None) -> str | None:
    if molecule is None:
        return None
    if molecule.source_agent == "seed_ligand_import":
        return "seed_ligand_import"
    if molecule.source_agent and ":" in molecule.source_agent:
        return molecule.source_agent.split(":", 1)[1]
    for label in molecule.labels or []:
        if label.startswith("generator_strategy_"):
            return label.removeprefix("generator_strategy_")
    return molecule.source_agent


def _evidence_chain(
    links: list[EvidenceLink],
    evidence_context: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {
            "evidence_id": link.evidence_id,
            "chunk_id": link.chunk_id,
            "claim_type": link.claim_type,
            "confidence": link.confidence,
            "evidence_confidence": link.confidence,
            "evidence_confidence_semantics": (
                "legacy_retrieval_score_not_probability"
                if link.confidence is not None
                else "not_calibrated"
            ),
            "rationale": link.rationale,
            **evidence_context.get(link.chunk_id, {}),
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
        "analysis_method": critique.analysis_method,
        "llm_provider": critique.llm_provider,
    }


def _rule_filter_summary(result: RuleFilterResult) -> dict[str, Any]:
    return {
        "filter_result_id": result.filter_result_id,
        "molecule_id": result.molecule_id,
        "rule_set": result.rule_set,
        "decision": result.decision,
        "failed_rules": result.failed_rules or [],
        "warnings": result.warnings or [],
        "labels": result.labels or [],
        "properties_snapshot": result.properties_snapshot or {},
        "sar_notes": (result.raw_output or {}).get("sar_notes", []),
    }


def _docking_summary(result: DockingResult | None) -> dict[str, Any] | None:
    if result is None:
        return None
    raw_output = result.raw_output or {}
    selected_pose_rank = raw_output.get("selected_pose_rank")
    pose_selection_method = raw_output.get("pose_selection_method")
    pose_available = pose_artifact_available(result.pose_file)
    pose_coordinates = pose_coordinates_from_file(result.pose_file) if pose_available else None
    best_pose_confirmed = raw_output.get("best_pose_confirmed")
    if best_pose_confirmed is None:
        best_pose_confirmed = bool(
            selected_pose_rank == 1
            and pose_selection_method
            and "not_confirmed" not in pose_selection_method
        )
    best_pose_confirmed = bool(best_pose_confirmed and pose_available)
    return {
        "vina_score": result.vina_score,
        "cnn_score": result.cnn_score,
        "diffdock_confidence": result.diffdock_confidence,
        "key_hbond_count": result.key_hbond_count,
        "clash_count": result.clash_count,
        "pose_file": result.pose_file if pose_available else None,
        "pose_artifact_available": pose_available,
        "pose_coordinates": pose_coordinates,
        "selected_pose_rank": selected_pose_rank,
        "pose_count": raw_output.get("pose_count"),
        "pose_selection_method": pose_selection_method,
        "best_pose_confirmed": best_pose_confirmed,
        "labels": result.labels or [],
        "raw_output": raw_output,
    }


def _admet_summary(molecule_id: str, result: ADMETResult | None) -> dict[str, Any] | None:
    if result is None:
        return None
    raw_output = result.raw_output or {}
    return {
        "molecule_id": molecule_id,
        "hERG": {
            "probability": result.hERG_probability,
            "risk": result.hERG_risk,
        },
        "Ames": {
            "probability": result.Ames_probability,
            "risk": result.Ames_risk,
        },
        "solubility": result.solubility,
        "permeability": result.permeability,
        "admet_risk_score": result.admet_risk_score,
        "CYP3A4": raw_output.get("CYP3A4_inhibition"),
        "CYP2D6": raw_output.get("CYP2D6_inhibition"),
        "DILI": raw_output.get("DILI_risk"),
        "Pgp": raw_output.get("Pgp_substrate"),
        "BBB": raw_output.get("BBB_penetration"),
        "labels": result.labels or [],
        "adapter_mode": raw_output.get("adapter_mode"),
        "tool_name": raw_output.get("tool_name"),
        "tool_version": raw_output.get("tool_version"),
        "model_name": raw_output.get("model_name"),
        "model_count": raw_output.get("model_count"),
        "compute_device": raw_output.get("compute_device"),
        "result_kind": raw_output.get("result_kind"),
    }


def _synthesis_summary(molecule_id: str, route: SynthesisRoute | None) -> dict[str, Any] | None:
    if route is None:
        return None
    route_json = route.route_json or {}
    labels = route.labels or []
    result_kind = route_json.get("result_kind")
    is_surrogate_estimate = (
        route_json.get("adapter_mode") == "rdkit_surrogate_synthesis"
        or route_json.get("status") == "surrogate_only"
        or result_kind == "non_retrosynthesis_coarse_estimate"
        or "rdkit_surrogate_synthesis" in labels
    )
    estimated_route_feasible = route_json.get("estimated_route_feasible")
    display_route_found = bool(route.route_found or estimated_route_feasible)
    display_route_steps = route.route_steps
    if display_route_steps is None:
        display_route_steps = route_json.get("estimated_route_steps")
    display_buyable_blocks = route.buyable_building_blocks
    if display_buyable_blocks is None:
        display_buyable_blocks = route_json.get("estimated_buyable_building_blocks")
    route_plan = route_json.get("route_plan") or _fallback_route_plan(
        display_route_found,
        display_route_steps,
        display_buyable_blocks,
    )
    starting_materials = route_json.get("starting_materials") or _fallback_starting_materials(
        display_buyable_blocks
    )
    route_note = route_json.get("route_note") or (
        "Route details are a surrogate synthesis blueprint unless AiZynthFinder output is configured."
    )
    if is_surrogate_estimate:
        route_plan = []
        starting_materials = []
        route_note = (
            "RDKit synthetic-accessibility estimate only; external retrosynthesis was not run "
            "for this molecule."
        )
    return {
        "molecule_id": molecule_id,
        "route_found": route.route_found,
        "route_steps": route.route_steps,
        "route_confidence": route.route_confidence,
        "buyable_building_blocks": route.buyable_building_blocks,
        "SA_score": route_json.get("SA_score"),
        "SCScore": route_json.get("SCScore"),
        "estimated_route_feasible": estimated_route_feasible,
        "estimated_route_steps": route_json.get("estimated_route_steps"),
        "estimated_route_confidence": route_json.get("estimated_route_confidence"),
        "estimated_buyable_building_blocks": route_json.get("estimated_buyable_building_blocks"),
        "hazardous_reaction_count": route_json.get("hazardous_reaction_count"),
        "protecting_group_count": route_json.get("protecting_group_count"),
        "route_summary": route_json.get("route_summary"),
        "route_plan": route_plan,
        "starting_materials": starting_materials,
        "route_risks": route_json.get("route_risks")
        or _fallback_route_risks(display_route_found, display_route_steps),
        "route_note": route_note,
        "adapter_mode": route_json.get("adapter_mode"),
        "result_kind": result_kind,
        "route_metadata": route_json.get("route_metadata"),
        "has_reaction_tree": bool(route_json.get("route_trees")),
        "labels": labels,
    }


def _fallback_starting_materials(buyable_blocks: int | None) -> list[str]:
    count = max(1, buyable_blocks or 1)
    materials = ["commercial aryl/heteroaryl core", "polar linker fragment", "late-stage R-group fragment"]
    return materials[:count]


def _fallback_route_plan(
    route_found: bool,
    route_steps: int | None,
    buyable_blocks: int | None,
) -> list[dict[str, Any]]:
    steps = route_steps or 3
    plan = [
        {
            "step": 1,
            "stage": "Building-block selection",
            "input": _fallback_starting_materials(buyable_blocks),
            "operation": "Select purchasable fragments compatible with the candidate scaffold.",
            "output": "Fragment set for analog synthesis.",
        },
        {
            "step": 2,
            "stage": "Scaffold assembly",
            "input": ["core fragment", "linker or cap fragment"],
            "operation": "Assemble the candidate core through the main bond-forming transformation.",
            "output": "Advanced intermediate.",
        },
        {
            "step": 3,
            "stage": "Late-stage optimization",
            "input": ["advanced intermediate"],
            "operation": "Install final substituents and purify the candidate.",
            "output": "Target molecule candidate.",
        },
    ]
    if steps > 3:
        plan.append(
            {
                "step": 4,
                "stage": "Complexity management",
                "input": ["target molecule candidate"],
                "operation": "Resolve additional purification, salt/form, or protecting-group needs.",
                "output": "Screening-ready batch.",
            }
        )
    if not route_found:
        plan.append(
            {
                "step": len(plan) + 1,
                "stage": "Route redesign",
                "input": ["current candidate"],
                "operation": "Simplify motifs or choose alternate building blocks before nomination.",
                "output": "Revised candidate proposal.",
            }
        )
    return plan


def _fallback_route_risks(route_found: bool, route_steps: int | None) -> list[str]:
    risks: list[str] = []
    if not route_found:
        risks.append("No confident route was found within the surrogate assessment.")
    if route_steps is not None and route_steps > 6:
        risks.append(f"Estimated route length is high: {route_steps} steps.")
    if not risks:
        risks.append("No major surrogate route risk detected.")
    return risks


def _flatten_evidence_links(
    evidence_links: dict[str, list[EvidenceLink]],
    evidence_context: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    flattened: list[dict[str, Any]] = []
    for molecule_id, links in evidence_links.items():
        for item in _evidence_chain(links, evidence_context):
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


def _count(counter: dict[str, int], key: str | None) -> None:
    if not key:
        return
    counter[str(key)] = counter.get(str(key), 0) + 1


def _raw_risk_label(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, dict):
        raw_value = value.get("risk") or value.get("label") or value.get("value")
        return str(raw_value) if raw_value else None
    if isinstance(value, str):
        return value
    return str(value)


def _average(values: list[float | int]) -> float | None:
    if not values:
        return None
    return round(float(sum(values)) / len(values), 4)


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
