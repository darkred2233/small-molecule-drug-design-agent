import re
from dataclasses import dataclass, field


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
    """Rule-based first pass. Replace with qwen3.7-plus when model credentials exist."""

    def parse(self, message: str) -> ParsedConversation:
        normalized = message.lower()
        constraints: list[ParsedConstraint] = []
        intent = "ask_explanation"

        if any(token in normalized for token in ["跑一轮", "启动", "run"]):
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
        scaffold_match = re.search(r"(?:保留|keep)\s*([A-Za-z0-9\-]+|[\u4e00-\u9fff]+)\s*(?:母核|骨架|scaffold)?", message)
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
        region_match = re.search(r"(R\d+)\s*(?:位|位置)?", message, flags=re.IGNORECASE)
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
            reply = "已把你的自然语言要求转成结构化优化约束，后续流程会记录这些约束并用于生成、过滤和排序。"
        elif intent == "run_pipeline":
            reply = "已准备启动当前项目流程；当前版本会先创建可追踪的 dry-run Agent 运行记录。"
        else:
            reply = "我已记录这条消息；当前骨架会先保留上下文，后续接入 RAG 后可基于证据回答。"

        return ParsedConversation(intent=intent, reply=reply, constraints=constraints)
