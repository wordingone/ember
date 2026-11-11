# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Red for hf_inventory.reconcile_totals (lead 83196): after == before - excluded, the set counted is named, and after > before refuses."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from lane_config import LANE_ROOT
import os, sys, json, copy
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import hf_inventory as H

res = []
def chk(name, cond):
    res.append((name, bool(cond))); print(("PASS " if cond else "FAIL ") + name)

def mk():
    return {"repos": {
        "train": {"stages": {"train_ready": {"text": {"tokens": 900, "files": 10, "docs": 50, "shards_in_manifests": 9, "tokens_before_h19_exclusion": 1000, "h19_excluded_tokens": 100}}}},
        "public": {"stages": {"train_ready": {"text": {"tokens": 70, "files": 3, "shards_in_manifests": 2}}}}},
        "totals": {"train_ready/text": {"tokens": 970, "files": 13, "docs": 50, "shards_in_manifests": 11, "tokens_before_h19_exclusion": 1000, "h19_excluded_tokens": 100}}}

r = mk(); H.reconcile_totals(r); t = r["totals"]["train_ready/text"]
chk("a) before counts the same set as tokens (train + public): 1070", t["tokens_before_h19_exclusion"] == 1070)
chk("b) after == before - excluded and after <= before", t["tokens"] == t["tokens_before_h19_exclusion"] - t["h19_excluded_tokens"] and t["tokens"] <= t["tokens_before_h19_exclusion"])
chk("c) sets_counted names train and public with their tokens", t["sets_counted"]["train"]["tokens"] == 900 and t["sets_counted"]["public"]["tokens"] == 70 and t["sets_counted"]["public"]["h19_aware"] is False)
a = copy.deepcopy(t); H.reconcile_totals(r); chk("d) idempotent", r["totals"]["train_ready/text"] == a)
r = mk(); r["totals"]["train_ready/text"]["tokens"] = 1200     # an after larger than before must refuse
try: H.reconcile_totals(r); ok = False
except SystemExit: ok = True
chk("e) tokens above before - excluded refuses (SystemExit)", ok)
r = mk(); r["repos"]["public"]["stages"]["train_ready"]["text"]["tokens"] = 0; r["totals"]["train_ready/text"]["tokens"] = 900
H.reconcile_totals(r); chk("f) no public shards: before == 1000", r["totals"]["train_ready/text"]["tokens_before_h19_exclusion"] == 1000)
# the real file, if present
p = (LANE_ROOT + "/census/census-latest.json")
if os.path.exists(p):
    d = json.load(open(p)); H.reconcile_totals(d); t = d["totals"]["train_ready/text"]
    chk("g) the live census-latest.json reconciles: after == before - excluded", t["tokens"] == t["tokens_before_h19_exclusion"] - t["h19_excluded_tokens"])
src = open(os.path.join(os.path.dirname(HERE), "hf_inventory.py"), encoding="utf-8").read()
chk("w) main() calls reconcile_totals before writing", "    reconcile_totals(res)" in src)
bad = [n for n, c in res if not c]
print("FAILCOUNT", len(bad), "of", len(res)); print("ALL PASS" if not bad else "FAILED"); sys.exit(1 if bad else 0)
