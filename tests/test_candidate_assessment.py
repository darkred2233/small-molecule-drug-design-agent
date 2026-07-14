from fastapi.testclient import TestClient
import pytest
from types import SimpleNamespace

import medagent.api.app as api_app
from medagent.api.app import create_app
from medagent.core.config import Settings
from medagent.db.models import Critique
from medagent.services import candidate_assessment
from medagent.services.aizynthfinder_adapter import AiZynthFinderResult
from medagent.services.docking_adapters import DockingToolResult


def make_client(tmp_path):
    app = create_app(
        Settings(
            database_url=f"sqlite:///{tmp_path / 'test.db'}",
            storage_local_root=str(tmp_path / "uploads"),
        )
    )
    return TestClient(app)


@pytest.fixture(autouse=True)
def disable_external_retrosynthesis_by_default(monkeypatch):
    original_tool_status = candidate_assessment.candidate_assessment_tool_status

    def fake_tool_status():
        return _disable_external_retrosynthesis(original_tool_status())

    monkeypatch.setattr(candidate_assessment, "candidate_assessment_tool_status", fake_tool_status)


def _disable_external_retrosynthesis(status: dict) -> dict:
    status["aizynthfinder"] = {
        "available": False,
        "mode": None,
        "version": None,
        "path": None,
        "docker_image": None,
        "model_configured": False,
    }
    status["askcos"] = {"available": False, "version": None}
    return status


def _minimal_tool_status_with_external() -> dict:
    return {
        "rdkit": {"available": True, "version": "test"},
        "gnina": {
            "available": True,
            "mode": "docker",
            "version": None,
            "path": None,
            "docker_image": "gnina/gnina:latest",
        },
        "vina": {"available": False, "mode": None, "path": None, "docker_image": None},
        "diffdock": {"available": False, "mode": None, "version": None, "docker_image": None},
        "oddt": {"available": False, "version": None},
        "admetlab": {"available": False, "version": None},
        "chemprop": {"available": False, "mode": None, "version": None},
        "deepchem": {"available": False, "version": None},
        "aizynthfinder": {
            "available": True,
            "mode": "docker",
            "version": None,
            "path": None,
            "docker_image": "aizynthfinder:latest",
            "model_configured": True,
        },
        "askcos": {"available": False, "version": None},
    }


def _successful_docking_result(tmp_path, request) -> DockingToolResult:
    return DockingToolResult(
        adapter_mode="gnina_docker_docking",
        tool_name="gnina",
        success=True,
        vina_score=-8.4,
        cnn_score=0.72,
        cnn_affinity=-7.8,
        pose_file=str(tmp_path / f"{request.molecule_id}.sdf"),
        labels=["external_docking_adapter_used", "gnina_adapter"],
        stdout="Affinity: -8.4\nCNNscore: 0.72\nCNNaffinity: -7.8\n",
    )


def _successful_retrosynthesis_result() -> AiZynthFinderResult:
    return AiZynthFinderResult(
        adapter_mode="aizynthfinder_docker",
        tool_name="aizynthfinder",
        success=True,
        route_found=True,
        num_steps=2,
        route_score=0.84,
        route_summary="AiZynthFinder found a route in 2 steps; top score=0.84.",
        labels=["aizynthfinder_executed", "aizynthfinder_route"],
    )


def test_external_refinement_top_n_is_selected_after_coarse_screen():
    coarse_passed = [
        SimpleNamespace(molecule_id="MOL-PASS-1"),
        SimpleNamespace(molecule_id="MOL-PASS-2"),
        SimpleNamespace(molecule_id="MOL-PASS-3"),
    ]
    ranking = SimpleNamespace(
        molecule_ids=[
            "MOL-FAILED-1",
            "MOL-PASS-2",
            "MOL-FAILED-2",
            "MOL-PASS-1",
        ]
    )

    selected = candidate_assessment._top_ranked_molecules_for_external_refinement(
        coarse_passed,
        ranking,
        external_top_n=2,
    )

    assert [molecule.molecule_id for molecule in selected] == ["MOL-PASS-2", "MOL-PASS-1"]

    full_selection = candidate_assessment._top_ranked_molecules_for_external_refinement(
        coarse_passed,
        ranking,
        external_top_n=len(coarse_passed),
    )

    assert [molecule.molecule_id for molecule in full_selection] == [
        "MOL-PASS-2",
        "MOL-PASS-1",
        "MOL-PASS-3",
    ]


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
                "max_molecules": 2,
                "top_n": 2,
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
        assert all(item["route_json"]["route_plan"] for item in synthesis)
        assert all(item["route_json"]["starting_materials"] for item in synthesis)
        assert all(item["route_json"]["route_risks"] for item in synthesis)

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

        payload = {"max_molecules": 2, "top_n": 2}
        first = client.post(f"/projects/{project_id}/candidate-assessment/run", json=payload).json()
        second = client.post(f"/projects/{project_id}/candidate-assessment/run", json=payload).json()

        assert second["conformer"]["generated_count"] == first["conformer"]["generated_count"]
        assert second["docking"]["evaluated_count"] == first["docking"]["evaluated_count"]
        assert len(client.get(f"/projects/{project_id}/docking-results").json()) == 2
        assert len(client.get(f"/projects/{project_id}/admet-results").json()) == 2
        assert len(client.get(f"/projects/{project_id}/synthesis-routes").json()) == 2
        assert len(client.get(f"/projects/{project_id}/rankings").json()) == 2


def test_project_rankings_can_be_regenerated_without_duplicate_rows(tmp_path):
    with make_client(tmp_path) as client:
        project_id = create_filtered_project(client)
        payload = {"max_molecules": 2, "top_n": 2}
        assert client.post(f"/projects/{project_id}/candidate-assessment/run", json=payload).status_code == 200

        first = client.post(f"/projects/{project_id}/rankings/generate", json=payload).json()
        second = client.post(f"/projects/{project_id}/rankings/generate", json=payload).json()

        assert first["ranking"]["evaluated_count"] == 2
        assert second["ranking"]["evaluated_count"] == 2

        rankings = client.get(f"/projects/{project_id}/rankings").json()
        assert len(rankings) == 2
        assert [item["rank"] for item in rankings] == [1, 2]
        assert all(item["evidence_confidence"] > 0 for item in rankings)


def test_project_rankings_consume_self_refutation_critiques(tmp_path):
    with make_client(tmp_path) as client:
        project_id = create_filtered_project(client)
        assert client.post(
            f"/projects/{project_id}/candidate-assessment/run",
            json={"max_molecules": 2, "top_n": 2},
        ).status_code == 200
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

        response = client.post(
            f"/projects/{project_id}/rankings/generate",
            json={"max_molecules": 2, "top_n": 2},
        )
        assert response.status_code == 200

        reranked = client.get(f"/projects/{project_id}/rankings").json()
        penalized = next(item for item in reranked if item["molecule_id"] == penalized_id)
        assert penalized["final_decision"] == "reject"
        assert penalized["overall_score"] < initial_score
        assert penalized["score_breakdown"]["critique"]["available"] is True
        assert penalized["score_breakdown"]["critique"]["refutation_decision"] == "reject"
        assert penalized["score_breakdown"]["critique_overall_penalty"] == 30.0

        molecules = client.get(f"/projects/{project_id}/molecules").json()
        penalized_molecule = next(item for item in molecules if item["molecule_id"] == penalized_id)
        assert penalized_molecule["status"] == "rejected_by_ranking"
        assert "ranking_reject" in penalized_molecule["labels"]


def test_candidate_assessment_marks_route_failures_as_failed_assessment(tmp_path):
    with make_client(tmp_path) as client:
        project_id = create_filtered_project(client)

        response = client.post(
            f"/projects/{project_id}/candidate-assessment/run",
            json={"max_molecules": 2, "top_n": 2, "max_synthesis_steps": 1},
        )

        assert response.status_code == 200
        routes = client.get(f"/projects/{project_id}/synthesis-routes").json()
        assert len(routes) == 2
        assert all(route["route_found"] is False for route in routes)

        molecules = client.get(f"/projects/{project_id}/molecules").json()
        routed_ids = {route["molecule_id"] for route in routes}
        routed_molecules = [molecule for molecule in molecules if molecule["molecule_id"] in routed_ids]
        assert {molecule["status"] for molecule in routed_molecules} == {"failed_assessment"}
        assert all("assessment_failed" in molecule["labels"] for molecule in routed_molecules)


def test_candidate_assessment_uses_external_gnina_adapter_when_ready(tmp_path, monkeypatch):
    original_tool_status = candidate_assessment.candidate_assessment_tool_status
    docking_requests = []

    def fake_tool_status():
        status = original_tool_status()
        status["gnina"] = {"available": True, "path": "gnina"}
        status["vina"] = {"available": False, "path": None}
        status["chemprop"] = {"available": False, "mode": None, "version": None}
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
                "assessment_mode": "full",
                "max_molecules": 2,
                "top_n": 2,
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


def test_fast_assessment_mode_skips_external_docking_and_retrosynthesis(tmp_path, monkeypatch):
    monkeypatch.setattr(
        candidate_assessment,
        "candidate_assessment_tool_status",
        _minimal_tool_status_with_external,
    )

    def fail_external_docking(*_args, **_kwargs):
        raise AssertionError("fast mode should not call external docking")

    def fail_retrosynthesis(*_args, **_kwargs):
        raise AssertionError("fast mode should not call AiZynthFinder")

    monkeypatch.setattr(candidate_assessment, "run_external_docking", fail_external_docking)
    monkeypatch.setattr(candidate_assessment, "run_aizynthfinder_retrosynthesis", fail_retrosynthesis)

    receptor_file = tmp_path / "egfr_receptor.pdb"
    receptor_file.write_text("HEADER    TEST RECEPTOR\n", encoding="utf-8")

    with make_client(tmp_path) as client:
        project_id = create_filtered_project(client)
        response = client.post(
            f"/projects/{project_id}/candidate-assessment/run",
            json={
                "assessment_mode": "fast",
                "max_molecules": 2,
                "top_n": 2,
                "protein_file": str(receptor_file),
                "grid_center": [1.0, 2.0, 3.0],
                "grid_size": [18.0, 18.0, 18.0],
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["assessment_mode"] == "fast"
        assert body["docking"]["adapter_mode"] == "rdkit_surrogate_docking"
        assert body["synthesis"]["adapter_mode"] == "rdkit_surrogate_synthesis"
        assert body["admet"]["adapter_mode"] == "rdkit_surrogate_admet"

        docking = client.get(f"/projects/{project_id}/docking-results").json()
        synthesis = client.get(f"/projects/{project_id}/synthesis-routes").json()
        assert all("external_docking_adapter_pending" in item["labels"] for item in docking)
        assert all("rdkit_surrogate_synthesis" in item["labels"] for item in synthesis)


def test_external_assessment_mode_refines_only_top_n(tmp_path, monkeypatch):
    docking_requests = []
    retrosynthesis_requests = []

    monkeypatch.setattr(
        candidate_assessment,
        "candidate_assessment_tool_status",
        _minimal_tool_status_with_external,
    )

    def fake_external_docking(request, tool_status):
        docking_requests.append((request, tool_status))
        return _successful_docking_result(tmp_path, request)

    def fake_retrosynthesis(request, status=None):
        retrosynthesis_requests.append((request, status))
        return _successful_retrosynthesis_result()

    monkeypatch.setattr(candidate_assessment, "run_external_docking", fake_external_docking)
    monkeypatch.setattr(candidate_assessment, "run_aizynthfinder_retrosynthesis", fake_retrosynthesis)

    receptor_file = tmp_path / "egfr_receptor.pdb"
    receptor_file.write_text("HEADER    TEST RECEPTOR\n", encoding="utf-8")

    with make_client(tmp_path) as client:
        project_id = create_filtered_project(client)
        response = client.post(
            f"/projects/{project_id}/candidate-assessment/run",
            json={
                "assessment_mode": "external",
                "external_top_n": 1,
                "max_molecules": 2,
                "top_n": 2,
                "protein_file": str(receptor_file),
                "grid_center": [1.0, 2.0, 3.0],
                "grid_size": [18.0, 18.0, 18.0],
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["assessment_mode"] == "external"
        assert body["external_top_n"] == 1
        assert body["docking"]["adapter_mode"] == "gnina_docker_docking_top_n_refinement"
        assert body["synthesis"]["adapter_mode"] == "aizynthfinder_docker_top_n_refinement"
        assert len(docking_requests) == 1
        assert len(retrosynthesis_requests) == 1

        docking = client.get(f"/projects/{project_id}/docking-results").json()
        synthesis = client.get(f"/projects/{project_id}/synthesis-routes").json()
        assert sum("external_docking_adapter_used" in item["labels"] for item in docking) == 1
        assert sum("external_retrosynthesis_adapter_used" in item["labels"] for item in synthesis) == 1
        assert sum("rdkit_surrogate_synthesis" in item["labels"] for item in synthesis) == 1

        refined_ids = {
            item["molecule_id"]
            for item in synthesis
            if "external_retrosynthesis_adapter_used" in item["labels"]
        }
        molecules = client.get(f"/projects/{project_id}/molecules").json()
        refined_molecules = [
            molecule for molecule in molecules if molecule["molecule_id"] in refined_ids
        ]
        assert refined_molecules
        assert all("externally_refined_candidate" in molecule["labels"] for molecule in refined_molecules)
        assert all(
            "external_retrosynthesis_adapter_pending" not in molecule["labels"]
            for molecule in refined_molecules
        )
        assert all("rdkit_surrogate_synthesis" not in molecule["labels"] for molecule in refined_molecules)

        status = client.get(f"/projects/{project_id}/status").json()
        docking_runs = [run for run in status["agent_runs"] if run["agent_name"] == "docking_agent"]
        assert docking_runs
        assert docking_runs[-1]["output_json"]["progress"]["percent"] == 100


def test_external_refinement_skips_coarse_screen_failures(tmp_path, monkeypatch):
    docking_requests = []
    retrosynthesis_requests = []

    monkeypatch.setattr(
        candidate_assessment,
        "candidate_assessment_tool_status",
        _minimal_tool_status_with_external,
    )

    original_failure_reasons = candidate_assessment._assessment_failure_reasons

    def fake_failure_reasons(db, molecule, synthesis_route=None):
        if molecule.smiles == "CCO":
            return ["assessment_bad_pose"]
        return original_failure_reasons(db, molecule, synthesis_route=synthesis_route)

    def fake_external_docking(request, tool_status):
        docking_requests.append((request, tool_status))
        return _successful_docking_result(tmp_path, request)

    def fake_retrosynthesis(request, status=None):
        retrosynthesis_requests.append((request, status))
        return _successful_retrosynthesis_result()

    monkeypatch.setattr(candidate_assessment, "_assessment_failure_reasons", fake_failure_reasons)
    monkeypatch.setattr(candidate_assessment, "run_external_docking", fake_external_docking)
    monkeypatch.setattr(candidate_assessment, "run_aizynthfinder_retrosynthesis", fake_retrosynthesis)

    receptor_file = tmp_path / "egfr_receptor.pdb"
    receptor_file.write_text("HEADER    TEST RECEPTOR\n", encoding="utf-8")

    with make_client(tmp_path) as client:
        project_id = create_filtered_project(client)
        response = client.post(
            f"/projects/{project_id}/candidate-assessment/run",
            json={
                "assessment_mode": "external",
                "external_top_n": 2,
                "max_molecules": 2,
                "top_n": 2,
                "protein_file": str(receptor_file),
                "grid_center": [1.0, 2.0, 3.0],
                "grid_size": [18.0, 18.0, 18.0],
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert len(docking_requests) == 1
        assert len(retrosynthesis_requests) == 1
        assert "coarse_screen_failed_skip_external=1" in body["docking"]["warnings"]

        molecules = client.get(f"/projects/{project_id}/molecules").json()
        failed = next(molecule for molecule in molecules if molecule["smiles"] == "CCO")
        assert "rejected_by_coarse_screen" in failed["labels"]
        assert "externally_refined_candidate" not in failed["labels"]


def test_full_assessment_mode_refines_all_candidates(tmp_path, monkeypatch):
    docking_requests = []
    retrosynthesis_requests = []

    monkeypatch.setattr(
        candidate_assessment,
        "candidate_assessment_tool_status",
        _minimal_tool_status_with_external,
    )

    def fake_external_docking(request, tool_status):
        docking_requests.append((request, tool_status))
        return _successful_docking_result(tmp_path, request)

    def fake_retrosynthesis(request, status=None):
        retrosynthesis_requests.append((request, status))
        return _successful_retrosynthesis_result()

    monkeypatch.setattr(candidate_assessment, "run_external_docking", fake_external_docking)
    monkeypatch.setattr(candidate_assessment, "run_aizynthfinder_retrosynthesis", fake_retrosynthesis)

    receptor_file = tmp_path / "egfr_receptor.pdb"
    receptor_file.write_text("HEADER    TEST RECEPTOR\n", encoding="utf-8")

    with make_client(tmp_path) as client:
        project_id = create_filtered_project(client)
        response = client.post(
            f"/projects/{project_id}/candidate-assessment/run",
            json={
                "assessment_mode": "full",
                "max_molecules": 2,
                "top_n": 2,
                "protein_file": str(receptor_file),
                "grid_center": [1.0, 2.0, 3.0],
                "grid_size": [18.0, 18.0, 18.0],
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["assessment_mode"] == "full"
        assert body["docking"]["adapter_mode"] == "gnina_docker_docking"
        assert body["synthesis"]["adapter_mode"] == "aizynthfinder_docker"
        assert len(docking_requests) == 2
        assert len(retrosynthesis_requests) == 2


def test_candidate_assessment_uses_aizynthfinder_when_available(tmp_path, monkeypatch):
    original_tool_status = candidate_assessment.candidate_assessment_tool_status
    retrosynthesis_requests = []

    def fake_tool_status():
        status = original_tool_status()
        status["aizynthfinder"] = {
            "available": True,
            "mode": "docker",
            "version": None,
            "path": None,
            "docker_image": "aizynthfinder:latest",
            "model_configured": True,
        }
        status["askcos"] = {"available": False, "version": None}
        status["chemprop"] = {"available": False, "mode": None, "version": None}
        return status

    def fake_retrosynthesis(request, status=None):
        retrosynthesis_requests.append((request, status))
        return AiZynthFinderResult(
            adapter_mode="aizynthfinder_docker",
            tool_name="aizynthfinder",
            success=True,
            route_found=True,
            num_steps=2,
            route_score=0.84,
            route_summary="AiZynthFinder found a route in 2 steps; top score=0.84.",
            labels=["aizynthfinder_executed", "aizynthfinder_route"],
        )

    monkeypatch.setattr(candidate_assessment, "candidate_assessment_tool_status", fake_tool_status)
    monkeypatch.setattr(
        candidate_assessment,
        "run_aizynthfinder_retrosynthesis",
        fake_retrosynthesis,
    )

    with make_client(tmp_path) as client:
        project_id = create_filtered_project(client)

        response = client.post(
            f"/projects/{project_id}/candidate-assessment/run",
            json={
                "assessment_mode": "full",
                "max_molecules": 2,
                "top_n": 2,
                "max_synthesis_steps": 5,
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["synthesis"]["adapter_mode"] == "aizynthfinder_docker"
        assert body["synthesis"]["evaluated_count"] == 2
        assert len(retrosynthesis_requests) == 2

        synthesis = client.get(f"/projects/{project_id}/synthesis-routes").json()
        assert len(synthesis) == 2
        assert all(item["route_found"] is True for item in synthesis)
        assert all(item["route_steps"] == 2 for item in synthesis)
        assert all(item["route_json"]["adapter_mode"] == "aizynthfinder_docker" for item in synthesis)
        assert all(item["route_json"]["route_score"] == 0.84 for item in synthesis)
        assert all("external_retrosynthesis_adapter_used" in item["labels"] for item in synthesis)
        assert all("external_retrosynthesis_adapter_pending" not in item["labels"] for item in synthesis)
        assert all("rdkit_surrogate_synthesis" not in item["labels"] for item in synthesis)
