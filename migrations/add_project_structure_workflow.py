#!/usr/bin/env python3
"""Add project-scoped receptor structures and active selections."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from medagent.core.config import get_settings
from medagent.db.models import Base


def apply_migration(database_url: str | None = None) -> dict[str, list[str]]:
    url = database_url or os.getenv("MEDAGENT_DATABASE_URL") or get_settings().database_url
    engine = create_engine(url)
    before = set(inspect(engine).get_table_names())
    added_columns: list[str] = []
    if "projects" in before:
        existing = {column["name"] for column in inspect(engine).get_columns("projects")}
        with engine.begin() as connection:
            for column in ("active_structure_id", "active_binding_site_id"):
                if column not in existing:
                    connection.execute(text(f"ALTER TABLE projects ADD COLUMN {column} VARCHAR(80)"))
                    added_columns.append(column)
    if "project_structures" in before:
        existing = {
            column["name"] for column in inspect(engine).get_columns("project_structures")
        }
        definitions = {
            "prepared_receptor_file": "TEXT",
            "prepared_receptor_sha256": "VARCHAR(64)",
            "preparation_json": "JSON DEFAULT '{}'",
        }
        with engine.begin() as connection:
            for column, definition in definitions.items():
                if column not in existing:
                    connection.execute(
                        text(f"ALTER TABLE project_structures ADD COLUMN {column} {definition}")
                    )
                    added_columns.append(f"project_structures.{column}")
    Base.metadata.create_all(bind=engine)
    after = set(inspect(engine).get_table_names())
    return {"added_columns": added_columns, "created_tables": sorted(after - before)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url")
    args = parser.parse_args()
    print(apply_migration(args.database_url))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
