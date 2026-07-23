from types import SimpleNamespace

from medagent.core.config import Settings
from medagent.db.models import Base, Project, ProjectResource
from medagent.db.session import build_engine, build_session_factory
from medagent.domain.schemas import TargetDiffCampaignConfig

from medagent.pipeline.round_orchestrator import RoundOrchestrator


def test_targetdiff_resource_resolution_prefers_explicit_project_pocket(tmp_path):
    from medagent.services.targetdiff_resources import resolve_targetdiff_resources

    settings = Settings(database_url=f"sqlite:///{tmp_path / 'test.db'}")
    engine = build_engine(settings)
    Base.metadata.create_all(bind=engine)
    session_factory = build_session_factory(settings)
    explicit_pocket = tmp_path / "explicit-pocket.pdb"
    fallback_pocket = tmp_path / "fallback-pocket.pdb"
    explicit_pocket.write_text("HEADER EXPLICIT POCKET\n", encoding="utf-8")
    fallback_pocket.write_text("HEADER FALLBACK POCKET\n", encoding="utf-8")

    with session_factory() as db:
        project = Project(project_id="PROJ-TARGETDIFF", name="TargetDiff resources")
        db.add_all(
            [
                project,
                ProjectResource(
                    resource_id="POCKET-FALLBACK",
                    project_id=project.project_id,
                    resource_type="binding_pocket",
                    scope="project",
                    name="Fallback pocket",
                    file_path=f"local://{fallback_pocket}",
                ),
                ProjectResource(
                    resource_id="POCKET-EXPLICIT",
                    project_id=project.project_id,
                    resource_type="binding_pocket",
                    scope="project",
                    name="Explicit pocket",
                    file_path=f"local://{explicit_pocket}",
                ),
            ]
        )
        db.flush()

        bundle = resolve_targetdiff_resources(
            db,
            project,
            TargetDiffCampaignConfig(pocket_resource_id="POCKET-EXPLICIT"),
        )

    assert bundle.pocket_file == str(explicit_pocket)
    assert bundle.pocket_resource_id == "POCKET-EXPLICIT"
    assert bundle.provenance["source"] == "project_resource"


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
        {"mode": "external_top_n", "top_n": 7},
    )

    assert result["assessment"] == "ok"
    assert captured["round_id"] == "ROUND-001"
    assert captured["assessment_mode"] == "external"
    assert captured["external_top_n"] == 7


def test_round_assessment_passes_preflight_stage_permissions(monkeypatch):
    import medagent.services.candidate_assessment as assessment_service

    captured: dict = {}

    def fake_assessment(db, project, **kwargs):
        captured.update(kwargs)
        return {"assessment": "ok"}

    monkeypatch.setattr(assessment_service, "run_project_candidate_assessment", fake_assessment)
    round_obj = SimpleNamespace(
        round_id="ROUND-003",
        round_number=3,
        execution_config_snapshot_json={
            "scientific_preflight": {
                "plan": {
                    "stages": [
                        {"stage": "vina_screen", "allowed": False, "evidence_level": "L0"},
                        {"stage": "gnina_refine", "allowed": False, "evidence_level": "L0"},
                        {"stage": "admet_batch", "allowed": True, "evidence_level": "L1"},
                        {
                            "stage": "retrosynthesis_batch",
                            "allowed": True,
                            "evidence_level": "L1",
                        },
                    ]
                }
            }
        },
    )

    RoundOrchestrator(SimpleNamespace()).run_round_assessment(
        None,
        SimpleNamespace(project_id="PROJ-ROUND"),
        round_obj,
    )

    assert captured["stage_permissions"] == {
        "docking": False,
        "admet": False,
        "synthesis": False,
        "ranking": True,
    }


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


def test_docking_stage_payload_does_not_promote_vina_to_gnina():
    payload = {"adapter_mode": "vina_local_docking", "external_success_count": 1}

    assert RoundOrchestrator._docking_stage_payload(payload, "vina_local_docking", "vina") == payload
    assert RoundOrchestrator._docking_stage_payload(
        payload, "vina_local_docking", "gnina"
    ) == {
        "status": "not_executed",
        "execution_mode": "not_executed",
        "warnings": ["gnina_not_selected_by_docking_adapter"],
    }
