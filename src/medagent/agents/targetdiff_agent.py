"""Pocket-conditioned TargetDiff generation agent."""

from __future__ import annotations

from pathlib import Path

from medagent.agents.generation_base import GenerationAgent, _agent_molecules, _failed_result, _skipped_result, _requested_count
from medagent.core.config import get_settings
from medagent.domain.schemas import AgentName, AgentResult, AgentTask
from medagent.services.molecule_generation import GenerationBatch, GenerationCandidate, generation_tool_status
from medagent.services.targetdiff_adapter import (
    TargetDiffRequest,
    TargetDiffResult,
    run_targetdiff_generation,
)


class TargetDiffAgent(GenerationAgent):
    agent_name: AgentName = "targetdiff"
    requires_task_seeds = False

    def _skip_reason(self, task: AgentTask) -> str | None:
        pocket = _pocket_path(task)
        if not pocket:
            return "targetdiff_requires_pocket_file"
        path = Path(pocket)
        if not path.is_file() or path.suffix.lower() != ".pdb":
            return "targetdiff_pocket_pdb_not_found"
        return None

    def run(self, task: AgentTask) -> AgentResult:
        if task.agent != self.agent_name:
            return _failed_result(task, self.agent_name, "agent_task_mismatch")
        requested_count = _requested_count(task)
        if requested_count <= 0:
            return _skipped_result(task, "generation_budget_is_zero")
        skip = self._skip_reason(task)
        if skip:
            return _skipped_result(task, skip)
        status = generation_tool_status()["targetdiff"]
        if not status.get("available"):
            return _skipped_result(task, str(status.get("warning") or "targetdiff_not_installed"))
        root = _campaign_output_dir(task)
        result = run_targetdiff_generation(
            TargetDiffRequest(
                _pocket_path(task) or "",
                str(root),
                requested_count,
                int(status.get("configured_timeout_seconds") or 2700),
            ),
            status,
        )
        execution_details = _execution_details(result)
        candidates = [GenerationCandidate(smiles=value, strategy="targetdiff", seed_smiles="", rationale="TargetDiff pocket-conditioned generation; requires independent docking.", labels=tuple(result.labels), metadata={"adapter_mode": result.adapter_mode, "generation_pose_is_docking_evidence": False}) for value in result.generated_smiles[:requested_count]]
        batch = GenerationBatch(candidates=candidates, adapter_mode=result.adapter_mode, tool_status={"targetdiff": status}, warnings=result.warnings, candidate_source_counts={"targetdiff": len(candidates)}, provenance=result.provenance, execution_mode="external_tool" if result.success else "not_run", external_tools_requested=True, external_tool_used=result.success)
        molecules = _agent_molecules(task, batch)
        if not molecules:
            return _failed_result(
                task,
                self.agent_name,
                result.adapter_mode,
                result.warnings,
                execution_details,
            )
        return AgentResult(
            agent=self.agent_name,
            round=task.round,
            success=True,
            status="completed",
            molecules=molecules,
            warnings=result.warnings,
            execution_details=execution_details,
        )


def _pocket_path(task: AgentTask) -> str | None:
    value = (task.resource_bundle or {}).get("pocket_file") or task.constraints.get("pocket_file")
    return str(value).removeprefix("local://") if value else None


def _campaign_output_dir(task: AgentTask) -> Path:
    configured = task.constraints.get("output_dir")
    if configured:
        output_dir = Path(str(configured))
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir
    settings = get_settings()
    project_id = task.project_id or "unscoped"
    campaign_id = task.campaign_run_id or f"round-{task.round}"
    output_dir = (
        Path(settings.storage_local_root)
        / project_id
        / "campaigns"
        / campaign_id
        / "targetdiff"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def _execution_details(result: TargetDiffResult) -> dict[str, object]:
    return {
        "tool_name": result.tool_name,
        "adapter_mode": result.adapter_mode,
        "exit_code": result.exit_code,
        "runtime_seconds": result.runtime_seconds,
        "command": result.provenance.get("command", []),
        "stdout": result.stdout,
        "stderr": result.stderr,
        "provenance": result.provenance,
    }
