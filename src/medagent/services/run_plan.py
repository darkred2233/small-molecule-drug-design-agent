from copy import deepcopy
from typing import Any

from medagent.db.models import Project
from medagent.domain.schemas import RunPlan, RunPlanAgentConfig, RunPlanEvaluation, RunPlanStopping


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
AGENT_ROLES = {
    "reinvent4": "全局探索，扩大候选分子化学空间",
    "crem": "围绕 top seed 做局部 SAR 修改",
    "autogrow4": "在 receptor/grid 可靠时做 docking 引导优化",
}
AUTOGROW4_CONDITION = "有可靠 receptor/grid/pose 条件时才运行；否则标记 skipped"
VALID_EXPLORATION_LEVELS = {"low", "medium", "high"}
VALID_RUN_PLAN_STATUSES = {"draft", "approved", "running", "completed", "failed"}
VALID_SYNTHESIS_ROUTE_SCOPES = {"disabled", "every_round_top_n", "final_round_top_n"}
BUDGET_REQUESTED_COUNTS = {
    "low": 10,
    "medium": 25,
    "high": 50,
}


def build_default_run_plan(
    project: Project,
    pipeline_config: dict[str, Any] | None = None,
) -> RunPlan:
    """Build a draft RunPlan from today's project JSON config without changing execution."""
    normalized = _normalize_pipeline_config(project, pipeline_config)
    raw_config = _raw_pipeline_config(project, pipeline_config)
    explicit_level = raw_config.get("exploration_level")
    exploration_level = (
        explicit_level
        if isinstance(explicit_level, str) and explicit_level in VALID_EXPLORATION_LEVELS
        else _exploration_level_from_generation_size(normalized["generation_size"])
    )
    strategy_counts = normalized["strategy_counts"]

    agents: dict[str, RunPlanAgentConfig] = {}
    for agent_name in ("reinvent4", "crem", "autogrow4"):
        requested_count = strategy_counts.get(agent_name, 0)
        enabled = _agent_enabled(agent_name, requested_count)
        budget = exploration_level if isinstance(explicit_level, str) else _budget_from_count(requested_count)
        agents[agent_name] = RunPlanAgentConfig(
            enabled=enabled,
            role=AGENT_ROLES[agent_name],
            budget=budget,
            requested_count=requested_count,
            condition=AUTOGROW4_CONDITION if agent_name == "autogrow4" and enabled else None,
        )

    assessment_mode = normalized["assessment_mode"]
    evaluation_mode = "external_top_n" if assessment_mode == "external" else assessment_mode
    evaluation_top_n = (
        normalized["external_top_n"] if evaluation_mode == "external_top_n" else normalized["top_n"]
    )
    objective = project.objective or "围绕当前项目 seed 生成、评估并排序候选分子。"
    status = raw_config.get("run_plan_status", "draft")
    if status not in VALID_RUN_PLAN_STATUSES:
        status = "draft"

    warnings: list[str] = []
    if agents["autogrow4"].enabled == "conditional":
        warnings.append("AutoGrow4 已设为条件启用；缺少可靠 receptor/grid 时应显示为 skipped。")
    if not any(bool(config.enabled) for config in agents.values()):
        warnings.append("当前计划没有启用任何生成 Agent。")

    return RunPlan(
        status=status,
        objective=objective,
        auto_run=bool(raw_config.get("auto_run", False)),
        max_rounds=_bounded_int(raw_config.get("max_rounds"), 3, 1, 20),
        next_round_seed_count=_bounded_int(raw_config.get("next_round_seed_count"), 10, 1, 100),
        seed_smiles=_string_list(raw_config.get("seed_smiles")),
        exploration_level=exploration_level,
        agents=agents,
        constraints=dict(normalized.get("generation_constraints") or {}),
        evaluation=RunPlanEvaluation(
            mode=evaluation_mode,
            top_n=evaluation_top_n,
            use_docking=bool(raw_config.get("use_docking", evaluation_mode != "fast")),
            use_admet=bool(raw_config.get("use_admet", True)),
            use_synthesis=bool(raw_config.get("use_synthesis", True)),
            synthesis_route_scope=_synthesis_route_scope(raw_config),
            use_filters=bool(raw_config.get("use_filters", True)),
        ),
        stopping=RunPlanStopping(
            min_score_improvement=_bounded_float(
                raw_config.get("min_score_improvement"),
                default=0.0,
                minimum=0.0,
                maximum=100.0,
            ),
            max_total_molecules=_bounded_int(
                raw_config.get("max_total_molecules"),
                300,
                1,
                5000,
            ),
            max_tool_failures=_bounded_int(raw_config.get("max_tool_failures"), 3, 1, 20),
        ),
        decision_trace=[
            {
                "step": "default_run_plan_from_project_config",
                "reason": "根据项目目标和现有 pipeline_config 生成初始 RunPlan，后续由 iterative agent 流程执行。",
                "evidence_refs": [],
            },
            {
                "step": "map_strategy_counts_to_agent_counts",
                "reason": "把 per-strategy counts 写入各生成 Agent 的每轮请求数量。",
                "input": strategy_counts,
            },
        ],
        warnings=warnings,
    )


def ensure_project_run_plan(
    project: Project,
    pipeline_config: dict[str, Any] | None = None,
    *,
    overwrite: bool = False,
) -> RunPlan:
    constraints_json = dict(project.constraints_json or {})
    existing = constraints_json.get("run_plan")
    if isinstance(existing, dict) and not overwrite:
        try:
            return _validate_run_plan(existing)
        except ValueError:
            pass

    run_plan = build_default_run_plan(project, pipeline_config)
    if isinstance(existing, dict) and not overwrite:
        run_plan.warnings.append("已有 run_plan 无法通过契约校验，已从项目配置重新生成。")
    save_project_run_plan(project, run_plan)
    return run_plan


def save_project_run_plan(project: Project, run_plan: RunPlan) -> None:
    constraints_json = dict(project.constraints_json or {})
    constraints_json["run_plan"] = _dump_run_plan(run_plan)
    project.constraints_json = constraints_json


def _raw_pipeline_config(
    project: Project,
    pipeline_config: dict[str, Any] | None,
) -> dict[str, Any]:
    constraints_json = project.constraints_json or {}
    stored = constraints_json.get("pipeline_config")
    raw: dict[str, Any] = {}
    if isinstance(stored, dict):
        raw.update(stored)
    if isinstance(pipeline_config, dict):
        raw.update(pipeline_config)
    return raw


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


def _agent_enabled(agent_name: str, requested_count: int) -> bool | str:
    if requested_count <= 0:
        return False
    if agent_name == "autogrow4":
        return "conditional"
    return True


def _budget_from_count(requested_count: int) -> str:
    if requested_count <= 10:
        return "low"
    if requested_count <= 25:
        return "medium"
    return "high"


def _exploration_level_from_generation_size(generation_size: int) -> str:
    if generation_size <= 30:
        return "low"
    if generation_size <= 75:
        return "medium"
    return "high"


def _synthesis_route_scope(raw_config: dict[str, Any]) -> str:
    scope = raw_config.get("synthesis_route_scope")
    if isinstance(scope, str) and scope in VALID_SYNTHESIS_ROUTE_SCOPES:
        return scope
    return "final_round_top_n"


def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))


def _bounded_float(value: Any, *, default: float, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))


def _validate_run_plan(payload: dict[str, Any]) -> RunPlan:
    payload = _migrated_run_plan_payload(payload)
    if hasattr(RunPlan, "model_validate"):
        return RunPlan.model_validate(payload)
    return RunPlan.parse_obj(payload)


def _dump_run_plan(run_plan: RunPlan) -> dict[str, Any]:
    if hasattr(run_plan, "model_dump"):
        return run_plan.model_dump(mode="json")
    return run_plan.dict()


def _migrated_run_plan_payload(payload: dict[str, Any]) -> dict[str, Any]:
    migrated = deepcopy(payload)
    migrated.setdefault("next_round_seed_count", 10)
    migrated.setdefault("seed_smiles", [])
    _migrate_legacy_score_improvement_stop(migrated)
    agents = migrated.get("agents")
    if not isinstance(agents, dict):
        return migrated
    for config in agents.values():
        if not isinstance(config, dict) or "requested_count" in config:
            continue
        if config.get("enabled") is False:
            config["requested_count"] = 0
            continue
        budget = config.get("budget")
        if isinstance(budget, str) and budget in BUDGET_REQUESTED_COUNTS:
            config["requested_count"] = BUDGET_REQUESTED_COUNTS[budget]
        else:
            config["requested_count"] = 0
    return migrated


def _migrate_legacy_score_improvement_stop(payload: dict[str, Any]) -> None:
    stopping = payload.get("stopping")
    if not isinstance(stopping, dict):
        return
    if stopping.get("min_score_improvement") != 5.0:
        return
    for trace in payload.get("decision_trace") or []:
        if not isinstance(trace, dict):
            continue
        changed_paths = trace.get("changed_paths")
        if isinstance(changed_paths, list) and "stopping.min_score_improvement" in changed_paths:
            return
    stopping["min_score_improvement"] = 0.0


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]
