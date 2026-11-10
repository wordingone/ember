# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Red/green for ckpt_lineage_delete.py after #2454: a status json that says COVERED, a log line that says HF-verified, or a stale PASS file select candidates but prove nothing at delete time.
Branches (a)/(b) delete a file only when the fake server (injected as READER) has the path with equal size AND LFS sha256 right now; a same-size corrupt upload, an entry with no LFS sha256 and a missing entry keep the file.
Branch (c) (no copy) refuses --apply without --ruling and, with it, writes the sha256 manifest before the first remove. Tmp tree and stubbed guards only; nothing real is read or deleted.
Run: python scripts/tests/ckpt_lineage_delete_verify_red_test.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from lane_config import LANE_ROOT
import os, sys, json, time, shutil, hashlib, tempfile, importlib.util, types, io, contextlib
HERE = os.path.dirname(os.path.abspath(__file__)); SC = os.path.dirname(HERE)
sys.path.insert(0, SC)
ok = True


def check(label, cond):
    global ok
    ok &= bool(cond); print("PASS" if cond else "FAIL", label)


SCR = (LANE_ROOT + "/scratch"); os.makedirs(SCR, exist_ok=True)
T = tempfile.mkdtemp(dir=SCR, prefix="cld-test-"); MB = 1 << 20
sha = lambda b: hashlib.sha256(b).hexdigest()
old = time.time() - 7200


def mkfile(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True); open(path, "wb").write(data); os.utime(path, (old, old))


# stubs for the three guards the script imports inside main()
G = types.ModuleType("probe_terminal_guard"); G.probe_eligibility = lambda d, kept=None: dict(ok=True, reason="", clause="A: test", consumers=[], terminal_receipt=None)
E = types.ModuleType("evict_ckpt_list"); E.kept = lambda d: False
B = types.ModuleType("ckpt_bound"); B.bound_dirs = lambda: []; B.is_bound = lambda d, b: False
for m in (G, E, B): sys.modules[m.__name__] = m


def load(argv):
    sys.argv = ["ckpt_lineage_delete.py"] + argv
    spec = importlib.util.spec_from_file_location("cld_" + str(time.time_ns()), SC + "/ckpt_lineage_delete.py"); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    m.CHK = T + "/chk.json"; m.PASS = T + "/PASS"; m.MAN = T + "/man/manifest.jsonl"; m.RCPT = T + "/man/receipts.jsonl"; m.BK_LOGS = (T + "/bk.log",); m.OLD = T + "/old.json"; m.PROBES = T + "/probes.json"
    m.FREEZE = T + "/NO-FREEZE.flag"; os.makedirs(T + "/man", exist_ok=True); open(m.PASS, "w").write("ok")
    return m


def run(m):
    buf = io.StringIO(); rc = 0
    with contextlib.redirect_stdout(buf):
        try: m.main()
        except SystemExit as e: rc = e.code or 0
    return rc, buf.getvalue()


def rcpts():
    p = T + "/man/receipts.jsonl"
    return [json.loads(l) for l in open(p)] if os.path.exists(p) else []


# child C1 (branch a): 4 big files; the server has f1 right, f2 same-size corrupt, f3 size-only (no LFS sha), f4 missing
data = {n: os.urandom(MB + 10) + n.encode() for n in ("f1", "f2", "f3", "f4")}
C1 = T + "/C1"
for n, d in data.items(): mkfile(f"{C1}/{n}.pt", d)
json.dump({"C1": dict(status="COVERED", dir=C1, step_dir="lineage/C1")}, open(T + "/chk.json", "w")); json.dump([], open(T + "/probes.json", "w")); json.dump([], open(T + "/old.json", "w"))
corrupt = bytearray(data["f2"]); corrupt[5] ^= 1
SRV = {("wordingone/ember-corpus", "lineage/C1/f1.pt"): (len(data["f1"]), sha(data["f1"])),
       ("wordingone/ember-corpus", "lineage/C1/f2.pt"): (len(data["f2"]), sha(bytes(corrupt))),
       ("wordingone/ember-corpus", "lineage/C1/f3.pt"): (len(data["f3"]), None)}
m = load(["--apply"]); m.READER = lambda repo, hp: SRV.get((repo, hp))
rc, out = run(m)
left = sorted(os.listdir(C1))
check("GREEN f1 (server size+sha256 match read back now) is deleted", "f1.pt" not in left)
check("RED f2 (status says COVERED, server has a same-size corrupt upload): kept", "f2.pt" in left)
check("RED f3 (server entry has no LFS sha256, size equal): kept", "f3.pt" in left)
check("RED f4 (no server entry; the status json is not proof): kept", "f4.pt" in left)
check("exit code 7 and the KEPT lines name the reasons", rc == 7 and "KEPT 3" in out and "sha256 mismatch" in out and "no LFS sha256" in out and "no server entry" in out)
r = rcpts()
check("the receipt row for f1 carries local and server sha256 and exists (written before the remove)", len(r) == 1 and r[0]["kind"] == "server-verified" and r[0]["local_sha256"] == r[0]["server_sha256"] == sha(data["f1"]))
mf = [json.loads(l) for l in open(T + "/man/manifest.jsonl")]
check("the plan manifest lists all 4 rows first, server rows say the sha256 is hashed in the receipt", len(mf) == 4 and all(x["sha256"] is None for x in mf) and all(x["kind"] == "server-verify" for x in mf))

# server unreadable: nothing is deleted
def down(repo, hp): raise __import__("verified_remove").ServerUnreadable("503")
m = load(["--apply"]); m.READER = down; rc, out = run(m)
check("RED server unreadable: every remaining file kept, exit 7", rc == 7 and sorted(os.listdir(C1)) == ["f2.pt", "f3.pt", "f4.pt"] and "server unreadable" in out)

# a hard-link name outside the set is never touched (existing in-set rule) and a stale PASS cannot bypass the server read
OUT = T + "/outside.pt"; os.link(C1 + "/f4.pt", OUT)
m = load(["--apply"]); m.READER = lambda repo, hp: (len(data["f4"]), sha(data["f4"]))
rc, out = run(m)
check("RED f4 has a second name outside the child dir: not selected for removal even with a matching server entry", os.path.exists(C1 + "/f4.pt") and os.path.exists(OUT))
os.remove(OUT)

# branch (b): ckpt_backup log line says HF-verified, server has nothing
C2 = T + "/C2"; mkfile(C2 + "/w.pt", os.urandom(MB + 3))
json.dump({}, open(T + "/chk.json", "w")); json.dump([dict(name="C2", dir=C2)], open(T + "/old.json", "w"))
open(T + "/bk.log", "w").write("12:00:00 C2 HF-verified 1 files 0.0 GiB at checkpoints/abcd1234-C2\n")
m = load(["--apply"]); m.READER = lambda repo, hp: None
rc, out = run(m)
check("RED branch (b): the 'HF-verified' log line is not proof, the server has no entry: kept", os.path.exists(C2 + "/w.pt") and rc == 7)
shutil.rmtree(C2); json.dump([], open(T + "/old.json", "w")); open(T + "/bk.log", "w").write("")

# branch (c): no copy -> --ruling required
P = T + "/P1"; pd = os.urandom(MB + 9); mkfile(P + "/payload.pt", pd)
json.dump([dict(name="P1", dir=P)], open(T + "/probes.json", "w"))
n0 = len(open(T + "/man/manifest.jsonl").read().splitlines())
m = load(["--apply", "--only-probes"]); m.READER = lambda repo, hp: None; rc, out = run(m)
before = len(open(T + "/man/manifest.jsonl").read().splitlines())
check("RED --apply on a no-copy probe child without --ruling: refused (exit 5), nothing deleted, and no manifest row written", rc == 5 and os.path.exists(P + "/payload.pt") and "need --ruling" in out and before == n0)
m = load(["--apply", "--only-probes", "--ruling", "82499"]); m.READER = lambda repo, hp: None; rc, out = run(m)
mf = [json.loads(l) for l in open(T + "/man/manifest.jsonl")][before:]
check("GREEN with --ruling the no-copy payload is removed, manifest row has sha256 + ruling + probe_clause", rc == 0 and not os.path.exists(P + "/payload.pt") and len(mf) == 1 and mf[0]["sha256"] == sha(pd) and mf[0]["ruling"] == "82499" and mf[0]["probe_clause"] == "A: test")
check("the no-copy receipt is labelled ruled-no-copy-remove, never server-verified", rcpts()[-1]["kind"] == "ruled-no-copy-remove")
mkfile(P + "/payload.pt", pd)
m = load(["--only-probes", "--ruling", "82499"]); rc, out = run(m)
check("dry run (no --apply) deletes nothing and prints the DRY RUN line", rc == 0 and "DRY RUN" in out and os.path.exists(P + "/payload.pt"))

# the freeze flag still wins
open(T + "/NO-FREEZE.flag", "w").write("x")
m = load(["--apply", "--only-probes", "--ruling", "82499"]); m.FREEZE = T + "/NO-FREEZE.flag"; rc, out = run(m)
check("freeze flag present: exit 3, nothing deleted", rc == 3 and os.path.exists(P + "/payload.pt"))
src = open(SC + "/ckpt_lineage_delete.py", encoding="utf-8").read()
check("source: no bare os.remove in the script, every delete goes through verified_remove", "os.remove(" not in src and "VR.remove_verified(" in src and "VR.remove_ruled(" in src)
shutil.rmtree(T, ignore_errors=True)
print("ALL PASS" if ok else "FAILED"); sys.exit(0 if ok else 1)
