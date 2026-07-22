from medagent.core.config import Settings
from medagent.db.models import Base, BindingSite, Project
from medagent.db.session import build_engine, build_session_factory
from medagent.domain.schemas import AutoGrow4CampaignConfig
from medagent.services.autogrow4_resources import _resolve_receptor_and_grid


def test_autogrow4_resource_resolution_prefers_prepared_site_with_valid_grid(tmp_path):
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'test.db'}")
    engine = build_engine(settings)
    Base.metadata.create_all(bind=engine)
    session_factory = build_session_factory(settings)
    receptor = tmp_path / "prepared_braf.pdb"
    receptor.write_text("HEADER BRAF\n", encoding="utf-8")

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
                    receptor_file=f"local://{receptor}",
                    preparation_status="prepared",
                    grid_box={
                        "center": [2.6, -2.3, -19.4],
                        "size": [28.3, 18.0, 18.4],
                    },
                ),
            ]
        )
        db.flush()

        receptor_file, center, size, binding_site_id = _resolve_receptor_and_grid(
            db,
            project,
            AutoGrow4CampaignConfig(),
        )

    assert receptor_file == str(receptor)
    assert binding_site_id == "SITE-PREPARED"
    assert center == [2.6, -2.3, -19.4]
    assert size == [28.3, 18.0, 18.4]
