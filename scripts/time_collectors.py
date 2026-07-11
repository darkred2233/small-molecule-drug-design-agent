from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
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
    start = time.time()
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(collector.collect_target_pack, target)
            results = future.result(timeout=15)
        elapsed = time.time() - start
        print(f"OK: {len(results)} results in {elapsed:.1f}s")
        for r in results[:2]:
            print(f"  - {r.title}: {(r.content or '')[:80].replace(chr(10), ' ')}")
    except FutureTimeoutError:
        elapsed = time.time() - start
        print(f"TIMEOUT after {elapsed:.1f}s")
    except Exception as exc:
        elapsed = time.time() - start
        print(f"FAIL after {elapsed:.1f}s: {exc}")
    print()
