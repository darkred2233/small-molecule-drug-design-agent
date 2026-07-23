from fastapi.testclient import TestClient

from medagent.api.app import create_app
from medagent.core.config import Settings


def _client(tmp_path) -> TestClient:
    app = create_app(
        Settings(
            database_url=f"sqlite:///{tmp_path / 'scientific.db'}",
            dashscope_api_key=None,
            self_refutation_use_llm=False,
        )
    )
    return TestClient(app)


def test_scientific_preflight_reports_metadata_only_target_as_not_dock_ready(tmp_path):
    with _client(tmp_path) as client:
        package = client.get("/scientific/targets/TGT-EGFR/resource-package")
        assert package.status_code == 200
        assert package.json()["status"] == "metadata_ready"
        assert package.json()["resource"]["verified_pocket"] is False

        project = client.post(
            "/projects",
            json={"name": "Scientific EGFR", "target_id": "TGT-EGFR", "objective": "test"},
        )
        assert project.status_code == 201
        project_id = project.json()["project_id"]

        preflight = client.post(
            f"/scientific/projects/{project_id}/preflight",
            json={"require_external_evidence_for_ranking": True},
        )
        assert preflight.status_code == 200
        stages = {stage["stage"]: stage for stage in preflight.json()["plan"]["stages"]}
        assert stages["vina_screen"]["allowed"] is False
        assert stages["gnina_refine"]["allowed"] is False
        assert stages["ranking"]["allowed"] is False


def test_scientific_approval_can_be_decided_once(tmp_path):
    with _client(tmp_path) as client:
        project = client.post(
            "/projects",
            json={"name": "Approval EGFR", "target_id": "TGT-EGFR", "objective": "test"},
        )
        project_id = project.json()["project_id"]
        approval = client.post(
            f"/scientific/projects/{project_id}/approvals",
            json={"event_type": "allow_l1_final_candidate", "request": {"molecule_id": "MOL-1"}},
        )
        assert approval.status_code == 200

        decision = client.post(
            f"/scientific/approvals/{approval.json()['approval_id']}/decision",
            json={"approved": True, "decided_by": "reviewer", "rationale": "exploration only"},
        )
        assert decision.status_code == 200
        assert decision.json()["status"] == "approved"

        duplicate = client.post(
            f"/scientific/approvals/{approval.json()['approval_id']}/decision",
            json={"approved": False, "decided_by": "reviewer"},
        )
        assert duplicate.status_code == 409
