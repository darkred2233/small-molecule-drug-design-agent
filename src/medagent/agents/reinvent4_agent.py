"""REINVENT4 generation agent.

Uses reward-guided de novo generation:
- Prior model → soft constraint (seed similarity + property reward) → lightweight RL → sample
- Transfer Learning is conditional on ligand count (not default for < 20 ligands)
- Docking-informed rerank is post-generation (not in RL loop)
"""

from __future__ import annotations

import tempfile
from typing import Any

from medagent.agents.generation_base import (
    BUDGET_REQUESTED_COUNTS,
    GenerationAgent,
    _bounded_int,
    _failed_result,
    _skipped_result,
)
from medagent.domain.schemas import (
    AgentMoleculeCandidate,
    AgentName,
    AgentResult,
    AgentTask,
)


def _select_reinvent4_mode(
    reference_ligand_count: int,
    user_mode: str | None = None,
) -> str:
    """根据有效 ligand 数量决定 REINVENT4 运行模式。

    规则（基于标准化、去重、通过质量过滤后的有效 ligand 数量）：
    - < 20：rl_only（不做 TL）
    - 20-49：默认 rl_only，用户可选 light_tl_then_rl
    - 50-99：可选 light_tl_then_rl 或 tl_then_rl
    - >= 100：默认 tl_then_rl
    """
    if user_mode:
        return user_mode

    if reference_ligand_count < 20:
        return "rl_only"
    elif reference_ligand_count < 50:
        return "rl_only"  # 默认不做 TL，用户可选 light_tl_then_rl
    elif reference_ligand_count < 100:
        return "light_tl_then_rl"
    else:
        return "tl_then_rl"


def _build_scoring_components_from_config(
    campaign_config: dict[str, Any],
) -> list[dict[str, Any]] | None:
    """从 campaign_config 构建 REINVENT4 scoring components。"""
    from medagent.services.reinvent4_adapter import default_scoring_components

    base_components = default_scoring_components()

    # seed similarity soft constraint
    seed_sim_min = campaign_config.get("seed_similarity_min", 0.35)
    seed_sim_max = campaign_config.get("seed_similarity_max", 0.75)
    penalty_low = campaign_config.get("seed_similarity_penalty_low", 0.25)
    penalty_high = campaign_config.get("seed_similarity_penalty_high", 0.85)

    base_components.append({
        "type": "CustomAlerts",
        "name": "seed_similarity_range",
        "weight": 0.20,
        "params": {
            "similarity_min": seed_sim_min,
            "similarity_max": seed_sim_max,
            "penalty_below": penalty_low,
            "penalty_above": penalty_high,
        },
    })

    # property range reward
    property_targets = campaign_config.get("property_targets", {})
    if property_targets:
        base_components.append({
            "type": "CustomAlerts",
            "name": "property_range_reward",
            "weight": 0.15,
            "params": property_targets,
        })

    return base_components


class Reinvent4Agent(GenerationAgent):
    agent_name: AgentName = "reinvent4"
    requires_task_seeds: bool = False

    def run(self, task: AgentTask) -> AgentResult:
        if task.agent != self.agent_name:
            return _failed_result(
                task, self.agent_name, "agent_task_mismatch",
                [f"expected_agent:{self.agent_name}", f"actual_agent:{task.agent}"],
            )

        requested_count = _requested_count(task)
        if requested_count <= 0:
            return _skipped_result(task, "generation_budget_is_zero")

        skipped_reason = self._skip_reason(task)
        if skipped_reason is not None:
            return _skipped_result(task, skipped_reason)

        # 决定运行模式
        campaign_config = task.campaign_config or {}
        reference_count = campaign_config.get("reference_ligand_count", len(task.seed_molecules))
        user_mode = campaign_config.get("mode")
        reinvent4_mode = _select_reinvent4_mode(reference_count, user_mode)

        # 构建 scoring components
        scoring_components = _build_scoring_components_from_config(campaign_config)

        # 从 campaign_config 读取参数
        rl_steps = campaign_config.get("rl_steps", 30)
        batch_size = campaign_config.get("batch_size", 128)
        sample_count = campaign_config.get("sample_count", requested_count)
        tl_epochs = campaign_config.get("tl_epochs", 5)

        from medagent.services.reinvent4_adapter import (
            Reinvent4Request,
            check_reinvent4_available,
            run_reinvent4_generation,
        )

        status = check_reinvent4_available()
        if not status.get("available"):
            return _failed_result(
                task, self.agent_name, "reinvent4_unavailable",
                warnings=[status.get("warning") or "reinvent4_not_installed"],
            )

        # 映射 mode 到 adapter run_type
        run_type_map = {
            "rl_only": "staged_learning",
            "light_tl_then_rl": "staged_learning",
            "tl_then_rl": "staged_learning",
        }
        run_type = run_type_map.get(reinvent4_mode, "staged_learning")

        with tempfile.TemporaryDirectory(prefix="reinvent4_agent_") as tmp_dir:
            request = Reinvent4Request(
                seed_smiles=task.seed_molecules,
                output_dir=tmp_dir,
                num_molecules=sample_count,
                constraints=dict(task.constraints),
                run_type=run_type,
                tl_epochs=tl_epochs if reinvent4_mode != "rl_only" else 0,
                rl_epochs=rl_steps,
                rl_batch_size=batch_size,
                scoring_components=scoring_components,
                reference_ligands=task.seed_molecules if task.seed_molecules else None,
                timeout_seconds=task.constraints.get("timeout_seconds", 1200),
            )

            result = run_reinvent4_generation(request, reinvent4_status=status)

        if not result.success:
            return AgentResult(
                agent=self.agent_name,
                round=task.round,
                success=False,
                status="failed",
                molecules=[],
                warnings=result.warnings,
                failure_reason=result.adapter_mode,
            )

        # Convert to AgentResult
        molecules = _reinvent4_to_agent_molecules(task, result)
        if not molecules:
            return AgentResult(
                agent=self.agent_name,
                round=task.round,
                success=False,
                status="failed",
                molecules=[],
                warnings=result.warnings,
                failure_reason="reinvent4_no_valid_molecules",
            )

        return AgentResult(
            agent=self.agent_name,
            round=task.round,
            success=True,
            status="completed",
            molecules=molecules,
            warnings=result.warnings,
            failure_reason=None,
        )


def _reinvent4_to_agent_molecules(
    task: AgentTask,
    result: Any,
) -> list[AgentMoleculeCandidate]:
    """Convert Reinvent4Result molecules to AgentMoleculeCandidate."""
    molecules: list[AgentMoleculeCandidate] = []
    for smiles, score in zip(result.generated_smiles, result.scores):
        metadata: dict[str, Any] = {
            "adapter_mode": result.adapter_mode,
            "labels": list(result.labels),
            "execution_mode": "external_tool",
            "external_tool_used": True,
            "surrogate_used": False,
            "fallback_used": False,
        }
        if score is not None:
            metadata["score"] = score

        molecules.append(
            AgentMoleculeCandidate(
                smiles=smiles,
                rationale=f"REINVENT4 {result.adapter_mode}",
                provenance={
                    "agent": task.agent,
                    "round": task.round,
                    "method": result.adapter_mode,
                    "adapter_mode": result.adapter_mode,
                    "execution_mode": "external_tool",
                    "external_tool_used": True,
                    "surrogate_used": False,
                    "fallback_used": False,
                    "tool_provenance": result.provenance,
                },
                metadata=metadata,
            )
        )
    return molecules


def _requested_count(task: AgentTask) -> int:
    explicit = task.constraints.get("requested_count", task.constraints.get("generation_size"))
    if explicit is not None:
        return _bounded_int(explicit, default=0, minimum=0, maximum=500)
    return BUDGET_REQUESTED_COUNTS[task.budget]
