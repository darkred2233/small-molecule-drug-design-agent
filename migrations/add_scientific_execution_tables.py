#!/usr/bin/env python3
"""Add provenance tables and reproducibility fields for scientific execution."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from medagent.core.config import get_settings
from medagent.db.models import Base


def _database_url(cli_database_url: str | None = None) -> str:
    return cli_database_url or os.getenv("MEDAGENT_DATABASE_URL") or get_settings().database_url


def _binding_site_columns(dialect_name: str) -> dict[str, str]:
    json_type = "JSONB DEFAULT '[]'::jsonb" if dialect_name == "postgresql" else "JSON DEFAULT '[]'"
    return {
        "structure_id": "VARCHAR(80)",
        "reference_ligand_id": "VARCHAR(80)",
        "pocket_residues_json": json_type,
        "pocket_method": "VARCHAR(80)",
        "validation_status": "VARCHAR(80) DEFAULT 'unvalidated'",
        "redock_rmsd": "FLOAT",
        "artifact_id": "VARCHAR(80)",
    }


def apply_migration(database_url: str | None = None) -> dict[str, list[str]]:
    engine = create_engine(_database_url(database_url))
    before = set(inspect(engine).get_table_names())
    added_columns: list[str] = []

    if "binding_sites" in before:
        existing = {column["name"] for column in inspect(engine).get_columns("binding_sites")}
        with engine.begin() as connection:
            for column, column_type in _binding_site_columns(engine.dialect.name).items():
                if column in existing:
                    continue
                connection.execute(text(f"ALTER TABLE binding_sites ADD COLUMN {column} {column_type}"))
                added_columns.append(column)

    Base.metadata.create_all(bind=engine)
    after = set(inspect(engine).get_table_names())
    return {
        "added_columns": added_columns,
        "created_tables": sorted(after - before),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url")
    args = parser.parse_args()
    print(apply_migration(args.database_url))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
