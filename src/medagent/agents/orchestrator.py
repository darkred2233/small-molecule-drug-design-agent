from sqlalchemy.orm import Session

from medagent.core.config import Settings
from medagent.db.models import AgentRun, Project
from medagent.services.ids import new_id


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

    def _resolve_model(self, default_model: str) -> str:
        model_map = {
            "qwen3.7-max": self.settings.qwen_reasoning_model,
            "qwen3.7-plus": self.settings.qwen_task_model,
            "deepseek-v4-pro": self.settings.deepseek_refutation_model,
            "text-embedding-v4": self.settings.embedding_model,
        }
        return model_map.get(default_model, default_model)
