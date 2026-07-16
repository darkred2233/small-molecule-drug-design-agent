import os
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

import medagent.pipeline.orchestrator as orchestrator_module
import medagent.reporting.project_report as project_report_module
from medagent.core.config import Settings
from medagent.db.models import AgentRun, Base, Molecule, Project
from medagent.db.session import build_engine, build_session_factory
from medagent.pipeline.orchestrator import PipelineOrchestrator


def _session_factory(tmp_path):
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'test.db'}")
    engine = build_engine(settings)
    Base.metadata.create_all(bind=engine)
    return settings, build_session_factory(settings)


def test_full_pipeline_executes_target_and_sar_before_generation(tmp_path, monkeypatch):
    settings, session_factory = _session_factory(tmp_path)

    monkeypatch.setattr(
        PipelineOrchestrator,
        "_run_knowledge_ingestion",
        lambda self, db, project: {"file_ingestion": {}, "rag_index": {}},
    )
    monkeypatch.setattr(
        orchestrator_module,
        "import_seed_ligands_as_molecules",
        lambda db, project: {"imported_count": 0},
    )
    monkeypatch.setattr(
        PipelineOrchestrator,
        "_run_target_analysis",
        lambda self, db, project: {"target_protein": project.target_id},
    )
    monkeypatch.setattr(
        PipelineOrchestrator,
        "_run_sar_analysis",
        lambda self, db, project: {"molecules_analyzed": 0},
    )
    monkeypatch.setattr(
        PipelineOrchestrator,
        "_run_generation_if_needed",
        lambda self, db, project, config: {"molecule_count": 0},
    )
    monkeypatch.setattr(
        orchestrator_module,
        "validate_project_molecules",
        lambda db, project: {"validated_count": 0},
    )
    monkeypatch.setattr(
        orchestrator_module,
        "filter_project_molecules",
        lambda db, project: {"passed_count": 0},
    )
    monkeypatch.setattr(
        orchestrator_module,
        "run_project_candidate_assessment",
        lambda db, project, **kwargs: {"assessed_count": 0},
    )
    monkeypatch.setattr(
        orchestrator_module,
        "generate_project_critiques",
        lambda db, project, **kwargs: {"critique_count": 0},
    )
    monkeypatch.setattr(
        orchestrator_module,
        "generate_project_rankings",
        lambda db, project, **kwargs: SimpleNamespace(as_dict=lambda: {"ranking_count": 0}),
    )
    monkeypatch.setattr(
        orchestrator_module,
        "generate_project_advice",
        lambda db, project: {"suggestion_count": 0},
    )
    monkeypatch.setattr(
        orchestrator_module,
        "generate_project_decision_cards",
        lambda db, project: {"decision_card_count": 0},
    )
    monkeypatch.setattr(
        orchestrator_module,
        "build_project_report",
        lambda db, project: {"project_id": project.project_id},
    )

    with session_factory() as db:
        project = Project(project_id="PROJ-FLOW", name="Pipeline flow", target_id="EGFR")
        db.add(project)
        db.commit()

        runs = PipelineOrchestrator(settings).run_full(db, project)
        names = [run.agent_name for run in runs]

    assert names.index("molecule_import_agent") < names.index("sar_agent")
    assert names.index("target_agent") < names.index("sar_agent")
    assert names.index("sar_agent") < names.index("generator_agent")


def test_target_and_sar_agents_return_rule_based_scientific_outputs(tmp_path):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        dashscope_api_key=None,
    )
    engine = build_engine(settings)
    Base.metadata.create_all(bind=engine)
    session_factory = build_session_factory(settings)

    with session_factory() as db:
        project = Project(project_id="PROJ-AGENT-RUN", name="Agent run", target_id="EGFR")
        db.add(project)
        db.flush()
        db.add(
            Molecule(
                molecule_id="MOL-AGENT-RUN",
                project_id=project.project_id,
                smiles="CCO",
                status="imported_from_seed",
                labels=[],
            )
        )
        db.commit()

        orchestrator = PipelineOrchestrator(settings)
        target_output = orchestrator._run_target_analysis(db, project)
        sar_output = orchestrator._run_sar_analysis(db, project)

    assert target_output["analysis_mode"] == "rule_based"
    assert target_output["target_protein"] == "EGFR"
    assert target_output["score_semantics"] == "heuristic_not_probability"
    assert sar_output["analysis_mode"] == "rule_based"
    assert sar_output["molecules_analyzed"] == 1
    assert sar_output["evidence_scope"] == "computational_docking_hypotheses"


def test_pipeline_step_database_error_records_failed_state_in_postgres():
    database_url = os.getenv("MEDAGENT_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("MEDAGENT_TEST_POSTGRES_URL is not configured")

    source_url = make_url(database_url)
    database_name = f"medagent_step_failure_test_{uuid4().hex}"
    admin_engine = create_engine(
        source_url.set(database="postgres"),
        isolation_level="AUTOCOMMIT",
    )
    test_engine = None
    try:
        with admin_engine.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{database_name}"'))

        test_engine = create_engine(source_url.set(database=database_name))
        Base.metadata.create_all(test_engine)

        with Session(test_engine) as db:
            project = Project(
                project_id="PROJ-STEP-FAILURE",
                name="Step failure",
                status="pipeline_running",
            )
            db.add(project)
            db.commit()

            orchestrator = PipelineOrchestrator(
                Settings(database_url=str(source_url.set(database=database_name)))
            )

            with pytest.raises(Exception):
                orchestrator._run_step(
                    db,
                    project,
                    "knowledge_ingestion_agent",
                    "qwen3.7-plus",
                    {"mode": "full"},
                    lambda: db.execute(text("SELECT * FROM definitely_missing_table")).all(),
                )

        with Session(test_engine) as db:
            saved_project = db.query(Project).filter_by(project_id="PROJ-STEP-FAILURE").one()
            saved_run = db.query(AgentRun).filter_by(project_id=saved_project.project_id).one()

        assert saved_project.status == "pipeline_failed"
        assert saved_run.status == "failed"
        assert "definitely_missing_table" in saved_run.error_message
    finally:
        if test_engine is not None:
            test_engine.dispose()
        with admin_engine.connect() as connection:
            connection.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :database_name AND pid <> pg_backend_pid()"
                ),
                {"database_name": database_name},
            )
            connection.execute(text(f'DROP DATABASE IF EXISTS "{database_name}"'))
        admin_engine.dispose()


def test_project_report_includes_target_and_sar_agent_outputs(tmp_path, monkeypatch):
    _, session_factory = _session_factory(tmp_path)
    monkeypatch.setattr(
        project_report_module,
        "_write_report_file",
        lambda project, report: str(tmp_path / "report.json"),
    )

    with session_factory() as db:
        project = Project(project_id="PROJ-REPORT-AGENTS", name="Agent report")
        db.add(project)
        db.flush()
        db.add_all(
            [
                AgentRun(
                    agent_run_id="RUN-TARGET",
                    project_id=project.project_id,
                    agent_name="target_agent",
                    model_name="rule_based",
                    status="completed",
                    input_json={},
                    output_json={"target_support_score": 0.8},
                ),
                AgentRun(
                    agent_run_id="RUN-SAR",
                    project_id=project.project_id,
                    agent_name="sar_agent",
                    model_name="rule_based",
                    status="completed",
                    input_json={},
                    output_json={"molecules_analyzed": 3},
                ),
            ]
        )
        db.commit()

        report = project_report_module.build_project_report(db, project)

    assert report["target_and_pocket_analysis"]["agent_analysis"]["target_support_score"] == 0.8
    assert report["sar_overview"]["agent_analysis"]["molecules_analyzed"] == 3
