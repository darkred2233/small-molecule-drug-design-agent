"""Report only the project-local chemistry runtimes used by MedAgent."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def collect_status() -> dict[str, dict[str, Any]]:
    from medagent.services.admet_adapter import check_chemprop_available
    from medagent.services.aizynthfinder_adapter import aizynthfinder_tool_status
    from medagent.services.autogrow4_adapter import autogrow4_tool_status
    from medagent.services.docking_adapters import check_gnina_available, check_vina_available
    from medagent.services.molecule_generation import generation_tool_status

    generation = generation_tool_status()
    return {
        "rdkit": generation["rdkit"],
        "crem": generation["crem"],
        "admet_ai": check_chemprop_available(),
        "gnina": check_gnina_available(),
        "vina": check_vina_available(),
        "targetdiff": generation["targetdiff"],
        "autogrow4": autogrow4_tool_status(),
        "aizynthfinder": aizynthfinder_tool_status(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Check project-local chemistry tools")
    parser.add_argument("--json", action="store_true", help="emit machine-readable status")
    parser.add_argument(
        "--strict", action="store_true", help="fail unless core local tools are available"
    )
    args = parser.parse_args()
    status = collect_status()
    if args.json:
        print(json.dumps(status, indent=2, ensure_ascii=False, default=str))
    else:
        for name, result in status.items():
            mark = "OK" if result.get("available") else "MISSING"
            detail = (
                result.get("path") or result.get("python_executable") or result.get("warning") or ""
            )
            print(f"{mark:7} {name:14} {detail}")
    if args.strict:
        required = (
            "rdkit",
            "crem",
            "admet_ai",
            "gnina",
            "vina",
            "targetdiff",
            "autogrow4",
            "aizynthfinder",
        )
        return 0 if all(status[name].get("available") for name in required) else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
