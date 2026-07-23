import hashlib
import json
from pathlib import Path

from fastapi.testclient import TestClient

from medagent.api.app import create_app
from medagent.core.config import Settings


PDB_PAYLOAD = (
    b"HEADER    TEST RECEPTOR\n"
    b"TITLE     TRACEABLE EGFR STRUCTURE\n"
    b"ATOM      1  N   MET A   1      11.104  13.207  14.099  1.00 10.00           N\n"
    b"ATOM      2  CA  MET A   1      12.560  13.211  14.099  1.00 10.00           C\n"
    b"END\n"
)


class FakeResponse:
    def __init__(self, payload: bytes, content_type: str):
        self.payload = payload
        self.headers = {"Content-Type": content_type, "ETag": '"test-etag"'}

    def read(self, size: int = -1) -> bytes:
        if not self.payload:
            return b""
        if size < 0:
            payload, self.payload = self.payload, b""
            return payload
        payload, self.payload = self.payload[:size], self.payload[size:]
        return payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def make_client(tmp_path) -> TestClient:
    return TestClient(
        create_app(
            Settings(
                database_url=f"sqlite:///{tmp_path / 'structure-workflow.db'}",
                storage_local_root=str(tmp_path / "storage"),
            )
        )
    )


def create_project(client: TestClient) -> str:
    response = client.post(
        "/projects",
        json={"name": "Structure workflow", "target_id": "TGT-EGFR", "objective": "design"},
    )
    assert response.status_code == 201
    return response.json()["project_id"]


def test_rcsb_import_creates_an_active_hashed_project_structure(tmp_path, monkeypatch):
    metadata = {
        "rcsb_id": "4ZAU",
        "exptl": [{"method": "X-RAY DIFFRACTION"}],
        "rcsb_entry_info": {"resolution_combined": [2.8]},
        "rcsb_accession_info": {"initial_release_date": "2015-05-06T00:00:00Z"},
        "struct": {"title": "EGFR kinase domain"},
    }

    def fake_urlopen(request, timeout=0):
        url = request.full_url
        if "data.rcsb.org" in url:
            return FakeResponse(json.dumps(metadata).encode(), "application/json")
        if "files.rcsb.org" in url:
            return FakeResponse(PDB_PAYLOAD, "chemical/x-pdb")
        raise AssertionError(url)

    monkeypatch.setattr("medagent.services.structure_workflow.urlopen", fake_urlopen)

    with make_client(tmp_path) as client:
        project_id = create_project(client)
        response = client.post(
            f"/projects/{project_id}/structures/import-rcsb",
            json={"pdb_id": "4zau"},
        )

        assert response.status_code == 201, response.text
        structure = response.json()
        assert structure["source"] == "rcsb_pdb"
        assert structure["source_identifier"] == "4ZAU"
        assert structure["status"] == "validated"
        assert structure["is_active"] is True
        assert structure["sha256"] == hashlib.sha256(PDB_PAYLOAD).hexdigest()
        assert structure["metadata"]["experimental_method"] == "X-RAY DIFFRACTION"
        assert structure["metadata"]["resolution"] == 2.8

        project = client.get(f"/projects/{project_id}").json()
        assert project["active_structure_id"] == structure["structure_id"]

        structures = client.get(f"/projects/{project_id}/structures").json()
        assert [item["structure_id"] for item in structures] == [structure["structure_id"]]


def test_uploaded_pdb_can_be_registered_without_creating_an_unconfirmed_pocket(tmp_path):
    with make_client(tmp_path) as client:
        project_id = create_project(client)
        upload = client.post(
            f"/projects/{project_id}/files",
            files={"file": ("receptor.pdb", PDB_PAYLOAD, "chemical/x-pdb")},
        )
        assert upload.status_code == 202

        response = client.post(
            f"/projects/{project_id}/structures/register-upload",
            json={"source_file_id": upload.json()["file_id"]},
        )

        assert response.status_code == 201, response.text
        structure = response.json()
        assert structure["source"] == "upload"
        assert structure["source_file_id"] != upload.json()["file_id"]
        assert structure["status"] == "validated"
        assert structure["sha256"] == hashlib.sha256(PDB_PAYLOAD).hexdigest()
        assert structure["metadata"]["pdb_summary"]["atom_count"] == 2
        sites = client.get(f"/projects/{project_id}/binding-sites").json()
        assert not any(site["project_id"] == project_id for site in sites)


def test_structure_workflow_rejects_invalid_pdb_ids_and_non_pdb_uploads(tmp_path):
    with make_client(tmp_path) as client:
        project_id = create_project(client)
        invalid_id = client.post(
            f"/projects/{project_id}/structures/import-rcsb",
            json={"pdb_id": "../../etc/passwd"},
        )
        assert invalid_id.status_code == 422

        unsupported_assembly = client.post(
            f"/projects/{project_id}/structures/import-rcsb",
            json={"pdb_id": "4ZAU", "assembly_id": "1"},
        )
        assert unsupported_assembly.status_code == 422

        upload = client.post(
            f"/projects/{project_id}/files",
            files={"file": ("notes.txt", b"not a receptor", "text/plain")},
        )
        response = client.post(
            f"/projects/{project_id}/structures/register-upload",
            json={"source_file_id": upload.json()["file_id"]},
        )
        assert response.status_code == 422


def test_p2rank_selection_and_pdbqt_preparation_share_one_structure(tmp_path, monkeypatch):
    def fake_p2rank_status():
        return {
            "available": True,
            "runtime_available": True,
            "java_executable": "java.exe",
            "launcher": "prank.bat",
            "working_directory": str(tmp_path),
            "version": "2.5.1",
        }

    def fake_p2rank_run(command, **kwargs):
        output = Path(command[command.index("-o") + 1])
        output.mkdir(parents=True)
        (output / "input.pdb_predictions.csv").write_text(
            "name,rank,score,probability,sas_points,surf_atoms,center_x,center_y,center_z,residue_ids,surf_atom_ids\n"
            "pocket1,1,9.77,0.525,70,40,12.0,14.0,15.0,A_1,1 2\n",
            encoding="utf-8",
        )

        class Completed:
            returncode = 0
            stdout = "P2Rank completed"
            stderr = ""

        return Completed()

    def fake_prepare(receptor_path, output_dir, tool_status):
        prepared = output_dir / "receptor.pdbqt"
        prepared.write_text(
            "ATOM      1  N   MET A   1      11.104  13.207  14.099  0.00  0.00      N\n",
            encoding="utf-8",
        )
        return prepared, []

    monkeypatch.setattr("medagent.services.p2rank_adapter.p2rank_tool_status", fake_p2rank_status)
    monkeypatch.setattr("medagent.services.p2rank_adapter.subprocess.run", fake_p2rank_run)
    monkeypatch.setattr(
        "medagent.services.receptor_preparation._prepare_receptor_for_vina", fake_prepare
    )

    with make_client(tmp_path) as client:
        project_id = create_project(client)
        upload = client.post(
            f"/projects/{project_id}/files",
            files={"file": ("receptor.pdb", PDB_PAYLOAD, "chemical/x-pdb")},
        ).json()
        structure = client.post(
            f"/projects/{project_id}/structures/register-upload",
            json={"source_file_id": upload["file_id"]},
        ).json()

        prediction = client.post(
            f"/projects/{project_id}/structures/{structure['structure_id']}/p2rank"
        )
        assert prediction.status_code == 200, prediction.text
        site = prediction.json()["binding_sites"][0]
        assert site["structure_id"] == structure["structure_id"]

        selection = client.post(
            f"/projects/{project_id}/binding-sites/{site['binding_site_id']}/select"
        )
        assert selection.status_code == 200, selection.text
        assert selection.json()["binding_site_id"] == site["binding_site_id"]

        preparation = client.post(
            f"/projects/{project_id}/structures/{structure['structure_id']}/prepare"
        )
        assert preparation.status_code == 200, preparation.text
        assert preparation.json()["prepared_receptor_sha256"]

        readiness = client.get(f"/projects/{project_id}/structure-readiness")
        assert readiness.status_code == 200
        bundle = readiness.json()
        assert bundle["ready"] is True
        assert bundle["structure_id"] == structure["structure_id"]
        assert bundle["binding_site_id"] == site["binding_site_id"]
        assert bundle["pocket_pdb"]["sha256"]
        assert bundle["prepared_receptor_pdbqt"]["sha256"]
        assert bundle["tools"]["targetdiff"]["ready"] is True
        assert bundle["tools"]["autogrow4"]["ready"] is True

        pocket_path = next((tmp_path / "storage" / project_id / "p2rank_runs").rglob("pocket_1.pdb"))
        pocket_payload = pocket_path.read_bytes()
        pocket_path.write_text("ATOM tampered pocket\n", encoding="utf-8")
        stale_pocket = client.get(f"/projects/{project_id}/structure-readiness").json()
        assert stale_pocket["ready"] is False
        assert "pocket_pdb_hash_mismatch" in stale_pocket["reason_codes"]
        pocket_path.write_bytes(pocket_payload)

        source_path = (
            tmp_path
            / "storage"
            / project_id
            / "structures"
            / structure["structure_id"]
            / "original"
            / "receptor.pdb"
        )
        source_path.write_text("ATOM tampered\n", encoding="utf-8")
        stale = client.get(f"/projects/{project_id}/structure-readiness").json()
        assert stale["ready"] is False
        assert "source_receptor_hash_mismatch" in stale["reason_codes"]

        manifests = client.get(
            f"/scientific/projects/{project_id}/execution-manifests"
        ).json()
        preparation_manifest = next(
            item for item in manifests if item["stage"] == "receptor_preparation"
        )
        assert preparation_manifest["input_artifacts"]["source_receptor_pdb"]["sha256"]
        assert preparation_manifest["output_artifacts"]["prepared_receptor_pdbqt"]["sha256"]


def test_binding_site_selection_rejects_a_site_from_an_inactive_structure(tmp_path, monkeypatch):
    with make_client(tmp_path) as client:
        project_id = create_project(client)
        first_upload = client.post(
            f"/projects/{project_id}/files",
            files={"file": ("first.pdb", PDB_PAYLOAD, "chemical/x-pdb")},
        ).json()
        first = client.post(
            f"/projects/{project_id}/structures/register-upload",
            json={"source_file_id": first_upload["file_id"]},
        ).json()

        # Use the compatibility receptor endpoint to create a site, then attach it to the first structure.
        prepared = client.post(
            f"/projects/{project_id}/receptors/prepare",
            json={
                "source_file_id": first_upload["file_id"],
                "grid_center": [1, 2, 3],
                "grid_size": [18, 18, 18],
                "prepare_for_vina": False,
            },
        ).json()

        second_payload = PDB_PAYLOAD.replace(b"TRACEABLE", b"SECOND   ")
        second_upload = client.post(
            f"/projects/{project_id}/files",
            files={"file": ("second.pdb", second_payload, "chemical/x-pdb")},
        ).json()
        client.post(
            f"/projects/{project_id}/structures/register-upload",
            json={"source_file_id": second_upload["file_id"]},
        )

        response = client.post(
            f"/projects/{project_id}/binding-sites/{prepared['binding_site_id']}/select"
        )
        assert first["is_active"] is True
        assert response.status_code == 422
