from fastapi.testclient import TestClient

import medagent.api.app as api_app
from medagent.api.app import create_app
from medagent.core.config import Settings
from medagent.db.models import Base, Molecule, MoleculeProperty, Project
from medagent.db.session import build_engine, build_session_factory
from medagent.services.molecule_validation import (
    backfill_project_molecule_properties,
    validate_smiles_lightweight,
)


def make_client(tmp_path):
    app = create_app(
        Settings(
            database_url=f"sqlite:///{tmp_path / 'test.db'}",
            storage_local_root=str(tmp_path / "uploads"),
        )
    )
    return TestClient(app)


def create_project_with_molecules(client: TestClient) -> str:
    project = client.post(
        "/projects",
        json={"name": "Molecule validation"},
    ).json()
    project_id = project["project_id"]
    client.post(
        f"/projects/{project_id}/files",
        files={
            "file": (
                "validation.smi",
                b"CCO ethanol\nC1CC unclosed_ring\nC(C unclosed_branch\n",
                "text/plain",
            )
        },
    )
    client.post(f"/projects/{project_id}/ingest")
    client.post(f"/projects/{project_id}/molecules/import-seeds")
    return project_id


def test_validate_molecules_writes_properties_and_updates_status(tmp_path):
    with make_client(tmp_path) as client:
        project_id = create_project_with_molecules(client)

        validate_response = client.post(f"/projects/{project_id}/molecules/validate")

        assert validate_response.status_code == 200
        summary = validate_response.json()
        assert summary["validated_count"] == 1
        assert summary["invalid_count"] == 0
        assert summary["property_count"] == 1

        molecules = client.get(f"/projects/{project_id}/molecules").json()
        by_smiles = {molecule["smiles"]: molecule for molecule in molecules}
        assert by_smiles["CCO"]["status"] == "structure_validated"
        assert set(by_smiles["CCO"]["labels"]) & {"light_validation_passed", "rdkit_validation_passed"}
        assert "C1CC" not in by_smiles
        assert "C(C" not in by_smiles

        properties_response = client.get(
            f"/projects/{project_id}/molecules/{by_smiles['CCO']['molecule_id']}/properties"
        )
        assert properties_response.status_code == 200
        properties = properties_response.json()
        assert properties["molecule_id"] == by_smiles["CCO"]["molecule_id"]
        assert properties["mw"] > 30
        assert properties["tool_metadata"]["validator"] in {"lightweight_smiles_validator", "rdkit"}
        assert properties["tool_metadata"]["heavy_atom_count"] == 3
        assert properties["tool_metadata"].get("rotatable_bond_count") is not None
        if properties["tool_metadata"]["validator"] == "rdkit":
            assert 0 <= properties["tool_metadata"]["qed"] <= 1


def test_validate_molecules_is_idempotent(tmp_path):
    with make_client(tmp_path) as client:
        project_id = create_project_with_molecules(client)
        first = client.post(f"/projects/{project_id}/molecules/validate").json()
        second = client.post(f"/projects/{project_id}/molecules/validate").json()

        assert first["property_count"] == 1
        assert second["property_count"] == 1

        valid_molecule = next(
            molecule
            for molecule in client.get(f"/projects/{project_id}/molecules").json()
            if molecule["smiles"] == "CCO"
        )
        properties = client.get(
            f"/projects/{project_id}/molecules/{valid_molecule['molecule_id']}/properties"
        ).json()
        assert properties["tool_metadata"]["validation_run_count"] == 3


def test_properties_endpoint_backfills_missing_qed_metadata(tmp_path):
    with make_client(tmp_path) as client:
        project_id = create_project_with_molecules(client)
        assert client.post(f"/projects/{project_id}/molecules/validate").status_code == 200

        valid_molecule = next(
            molecule
            for molecule in client.get(f"/projects/{project_id}/molecules").json()
            if molecule["smiles"] == "CCO"
        )
        with api_app.SessionLocal() as db:
            properties = db.query(MoleculeProperty).filter_by(
                molecule_id=valid_molecule["molecule_id"]
            ).one()
            metadata = dict(properties.tool_metadata or {})
            metadata.pop("qed", None)
            properties.tool_metadata = metadata
            db.commit()

        properties = client.get(
            f"/projects/{project_id}/molecules/{valid_molecule['molecule_id']}/properties"
        ).json()

        assert properties["tool_metadata"]["rotatable_bond_count"] == 0
        assert 0 <= properties["tool_metadata"]["qed"] <= 1


def test_lightweight_validation_rejects_unsupported_atom_tokens():
    result = validate_smiles_lightweight("XYZ")

    assert result.valid is False
    assert "unsupported_atom_tokens" in result.labels


def test_property_backfill_preserves_existing_workflow_status(tmp_path):
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'backfill.db'}")
    engine = build_engine(settings)
    Base.metadata.create_all(bind=engine)
    session_factory = build_session_factory(settings)

    with session_factory() as db:
        project = Project(project_id="PROJ-BACKFILL", name="Backfill")
        molecule = Molecule(
            molecule_id="MOL-BACKFILL",
            project_id=project.project_id,
            smiles="CCOc1ccccc1",
            status="candidate_assessed",
            labels=["external_docking_adapter_used"],
        )
        db.add_all([project, molecule])
        db.commit()

        summary = backfill_project_molecule_properties(db, project)
        properties = db.query(MoleculeProperty).filter_by(molecule_id=molecule.molecule_id).one()

        assert summary["backfilled_count"] == 1
        assert properties.mw is not None
        assert properties.logp is not None
        assert molecule.status == "candidate_assessed"
        assert "external_docking_adapter_used" in molecule.labels
