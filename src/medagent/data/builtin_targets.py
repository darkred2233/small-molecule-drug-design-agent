import json
from pathlib import Path
from typing import Any

from medagent.data.seed_catalog import TARGET_CATALOG


def load_builtin_targets() -> list[dict[str, Any]]:
    seed_path = Path(__file__).with_name("target_drug_library.json")
    if seed_path.exists():
        return json.loads(seed_path.read_text(encoding="utf-8"))

    return [
        {
            **target,
            "drugs": [
                {
                    "drug_name": drug_name,
                    "drug_status": drug_status,
                    "mechanism": mechanism,
                    "indication": indication,
                    "smiles": None,
                    "canonical_smiles": None,
                    "isomeric_smiles": None,
                    "inchi_key": None,
                    "pubchem_cid": None,
                    "evidence_source": "MVP seed catalog",
                    "external_refs": {},
                }
                for drug_name, drug_status, mechanism, indication in target["drugs"]
            ],
        }
        for target in TARGET_CATALOG
    ]


BUILTIN_TARGETS = load_builtin_targets()
