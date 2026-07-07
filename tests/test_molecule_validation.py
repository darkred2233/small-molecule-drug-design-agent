from fastapi.testclient import TestClient

from medagent.api.app import create_app
from medagent.core.config import Settings
from medagent.services.molecule_validation import validate_smiles_lightweight


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
        json={"name": "Molecule validation", "target_id": "TGT-EGFR"},
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
        assert summary["invalid_count"] == 2
        assert summary["property_count"] == 1

        molecules = client.get(f"/projects/{project_id}/molecules").json()
        by_smiles = {molecule["smiles"]: molecule for molecule in molecules}
        assert by_smiles["CCO"]["status"] == "structure_validated"
        assert "light_validation_passed" in by_smiles["CCO"]["labels"]
        assert "needs_rdkit_validation" in by_smiles["CCO"]["labels"]
        assert by_smiles["C1CC"]["status"] == "invalid_structure"
        assert by_smiles["C(C"]["status"] == "invalid_structure"

        properties_response = client.get(
            f"/projects/{project_id}/molecules/{by_smiles['CCO']['molecule_id']}/properties"
        )
        assert properties_response.status_code == 200
        properties = properties_response.json()
        assert properties["molecule_id"] == by_smiles["CCO"]["molecule_id"]
        assert properties["mw"] > 30
        assert properties["tool_metadata"]["validator"] == "lightweight_smiles_validator"
        assert properties["tool_metadata"]["heavy_atom_count"] == 3


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
        assert properties["tool_metadata"]["validation_run_count"] == 2


def test_lightweight_validation_rejects_unsupported_atom_tokens():
    result = validate_smiles_lightweight("XYZ")

    assert result.valid is False
    assert "unsupported_atom_tokens" in result.labels
