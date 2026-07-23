from medagent.core.config import Settings
from medagent.db.models import Base, BindingSite, Project
from medagent.db.session import build_engine, build_session_factory
from medagent.domain.schemas import TargetDiffCampaignConfig
from medagent.services.targetdiff_resources import resolve_targetdiff_resources


def test_targetdiff_uses_predicted_pocket_artifact_not_the_full_receptor(tmp_path):
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'test.db'}")
    engine = build_engine(settings)
    Base.metadata.create_all(bind=engine)
    session_factory = build_session_factory(settings)
    pocket = tmp_path / "pocket.pdb"
    pocket.write_text("ATOM      1  N   MET A   1       0.0   0.0   0.0\n", encoding="utf-8")

    with session_factory() as db:
        project = Project(project_id="PROJ-TARGETDIFF", name="TargetDiff", target_id="TGT-EGFR")
        site = BindingSite(
            binding_site_id="SITE-P2RANK",
            project_id=project.project_id,
            target_id="TGT-EGFR",
            receptor_file="local://full_receptor.pdb",
            preparation_status="pocket_predicted",
            grid_box={"pocket_file": f"local://{pocket}"},
        )
        db.add_all([project, site])
        db.commit()

        bundle = resolve_targetdiff_resources(
            db, project, TargetDiffCampaignConfig(binding_site_id=site.binding_site_id)
        )

    assert bundle.pocket_file == str(pocket)
    assert bundle.binding_site_id == "SITE-P2RANK"
    assert bundle.provenance["input_status"] == "predicted_not_experimentally_validated"
