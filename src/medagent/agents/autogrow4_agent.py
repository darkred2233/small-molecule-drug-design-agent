"""AutoGrow4 generation agent.

Receptor-guided genetic search. 不强制 task.seed_molecules，
但必须有 resource_bundle（receptor + source_compounds_file）。
"""

from pathlib import Path

from medagent.agents.generation_base import (
    GenerationAgent,
    _agent_molecules,
    _failed_result,
    _skipped_result,
    grid_values,
)
from medagent.core.config import get_settings
from medagent.domain.schemas import AgentName, AgentResult, AgentTask
from medagent.services.autogrow4_adapter import autogrow_profile
from medagent.services.molecule_generation import STRATEGY_ADAPTERS


class AutoGrow4Agent(GenerationAgent):
    agent_name: AgentName = "autogrow4"
    requires_task_seeds: bool = False

    def _skip_reason(self, task: AgentTask) -> str | None:
        # 优先从 resource_bundle 读取
        bundle = task.resource_bundle
        if bundle:
            receptor_file = _local_file_path(bundle.get("receptor_file"))
            source_file = bundle.get("source_compounds_file")
            if not receptor_file:
                return "autogrow4_resource_bundle_missing_receptor_file"
            if not source_file:
                return "autogrow4_resource_bundle_missing_source_compounds_file"
            try:
                receptor_path = Path(str(receptor_file)).expanduser()
            except OSError:
                return "autogrow4_receptor_file_invalid"
            if not receptor_path.is_file():
                return "autogrow4_receptor_file_not_found"
            source_path = Path(str(source_file)).expanduser()
            if not source_path.is_file():
                return "autogrow4_source_compounds_file_not_found"
            center = bundle.get("grid_center")
            size = bundle.get("grid_size")
            if not center or not size:
                return "autogrow4_requires_grid_center_and_size"
            return None

        # 兼容旧模式：从 constraints 读取
        receptor_file = _local_file_path(task.constraints.get("receptor_file"))
        if not receptor_file:
            return "autogrow4_requires_receptor_file_or_resource_bundle"
        try:
            receptor_path = Path(str(receptor_file)).expanduser()
        except OSError:
            return "autogrow4_receptor_file_invalid"
        if not receptor_path.is_file():
            return "autogrow4_receptor_file_not_found"
        if grid_values(task.constraints) is None:
            return "autogrow4_requires_grid_center_and_size"
        return None

    def run(self, task: AgentTask) -> AgentResult:
        """重写 run 以支持 resource_bundle 和 search_intensity 映射。"""
        if task.agent != self.agent_name:
            return _failed_result(
                task, self.agent_name, "agent_task_mismatch",
                [f"expected_agent:{self.agent_name}", f"actual_agent:{task.agent}"],
            )

        from medagent.agents.generation_base import _requested_count
        requested_count = _requested_count(task)
        if requested_count <= 0:
            return _skipped_result(task, "generation_budget_is_zero")

        skipped_reason = self._skip_reason(task)
        if skipped_reason is not None:
            return _skipped_result(task, skipped_reason)

        # 从 resource_bundle 或 campaign_config 构建增强 constraints
        enhanced_constraints = dict(task.constraints)
        bundle = task.resource_bundle
        campaign_config = task.campaign_config or {}

        if bundle:
            enhanced_constraints["receptor_file"] = _local_file_path(bundle["receptor_file"])
            enhanced_constraints["grid_center"] = bundle["grid_center"]
            enhanced_constraints["grid_size"] = bundle["grid_size"]

        # This agent has a single supported docking contract. Persist it in the
        # task constraints as well as enforcing it in the adapter so that a
        # future default change cannot silently re-enable CPU docking.
        enhanced_constraints.update(
            {
                "docking_backend": "vina_gpu_2_1_batch",
                "gpu_required": True,
                "gpu_id": 0,
                "cpu_fallback": False,
            }
        )

        configured_output = enhanced_constraints.get("output_dir")
        if configured_output:
            output_dir = Path(str(configured_output))
            output_dir.mkdir(parents=True, exist_ok=True)
            enhanced_constraints["output_dir"] = str(output_dir)
        elif task.project_id and task.campaign_run_id:
            output_dir = (
                Path(get_settings().storage_local_root)
                / task.project_id
                / "campaigns"
                / task.campaign_run_id
                / "autogrow4"
            )
            output_dir.mkdir(parents=True, exist_ok=True)
            enhanced_constraints["output_dir"] = str(output_dir)

        # search_intensity 映射到 generations / population_size
        intensity = campaign_config.get("search_intensity", "normal")
        profile = autogrow_profile(intensity)
        generations = campaign_config.get("generations")
        if not generations:
            generations = profile["generations"]
        population_size = min(
            profile["population_size"], max(requested_count, 1)
        )

        enhanced_constraints["search_intensity"] = intensity
        enhanced_constraints["num_generations"] = generations
        enhanced_constraints["population_size"] = population_size
        enhanced_constraints["crossover_fraction"] = campaign_config.get(
            "crossover_fraction", 0.5
        )

        # The resource bundle is the execution-time source pool. Newer strategy
        # snapshots write the confirmed method seeds to this same artifact;
        # older callers also rely on it to apply source_pool_policy correctly.
        seeds = list(task.seed_molecules)
        if bundle and bundle.get("source_compounds_file"):
            source_path = Path(bundle["source_compounds_file"])
            if source_path.is_file():
                resource_seeds = _read_source_compounds(source_path)
                if resource_seeds:
                    seeds = resource_seeds

        if not seeds:
            return _failed_result(
                task, self.agent_name, "autogrow4_no_source_compounds",
            )

        try:
            batch = STRATEGY_ADAPTERS[self.agent_name].generate(
                seeds=seeds,
                requested_count=requested_count,
                constraints=enhanced_constraints,
            )
        except Exception as exc:
            return _failed_result(
                task, self.agent_name,
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
                execution_details=batch.provenance,
            )

        return AgentResult(
            agent=self.agent_name,
            round=task.round,
            success=True,
            status="completed",
            molecules=molecules,
            warnings=batch.warnings,
            failure_reason=None,
            execution_details=batch.provenance,
        )


def _read_source_compounds(path: Path) -> list[str]:
    """读取 source_compounds.smi 文件。"""
    smiles_list: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            smiles = line.split("\t")[0].strip()
            if smiles:
                smiles_list.append(smiles)
    return smiles_list


def _local_file_path(value: object) -> str | None:
    if value is None:
        return None
    return str(value).removeprefix("local://")
