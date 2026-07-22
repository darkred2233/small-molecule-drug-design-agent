from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from medagent.agents.round_strategy import RoundStrategyAgent
from medagent.api.rounds_router import _prepare_seed_selection
from medagent.db.models import (
    ADMETResult,
    Base,
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
from medagent.services.strategy_validator import StrategyValidator


class FailingLLMClient:
    def generate_structured(self, **kwargs):
        raise ValueError("provider unavailable")


def make_session() -> Session:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return Session(engine)


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
            "reinvent4": False,
            "autogrow4": False,
        },
    )

    assert strategy["campaign_config"]["crem"]["enabled"] is True
    assert strategy["campaign_config"]["reinvent4"]["enabled"] is False
    assert strategy["seed_policy"]["molecule_ids"] == ["MOL-2", "MOL-1", "MOL-3"]
    assert strategy["requires_user_confirmation"] is True
    assert any("deterministic fallback" in warning for warning in strategy["warnings"])


def test_strategy_validator_clamps_values_and_keeps_ranked_explicit_seed_order():
    validated = StrategyValidator().validate_and_fix(
        {
            "objective": "test",
            "campaign_config": {
                "crem": {"enabled": True, "num_molecules": 9999, "edit_depth": 99},
                "reinvent4": {"enabled": False},
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
            lambda: {"crem": True, "reinvent4": False, "autogrow4": False},
        )
        next_round = orchestrator.create_round_draft(
            db,
            project,
            round_number=2,
            parent_round_id=parent_round.round_id,
            auto_generate_strategy=True,
        )

        strategy = next_round.user_conditions_json["strategy_draft"]
        assert next_round.status == "ready"
        assert strategy["requires_user_confirmation"] is True
        assert strategy["seed_policy"]["molecule_ids"] == ["MOL-1"]
