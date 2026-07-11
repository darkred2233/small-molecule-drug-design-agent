from fastapi.testclient import TestClient

from medagent.api.app import create_app
from medagent.core.config import Settings
from medagent.services.molecule_generation import generation_tool_status


def make_client(tmp_path):
    app = create_app(
        Settings(
            database_url=f"sqlite:///{tmp_path / 'test.db'}",
            storage_local_root=str(tmp_path / "uploads"),
        )
    )
    return TestClient(app)


def create_project_with_generation_seeds(client: TestClient) -> str:
    project_response = client.post(
        "/projects",
        json={
            "name": "Molecule generation",
            "target_id": "TGT-EGFR",
            "objective": "generate three classes of candidate molecules",
        },
    )
    assert project_response.status_code == 201
    project_id = project_response.json()["project_id"]
    upload_response = client.post(
        f"/projects/{project_id}/files",
        files={
            "file": (
                "generation_seeds.smi",
                b"CCO ethanol\nc1ccccc1 benzene\n",
                "text/plain",
            )
        },
    )
    assert upload_response.status_code == 202
    ingest_response = client.post(f"/projects/{project_id}/ingest")
    assert ingest_response.status_code == 202
    return project_id


def test_generate_molecules_runs_all_three_generation_classes(tmp_path):
    with make_client(tmp_path) as client:
        project_id = create_project_with_generation_seeds(client)

        response = client.post(
            f"/projects/{project_id}/molecules/generate",
            json={"generation_size": 9},
        )

        assert response.status_code == 201
        summary = response.json()
        assert summary["stored_count"] == 9
        assert summary["invalid_count"] == 0
        assert summary["adapter_mode"] == "rdkit_datamol_generation_toolchain"
        assert "rdkit" in summary["tool_status"]
        assert "datamol" in summary["tool_status"]
        assert set(summary["strategy_summaries"]) == {"reinvent4", "crem", "autogrow4"}
        assert all(item["stored_count"] == 3 for item in summary["strategy_summaries"].values())
        assert all(
            item["candidate_source_counts"] for item in summary["strategy_summaries"].values()
        )

        crem_summary = summary["strategy_summaries"]["crem"]
        if generation_tool_status()["crem"]["database_available"]:
            assert crem_summary["tool_status"]["crem"]["database_available"] is True
            assert crem_summary["adapter_mode"] in {
                "crem_fragment_database",
                "crem_fragment_database_with_rdkit_surrogate_fill",
                "rdkit_datamol_crem_fragment_surrogate",
            }

        molecules_response = client.get(f"/projects/{project_id}/molecules")
        assert molecules_response.status_code == 200
        molecules = molecules_response.json()
        assert len(molecules) == 9
        assert {item["source_agent"] for item in molecules} == {
            "generator_agent:reinvent4",
            "generator_agent:crem",
            "generator_agent:autogrow4",
        }
        assert all(item["status"] == "generated" for item in molecules)
        assert all("requires_structure_validation" in item["labels"] for item in molecules)

        validation_response = client.post(f"/projects/{project_id}/molecules/validate")
        assert validation_response.status_code == 200
        assert validation_response.json()["validated_count"] == 9

        filter_response = client.post(f"/projects/{project_id}/molecules/filter-rules")
        assert filter_response.status_code == 200
        assert filter_response.json()["evaluated_count"] == 9


def test_generation_is_idempotent_for_same_project(tmp_path):
    with make_client(tmp_path) as client:
        project_id = create_project_with_generation_seeds(client)
        first = client.post(
            f"/projects/{project_id}/molecules/generate",
            json={"generation_size": 6},
        )
        assert first.status_code == 201

        second = client.post(
            f"/projects/{project_id}/molecules/generate",
            json={"generation_size": 6},
        )

        assert second.status_code == 201
        assert second.json()["stored_count"] == 0
        assert second.json()["duplicate_count"] >= 6
        molecules = client.get(f"/projects/{project_id}/molecules").json()
        assert len(molecules) == 6


def test_generation_can_use_builtin_target_library_as_seed_source(tmp_path):
    with make_client(tmp_path) as client:
        project_id = client.post(
            "/projects",
            json={
                "name": "Target library generation",
                "target_id": "TGT-EGFR",
                "objective": "generate from target-drug library seeds",
            },
        ).json()["project_id"]

        response = client.post(
            f"/projects/{project_id}/molecules/generate",
            json={"generation_size": 3, "strategies": ["reinvent4"]},
        )

        assert response.status_code == 201
        summary = response.json()
        assert summary["stored_count"] == 3
        assert summary["seed_count"] > 0
        assert summary["strategy_summaries"]["reinvent4"]["stored_count"] == 3
