import json
from pathlib import Path
from typing import Any

from medagent.data.seed_catalog import TARGET_CATALOG
from medagent.data.target_metadata import get_target_metadata


def load_builtin_targets() -> list[dict[str, Any]]:
    seed_path = Path(__file__).with_name("target_drug_library.json")
    if seed_path.exists():
        return [_with_metadata(target) for target in json.loads(seed_path.read_text(encoding="utf-8"))]

    return [
        _with_metadata(
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
        )
        for target in TARGET_CATALOG
    ]


def get_builtin_target_ids() -> set[str]:
    return {target["target_id"] for target in load_builtin_targets()}


def _with_metadata(target: dict[str, Any]) -> dict[str, Any]:
    metadata = get_target_metadata(target.get("target_id"))
    return {
        **target,
        "pocket_summary": metadata.get("pocket_summary", target.get("pocket_summary")),
        "binding_sites": metadata.get("binding_sites", target.get("binding_sites", [])),
        "sar_rules": metadata.get("sar_rules", target.get("sar_rules", [])),
        "admet_risks": metadata.get("admet_risks", target.get("admet_risks", [])),
    }


BUILTIN_TARGETS = load_builtin_targets()
