from pathlib import Path

from fastapi.testclient import TestClient

import medagent.api.app as api_app
from medagent.api.app import create_app
from medagent.core.config import Settings
from medagent.db.models import (
    ADMETResult,
    AgentRun,
    AdvisorSuggestion,
    BindingSite,
    ConformerResult,
    ConversationMessage,
    Critique,
    DecisionCard,
    DockingResult,
    EvidenceLink,
    Molecule,
    MoleculeProperty,
    OptimizationConstraint,
    RagChunk,
    RagDocument,
    Ranking,
    ReasoningTrace,
    RuleFilterResult,
    SeedLigand,
    SynthesisRoute,
    Target,
    UploadedFile,
)


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
        egfr = next(target for target in targets if target["target_id"] == "TGT-EGFR")
        assert egfr["pdb_ids"]
        assert egfr["pocket_summary"]
        assert egfr["binding_sites"]
        assert egfr["binding_sites"][0]["grid_box"]["center"]
        assert egfr["sar_rules"]
        assert egfr["admet_risks"]
        assert egfr["seed_ligand_count"] > 0
        assert all(drug["smiles"] for drug in egfr["drugs"])

        her2 = next(target for target in targets if target["target_id"] == "TGT-HER2")
        assert her2["seed_ligand_count"] >= 3
        assert {drug["drug_name"] for drug in her2["drugs"]} >= {"lapatinib", "neratinib", "tucatinib"}
        assert all(drug["smiles"] and drug["pubchem_cid"] for drug in her2["drugs"])
        assert her2["binding_sites"]
        assert her2["binding_sites"][0]["pdb_id"] == "3PP0"
        assert her2["binding_sites"][0]["grid_box"]["center"]
        assert her2["sar_rules"]
        assert her2["admet_risks"]


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
        seed_response = client.get(f"/projects/{project_id}/seed-ligands")
        assert seed_response.status_code == 200
        seed_ligands = seed_response.json()
        assert len(seed_ligands) > 0
        assert all(ligand["smiles"] for ligand in seed_ligands)

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


def test_delete_project_removes_project_scoped_records_and_artifacts(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'delete.db'}",
        storage_local_root=str(tmp_path / "uploads"),
    )
    app = create_app(settings)

    with TestClient(app) as client:
        project_id = client.post(
            "/projects",
            json={
                "name": "Delete cascade",
                "target_id": "TGT-EGFR",
                "objective": "verify cleanup",
            },
        ).json()["project_id"]

        upload_file = tmp_path / "uploads" / project_id / "FILE-DELETE" / "seed.smi"
        upload_file.parent.mkdir(parents=True)
        upload_file.write_text("CCO ethanol\n", encoding="utf-8")

        report_dir = tmp_path / ".local" / "reports" / project_id
        report_dir.mkdir(parents=True)
        (report_dir / "report.json").write_text("{}", encoding="utf-8")

        with api_app.SessionLocal() as db:
            target_site_count = db.query(BindingSite).filter(BindingSite.project_id.is_(None)).count()
            db.add_all(
                [
                    UploadedFile(
                        file_id="FILE-DELETE",
                        project_id=project_id,
                        filename="seed.smi",
                        file_type="text/plain",
                        storage_path=f"local://{upload_file}",
                    ),
                    ConversationMessage(
                        message_id="MSG-DELETE",
                        project_id=project_id,
                        role="user",
                        content="delete me",
                    ),
                    OptimizationConstraint(
                        constraint_id="CONS-DELETE",
                        project_id=project_id,
                        label="delete",
                    ),
                    Molecule(
                        molecule_id="MOL-DELETE",
                        project_id=project_id,
                        smiles="CCO",
                    ),
                    MoleculeProperty(molecule_id="MOL-DELETE", mw=46.07),
                    RuleFilterResult(
                        filter_result_id="FILTER-DELETE",
                        project_id=project_id,
                        molecule_id="MOL-DELETE",
                        decision="pass",
                    ),
                    ConformerResult(molecule_id="MOL-DELETE", conformer_generated=True),
                    DockingResult(molecule_id="MOL-DELETE", vina_score=-7.1),
                    ADMETResult(molecule_id="MOL-DELETE", hERG_risk="low"),
                    SynthesisRoute(molecule_id="MOL-DELETE", route_found=True),
                    Critique(
                        critique_id="CRIT-DELETE",
                        molecule_id="MOL-DELETE",
                        risk_level="low",
                        reason="cleanup check",
                    ),
                    RagDocument(
                        document_id="DOC-DELETE",
                        project_id=project_id,
                        title="Delete doc",
                        document_type="upload",
                    ),
                    RagChunk(
                        chunk_id="CHK-DELETE",
                        document_id="DOC-DELETE",
                        content="cleanup evidence",
                    ),
                    EvidenceLink(
                        evidence_id="EVD-DELETE",
                        molecule_id="MOL-DELETE",
                        chunk_id="CHK-DELETE",
                        claim_type="cleanup",
                    ),
                    AgentRun(
                        agent_run_id="RUN-DELETE",
                        project_id=project_id,
                        agent_name="cleanup_agent",
                    ),
                    ReasoningTrace(
                        trace_id="TRACE-DELETE",
                        project_id=project_id,
                        molecule_id="MOL-DELETE",
                        claim="cleanup trace",
                    ),
                    DecisionCard(
                        decision_id="CARD-DELETE",
                        project_id=project_id,
                        molecule_id="MOL-DELETE",
                        trace_id="TRACE-DELETE",
                        title="Cleanup",
                        decision="remove",
                        summary="cleanup card",
                    ),
                    AdvisorSuggestion(
                        suggestion_id="ADV-DELETE",
                        project_id=project_id,
                        summary="cleanup advice",
                        suggestions=[],
                        next_round_constraints=[],
                        suggested_generation_config={},
                    ),
                    Ranking(
                        project_id=project_id,
                        molecule_id="MOL-DELETE",
                        rank=1,
                        final_decision="remove",
                        score_breakdown={},
                    ),
                    BindingSite(
                        binding_site_id="SITE-DELETE",
                        project_id=project_id,
                        target_id="TGT-EGFR",
                    ),
                    SeedLigand(
                        ligand_id="LIG-DELETE",
                        project_id=project_id,
                        target_id="TGT-EGFR",
                        name="delete ligand",
                        smiles="CCO",
                    ),
                ]
            )
            db.commit()

        response = client.delete(f"/projects/{project_id}")

        assert response.status_code == 200
        assert client.get(f"/projects/{project_id}").status_code == 404
        assert project_id not in {item["project_id"] for item in client.get("/projects").json()}
        assert not (tmp_path / "uploads" / project_id).exists()
        assert not report_dir.exists()

        with api_app.SessionLocal() as db:
            assert db.query(Target).filter_by(target_id="TGT-EGFR").count() == 1
            assert db.query(BindingSite).filter(BindingSite.project_id.is_(None)).count() == target_site_count
            for model in [
                UploadedFile,
                ConversationMessage,
                OptimizationConstraint,
                Molecule,
                RuleFilterResult,
                RagDocument,
                AgentRun,
                ReasoningTrace,
                DecisionCard,
                AdvisorSuggestion,
                Ranking,
                BindingSite,
                SeedLigand,
            ]:
                assert db.query(model).filter_by(project_id=project_id).count() == 0
            for model in [
                MoleculeProperty,
                ConformerResult,
                DockingResult,
                ADMETResult,
                SynthesisRoute,
                Critique,
            ]:
                assert db.query(model).filter_by(molecule_id="MOL-DELETE").count() == 0
            assert db.query(RagChunk).filter_by(document_id="DOC-DELETE").count() == 0
            assert db.query(EvidenceLink).filter_by(evidence_id="EVD-DELETE").count() == 0


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
                "generation_config": {
                    "strategy_counts": {"reinvent4": 1, "crem": 1, "autogrow4": 0},
                    "top_n": 2,
                    "max_assessment_molecules": 4,
                    "assessment_mode": "fast",
                    "generate_when_seeds_exist": True,
                },
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
        assert len(rankings) == 2
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
        assert report["candidate_summary"]["seed_ligand_count"] > 0
        assert report["candidate_summary"]["binding_site_count"] > 0
        assert report["target_and_pocket_analysis"]["target"]["pocket_summary"]
        assert report["target_and_pocket_analysis"]["binding_sites"]
        assert report["target_and_pocket_analysis"]["seed_ligands"]
        assert report["sar_overview"]["target_sar_rules"]
        assert report["admet_overview"]["target_admet_risks"]
        assert report["synthesis_overview"]["result_count"] >= 2
        assert report["synthesis_overview"]["routes"]
        assert report["top_candidates"][0]["rule_filter"]
        assert report["top_candidates"][0]["admet"]
        assert report["top_candidates"][0]["synthesis"]
        assert report["top_candidates"][0]["refutation_chain"]
        assert Path(report["report_file"]).exists()

        download = client.get(f"/projects/{project_id}/report/download")
        assert download.status_code == 200
        assert download.headers["content-type"].startswith("application/json")
        assert "attachment" in download.headers["content-disposition"]
        assert download.json()["project_summary"]["project_id"] == project_id


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
