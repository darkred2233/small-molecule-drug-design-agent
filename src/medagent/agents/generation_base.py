"""Shared AgentTask -> AgentResult contract for generation agents."""

from __future__ import annotations

import math
from typing import Any

from medagent.domain.schemas import AgentMoleculeCandidate, AgentName, AgentResult, AgentTask
from medagent.services.molecule_generation import GenerationBatch, STRATEGY_ADAPTERS


BUDGET_REQUESTED_COUNTS = {
    "low": 10,
    "medium": 25,
    "high": 50,
}


class GenerationAgent:
    """Base wrapper for a molecule generation strategy."""

    agent_name: AgentName
    requires_task_seeds: bool = False  # 各 agent 自行声明是否需要 seed_molecules

    def run(self, task: AgentTask) -> AgentResult:
        if task.agent != self.agent_name:
            return _failed_result(
                task,
                self.agent_name,
                "agent_task_mismatch",
                [f"expected_agent:{self.agent_name}", f"actual_agent:{task.agent}"],
            )

        requested_count = _requested_count(task)
        if requested_count <= 0:
            return _skipped_result(task, "generation_budget_is_zero")

        if self.requires_task_seeds and not task.seed_molecules:
            return _failed_result(
                task,
                self.agent_name,
                "generation_requires_at_least_one_seed_ligand",
            )

        skipped_reason = self._skip_reason(task)
        if skipped_reason is not None:
            return _skipped_result(task, skipped_reason)

        try:
            batch = STRATEGY_ADAPTERS[self.agent_name].generate(
                seeds=task.seed_molecules,
                requested_count=requested_count,
                constraints=task.constraints,
            )
        except Exception as exc:  # pragma: no cover - external adapters are environment-dependent.
            return _failed_result(
                task,
                self.agent_name,
                f"generation_adapter_exception:{type(exc).__name__}",
            )

        molecules = _agent_molecules(task, batch)
        if not molecules:
            return AgentResult(
                agent=self.agent_name,
                round=task.round,
                success=False,
                status="failed",
                molecules=[],
                warnings=batch.warnings,
                failure_reason="generation_returned_no_candidates",
            )

        return AgentResult(
            agent=self.agent_name,
            round=task.round,
            success=True,
            status="completed",
            molecules=molecules,
            warnings=batch.warnings,
            failure_reason=None,
        )

    def _skip_reason(self, task: AgentTask) -> str | None:
        return None


def _requested_count(task: AgentTask) -> int:
    explicit = task.constraints.get("requested_count", task.constraints.get("generation_size"))
    if explicit is not None:
        return _bounded_int(explicit, default=0, minimum=0, maximum=500)
    return BUDGET_REQUESTED_COUNTS[task.budget]


def _agent_molecules(task: AgentTask, batch: GenerationBatch) -> list[AgentMoleculeCandidate]:
    molecules: list[AgentMoleculeCandidate] = []
    for candidate in batch.candidates:
        metadata = dict(candidate.metadata)
        if candidate.score is not None:
            metadata["score"] = candidate.score
        metadata["labels"] = list(candidate.labels)
        metadata.setdefault("execution_mode", batch.execution_mode)
        metadata.setdefault("external_tool_used", batch.external_tool_used)
        metadata.setdefault("surrogate_used", batch.surrogate_used)
        metadata.setdefault("fallback_used", batch.fallback_used)
        provenance: dict[str, Any] = {
            "agent": task.agent,
            "round": task.round,
            "method": metadata.get("candidate_source") or batch.adapter_mode,
            "seed": candidate.seed_smiles,
            "adapter_mode": batch.adapter_mode,
            "execution_mode": batch.execution_mode,
            "external_tool_used": batch.external_tool_used,
            "surrogate_used": batch.surrogate_used,
            "fallback_used": batch.fallback_used,
            "tool_status": batch.tool_status,
            "tool_provenance": metadata.get("tool_provenance") or batch.provenance,
            "source_strategy": candidate.strategy,
        }
        if task.round_id:
            provenance["round_id"] = task.round_id
        if task.campaign_run_id:
            provenance["campaign_run_id"] = task.campaign_run_id
        molecules.append(
            AgentMoleculeCandidate(
                smiles=candidate.smiles,
                rationale=candidate.rationale,
                provenance=provenance,
                metadata=metadata,
            )
        )
    return molecules


def _skipped_result(task: AgentTask, reason: str) -> AgentResult:
    return AgentResult(
        agent=task.agent,
        round=task.round,
        success=False,
        status="skipped",
        molecules=[],
        warnings=[],
        failure_reason=reason,
    )


def _failed_result(
    task: AgentTask,
    agent_name: AgentName,
    reason: str,
    warnings: list[str] | None = None,
) -> AgentResult:
    return AgentResult(
        agent=agent_name,
        round=task.round,
        success=False,
        status="failed",
        molecules=[],
        warnings=warnings or [],
        failure_reason=reason,
    )


def grid_values(constraints: dict[str, Any]) -> tuple[list[float], list[float]] | None:
    center = constraints.get("grid_center") or constraints.get("center")
    size = constraints.get("grid_size") or constraints.get("size")
    if not isinstance(center, list) or not isinstance(size, list):
        return None
    if len(center) != 3 or len(size) != 3:
        return None
    try:
        center_values = [float(value) for value in center]
        size_values = [float(value) for value in size]
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(value) for value in [*center_values, *size_values]):
        return None
    if not all(value > 0 for value in size_values):
        return None
    return center_values, size_values


def _bounded_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))
