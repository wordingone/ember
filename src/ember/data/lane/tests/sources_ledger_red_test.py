# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Reds/greens for sources_ledger.py (D1, lead 82134; AT-LIB-6). Run: python scripts/tests/sources_ledger_red_test.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from lane_config import LANE_ROOT
import os, sys, json, tempfile, shutil
pass
import sources_ledger as S
ok = True
def check(l, c):
    global ok
    ok &= bool(c); print("PASS" if c else "FAIL", l)
base = dict(schema=S.SCHEMA, source_id="a", name="n", modality="text", licence_verdict="pending", state="queued", bytes_expected=None, bytes_done=0, link_job_id=None, eta_s=None, receipts=[], bytes_expected_reason="unknown size")
check("GREEN valid row", S.validate([base]) == [])
check("RED bad state refused", S.validate([dict(base, state="running")]) != [])
check("RED bad licence_verdict refused", S.validate([dict(base, licence_verdict="maybe")]) != [])
check("RED eta_s on a non-downloading row refused", S.validate([dict(base, eta_s=5, bytes_expected=10)]) != [])
check("RED eta_s without bytes_expected refused", S.validate([dict(base, state="downloading", eta_s=5)]) != [])
check("RED missing field refused", S.validate([{k: v for k, v in base.items() if k != "receipts"}]) != [])
check("RED null bytes_expected without a reason refused", S.validate([dict(base, bytes_expected_reason=None)]) != [])
check("RED known bytes_expected with a reason refused", S.validate([dict(base, bytes_expected=5)]) != [])
sm = S.summary([dict(base, name="a", state="downloading", bytes_expected=3 * 2**30, bytes_done=2**30, bytes_expected_reason=None), dict(base, name="bulk-ccby", state="downloading", bytes_expected=10**15, bytes_done=0, bytes_expected_reason=None)], now=1000.0)
check("GREEN summary: serial remaining excludes quota-bound lane", sm["bytes_remaining"] == 2 * 2**30 and sm["lanes_quota_bound_excluded"] == ["bulk-ccby"])
check("RED duplicate source_id refused", S.validate([base, dict(base, name="m")]) != [])
T = tempfile.mkdtemp(dir=(LANE_ROOT + "/scratch"))
try:
    for d in ("loops", "bulk/mls", "packed"): os.makedirs(f"{T}/{d}")
    json.dump({"bytes_uploaded": 100, "bytes_expected": 1000}, open(f"{T}/bulk/mls/progress.json", "w"))
    json.dump({"rx": 5_000_000, "t": 200.0}, open(f"{T}/loops/net-last.json", "w")); json.dump({"rx": 0, "t": 100.0, "bps": None}, open(f"{T}/loops/net-prev.json", "w"))
    S.ROOT = T; S._RS_OFF = True; S.cmdlines = lambda: ["python scripts/bulk_lane.py mls"]
    rs = S.rows(); m = [r for r in rs if r["name"] == "bulk-mls"][0]; bps = 5_000_000 / 100.0
    check("GREEN downloading lane: state + link job bound", m["state"] == "downloading" and m["link_job_id"])
    check("GREEN eta_s == bytes_remaining / measured_downlink (AT-LIB-6)", m["eta_s"] == round(900 / bps))
    q = [r for r in rs if r["name"] == "bulk-pd12m"][0]
    check("GREEN a lane with no process is queued with null eta", q["state"] == "queued" and q["eta_s"] is None)
    out = f"{T}/sources-ledger.jsonl"; S.write(out)
    check("GREEN atomic write: file present, no temp left", os.path.exists(out) and not [f for f in os.listdir(T) if f.endswith(".tmp")])
    check("GREEN written file re-validates", S.validate([json.loads(l) for l in open(out)]) == [])
finally:
    shutil.rmtree(T, ignore_errors=True)
print("ALL PASS" if ok else "FAILED"); sys.exit(0 if ok else 1)
