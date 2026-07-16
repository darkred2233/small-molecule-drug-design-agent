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
    if "seed_ligands" not in inspector.get_table_names():
        return False
    columns = {column["name"] for column in inspector.get_columns("seed_ligands")}
    if "activity_type" in columns:
        return False
    with engine.begin() as connection:
        connection.execute(
            text("ALTER TABLE seed_ligands ADD COLUMN activity_type VARCHAR(40)")
        )
    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url")
    args = parser.parse_args()
    changed = apply_migration(args.database_url)
    print("migration_applied" if changed else "migration_not_needed")


if __name__ == "__main__":
    main()
