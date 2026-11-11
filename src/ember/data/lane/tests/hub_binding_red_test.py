# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Red/green for hub_binding.py: the Hub-binding entry is written by code from the Hub listing (never by hand). Tmp tree, fake lister, no network. Run: python tests/hub_binding_red_test.py (lane env set, see README.md; temp files under A: only)"""
import os, sys, json, tempfile, shutil, hashlib, time
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if not os.environ.get("TMP", "").replace("\\", "/").lower().startswith("a:/"):
    os.environ["TMP"] = os.environ["TEMP"] = "A:/data-scan/tmp-red"
os.makedirs(os.environ["TMP"], exist_ok=True); tempfile.tempdir = None
T = tempfile.mkdtemp(prefix="hb-test-"); os.makedirs(T + "/loops"); os.makedirs(T + "/logs/th-scan")
os.environ.update(HB_ROOT=T, HB_BINDING=T + "/loops/scan-hub-binding.json", HB_SCAN_DIR=T + "/logs/th-scan")
sys.path.insert(0, HERE)
import hub_binding as H
ok = True
def check(label, cond):
    global ok; ok &= bool(cond); print("PASS" if cond else "FAIL", label)
B = T + "/loops/scan-hub-binding.json"
rows_a = [("shards/v1-00000.bin", 100), ("intake.json", 7)]
sig_a = hashlib.sha1(json.dumps(sorted(rows_a)).encode()).hexdigest()
lister = lambda path: [("text/pa/" + r, s) for r, s in rows_a] + [("text/pb/x.bin", 5)]
json.dump({"pb": "old-b"}, open(B, "w"))
json.dump({"name": "train-pa", "signature": sig_a, "clean": True}, open(T + "/logs/th-scan/train-pa.json", "w"))
r = H.refresh_one("pa", lister=lister)
d = json.load(open(B))
check("GREEN refresh_one sets the pack's entry to th_pack_scan's signature formula over the Hub listing, keeps the other packs' entries, and reports row signature == Hub", r["ok"] and d["pa"] == sig_a and d["pb"] == "old-b" and r["row_sig_eq_hub"] and r["files"] == 2 and r["changed"])
r2 = H.refresh_one("pa", lister=lister)
check("GREEN a second refresh is idempotent (changed False)", r2["ok"] and not r2["changed"])
json.dump({"name": "train-pa", "signature": "other", "clean": True}, open(T + "/logs/th-scan/train-pa.json", "w"))
check("RED a scan row whose signature differs from the Hub listing is reported (row_sig_eq_hub False), not hidden", H.refresh_one("pa", lister=lister)["row_sig_eq_hub"] is False)
before = open(B).read()
r = H.refresh_one("pz", lister=lister)
check("RED an empty Hub listing for the pack refuses and leaves the binding file byte-identical", (not r["ok"]) and "empty" in r["why"] and open(B).read() == before)
def boom(path): raise RuntimeError("hub down")
r = H.refresh_one("pa", lister=boom)
check("RED an unreadable Hub listing refuses and leaves the binding untouched", (not r["ok"]) and "listing failed" in r["why"] and open(B).read() == before)
open(B, "w").write("{"); r = H.refresh_one("pa", lister=lister)
check("RED an unreadable existing binding is not overwritten by a one-entry refresh (use refresh_all)", (not r["ok"]) and "unreadable" in r["why"] and open(B).read() == "{")
ra = H.refresh_all(lister=lister)
d = json.load(open(B))
check("GREEN refresh_all rebuilds every pack from one recursive listing", ra["ok"] and set(d) == {"pa", "pb"} and d["pa"] == sig_a and ra["packs"] == 2)
ra = H.refresh_all(lister=lambda p: []); check("RED refresh_all on an empty listing refuses and keeps the file", (not ra["ok"]) and set(json.load(open(B))) == {"pa", "pb"})
open(B + ".lock", "w").write("999"); os.utime(B + ".lock", (time.time() - 3600, time.time() - 3600))
r = H.refresh_one("pa", lister=lister); check("GREEN a stale lock (older than 10 min) is taken over", r["ok"] and not os.path.exists(B + ".lock"))
tk = open(os.path.join(HERE, "loops", "tick.py"), encoding="utf-8").read()
check("GREEN tick.py upload calls hub_binding.refresh_one right after drop_uploaded.run", tk.index("drop_uploaded.run") < tk.index("hub_binding as _hb") < tk.index("SET UPLOADED + DROPPED"))
shutil.rmtree(T, ignore_errors=True); print("ALL PASS" if ok else "FAILED"); sys.exit(0 if ok else 1)
