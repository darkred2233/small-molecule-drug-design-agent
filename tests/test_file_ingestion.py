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


def create_project(
    client: TestClient,
    target_id: str | None = None,
    target_name: str | None = None,
) -> str:
    payload = {
        "name": "EGFR upload parsing",
        "target_id": target_id,
        "objective": "parse uploaded seed ligands",
    }
    if target_name is not None:
        payload["target_name"] = target_name

    response = client.post(
        "/projects",
        json=payload,
    )
    assert response.status_code == 201
    return response.json()["project_id"]


def test_upload_smiles_file_can_be_parsed_into_seed_ligands(tmp_path):
    with make_client(tmp_path) as client:
        project_id = create_project(client)
        upload_response = client.post(
            f"/projects/{project_id}/files",
            files={"file": ("seeds.smi", b"CCO ethanol\nc1ccccc1 benzene\n", "text/plain")},
        )
        assert upload_response.status_code == 202
        file_id = upload_response.json()["file_id"]

        ingest_response = client.post(f"/projects/{project_id}/ingest")

        assert ingest_response.status_code == 202
        body = ingest_response.json()
        assert body["parsed_files"] == 1
        assert body["seed_ligands_created"] == 2

        result_response = client.get(f"/projects/{project_id}/files/{file_id}/parse-result")
        result = result_response.json()
        assert result_response.status_code == 200
        assert result["parse_status"] == "parsed"
        assert result["metadata"]["record_count"] == 2
        assert result["metadata"]["seed_ligand_count"] == 2

        ligands_response = client.get(f"/projects/{project_id}/seed-ligands")
        ligands = ligands_response.json()
        assert ligands_response.status_code == 200
        assert {ligand["name"] for ligand in ligands} == {"ethanol", "benzene"}


def test_upload_csv_file_preserves_activity_values(tmp_path):
    with make_client(tmp_path) as client:
        project_id = create_project(client)
        csv_payload = (
            "name,smiles,activity_value,activity_unit\n"
            "ligand_a,CCN,12.5,nM\n"
            "ligand_b,CCCl,0.8,uM\n"
        )
        upload_response = client.post(
            f"/projects/{project_id}/files",
            files={"file": ("activity.csv", csv_payload.encode("utf-8"), "text/csv")},
        )
        assert upload_response.status_code == 202

        ingest_response = client.post(f"/projects/{project_id}/ingest")

        assert ingest_response.status_code == 202
        ligands = client.get(f"/projects/{project_id}/seed-ligands").json()
        assert [(item["name"], item["activity_value"], item["activity_unit"]) for item in ligands] == [
            ("ligand_a", 12.5, "nM"),
            ("ligand_b", 0.8, "uM"),
        ]


def test_upload_pdb_file_records_structure_summary(tmp_path):
    pdb_payload = b"""HEADER    TEST PDB\nTITLE     EGFR TEST STRUCTURE\nATOM      1  N   MET A   1      11.104  13.207  14.099  1.00 10.00           N\nATOM      2  CA  MET A   1      12.560  13.211  14.099  1.00 10.00           C\nATOM      3  N   GLY B   2      15.104  16.207  12.099  1.00 10.00           N\nEND\n"""

    with make_client(tmp_path) as client:
        project_id = create_project(client, target_id="TGT-EGFR")
        upload_response = client.post(
            f"/projects/{project_id}/files",
            files={"file": ("target.pdb", pdb_payload, "chemical/x-pdb")},
        )
        file_id = upload_response.json()["file_id"]

        ingest_response = client.post(f"/projects/{project_id}/ingest")

        assert ingest_response.status_code == 202
        result = client.get(f"/projects/{project_id}/files/{file_id}/parse-result").json()
        assert result["parse_status"] == "parsed"
        assert result["metadata"]["pdb"]["atom_count"] == 3
        assert result["metadata"]["pdb"]["chain_ids"] == ["A", "B"]
        assert result["metadata"]["binding_site_created"] is True


def test_custom_target_upload_pdb_creates_project_binding_site(tmp_path):
    pdb_payload = b"""HEADER    TEST PDB\nTITLE     MYC TEST STRUCTURE\nATOM      1  N   MET A   1      11.104  13.207  14.099  1.00 10.00           N\nATOM      2  CA  MET A   1      12.560  13.211  14.099  1.00 10.00           C\nEND\n"""

    with make_client(tmp_path) as client:
        project_id = create_project(client, target_id="CUSTOM-MYC", target_name="MYC")

        builtin_ids = {target["target_id"] for target in client.get("/builtin-targets").json()}
        assert "CUSTOM-MYC" not in builtin_ids

        upload_response = client.post(
            f"/projects/{project_id}/files",
            files={"file": ("myc.pdb", pdb_payload, "chemical/x-pdb")},
        )
        file_id = upload_response.json()["file_id"]

        ingest_response = client.post(f"/projects/{project_id}/ingest")

        assert ingest_response.status_code == 202
        result = client.get(f"/projects/{project_id}/files/{file_id}/parse-result").json()
        assert result["metadata"]["binding_site_created"] is True

        sites_response = client.get(f"/projects/{project_id}/binding-sites")
        assert sites_response.status_code == 200
        sites = sites_response.json()
        assert any(
            site["project_id"] == project_id and site["target_id"] == "CUSTOM-MYC"
            for site in sites
        )


def test_project_files_endpoint_lists_uploads(tmp_path):
    with make_client(tmp_path) as client:
        project_id = create_project(client)
        client.post(
            f"/projects/{project_id}/files",
            files={"file": ("notes.txt", b"not a smiles line", "text/plain")},
        )

        response = client.get(f"/projects/{project_id}/files")

        assert response.status_code == 200
        files = response.json()
        assert len(files) == 1
        assert files[0]["filename"] == "notes.txt"
