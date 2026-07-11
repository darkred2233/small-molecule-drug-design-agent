from pathlib import Path

from fastapi.testclient import TestClient

import medagent.api.app as api_app
from medagent.api.app import create_app
from medagent.core.config import Settings
from medagent.db.models import AdvisorSuggestion


def make_client(tmp_path):
    app = create_app(Settings(database_url=f"sqlite:///{tmp_path / 'test.db'}"))
    return TestClient(app)


def advisor_constraints(items):
    return [item for item in items if item["label"].startswith("advisor_")]


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
        assert "ranker_agent" in agent_names
        assert "self_refutation_agent" in agent_names
        assert "advisor_agent" in agent_names
        assert "decision_card_agent" in agent_names
        assert "report_agent" in agent_names
        pipeline_run_names = {
            "knowledge_ingestion_agent",
            "molecule_import_agent",
            "generator_agent",
            "validation_agent",
            "filter_agent",
            "candidate_assessment_agent",
            "ranker_agent",
            "self_refutation_agent",
            "advisor_agent",
            "decision_card_agent",
            "report_agent",
        }
        pipeline_runs = [
            run for run in body["agent_runs"] if run["agent_name"] in pipeline_run_names
        ]
        assert len(pipeline_runs) == 11
        assert all(run["status"] == "completed" for run in pipeline_runs)

        molecules = client.get(f"/projects/{project_id}/molecules").json()
        assert len(molecules) >= 2

        rankings = client.get(f"/projects/{project_id}/rankings").json()
        assert len(rankings) >= 2
        assert rankings[0]["overall_score"] >= rankings[-1]["overall_score"]

        decision_cards = client.get(f"/projects/{project_id}/decision-cards").json()
        assert len(decision_cards) >= 2
        assert all(card["trace_id"] for card in decision_cards)

        advice = client.get(f"/projects/{project_id}/advice").json()
        assert len(advice) == 1
        assert len(advice[0]["suggestions"]) >= 3
        assert advice[0]["next_round_constraints"]
        assert advice[0]["suggested_generation_config"]["rerank_after_generation"] is True

        constraints_before_apply = client.get(f"/projects/{project_id}/constraints").json()
        assert not advisor_constraints(constraints_before_apply)

        apply_response = client.post(f"/projects/{project_id}/advisor/apply")
        assert apply_response.status_code == 202
        applied = apply_response.json()
        assert applied["status"] == "applied"
        assert applied["suggestion_id"] == advice[0]["suggestion_id"]
        assert applied["applied_constraint_count"] == len(advice[0]["next_round_constraints"])
        assert applied["created_constraint_count"] == applied["applied_constraint_count"]
        assert applied["updated_constraint_count"] == 0
        assert applied["unchanged_constraint_count"] == 0
        assert applied["generation_payload"]["generation_request"]["generation_size"] == 50
        assert applied["generation_payload"]["generation_request"]["strategies"] == ["crem"]
        assert applied["generation_payload"]["rerank_after_generation"] is True

        constraints = client.get(f"/projects/{project_id}/constraints").json()
        assert len(advisor_constraints(constraints)) == applied["applied_constraint_count"]

        second_apply = client.post(f"/projects/{project_id}/advisor/apply").json()
        assert second_apply["created_constraint_count"] == 0
        assert second_apply["updated_constraint_count"] == 0
        assert second_apply["unchanged_constraint_count"] == applied["applied_constraint_count"]
        constraints_after_second_apply = client.get(f"/projects/{project_id}/constraints").json()
        assert (
            len(advisor_constraints(constraints_after_second_apply))
            == applied["applied_constraint_count"]
        )

        report = client.get(f"/projects/{project_id}/report").json()
        assert report["project_summary"]["project_id"] == project_id
        assert report["project_summary"]["status"] == "pipeline_completed"
        assert len(report["top_candidates"]) >= 2
        assert report["self_refutation"]["critique_count"] >= 2
        assert report["candidate_summary"]["top_molecule_count"] >= 2
        assert report["top_candidates"][0]["refutation_chain"]
        assert Path(report["report_file"]).exists()


def test_advisor_apply_requires_existing_advice(tmp_path):
    with make_client(tmp_path) as client:
        project_id = client.post(
            "/projects",
            json={
                "name": "Advisor apply guard",
                "target_id": "TGT-EGFR",
                "objective": "do not apply missing advice",
            },
        ).json()["project_id"]

        response = client.post(f"/projects/{project_id}/advisor/apply")

        assert response.status_code == 404
        assert "No advisor suggestion" in response.json()["detail"]


def test_advisor_apply_accepts_document_shaped_advice(tmp_path):
    with make_client(tmp_path) as client:
        project_id = client.post(
            "/projects",
            json={
                "name": "Advisor document shape",
                "target_id": "TGT-EGFR",
                "objective": "apply doc-shaped Advisor constraints",
            },
        ).json()["project_id"]

        with api_app.SessionLocal() as db:
            db.add(
                AdvisorSuggestion(
                    suggestion_id="ADV-DOC-SHAPE",
                    project_id=project_id,
                    summary="Doc-shaped Advisor output.",
                    suggestions=[],
                    next_round_constraints=[
                        {
                            "constraint_type": "hard_constraint",
                            "name": "protected_motif",
                            "value": "quinazoline_core",
                        },
                        {
                            "constraint_type": "soft_constraint",
                            "name": "cLogP",
                            "target_range": [1.5, 3.5],
                        },
                    ],
                    suggested_generation_config={
                        "generation_size": 15000,
                        "min_tanimoto_to_seed": 0.45,
                        "max_tanimoto_to_seed": 0.82,
                        "rerank_after_generation": True,
                    },
                )
            )
            db.commit()

        response = client.post(f"/projects/{project_id}/advisor/apply")

        assert response.status_code == 202
        applied = response.json()
        assert applied["applied_constraint_count"] == 2
        assert applied["generation_payload"]["generation_request"]["generation_size"] == 500
        assert applied["generation_payload"]["generation_config_normalization"] == {
            "requested_generation_size": 15000,
            "applied_generation_size": 500,
            "max_generation_size": 500,
        }
        generation_constraints = applied["generation_payload"]["generation_request"]["constraints"]
        assert generation_constraints["min_tanimoto_to_seed"] == 0.45
        assert generation_constraints["max_tanimoto_to_seed"] == 0.82
        assert len(generation_constraints["advisor_constraints"]) == 2

        constraints = advisor_constraints(client.get(f"/projects/{project_id}/constraints").json())
        assert {item["label"] for item in constraints} == {
            "advisor_protected_motif",
            "advisor_cLogP",
        }
        assert next(
            item for item in constraints if item["label"] == "advisor_cLogP"
        )["operator"] == "target_range"

        round_response = client.post(f"/projects/{project_id}/rounds")
        assert round_response.status_code == 202
        generator_runs = [
            run
            for run in round_response.json()["agent_runs"]
            if run["agent_name"] == "generator_agent"
        ]
        assert generator_runs[-1]["output_json"]["generation_payload"]["source_suggestion_id"] == (
            "ADV-DOC-SHAPE"
        )
