from fastapi.testclient import TestClient

import medagent.services.rule_filtering as rule_filtering
from medagent.api.app import create_app
from medagent.core.config import Settings
from medagent.db.models import Molecule, MoleculeProperty, Project
from medagent.services.rdkit_adapter import RdkitCatalogMatch
from medagent.services.rule_filtering import evaluate_molecule_rules


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
        assert summary["rule_set"] == "target_aware_drug_likeness_v2"
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


def test_hdac_seed_ligands_are_not_all_rejected_by_target_required_alerts(tmp_path):
    with make_client(tmp_path) as client:
        project = client.post(
            "/projects",
            json={
                "name": "HDAC target-aware filtering",
                "target_id": "TGT-HDAC",
                "objective": "preserve zinc-binding HDAC pharmacophore",
            },
        ).json()
        project_id = project["project_id"]
        assert client.post(f"/projects/{project_id}/molecules/import-seeds").status_code == 201
        assert client.post(f"/projects/{project_id}/molecules/validate").status_code == 200

        summary = client.post(f"/projects/{project_id}/molecules/filter-rules").json()

        assert summary["evaluated_count"] >= 3
        assert summary["passed_count"] >= 1
        assert summary["failed_count"] < summary["evaluated_count"]
        assert summary["warning_count"] >= 1

        results = client.get(f"/projects/{project_id}/rule-filter-results").json()
        assert any(result["decision"] == "passed_with_warnings" for result in results)
        assert any(
            any(warning.startswith("target_allowed_rdkit_alert:") for warning in result["warnings"])
            for result in results
        )


def test_rule_filtering_is_idempotent(tmp_path):
    with make_client(tmp_path) as client:
        project_id = create_project_with_rule_filter_inputs(client)

        first = client.post(f"/projects/{project_id}/molecules/filter-rules").json()
        second = client.post(f"/projects/{project_id}/molecules/filter-rules").json()

        assert second["result_ids"] == first["result_ids"]
        results = client.get(f"/projects/{project_id}/rule-filter-results").json()
        assert len(results) == 3


def test_rule_filtering_rejects_lipinski_and_veber_standard_violations(monkeypatch):
    monkeypatch.setattr(rule_filtering, "find_rdkit_filter_matches", lambda _smiles: (True, []))
    molecule = Molecule(molecule_id="MOL-MW", project_id="PROJ", smiles="CCO", status="structure_validated", labels=[])
    properties = MoleculeProperty(
        molecule_id="MOL-MW",
        mw=510.0,
        logp=2.0,
        tpsa=80.0,
        hbd=1,
        hba=3,
        tool_metadata={"rotatable_bond_count": 3},
    )
    project = Project(project_id="PROJ", name="Rule filter", target_id="TGT-EGFR")

    evaluation = evaluate_molecule_rules(molecule, properties, project)

    assert evaluation.decision == "failed"
    assert "lipinski_mw_gt_500" in evaluation.failed_rules


def test_rule_filtering_rejects_cumulative_drug_likeness_violations(monkeypatch):
    monkeypatch.setattr(rule_filtering, "find_rdkit_filter_matches", lambda _smiles: (True, []))
    molecule = Molecule(molecule_id="MOL-MULTI", project_id="PROJ", smiles="CCO", status="structure_validated", labels=[])
    properties = MoleculeProperty(
        molecule_id="MOL-MULTI",
        mw=499.0,
        logp=5.4,
        tpsa=145.0,
        hbd=6,
        hba=11,
        tool_metadata={"rotatable_bond_count": 11},
    )
    project = Project(project_id="PROJ", name="Rule filter", target_id="TGT-EGFR")

    evaluation = evaluate_molecule_rules(molecule, properties, project)

    assert evaluation.decision == "failed"
    assert "drug_likeness_violation_count_ge_3" in evaluation.failed_rules
    assert evaluation.raw_output["drug_likeness_violation_count"] == 5


def test_rule_filtering_rejects_pains_alerts_even_for_target_allowed_descriptions(monkeypatch):
    def fake_catalog(_smiles):
        return True, [RdkitCatalogMatch(catalog="PAINS_A", description="hydroxamic_acid")]

    monkeypatch.setattr(rule_filtering, "find_rdkit_filter_matches", fake_catalog)
    molecule = Molecule(molecule_id="MOL-PAINS", project_id="PROJ", smiles="CCO", status="structure_validated", labels=[])
    properties = MoleculeProperty(
        molecule_id="MOL-PAINS",
        mw=220.0,
        logp=2.0,
        tpsa=80.0,
        hbd=1,
        hba=3,
        tool_metadata={"rotatable_bond_count": 3},
    )
    project = Project(project_id="PROJ", name="HDAC", target_id="TGT-HDAC")

    evaluation = evaluate_molecule_rules(molecule, properties, project)

    assert evaluation.decision == "failed"
    assert "rdkit_alert:PAINS_A:hydroxamic_acid" in evaluation.failed_rules
