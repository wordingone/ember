# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Red test for the decision rows of ckpt_lineage_delete.py (issue 2450, review round 2): the manifest lists the PLAN, the decisions file says what was DONE.
EXECUTED against a sandbox lane root (tmp tree, stub guards, stub protected set, os.remove spied): three covered files; the first removal declares a marker over the third, so
(1) the third file is kept and the decisions file says `kept` with that marker, the manifest still lists it as planned;
(2) every `remove` decision row exists, fsynced, BEFORE the os.remove of that path (checked inside the spy);
(3) each decision row carries the protected-set sha256 re-read for THAT file: the second removal records the new sha, not the one the plan was written under.
Run: python scripts/tests/ckpt_lineage_decisions_red_test.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import os, sys, json, time, shutil, tempfile, importlib.util, types, io, contextlib
HERE = os.path.dirname(os.path.abspath(__file__)); SC = os.path.dirname(HERE)
ok = True


def check(label, cond):
    global ok
    ok &= bool(cond); print("PASS" if cond else "FAIL", label)


T = tempfile.mkdtemp(prefix="cld-dec-").replace("\\", "/")
os.environ["EMBER_LANE_ROOT"] = T + "/lane"; os.environ["EMBER_HF_RAW_REPO"] = "raw-test"
for sub in ("logs", "loops", "scratch"): os.makedirs(T + "/lane/" + sub, exist_ok=True)
MB = 1 << 20; old = time.time() - 7200
C = T + "/child"; os.makedirs(C)
names = ("f1.pt", "f2.pt", "f3.pt")
for n in names:
    open(C + "/" + n, "wb").write(os.urandom(MB + 5) + n.encode()); os.utime(C + "/" + n, (old, old))
json.dump({"C": dict(status="COVERED", dir=C, step_dir="lineage/C")}, open(T + "/lane/logs/ckpt-lineage-check.json", "w")); json.dump([], open(T + "/lane/logs/ckpt-probes.json", "w")); json.dump([], open(T + "/lane/logs/ckpt-old.json", "w"))
open(T + "/lane/logs/ckpt-roundtrip.PASS", "w").write("ok")
state = dict(markers=[], sha="sha-before")
PS = types.ModuleType("protected_set"); PS.load = lambda: dict(sha256=state["sha"], path="stub-declaration.json", markers=list(state["markers"]), reserve_markers=[])
E = types.ModuleType("evict_ckpt_list"); E.kept = lambda p, markers=None: next((m for m in (markers or []) if m in p.replace("\\", "/")), None)
B = types.ModuleType("ckpt_bound"); B.bound_dirs = lambda: []; B.is_bound = lambda d, b: False
for m in (PS, E, B): sys.modules[m.__name__] = m
sys.argv = ["ckpt_lineage_delete.py", "--apply"]
spec = importlib.util.spec_from_file_location("cld_dec", SC + "/ckpt_lineage_delete.py"); mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
DEC = os.path.dirname(mod.MAN) + "/ckpt-lineage-delete-decisions.jsonl"
real_remove = os.remove; seen = []
def spy(p, *a, **k):
    q = str(p).replace("\\", "/")
    rows = [json.loads(l) for l in open(DEC, encoding="utf-8")] if os.path.exists(DEC) else []
    seen.append((q, any(r["path"].replace("\\", "/") == q and r["decision"] == "remove" for r in rows)))      # the decision row must already be on disk
    if q.endswith("/f1.pt") or q.endswith("f1.pt"):      # the first removal: a marker over the third file is declared and the set changes
        state["markers"] = ["/child/f3.pt"]; state["sha"] = "sha-after"
    return real_remove(p, *a, **k)
os.remove = spy
buf = io.StringIO(); rc = 0
try:
    with contextlib.redirect_stdout(buf):
        try: mod.main()
        except SystemExit as e: rc = e.code or 0
finally:
    os.remove = real_remove
out = buf.getvalue()
dec = [json.loads(l) for l in open(DEC, encoding="utf-8")] if os.path.exists(DEC) else []
man = [json.loads(l) for l in open(mod.MAN, encoding="utf-8")]
by = {os.path.basename(r["path"]): r for r in dec}
check("run completed (exit 0) and two files were removed, the third kept", rc == 0 and not os.path.exists(C + "/f1.pt") and not os.path.exists(C + "/f2.pt") and os.path.exists(C + "/f3.pt") and "deleted 2 names" in out)
check("RED the manifest lists all three planned rows (it is the plan, not the outcome)", len(man) == 3 and all("protected_set_sha256_at_plan" in r and "protected_set_sha256" not in r for r in man))
check("the decisions file has one row per file: two `remove`, one `kept`", sorted(r["decision"] for r in dec) == ["kept", "remove", "remove"])
check("RED the kept file is marked `kept` with the marker that kept it (a reader does not conclude it was deleted)", by["f3.pt"]["decision"] == "kept" and by["f3.pt"]["marker"] == "/child/f3.pt")
check("RED receipt-before-remove: for every os.remove the `remove` decision row for that path was already on disk", len(seen) == 2 and all(flag for _, flag in seen))
check("RED each row records the set re-read for THAT file: f1 under sha-before, f2 and f3 under sha-after; the plan was written under sha-before", by["f1.pt"]["protected_set_sha256"] == "sha-before" and by["f2.pt"]["protected_set_sha256"] == "sha-after" and by["f3.pt"]["protected_set_sha256"] == "sha-after" and all(r["planned_under_sha256"] == "sha-before" for r in dec))
src = open(SC + "/ckpt_lineage_delete.py", encoding="utf-8").read()
check("source: the decision row is written before os.remove", src.index('_dec(r, cur, "remove")') < src.index("os.remove(r[\"path\"])"))
shutil.rmtree(T, ignore_errors=True)
print("ALL PASS" if ok else "FAILED"); sys.exit(0 if ok else 1)
