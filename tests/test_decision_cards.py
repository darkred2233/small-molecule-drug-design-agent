from fastapi.testclient import TestClient

from medagent.api.app import create_app
from medagent.core.config import Settings
from medagent.db.models import Molecule
from medagent.api import app as api_app


def make_client(tmp_path):
    app = create_app(
        Settings(
            database_url=f"sqlite:///{tmp_path / 'test.db'}",
            storage_local_root=str(tmp_path / "uploads"),
        )
    )
    return TestClient(app)


def create_validated_project(client: TestClient) -> str:
    project = client.post(
        "/projects",
        json={"name": "Decision cards"},
    ).json()
    project_id = project["project_id"]
    client.post(
        f"/projects/{project_id}/files",
        files={
            "file": (
                "decision_cards.smi",
                b"CCO ethanol\nC1CC unclosed_ring\n",
                "text/plain",
            )
        },
    )
    client.post(f"/projects/{project_id}/ingest")
    client.post(f"/projects/{project_id}/molecules/import-seeds")
    client.post(f"/projects/{project_id}/molecules/validate")
    return project_id


def create_assessed_project(client: TestClient) -> str:
    project = client.post(
        "/projects",
        json={
            "name": "Assessed decision cards",
            "target_id": "TGT-EGFR",
            "objective": "rank candidates after docking, ADMET, and synthesis checks",
        },
    ).json()
    project_id = project["project_id"]
    upload_response = client.post(
        f"/projects/{project_id}/files",
        files={
            "file": (
                "assessed_decision_cards.smi",
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
    assessment_response = client.post(
        f"/projects/{project_id}/candidate-assessment/run",
        json={
            "assessment_mode": "fast",
            "max_molecules": 2,
            "top_n": 2,
            "max_synthesis_steps": 5,
        },
    )
    assert assessment_response.status_code == 200
    return project_id


def test_decision_cards_are_generated_from_validation_results(tmp_path):
    with make_client(tmp_path) as client:
        project_id = create_validated_project(client)

        response = client.post(f"/projects/{project_id}/decision-cards/generate")

        assert response.status_code == 201
        body = response.json()
        assert body["generated_count"] == 2
        assert body["trace_count"] == 2
        assert len(body["decision_card_ids"]) == 2

        cards_response = client.get(f"/projects/{project_id}/decision-cards")
        assert cards_response.status_code == 200
        cards = cards_response.json()
        assert len(cards) == 2

        molecules = client.get(f"/projects/{project_id}/molecules").json()
        by_smiles = {molecule["smiles"]: molecule for molecule in molecules}
        by_molecule_id = {card["molecule_id"]: card for card in cards}

        valid_card = by_molecule_id[by_smiles["CCO"]["molecule_id"]]
        assert valid_card["decision"] == "advance_to_rule_filter"
        assert valid_card["title"] == "进入规则过滤"
        assert valid_card["trace_id"]
        assert valid_card["evidence_ids"][0].startswith("DB:MOL:")
        assert valid_card["provenance"]["basis"] == "database_records"
        assert any("RDKit" in risk for risk in valid_card["risk"])

        invalid_card = by_molecule_id[by_smiles["C1CC"]["molecule_id"]]
        assert invalid_card["decision"] == "reject_for_structure"
        assert invalid_card["title"] == "结构异常，暂不推进"
        assert any("invalid" in factor for factor in invalid_card["support"])

        traces_response = client.get(f"/projects/{project_id}/reasoning-traces")
        assert traces_response.status_code == 200
        traces = traces_response.json()
        assert len(traces) == 2
        assert {trace["source_agent"] for trace in traces} == {"decision_card_generator"}


def test_unvalidated_decision_card_is_marked_as_hypothesis(tmp_path):
    with make_client(tmp_path) as client:
        project_id = client.post("/projects", json={"name": "Hypothesis card"}).json()[
            "project_id"
        ]
        with api_app.SessionLocal() as db:
            db.add(
                Molecule(
                    molecule_id="MOL-HYPOTHESIS",
                    project_id=project_id,
                    smiles="CCO",
                    status="generated",
                    labels=[],
                )
            )
            db.commit()

        response = client.post(f"/projects/{project_id}/decision-cards/generate")

        assert response.status_code == 201
        card = client.get(f"/projects/{project_id}/decision-cards").json()[0]
        assert card["provenance"]["claim_status"] == "hypothesis"
        assert card["provenance"]["confidence_semantics"] == "not_calibrated"
        assert card["confidence"] is None


def test_assessed_molecules_do_not_regress_to_validation_cards(tmp_path):
    with make_client(tmp_path) as client:
        project_id = create_assessed_project(client)

        response = client.post(f"/projects/{project_id}/decision-cards/generate")

        assert response.status_code == 201
        molecules = client.get(f"/projects/{project_id}/molecules").json()
        assessed_molecules = [
            molecule for molecule in molecules if molecule["status"] == "candidate_assessed"
        ]
        assert assessed_molecules

        cards = client.get(f"/projects/{project_id}/decision-cards").json()
        by_molecule_id = {card["molecule_id"]: card for card in cards}

        for molecule in assessed_molecules:
            card = by_molecule_id[molecule["molecule_id"]]
            assert card["decision"] != "needs_structure_validation"
            assert card["title"] != "Run structure validation"
            assert f"DB:PROP:{molecule['molecule_id']}" in card["evidence_ids"]
            assert "label=requires_structure_validation" not in card["support"]
            assert not any("structure validation before it can be judged" in risk for risk in card["risk"])
            assert not any("/molecules/validate" in step for step in card["next_steps"])


def test_assessed_decision_cards_are_condensed_in_chinese(tmp_path):
    with make_client(tmp_path) as client:
        project_id = create_assessed_project(client)

        response = client.post(f"/projects/{project_id}/decision-cards/generate")

        assert response.status_code == 201
        cards = client.get(f"/projects/{project_id}/decision-cards").json()
        watch_card = next(card for card in cards if card["decision"] == "watch_ranked_candidate")

        assert watch_card["title"] == "观察候选物"
        assert "保留观察" in watch_card["summary"]
        assert watch_card["support"]
        assert watch_card["risk"]
        assert watch_card["next_steps"]
        assert all(not item.startswith("label=") for item in watch_card["support"])
        assert all(not item.startswith("label=") for item in watch_card["risk"])
        assert all("No major surrogate route risk detected" not in item for item in watch_card["risk"])
        assert all("No major AiZynthFinder route risk detected" not in item for item in watch_card["risk"])
        assert len(watch_card["risk"]) == len(set(watch_card["risk"]))
        assert any(item.startswith("结构与理化性质：") for item in watch_card["support"])
        assert any(item.startswith("综合排名：") for item in watch_card["support"])
        assert any("外部对接" in item for item in watch_card["risk"])


def test_molecule_decision_cards_can_be_read_and_regenerated_idempotently(tmp_path):
    with make_client(tmp_path) as client:
        project_id = create_validated_project(client)

        first = client.post(f"/projects/{project_id}/decision-cards/generate").json()
        second = client.post(f"/projects/{project_id}/decision-cards/generate").json()

        assert second["decision_card_ids"] == first["decision_card_ids"]
        assert second["trace_ids"] == first["trace_ids"]

        molecules = client.get(f"/projects/{project_id}/molecules").json()
        molecule_id = molecules[0]["molecule_id"]
        molecule_cards_response = client.get(
            f"/projects/{project_id}/molecules/{molecule_id}/decision-cards"
        )

        assert molecule_cards_response.status_code == 200
        molecule_cards = molecule_cards_response.json()
        assert len(molecule_cards) == 1

        project_cards = client.get(f"/projects/{project_id}/decision-cards").json()
        project_traces = client.get(f"/projects/{project_id}/reasoning-traces").json()
        assert len(project_cards) == first["generated_count"]
        assert len(project_traces) == first["trace_count"]
