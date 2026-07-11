from medagent.data.builtin_targets import BUILTIN_TARGETS
from medagent.data.collect_target_pack import TargetPackBuilder

target = next(t for t in BUILTIN_TARGETS if t["target_id"] == "TGT-EGFR")
print("RAW DRUGS:", target["drugs"][:2])
builder = TargetPackBuilder(target)
print("NORMALIZED:", builder._normalize_drugs(target["drugs"])[:2])
payload = {**target, "drugs": builder._normalize_drugs(target["drugs"])}
print("PAYLOAD DRUGS TYPE:", type(payload["drugs"][0]))
