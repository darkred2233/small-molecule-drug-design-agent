import os
import sqlite3
import subprocess
import sys
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from medagent.api.app import create_app
from medagent.core.config import Settings
from medagent.db.models import Base, BindingSite, Target
from medagent.db.session import build_engine
from medagent.services.bootstrap import seed_builtin_targets
from medagent.services.database import ensure_relational_schema


def test_builtin_database_covers_mvp_targets(tmp_path):
    app = create_app(Settings(database_url=f"sqlite:///{tmp_path / 'test.db'}"))

    with TestClient(app) as client:
        response = client.get("/database/summary")

    assert response.status_code == 200
    summary = response.json()
    assert summary["target_count"] >= 50
    assert summary["drug_count"] >= 150
    assert set(summary["target_ids"]) >= {
        "TGT-EGFR",
        "TGT-ALK",
        "TGT-BRAF",
        "TGT-KRAS-G12C",
        "TGT-JAK2",
        "TGT-BTK",
        "TGT-CDK4-6",
        "TGT-PARP1",
        "TGT-PI3K",
        "TGT-HDAC",
        "TGT-HER2",
        "TGT-MET",
        "TGT-DPP4",
        "TGT-HMGCR",
        "TGT-HIV1-PROTEASE",
    }


def test_cli_creates_portable_sqlite_seed_database(tmp_path):
    output_db = tmp_path / "medagent_seed.sqlite"
    env = {**os.environ, "PYTHONPATH": "src"}

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "medagent.cli",
            "db",
            "init",
            "--database-url",
            f"sqlite:///{output_db}",
        ],
        check=False,
        capture_output=True,
        env=env,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert output_db.exists()

    with sqlite3.connect(output_db) as connection:
        target_count = connection.execute("select count(*) from targets").fetchone()[0]
        drug_count = connection.execute("select count(*) from target_drug_library").fetchone()[0]
        binding_site_count = connection.execute("select count(*) from binding_sites").fetchone()[0]
        target_pocket_count = connection.execute(
            "select count(*) from targets where pocket_summary is not null and pocket_summary != ''"
        ).fetchone()[0]
        drug_smiles_count = connection.execute(
            "select count(*) from target_drug_library where smiles is not null and smiles != ''"
        ).fetchone()[0]

    assert target_count >= 50
    assert drug_count >= 150
    assert binding_site_count >= 45
    assert target_pocket_count >= 50
    assert drug_smiles_count == drug_count


def test_builtin_seed_respects_postgres_foreign_keys():
    database_url = os.getenv("MEDAGENT_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("MEDAGENT_TEST_POSTGRES_URL is not configured")

    source_url = make_url(database_url)
    database_name = f"medagent_seed_test_{uuid4().hex}"
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
        with Session(test_engine, autoflush=False) as db:
            seed_builtin_targets(db)
            assert db.scalar(func.count(Target.id)) >= 50
            assert db.scalar(func.count(BindingSite.id)) >= 45
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


def test_pgvector_schema_creates_2048_dimension_embedding_column():
    database_url = os.getenv("MEDAGENT_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("MEDAGENT_TEST_POSTGRES_URL is not configured")

    source_url = make_url(database_url)
    database_name = f"medagent_pgvector_schema_test_{uuid4().hex}"
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

        ensure_relational_schema(test_engine)

        with test_engine.connect() as connection:
            embedding_type = connection.scalar(
                text(
                    "SELECT format_type(attribute.atttypid, attribute.atttypmod) "
                    "FROM pg_attribute attribute "
                    "WHERE attribute.attrelid = 'rag_chunks'::regclass "
                    "AND attribute.attname = 'embedding_vector'"
                )
            )
            index_names = {
                row[0]
                for row in connection.execute(
                    text("SELECT indexname FROM pg_indexes WHERE tablename = 'rag_chunks'")
                ).all()
            }

        assert embedding_type == "vector(2048)"
        assert "idx_rag_chunks_embedding_vector" not in index_names
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


def test_relational_schema_adds_llm_critique_columns_to_existing_sqlite(tmp_path):
    db_path = tmp_path / "legacy.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            create table critiques (
                id integer primary key,
                critique_id varchar(80),
                molecule_id varchar(80),
                risk_level varchar(80),
                reason text,
                evidence_ids json,
                refutation_decision varchar(80),
                created_at datetime,
                updated_at datetime
            )
            """
        )

    engine = build_engine(Settings(database_url=f"sqlite:///{db_path}"))
    ensure_relational_schema(engine)

    with sqlite3.connect(db_path) as connection:
        columns = {
            row[1]
            for row in connection.execute("pragma table_info(critiques)").fetchall()
        }

    assert {"con_score", "llm_critique_json", "llm_provider", "analysis_method"} <= columns
