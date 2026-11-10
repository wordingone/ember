# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Reds/greens for the clear_uploaded_shards class guard (lead 82108). Run: python scripts/tests/clear_shards_red_test.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from lane_config import LANE_ROOT
import os, sys, json, tempfile, shutil
pass
import clear_uploaded_shards as C
ok = True
def check(l, c):
    global ok
    ok &= bool(c); print("PASS" if c else "FAIL", l)
consumed = {"v1-00000-aaaaaaaaaaaa.bin"}; dropped = {"wikipedia-old"}
check("RED admitted + unconsumed shard refused", C.evictable("loc-00000-00000", "shards", "v1-00000-1321e1508433.bin", consumed, dropped) == (False, "admitted and not yet consumed by a governed hour"))
check("GREEN shard of a trained hour allowed", C.evictable("pg-1", "shards", "v1-00000-aaaaaaaaaaaa.bin", consumed, dropped)[0])
check("GREEN shard of a dropped (superseded/twinned) pack allowed", C.evictable("wikipedia-old", "shards", "v1-00007-bbbbbbbbbbbb.bin", consumed, dropped)[0])
check("GREEN object keeps the old rule", C.evictable("loc-00000-00000", "objects", "x.jsonl.zst", consumed, dropped)[0])
T = tempfile.mkdtemp(dir=(LANE_ROOT + "/scratch"))
def mk(dirname, ledger_names, parent=None, ledger_exists=True):
    d = f"{T}/{dirname}/measurement-x"; os.makedirs(d, exist_ok=True); lp = f"{T}/{dirname}-ledger.jsonl"
    if ledger_exists: open(lp, "w").write("".join(json.dumps({"name": n}) + chr(10) for n in ledger_names))
    r = {"input_binding": {"shard_ledger_path": lp}, "lineage": ({"parent_checkpoint": parent + "/trained-child"} if parent else {})}
    json.dump(r, open(d + "/hour-result.json", "w")); return d
def head(path, hr): json.dump({"hour_result_path": hr + "/hour-result.json"}, open(path, "w"))
try:
    try: C.consumed_names(T + "/missing.json"); check("RED missing head file fails closed", False)
    except C.GuardError: check("RED missing head file fails closed", True)
    open(T + "/bad.json", "w").write("{not json")
    try: C.consumed_names(T + "/bad.json"); check("RED unreadable head fails closed", False)
    except C.GuardError: check("RED unreadable head fails closed", True)
    h0 = mk("h0", ["v1-00001-cccccccccccc.bin"]); h1 = mk("h1", ["v1-00002-dddddddddddd.bin"], parent=h0)
    mk("refuted", ["v1-00099-eeeeeeeeeeee.bin"], parent=h1)          # a child NOT in the head's ancestry
    head(T + "/ok.json", h1)
    check("GREEN ancestry ledgers loaded (head + parent)", C.consumed_names(T + "/ok.json") == {"v1-00001-cccccccccccc.bin", "v1-00002-dddddddddddd.bin"})
    check("RED refuted child's shard is NOT consumed", "v1-00099-eeeeeeeeeeee.bin" not in C.consumed_names(T + "/ok.json"))
    g1 = mk("g1", ["v1-00003-ffffffffffff.bin"], parent=T + "/nowhere/measurement-x"); head(T + "/gone.json", g1)
    try: C.consumed_names(T + "/gone.json"); check("RED missing ancestor hour-result fails closed", False)
    except C.GuardError: check("RED missing ancestor hour-result fails closed", True)
    m1 = mk("m1", ["v1-00004-aaaaaaaaaaaa.bin"], ledger_exists=False); head(T + "/noledger.json", m1)
    try: C.consumed_names(T + "/noledger.json"); check("RED missing ledger file fails closed", False)
    except C.GuardError: check("RED missing ledger file fails closed", True)
    os.makedirs(T + "/p/a"); os.makedirs(T + "/p/a-r1"); os.makedirs(T + "/p/b"); os.makedirs(T + "/p/c")
    open(T + "/s.jsonl", "w").write(json.dumps({"original_pack": "c"}) + chr(10))
    check("dropped = base with an -r1 twin + supersession-named pack, not the plain admitted one", C.dropped_packs(T + "/p", [T + "/s.jsonl"]) == {"a", "c"})
finally:
    shutil.rmtree(T, ignore_errors=True)
src = open((LANE_ROOT + "/scripts/clear_uploaded_shards.py"), encoding="utf-8").read()
check("main() deletes only after evictable()", src.index("evictable(pack, sub, f, consumed, dropped)") < src.index("os.remove(p)"))
check("real selected head derives a non-empty consumed set", len(C.consumed_names()) > 0)
print("ALL PASS" if ok else "FAILED"); sys.exit(0 if ok else 1)
