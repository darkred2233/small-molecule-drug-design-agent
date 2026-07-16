import json
import re
from dataclasses import dataclass, field
from typing import Any

from medagent.llm import LLMMessage, get_llm_client


ALLOWED_INTENTS = frozenset(
    {
        "ask_explanation",
        "avoid_risk",
        "general_chat",
        "keep_scaffold",
        "prioritize_property",
        "run_pipeline",
    }
)
ALLOWED_CONSTRAINT_LABELS = frozenset(
    {"editable_region", "objective", "penalty", "protected_motif"}
)


@dataclass
class ParsedConstraint:
    label: str
    field: str | None = None
    operator: str | None = None
    value: str | None = None
    priority: int = 50


@dataclass
class ParsedConversation:
    intent: str
    reply: str
    constraints: list[ParsedConstraint] = field(default_factory=list)


class ConversationAgent:
    """对话解析 Agent：优先尝试 LLM，失败时回退到轻量规则解析。"""

    def __init__(self):
        self._llm_client: Any | None = None

    @property
    def llm_client(self) -> Any:
        if self._llm_client is None:
            self._llm_client = get_llm_client()
        return self._llm_client

    def parse(self, message: str, project_context: str = "") -> ParsedConversation:
        """解析用户消息，提取意图和优化约束。"""
        try:
            return self._llm_parse(message, project_context)
        except Exception as exc:
            print(f"LLM 解析失败，回退到规则解析: {exc}")
            return self._rule_based_parse(message)

    def _llm_parse(self, message: str, project_context: str) -> ParsedConversation:
        """基于 LLM 的结构化解析。"""
        prompt = f"""你是药物设计助手。请解析用户消息的意图并提取优化约束。

## 项目上下文
{project_context or "无"}

## 用户消息
{message}

The intent field must contain exactly one of these values: {", ".join(sorted(ALLOWED_INTENTS))}.
Each constraint label must contain exactly one of these values:
{", ".join(sorted(ALLOWED_CONSTRAINT_LABELS))}.
请只返回 JSON：
{{
  "intent": "avoid_risk",
  "constraints": [
    {{
      "label": "penalty/objective/protected_motif/editable_region",
      "field": "hERG_risk/solubility/scaffold/region/...",
      "operator": "minimize/maximize/keep/edit",
      "value": "具体值",
      "priority": 0-100
    }}
  ],
  "reply": "对用户的自然语言回复（中文，50字以内）"
}}
"""

        response = self.llm_client.complete(
            messages=[LLMMessage(role="user", content=prompt)],
            provider="qwen",
            model="qwen-plus",
            temperature=0.3,
            max_tokens=800,
        )
        return self._parse_llm_response(response.content)

    def _parse_llm_response(self, content: str) -> ParsedConversation:
        """解析 LLM 的 JSON 响应。"""
        json_match = re.search(r"\{.*\}", content, re.DOTALL)
        if not json_match:
            raise ValueError("LLM 未返回有效 JSON")

        result = json.loads(json_match.group())
        intent = result.get("intent")
        if intent not in ALLOWED_INTENTS:
            raise ValueError(f"LLM returned unsupported intent: {intent!r}")
        raw_constraints = result.get("constraints", [])
        if not isinstance(raw_constraints, list):
            raise ValueError("LLM constraints must be a list")
        constraints = []
        for constraint in raw_constraints:
            if not isinstance(constraint, dict):
                raise ValueError("Each LLM constraint must be an object")
            if constraint.get("label") not in ALLOWED_CONSTRAINT_LABELS:
                raise ValueError(
                    f"LLM returned unsupported constraint label: {constraint.get('label')!r}"
                )
            parsed_constraint = ParsedConstraint(**constraint)
            if not 0 <= parsed_constraint.priority <= 100:
                raise ValueError("LLM constraint priority must be between 0 and 100")
            constraints.append(parsed_constraint)
        return ParsedConversation(
            intent=intent,
            reply=result["reply"],
            constraints=constraints,
        )

    def _rule_based_parse(self, message: str) -> ParsedConversation:
        """离线可用的规则解析兜底。"""
        normalized = message.lower()
        constraints: list[ParsedConstraint] = []
        intent = "general_chat"

        if any(token in normalized for token in ["跑一轮", "启动", "运行", "run", "start"]):
            intent = "run_pipeline"

        if any(token in normalized for token in ["herg", "ames", "毒性", "风险"]):
            intent = "avoid_risk"
            if "herg" in normalized:
                constraints.append(
                    ParsedConstraint(
                        label="penalty",
                        field="hERG_risk",
                        operator="minimize",
                        value="hERG_high_risk",
                        priority=90,
                    )
                )
            if "ames" in normalized:
                constraints.append(
                    ParsedConstraint(
                        label="penalty",
                        field="Ames_risk",
                        operator="minimize",
                        value="Ames_high_risk",
                        priority=90,
                    )
                )

        if any(token in normalized for token in ["溶解度", "solubility"]):
            intent = "prioritize_property"
            constraints.append(
                ParsedConstraint(
                    label="objective",
                    field="solubility",
                    operator="maximize",
                    value="high",
                    priority=80,
                )
            )

        scaffold_match = re.search(
            r"(?:保留|keep)\s*([A-Za-z0-9-]+|[\u4e00-\u9fff]+?)\s*(?:母核|骨架|scaffold|$)",
            message,
            flags=re.IGNORECASE,
        )
        if scaffold_match:
            intent = "keep_scaffold"
            constraints.append(
                ParsedConstraint(
                    label="protected_motif",
                    field="scaffold",
                    operator="keep",
                    value=scaffold_match.group(1),
                    priority=95,
                )
            )

        region_match = re.search(r"(R\d+)\s*(?:位点|位置)?", message, flags=re.IGNORECASE)
        if region_match:
            constraints.append(
                ParsedConstraint(
                    label="editable_region",
                    field="region",
                    operator="edit",
                    value=region_match.group(1).upper(),
                    priority=75,
                )
            )

        if constraints:
            reply = "已把你的要求转成结构化优化约束，后续流程会用于生成、过滤和排序。"
        elif intent == "run_pipeline":
            reply = "已准备启动当前项目流程。"
        else:
            reply = "已记录这条消息，后续会结合项目证据继续回答。"

        return ParsedConversation(intent=intent, reply=reply, constraints=constraints)
