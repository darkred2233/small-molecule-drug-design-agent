from medagent.agents.ranker import MoleculeScore, RankingResult
from medagent.agents.report import ReportAgent
from medagent.core.config import Settings
from medagent.db.models import (
    ADMETResult,
    Base,
    Critique,
    DockingResult,
    Molecule,
    MoleculeProperty,
    Project,
    SynthesisRoute,
)
from medagent.db.session import build_engine, build_session_factory


def test_report_agent_uses_current_models_and_critiques(tmp_path):
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'test.db'}")
    engine = build_engine(settings)
    Base.metadata.create_all(bind=engine)
    session_factory = build_session_factory(settings)

    with session_factory() as db:
        pose_file = tmp_path / "pose.sdf"
        pose_file.write_text("pose\n$$$$\n", encoding="utf-8")
        project = Project(
            project_id="PROJ-REPORT",
            name="Report project",
            target_id="TGT-REPORT",
            objective="oncology",
        )
        molecule = Molecule(
            molecule_id="MOL-REPORT",
            project_id=project.project_id,
            smiles="CCO",
            status="candidate_assessed",
            labels=[],
        )
        db.add_all(
            [
                project,
                molecule,
                MoleculeProperty(
                    molecule_id=molecule.molecule_id,
                    mw=46.07,
                    logp=0.1,
                    tpsa=20.2,
                    hbd=1,
                    hba=1,
                    sa_score=1.2,
                    tool_metadata={"rotatable_bond_count": 0, "qed": 0.42},
                ),
                ADMETResult(
                    molecule_id=molecule.molecule_id,
                    hERG_probability=0.12,
                    hERG_risk="low_risk",
                    Ames_probability=0.08,
                    Ames_risk="low_risk",
                    solubility="high",
                    permeability="medium",
                    admet_risk_score=0.1,
                    labels=["admet_clean"],
                    raw_output={"CYP3A4_risk": "low_risk", "DILI_risk": "medium_risk"},
                ),
                DockingResult(
                    molecule_id=molecule.molecule_id,
                    tool_run_id="DOCK-1",
                    vina_score=-8.1,
                    cnn_score=0.73,
                    key_hbond_count=1,
                    clash_count=0,
                    pose_file=str(pose_file),
                    labels=["pose_confident"],
                    raw_output={
                        "selected_pose_rank": 1,
                        "pose_count": 9,
                        "pose_selection_method": "gnina_output_mode_1",
                    },
                ),
                SynthesisRoute(
                    molecule_id=molecule.molecule_id,
                    route_found=True,
                    route_steps=3,
                    route_confidence=0.8,
                    buyable_building_blocks=2,
                    labels=["route_found"],
                    route_json={"sa_score": 1.2, "complexity_level": "easy"},
                ),
                Critique(
                    critique_id="CRT-REPORT",
                    molecule_id=molecule.molecule_id,
                    con_score=38.0,
                    risk_level="medium",
                    reason="Needs ADMET confirmation.",
                    evidence_ids=["DB:MOL:MOL-REPORT"],
                    refutation_decision="reserve",
                    analysis_method="llm_assisted_self_refutation",
                    llm_critique_json={
                        "hidden_risks": ["metabolic liability"],
                        "evidence_concerns": ["surrogate model only"],
                        "verdict": {"risk_adjustment": "maintain"},
                    },
                    llm_provider="deepseek",
                ),
            ]
        )
        db.commit()

        ranking_result = RankingResult(
            project_id=project.project_id,
            total_molecules=1,
            ranked_molecules=[
                MoleculeScore(
                    molecule_id=molecule.molecule_id,
                    structure_score=90,
                    admet_score=80,
                    docking_score=75,
                    synthesis_score=85,
                    weighted_score=82,
                    final_score=82,
                    rank=1,
                    tier="excellent",
                )
            ],
            excellent_count=1,
        )

        report = ReportAgent(db).generate_report(project, ranking_result)

        assert report.project_overview["project_name"] == "Report project"
        assert report.project_overview["target_protein"] == "TGT-REPORT"
        assert report.project_overview["disease_area"] == "oncology"
        assert len(report.detailed_molecules) == 1

        detail = report.detailed_molecules[0]
        assert detail.mol_name == "Molecule-1"
        assert detail.structure_analysis["qed"] == 0.42
        assert detail.admet_analysis["dili"]["risk"] == "medium_risk"
        assert detail.docking_analysis["tool"] == "DOCK-1"
        assert detail.docking_analysis["selected_pose_rank"] == 1
        assert detail.docking_analysis["pose_count"] == 9
        assert detail.docking_analysis["pose_selection_method"] == "gnina_output_mode_1"
        assert detail.docking_analysis["best_pose_confirmed"] is True
        assert detail.docking_analysis["pose_artifact_available"] is True
        assert detail.synthesis_analysis["num_steps"] == 3
        assert detail.refutation_summary["decision"] == "reserve"
        assert detail.refutation_summary["analysis_method"] == "llm_assisted_self_refutation"
        assert detail.refutation_summary["hidden_risks"] == ["metabolic liability"]
        assert "谨慎推荐" in detail.recommendation
