#!/usr/bin/env python3
"""Add auditable raw output/provenance storage to docking results."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from medagent.core.config import get_settings


def apply_migration(database_url: str | None = None) -> bool:
    url = database_url or os.getenv("MEDAGENT_DATABASE_URL") or get_settings().database_url
    engine = create_engine(url)
    inspector = inspect(engine)
    if not inspector.has_table("docking_results"):
        raise RuntimeError("Table 'docking_results' does not exist.")
    if "raw_output" in {column["name"] for column in inspector.get_columns("docking_results")}:
        return False
    column_type = "JSONB" if engine.dialect.name == "postgresql" else "JSON"
    default = "'{}'::jsonb" if engine.dialect.name == "postgresql" else "'{}'"
    with engine.begin() as connection:
        connection.execute(
            text(f"ALTER TABLE docking_results ADD COLUMN raw_output {column_type} DEFAULT {default}")
        )
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url")
    args = parser.parse_args()
    print("Applied docking_results.raw_output" if apply_migration(args.database_url) else "Already applied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
