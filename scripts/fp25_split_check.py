"""fp25_split_check.py — CPU-only pre-dispatch check for the fp-25 recall eval.

Runs INSIDE the daemon's env (the same env the live eval will use): loads each
MBPP split via w1_mbpp.load_split, reports how many of the 28 recall ids each
split contains, and asserts the --task-ids-file filter on the target split
yields exactly the 28. No model load, no GPU. Prints FP25_SPLIT_CHECK_PASS
only if exactly one split contains all 28 and the filter is exact.
"""
import json
import sys

NC = "/mnt/b/M/avir/leo/state/nc-ladder"
sys.path.insert(0, f"{NC}/scripts")
from w1_mbpp import load_split  # noqa: E402
from w4_eval import filter_problems_by_ids  # noqa: E402

IDS_FILE = f"{NC}/ledger/views/fp25-recall-task-ids.txt"

want = set()
with open(IDS_FILE, encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if line:
            want.add(int(line.split(":")[-1]))
assert len(want) == 28, f"ids file has {len(want)} ids, want 28"

report = {"want": 28, "splits": {}}
full = []
for split in ("train", "validation", "test", "prompt"):
    try:
        probs = load_split(split, None)
        ids = {p["id"] for p in probs}
        n = len(want & ids)
        report["splits"][split] = {"size": len(ids), "contains": n}
        if n == 28:
            full.append(split)
    except Exception as e:  # noqa: BLE001 — report, don't crash the check
        report["splits"][split] = {"error": f"{type(e).__name__}: {e}"[:120]}

report["splits_with_all_28"] = full
ok = False
if full == ["train"]:
    probs = load_split("train", None)
    filtered = filter_problems_by_ids(probs, IDS_FILE)
    got = {p["id"] for p in filtered}
    report["filter_on_train"] = {"n": len(filtered), "exact": got == want}
    ok = got == want
print(json.dumps(report, indent=2), flush=True)
print("FP25_SPLIT_CHECK_PASS" if ok else "FP25_SPLIT_CHECK_FAIL", flush=True)
