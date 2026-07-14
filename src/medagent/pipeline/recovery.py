"""
Pipeline recovery and checkpoint management.

This module provides:
- Checkpoint saving after each successful step
- Recovery from failed steps
- State rollback on critical errors
- Idempotent step execution
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from medagent.db.models import AgentRun, Project
from medagent.pipeline.state import PIPELINE_FAILED, PIPELINE_RUNNING


class PipelineCheckpoint:
    """Manages pipeline checkpoints for recovery."""

    def __init__(self, project_id: str, checkpoint_dir: Path | None = None):
        self.project_id = project_id
        if checkpoint_dir is None:
            checkpoint_dir = Path(".local") / "checkpoints" / self._safe_path_part(project_id)
        self.checkpoint_dir = checkpoint_dir
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

    def save(self, step_name: str, data: dict[str, Any]) -> Path:
        """Save checkpoint after successful step execution."""
        checkpoint_file = self.checkpoint_dir / f"{step_name}.json"
        checkpoint = {
            "project_id": self.project_id,
            "step_name": step_name,
            "data": data,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        checkpoint_file.write_text(
            json.dumps(checkpoint, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return checkpoint_file

    def load(self, step_name: str) -> dict[str, Any] | None:
        """Load checkpoint data for a specific step."""
        checkpoint_file = self.checkpoint_dir / f"{step_name}.json"
        if not checkpoint_file.exists():
            return None
        try:
            checkpoint = json.loads(checkpoint_file.read_text(encoding="utf-8"))
            return checkpoint.get("data")
        except (json.JSONDecodeError, KeyError):
            return None

    def list_checkpoints(self) -> list[str]:
        """List all saved checkpoint step names."""
        return [
            checkpoint_file.stem
            for checkpoint_file in self.checkpoint_dir.glob("*.json")
        ]

    def clear(self) -> None:
        """Clear all checkpoints for this project."""
        for checkpoint_file in self.checkpoint_dir.glob("*.json"):
            checkpoint_file.unlink()

    @staticmethod
    def _safe_path_part(value: str) -> str:
        safe = "".join(char if char.isalnum() or char in "._-" else "_" for char in value)
        return safe.strip("._") or "project"


class PipelineRecovery:
    """Handles pipeline recovery from failures."""

    def __init__(self, db: Session, project: Project):
        self.db = db
        self.project = project
        self.checkpoint = PipelineCheckpoint(project.project_id)

    def find_last_successful_step(self) -> str | None:
        """Find the last successfully completed step in the pipeline."""
        completed_runs = (
            self.db.query(AgentRun)
            .filter_by(project_id=self.project.project_id, status="completed")
            .order_by(AgentRun.updated_at.desc())
            .all()
        )

        if not completed_runs:
            return None

        return completed_runs[0].agent_name

    def find_failed_step(self) -> tuple[str, str] | None:
        """Find the first failed step and its error message."""
        failed_run = (
            self.db.query(AgentRun)
            .filter_by(project_id=self.project.project_id, status="failed")
            .order_by(AgentRun.updated_at.asc())
            .first()
        )

        if failed_run is None:
            return None

        return (failed_run.agent_name, failed_run.error_message or "Unknown error")

    def can_resume(self) -> bool:
        """Check if pipeline can be resumed from the last checkpoint."""
        if self.project.status != PIPELINE_FAILED:
            return False

        last_step = self.find_last_successful_step()
        return last_step is not None

    def resume_from_checkpoint(self, pipeline_steps: list[str]) -> list[str]:
        """
        Get the list of steps to execute when resuming from checkpoint.

        Args:
            pipeline_steps: Full ordered list of pipeline step names

        Returns:
            List of step names to execute (starting from failed step)
        """
        last_successful = self.find_last_successful_step()

        if last_successful is None:
            return pipeline_steps

        try:
            last_index = pipeline_steps.index(last_successful)
            # Resume from the next step after the last successful one
            return pipeline_steps[last_index + 1:]
        except ValueError:
            # Step name not found, restart from beginning
            return pipeline_steps

    def rollback_failed_step(self, step_name: str) -> None:
        """
        Rollback a failed step by marking its AgentRun as retrying.

        This allows the step to be re-executed without creating a duplicate run.
        """
        failed_runs = (
            self.db.query(AgentRun)
            .filter_by(
                project_id=self.project.project_id,
                agent_name=step_name,
                status="failed",
            )
            .all()
        )

        for run in failed_runs:
            run.status = "retrying"
            run.error_message = None

        self.db.commit()

    def reset_pipeline(self) -> None:
        """
        Reset pipeline to initial state.

        WARNING: This deletes all AgentRun records and checkpoints.
        Use only when a complete restart is needed.
        """
        # Delete all agent runs for this project
        self.db.query(AgentRun).filter_by(project_id=self.project.project_id).delete()

        # Clear checkpoints
        self.checkpoint.clear()

        # Reset project status
        self.project.status = PIPELINE_RUNNING
        self.db.commit()

    def get_recovery_summary(self) -> dict[str, Any]:
        """Get a summary of the current recovery state."""
        last_successful = self.find_last_successful_step()
        failed_info = self.find_failed_step()
        checkpoints = self.checkpoint.list_checkpoints()

        return {
            "project_id": self.project.project_id,
            "project_status": self.project.status,
            "can_resume": self.can_resume(),
            "last_successful_step": last_successful,
            "failed_step": failed_info[0] if failed_info else None,
            "failure_reason": failed_info[1] if failed_info else None,
            "available_checkpoints": checkpoints,
            "checkpoint_count": len(checkpoints),
        }


def is_step_idempotent(step_name: str) -> bool:
    """
    Check if a step can be safely re-executed without side effects.

    Idempotent steps can be retried without data corruption.
    Non-idempotent steps may need special handling.
    """
    # Most computational steps are idempotent
    idempotent_steps = {
        "knowledge_ingestion_agent",
        "molecule_import_agent",
        "validation_agent",
        "filter_agent",
        "candidate_assessment_agent",
        "self_refutation_agent",
        "ranker_agent",
        "advisor_agent",
        "decision_card_agent",
        "report_agent",
    }

    return step_name in idempotent_steps


def should_retry_step(step_name: str, attempt_count: int, max_retries: int = 3) -> bool:
    """
    Determine if a failed step should be retried.

    Args:
        step_name: Name of the failed step
        attempt_count: Current number of attempts
        max_retries: Maximum number of retries allowed

    Returns:
        True if step should be retried
    """
    if attempt_count >= max_retries:
        return False

    # Always retry idempotent steps
    if is_step_idempotent(step_name):
        return True

    # Non-idempotent steps: retry only on first failure
    return attempt_count < 2


def get_recovery_strategy(failure_type: str) -> str:
    """
    Get recommended recovery strategy based on failure type.

    Args:
        failure_type: Type of failure (e.g., 'timeout', 'validation_error', 'tool_error')

    Returns:
        Recovery strategy name
    """
    strategies = {
        "timeout": "retry_with_increased_timeout",
        "validation_error": "skip_invalid_molecules_and_continue",
        "tool_error": "retry_with_fallback_tool",
        "llm_error": "retry_with_different_model",
        "database_error": "rollback_and_retry",
        "file_not_found": "check_dependencies_and_retry",
    }

    return strategies.get(failure_type, "retry_from_checkpoint")
