from typing import Any

from sqlalchemy.orm import Session

from medagent.agents.generation import run_generation_agent
from medagent.configs.settings import Settings
from medagent.db.models import AgentRun, Molecule, Project, Ranking
from medagent.domain.schemas import AgentResult, AgentTask, RunPlan
from medagent.pipeline.state import PIPELINE_FAILED
from medagent.services.advisor import generate_project_advice
from medagent.services.sar_bridge import sar_to_generation_constraints
from medagent.services.candidate_assessment import (
    candidate_assessment_tool_status,
    run_project_candidate_assessment,
    run_project_synthesis,
)
from medagent.services.candidate_ranking import generate_project_rankings
from medagent.services.ids import new_id
from medagent.services.molecule_generation import (
    _standardize_or_normalize_smiles,
    collect_generation_seed_smiles,
)
from medagent.services.molecule_import import is_lightly_valid_smiles
from medagent.services.molecule_validation import merge_labels, validate_project_molecules
from medagent.services.narrative import (
    persist_project_final_report,
    persist_project_molecule_narratives,
)
from medagent.reporting.project_report import build_project_report
from medagent.services.receptor_preparation import project_docking_config
from medagent.services.run_plan import DEFAULT_GENERATION_CONSTRAINTS
from medagent.services.rule_filtering import filter_project_molecules


class PipelineOrchestrator:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def run_iterative(
        self,
        db: Session,
        project: Project,
        run_plan: RunPlan | dict[str, Any] | None = None,
    ) -> list[AgentRun]:
        from medagent.services.run_plan import ensure_project_run_plan, save_project_run_plan

        plan = _coerce_run_plan(run_plan) if run_plan is not None else ensure_project_run_plan(project)
        plan.status = "running"
        save_project_run_plan(project, plan)
        project.status = "iterative_running"

        orchestrator_run = AgentRun(
            agent_run_id=new_id("RUN"),
            project_id=project.project_id,
            agent_name="iterative_orchestrator_agent",
            model_name="deterministic-orchestrator",
            status="running",
            input_json={
                "project_id": project.project_id,
                "run_plan": _schema_to_payload(plan),
            },
            output_json={
                "rounds": [],
                "status": "running",
            },
        )
        db.add(orchestrator_run)
        db.add(project)
        db.commit()

        runs: list[AgentRun] = [orchestrator_run]
        round_summaries: list[dict[str, Any]] = []
        final_route_summary: dict[str, Any] | None = None
        stop_reason = "max_rounds_reached"
        previous_top_score: float | None = None
        consecutive_tool_failures = 0
        seeds = _initial_iterative_seed_smiles(db, project, plan)
        advisor_context: list[str] = []
        sar_constraints: dict[str, Any] = {}

        try:
            if not seeds:
                stop_reason = "generation_requires_at_least_one_seed_ligand"
            else:
                for round_number in range(1, plan.max_rounds + 1):
                    remaining_total = plan.stopping.max_total_molecules - self._molecule_count(db, project)
                    if remaining_total <= 0:
                        stop_reason = "max_total_molecules_reached"
                        break

                    tasks = _generation_tasks_from_run_plan(
                        db,
                        project,
                        plan,
                        round_number=round_number,
                        seed_molecules=seeds,
                        sar_context=advisor_context,
                        sar_constraints=sar_constraints,
                        remaining_total=remaining_total,
                    )
                    if not tasks:
                        stop_reason = "run_plan_has_no_enabled_generation_agents"
                        break

                    round_summary: dict[str, Any] = {
                        "round": round_number,
                        "stage": "generation",
                        "status": "running",
                        "active_agent": None,
                        "seed_molecules": seeds,
                        "agents": [],
                        "stored_molecule_ids": [],
                        "validation": None,
                        "filtering": None,
                        "assessment": None,
                        "advisor": None,
                        "top_score": None,
                        "score_improvement": None,
                        "stop_reason": None,
                    }
                    round_summaries.append(round_summary)
                    _update_iterative_run(orchestrator_run, round_summaries, stop_reason=None)
                    db.commit()
                    stored_molecule_ids: list[str] = []
                    round_agent_failures = 0

                    for task in tasks:
                        round_summary["stage"] = "generation"
                        round_summary["active_agent"] = task.agent
                        _update_iterative_run(orchestrator_run, round_summaries, stop_reason=None)
                        db.commit()
                        agent_run, result, storage_summary = self._run_generation_agent_task(
                            db,
                            project,
                            task,
                        )
                        runs.append(agent_run)
                        round_summary["agents"].append(
                            {
                                "agent_run_id": agent_run.agent_run_id,
                                "agent": task.agent,
                                "status": result.status,
                                "success": result.success,
                                "failure_reason": result.failure_reason,
                                "warnings": result.warnings,
                                "requested_count": task.constraints.get("requested_count"),
                                "proposed_count": len(result.molecules),
                                "stored_count": storage_summary["stored_count"],
                                "molecule_ids": storage_summary["molecule_ids"],
                            }
                        )
                        stored_molecule_ids.extend(storage_summary["molecule_ids"])
                        if not result.success and result.status != "skipped":
                            round_agent_failures += 1
                        round_summary["active_agent"] = None
                        _update_iterative_run(orchestrator_run, round_summaries, stop_reason=None)
                        db.commit()

                    stored_molecule_ids = _dedupe(stored_molecule_ids)
                    round_summary["stored_molecule_ids"] = stored_molecule_ids
                    if round_agent_failures:
                        consecutive_tool_failures += round_agent_failures
                    else:
                        consecutive_tool_failures = 0

                    if not stored_molecule_ids:
                        round_summary["stop_reason"] = "round_returned_no_new_candidates"
                        round_summary["stage"] = "completed"
                        round_summary["status"] = "stopped"
                        stop_reason = "round_returned_no_new_candidates"
                        _update_iterative_run(orchestrator_run, round_summaries, stop_reason)
                        db.commit()
                        break

                    round_summary["stage"] = "validation"
                    _update_iterative_run(orchestrator_run, round_summaries, stop_reason=None)
                    db.commit()
                    round_summary["validation"] = validate_project_molecules(db, project)
                    if plan.evaluation.use_filters:
                        round_summary["stage"] = "filtering"
                        _update_iterative_run(orchestrator_run, round_summaries, stop_reason=None)
                        db.commit()
                        round_summary["filtering"] = filter_project_molecules(db, project)

                    round_summary["stage"] = "assessment"
                    _update_iterative_run(orchestrator_run, round_summaries, stop_reason=None)
                    db.commit()
                    round_summary["assessment"] = self._run_iterative_round_assessment(
                        db,
                        project,
                        plan,
                        molecule_ids=stored_molecule_ids,
                        round_number=round_number,
                    )
                    round_summary["stage"] = "sar"
                    _update_iterative_run(orchestrator_run, round_summaries, stop_reason=None)
                    db.commit()
                    sar_result = _run_sar_analysis(db, self.settings, project)
                    round_summary["sar"] = sar_result.get("summary", {})
                    sar_constraints = sar_result.get("constraints", {})
                    sar_context_strings = sar_result.get("sar_context", [])

                    round_summary["stage"] = "advisor"
                    _update_iterative_run(orchestrator_run, round_summaries, stop_reason=None)
                    db.commit()
                    round_summary["advisor"] = generate_project_advice(db, project)
                    advisor_context = _advisor_context(round_summary["advisor"]) + sar_context_strings

                    top_score = _top_ranking_score(db, project)
                    round_summary["top_score"] = top_score
                    if previous_top_score is not None and top_score is not None:
                        round_summary["score_improvement"] = round(top_score - previous_top_score, 3)
                    if top_score is not None:
                        previous_top_score = top_score

                    seeds = _top_ranked_seed_smiles(
                        db,
                        project,
                        top_n=min(plan.evaluation.top_n, plan.next_round_seed_count),
                    ) or seeds
                    round_summary["stage"] = "completed"
                    round_summary["status"] = "completed"
                    _update_iterative_run(orchestrator_run, round_summaries, stop_reason=None)
                    db.commit()

                    if consecutive_tool_failures >= plan.stopping.max_tool_failures:
                        stop_reason = "max_tool_failures_reached"
                        round_summary["stop_reason"] = stop_reason
                        break
                    if self._molecule_count(db, project) >= plan.stopping.max_total_molecules:
                        stop_reason = "max_total_molecules_reached"
                        round_summary["stop_reason"] = stop_reason
                        break
                    improvement = round_summary.get("score_improvement")
                    if (
                        round_number > 1
                        and plan.stopping.min_score_improvement > 0
                        and improvement is not None
                        and improvement < plan.stopping.min_score_improvement
                    ):
                        stop_reason = "min_score_improvement_not_met"
                        round_summary["stop_reason"] = stop_reason
                        break

            final_route_summary = self._run_final_synthesis_routes_if_needed(db, project, plan)
            if final_route_summary is not None:
                round_summaries.append(
                    {
                        "round": "final_route_prediction",
                        "synthesis_routes": final_route_summary,
                    }
                )
                generate_project_advice(db, project)

            plan.status = "completed"
            plan.decision_trace.append(
                {
                    "step": "run_iterative_completed",
                    "reason": "RunPlan 已由 iterative orchestrator 执行完成。",
                    "rounds_executed": len(
                        [item for item in round_summaries if isinstance(item.get("round"), int)]
                    ),
                    "stop_reason": stop_reason,
                }
            )
            save_project_run_plan(project, plan)
            project.status = "iterative_completed"
            orchestrator_run.status = "completed"
            orchestrator_run.output_json = {
                "status": "completed",
                "stop_reason": stop_reason,
                "rounds": round_summaries,
                "final_synthesis_routes": final_route_summary,
            }
            db.add(project)
            db.add(orchestrator_run)
            db.commit()
            report = build_project_report(db, project)
            runs.append(
                persist_project_molecule_narratives(
                    db,
                    project,
                    report,
                    top_n=plan.evaluation.top_n,
                )
            )
            runs.append(persist_project_final_report(db, project, report))
            return runs
        except Exception as exc:
            db.rollback()
            plan.status = "failed"
            plan.warnings.append(f"run_iterative_failed:{type(exc).__name__}")
            save_project_run_plan(project, plan)
            project.status = PIPELINE_FAILED
            failed_run = (
                db.query(AgentRun)
                .filter_by(agent_run_id=orchestrator_run.agent_run_id)
                .one_or_none()
            )
            if failed_run is None:
                failed_run = orchestrator_run
                db.add(failed_run)
            failed_run.status = "failed"
            failed_run.error_message = str(exc)
            failed_run.output_json = {
                "status": "failed",
                "error": str(exc),
                "rounds": round_summaries,
            }
            db.add(project)
            db.commit()
            raise

    def _run_iterative_round_assessment(
        self,
        db: Session,
        project: Project,
        plan: RunPlan,
        *,
        molecule_ids: list[str],
        round_number: int,
    ) -> dict[str, Any]:
        assessment_mode = _assessment_mode_for_run_plan(plan)
        external_synthesis_routes = (
            plan.evaluation.use_synthesis
            and plan.evaluation.synthesis_route_scope == "every_round_top_n"
        )
        docking_config = project_docking_config(
            db,
            project,
            plan.constraints.get("binding_site_id"),
        )
        return run_project_candidate_assessment(
            db,
            project,
            molecule_ids=molecule_ids,
            max_molecules=len(molecule_ids),
            top_n=plan.evaluation.top_n,
            assessment_mode=assessment_mode,
            external_top_n=plan.evaluation.top_n,
            binding_site_id=docking_config.get("binding_site_id"),
            protein_file=docking_config.get("protein_file"),
            grid_center=docking_config.get("grid_center"),
            grid_size=docking_config.get("grid_size"),
            key_residues=docking_config.get("key_residues") or [],
            max_synthesis_steps=_bounded_int(
                plan.constraints.get("max_synthesis_steps"),
                5,
                1,
                12,
            ),
            prefer_buyable_building_blocks=bool(
                plan.constraints.get("prefer_buyable_building_blocks", True)
            ),
            enable_external_synthesis_routes=external_synthesis_routes,
        ) | {
            "round": round_number,
            "external_synthesis_route_scope": plan.evaluation.synthesis_route_scope,
        }

    def _run_generation_agent_task(
        self,
        db: Session,
        project: Project,
        task: AgentTask,
    ) -> tuple[AgentRun, AgentResult, dict[str, Any]]:
        agent_run = AgentRun(
            agent_run_id=new_id("RUN"),
            project_id=project.project_id,
            agent_name=f"{task.agent}_agent",
            model_name="tool-adapter",
            status="running",
            input_json={"project_id": project.project_id, "task": _schema_to_payload(task)},
            output_json={},
        )
        db.add(agent_run)
        db.commit()

        try:
            result = run_generation_agent(task)
            storage_summary = _store_agent_result_molecules(db, project, result)
            agent_run.status = result.status
            agent_run.output_json = {
                "result": _schema_to_payload(result),
                "storage": storage_summary,
            }
            agent_run.error_message = result.failure_reason
            db.add(agent_run)
            db.commit()
            return agent_run, result, storage_summary
        except Exception as exc:
            result = AgentResult(
                agent=task.agent,
                round=task.round,
                success=False,
                status="failed",
                molecules=[],
                warnings=[],
                failure_reason=f"generation_agent_exception:{type(exc).__name__}",
            )
            agent_run.status = "failed"
            agent_run.error_message = str(exc)
            agent_run.output_json = {
                "result": _schema_to_payload(result),
                "error": str(exc),
                "storage": _empty_storage_summary(),
            }
            db.add(agent_run)
            db.commit()
            return agent_run, result, _empty_storage_summary()

    def _run_final_synthesis_routes_if_needed(
        self,
        db: Session,
        project: Project,
        plan: RunPlan,
    ) -> dict[str, Any] | None:
        if not plan.evaluation.use_synthesis:
            return None
        if plan.evaluation.synthesis_route_scope != "final_round_top_n":
            return None

        top_molecules = _top_ranked_molecules(db, project, top_n=plan.evaluation.top_n)
        if not top_molecules:
            return {
                "skipped": True,
                "reason": "no_ranked_molecules_for_final_synthesis_routes",
            }

        tool_status = candidate_assessment_tool_status()
        synthesis = run_project_synthesis(
            db,
            project,
            top_molecules,
            tool_status,
            allow_external_tools=True,
            max_synthesis_steps=_bounded_int(
                plan.constraints.get("max_synthesis_steps"),
                5,
                1,
                12,
            ),
            prefer_buyable_building_blocks=bool(
                plan.constraints.get("prefer_buyable_building_blocks", True)
            ),
        )
        ranking = generate_project_rankings(
            db,
            project,
            molecules=top_molecules,
            max_molecules=len(top_molecules),
            top_n=plan.evaluation.top_n,
            tool_status=tool_status,
        )
        return {
            "skipped": False,
            "scope": "final_round_top_n",
            "molecule_ids": [molecule.molecule_id for molecule in top_molecules],
            "synthesis": synthesis.as_dict(),
            "ranking": ranking.as_dict(),
        }

    def _molecule_count(self, db: Session, project: Project, status: str | None = None) -> int:
        query = db.query(Molecule).filter_by(project_id=project.project_id)
        if status is not None:
            query = query.filter_by(status=status)
        return query.count()


def _generation_tasks_from_run_plan(
    db: Session,
    project: Project,
    plan: RunPlan,
    *,
    round_number: int,
    seed_molecules: list[str],
    sar_context: list[str],
    sar_constraints: dict[str, Any] | None = None,
    remaining_total: int,
) -> list[AgentTask]:
    constraints = _generation_constraints_for_round(
        db, project, plan,
        round_number=round_number,
        sar_constraints=sar_constraints,
    )
    tasks: list[AgentTask] = []
    remaining = max(0, remaining_total)
    for agent_name in ("reinvent4", "crem", "autogrow4"):
        config = plan.agents.get(agent_name)
        if config is None or config.enabled is False:
            continue
        requested_count = min(config.requested_count, remaining)
        if requested_count <= 0:
            continue
        agent_constraints = {
            **constraints,
            "requested_count": requested_count,
        }
        tasks.append(
            AgentTask(
                round=round_number,
                agent=agent_name,
                seed_molecules=seed_molecules,
                constraints=agent_constraints,
                budget=config.budget,
                sar_context=sar_context,
                evaluation_context={
                    "target_id": project.target_id,
                    "objective": plan.objective,
                    "use_docking": plan.evaluation.use_docking,
                    "use_admet": plan.evaluation.use_admet,
                    "use_synthesis": plan.evaluation.use_synthesis,
                    "synthesis_route_scope": plan.evaluation.synthesis_route_scope,
                    "top_n": plan.evaluation.top_n,
                },
            )
        )
        remaining -= requested_count
    return tasks


def _generation_constraints_for_round(
    db: Session,
    project: Project,
    plan: RunPlan,
    *,
    round_number: int,
    sar_constraints: dict[str, Any] | None = None,
) -> dict[str, Any]:
    constraints = {
        **DEFAULT_GENERATION_CONSTRAINTS,
        **dict(plan.constraints or {}),
        **(sar_constraints or {}),
        "optimization_round": round_number,
    }
    docking_config = project_docking_config(db, project, constraints.get("binding_site_id"))
    if docking_config.get("protein_file"):
        constraints.setdefault("receptor_file", docking_config["protein_file"])
    for key in ("grid_center", "grid_size", "key_residues", "binding_site_id"):
        if docking_config.get(key):
            constraints.setdefault(key, docking_config[key])
    return constraints


def _store_agent_result_molecules(
    db: Session,
    project: Project,
    result: AgentResult,
) -> dict[str, Any]:
    summary = _empty_storage_summary()
    existing_smiles = {
        _standardize_or_normalize_smiles(row[0])
        for row in db.query(Molecule.smiles).filter_by(project_id=project.project_id).all()
    }
    seen_in_result: set[str] = set()

    for candidate in result.molecules:
        normalized_smiles = _standardize_or_normalize_smiles(candidate.smiles)
        if not is_lightly_valid_smiles(normalized_smiles):
            summary["invalid_count"] += 1
            summary["failed_reason_summary"]["invalid_smiles"] = (
                summary["failed_reason_summary"].get("invalid_smiles", 0) + 1
            )
            continue
        if normalized_smiles in existing_smiles or normalized_smiles in seen_in_result:
            summary["duplicate_count"] += 1
            summary["failed_reason_summary"]["duplicate"] = (
                summary["failed_reason_summary"].get("duplicate", 0) + 1
            )
            continue

        source_strategy = str(candidate.provenance.get("source_strategy") or result.agent)
        molecule = Molecule(
            molecule_id=new_id("MOL"),
            project_id=project.project_id,
            smiles=normalized_smiles,
            inchi_key=None,
            scaffold=None,
            source_agent=f"{result.agent}_agent",
            status="generated",
            labels=merge_labels(
                [
                    "generated",
                    "candidate_generated",
                    "requires_structure_validation",
                    f"generation_agent_{result.agent}",
                    f"generator_strategy_{source_strategy}",
                    f"optimization_round_{result.round}",
                ],
                list(candidate.metadata.get("labels") or []),
            ),
        )
        db.add(molecule)
        db.flush()

        existing_smiles.add(normalized_smiles)
        seen_in_result.add(normalized_smiles)
        summary["stored_count"] += 1
        summary["molecule_ids"].append(molecule.molecule_id)
        summary["stored_candidates"].append(
            {
                "molecule_id": molecule.molecule_id,
                "smiles": normalized_smiles,
                "rationale": candidate.rationale,
                "provenance": candidate.provenance,
                "metadata": candidate.metadata,
            }
        )

    if result.status == "completed":
        project.status = "molecules_generated"
    db.add(project)
    db.commit()
    return summary


def _empty_storage_summary() -> dict[str, Any]:
    return {
        "stored_count": 0,
        "duplicate_count": 0,
        "invalid_count": 0,
        "failed_reason_summary": {},
        "molecule_ids": [],
        "stored_candidates": [],
    }


def _assessment_mode_for_run_plan(plan: RunPlan) -> str:
    if plan.evaluation.mode == "external_top_n":
        return "external"
    return plan.evaluation.mode


def _top_ranked_molecules(db: Session, project: Project, *, top_n: int) -> list[Molecule]:
    rankings = (
        db.query(Ranking)
        .filter_by(project_id=project.project_id)
        .order_by(Ranking.rank.asc(), Ranking.id.asc())
        .limit(top_n)
        .all()
    )
    molecules: list[Molecule] = []
    for ranking in rankings:
        molecule = db.query(Molecule).filter_by(molecule_id=ranking.molecule_id).one_or_none()
        if molecule is not None:
            molecules.append(molecule)
    return molecules


def _top_ranked_seed_smiles(db: Session, project: Project, *, top_n: int) -> list[str]:
    seeds: list[str] = []
    for molecule in _top_ranked_molecules(db, project, top_n=top_n):
        if molecule.status in {"invalid_structure", "failed_filter", "failed_assessment"}:
            continue
        normalized = _standardize_or_normalize_smiles(molecule.smiles)
        if normalized and normalized not in seeds:
            seeds.append(normalized)
    return seeds


def _initial_iterative_seed_smiles(db: Session, project: Project, plan: RunPlan) -> list[str]:
    manual_seeds = [
        normalized
        for value in plan.seed_smiles
        for normalized in [_standardize_or_normalize_smiles(value)]
        if normalized and is_lightly_valid_smiles(normalized)
    ]
    previous_top_seeds = _top_ranked_seed_smiles(
        db,
        project,
        top_n=min(plan.evaluation.top_n, plan.next_round_seed_count),
    )
    project_seeds = collect_generation_seed_smiles(db, project, include_target_library_seeds=True)
    return _dedupe([*manual_seeds, *previous_top_seeds, *project_seeds])


def _top_ranking_score(db: Session, project: Project) -> float | None:
    ranking = (
        db.query(Ranking)
        .filter_by(project_id=project.project_id)
        .order_by(Ranking.rank.asc(), Ranking.id.asc())
        .first()
    )
    if ranking is None or ranking.overall_score is None:
        return None
    return float(ranking.overall_score)


def _run_sar_analysis(
    db: Session,
    settings: Any,
    project: Project,
) -> dict[str, Any]:
    """Run SAR analysis and return constraints + context for the next round."""
    try:
        from medagent.agents.sar import SARAgent

        use_llm = bool(getattr(settings, "dashscope_api_key", None))
        sar_report = SARAgent(db).analyze_sar(project, use_llm=use_llm)
        bridge = sar_to_generation_constraints(sar_report)
        return {
            "summary": {
                "molecules_analyzed": sar_report.molecules_analyzed,
                "patterns_count": len(sar_report.sar_patterns),
                "pharmacophores_count": len(sar_report.pharmacophores),
                "suggestions_count": len(sar_report.optimization_suggestions),
                "key_findings": sar_report.key_findings,
                "warnings": sar_report.warnings,
            },
            "constraints": bridge["constraints"],
            "sar_context": bridge["sar_context"],
        }
    except Exception as exc:
        return {
            "summary": {"error": str(exc)},
            "constraints": {},
            "sar_context": [f"sar_analysis_failed:{type(exc).__name__}"],
        }


def _advisor_context(advisor_output: dict[str, Any] | None) -> list[str]:
    if not advisor_output:
        return []
    context: list[str] = []
    for suggestion in advisor_output.get("suggestions") or []:
        action = suggestion.get("action")
        rationale = suggestion.get("rationale")
        if action or rationale:
            context.append(": ".join(str(item) for item in [action, rationale] if item))
    for constraint in advisor_output.get("next_round_constraints") or []:
        field = constraint.get("field")
        operator = constraint.get("operator")
        value = constraint.get("value")
        if field:
            context.append(f"advisor_constraint: {field} {operator or ''} {value or ''}".strip())
    return _dedupe(context)


def _update_iterative_run(
    orchestrator_run: AgentRun,
    rounds: list[dict[str, Any]],
    stop_reason: str | None,
) -> None:
    orchestrator_run.output_json = {
        "status": "running",
        "stop_reason": stop_reason,
        "rounds": rounds,
        "completed_rounds": len([item for item in rounds if isinstance(item.get("round"), int)]),
    }


def _coerce_run_plan(payload: RunPlan | dict[str, Any]) -> RunPlan:
    if isinstance(payload, RunPlan):
        return payload
    if hasattr(RunPlan, "model_validate"):
        return RunPlan.model_validate(payload)
    return RunPlan.parse_obj(payload)


def _schema_to_payload(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "dict"):
        return value.dict()
    return value


def _dedupe(values: list[str]) -> list[str]:
    deduped: list[str] = []
    for value in values:
        if value in deduped:
            continue
        deduped.append(value)
    return deduped


def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))
