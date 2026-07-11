from __future__ import annotations

import sys
sys.path.insert(0, 'src')

from medagent.data.builtin_targets import BUILTIN_TARGETS
from medagent.data.collect_target_pack import TargetPackBuilder
from medagent.data.collectors.uniprot import UniProtCollector
from medagent.data.collectors.chembl import ChEMBLCollector
from medagent.data.collectors.pubchem import PubChemCollector
from medagent.data.collectors.pdb import PDBCollector
from medagent.data.collectors.pubmed import PubMedCollector
from medagent.data.collectors.safety import SafetyCollector
from medagent.data.collectors.clinical import ClinicalCollector

target = next(t for t in BUILTIN_TARGETS if t["target_id"] == "TGT-EGFR")
collectors = [
    ("uniprot", UniProtCollector()),
    ("chembl", ChEMBLCollector()),
    ("pubchem", PubChemCollector()),
    ("pdb", PDBCollector()),
    ("pubmed", PubMedCollector()),
    ("safety", SafetyCollector()),
    ("clinical", ClinicalCollector()),
]

for name, collector in collectors:
    print(f"=== {name} ===")
    try:
        results = collector.collect_target_pack(target)
        print(f"OK: {len(results)} results")
        for r in results[:2]:
            print(f"  - {r.title}: {r.content[:60].replace(chr(10), ' ')}")
    except Exception as exc:
        print(f"FAIL: {exc}")
    print()
