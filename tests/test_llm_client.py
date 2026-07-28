import pytest

from medagent.llm.client import LLMClient, LLMResponse, StructuredOutputError


def test_generate_structured_rejects_schema_invalid_json(monkeypatch):
    client = LLMClient()
    monkeypatch.setattr(
        client,
        "complete",
        lambda **_kwargs: LLMResponse(
            content='{"count": 51}',
            model="test-model",
            provider="test-provider",
        ),
    )

    with pytest.raises(StructuredOutputError, match="schema validation"):
        client.generate_structured(
            prompt="Return a count",
            schema={
                "type": "object",
                "properties": {"count": {"type": "integer", "maximum": 50}},
                "required": ["count"],
            },
        )


def test_generate_structured_rejects_non_json_instead_of_faking_success(monkeypatch):
    client = LLMClient()
    monkeypatch.setattr(
        client,
        "complete",
        lambda **_kwargs: LLMResponse(
            content="not json",
            model="test-model",
            provider="test-provider",
        ),
    )

    with pytest.raises(StructuredOutputError, match="not valid JSON"):
        client.generate_structured(prompt="Return JSON", schema={"type": "object"})
