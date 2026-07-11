from fastapi.testclient import TestClient

from medagent.api.app import create_app
from medagent.core.config import Settings


def make_client(tmp_path):
    app = create_app(Settings(database_url=f"sqlite:///{tmp_path / 'test.db'}"))
    return TestClient(app)


def test_builtin_targets_are_seeded(tmp_path):
    with make_client(tmp_path) as client:
        response = client.get("/builtin-targets")

        assert response.status_code == 200
        targets = response.json()
        assert any(target["target_id"] == "TGT-EGFR" for target in targets)


def test_create_project_and_parse_constraints(tmp_path):
    with make_client(tmp_path) as client:
        project_response = client.post(
            "/projects",
            json={
                "name": "EGFR lead optimization",
                "target_id": "TGT-EGFR",
                "objective": "lower hERG while preserving quinazoline scaffold",
            },
        )
        assert project_response.status_code == 201
        project_id = project_response.json()["project_id"]

        chat_response = client.post(
            f"/projects/{project_id}/chat",
            json={"message": "下一轮优先降低 hERG 风险，但保留 quinazoline 母核，只改 R6 位"},
        )

        assert chat_response.status_code == 200
        body = chat_response.json()
        assert body["created_constraints"]
        assert body["intent"] in {"avoid_risk", "keep_scaffold"}

        constraints_response = client.get(f"/projects/{project_id}/constraints")
        constraints = constraints_response.json()
        assert constraints_response.status_code == 200
        assert {item["label"] for item in constraints} >= {
            "penalty",
            "protected_motif",
            "editable_region",
        }


def test_project_router_uses_current_project_schema(tmp_path):
    with make_client(tmp_path) as client:
        project_response = client.post(
            "/projects/",
            json={
                "name": "Trailing slash project",
                "target_id": "TGT-EGFR",
                "objective": "verify project router schema",
            },
        )

        assert project_response.status_code == 201
        body = project_response.json()
        project_id = body["project_id"]
        assert body["name"] == "Trailing slash project"
        assert body["target_id"] == "TGT-EGFR"

        list_response = client.get("/projects")
        assert list_response.status_code == 200
        assert any(project["project_id"] == project_id for project in list_response.json())

        trailing_list_response = client.get("/projects/")
        assert trailing_list_response.status_code == 200
        assert any(project["project_id"] == project_id for project in trailing_list_response.json())

        detail_response = client.get(f"/projects/{project_id}")
        assert detail_response.status_code == 200
        assert detail_response.json()["objective"] == "verify project router schema"


def test_pipeline_dry_run_registers_agent_steps(tmp_path):
    with make_client(tmp_path) as client:
        project_id = client.post("/projects", json={"name": "KRAS program"}).json()["project_id"]

        response = client.post(f"/projects/{project_id}/run", json={"mode": "dry_run"})

        assert response.status_code == 202
        body = response.json()
        assert body["status"] == "pipeline_queued"
        assert len(body["agent_runs"]) >= 10
        assert any(run["agent_name"] == "self_refutation_agent" for run in body["agent_runs"])


def test_pipeline_full_runs_end_to_end(tmp_path):
    with make_client(tmp_path) as client:
        project_id = client.post(
            "/projects",
            json={
                "name": "Full pipeline",
                "target_id": "TGT-EGFR",
                "objective": "run the executable agent workflow",
            },
        ).json()["project_id"]

        upload_response = client.post(
            f"/projects/{project_id}/files",
            files={
                "file": (
                    "pipeline_seed.smi",
                    b"CCO ethanol\nCc1ccccc1 toluene\n",
                    "text/plain",
                )
            },
        )
        assert upload_response.status_code == 202

        response = client.post(f"/projects/{project_id}/run", json={"mode": "full"})

        assert response.status_code == 202
        body = response.json()
        assert body["status"] == "pipeline_completed"
        agent_names = [run["agent_name"] for run in body["agent_runs"]]
        assert "knowledge_ingestion_agent" in agent_names
        assert "filter_agent" in agent_names
        assert "candidate_assessment_agent" in agent_names
        assert "decision_card_agent" in agent_names
        pipeline_run_names = {
            "knowledge_ingestion_agent",
            "molecule_import_agent",
            "generator_agent",
            "validation_agent",
            "filter_agent",
            "candidate_assessment_agent",
            "decision_card_agent",
        }
        pipeline_runs = [
            run for run in body["agent_runs"] if run["agent_name"] in pipeline_run_names
        ]
        assert len(pipeline_runs) == 7
        assert all(run["status"] == "completed" for run in pipeline_runs)

        molecules = client.get(f"/projects/{project_id}/molecules").json()
        assert len(molecules) >= 2

        rankings = client.get(f"/projects/{project_id}/rankings").json()
        assert len(rankings) >= 2
        assert rankings[0]["overall_score"] >= rankings[-1]["overall_score"]

        decision_cards = client.get(f"/projects/{project_id}/decision-cards").json()
        assert len(decision_cards) >= 2
        assert all(card["trace_id"] for card in decision_cards)
