from __future__ import annotations

import sys
sys.path.insert(0, 'src')

from medagent.data.builtin_targets import BUILTIN_TARGETS
from medagent.data.collect_target_pack import TargetPackBuilder

target = next(t for t in BUILTIN_TARGETS if t["target_id"] == "TGT-EGFR")
print('file=', TargetPackBuilder.__module__)
builder = TargetPackBuilder(target)
print('normalized=', builder._normalize_drugs(target['drugs'])[:2])
pack_docs = builder.build()
print('doc_count=', len(pack_docs))
for doc in pack_docs[:5]:
    print('DOC:', doc.title, '|', doc.source, '|', doc.content[:80].replace('\n', ' '))
