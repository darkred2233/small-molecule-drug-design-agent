import json
import re
from dataclasses import dataclass, field
from typing import Any

from medagent.domain.schemas import RunPlan, RunPlanChange, RunPlanPatch
from medagent.llm import LLMMessage, get_llm_client


EXECUTION_TOKENS = ("开始", "执行", "运行", "自动", "跑", "run", "start", "execute")
CHINESE_NUMBERS = {
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}
AGENT_NAMES = ("reinvent4", "crem", "autogrow4")
AGENT_ALIASES = {
    "reinvent4": ("reinvent4", "reinvent"),
    "crem": ("crem",),
    "autogrow4": ("autogrow4", "autogrow"),
}
PRESET_CHANGES = {
    "快速探索": {
        "max_rounds": 1,
        "next_round_seed_count": 5,
        "exploration_level": "low",
        "evaluation.mode": "fast",
        "evaluation.top_n": 10,
        "agents.reinvent4.requested_count": 5,
        "agents.crem.requested_count": 5,
        "agents.autogrow4.requested_count": 0,
        "agents.reinvent4.enabled": True,
        "agents.crem.enabled": True,
        "agents.autogrow4.enabled": False,
    },
    "标准优化": {
        "max_rounds": 3,
        "next_round_seed_count": 10,
        "exploration_level": "medium",
        "evaluation.mode": "external_top_n",
        "evaluation.top_n": 20,
        "agents.reinvent4.requested_count": 10,
        "agents.crem.requested_count": 10,
        "agents.autogrow4.requested_count": 5,
        "agents.reinvent4.enabled": True,
        "agents.crem.enabled": True,
        "agents.autogrow4.enabled": "conditional",
    },
    "深度探索": {
        "max_rounds": 5,
        "next_round_seed_count": 20,
        "exploration_level": "high",
        "evaluation.mode": "external_top_n",
        "evaluation.top_n": 50,
        "agents.reinvent4.requested_count": 30,
        "agents.crem.requested_count": 20,
        "agents.autogrow4.requested_count": 10,
        "agents.reinvent4.enabled": True,
        "agents.crem.enabled": True,
        "agents.autogrow4.enabled": "conditional",
    },
}


@dataclass
class PlannerAgentResult:
    reply: str
    intent: str
    run_plan: RunPlan
    plan_patch: RunPlanPatch | None = None
    plan_diff: list[RunPlanChange] = field(default_factory=list)
    suggested_execution: bool = False
    requires_confirmation: bool = True
    warnings: list[str] = field(default_factory=list)


class PlannerAgent:
    """Convert natural language into auditable RunPlan patches."""

    def __init__(self, *, use_llm: bool = True) -> None:
        self.use_llm = use_llm
        self._llm_client: Any | None = None

    @property
    def llm_client(self) -> Any:
        if self._llm_client is None:
            self._llm_client = get_llm_client()
        return self._llm_client

    def plan(self, message: str, *, current_plan: RunPlan) -> PlannerAgentResult:
        if not self.use_llm:
            return self._rule_based_plan(message, current_plan)
        try:
            return self._llm_plan(message, current_plan)
        except Exception:
            return self._rule_based_plan(message, current_plan)

    def _llm_plan(self, message: str, current_plan: RunPlan) -> PlannerAgentResult:
        prompt = f"""你是小分子药物设计计划 Agent。
你的任务是把用户自然语言转成 RunPlan patch。不要声称工具已经运行，不要编造 docking/ADMET/SAR 结果。
只返回 JSON，字段如下：
{{
  "reply": "中文，80字以内",
  "intent": "update_run_plan/general_chat",
  "changes": [
    {{"path": "max_rounds", "new_value": 3}},
    {{"path": "constraints.reduce_hERG", "new_value": true}}
  ],
  "suggested_execution": false,
  "requires_confirmation": true,
  "warnings": []
}}

允许修改的字段包括 objective、auto_run、max_rounds、next_round_seed_count、seed_smiles、exploration_level、
agents.reinvent4/crem/autogrow4.enabled、agents.*.budget、agents.*.requested_count、agents.autogrow4.condition、
constraints.*、evaluation.mode、evaluation.top_n、evaluation.use_docking/use_admet/use_synthesis/use_filters、
evaluation.synthesis_route_scope、
stopping.min_score_improvement/stopping.max_total_molecules/stopping.max_tool_failures。

当前 RunPlan:
{json.dumps(_dump_model(current_plan), ensure_ascii=False)}

用户消息:
{message}
"""
        response = self.llm_client.complete(
            messages=[LLMMessage(role="user", content=prompt)],
            provider="qwen",
            model="qwen-plus",
            temperature=0.2,
            max_tokens=1000,
            retry_count=1,
        )
        payload = _extract_json_object(response.content)
        if not isinstance(payload, dict):
            raise ValueError("PlannerAgent did not return a JSON object")
        changes = payload.get("changes", [])
        if not isinstance(changes, list):
            raise ValueError("PlannerAgent changes must be a list")
        change_specs = [
            {"path": item.get("path"), "new_value": item.get("new_value")}
            for item in changes
            if isinstance(item, dict)
        ]
        return self._build_result(
            message=message,
            current_plan=current_plan,
            change_specs=change_specs,
            reply=_string_or_default(payload.get("reply"), "已把你的要求转成 RunPlan 修改。"),
            suggested_execution=bool(payload.get("suggested_execution", False)),
            requires_confirmation=bool(payload.get("requires_confirmation", True)),
            warnings=_string_list(payload.get("warnings")),
        )

    def _rule_based_plan(self, message: str, current_plan: RunPlan) -> PlannerAgentResult:
        normalized = message.lower()
        changes: list[dict[str, Any]] = []
        warnings: list[str] = []
        suggested_execution = _suggests_execution(message)
        requires_confirmation = True

        preset = _extract_preset(message)
        if preset is not None:
            changes.extend(
                {"path": path, "new_value": value}
                for path, value in PRESET_CHANGES[preset].items()
            )

        rounds = _extract_round_count(message)
        if rounds is not None:
            changes.append({"path": "max_rounds", "new_value": rounds})

        next_round_seed_count = _extract_next_round_seed_count(message)
        if next_round_seed_count is not None:
            changes.append({"path": "next_round_seed_count", "new_value": next_round_seed_count})

        for agent_name, requested_count in _extract_agent_counts(message).items():
            changes.append({"path": f"agents.{agent_name}.requested_count", "new_value": requested_count})
            changes.append(
                {
                    "path": f"agents.{agent_name}.enabled",
                    "new_value": "conditional" if agent_name == "autogrow4" and requested_count > 0 else requested_count > 0,
                }
            )

        if suggested_execution:
            changes.append({"path": "auto_run", "new_value": True})

        if "herg" in normalized:
            changes.append({"path": "constraints.reduce_hERG", "new_value": True})
            changes.append({"path": "constraints.max_logp", "new_value": 4.5})

        if "ames" in normalized:
            changes.append({"path": "constraints.reduce_Ames", "new_value": True})

        if any(token in message for token in ("保留核心", "保留母核", "保留骨架")) or "keep core" in normalized:
            changes.append({"path": "constraints.keep_core", "new_value": True})

        if "logp" in normalized or "脂溶" in message:
            changes.append({"path": "constraints.max_logp", "new_value": _extract_threshold(message) or 4.0})

        if "可合成" in message or "合成" in message or "synthesis" in normalized:
            changes.append({"path": "constraints.max_sa_score", "new_value": 5.0})
            changes.append({"path": "agents.crem.budget", "new_value": "high"})
            changes.append({"path": "agents.reinvent4.budget", "new_value": "medium"})

        exploration_level = _extract_exploration_level(message)
        if exploration_level is not None:
            changes.append({"path": "exploration_level", "new_value": exploration_level})
            for agent_name, agent_config in current_plan.agents.items():
                if agent_config.enabled:
                    changes.append({"path": f"agents.{agent_name}.budget", "new_value": exploration_level})

        if _asks_to_disable(message, "autogrow4"):
            changes.append({"path": "agents.autogrow4.enabled", "new_value": False})
            changes.append({"path": "agents.autogrow4.requested_count", "new_value": 0})
            changes.append({"path": "agents.autogrow4.condition", "new_value": None})
        elif _asks_to_enable(message, "autogrow4"):
            changes.append({"path": "agents.autogrow4.enabled", "new_value": "conditional"})
            if current_plan.agents["autogrow4"].requested_count <= 0:
                changes.append({"path": "agents.autogrow4.requested_count", "new_value": 5})
            changes.append(
                {
                    "path": "agents.autogrow4.condition",
                    "new_value": "有可靠 receptor/grid/pose 条件时才运行；否则标记 skipped",
                }
            )
            warnings.append("AutoGrow4 只能条件启用；缺少 receptor/grid 时不能假装成功。")

        if _asks_to_disable(message, "reinvent4"):
            changes.append({"path": "agents.reinvent4.enabled", "new_value": False})
            changes.append({"path": "agents.reinvent4.requested_count", "new_value": 0})
        elif _mentions_agent(message, "reinvent4"):
            changes.append({"path": "agents.reinvent4.enabled", "new_value": True})
            if current_plan.agents["reinvent4"].requested_count <= 0:
                changes.append({"path": "agents.reinvent4.requested_count", "new_value": 10})

        if _asks_to_disable(message, "crem"):
            changes.append({"path": "agents.crem.enabled", "new_value": False})
            changes.append({"path": "agents.crem.requested_count", "new_value": 0})
        elif _mentions_agent(message, "crem"):
            changes.append({"path": "agents.crem.enabled", "new_value": True})
            if current_plan.agents["crem"].requested_count <= 0:
                changes.append({"path": "agents.crem.requested_count", "new_value": 10})
            if "保守" in message or "局部" in message:
                changes.append({"path": "agents.crem.budget", "new_value": "high"})

        if "快速" in message:
            changes.append({"path": "evaluation.mode", "new_value": "fast"})
            changes.append({"path": "evaluation.use_docking", "new_value": False})
        elif "全量" in message:
            changes.append({"path": "evaluation.mode", "new_value": "full"})

        if "合成可行性" in message:
            changes.append({"path": "evaluation.use_synthesis", "new_value": True})

        if _mentions_synthesis_route_prediction(message):
            if _asks_final_round_route_prediction(message):
                changes.append(
                    {"path": "evaluation.synthesis_route_scope", "new_value": "final_round_top_n"}
                )
            elif _asks_every_round_route_prediction(message):
                changes.append(
                    {"path": "evaluation.synthesis_route_scope", "new_value": "every_round_top_n"}
                )
            elif _asks_to_disable_route_prediction(message):
                changes.append({"path": "evaluation.synthesis_route_scope", "new_value": "disabled"})

        top_n = _extract_top_n(message)
        if top_n is not None:
            changes.append({"path": "evaluation.top_n", "new_value": top_n})

        if not changes:
            changes.append({"path": "objective", "new_value": _updated_objective(current_plan.objective, message)})
            requires_confirmation = False

        return self._build_result(
            message=message,
            current_plan=current_plan,
            change_specs=changes,
            reply="已把你的自然语言要求转成 RunPlan 修改，先作为计划预览，不会自动运行工具。",
            suggested_execution=suggested_execution,
            requires_confirmation=requires_confirmation,
            warnings=warnings,
        )

    def _build_result(
        self,
        *,
        message: str,
        current_plan: RunPlan,
        change_specs: list[dict[str, Any]],
        reply: str,
        suggested_execution: bool,
        requires_confirmation: bool,
        warnings: list[str],
    ) -> PlannerAgentResult:
        plan_data = _dump_model(current_plan)
        diffs: list[RunPlanChange] = []
        skipped_changes: list[str] = []

        for change_spec in _dedupe_change_specs(change_specs):
            path = change_spec.get("path")
            if not isinstance(path, str) or not _allowed_path(path):
                skipped_changes.append(str(path))
                continue
            old_value = _get_path(plan_data, path)
            new_value = change_spec.get("new_value")
            if old_value == new_value:
                continue
            _set_path(plan_data, path, new_value)
            diffs.append(
                RunPlanChange(
                    path=path,
                    old_value=old_value,
                    new_value=new_value,
                    affects_next_round=_affects_next_round(path),
                )
            )

        if _get_path(plan_data, "agents.autogrow4.enabled") is False:
            old_condition = _get_path(plan_data, "agents.autogrow4.condition")
            if old_condition is not None:
                _set_path(plan_data, "agents.autogrow4.condition", None)
                diffs.append(
                    RunPlanChange(
                        path="agents.autogrow4.condition",
                        old_value=old_condition,
                        new_value=None,
                        affects_next_round=True,
                    )
                )

        if any(change.path == "auto_run" and change.new_value is True for change in diffs):
            suggested_execution = True

        if skipped_changes:
            warnings.append(f"忽略了不在 RunPlan 契约允许范围内的修改：{', '.join(skipped_changes)}")

        decision_trace = list(plan_data.get("decision_trace") or [])
        decision_trace.append(
            {
                "step": "planner_patch_from_chat",
                "reason": "用户自然语言修改 RunPlan；保存字段级 diff 供前端预览和审计。",
                "user_message": message,
                "changed_paths": [change.path for change in diffs],
                "evidence_refs": [],
            }
        )
        plan_data["decision_trace"] = decision_trace

        run_plan = _validate_run_plan(plan_data)
        plan_patch = RunPlanPatch(
            reason="用户通过自然语言调整 RunPlan。",
            changes=diffs,
            requires_confirmation=requires_confirmation,
            warnings=warnings,
        )
        return PlannerAgentResult(
            reply=reply,
            intent="update_run_plan" if diffs else "general_chat",
            run_plan=run_plan,
            plan_patch=plan_patch,
            plan_diff=diffs,
            suggested_execution=suggested_execution,
            requires_confirmation=requires_confirmation,
            warnings=warnings,
        )


def _extract_json_object(content: str) -> dict[str, Any]:
    match = re.search(r"\{.*\}", content, re.DOTALL)
    if not match:
        raise ValueError("No JSON object found")
    parsed = json.loads(match.group())
    if not isinstance(parsed, dict):
        raise ValueError("JSON payload must be an object")
    return parsed


def _extract_round_count(message: str) -> int | None:
    match = re.search(r"(\d+)\s*(?:轮|rounds?|次)", message, flags=re.IGNORECASE)
    if match:
        return max(1, min(int(match.group(1)), 20))
    for word, value in CHINESE_NUMBERS.items():
        if re.search(rf"(?<![下每本上前后]){re.escape(word)}(?:轮|次)", message):
            return value
    return None


def _extract_preset(message: str) -> str | None:
    if "快速探索" in message:
        return "快速探索"
    if "标准优化" in message or "标准模式" in message:
        return "标准优化"
    if "深度探索" in message or "深度验证" in message:
        return "深度探索"
    return None


def _extract_next_round_seed_count(message: str) -> int | None:
    patterns = (
        r"(?:下一轮|下轮|下一次|后续轮次)[^\n，。；;,.!?！？]{0,24}(?:top\s*)?(?:前)?\s*(\d+)\s*(?:个|条|枚)?\s*(?:种子|seed)",
        r"(?:种子|seed)[^\n，。；;,.!?！？]{0,24}(?:top\s*)?(?:前)?\s*(\d+)",
    )
    for pattern in patterns:
        match = re.search(pattern, message, flags=re.IGNORECASE)
        if match:
            return max(1, min(int(match.group(1)), 100))
    return None


def _extract_agent_counts(message: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for segment in re.split(r"[，。；;,.!?！？\n]", message):
        normalized = segment.lower()
        for agent_name, aliases in AGENT_ALIASES.items():
            if not any(alias in normalized for alias in aliases):
                continue
            match = re.search(
                r"(\d+)\s*(?:个|条|枚|种|分子|molecules?)",
                segment,
                flags=re.IGNORECASE,
            )
            if match:
                counts[agent_name] = max(0, min(int(match.group(1)), 500))
    return counts


def _extract_threshold(message: str) -> float | None:
    match = re.search(r"(?:<=|≤|低于|小于|不超过)\s*(\d+(?:\.\d+)?)", message)
    if not match:
        return None
    return float(match.group(1))


def _extract_top_n(message: str) -> int | None:
    match = re.search(r"top\s*n?\s*(\d+)|前\s*(\d+)\s*个", message, flags=re.IGNORECASE)
    if not match:
        return None
    value = match.group(1) or match.group(2)
    return max(1, min(int(value), 500))


def _extract_exploration_level(message: str) -> str | None:
    normalized = message.lower()
    if "低探索" in message or "保守探索" in message or "low exploration" in normalized:
        return "low"
    if "高探索" in message or "大范围" in message or "high exploration" in normalized:
        return "high"
    if "中等探索" in message or "medium exploration" in normalized:
        return "medium"
    return None


def _mentions_synthesis_route_prediction(message: str) -> bool:
    normalized = message.lower()
    return (
        "合成路线" in message
        or "逆合成" in message
        or "retrosynthesis" in normalized
        or "route prediction" in normalized
        or "synthesis route" in normalized
    )


def _asks_final_round_route_prediction(message: str) -> bool:
    normalized = message.lower()
    return any(
        token in message
        for token in ("最后", "最终", "末轮", "最后一轮", "最终一轮", "不用每次", "不需要每次")
    ) or "final" in normalized


def _asks_every_round_route_prediction(message: str) -> bool:
    normalized = message.lower()
    return any(token in message for token in ("每轮", "每一轮", "每次", "每一次")) or any(
        token in normalized for token in ("every round", "each round", "every time")
    )


def _asks_to_disable_route_prediction(message: str) -> bool:
    normalized = message.lower()
    return any(token in message for token in ("不要跑", "不跑", "禁用", "关闭", "不用跑")) or any(
        token in normalized for token in ("disable", "skip", "off")
    )


def _suggests_execution(message: str) -> bool:
    for segment in re.split(r"[，。；;,.!?！？\n]", message):
        segment = segment.strip()
        if not segment:
            continue
        normalized = segment.lower()
        if any(
            token in segment
            for token in ("不要执行", "别执行", "不执行", "暂不执行", "先不执行", "不要运行", "不运行", "不要跑", "别跑", "不跑", "不自动")
        ):
            continue
        if any(token in normalized or token in segment for token in EXECUTION_TOKENS):
            return True
    return False


def _mentions_agent(message: str, agent_name: str) -> bool:
    normalized = message.lower()
    return any(alias in normalized for alias in AGENT_ALIASES.get(agent_name, (agent_name.lower(),)))


def _asks_to_disable(message: str, agent_name: str) -> bool:
    return _agent_action_requested(
        message,
        agent_name,
        chinese_terms=("不要", "别", "禁用", "关闭", "不跑", "不用", "跳过", "先不", "暂不"),
        english_terms=("disable", "without", "skip", "no", "off"),
    )


def _asks_to_enable(message: str, agent_name: str) -> bool:
    return _agent_action_requested(
        message,
        agent_name,
        chinese_terms=("启用", "打开", "使用", "用", "跑"),
        english_terms=("enable", "use", "run"),
    )


def _agent_action_requested(
    message: str,
    agent_name: str,
    *,
    chinese_terms: tuple[str, ...],
    english_terms: tuple[str, ...],
) -> bool:
    for segment in _agent_segments(message, agent_name):
        normalized = segment.lower()
        if any(term in segment for term in chinese_terms):
            return True
        for term in english_terms:
            pattern = rf"(?<![a-z]){re.escape(term.lower())}(?![a-z])"
            if re.search(pattern, normalized, flags=re.IGNORECASE):
                return True
    return False


def _agent_segments(message: str, agent_name: str) -> list[str]:
    aliases = AGENT_ALIASES.get(agent_name, (agent_name.lower(),))
    return [
        segment
        for segment in re.split(r"[，。；;,.!?！？\n]", message)
        if any(alias in segment.lower() for alias in aliases)
    ]


def _updated_objective(current_objective: str, message: str) -> str:
    if not current_objective:
        return message
    if message in current_objective:
        return current_objective
    return f"{current_objective}\n补充要求：{message}"


def _allowed_path(path: str) -> bool:
    if path in {
        "objective",
        "auto_run",
        "max_rounds",
        "next_round_seed_count",
        "seed_smiles",
        "exploration_level",
        "evaluation.mode",
        "evaluation.top_n",
        "evaluation.use_docking",
        "evaluation.use_admet",
        "evaluation.use_synthesis",
        "evaluation.synthesis_route_scope",
        "evaluation.use_filters",
        "stopping.min_score_improvement",
        "stopping.max_total_molecules",
        "stopping.max_tool_failures",
    }:
        return True
    if path.startswith("constraints."):
        return True
    for agent_name in ("reinvent4", "crem", "autogrow4"):
        if path in {
            f"agents.{agent_name}.enabled",
            f"agents.{agent_name}.budget",
            f"agents.{agent_name}.requested_count",
            f"agents.{agent_name}.condition",
        }:
            return True
    return False


def _affects_next_round(path: str) -> bool:
    return path.startswith(("agents.", "constraints.", "evaluation.", "stopping.")) or path in {
        "max_rounds",
        "next_round_seed_count",
        "seed_smiles",
        "exploration_level",
        "auto_run",
    }


def _dedupe_change_specs(change_specs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    for change_spec in change_specs:
        path = change_spec.get("path")
        if isinstance(path, str):
            deduped[path] = change_spec
    return list(deduped.values())


def _get_path(payload: dict[str, Any], path: str) -> Any:
    current: Any = payload
    for part in path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _set_path(payload: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    current = payload
    for part in parts[:-1]:
        next_value = current.get(part)
        if not isinstance(next_value, dict):
            next_value = {}
            current[part] = next_value
        current = next_value
    current[parts[-1]] = value


def _validate_run_plan(payload: dict[str, Any]) -> RunPlan:
    if hasattr(RunPlan, "model_validate"):
        return RunPlan.model_validate(payload)
    return RunPlan.parse_obj(payload)


def _dump_model(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model.dict()


def _string_or_default(value: Any, default: str) -> str:
    return value if isinstance(value, str) and value.strip() else default


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]
