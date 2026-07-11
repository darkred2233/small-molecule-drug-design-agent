from fastapi.testclient import TestClient

import medagent.api.app as api_app
from medagent.api.app import create_app
from medagent.core.config import Settings
from medagent.db.models import Critique
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


def create_filtered_project(client: TestClient) -> str:
    project = client.post(
        "/projects",
        json={
            "name": "Candidate assessment",
            "target_id": "TGT-EGFR",
            "objective": "run docking, ADMET, and synthesis",
        },
    ).json()
    project_id = project["project_id"]
    upload_response = client.post(
        f"/projects/{project_id}/files",
        files={
            "file": (
                "candidate_assessment_seed.smi",
                b"CCO ethanol\nCc1ccccc1 toluene\n",
                "text/plain",
            )
        },
    )
    assert upload_response.status_code == 202
    assert client.post(f"/projects/{project_id}/ingest").status_code == 202
    assert client.post(f"/projects/{project_id}/molecules/import-seeds").status_code == 201
    assert client.post(f"/projects/{project_id}/molecules/validate").status_code == 200
    assert client.post(f"/projects/{project_id}/molecules/filter-rules").status_code == 200
    return project_id


def test_candidate_assessment_writes_docking_admet_and_synthesis_results(tmp_path):
    with make_client(tmp_path) as client:
        project_id = create_filtered_project(client)

        response = client.post(
            f"/projects/{project_id}/candidate-assessment/run",
            json={
                "key_residues": ["Met793", "Lys745", "Asp855"],
                "max_synthesis_steps": 5,
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["project_id"] == project_id
        assert body["conformer"]["generated_count"] == 2
        assert body["docking"]["evaluated_count"] == 2
        assert body["admet"]["evaluated_count"] == 2
        assert body["synthesis"]["evaluated_count"] == 2
        assert body["ranking"]["evaluated_count"] == 2
        assert body["tool_status"]["rdkit"]["available"] is True
        assert body["docking"]["adapter_mode"] == "rdkit_surrogate_docking"
        assert body["admet"]["adapter_mode"] in {
            "admet_ai_chemprop_admet",
            "chemprop_with_rdkit_surrogate_admet",
            "rdkit_surrogate_admet",
        }
        assert body["synthesis"]["adapter_mode"] == "rdkit_surrogate_synthesis"
        assert body["ranking"]["adapter_mode"] == "heuristic_candidate_ranking"

        conformers = client.get(f"/projects/{project_id}/conformer-results").json()
        assert len(conformers) == 2
        assert all(item["conformer_generated"] for item in conformers)
        assert all("conformer_ok" in item["labels"] for item in conformers)

        docking = client.get(f"/projects/{project_id}/docking-results").json()
        assert len(docking) == 2
        assert all(item["vina_score"] < 0 for item in docking)
        assert all("external_docking_adapter_pending" in item["labels"] for item in docking)

        admet = client.get(f"/projects/{project_id}/admet-results").json()
        assert len(admet) == 2
        assert all(item["hERG_risk"] in {"low_risk", "medium_risk", "high_risk"} for item in admet)
        assert all(
            item["raw_output"]["adapter_mode"] in {
                "admet_ai_chemprop_admet",
                "chemprop_local_admet",
                "chemprop_docker_admet",
                "rdkit_surrogate_admet",
            }
            for item in admet
        )

        synthesis = client.get(f"/projects/{project_id}/synthesis-routes").json()
        assert len(synthesis) == 2
        assert all(item["route_steps"] is not None for item in synthesis)
        assert all("route_confidence" in item for item in synthesis)

        rankings = client.get(f"/projects/{project_id}/rankings").json()
        assert len(rankings) == 2
        assert [item["rank"] for item in rankings] == [1, 2]
        assert rankings[0]["overall_score"] >= rankings[1]["overall_score"]
        assert all(item["final_decision"] in {"advance", "watch", "deprioritize", "reject"} for item in rankings)
        assert all("docking" in item["score_breakdown"] for item in rankings)
        assert all("admet" in item["score_breakdown"] for item in rankings)
        assert all("synthesis" in item["score_breakdown"] for item in rankings)
        assert all("rule_filter" in item["score_breakdown"] for item in rankings)


def test_candidate_assessment_is_idempotent(tmp_path):
    with make_client(tmp_path) as client:
        project_id = create_filtered_project(client)

        first = client.post(f"/projects/{project_id}/candidate-assessment/run", json={}).json()
        second = client.post(f"/projects/{project_id}/candidate-assessment/run", json={}).json()

        assert second["conformer"]["generated_count"] == first["conformer"]["generated_count"]
        assert second["docking"]["evaluated_count"] == first["docking"]["evaluated_count"]
        assert len(client.get(f"/projects/{project_id}/docking-results").json()) == 2
        assert len(client.get(f"/projects/{project_id}/admet-results").json()) == 2
        assert len(client.get(f"/projects/{project_id}/synthesis-routes").json()) == 2
        assert len(client.get(f"/projects/{project_id}/rankings").json()) == 2


def test_project_rankings_can_be_regenerated_without_duplicate_rows(tmp_path):
    with make_client(tmp_path) as client:
        project_id = create_filtered_project(client)
        assert client.post(f"/projects/{project_id}/candidate-assessment/run", json={}).status_code == 200

        first = client.post(f"/projects/{project_id}/rankings/generate", json={}).json()
        second = client.post(f"/projects/{project_id}/rankings/generate", json={}).json()

        assert first["ranking"]["evaluated_count"] == 2
        assert second["ranking"]["evaluated_count"] == 2

        rankings = client.get(f"/projects/{project_id}/rankings").json()
        assert len(rankings) == 2
        assert [item["rank"] for item in rankings] == [1, 2]
        assert all(item["evidence_confidence"] > 0 for item in rankings)


def test_project_rankings_consume_self_refutation_critiques(tmp_path):
    with make_client(tmp_path) as client:
        project_id = create_filtered_project(client)
        assert client.post(f"/projects/{project_id}/candidate-assessment/run", json={}).status_code == 200
        initial_rankings = client.get(f"/projects/{project_id}/rankings").json()
        penalized_id = initial_rankings[0]["molecule_id"]
        initial_score = initial_rankings[0]["overall_score"]

        with api_app.SessionLocal() as db:
            db.add(
                Critique(
                    critique_id="CRT-TEST",
                    molecule_id=penalized_id,
                    con_score=95.0,
                    risk_level="high",
                    reason="Manual test critique that should force ranker rejection.",
                    evidence_ids=["TEST:EVIDENCE"],
                    refutation_decision="reject",
                )
            )
            db.commit()

        response = client.post(f"/projects/{project_id}/rankings/generate", json={})
        assert response.status_code == 200

        reranked = client.get(f"/projects/{project_id}/rankings").json()
        penalized = next(item for item in reranked if item["molecule_id"] == penalized_id)
        assert penalized["final_decision"] == "reject"
        assert penalized["overall_score"] < initial_score
        assert penalized["score_breakdown"]["critique"]["available"] is True
        assert penalized["score_breakdown"]["critique"]["refutation_decision"] == "reject"
        assert penalized["score_breakdown"]["critique_overall_penalty"] == 30.0


def test_candidate_assessment_uses_external_gnina_adapter_when_ready(tmp_path, monkeypatch):
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
            vina_score=-8.4,
            cnn_score=0.72,
            cnn_affinity=-7.8,
            pose_file=str(tmp_path / f"{request.molecule_id}.sdf"),
            labels=["external_docking_adapter_used", "gnina_adapter"],
            stdout="Affinity: -8.4\nCNNscore: 0.72\nCNNaffinity: -7.8\n",
        )

    monkeypatch.setattr(candidate_assessment, "candidate_assessment_tool_status", fake_tool_status)
    monkeypatch.setattr(candidate_assessment, "run_external_docking", fake_external_docking)

    receptor_file = tmp_path / "egfr_receptor.pdb"
    receptor_file.write_text("HEADER    TEST RECEPTOR\n", encoding="utf-8")

    with make_client(tmp_path) as client:
        project_id = create_filtered_project(client)

        response = client.post(
            f"/projects/{project_id}/candidate-assessment/run",
            json={
                "protein_file": str(receptor_file),
                "grid_center": [1.0, 2.0, 3.0],
                "grid_size": [18.0, 18.0, 18.0],
                "key_residues": ["Met793"],
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["docking"]["adapter_mode"] == "gnina_external_docking"
        assert body["docking"]["evaluated_count"] == 2
        assert len(docking_requests) == 2
        assert all(request.receptor_file == str(receptor_file) for request, _ in docking_requests)
        assert all(request.ligand_file.endswith(".sdf") for request, _ in docking_requests)

        docking = client.get(f"/projects/{project_id}/docking-results").json()
        assert all(item["vina_score"] == -8.4 for item in docking)
        assert all("external_docking_adapter_used" in item["labels"] for item in docking)
        assert all("external_docking_adapter_pending" not in item["labels"] for item in docking)
