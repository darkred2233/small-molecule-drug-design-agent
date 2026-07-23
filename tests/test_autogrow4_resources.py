from medagent.core.config import Settings
from medagent.db.models import Base, BindingSite, Molecule, Project, ProjectRound, DockingResult
from medagent.db.session import build_engine, build_session_factory
from medagent.domain.schemas import AutoGrow4CampaignConfig
from medagent.services.autogrow4_resources import resolve_autogrow4_resources


def test_autogrow4_uses_prepared_pdbqt_and_previous_vina_top_molecules(tmp_path, monkeypatch):
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'test.db'}")
    engine = build_engine(settings)
    Base.metadata.create_all(bind=engine)
    session_factory = build_session_factory(settings)
    monkeypatch.chdir(tmp_path)
    receptor = tmp_path / "prepared_braf.pdbqt"
    receptor.write_text("REMARK  test\nATOM      1  N   MET A   1       0.0   0.0   0.0\n", encoding="utf-8")

    with session_factory() as db:
        project = Project(project_id="PROJ-AUTOGROW-RESOURCES", name="AutoGrow resources")
        db.add_all(
            [
                project,
                BindingSite(
                    binding_site_id="SITE-UPLOADED",
                    project_id=project.project_id,
                    target_id="TGT-BRAF",
                    receptor_file="local://missing.pdb",
                    preparation_status="uploaded",
                    grid_box={},
                ),
                BindingSite(
                    binding_site_id="SITE-PREPARED",
                    project_id=project.project_id,
                    target_id="TGT-BRAF",
                    receptor_file="local://missing.pdb",
                    prepared_receptor_file=f"local://{receptor}",
                    preparation_status="prepared",
                    grid_box={
                        "center": [2.6, -2.3, -19.4],
                        "size": [28.3, 18.0, 18.4],
                    },
                ),
            ]
        )
        previous_round = ProjectRound(
            round_id="ROUND-1", project_id=project.project_id, round_number=1, status="completed"
        )
        current_round = ProjectRound(
            round_id="ROUND-2", project_id=project.project_id, round_number=2, status="draft"
        )
        db.add_all([previous_round, current_round])
        db.add_all([
            Molecule(molecule_id="MOL-TOP", project_id=project.project_id, round_id=previous_round.round_id, smiles="CCO"),
            Molecule(molecule_id="MOL-LOW", project_id=project.project_id, round_id=previous_round.round_id, smiles="CCN"),
        ])
        db.flush()
        db.add_all([
            DockingResult(molecule_id="MOL-TOP", round_id=previous_round.round_id, vina_score=-9.0),
            DockingResult(molecule_id="MOL-LOW", round_id=previous_round.round_id, vina_score=-7.0),
        ])
        db.commit()

        bundle = resolve_autogrow4_resources(
            db,
            project,
            AutoGrow4CampaignConfig(
                source_pool_policy="previous_top", previous_top_n=1, binding_site_id="SITE-PREPARED"
            ),
        )

    assert bundle.receptor_file == str(receptor)
    assert bundle.prepared_receptor_file == str(receptor)
    assert bundle.binding_site_id == "SITE-PREPARED"
    assert bundle.grid_center == [2.6, -2.3, -19.4]
    assert bundle.grid_size == [28.3, 18.0, 18.4]
    assert (tmp_path / bundle.source_compounds_file).read_text(encoding="utf-8") == "CCO\tMOL-TOP\n"
