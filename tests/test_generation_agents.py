from types import SimpleNamespace

from medagent.agents import generation_base
from medagent.agents.generation import AutoGrow4Agent, CremAgent, Reinvent4Agent
from medagent.domain.schemas import AgentTask
from medagent.services.molecule_generation import GenerationBatch, GenerationCandidate


class FakeStrategyAdapter:
    def __init__(self, strategy: str) -> None:
        self.strategy = strategy
        self.calls = []

    def generate(self, *, seeds, requested_count, constraints):
        self.calls.append(
            {
                "seeds": seeds,
                "requested_count": requested_count,
                "constraints": constraints,
            }
        )
        return GenerationBatch(
            candidates=[
                GenerationCandidate(
                    smiles="CCO",
                    strategy=self.strategy,
                    seed_smiles=seeds[0],
                    rationale="Generated from test strategy",
                    labels=("test_generated",),
                    score=0.7,
                    metadata={"candidate_source": "test_strategy"},
                )
            ],
            adapter_mode="test_adapter",
            tool_status={"test_tool": {"available": True}},
            warnings=["test_warning"],
            candidate_source_counts={"test_strategy": 1},
            provenance={"execution_mode": "test"},
        )


def test_reinvent4_agent_returns_agent_result_with_provenance(monkeypatch):
    requests = []

    monkeypatch.setattr(
        "medagent.services.reinvent4_adapter.check_reinvent4_available",
        lambda: {"available": True, "mode": "test", "warning": None},
    )

    def fake_run_reinvent4(request, reinvent4_status):
        requests.append((request, reinvent4_status))
        return SimpleNamespace(
            success=True,
            generated_smiles=["CCO"],
            scores=[0.7],
            labels=["test_generated"],
            warnings=["test_warning"],
            adapter_mode="test_reinvent4_adapter",
            provenance={"execution_mode": "external_tool"},
        )

    monkeypatch.setattr(
        "medagent.services.reinvent4_adapter.run_reinvent4_generation",
        fake_run_reinvent4,
    )

    result = Reinvent4Agent().run(
        AgentTask(
            round=2,
            agent="reinvent4",
            seed_molecules=["CCN"],
            constraints={"requested_count": 1, "keep_core": True},
            budget="low",
        )
    )

    assert result.status == "completed"
    assert result.success is True
    assert result.warnings == ["test_warning"]
    assert requests[0][0].num_molecules == 1
    assert result.molecules[0].smiles == "CCO"
    assert result.molecules[0].provenance["agent"] == "reinvent4"
    assert result.molecules[0].provenance["round"] == 2
    assert result.molecules[0].provenance["method"] == "test_reinvent4_adapter"
    assert result.molecules[0].provenance["adapter_mode"] == "test_reinvent4_adapter"
    assert result.molecules[0].provenance["execution_mode"] == "external_tool"


def test_crem_agent_returns_agent_result_with_provenance(monkeypatch):
    fake_adapter = FakeStrategyAdapter("crem")
    monkeypatch.setitem(generation_base.STRATEGY_ADAPTERS, "crem", fake_adapter)

    result = CremAgent().run(
        AgentTask(
            round=1,
            agent="crem",
            seed_molecules=["CCN"],
            constraints={"requested_count": 1, "keep_core": True},
            budget="low",
        )
    )

    assert result.status == "completed"
    assert result.success is True
    assert result.molecules[0].provenance["agent"] == "crem"
    assert result.molecules[0].provenance["source_strategy"] == "crem"


def test_crem_agent_skips_zero_budget_without_calling_strategy(monkeypatch):
    fake_adapter = FakeStrategyAdapter("crem")
    monkeypatch.setitem(generation_base.STRATEGY_ADAPTERS, "crem", fake_adapter)

    result = CremAgent().run(
        AgentTask(
            round=1,
            agent="crem",
            seed_molecules=["CCN"],
            constraints={"requested_count": 0},
            budget="low",
        )
    )

    assert result.status == "skipped"
    assert result.success is False
    assert result.failure_reason == "generation_budget_is_zero"
    assert fake_adapter.calls == []


def test_autogrow4_agent_skips_when_receptor_or_grid_is_missing(monkeypatch):
    fake_adapter = FakeStrategyAdapter("autogrow4")
    monkeypatch.setitem(generation_base.STRATEGY_ADAPTERS, "autogrow4", fake_adapter)

    result = AutoGrow4Agent().run(
        AgentTask(
            round=1,
            agent="autogrow4",
            seed_molecules=["CCN"],
            constraints={"requested_count": 1},
            budget="low",
        )
    )

    assert result.status == "skipped"
    assert result.success is False
    assert result.failure_reason == "autogrow4_requires_receptor_file_or_resource_bundle"
    assert fake_adapter.calls == []


def test_autogrow4_agent_runs_when_receptor_and_grid_are_available(tmp_path, monkeypatch):
    receptor = tmp_path / "receptor.pdb"
    receptor.write_text("HEADER TEST\n", encoding="utf-8")
    fake_adapter = FakeStrategyAdapter("autogrow4")
    monkeypatch.setitem(generation_base.STRATEGY_ADAPTERS, "autogrow4", fake_adapter)

    result = AutoGrow4Agent().run(
        AgentTask(
            round=1,
            agent="autogrow4",
            seed_molecules=["CCN"],
            constraints={
                "requested_count": 1,
                "receptor_file": str(receptor),
                "grid_center": [1.0, 2.0, 3.0],
                "grid_size": [20.0, 20.0, 20.0],
            },
            budget="low",
        )
    )

    assert result.status == "completed"
    assert result.success is True
    assert fake_adapter.calls[0]["constraints"]["receptor_file"] == str(receptor)
    assert result.molecules[0].provenance["agent"] == "autogrow4"
    assert result.molecules[0].provenance["source_strategy"] == "autogrow4"
