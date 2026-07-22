"""Pocket-conditioned TargetDiff generation agent."""

from __future__ import annotations

import tempfile
from pathlib import Path

from medagent.agents.generation_base import GenerationAgent, _agent_molecules, _failed_result, _skipped_result, _requested_count
from medagent.domain.schemas import AgentName, AgentResult, AgentTask
from medagent.services.molecule_generation import GenerationBatch, GenerationCandidate, generation_tool_status
from medagent.services.targetdiff_adapter import TargetDiffRequest, run_targetdiff_generation


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
        with tempfile.TemporaryDirectory(prefix="targetdiff_agent_") as root:
            result = run_targetdiff_generation(TargetDiffRequest(_pocket_path(task) or "", root, requested_count, int(status.get("configured_timeout_seconds") or 1800)), status)
        candidates = [GenerationCandidate(smiles=value, strategy="targetdiff", seed_smiles="", rationale="TargetDiff pocket-conditioned generation; requires independent docking.", labels=tuple(result.labels), metadata={"adapter_mode": result.adapter_mode, "generation_pose_is_docking_evidence": False}) for value in result.generated_smiles[:requested_count]]
        batch = GenerationBatch(candidates=candidates, adapter_mode=result.adapter_mode, tool_status={"targetdiff": status}, warnings=result.warnings, candidate_source_counts={"targetdiff": len(candidates)}, provenance=result.provenance, execution_mode="external_tool" if result.success else "not_run", external_tools_requested=True, external_tool_used=result.success)
        molecules = _agent_molecules(task, batch)
        if not molecules:
            return _failed_result(task, self.agent_name, result.adapter_mode, result.warnings)
        return AgentResult(agent=self.agent_name, round=task.round, success=True, status="completed", molecules=molecules, warnings=result.warnings)


def _pocket_path(task: AgentTask) -> str | None:
    value = (task.resource_bundle or {}).get("pocket_file") or task.constraints.get("pocket_file")
    return str(value).removeprefix("local://") if value else None
