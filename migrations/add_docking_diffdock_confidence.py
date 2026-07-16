#!/usr/bin/env python3
"""Add a dedicated DiffDock confidence column to docking results."""

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
    columns = {column["name"] for column in inspector.get_columns("docking_results")}
    if "diffdock_confidence" in columns:
        return False
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE docking_results ADD COLUMN diffdock_confidence FLOAT"))
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url")
    args = parser.parse_args()
    message = (
        "Applied docking_results.diffdock_confidence"
        if apply_migration(args.database_url)
        else "Already applied"
    )
    print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
