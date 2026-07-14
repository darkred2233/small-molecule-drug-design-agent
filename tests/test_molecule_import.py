from fastapi.testclient import TestClient

from medagent.api.app import create_app
from medagent.core.config import Settings


def make_client(tmp_path):
    app = create_app(
        Settings(
            database_url=f"sqlite:///{tmp_path / 'test.db'}",
            storage_local_root=str(tmp_path / "uploads"),
        )
    )
    return TestClient(app)


def create_project_with_seed_file(client: TestClient) -> str:
    project_response = client.post(
        "/projects",
        json={
            "name": "Seed molecule import",
            "objective": "import parsed seed ligands into molecule table",
        },
    )
    assert project_response.status_code == 201
    project_id = project_response.json()["project_id"]
    upload_response = client.post(
        f"/projects/{project_id}/files",
        files={
            "file": (
                "seeds.smi",
                b"CCO ethanol\nCCO ethanol_duplicate\nc1ccccc1 benzene\nnot_a_smiles invalid\n",
                "text/plain",
            )
        },
    )
    assert upload_response.status_code == 202
    ingest_response = client.post(f"/projects/{project_id}/ingest")
    assert ingest_response.status_code == 202
    return project_id


def test_seed_ligands_can_be_imported_into_molecules(tmp_path):
    with make_client(tmp_path) as client:
        project_id = create_project_with_seed_file(client)

        import_response = client.post(f"/projects/{project_id}/molecules/import-seeds")

        assert import_response.status_code == 201
        body = import_response.json()
        assert body["imported_count"] == 2
        assert body["duplicate_count"] == 1
        assert body["invalid_count"] == 1

        molecules_response = client.get(f"/projects/{project_id}/molecules")
        molecules = molecules_response.json()
        assert molecules_response.status_code == 200
        assert {item["smiles"] for item in molecules} == {"CCO", "c1ccccc1"}
        assert {item["status"] for item in molecules} == {"imported_from_seed"}
        assert all("seed_ligand" in item["labels"] for item in molecules)


def test_import_seeds_is_idempotent_and_single_molecule_can_be_read(tmp_path):
    with make_client(tmp_path) as client:
        project_id = create_project_with_seed_file(client)
        first_import = client.post(f"/projects/{project_id}/molecules/import-seeds")
        assert first_import.status_code == 201

        second_import = client.post(f"/projects/{project_id}/molecules/import-seeds")

        assert second_import.status_code == 201
        assert second_import.json()["imported_count"] == 0
        assert second_import.json()["duplicate_count"] >= 3

        molecules = client.get(f"/projects/{project_id}/molecules").json()
        molecule_id = molecules[0]["molecule_id"]
        molecule_response = client.get(f"/projects/{project_id}/molecules/{molecule_id}")

        assert molecule_response.status_code == 200
        molecule = molecule_response.json()
        assert molecule["molecule_id"] == molecule_id
        assert molecule["source_agent"] == "seed_ligand_import"
