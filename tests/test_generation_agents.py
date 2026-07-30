from medagent.agents.autogrow4_agent import AutoGrow4Agent
from medagent.agents.crem_agent import CremAgent
from medagent.agents.generation import GENERATION_AGENTS, run_generation_agent
from medagent.agents.targetdiff_agent import TargetDiffAgent
from medagent.domain.schemas import AgentTask
from medagent.services.molecule_generation import GenerationBatch, GenerationCandidate
from medagent.services.targetdiff_adapter import TargetDiffResult


def test_generation_registry_contains_only_supported_local_generators():
    assert set(GENERATION_AGENTS) == {"crem", "targetdiff", "autogrow4"}


def test_targetdiff_agent_uses_local_pocket_generation(monkeypatch, tmp_path):
    import medagent.agents.targetdiff_agent as targetdiff_agent

    pocket = tmp_path / "pocket.pdb"
    pocket.write_text("HEADER POCKET\n", encoding="utf-8")
    captured = {}
    monkeypatch.setattr(
        targetdiff_agent,
        "generation_tool_status",
        lambda: {"targetdiff": {"available": True, "configured_timeout_seconds": 90}},
    )

    def fake_run(request, status):
        captured["request"] = request
        captured["status"] = status
        return TargetDiffResult(
            "targetdiff_local_generation",
            "targetdiff",
            True,
            generated_smiles=["CCO", "CCN"],
            labels=["targetdiff_generation_pose"],
        )

    monkeypatch.setattr(targetdiff_agent, "run_targetdiff_generation", fake_run)
    result = TargetDiffAgent().run(
        AgentTask(
            agent="targetdiff",
            round=1,
            constraints={"requested_count": 2},
            resource_bundle={"pocket_file": str(pocket)},
        )
    )

    assert result.success is True
    assert [item.smiles for item in result.molecules] == ["CCO", "CCN"]
    assert captured["request"].pocket_file == str(pocket)
    assert captured["request"].batch_size == 25
    assert result.molecules[0].provenance["agent"] == "targetdiff"
    assert result.molecules[0].metadata["generation_pose_is_docking_evidence"] is False


def test_targetdiff_agent_skips_without_a_real_pocket_file():
    result = TargetDiffAgent().run(AgentTask(agent="targetdiff", round=1, constraints={"requested_count": 1}))

    assert result.status == "skipped"
    assert result.failure_reason == "targetdiff_requires_pocket_file"


def test_targetdiff_agent_preserves_external_failure_diagnostics(monkeypatch, tmp_path):
    import medagent.agents.targetdiff_agent as targetdiff_agent

    pocket = tmp_path / "pocket.pdb"
    pocket.write_text("HEADER POCKET\n", encoding="utf-8")
    monkeypatch.setattr(
        targetdiff_agent,
        "generation_tool_status",
        lambda: {"targetdiff": {"available": True, "configured_timeout_seconds": 90}},
    )
    monkeypatch.setattr(
        targetdiff_agent,
        "run_targetdiff_generation",
        lambda *_args: TargetDiffResult(
            "targetdiff_local_generation",
            "targetdiff",
            False,
            warnings=["targetdiff_execution_failed"],
            stderr="AttributeError: module 'numpy' has no attribute 'long'",
            exit_code=1,
            runtime_seconds=6.2,
            provenance={"command": ["python", "sample_for_pocket.py"]},
        ),
    )

    result = TargetDiffAgent().run(
        AgentTask(
            agent="targetdiff",
            round=1,
            constraints={"requested_count": 1},
            resource_bundle={"pocket_file": str(pocket)},
        )
    )

    assert result.success is False
    assert result.execution_details["exit_code"] == 1
    assert "numpy" in result.execution_details["stderr"]
    assert result.execution_details["command"] == ["python", "sample_for_pocket.py"]


def test_autogrow_agent_preserves_batch_failure_diagnostics(monkeypatch, tmp_path):
    import medagent.agents.autogrow4_agent as autogrow4_agent

    receptor = tmp_path / "receptor.pdb"
    source_pool = tmp_path / "source.smi"
    receptor.write_text("HEADER RECEPTOR\n", encoding="utf-8")
    source_pool.write_text("CCO\tethanol\n", encoding="utf-8")

    class FailedAdapter:
        def generate(self, **_kwargs):
            return GenerationBatch(
                candidates=[],
                adapter_mode="autogrow4_local_generation",
                tool_status={"autogrow4": {"available": True}},
                warnings=["autogrow4_execution_failed"],
                provenance={"exit_code": 2, "stderr": "AutoGrow failed"},
            )

    monkeypatch.setitem(autogrow4_agent.STRATEGY_ADAPTERS, "autogrow4", FailedAdapter())
    result = AutoGrow4Agent().run(
        AgentTask(
            agent="autogrow4",
            round=1,
            seed_molecules=["CCO"],
            constraints={"requested_count": 1},
            resource_bundle={
                "receptor_file": str(receptor),
                "source_compounds_file": str(source_pool),
                "grid_center": [1, 2, 3],
                "grid_size": [18, 18, 18],
            },
        )
    )

    assert result.success is False
    assert result.execution_details == {"exit_code": 2, "stderr": "AutoGrow failed"}


def test_autogrow_agent_consumes_resource_seed_snapshot_and_local_grid(monkeypatch, tmp_path):
    import medagent.agents.autogrow4_agent as autogrow4_agent

    receptor = tmp_path / "receptor.pdb"
    source_pool = tmp_path / "source.smi"
    receptor.write_text("HEADER RECEPTOR\n", encoding="utf-8")
    source_pool.write_text("CCO\tethanol\nCCN\tethylamine\n", encoding="utf-8")
    captured = {}

    class FakeAdapter:
        def generate(self, **kwargs):
            captured.update(kwargs)
            return GenerationBatch(
                candidates=[GenerationCandidate("CCC", "autogrow4", "CCO", "local search")],
                adapter_mode="autogrow4_local_generation",
                tool_status={"autogrow4": {"available": True}},
                external_tool_used=True,
                execution_mode="external_tool",
            )

    monkeypatch.setitem(autogrow4_agent.STRATEGY_ADAPTERS, "autogrow4", FakeAdapter())
    result = AutoGrow4Agent().run(
        AgentTask(
            agent="autogrow4",
            round=1,
            seed_molecules=["CCN", "CCC"],
            constraints={"requested_count": 1},
            campaign_config={"search_intensity": "quick"},
            resource_bundle={
                "receptor_file": str(receptor),
                "source_compounds_file": str(source_pool),
                "grid_center": [1, 2, 3],
                "grid_size": [18, 18, 18],
            },
        )
    )

    assert result.success is True
    assert captured["seeds"] == ["CCO", "CCN"]
    assert captured["constraints"]["num_generations"] == 3
    assert captured["constraints"]["grid_size"] == [18, 18, 18]
    assert captured["constraints"]["docking_backend"] == "vina_gpu_2_1_batch"
    assert captured["constraints"]["gpu_required"] is True
    assert captured["constraints"]["gpu_id"] == 0
    assert captured["constraints"]["cpu_fallback"] is False


def test_crem_requires_seed_molecules_before_generation():
    result = CremAgent().run(AgentTask(agent="crem", round=1, constraints={"requested_count": 1}))

    assert result.success is False
    assert result.failure_reason == "generation_requires_at_least_one_seed_ligand"
    assert run_generation_agent is not None
