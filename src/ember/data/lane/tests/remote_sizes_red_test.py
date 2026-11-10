# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Reds/greens for remote_sizes + the ledger writer wiring (lead 82182 (4)). Run: python scripts/tests/remote_sizes_red_test.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from lane_config import LANE_ROOT
import os, sys, json, tempfile, shutil, time
pass
import remote_sizes as R
ok = True
def check(l, c):
    global ok; ok &= bool(c); print("PASS" if c else "FAIL", l)
src = R.lane_sources()
check("all 11 text lanes parsed from text_lane.py SPEC", sum(1 for k in src if k.startswith("text-")) == 11)
check("text-loc source parsed correctly", src["text-loc"][0] == "storytracer/LoC-PD-Books" and src["text-loc"][1] == "data")
T = tempfile.mkdtemp(dir=(LANE_ROOT + "/scratch")); R.CACHE = T + "/c.json"
files = {"data/train_00001.parquet": 100, "data/train_00002.parquet": 300}
c = R.refresh(["text-loc"], now=1000.0, lister=lambda *a: files)
check("GREEN refresh stores the REMOTE total", c["text-loc"]["bytes_expected"] == 400)
def boom(*a): raise RuntimeError("hf down")
c2 = R.refresh(["text-loc"], now=1000.0 + R.TTL_S + 1, lister=boom)
check("RED failed refresh keeps the stale value (no null, no crash)", c2["text-loc"]["bytes_expected"] == 400)
check("RED lane without a remote listing (bulk-pd12m) returns None, not an invented number", R.expected_done("bulk-pd12m", c2) == (None, None))
check("RED unknown cache entry returns None", R.expected_done("text-pubmed", {}) == (None, None))
os.makedirs(T + "/bulk/loc", exist_ok=True); json.dump({"done": {"data/train_00001.parquet": {"bytes": 999}}}, open(T + "/bulk/loc/state.json", "w"))
R.ROOT = T; x, d = R.expected_done("text-loc", c2)
check("GREEN done = REMOTE size of the files state.json marks done (same unit as expected)", (x, d) == (400, 100))
shutil.rmtree(T, ignore_errors=True)
L = (LANE_ROOT + "/loops/sources-ledger.jsonl"); rows = [json.loads(l) for l in open(L, encoding="utf-8") if l.strip()]
pass; import importlib; R2 = importlib.reload(R)
miss = [r["name"] for r in rows if r["state"] == "downloading" and r["name"] in R2.lane_sources() and r["bytes_expected"] is None]
check(f"live ledger: every downloading row with a remote listing has bytes_expected (missing: {miss})", not miss)
check("writer is wired (sources_ledger imports remote_sizes)", "remote_sizes" in open((LANE_ROOT + "/scripts/sources_ledger.py"), encoding="utf-8").read())
print("ALL PASS" if ok else "FAILED"); sys.exit(0 if ok else 1)
