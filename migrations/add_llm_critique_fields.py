#!/usr/bin/env python3
"""
Add LLM critique fields to the critiques table.

The script is intentionally idempotent: it inspects the target database and only
adds missing columns. It uses MEDAGENT_DATABASE_URL when set, otherwise the
project Settings.database_url value.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from medagent.core.config import get_settings


def _database_url(cli_database_url: str | None = None) -> str:
    return (
        cli_database_url
        or os.getenv("MEDAGENT_DATABASE_URL")
        or get_settings().database_url
    )


def _ddl_for_column(dialect_name: str, column_name: str) -> str:
    if column_name == "llm_critique_json":
        column_type = "JSONB" if dialect_name == "postgresql" else "JSON"
        return f"ALTER TABLE critiques ADD COLUMN {column_name} {column_type} DEFAULT NULL"
    if column_name == "llm_provider":
        return "ALTER TABLE critiques ADD COLUMN llm_provider VARCHAR(80) DEFAULT NULL"
    if column_name == "analysis_method":
        return (
            "ALTER TABLE critiques ADD COLUMN analysis_method VARCHAR(80) "
            "DEFAULT 'heuristic_self_refutation'"
        )
    raise ValueError(f"Unsupported column: {column_name}")


def apply_migration(database_url: str | None = None) -> list[str]:
    engine = create_engine(_database_url(database_url))
    inspector = inspect(engine)
    if not inspector.has_table("critiques"):
        raise RuntimeError("Table 'critiques' does not exist.")

    existing_columns = {
        column["name"]
        for column in inspector.get_columns("critiques")
    }
    required_columns = ["llm_critique_json", "llm_provider", "analysis_method"]
    missing_columns = [
        column_name
        for column_name in required_columns
        if column_name not in existing_columns
    ]

    applied: list[str] = []
    with engine.begin() as connection:
        for column_name in missing_columns:
            connection.execute(text(_ddl_for_column(engine.dialect.name, column_name)))
            applied.append(column_name)
        if engine.dialect.name == "postgresql" and "llm_critique_json" in applied:
            connection.execute(
                text(
                    "COMMENT ON COLUMN critiques.llm_critique_json IS "
                    "'LLM critique JSON payload'"
                )
            )
        if engine.dialect.name == "postgresql" and "llm_provider" in applied:
            connection.execute(
                text("COMMENT ON COLUMN critiques.llm_provider IS 'LLM provider name'")
            )
        if engine.dialect.name == "postgresql" and "analysis_method" in applied:
            connection.execute(
                text(
                    "COMMENT ON COLUMN critiques.analysis_method IS "
                    "'Actual critique execution method'"
                )
            )
    return applied


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", help="Override MEDAGENT_DATABASE_URL/Settings.database_url")
    args = parser.parse_args()

    applied = apply_migration(args.database_url)
    if applied:
        print(f"Applied migration columns: {', '.join(applied)}")
    else:
        print("Migration already applied; no columns were added.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
