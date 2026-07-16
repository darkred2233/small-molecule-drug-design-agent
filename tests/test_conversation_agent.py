import json
from types import SimpleNamespace

from medagent.agents.conversation import ConversationAgent


class _InvalidIntentClient:
    def complete(self, **kwargs):
        del kwargs
        return SimpleNamespace(
            content=json.dumps(
                {
                    "intent": (
                        "run_pipeline/avoid_risk/prioritize_property/keep_scaffold/"
                        "ask_explanation/general_chat"
                    ),
                    "constraints": [],
                    "reply": "invalid combined intent",
                }
            )
        )


class _InvalidConstraintClient:
    def complete(self, **kwargs):
        del kwargs
        return SimpleNamespace(
            content=json.dumps(
                {
                    "intent": "keep_scaffold",
                    "constraints": [
                        {
                            "label": "keep_scaffold",
                            "field": "scaffold",
                            "operator": "keep",
                            "value": "quinazoline",
                            "priority": 95,
                        }
                    ],
                    "reply": "invalid constraint label",
                }
            )
        )


def test_invalid_llm_intent_falls_back_to_deterministic_parser():
    agent = ConversationAgent()
    agent._llm_client = _InvalidIntentClient()

    parsed = agent.parse("lower hERG risk, keep quinazoline scaffold, edit R6")

    assert parsed.intent == "keep_scaffold"
    assert {constraint.label for constraint in parsed.constraints} == {
        "penalty",
        "protected_motif",
        "editable_region",
    }


def test_invalid_llm_constraint_falls_back_to_deterministic_parser():
    agent = ConversationAgent()
    agent._llm_client = _InvalidConstraintClient()

    parsed = agent.parse("lower hERG risk, keep quinazoline scaffold, edit R6")

    assert parsed.intent == "keep_scaffold"
    assert {constraint.label for constraint in parsed.constraints} == {
        "penalty",
        "protected_motif",
        "editable_region",
    }
