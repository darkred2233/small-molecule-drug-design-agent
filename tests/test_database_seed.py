import sqlite3
import subprocess
import sys
import os

from fastapi.testclient import TestClient

from medagent.api.app import create_app
from medagent.core.config import Settings


def test_builtin_database_covers_mvp_targets(tmp_path):
    app = create_app(Settings(database_url=f"sqlite:///{tmp_path / 'test.db'}"))

    with TestClient(app) as client:
        response = client.get("/database/summary")

    assert response.status_code == 200
    summary = response.json()
    assert summary["target_count"] >= 10
    assert summary["drug_count"] >= 30
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

    assert target_count >= 10
    assert drug_count >= 30
