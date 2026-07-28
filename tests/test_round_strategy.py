from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from medagent.agents.round_strategy import RoundStrategyAgent
from medagent.api.rounds_router import _prepare_seed_selection
from medagent.db.models import (
    ADMETResult,
    AgentRun,
    AdvisorSuggestion,
    Base,
    CampaignRun,
    Critique,
    DockingResult,
    Molecule,
    MoleculeProperty,
    Project,
    ProjectRound,
    Ranking,
    RoundReport,
    SynthesisRoute,
)
from medagent.pipeline.round_orchestrator import RoundOrchestrator
from medagent.reporting.round_report import build_round_report
from medagent.services.round_strategy_snapshot import (
    ExecutionSnapshotError,
    build_execution_snapshot,
    persist_strategy_document,
    validate_execution_snapshot,
)
from medagent.services.strategy_validator import StrategyValidator


class FailingLLMClient:
    def generate_structured(self, **kwargs):
        raise ValueError("provider unavailable")


class CapturingLLMClient:
    def __init__(self):
        self.schema = None

    def generate_structured(self, **kwargs):
        self.schema = kwargs["schema"]
        return {
            "objective": "select a persisted pocket",
            "campaign_config": {
                "crem": {"enabled": True, "num_molecules": 10},
                "targetdiff": {"enabled": False, "num_molecules": 0},
                "autogrow4": {"enabled": False, "num_molecules": 0},
            },
        }


def make_session() -> Session:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_strategy_version_only_advances_when_the_canonical_document_changes():
    round_obj = SimpleNamespace(user_conditions_json=None)
    strategy = {"objective": "first", "campaign_config": {}}

    first_version, first_hash = persist_strategy_document(
        round_obj, strategy, source="llm", changed_at="2026-07-28T00:00:00+00:00"
    )
    same_version, same_hash = persist_strategy_document(
        round_obj, strategy, source="confirmation", changed_at="2026-07-28T00:01:00+00:00"
    )
    changed_version, changed_hash = persist_strategy_document(
        round_obj,
        {**strategy, "objective": "user final"},
        source="user_confirmation",
        changed_at="2026-07-28T00:02:00+00:00",
    )

    assert (first_version, same_version, changed_version) == (1, 1, 2)
    assert first_hash == same_hash
    assert changed_hash != first_hash


def test_execution_snapshot_rejects_strategy_tampering():
    snapshot = build_execution_snapshot(
        {"objective": "confirmed", "campaign_config": {}},
        strategy_version=1,
        confirmed_at="2026-07-28T00:00:00+00:00",
        parent_round_id=None,
        seed_smiles=[],
        seed_molecule_ids=[],
    )
    snapshot["strategy"]["objective"] = "changed after confirmation"

    with pytest.raises(ExecutionSnapshotError, match="hash mismatch"):
        validate_execution_snapshot(snapshot)


def test_round_strategy_uses_deterministic_fallback_when_llm_is_unavailable(monkeypatch):
    agent = RoundStrategyAgent(llm_client=FailingLLMClient())
    monkeypatch.setattr(
        agent,
        "_collect_context",
        lambda db, project, parent_round_id: {
            "project_objective": "Improve potency without increasing hERG risk",
            "data_summary": {
                "seed_ligand_count": 2,
                "binding_site_count": 1,
                "prepared_binding_site_count": 1,
            },
            "has_previous_round": True,
            "previous_molecule_count": 3,
            "previous_ranked_molecule_ids": ["MOL-2", "MOL-1", "MOL-3"],
        },
    )

    strategy = agent.generate_strategy_draft(
        db=None,
        project=SimpleNamespace(name="Fallback project", target_id="TGT-1"),
        round_number=2,
        parent_round_id="ROUND-1",
        tool_availability={
            "crem": {"available": True},
            "targetdiff": False,
            "autogrow4": False,
        },
    )

    assert strategy["campaign_config"]["crem"]["enabled"] is True
    assert strategy["campaign_config"]["targetdiff"]["enabled"] is False
    assert strategy["seed_policy"]["molecule_ids"] == ["MOL-2", "MOL-1", "MOL-3"]
    assert strategy["requires_user_confirmation"] is True
    assert strategy["planner_metadata"] == {
        "mode": "deterministic_fallback",
        "provider": None,
        "error_type": "ValueError",
    }
    assert any("deterministic fallback" in warning for warning in strategy["warnings"])


def test_round_strategy_schema_enumerates_only_persisted_project_binding_sites(monkeypatch):
    client = CapturingLLMClient()
    agent = RoundStrategyAgent(llm_client=client)
    monkeypatch.setattr(
        agent,
        "_collect_context",
        lambda db, project, parent_round_id: {
            "project_objective": "test",
            "active_structure_id": "STR-1",
            "active_binding_site_id": "SITE-2",
            "available_binding_site_ids": ["SITE-1", "SITE-2"],
            "data_summary": {"seed_ligand_count": 1, "binding_site_count": 2},
            "has_previous_round": False,
        },
    )

    agent.generate_strategy_draft(
        db=None,
        project=SimpleNamespace(name="Pocket project", target_id="TGT-1"),
        round_number=1,
        tool_availability={"crem": True},
    )

    campaigns = client.schema["properties"]["campaign_config"]["properties"]
    assert campaigns["targetdiff"]["properties"]["binding_site_id"]["enum"] == [
        "SITE-1",
        "SITE-2",
    ]
    assert "pocket_resource_id" not in campaigns["targetdiff"]["properties"]
    assert campaigns["autogrow4"]["properties"]["binding_site_id"]["enum"] == [
        "SITE-1",
        "SITE-2",
    ]


def test_next_round_context_contains_parent_scientific_evidence():
    with make_session() as db:
        project = Project(project_id="PROJ-CONTEXT", name="Context", objective="Improve potency")
        parent = ProjectRound(
            round_id="ROUND-CONTEXT",
            project_id=project.project_id,
            round_number=1,
            status="completed",
        )
        molecule = Molecule(
            molecule_id="MOL-CONTEXT",
            project_id=project.project_id,
            round_id=parent.round_id,
            smiles="CCO",
            status="candidate_assessed",
            source_agent="crem",
            generation_method="crem_fragment_mutation",
        )
        db.add_all([project, parent, molecule])
        db.flush()
        db.add_all(
            [
                CampaignRun(
                    campaign_run_id="CAM-CONTEXT",
                    project_id=project.project_id,
                    round_id=parent.round_id,
                    method="autogrow4",
                    status="failed",
                    metrics_json={"failure_reason": "mutation_exhausted"},
                    warnings_json=["generation_incomplete"],
                ),
                MoleculeProperty(
                    molecule_id=molecule.molecule_id,
                    mw=46.07,
                    logp=-0.001,
                    tpsa=20.23,
                    hbd=1,
                    hba=1,
                    sa_score=1.2,
                ),
                DockingResult(
                    molecule_id=molecule.molecule_id,
                    round_id=parent.round_id,
                    vina_score=-8.1,
                    cnn_score=0.71,
                    key_hbond_count=2,
                    clash_count=0,
                ),
                ADMETResult(
                    molecule_id=molecule.molecule_id,
                    round_id=parent.round_id,
                    hERG_risk="low",
                    Ames_risk="low",
                    admet_risk_score=0.1,
                ),
                SynthesisRoute(
                    molecule_id=molecule.molecule_id,
                    round_id=parent.round_id,
                    route_found=True,
                    route_steps=2,
                    route_confidence=0.8,
                ),
                Critique(
                    critique_id="CRIT-CONTEXT",
                    molecule_id=molecule.molecule_id,
                    round_id=parent.round_id,
                    con_score=10.0,
                    risk_level="medium",
                    reason="Check metabolic liability",
                    refutation_decision="reserve",
                    campaign_patch_suggestions_json={"reduce_logp": True},
                ),
                Ranking(
                    project_id=project.project_id,
                    molecule_id=molecule.molecule_id,
                    round_id=parent.round_id,
                    rank=1,
                    overall_score=0.88,
                    final_decision="advance",
                    score_breakdown={"docking": 0.9},
                ),
                RoundReport(
                    report_id="REPORT-CONTEXT",
                    project_id=project.project_id,
                    round_id=parent.round_id,
                    status="completed",
                    report_json={"next_round_recommendations": [{"action": "reduce_logp"}]},
                ),
                AdvisorSuggestion(
                    suggestion_id="ADVISOR-CONTEXT",
                    project_id=project.project_id,
                    round_id=parent.round_id,
                    summary="Keep the active scaffold",
                    suggestions=[{"action": "retain_scaffold"}],
                    next_round_constraints=[{"field": "logp", "max": 4.0}],
                    suggested_generation_config={"crem": {"edit_depth": 1}},
                ),
            ]
        )
        db.flush()

        context = RoundStrategyAgent(FailingLLMClient())._collect_context(
            db, project, parent.round_id
        )

        top = context["previous_top_molecules"][0]
        assert top["smiles"] == "CCO"
        assert top["properties"]["mw"] == 46.07
        assert top["docking"]["vina_score"] == -8.1
        assert top["admet"]["hERG_risk"] == "low"
        assert top["synthesis"]["route_found"] is True
        assert top["critique"]["campaign_patch_suggestions"] == {"reduce_logp": True}
        assert context["previous_campaigns"][0]["metrics"]["failure_reason"] == "mutation_exhausted"
        assert context["previous_report_recommendations"]["next_round_recommendations"] == [
            {"action": "reduce_logp"}
        ]
        assert context["previous_advisor_suggestion"]["summary"] == "Keep the active scaffold"


def test_strategy_validator_disables_an_invented_binding_site_id():
    validated = StrategyValidator().validate_and_fix(
        {
            "campaign_config": {
                "crem": {"enabled": True, "num_molecules": 10},
                "targetdiff": {
                    "enabled": True,
                    "num_molecules": 10,
                    "binding_site_id": "SITE-INVENTED",
                },
                "autogrow4": {"enabled": False, "num_molecules": 0},
            }
        },
        tool_availability={"crem": True, "targetdiff": True},
        data_context={
            "active_binding_site_id": "SITE-REAL",
            "available_binding_site_ids": ["SITE-REAL"],
            "data_summary": {"seed_ligand_count": 1, "binding_site_count": 1},
        },
    )

    assert validated["campaign_config"]["targetdiff"]["enabled"] is False
    assert validated["campaign_config"]["targetdiff"]["binding_site_id"] is None
    assert any("SITE-INVENTED" in warning for warning in validated["warnings"])


def test_strategy_validator_clears_legacy_targetdiff_pocket_resource_id():
    validated = StrategyValidator().validate_and_fix(
        {
            "campaign_config": {
                "crem": {"enabled": False},
                "targetdiff": {
                    "enabled": True,
                    "num_molecules": 10,
                    "pocket_resource_id": "POCKET-LEGACY",
                    "binding_site_id": "SITE-REAL",
                },
                "autogrow4": {"enabled": False},
            }
        },
        tool_availability={"targetdiff": True},
        data_context={
            "active_binding_site_id": "SITE-REAL",
            "available_binding_site_ids": ["SITE-REAL"],
            "data_summary": {"binding_site_count": 1},
        },
    )

    assert validated["campaign_config"]["targetdiff"]["enabled"] is True
    assert validated["campaign_config"]["targetdiff"]["pocket_resource_id"] is None


def test_strategy_validator_disables_campaign_with_zero_requested_molecules():
    validated = StrategyValidator().validate_and_fix(
        {
            "campaign_config": {
                "crem": {"enabled": True, "num_molecules": 0},
                "targetdiff": {
                    "enabled": True,
                    "num_molecules": 10,
                    "binding_site_id": "SITE-REAL",
                },
                "autogrow4": {"enabled": False, "num_molecules": 0},
            }
        },
        tool_availability={"crem": True, "targetdiff": True},
        data_context={
            "active_binding_site_id": "SITE-REAL",
            "available_binding_site_ids": ["SITE-REAL"],
            "data_summary": {"seed_ligand_count": 1, "binding_site_count": 1},
        },
    )

    assert validated["campaign_config"]["crem"]["num_molecules"] == 0
    assert validated["campaign_config"]["crem"]["enabled"] is False
    assert any("CReM 生成数量为 0" in warning for warning in validated["warnings"])


def test_strategy_validator_clamps_values_and_keeps_ranked_explicit_seed_order():
    validated = StrategyValidator().validate_and_fix(
        {
            "objective": "test",
            "campaign_config": {
                "crem": {"enabled": True, "num_molecules": 9999, "edit_depth": 99},
                "targetdiff": {"enabled": False},
                "autogrow4": {"enabled": False},
            },
            "seed_policy": {
                "source": "top_from_previous",
                "top_n": 99,
                "molecule_ids": ["MOL-3", "UNKNOWN", "MOL-1"],
            },
            "assessment_config": {
                "mode": "external_top_n",
                "top_n": 999,
                "skip_docking": "true",
            },
        },
        tool_availability={"crem": True},
        data_context={
            "data_summary": {"seed_ligand_count": 1},
            "previous_ranked_molecule_ids": ["MOL-1", "MOL-2", "MOL-3"],
        },
    )

    assert validated["campaign_config"]["crem"]["num_molecules"] == 500
    assert validated["campaign_config"]["crem"]["edit_depth"] == 5
    assert validated["seed_policy"]["top_n"] == 50
    assert validated["seed_policy"]["molecule_ids"] == ["MOL-3", "MOL-1"]
    assert validated["assessment_config"]["top_n"] == 200
    assert validated["assessment_config"]["skip_docking"] is True


def test_campaign_and_generated_molecule_persist_lineage():
    with make_session() as db:
        project = Project(project_id="PROJ-1", name="Lineage", objective="test")
        round_obj = ProjectRound(
            round_id="ROUND-1",
            project_id=project.project_id,
            round_number=1,
            status="draft",
        )
        db.add_all([project, round_obj])
        db.flush()

        orchestrator = RoundOrchestrator(SimpleNamespace())
        campaign = orchestrator._create_campaign_run(
            db,
            project,
            round_obj,
            "crem",
            {"num_molecules": 1},
            ["SEED-2", "SEED-1", "SEED-2"],
        )
        result = SimpleNamespace(
            agent="crem",
            molecules=[
                SimpleNamespace(
                    smiles="CCN",
                    provenance={"method": "crem_fragment_mutation"},
                    metadata={"labels": ["generated"]},
                    rationale="single mutation",
                )
            ],
        )

        molecule_ids = orchestrator._store_agent_molecules(
            db, project, result, round_obj.round_id, campaign
        )
        molecule = db.query(Molecule).filter_by(molecule_id=molecule_ids[0]).one()

        assert campaign.input_molecule_ids == ["SEED-2", "SEED-1"]
        assert molecule.campaign_run_id == campaign.campaign_run_id
        assert molecule.generation_method == "crem_fragment_mutation"
        assert molecule.parent_molecule_ids == ["SEED-2", "SEED-1"]
        assert molecule.provenance_json["round_id"] == round_obj.round_id
        assert molecule.generation_metadata_json["rationale"] == "single mutation"
        properties = db.query(MoleculeProperty).filter_by(molecule_id=molecule.molecule_id).one()
        assert molecule.status == "structure_validated"
        assert properties.mw is not None
        assert properties.logp is not None
        assert properties.tpsa is not None


def test_explicit_seed_selection_preserves_user_order():
    with make_session() as db:
        project = Project(project_id="PROJ-1", name="Seeds", objective="test")
        parent_round = ProjectRound(
            round_id="ROUND-1",
            project_id=project.project_id,
            round_number=1,
            status="completed",
        )
        next_round = ProjectRound(
            round_id="ROUND-2",
            project_id=project.project_id,
            round_number=2,
            status="ready",
            parent_round_id=parent_round.round_id,
        )
        molecules = [
            Molecule(
                molecule_id="MOL-1",
                project_id=project.project_id,
                round_id=parent_round.round_id,
                smiles="CCO",
            ),
            Molecule(
                molecule_id="MOL-2",
                project_id=project.project_id,
                round_id=parent_round.round_id,
                smiles="CCN",
            ),
        ]
        db.add_all([project, parent_round, next_round, *molecules])
        db.flush()

        smiles, molecule_ids = _prepare_seed_selection(
            db,
            project,
            next_round,
            {
                "seed_policy": {
                    "source": "top_from_previous",
                    "molecule_ids": ["MOL-2", "MOL-1"],
                }
            },
        )

        assert molecule_ids == ["MOL-2", "MOL-1"]
        assert smiles == ["CCN", "CCO"]


def test_round_report_is_persisted_once_and_refreshed():
    with make_session() as db:
        project = Project(project_id="PROJ-1", name="Report", objective="test")
        round_obj = ProjectRound(
            round_id="ROUND-1",
            project_id=project.project_id,
            round_number=1,
            status="completed",
        )
        db.add_all([project, round_obj])
        db.flush()

        orchestrator = RoundOrchestrator(SimpleNamespace())
        first = orchestrator._persist_round_report(db, project, round_obj)
        second = orchestrator._persist_round_report(db, project, round_obj)

        assert first.report_id == second.report_id
        assert db.query(RoundReport).filter_by(round_id=round_obj.round_id).count() == 1
        assert second.report_json["round_summary"]["round_id"] == round_obj.round_id


def test_round_report_excludes_other_round_assessments_and_orders_top_rankings():
    with make_session() as db:
        project = Project(project_id="PROJ-REPORT", name="Round report", objective="test")
        parent_round = ProjectRound(
            round_id="ROUND-PARENT",
            project_id=project.project_id,
            round_number=1,
            status="completed",
        )
        current_round = ProjectRound(
            round_id="ROUND-CURRENT",
            project_id=project.project_id,
            round_number=2,
            status="completed",
            parent_round_id=parent_round.round_id,
        )
        molecule = Molecule(
            molecule_id="MOL-REPORT-SCOPED",
            project_id=project.project_id,
            round_id=current_round.round_id,
            smiles="CCO",
        )
        db.add_all([project, parent_round, current_round, molecule])
        db.flush()
        db.add_all([
            DockingResult(
                molecule_id=molecule.molecule_id,
                round_id=parent_round.round_id,
                vina_score=-5.0,
            ),
            DockingResult(
                molecule_id=molecule.molecule_id,
                round_id=current_round.round_id,
                vina_score=-8.0,
                cnn_score=0.72,
                key_hbond_count=2,
                clash_count=0,
                pose_file="C:/poses/MOL-REPORT-SCOPED.sdf",
                raw_output={
                    "selected_pose_rank": 1,
                    "pose_count": 9,
                    "pose_selection_method": "gnina_best_affinity",
                    "best_pose_confirmed": True,
                    "pose_interactions_computed": True,
                    "pose_interactions": {
                        "computed": True,
                        "hbond_count": 3,
                        "key_hbond_count": 2,
                        "clash_count": 0,
                        "key_residue_interactions": [{"residue": "CYS532"}],
                    },
                },
            ),
            ADMETResult(
                molecule_id=molecule.molecule_id,
                round_id=parent_round.round_id,
                hERG_risk="low",
            ),
            ADMETResult(
                molecule_id=molecule.molecule_id,
                round_id=current_round.round_id,
                hERG_risk="high",
            ),
            SynthesisRoute(
                molecule_id=molecule.molecule_id,
                round_id=parent_round.round_id,
                route_found=False,
            ),
            SynthesisRoute(
                molecule_id=molecule.molecule_id,
                round_id=current_round.round_id,
                route_found=True,
            ),
            Ranking(
                project_id=project.project_id,
                molecule_id=molecule.molecule_id,
                round_id=current_round.round_id,
                rank=2,
                overall_score=0.2,
                final_decision="hold",
            ),
            Ranking(
                project_id=project.project_id,
                molecule_id="MOL-CURRENT-TOP",
                round_id=current_round.round_id,
                rank=1,
                overall_score=0.9,
                final_decision="advance",
            ),
            Ranking(
                project_id=project.project_id,
                molecule_id=molecule.molecule_id,
                round_id=parent_round.round_id,
                rank=2,
                overall_score=0.1,
                final_decision="hold",
            ),
            Ranking(
                project_id=project.project_id,
                molecule_id="MOL-PARENT-TOP",
                round_id=parent_round.round_id,
                rank=1,
                overall_score=0.5,
                final_decision="advance",
            ),
        ])
        db.flush()

        report = build_round_report(db, project, current_round)

        assert report["assessment"] == {
            "docking_count": 1,
            "admet_count": 1,
            "synthesis_count": 1,
        }
        assert report["docking_distribution"] == {
            "count": 1,
            "min": -8.0,
            "max": -8.0,
            "mean": -8.0,
            "median": -8.0,
        }
        assert report["admet_distribution"] == {
            "low": 0,
            "medium": 0,
            "high": 1,
            "unknown": 0,
        }
        assert report["comparison_with_previous"]["current_top_score"] == 0.9
        assert report["comparison_with_previous"]["parent_top_score"] == 0.5
        assert report["comparison_with_previous"]["score_improvement"] == 0.4
        docking = report["ranking"]["top_10"][1]["docking"]
        assert docking["pose_interactions_computed"] is True
        assert docking["pose_interactions"]["key_residue_interactions"] == [
            {"residue": "CYS532"}
        ]


def test_next_round_auto_strategy_stays_ready_for_user_confirmation(monkeypatch):
    import medagent.llm.client as llm_module

    monkeypatch.setattr(llm_module, "get_llm_client", lambda: FailingLLMClient())

    with make_session() as db:
        project = Project(project_id="PROJ-1", name="Next round", objective="test")
        parent_round = ProjectRound(
            round_id="ROUND-1",
            project_id=project.project_id,
            round_number=1,
            status="completed",
        )
        molecule = Molecule(
            molecule_id="MOL-1",
            project_id=project.project_id,
            round_id=parent_round.round_id,
            smiles="CCO",
        )
        ranking = Ranking(
            project_id=project.project_id,
            molecule_id=molecule.molecule_id,
            round_id=parent_round.round_id,
            rank=1,
            overall_score=0.9,
            final_decision="advance",
        )
        db.add_all([project, parent_round, molecule, ranking])
        db.flush()

        orchestrator = RoundOrchestrator(SimpleNamespace())
        monkeypatch.setattr(
            orchestrator,
            "_detect_tool_availability",
            lambda: {"crem": True, "targetdiff": False, "autogrow4": False},
        )
        next_round = orchestrator.create_round_draft(
            db,
            project,
            round_number=2,
            parent_round_id=parent_round.round_id,
            auto_generate_strategy=True,
        )

        strategy = next_round.user_conditions_json["strategy_draft"]
        audit = db.query(AgentRun).filter_by(
            round_id=next_round.round_id,
            agent_name="round_strategy_agent",
        ).one()
        assert next_round.status == "ready"
        assert strategy["requires_user_confirmation"] is True
        assert strategy["seed_policy"]["molecule_ids"] == ["MOL-1"]
        assert strategy["planner_metadata"]["mode"] == "deterministic_fallback"
        assert audit.model_name == "deterministic_fallback"
        assert audit.status == "completed_with_fallback"
