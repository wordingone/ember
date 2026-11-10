# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Red/green for ckpt_lineage_delete.py after #2454: a status json that says COVERED, a log line that says HF-verified, or a stale PASS file select candidates but prove nothing at delete time.
Branches (a)/(b) delete a file only when the fake server (injected as READER) has the path with equal size AND LFS sha256 right now; a same-size corrupt upload, an entry with no LFS sha256 and a missing entry keep the file.
Branch (c) (no copy) refuses --apply without a mail-id --ruling and without --expect-dirs (the pin of the no-copy path, #2459 F1), and, with both, writes the sha256 manifest before the first remove. Tmp tree and stubbed guards only; nothing real is read or deleted.
Run: python scripts/tests/ckpt_lineage_delete_verify_red_test.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from lane_config import LANE_ROOT
import os, sys, re, json, time, shutil, hashlib, tempfile, importlib.util, types, io, contextlib
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

# F5 (#2459): the per-call nlink guard is the planned nlink, so a name hard-linked after the plan makes the remove refuse
C3 = T + "/C3"; d3 = os.urandom(MB + 11); mkfile(C3 + "/h.pt", d3); OUT3 = T + "/linked-later.pt"
json.dump({"C3": dict(status="COVERED", dir=C3, step_dir="lineage/C3")}, open(T + "/chk.json", "w"))
m = load(["--apply"]); m.READER = lambda repo, hp: (len(d3), sha(d3))
orig_rv = m.VR.remove_verified
def link_then_remove(path, *a, **k):
    os.link(path, OUT3); return orig_rv(path, *a, **k)
m.VR.remove_verified = link_then_remove
rc, out = run(m)
m.VR.remove_verified = orig_rv
check("RED F5 a name hard-linked AFTER the plan: the file is kept (nlink 2 != 1 at remove time), exit 7", os.path.exists(C3 + "/h.pt") and os.path.exists(OUT3) and rc == 7 and "nlink 2 != 1" in out)
os.remove(OUT3)
src5 = open(SC + "/ckpt_lineage_delete.py", encoding="utf-8").read()
check("source (F5): no require_nlink=0 in the script; both remove calls pass the countdown nlink (planned nlink minus names already removed)", "require_nlink=0" not in src5 and src5.count("require_nlink=req") == 2 and "nl_left.setdefault" in src5)

# F-A (#2459 round 2): an inode with two names INSIDE the delete set. The first name sees nlink 2, the second sees nlink 1: both must go (the old planned-nlink check refused the last name: exit 7, 0 GiB freed).
import verified_remove as VR0
fz = T + "/same.bin"; mkfile(fz, b"x" * 10); st0 = os.lstat(fz)
check("_same is True on an untouched file", VR0._same(fz, st0))
os.link(fz, fz + ".l"); check("RED F-A _same is False once a name is hard-linked after the first stat (nlink is part of the compare)", not VR0._same(fz, st0)); os.remove(fz + ".l")
C4 = T + "/C4"; d4 = os.urandom(MB + 12); mkfile(C4 + "/a.pt", d4); os.link(C4 + "/a.pt", C4 + "/b.pt")
json.dump({"C4": dict(status="COVERED", dir=C4, step_dir="lineage/C4")}, open(T + "/chk.json", "w"))
m = load(["--apply"]); m.READER = lambda repo, hp: (len(d4), sha(d4)); rc, out = run(m)
check("GREEN F-A verified branch: both names of one inode inside the set are removed (nlink 2 then 1), exit 0, nothing kept", rc == 0 and os.listdir(C4) == [] and "deleted 2 names" in out and "KEPT" not in out)
r4 = [x for x in rcpts() if x["path"].endswith(("a.pt", "b.pt"))]
check("F-A the two receipt rows exist, one per name", len(r4) == 2 and all(x["kind"] == "server-verified" for x in r4))
C5 = T + "/C5"; d5 = os.urandom(MB + 13); mkfile(C5 + "/a.pt", d5); os.link(C5 + "/a.pt", C5 + "/b.pt"); OUT5 = T + "/outside5.pt"
json.dump({"C5": dict(status="COVERED", dir=C5, step_dir="lineage/C5")}, open(T + "/chk.json", "w"))
m = load(["--apply"]); m.READER = lambda repo, hp: (len(d5), sha(d5))
orig_rv5 = m.VR.remove_verified
def link_after_first(path, *a, **k):
    res = orig_rv5(path, *a, **k)
    if res["ok"] and not os.path.exists(OUT5): os.link(C5 + "/b.pt", OUT5)      # a name appears outside the set after the first name went
    return res
m.VR.remove_verified = link_after_first; rc, out = run(m); m.VR.remove_verified = orig_rv5
check("RED F-A a name added outside the set after the first removal: the second name is kept (nlink 2 != countdown 1), exit 7", os.path.exists(C5 + "/b.pt") and os.path.exists(OUT5) and rc == 7 and "nlink 2 != 1" in out)
os.remove(OUT5); shutil.rmtree(C5)
json.dump({}, open(T + "/chk.json", "w"))

# branch (c): no copy -> --ruling required
P = T + "/P1"; pd = os.urandom(MB + 9); mkfile(P + "/payload.pt", pd)
json.dump([dict(name="P1", dir=P)], open(T + "/probes.json", "w"))
n0 = len(open(T + "/man/manifest.jsonl").read().splitlines())
m = load(["--apply", "--only-probes"]); m.READER = lambda repo, hp: None; rc, out = run(m)
before = len(open(T + "/man/manifest.jsonl").read().splitlines())
check("RED --apply on a no-copy probe child without --ruling: refused (exit 5), nothing deleted, and no manifest row written", rc == 5 and os.path.exists(P + "/payload.pt") and "need --ruling" in out and before == n0)
m = load(["--apply", "--only-probes", "--ruling", "x"]); m.READER = lambda repo, hp: None; rc, out = run(m)
check("RED (#2459 F1) a ruling that is not a mail id ('x') is refused (exit 5), payload stays", rc == 5 and os.path.exists(P + "/payload.pt") and len(open(T + "/man/manifest.jsonl").read().splitlines()) == n0)
m = load(["--apply", "--only-probes", "--ruling", "82499"]); m.READER = lambda repo, hp: None; rc, out = run(m)
check("RED (#2459 F1) --ruling but no --expect-dirs: refused (exit 5, NO_PIN), payload stays, no manifest row", rc == 5 and "NO_PIN" in out and os.path.exists(P + "/payload.pt") and len(open(T + "/man/manifest.jsonl").read().splitlines()) == n0)
json.dump([P.replace(chr(92), "/")], open(T + "/expect.json", "w"))
# F-C (#2459 round 2): the no-copy pin is FILE-level. The dry run prints PLAN-SHA256 over (path, bytes, sha256) of every selected no-copy file; --apply needs it and refuses any other file set.
m = load(["--only-probes", "--expect-dirs", T + "/expect.json", "--ruling", "82499"]); m.READER = lambda repo, hp: None; rc, out = run(m)
mm = re.search(r"^PLAN-SHA256 ([0-9a-f]{64}) over (\d+) no-copy files", out, re.M); PLAN = mm.group(1) if mm else "?"
check("F-C the dry run prints PLAN-SHA256 over the 1 selected no-copy file and writes the plan rows to a file", rc == 0 and bool(mm) and mm.group(2) == "1" and os.path.exists(T + "/man/ckpt-lineage-delete-plan-" + PLAN[:12] + ".jsonl"))
m = load(["--apply", "--only-probes", "--expect-dirs", T + "/expect.json", "--ruling", "82499"]); m.READER = lambda repo, hp: None; rc, out = run(m)
check("RED F-C --apply with --ruling and --expect-dirs but no --plan-sha256: refused (exit 5, NO_FILE_PIN), payload stays, no manifest row", rc == 5 and "NO_FILE_PIN" in out and os.path.exists(P + "/payload.pt") and len(open(T + "/man/manifest.jsonl").read().splitlines()) == before)
m = load(["--apply", "--only-probes", "--expect-dirs", T + "/expect.json", "--ruling", "82499", "--plan-sha256", "0" * 64]); m.READER = lambda repo, hp: None; rc, out = run(m)
check("RED F-C a wrong plan sha: refused (exit 4), payload stays, no manifest row", rc == 4 and "not the ruled plan" in out and os.path.exists(P + "/payload.pt") and len(open(T + "/man/manifest.jsonl").read().splitlines()) == before)
mkfile(P + "/added-later.pt", os.urandom(MB + 5))      # a file added to the ruled dir AFTER the dry run: the dir-level pin (expect-dirs) still passes, the file-level plan does not
m = load(["--apply", "--only-probes", "--expect-dirs", T + "/expect.json", "--ruling", "82499", "--plan-sha256", PLAN]); m.READER = lambda repo, hp: None; rc, out = run(m)
check("RED F-C a file added to the ruled dir after the dry run is NOT in the plan: refused (exit 4) naming added-later.pt, nothing removed, no manifest row", rc == 4 and "added-later.pt" in out and os.path.exists(P + "/payload.pt") and os.path.exists(P + "/added-later.pt") and len(open(T + "/man/manifest.jsonl").read().splitlines()) == before)
os.remove(P + "/added-later.pt")
m = load(["--apply", "--only-probes", "--expect-dirs", T + "/expect.json", "--ruling", "82499", "--plan-sha256", PLAN]); m.READER = lambda repo, hp: None; rc, out = run(m)
mf = [json.loads(l) for l in open(T + "/man/manifest.jsonl")][before:]
check("GREEN with --ruling and --expect-dirs the no-copy payload is removed, manifest row has sha256 + ruling + probe_clause + the pin", rc == 0 and not os.path.exists(P + "/payload.pt") and len(mf) == 1 and mf[0]["sha256"] == sha(pd) and mf[0]["ruling"] == "82499" and mf[0]["probe_clause"] == "A: test" and mf[0]["pinned_by"].startswith("expect-dirs sha256 "))
check("the no-copy receipt is labelled ruled-no-copy-remove, never server-verified, and carries both pins (dir list and file plan)", rcpts()[-1]["kind"] == "ruled-no-copy-remove" and rcpts()[-1]["pinned_by"].startswith("expect-dirs sha256 ") and ("plan sha256 " + PLAN) in rcpts()[-1]["pinned_by"])
mkfile(P + "/payload.pt", pd)
m = load(["--only-probes", "--ruling", "82499"]); rc, out = run(m)
check("dry run (no --apply) deletes nothing and prints the DRY RUN line", rc == 0 and "DRY RUN" in out and os.path.exists(P + "/payload.pt"))

# the freeze flag still wins
open(T + "/NO-FREEZE.flag", "w").write("x")
m = load(["--apply", "--only-probes", "--ruling", "82499"]); m.FREEZE = T + "/NO-FREEZE.flag"; rc, out = run(m)
check("freeze flag present: exit 3, nothing deleted", rc == 3 and os.path.exists(P + "/payload.pt"))
# F-A on the no-copy branch: an inode with two names inside a ruled probe dir: both removed, exit 0
os.remove(T + "/NO-FREEZE.flag")
P2 = T + "/P2"; pd2 = os.urandom(MB + 21); mkfile(P2 + "/payload.pt", pd2); os.link(P2 + "/payload.pt", P2 + "/payload-link.pt")
json.dump([dict(name="P2", dir=P2)], open(T + "/probes.json", "w")); json.dump([P2.replace(chr(92), "/")], open(T + "/expect2.json", "w"))
m = load(["--only-probes", "--expect-dirs", T + "/expect2.json", "--ruling", "82499"]); m.READER = lambda repo, hp: None; rc, out = run(m)
mm2 = re.search(r"^PLAN-SHA256 ([0-9a-f]{64}) over (\d+) no-copy files", out, re.M); PLAN2 = mm2.group(1) if mm2 else "?"
check("F-A probe dry run: two names of one inode are two files in the plan", rc == 0 and bool(mm2) and mm2.group(2) == "2")
m = load(["--apply", "--only-probes", "--expect-dirs", T + "/expect2.json", "--ruling", "82499", "--plan-sha256", PLAN2]); m.READER = lambda repo, hp: None; rc, out = run(m)
check("GREEN F-A probe branch: both names of the inode are removed (nlink 2 then 1), exit 0, nothing kept", rc == 0 and os.listdir(P2) == [] and "deleted 2 names" in out and "KEPT" not in out)
src = open(SC + "/ckpt_lineage_delete.py", encoding="utf-8").read()
check("source: no bare os.remove in the script, every delete goes through verified_remove", "os.remove(" not in src and "VR.remove_verified(" in src and "VR.remove_ruled(" in src)
shutil.rmtree(T, ignore_errors=True)
print("ALL PASS" if ok else "FAILED"); sys.exit(0 if ok else 1)
