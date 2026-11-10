# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Reds/greens for a_relocate.relocate (lead 82070): append-during-copy, file added after copy, open-handle holder, floor breach -> refused with the source intact; untouched dir -> moved, sha-equal.
Run: python scripts/tests/a_relocate_red_test.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from lane_config import LANE_ROOT
import os, sys, json, shutil, time, hashlib
pass
import a_relocate as A
T = (LANE_ROOT + "/scratch/a_reloc_test")
ok = True


def mk(name):
    base = f"{T}/{name}"; shutil.rmtree(base, ignore_errors=True); os.makedirs(base + "/src/sub"); os.makedirs(base + "/dst")
    for rel, body in (("a.bin", b"A" * 5000), ("sub/b.bin", b"B" * 7000), ("c.txt", b"hello")):
        open(f"{base}/src/{rel}", "wb").write(body)
    return base


def sha(p): return hashlib.sha256(open(p, "rb").read()).hexdigest()


def check(label, cond):
    global ok
    ok &= bool(cond); print("PASS" if cond else "FAIL", label)


def run(base, **kw):
    return A.relocate(f"{base}/src", f"{base}/dst", f"{base}/man.jsonl", check_bound=False, check_floor=False, make_junction=False, **kw)


# RED 1: a source file is appended after its copy -> refused, source intact (including the appended bytes)
b = mk("append"); before = sha(f"{b}/src/a.bin")
def app():
    with open(f"{b}/src/a.bin", "ab") as f: f.write(b"LATE-WRITE")
A._TEST_HOOK_AFTER_COPY = app
rc = run(b, check_writers=False); A._TEST_HOOK_AFTER_COPY = None
check("RED append-during-copy -> rc 1", rc == 1)
check("RED append-during-copy -> source intact with appended bytes", os.path.exists(f"{b}/src/a.bin") and open(f"{b}/src/a.bin", "rb").read().endswith(b"LATE-WRITE") and sha(f"{b}/src/a.bin") != before)

# RED 2: a NEW file appears in the source after the walk -> refused, source intact
b = mk("newfile")
def add(): open(f"{b}/src/new.bin", "wb").write(b"N" * 100)
A._TEST_HOOK_AFTER_COPY = add
rc = run(b, check_writers=False); A._TEST_HOOK_AFTER_COPY = None
check("RED file-added-after-copy -> rc 1", rc == 1)
check("RED file-added-after-copy -> source intact", os.path.exists(f"{b}/src/new.bin") and os.path.exists(f"{b}/src/a.bin"))

# RED 3: a process holds an open handle under the source -> refused at the start (live-writer refusal), source intact
b = mk("handle"); h = open(f"{b}/src/c.txt", "ab")
try:
    rc = run(b, check_writers=True)
finally:
    h.close()
check("RED open-handle -> rc 4", rc == 4)
check("RED open-handle -> source intact, nothing copied", os.path.exists(f"{b}/src/c.txt") and not os.path.exists(f"{b}/dst/a.bin"))

# RED 4: the B: floor (reserve_plan.floor_gib) would be breached -> refused rc 3, source intact
b = mk("floor"); rf = f"{b}/reserve.json"
fut = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 3600))
json.dump({"chain_start_utc": fut, "chain_start_floor_gib": 10 ** 6, "hour_writes_gib": 0, "publish_gib": 0, "declared_by": "test"}, open(rf, "w"))
os.environ["RESERVE_FILE"] = rf
import importlib, reserve_plan; importlib.reload(reserve_plan)
rc = A.relocate(f"{b}/src", f"{b}/dst", f"{b}/man.jsonl", check_bound=False, check_floor=True, make_junction=False, check_writers=False)
check("RED floor breach -> rc 3 (reads reserve_plan.floor_gib)", rc == 3 and os.path.exists(f"{b}/src/a.bin"))
del os.environ["RESERVE_FILE"]; importlib.reload(reserve_plan)

# GREEN: untouched source -> moved, dest sha-equal, source removed
b = mk("green"); want = {r: sha(f"{b}/src/{r}") for r in ("a.bin", "sub/b.bin", "c.txt")}
rc = run(b, check_writers=True)
check("GREEN untouched -> rc 0", rc == 0)
check("GREEN dest sha-equal and source removed", all(sha(f"{b}/dst/{r}") == s for r, s in want.items()) and not os.path.exists(f"{b}/src"))

shutil.rmtree(T, ignore_errors=True)
print("ALL PASS" if ok else "FAILED"); sys.exit(0 if ok else 1)
