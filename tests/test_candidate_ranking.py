from medagent.core.config import Settings
from medagent.db.models import (
    ADMETResult,
    Base,
    DockingResult,
    Molecule,
    MoleculeProperty,
    Project,
    Ranking,
    RuleFilterResult,
    SynthesisRoute,
)
from medagent.db.session import build_engine, build_session_factory
from medagent.services.candidate_ranking import generate_project_rankings


def test_external_refined_candidates_rank_ahead_of_coarse_only_candidates(tmp_path):
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'test.db'}")
    engine = build_engine(settings)
    Base.metadata.create_all(bind=engine)
    session_factory = build_session_factory(settings)

    with session_factory() as db:
        project = Project(project_id="PROJ-RANKING", name="Ranking")
        refined = Molecule(
            molecule_id="MOL-REFINED",
            project_id=project.project_id,
            smiles="CCO",
            status="candidate_assessed",
            labels=[
                "coarse_screen_passed",
                "external_refinement_attempted",
                "externally_refined_candidate",
            ],
        )
        coarse_only = Molecule(
            molecule_id="MOL-COARSE",
            project_id=project.project_id,
            smiles="Cc1ccccc1",
            status="candidate_assessed",
            labels=["coarse_screen_passed", "coarse_only_candidate"],
        )
        db.add_all([project, refined, coarse_only])
        db.flush()

        _add_supporting_evidence(
            db,
            project.project_id,
            molecule_id=refined.molecule_id,
            docking_labels=["external_docking_adapter_used", "gnina_adapter"],
            vina_score=-4.2,
            cnn_score=0.42,
            admet_risk=0.15,
            route_confidence=0.55,
            route_labels=["external_retrosynthesis_adapter_used", "aizynthfinder_route"],
        )
        _add_supporting_evidence(
            db,
            project.project_id,
            molecule_id=coarse_only.molecule_id,
            docking_labels=["external_docking_adapter_pending", "rdkit_surrogate_docking"],
            vina_score=-10.0,
            cnn_score=0.95,
            admet_risk=0.03,
            route_confidence=0.94,
            route_labels=["external_retrosynthesis_adapter_pending", "rdkit_surrogate_synthesis"],
        )
        db.commit()

        summary = generate_project_rankings(
            db,
            project,
            molecules=[refined, coarse_only],
            top_n=2,
        )

        rankings = {ranking.molecule_id: ranking for ranking in db.query(Ranking).all()}
        assert summary.molecule_ids == ["MOL-REFINED", "MOL-COARSE"]
        assert rankings["MOL-REFINED"].rank == 1
        assert rankings["MOL-REFINED"].score_breakdown["refinement"]["state"] == "externally_refined"
        assert rankings["MOL-COARSE"].score_breakdown["refinement"]["state"] == "coarse_only"
        assert rankings["MOL-COARSE"].score_breakdown["refinement"]["provisional_penalty"] == 40.0


def _add_supporting_evidence(
    db,
    project_id: str,
    *,
    molecule_id: str,
    docking_labels: list[str],
    vina_score: float,
    cnn_score: float,
    admet_risk: float,
    route_confidence: float,
    route_labels: list[str],
) -> None:
    db.add(
        MoleculeProperty(
            molecule_id=molecule_id,
            mw=220.0,
            logp=2.2,
            tpsa=52.0,
            hbd=1,
            hba=3,
            sa_score=2.5,
        )
    )
    db.add(
        RuleFilterResult(
            filter_result_id=f"RULE-{molecule_id}",
            project_id=project_id,
            molecule_id=molecule_id,
            rule_set="target_aware_drug_likeness_v2",
            decision="passed",
            labels=["rule_filter_passed"],
        )
    )
    db.add(
        DockingResult(
            molecule_id=molecule_id,
            vina_score=vina_score,
            cnn_score=cnn_score,
            key_hbond_count=2,
            clash_count=0,
            labels=docking_labels,
        )
    )
    db.add(
        ADMETResult(
            molecule_id=molecule_id,
            hERG_probability=admet_risk,
            hERG_risk="low_risk",
            Ames_probability=admet_risk,
            Ames_risk="low_risk",
            solubility="medium",
            permeability="high",
            admet_risk_score=admet_risk,
            labels=["admet_clean"],
        )
    )
    db.add(
        SynthesisRoute(
            molecule_id=molecule_id,
            route_found=True,
            route_steps=3,
            route_confidence=route_confidence,
            buyable_building_blocks=2,
            labels=route_labels,
            route_json={"hazardous_reaction_count": 0},
        )
    )
