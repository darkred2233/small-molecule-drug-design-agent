#!/usr/bin/env python3
"""Run every idempotent schema migration required by the current application."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))


def apply_all(database_url: str | None = None) -> dict[str, object]:
    from medagent.core.config import get_settings
    from migrations.add_docking_diffdock_confidence import (
        apply_migration as add_diffdock_confidence,
    )
    from migrations.add_docking_raw_output import apply_migration as add_docking_raw_output
    from migrations.add_llm_critique_fields import apply_migration as add_llm_critique_fields
    from migrations.add_round_provenance import apply_migration as add_round_provenance
    from migrations.add_seed_ligand_activity_type import apply_migration as add_activity_type

    url = database_url or os.getenv("MEDAGENT_DATABASE_URL") or get_settings().database_url
    return {
        "docking_raw_output": add_docking_raw_output(url),
        "docking_diffdock_confidence": add_diffdock_confidence(url),
        "seed_ligand_activity_type": add_activity_type(url),
        "llm_critique_fields": add_llm_critique_fields(url),
        "round_provenance": add_round_provenance(url),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url")
    args = parser.parse_args()
    results = apply_all(args.database_url)
    for migration, result in results.items():
        print(f"{migration}: {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
