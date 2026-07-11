from __future__ import annotations

import argparse
import json
from pathlib import Path

from medagent.data.builtin_targets import BUILTIN_TARGETS


def main() -> None:
    parser = argparse.ArgumentParser(prog="collect_target_pack")
    parser.add_argument("--target-id", action="append", default=None)
    parser.add_argument("--output", default="database/target_packs.json")
    args = parser.parse_args()

    targets = BUILTIN_TARGETS
    if args.target_id:
        targets = [target for target in targets if target.get("target_id") in args.target_id]

    pack = []
    for target in targets:
        pack.append({
            "target_id": target.get("target_id"),
            "name": target.get("name"),
            "aliases": target.get("aliases", []),
            "uniprot_id": target.get("uniprot_id"),
            "species": target.get("species"),
            "pdb_ids": target.get("pdb_ids", []),
            "summary": target.get("summary"),
            "drugs": target.get("drugs", []),
            "chembl_target_id": target.get("chembl_target_id"),
            "pack_documents": [],
        })

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(pack, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote target pack metadata to {output}")


if __name__ == "__main__":
    main()
