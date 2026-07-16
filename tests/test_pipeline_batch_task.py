from medagent.core.config import Settings
from medagent.db.models import Base, Molecule, MoleculeProperty, Project, RuleFilterResult
from medagent.db.session import build_engine, build_session_factory
from medagent.pipeline.tasks import batch_molecule_task


def test_batch_molecule_task_validates_filters_and_deletes(tmp_path):
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'test.db'}")
    engine = build_engine(settings)
    Base.metadata.create_all(bind=engine)
    session_factory = build_session_factory(settings)

    with session_factory() as db:
        project = Project(project_id="PROJ-BATCH", name="Batch project")
        molecule = Molecule(
            molecule_id="MOL-BATCH",
            project_id=project.project_id,
            smiles="CCO",
            status="generated",
            labels=[],
        )
        db.add_all([project, molecule])
        db.commit()

        validation = batch_molecule_task(db, project, [molecule.molecule_id], "validate")
        assert validation["succeeded"] == 1
        assert validation["failed"] == 0
        assert molecule.status == "structure_validated"
        assert (
            db.query(MoleculeProperty)
            .filter_by(molecule_id=molecule.molecule_id)
            .one_or_none()
            is not None
        )

        filtering = batch_molecule_task(db, project, [molecule.molecule_id], "filter")
        assert filtering["succeeded"] == 1
        assert filtering["failed"] == 0
        assert molecule.status in {"passed_filter", "failed_filter", "structure_validated"}
        assert (
            db.query(RuleFilterResult)
            .filter_by(molecule_id=molecule.molecule_id)
            .one_or_none()
            is not None
        )

        deletion = batch_molecule_task(db, project, [molecule.molecule_id], "delete")
        assert deletion["succeeded"] == 1
        assert deletion["failed"] == 0
        assert db.query(Molecule).filter_by(molecule_id=molecule.molecule_id).one_or_none() is None
