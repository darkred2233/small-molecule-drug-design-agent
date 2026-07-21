#!/usr/bin/env python3
"""Add molecule lineage fields and the persisted round report table."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from medagent.core.config import get_settings
from medagent.db.models import RoundReport


def _database_url(cli_database_url: str | None = None) -> str:
    return cli_database_url or os.getenv("MEDAGENT_DATABASE_URL") or get_settings().database_url


def apply_migration(database_url: str | None = None) -> dict[str, object]:
    engine = create_engine(_database_url(database_url))
    inspector = inspect(engine)
    if not inspector.has_table("molecules"):
        raise RuntimeError("Table 'molecules' does not exist.")

    existing_columns = {column["name"] for column in inspector.get_columns("molecules")}
    required_columns = {
        "campaign_run_id": "VARCHAR(80)",
        "generation_method": "VARCHAR(80)",
        "parent_molecule_ids": "JSON",
        "provenance_json": "JSON",
        "generation_metadata_json": "JSON",
    }
    added_columns: list[str] = []
    report_table_existed = inspector.has_table("round_reports")
    with engine.begin() as connection:
        for column_name, column_type in required_columns.items():
            if column_name in existing_columns:
                continue
            connection.execute(text(f"ALTER TABLE molecules ADD COLUMN {column_name} {column_type}"))
            added_columns.append(column_name)
        RoundReport.__table__.create(bind=connection, checkfirst=True)
    return {
        "added_columns": added_columns,
        "round_reports_created": not report_table_existed,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url")
    args = parser.parse_args()
    print(apply_migration(args.database_url))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
