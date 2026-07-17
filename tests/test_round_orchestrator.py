from types import SimpleNamespace

from medagent.domain.schemas import (
    RunPlan,
    RunPlanAgentConfig,
    RunPlanEvaluation,
)
from medagent.pipeline.round_orchestrator import RoundOrchestrator


def _plan_with_evaluation(mode: str = "external_top_n", top_n: int = 7) -> RunPlan:
    return RunPlan(
        status="approved",
        objective="Round-scoped orchestration test.",
        agents={
            "reinvent4": RunPlanAgentConfig(
                enabled=False,
                role="Global exploration",
                requested_count=0,
            ),
            "crem": RunPlanAgentConfig(
                enabled=True,
                role="Local SAR expansion",
                requested_count=1,
            ),
            "autogrow4": RunPlanAgentConfig(
                enabled=False,
                role="Docking-guided search",
                requested_count=0,
            ),
        },
        evaluation=RunPlanEvaluation(mode=mode, top_n=top_n),
    )


def test_round_assessment_maps_external_top_n_and_passes_round_id(monkeypatch):
    import medagent.services.candidate_assessment as assessment_service

    captured: dict = {}

    def fake_assessment(db, project, **kwargs):
        captured.update(kwargs)
        return {"assessment": "ok", "round_id": kwargs["round_id"]}

    monkeypatch.setattr(
        assessment_service,
        "run_project_candidate_assessment",
        fake_assessment,
    )

    project = SimpleNamespace(project_id="PROJ-ROUND")
    round_obj = SimpleNamespace(round_id="ROUND-001", round_number=1)

    result = RoundOrchestrator(SimpleNamespace()).run_round_assessment(
        None,
        project,
        round_obj,
        _plan_with_evaluation(),
    )

    assert result["assessment"] == "ok"
    assert captured["round_id"] == "ROUND-001"
    assert captured["assessment_mode"] == "external"
    assert captured["external_top_n"] == 7


def test_round_ranking_and_self_refutation_are_round_scoped(monkeypatch):
    import medagent.services.candidate_ranking as ranking_service
    import medagent.services.self_refutation as refutation_service

    ranking_kwargs: dict = {}
    refutation_kwargs: dict = {}
    molecules = [SimpleNamespace(molecule_id="MOL-ROUND-1")]

    def fake_rankings(db, project, **kwargs):
        ranking_kwargs.update(kwargs)
        return SimpleNamespace(as_dict=lambda: {"ranking": "ok", "round_id": kwargs["round_id"]})

    def fake_critiques(db, project, settings, **kwargs):
        refutation_kwargs.update(kwargs)
        return {"refutation": "ok", "round_id": kwargs["round_id"]}

    monkeypatch.setattr(ranking_service, "generate_project_rankings", fake_rankings)
    monkeypatch.setattr(refutation_service, "generate_project_critiques", fake_critiques)

    orch = RoundOrchestrator(SimpleNamespace())
    monkeypatch.setattr(
        orch,
        "collect_round_candidates",
        lambda db, project, round_obj: molecules,
    )
    project = SimpleNamespace(project_id="PROJ-ROUND")
    round_obj = SimpleNamespace(round_id="ROUND-002", round_number=2)

    ranking = orch.run_round_ranking(None, project, round_obj)
    refutation = orch.run_round_self_refutation(None, project, round_obj)

    assert ranking == {"ranking": "ok", "round_id": "ROUND-002"}
    assert ranking_kwargs["molecules"] == molecules
    assert ranking_kwargs["round_id"] == "ROUND-002"
    assert refutation == {"refutation": "ok", "round_id": "ROUND-002"}
    assert refutation_kwargs["round_id"] == "ROUND-002"
