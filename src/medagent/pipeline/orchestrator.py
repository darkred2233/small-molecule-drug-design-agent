from collections.abc import Callable
from dataclasses import asdict
from typing import Any

from sqlalchemy.orm import Session

from medagent.configs.settings import Settings
from medagent.agents.sar import SARAgent
from medagent.agents.target import TargetAgent
from medagent.db.models import AgentRun, Molecule, Project
from medagent.pipeline.graph import PIPELINE_AGENTS
from medagent.pipeline.state import (
    PIPELINE_COMPLETED,
    PIPELINE_FAILED,
    PIPELINE_QUEUED,
    PIPELINE_RUNNING,
)
from medagent.services.advisor import generate_project_advice
from medagent.services.candidate_assessment import run_project_candidate_assessment
from medagent.services.candidate_ranking import generate_project_rankings
from medagent.services.decision_cards import generate_project_decision_cards
from medagent.services.file_ingestion import parse_pending_project_files
from medagent.services.ids import new_id
from medagent.services.molecule_generation import generate_project_molecules
from medagent.services.molecule_import import import_seed_ligands_as_molecules
from medagent.services.molecule_validation import validate_project_molecules
from medagent.services.rag import build_project_rag_index
from medagent.reporting.project_report import build_project_report
from medagent.services.receptor_preparation import project_docking_config
from medagent.services.self_refutation import generate_project_critiques
from medagent.services.rule_filtering import filter_project_molecules


DEFAULT_PIPELINE_CONFIG = {
    "strategy_counts": {"reinvent4": 10, "crem": 10, "autogrow4": 10},
    "top_n": 20,
    "max_assessment_molecules": 50,
    "assessment_mode": "external",
    "external_top_n": 10,
    "generate_when_seeds_exist": True,
}
ASSESSMENT_MODES = {"fast", "external", "full"}
DEFAULT_GENERATION_CONSTRAINTS = {
    "max_mw": 500,
    "max_logp": 5,
    "max_tpsa": 140,
    "max_hbd": 5,
    "max_hba": 10,
}


class PipelineOrchestrator:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def create_dry_run(self, db: Session, project: Project) -> list[AgentRun]:
        runs: list[AgentRun] = []
        for agent_name, default_model in PIPELINE_AGENTS:
            model_name = self._resolve_model(default_model)
            run = AgentRun(
                agent_run_id=new_id("RUN"),
                project_id=project.project_id,
                agent_name=agent_name,
                model_name=model_name,
                status="queued",
                input_json={"project_id": project.project_id, "mode": "dry_run"},
                output_json={
                    "message": "Registered pipeline step. Real execution adapter is not connected yet."
                },
            )
            db.add(run)
            runs.append(run)
        project.status = PIPELINE_QUEUED
        db.commit()
        return runs

    def run_full(
        self,
        db: Session,
        project: Project,
        pipeline_config: dict[str, Any] | None = None,
    ) -> list[AgentRun]:
        config = _normalize_pipeline_config(project, pipeline_config)
        runs: list[AgentRun] = []
        project.status = PIPELINE_RUNNING
        db.commit()

        step_outputs: dict[str, dict[str, Any]] = {}

        def record_output(agent_name: str, output: dict[str, Any]) -> dict[str, Any]:
            step_outputs[agent_name] = output
            return output

        runs.append(
            self._run_step(
                db,
                project,
                "knowledge_ingestion_agent",
                "qwen3.7-plus",
                {"mode": "full"},
                lambda: record_output(
                    "knowledge_ingestion_agent",
                    self._run_knowledge_ingestion(db, project),
                ),
            )
        )
        runs.append(
            self._run_step(
                db,
                project,
                "molecule_import_agent",
                "tool-adapter",
                {
                    "mode": "full",
                    "seed_ligands_created": step_outputs["knowledge_ingestion_agent"].get(
                        "file_ingestion", {}
                    ).get("seed_ligands_created", 0),
                },
                lambda: record_output(
                    "molecule_import_agent",
                    import_seed_ligands_as_molecules(db, project),
                ),
            )
        )
        runs.append(
            self._run_step(
                db,
                project,
                "target_agent",
                "qwen3.7-plus",
                {"mode": "full", "target_id": project.target_id},
                lambda: record_output(
                    "target_agent",
                    self._run_target_analysis(db, project),
                ),
            )
        )
        runs.append(
            self._run_step(
                db,
                project,
                "sar_agent",
                "qwen3.7-plus",
                {
                    "mode": "full",
                    "seed_molecule_count": self._molecule_count(db, project),
                },
                lambda: record_output(
                    "sar_agent",
                    self._run_sar_analysis(db, project),
                ),
            )
        )
        runs.append(
            self._run_step(
                db,
                project,
                "generator_agent",
                "qwen3.7-max",
                {
                    "mode": "full",
                    "strategy_counts": config["strategy_counts"],
                    "requested_generation_size": config["generation_size"],
                },
                lambda: record_output(
                    "generator_agent",
                    self._run_generation_if_needed(db, project, config),
                ),
            )
        )
        runs.append(
            self._run_step(
                db,
                project,
                "validation_agent",
                "tool-adapter",
                {"mode": "full", "molecule_count": self._molecule_count(db, project)},
                lambda: record_output(
                    "validation_agent",
                    validate_project_molecules(db, project),
                ),
            )
        )
        runs.append(
            self._run_step(
                db,
                project,
                "filter_agent",
                "tool-adapter",
                {"mode": "full", "molecule_count": self._molecule_count(db, project)},
                lambda: record_output(
                    "filter_agent",
                    filter_project_molecules(db, project),
                ),
            )
        )
        runs.append(
            self._run_step(
                db,
                project,
                "candidate_assessment_agent",
                "tool-adapter",
                {
                    "mode": "full",
                    "max_molecules": config["max_assessment_molecules"],
                    "top_n": config["top_n"],
                    "assessment_mode": config["assessment_mode"],
                    "external_top_n": config["external_top_n"],
                    "passed_filter_count": self._molecule_count(db, project, status="passed_filter"),
                },
                lambda: record_output(
                    "candidate_assessment_agent",
                    run_project_candidate_assessment(
                        db,
                        project,
                        max_molecules=config["max_assessment_molecules"],
                        top_n=config["top_n"],
                        assessment_mode=config["assessment_mode"],
                        external_top_n=config["external_top_n"],
                    ),
                ),
            )
        )
        runs.append(
            self._run_step(
                db,
                project,
                "self_refutation_agent",
                "deepseek-v4-pro",
                {"mode": "full", "max_molecules": config["max_assessment_molecules"]},
                lambda: record_output(
                    "self_refutation_agent",
                    generate_project_critiques(
                        db,
                        project,
                        settings=self.settings,
                        max_molecules=config["max_assessment_molecules"],
                    ),
                ),
            )
        )
        runs.append(
            self._run_step(
                db,
                project,
                "ranker_agent",
                "qwen3.7-max",
                {
                    "mode": "full",
                    "max_molecules": config["max_assessment_molecules"],
                    "top_n": config["top_n"],
                    "source": "self_refutation",
                },
                lambda: record_output(
                    "ranker_agent",
                    generate_project_rankings(
                        db,
                        project,
                        max_molecules=config["max_assessment_molecules"],
                        top_n=config["top_n"],
                    ).as_dict(),
                ),
            )
        )
        runs.append(
            self._run_step(
                db,
                project,
                "advisor_agent",
                "qwen3.7-plus",
                {"mode": "full"},
                lambda: record_output(
                    "advisor_agent",
                    generate_project_advice(db, project),
                ),
            )
        )
        runs.append(
            self._run_step(
                db,
                project,
                "decision_card_agent",
                "qwen3.7-plus",
                {"mode": "full", "molecule_count": self._molecule_count(db, project)},
                lambda: record_output(
                    "decision_card_agent",
                    generate_project_decision_cards(db, project),
                ),
            )
        )
        project.status = PIPELINE_COMPLETED
        db.commit()
        runs.append(
            self._run_step(
                db,
                project,
                "report_agent",
                "qwen3.7-plus",
                {"mode": "full"},
                lambda: record_output(
                    "report_agent",
                    build_project_report(db, project),
                ),
            )
        )

        db.commit()
        return runs

    def _resolve_model(self, default_model: str) -> str:
        if default_model == "deepseek-v4-pro" and not self.settings.self_refutation_use_llm:
            return "heuristic_self_refutation"
        model_map = {
            "qwen3.7-max": self.settings.qwen_reasoning_model,
            "qwen3.7-plus": self.settings.qwen_task_model,
            "deepseek-v4-pro": self.settings.deepseek_refutation_model,
            "text-embedding-v4": self.settings.embedding_model,
        }
        return model_map.get(default_model, default_model)

    def _run_step(
        self,
        db: Session,
        project: Project,
        agent_name: str,
        default_model: str,
        input_json: dict[str, Any],
        operation: Callable[[], dict[str, Any]],
    ) -> AgentRun:
        run = AgentRun(
            agent_run_id=new_id("RUN"),
            project_id=project.project_id,
            agent_name=agent_name,
            model_name=self._resolve_model(default_model),
            status="running",
            input_json={"project_id": project.project_id, **input_json},
            output_json={},
        )
        db.add(run)
        db.commit()

        try:
            output = operation()
        except Exception as exc:
            db.rollback()
            run.status = "failed"
            run.error_message = str(exc)
            run.output_json = {"error": str(exc)}
            project.status = PIPELINE_FAILED
            db.add(run)
            db.add(project)
            db.commit()
            raise

        run.status = "completed"
        run.output_json = output
        run.error_message = None
        db.commit()
        return run

    def _run_knowledge_ingestion(self, db: Session, project: Project) -> dict[str, Any]:
        file_ingestion = parse_pending_project_files(db, self.settings, project)
        rag_index = build_project_rag_index(
            db,
            self.settings,
            project,
            include_builtin_target=True,
            include_uploads=True,
            rebuild=True,
        )
        return {
            "file_ingestion": file_ingestion,
            "rag_index": rag_index,
        }

    def _run_target_analysis(self, db: Session, project: Project) -> dict[str, Any]:
        use_llm = bool(self.settings.dashscope_api_key)
        report = TargetAgent(db).analyze_target(project, use_llm=use_llm)
        return {
            **asdict(report),
            "analysis_mode": "llm_with_rule_fallback" if use_llm else "rule_based",
        }

    def _run_sar_analysis(self, db: Session, project: Project) -> dict[str, Any]:
        use_llm = bool(self.settings.dashscope_api_key)
        report = SARAgent(db).analyze_sar(project, use_llm=use_llm)
        return {
            **asdict(report),
            "analysis_mode": "llm_with_rule_fallback" if use_llm else "rule_based",
        }

    def _run_generation_if_needed(
        self,
        db: Session,
        project: Project,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        existing_count = self._molecule_count(db, project)
        strategy_counts = config["strategy_counts"]
        requested_size = config["generation_size"]
        selected_strategies = [
            strategy for strategy, count in strategy_counts.items() if count > 0
        ]
        if requested_size <= 0:
            return {
                "skipped": True,
                "reason": "generation_size_is_zero",
                "molecule_count": existing_count,
                "strategy_counts": strategy_counts,
            }
        if existing_count > 0 and not config["generate_when_seeds_exist"]:
            return {
                "skipped": True,
                "reason": "existing_molecules_available",
                "molecule_count": existing_count,
                "strategy_counts": strategy_counts,
            }
        try:
            generation_constraints = dict(
                config.get("generation_constraints") or DEFAULT_GENERATION_CONSTRAINTS
            )
            docking_config = project_docking_config(
                db,
                project,
                generation_constraints.get("binding_site_id"),
            )
            if docking_config.get("protein_file"):
                generation_constraints.setdefault(
                    "receptor_file",
                    docking_config["protein_file"],
                )
            for key in ("grid_center", "grid_size", "key_residues"):
                if docking_config.get(key):
                    generation_constraints.setdefault(key, docking_config[key])
            return generate_project_molecules(
                db,
                project,
                generation_size=requested_size,
                strategies=selected_strategies,
                strategy_counts=strategy_counts,
                constraints=generation_constraints,
                include_target_library_seeds=True,
                agent_run_name="molecule_generation_tool_agent",
            )
        except ValueError as exc:
            if str(exc) != "generation_requires_at_least_one_seed_ligand":
                raise
            return {
                "skipped": True,
                "reason": "generation_requires_at_least_one_seed_ligand",
                "molecule_count": 0,
                "warnings": [str(exc)],
            }

    def _molecule_count(self, db: Session, project: Project, status: str | None = None) -> int:
        query = db.query(Molecule).filter_by(project_id=project.project_id)
        if status is not None:
            query = query.filter_by(status=status)
        return query.count()


def _normalize_pipeline_config(
    project: Project,
    override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    stored = (project.constraints_json or {}).get("pipeline_config", {})
    raw = {
        **DEFAULT_PIPELINE_CONFIG,
        **(stored if isinstance(stored, dict) else {}),
        **(override if isinstance(override, dict) else {}),
    }
    strategy_counts = _normalize_strategy_counts(raw.get("strategy_counts"))
    top_n = _bounded_int(raw.get("top_n"), DEFAULT_PIPELINE_CONFIG["top_n"], 1, 500)
    max_assessment_molecules = _bounded_int(
        raw.get("max_assessment_molecules"),
        max(top_n, DEFAULT_PIPELINE_CONFIG["max_assessment_molecules"]),
        1,
        500,
    )
    max_assessment_molecules = max(max_assessment_molecules, top_n)
    generation_constraints = _normalize_generation_constraints(stored, raw)
    assessment_mode = _normalize_assessment_mode(raw.get("assessment_mode"))
    external_top_n = _bounded_int(
        raw.get("external_top_n"),
        DEFAULT_PIPELINE_CONFIG["external_top_n"],
        1,
        100,
    )
    return {
        "strategy_counts": strategy_counts,
        "generation_size": sum(strategy_counts.values()),
        "top_n": top_n,
        "max_assessment_molecules": max_assessment_molecules,
        "assessment_mode": assessment_mode,
        "external_top_n": external_top_n,
        "generate_when_seeds_exist": bool(raw.get("generate_when_seeds_exist", True)),
        "generation_constraints": generation_constraints,
    }


def _normalize_strategy_counts(raw: Any) -> dict[str, int]:
    defaults = DEFAULT_PIPELINE_CONFIG["strategy_counts"]
    if not isinstance(raw, dict):
        raw = {}
    counts: dict[str, int] = {}
    for strategy, default_count in defaults.items():
        counts[strategy] = _bounded_int(raw.get(strategy), default_count, 0, 500)
    return counts


def _normalize_generation_constraints(stored: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
    constraints = dict(DEFAULT_GENERATION_CONSTRAINTS)
    for source in (
        stored.get("generation_constraints") if isinstance(stored, dict) else None,
        raw.get("generation_constraints"),
    ):
        if isinstance(source, dict):
            constraints.update({key: value for key, value in source.items() if value is not None})
    return constraints


def _normalize_assessment_mode(value: Any) -> str:
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in ASSESSMENT_MODES:
            return normalized
    return DEFAULT_PIPELINE_CONFIG["assessment_mode"]


def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))
