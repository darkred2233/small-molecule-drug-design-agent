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


def create_project_with_rule_filter_inputs(client: TestClient) -> str:
    project = client.post(
        "/projects",
        json={
            "name": "Rule filtering",
            "target_id": "TGT-EGFR",
            "objective": "filter validated seed ligands",
        },
    ).json()
    project_id = project["project_id"]
    long_alkane = "C" * 50
    content = f"CCO ethanol\n{long_alkane} long_alkane\nC1CC unclosed_ring\n"

    upload_response = client.post(
        f"/projects/{project_id}/files",
        files={"file": ("rule_filtering.smi", content.encode(), "text/plain")},
    )
    assert upload_response.status_code == 202
    client.post(f"/projects/{project_id}/ingest")
    client.post(f"/projects/{project_id}/molecules/import-seeds")
    client.post(f"/projects/{project_id}/molecules/validate")
    return project_id


def test_rule_filtering_classifies_valid_failed_and_skipped_molecules(tmp_path):
    with make_client(tmp_path) as client:
        project_id = create_project_with_rule_filter_inputs(client)

        filter_response = client.post(f"/projects/{project_id}/molecules/filter-rules")

        assert filter_response.status_code == 200
        summary = filter_response.json()
        assert summary["rule_set"] == "basic_drug_likeness_v1"
        assert summary["evaluated_count"] == 2
        assert summary["passed_count"] == 1
        assert summary["failed_count"] == 1
        assert summary["skipped_count"] == 1

        molecules = client.get(f"/projects/{project_id}/molecules").json()
        by_smiles = {molecule["smiles"]: molecule for molecule in molecules}
        assert by_smiles["CCO"]["status"] == "passed_filter"
        assert "rule_filter_passed" in by_smiles["CCO"]["labels"]
        assert by_smiles["C" * 50]["status"] == "failed_filter"
        assert "lipinski_mw_gt_500" in by_smiles["C" * 50]["labels"]
        assert by_smiles["C1CC"]["status"] == "invalid_structure"

        results_response = client.get(f"/projects/{project_id}/rule-filter-results")
        assert results_response.status_code == 200
        results = results_response.json()
        assert len(results) == 3

        by_molecule_id = {result["molecule_id"]: result for result in results}
        cco_result = by_molecule_id[by_smiles["CCO"]["molecule_id"]]
        long_alkane_result = by_molecule_id[by_smiles["C" * 50]["molecule_id"]]
        invalid_result = by_molecule_id[by_smiles["C1CC"]["molecule_id"]]

        assert cco_result["decision"] == "passed"
        assert cco_result["failed_rules"] == []
        assert long_alkane_result["decision"] == "failed"
        assert "lipinski_mw_gt_500" in long_alkane_result["failed_rules"]
        assert invalid_result["decision"] == "skipped_invalid_structure"

        molecule_results_response = client.get(
            f"/projects/{project_id}/molecules/{by_smiles['CCO']['molecule_id']}/rule-filter-results"
        )
        assert molecule_results_response.status_code == 200
        assert molecule_results_response.json() == [cco_result]


def test_rule_filtering_is_idempotent(tmp_path):
    with make_client(tmp_path) as client:
        project_id = create_project_with_rule_filter_inputs(client)

        first = client.post(f"/projects/{project_id}/molecules/filter-rules").json()
        second = client.post(f"/projects/{project_id}/molecules/filter-rules").json()

        assert second["result_ids"] == first["result_ids"]
        results = client.get(f"/projects/{project_id}/rule-filter-results").json()
        assert len(results) == 3
