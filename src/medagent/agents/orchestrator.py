from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from medagent.core.config import Settings
from medagent.db.models import AgentRun, Molecule, Project
from medagent.services.candidate_assessment import run_project_candidate_assessment
from medagent.services.decision_cards import generate_project_decision_cards
from medagent.services.file_ingestion import parse_pending_project_files
from medagent.services.ids import new_id
from medagent.services.molecule_generation import generate_project_molecules
from medagent.services.molecule_import import import_seed_ligands_as_molecules
from medagent.services.molecule_validation import validate_project_molecules
from medagent.services.rag import build_project_rag_index
from medagent.services.rule_filtering import filter_project_molecules


PIPELINE_AGENTS = [
    ("conversation_agent", "qwen3.7-plus"),
    ("knowledge_ingestion_agent", "qwen3.7-plus"),
    ("rag_builder_agent", "text-embedding-v4"),
    ("target_agent", "qwen3.7-plus"),
    ("sar_agent", "qwen3.7-plus"),
    ("generator_agent", "qwen3.7-max"),
    ("filter_agent", "tool-adapter"),
    ("docking_agent", "tool-adapter"),
    ("admet_agent", "tool-adapter"),
    ("synthesis_agent", "tool-adapter"),
    ("self_refutation_agent", "deepseek-v4-pro"),
    ("ranker_agent", "qwen3.7-max"),
    ("advisor_agent", "qwen3.7-plus"),
    ("report_agent", "qwen3.7-plus"),
]

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
        project.status = "pipeline_queued"
        db.commit()
        return runs

    def run_full(self, db: Session, project: Project) -> list[AgentRun]:
        runs: list[AgentRun] = []
        project.status = "pipeline_running"
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
                "generator_agent",
                "qwen3.7-max",
                {"mode": "full", "minimum_candidate_count": 1},
                lambda: record_output(
                    "generator_agent",
                    self._run_generation_if_needed(db, project),
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
                    "max_molecules": 50,
                    "passed_filter_count": self._molecule_count(db, project, status="passed_filter"),
                },
                lambda: record_output(
                    "candidate_assessment_agent",
                    run_project_candidate_assessment(db, project, max_molecules=50),
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

        project.status = "pipeline_completed"
        db.commit()
        return runs

    def _resolve_model(self, default_model: str) -> str:
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
            run.status = "failed"
            run.error_message = str(exc)
            run.output_json = {"error": str(exc)}
            project.status = "pipeline_failed"
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

    def _run_generation_if_needed(self, db: Session, project: Project) -> dict[str, Any]:
        existing_count = self._molecule_count(db, project)
        if existing_count > 0:
            return {
                "skipped": True,
                "reason": "existing_molecules_available",
                "molecule_count": existing_count,
            }
        try:
            return generate_project_molecules(
                db,
                project,
                generation_size=3,
                strategies=["crem"],
                constraints={},
                include_target_library_seeds=True,
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
