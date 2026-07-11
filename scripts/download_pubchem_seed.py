import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

from medagent.data.seed_catalog import TARGET_CATALOG


PUBCHEM_PROPERTY_URL = (
    "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/"
    "{name}/property/CanonicalSMILES,IsomericSMILES,InChIKey/JSON"
)


def fetch_pubchem_properties(drug_name: str) -> dict:
    quoted_name = urllib.parse.quote(drug_name)
    url = PUBCHEM_PROPERTY_URL.format(name=quoted_name)
    with urllib.request.urlopen(url, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))
    properties = payload["PropertyTable"]["Properties"][0]
    return {
        "pubchem_cid": properties.get("CID"),
        "canonical_smiles": properties.get("CanonicalSMILES"),
        "isomeric_smiles": properties.get("IsomericSMILES"),
        "inchi_key": properties.get("InChIKey"),
        "external_refs": {"pubchem": f"https://pubchem.ncbi.nlm.nih.gov/compound/{properties.get('CID')}"},
    }


def empty_pubchem_properties(drug_name: str) -> dict:
    return {
        "pubchem_cid": None,
        "canonical_smiles": None,
        "isomeric_smiles": None,
        "inchi_key": None,
        "external_refs": {"pubchem_search": f"https://pubchem.ncbi.nlm.nih.gov/#query={drug_name}"},
    }


def build_seed_library() -> list[dict]:
    library = []
    for target in TARGET_CATALOG:
        drugs = []
        for drug_name, drug_status, mechanism, indication in target["drugs"]:
            try:
                pubchem = fetch_pubchem_properties(drug_name)
            except Exception as exc:
                print(f"Warning: failed to fetch PubChem properties for {drug_name}: {exc}", file=sys.stderr)
                pubchem = empty_pubchem_properties(drug_name)
            drugs.append(
                {
                    "drug_name": drug_name,
                    "drug_status": drug_status,
                    "mechanism": mechanism,
                    "indication": indication,
                    "smiles": pubchem["canonical_smiles"],
                    "canonical_smiles": pubchem["canonical_smiles"],
                    "isomeric_smiles": pubchem["isomeric_smiles"],
                    "inchi_key": pubchem["inchi_key"],
                    "pubchem_cid": pubchem["pubchem_cid"],
                    "evidence_source": "MVP seed catalog + PubChem PUG REST",
                    "external_refs": pubchem["external_refs"],
                }
            )
            time.sleep(0.2)
        library.append({**target, "drugs": drugs})
    return library


def main() -> None:
    output = Path("src/medagent/data/target_drug_library.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    library = build_seed_library()
    output.write_text(json.dumps(library, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {output} with {len(library)} targets")


if __name__ == "__main__":
    main()
