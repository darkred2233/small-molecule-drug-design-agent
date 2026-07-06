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


def test_pipeline_dry_run_registers_agent_steps(tmp_path):
    with make_client(tmp_path) as client:
        project_id = client.post("/projects", json={"name": "KRAS program"}).json()["project_id"]

        response = client.post(f"/projects/{project_id}/run", json={"mode": "dry_run"})

        assert response.status_code == 202
        body = response.json()
        assert body["status"] == "pipeline_queued"
        assert len(body["agent_runs"]) >= 10
        assert any(run["agent_name"] == "self_refutation_agent" for run in body["agent_runs"])
