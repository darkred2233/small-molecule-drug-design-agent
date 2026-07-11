from fastapi.testclient import TestClient

from medagent.api.app import create_app
from medagent.core.config import Settings
from medagent.services import candidate_assessment
from medagent.services.docking_adapters import DockingToolResult


def make_client(tmp_path):
    app = create_app(
        Settings(
            database_url=f"sqlite:///{tmp_path / 'test.db'}",
            storage_local_root=str(tmp_path / "uploads"),
        )
    )
    return TestClient(app)


def create_project(client: TestClient) -> str:
    response = client.post(
        "/projects",
        json={
            "name": "Pocket preparation",
            "target_id": "TGT-EGFR",
            "objective": "prepare receptor and docking grid",
        },
    )
    assert response.status_code == 201
    return response.json()["project_id"]


def upload_receptor(client: TestClient, project_id: str) -> str:
    pdb_payload = (
        b"HEADER    TEST PDB\n"
        b"TITLE     EGFR TEST STRUCTURE\n"
        b"ATOM      1  N   MET A   1      11.104  13.207  14.099  1.00 10.00           N\n"
        b"ATOM      2  CA  MET A   1      12.560  13.211  14.099  1.00 10.00           C\n"
        b"ATOM      3  N   GLY B   2      15.104  16.207  12.099  1.00 10.00           N\n"
        b"END\n"
    )
    response = client.post(
        f"/projects/{project_id}/files",
        files={"file": ("egfr_receptor.pdb", pdb_payload, "chemical/x-pdb")},
    )
    assert response.status_code == 202
    return response.json()["file_id"]


def create_filtered_molecules(client: TestClient, project_id: str) -> None:
    upload_response = client.post(
        f"/projects/{project_id}/files",
        files={"file": ("seeds.smi", b"CCO ethanol\nCc1ccccc1 toluene\n", "text/plain")},
    )
    assert upload_response.status_code == 202
    assert client.post(f"/projects/{project_id}/ingest").status_code == 202
    assert client.post(f"/projects/{project_id}/molecules/import-seeds").status_code == 201
    assert client.post(f"/projects/{project_id}/molecules/validate").status_code == 200
    assert client.post(f"/projects/{project_id}/molecules/filter-rules").status_code == 200


def test_prepare_receptor_creates_project_binding_site(tmp_path):
    with make_client(tmp_path) as client:
        project_id = create_project(client)
        source_file_id = upload_receptor(client, project_id)

        response = client.post(
            f"/projects/{project_id}/receptors/prepare",
            json={
                "source_file_id": source_file_id,
                "grid_center": [1.0, 2.0, 3.0],
                "grid_size": [18.0, 19.0, 20.0],
                "key_residues": ["Met793", "Lys745"],
            },
        )

        assert response.status_code == 201
        body = response.json()
        assert body["project_id"] == project_id
        assert body["target_id"] == "TGT-EGFR"
        assert body["source_file_id"] == source_file_id
        assert body["receptor_file"].startswith("local://")
        assert body["grid_box"]["center"] == [1.0, 2.0, 3.0]
        assert body["grid_box"]["size"] == [18.0, 19.0, 20.0]
        assert body["key_residues"] == ["Met793", "Lys745"]
        assert body["preparation_status"] in {"prepared", "prepared_with_warnings"}

        sites = client.get(f"/projects/{project_id}/binding-sites").json()
        assert len(sites) == 1
        assert sites[0]["binding_site_id"] == body["binding_site_id"]


def test_candidate_assessment_uses_binding_site_receptor_and_grid(tmp_path, monkeypatch):
    original_tool_status = candidate_assessment.candidate_assessment_tool_status
    docking_requests = []

    def fake_tool_status():
        status = original_tool_status()
        status["gnina"] = {"available": True, "path": "gnina"}
        status["vina"] = {"available": False, "path": None}
        return status

    def fake_external_docking(request, tool_status):
        docking_requests.append((request, tool_status))
        return DockingToolResult(
            adapter_mode="gnina_external_docking",
            tool_name="gnina",
            success=True,
            vina_score=-8.1,
            cnn_score=0.7,
            cnn_affinity=-7.6,
            pose_file=str(tmp_path / f"{request.molecule_id}.sdf"),
            labels=["external_docking_adapter_used", "gnina_adapter"],
        )

    monkeypatch.setattr(candidate_assessment, "candidate_assessment_tool_status", fake_tool_status)
    monkeypatch.setattr(candidate_assessment, "run_external_docking", fake_external_docking)

    with make_client(tmp_path) as client:
        project_id = create_project(client)
        source_file_id = upload_receptor(client, project_id)
        site = client.post(
            f"/projects/{project_id}/receptors/prepare",
            json={
                "source_file_id": source_file_id,
                "grid_center": [4.0, 5.0, 6.0],
                "grid_size": [16.0, 17.0, 18.0],
                "key_residues": ["Met793"],
            },
        ).json()
        create_filtered_molecules(client, project_id)

        response = client.post(
            f"/projects/{project_id}/candidate-assessment/run",
            json={"binding_site_id": site["binding_site_id"]},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["docking"]["adapter_mode"] == "gnina_external_docking"
        assert len(docking_requests) == 2
        assert all(request.grid_center == [4.0, 5.0, 6.0] for request, _ in docking_requests)
        assert all(request.grid_size == [16.0, 17.0, 18.0] for request, _ in docking_requests)
        assert all(
            request.receptor_file.endswith(("egfr_receptor.pdb", "egfr_receptor.pdbqt"))
            for request, _ in docking_requests
        )
