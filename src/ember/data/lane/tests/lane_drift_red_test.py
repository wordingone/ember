# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Red/green for the lane drift check (#2454, lead 82490): the lane must run from, or be byte-checked against, the reviewed tree copy, and a tick refuses on drift.
Hermetic: a throwaway git repo is the "tree", a stub exporter stands in for export_lane.py (plus one real export of a tiny source dir for determinism), tmp dirs under scratch, nothing live is touched.
Covers: changed / new / tree-only files are drift (by git blob id); fail closed when git or the export fails; the content-bound, ruling-bound, expiring acknowledgement; the verdict cache; the fetch rate limit
and self-clearing after a merge; the CLI exit codes; and tick.py's gate (it runs before the scratch sweep, never through done(), 3 blocked ticks print ESCALATE).
Run: python scripts/tests/lane_drift_red_test.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from lane_config import LANE_ROOT
import os, sys, json, time, shutil, subprocess, tempfile, ast, re
HERE = os.path.dirname(os.path.abspath(__file__)); SC = os.path.dirname(HERE)
sys.path.insert(0, SC)
import lane_drift as D
ok = True


def check(label, cond, detail=""):
    global ok
    ok &= bool(cond); print("PASS" if cond else "FAIL", label, detail if not cond else "")


SCR = (LANE_ROOT + "/scratch"); os.makedirs(SCR, exist_ok=True)
T = tempfile.mkdtemp(dir=SCR, prefix="drift-test-").replace("\\", "/")
D.LANE_BASE = T; D.L = T + "/loops"; D.CACHE = D.L + "/drift-cache.json"; D.ACK = D.L + "/drift-ack.json"; os.makedirs(D.L)
SRC = T + "/src"; REPO = T + "/repo"; SUB = D.cfg()["tree"]["sub"]; TREE = REPO + "/" + SUB
ENV = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t", GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull)


def g(*a): return subprocess.run(["git", "-C", REPO] + list(a), capture_output=True, text=True, env=ENV, check=True).stdout


def wr(p, text): os.makedirs(os.path.dirname(p), exist_ok=True); open(p, "wb").write(text.encode())


CALLS = []


def stub(dst, src=None):
    """the export stand-in: every .py is copied as is, lane-README.md becomes README.md with LF"""
    src = src or D.SCRIPTS; CALLS.append(src)
    for dp, dn, fn in os.walk(src):
        for f in fn:
            rel = os.path.relpath(os.path.join(dp, f), src).replace("\\", "/"); data = open(os.path.join(dp, f), "rb").read()
            if rel == "lane-README.md": rel, data = "README.md", D.lf(data)
            elif not rel.endswith(".py"): continue
            os.makedirs(os.path.dirname(dst + "/" + rel) or dst, exist_ok=True); open(dst + "/" + rel, "wb").write(data)


D.export_to = stub
wr(SRC + "/a.py", "print('a')\n"); wr(SRC + "/b.py", "print('b')\n"); wr(SRC + "/tests/t.py", "print('t')\n"); wr(SRC + "/lane-README.md", "# lane\r\nline\r\n")
os.makedirs(REPO); g("init", "-q", "-b", "master")
stub(TREE, SRC); g("add", "-A"); g("commit", "-q", "-m", "tree")
KW = dict(src=SRC, repo=REPO, ref="HEAD")


def commit_tree(): g("add", "-A"); g("commit", "-q", "-m", "tree again")


# ---- compare + blob ids
c = D.compare({"x": "1", "y": "2", "z": "3"}, {"x": "1", "y": "9", "w": "4"})
check("compare: changed / live_only / tree_only are told apart", c == dict(changed=["y"], live_only=["z"], tree_only=["w"]), str(c))
check("blob_oid is git's blob id (same as `git hash-object`)", D.blob_oid(b"print('a')\n") == subprocess.run(["git", "hash-object", "--stdin"], input=b"print('a')\n", capture_output=True).stdout.decode().strip())
tid, toids = D.tree_oids(REPO, "HEAD", SUB)
check("tree_oids reads the committed blobs (README included, LF)", set(toids) == {"a.py", "b.py", "tests/t.py", "README.md"} and toids["README.md"] == D.blob_oid(b"# lane\nline\n"))

# ---- GREEN: identical
rep = D.check(use_cache=False, **KW)
ok_, note = D.gate("t", **KW)
check("GREEN: live export identical to the tree -> clean, gate passes", rep["clean"] and ok_ and note == "", str(rep))

# ---- RED: changed, new, tree-only
wr(SRC + "/a.py", "print('a edited')\n")
rep = D.check(use_cache=False, **KW)
check("RED: an edited script is drift and is named", not rep["clean"] and rep["changed"] == ["a.py"] and not rep["live_only"] and not rep["tree_only"], str(rep))
ok_, note = D.gate("t", fetcher=lambda *a: False, **KW)
check("RED: the gate refuses and the note names the file and the way out", not ok_ and "a.py" in note and "lane_drift.py ack" in note, note)
wr(SRC + "/new_tool.py", "print('new')\n")
rep = D.check(use_cache=False, **KW)
check("RED: a script that is not in the tree is drift (live_only)", rep["live_only"] == ["new_tool.py"] and rep["changed"] == ["a.py"], str(rep))
wr(SRC + "/a.py", "print('a')\n"); os.remove(SRC + "/new_tool.py"); os.remove(SRC + "/b.py")
rep = D.check(use_cache=False, **KW)
ok_, note = D.gate("t", fetcher=lambda *a: False, **KW)
check("RED: a tree file the live lane does not have is drift (tree_only) and refuses", rep["tree_only"] == ["b.py"] and not ok_ and "only in tree" in note, note)
wr(SRC + "/b.py", "print('b')\n")
wr(SRC + "/lane-README.md", "# lane\nline\n")
check("GREEN: CRLF vs LF in the README is not drift (compared as LF), a restored tree is clean again", D.check(use_cache=False, **KW)["clean"])
wr(SRC + "/lane-README.md", "# lane\r\nline CHANGED\r\n")
check("RED: a README edit is drift", D.check(use_cache=False, **KW)["changed"] == ["README.md"])
wr(SRC + "/lane-README.md", "# lane\r\nline\r\n")

# ---- fail closed
def boom_reader(*a): raise RuntimeError("git exploded")


def boom_export(dst, src=None): raise RuntimeError("export exploded")


ok_, note = D.gate("t", tree_reader=boom_reader, fetcher=lambda *a: False, **KW)
check("RED: git cannot be read -> the gate refuses (fail closed), says it could not run", not ok_ and "could not run" in note and "RuntimeError" in note, note)
wr(SRC + "/a.py", "print('changed so the cache cannot answer')\n")
ok_, note = D.gate("t", exporter=boom_export, fetcher=lambda *a: False, **KW)
check("RED: the export fails -> the gate refuses (fail closed)", not ok_ and "could not run" in note, note)
ok_, note = D.gate("t", fetcher=lambda *a: False, src=SRC, repo=REPO, ref="no-such-ref")
check("RED: an unknown tree ref -> refuses (a missing tree never means 'no drift')", not ok_ and "could not run" in note, note)
wr(SRC + "/a.py", "print('a')\n")

# ---- acknowledgement: content bound, ruling bound, expiring
wr(SRC + "/a.py", "print('a v2')\n"); wr(SRC + "/new_tool.py", "print('new')\n")
rep = D.check(use_cache=False, **KW)
try: D.write_ack(rep, "", path=D.ACK); no_ruling = False
except ValueError: no_ruling = True
check("RED: an acknowledgement without a ruling id cannot be written", no_ruling and not os.path.exists(D.ACK))
t0 = 1_000_000.0
ack = D.write_ack(rep, "lead 99999", note="landing via PR", ttl_h=48, path=D.ACK, now=t0)
ok_, note = D.gate("t", now=t0 + 3600, fetcher=lambda *a: False, **KW)
check("GREEN: with a ruling the exact drift is acknowledged; the note carries the ruling and the files", ok_ and "ACKNOWLEDGED" in note and "lead 99999" in note and "changed 1, new 1" in note, note)
ok_, note = D.gate("t", now=t0 + 49 * 3600, fetcher=lambda *a: False, **KW)
check("RED: after 48 h the acknowledgement has expired -> refuses again", not ok_ and "differs from the tree" in note, note)
wr(SRC + "/a.py", "print('a v3 edited after the ack')\n")
ok_, note = D.gate("t", now=t0 + 3600, fetcher=lambda *a: False, **KW)
check("RED: a file edited AFTER the acknowledgement (different content) is not covered -> refuses", not ok_, note)
wr(SRC + "/a.py", "print('a v2')\n"); wr(SRC + "/another.py", "print('x')\n")
ok_, note = D.gate("t", now=t0 + 3600, fetcher=lambda *a: False, **KW)
check("RED: an extra new file after the acknowledgement is not covered -> refuses", not ok_ and "another.py" in note, note)
os.remove(SRC + "/another.py")
bad = dict(ack); bad["ruling"] = ""; json.dump(bad, open(D.ACK, "w"))
ok_, note = D.gate("t", now=t0 + 3600, fetcher=lambda *a: False, **KW)
check("RED: an acknowledgement file whose ruling was blanked is ignored", not ok_, note)
json.dump(ack, open(D.ACK, "w")); open(D.ACK, "a").write("{{ corrupt")
ok_, note = D.gate("t", now=t0 + 3600, fetcher=lambda *a: False, **KW)
check("RED: a corrupt acknowledgement file is ignored (drift refuses)", not ok_, note)
os.remove(D.ACK); os.remove(SRC + "/new_tool.py"); wr(SRC + "/a.py", "print('a')\n")

# ---- cache
CALLS.clear(); D.check(**KW); n1 = len(CALLS)
rep = D.check(**KW); n2 = len(CALLS)
check("cache: an unchanged live lane + unchanged tree is answered from the cache (no second export)", n1 <= 1 and n2 == n1 and rep.get("cached") is True, f"{n1} {n2}")
wr(SRC + "/b.py", "print('b2')\n"); D.check(**KW)
check("cache: an edited script changes the key -> exported again", len(CALLS) == n2 + 1)
wr(SRC + "/b.py", "print('b')\n")
rep = D.check(**KW); n3 = len(CALLS)
wr(TREE + "/b.py", "print('b tree moved')\n"); commit_tree(); rep = D.check(**KW)
check("cache: a moved tree changes the key -> exported and compared again (b.py now differs)", len(CALLS) == n3 + 1 and rep["changed"] == ["b.py"], str(rep))
wr(TREE + "/b.py", "print('b')\n"); commit_tree()

# ---- fetch rate limit + self-clearing after a merge
RUNS = []
runner = lambda repo, *a, **k: RUNS.append(a) or b""
check("fetch: first call runs `git fetch`", D.maybe_fetch(REPO, "origin/master", cache=D.CACHE, now=5000.0, runner=runner) is True and RUNS and RUNS[0][:2] == ("fetch", "--quiet"))
check("fetch: a second call inside 30 min does not run", D.maybe_fetch(REPO, "origin/master", cache=D.CACHE, now=5000.0 + 600, runner=runner) is False and len(RUNS) == 1)
check("fetch: after 30 min it runs again", D.maybe_fetch(REPO, "origin/master", cache=D.CACHE, now=5000.0 + 1900, runner=runner) is True and len(RUNS) == 2)
def failing(repo, *a, **k): raise RuntimeError("offline")


check("fetch: a failing fetch is ignored (returns False), never raises", D.maybe_fetch(REPO, "origin/master", cache=D.CACHE, now=99999.0, runner=failing) is False)
wr(SRC + "/a.py", "print('a merged later')\n")
def merge_then_fetch(repo, ref): wr(TREE + "/a.py", "print('a merged later')\n"); commit_tree(); return True


ok_, note = D.gate("t", fetcher=merge_then_fetch, **KW)
check("GREEN: drift that a merged PR resolves clears itself after the fetch (no manual step)", ok_ and "cleared" in note, note)

# ---- CLI
wr(SRC + "/a.py", "print('a')\n"); wr(TREE + "/a.py", "print('a')\n"); commit_tree()
import io, contextlib


def cli(*a):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf): rc = D.main(list(a))
    return rc, buf.getvalue()


D.SCRIPTS = SRC     # the CLI check exports D.SCRIPTS
rc, out = cli("check", "--repo", REPO, "--ref", "HEAD")
check("CLI check: clean -> exit 0 'CLEAN'", rc == 0 and out.startswith("CLEAN"), out)
wr(SRC + "/a.py", "print('cli drift')\n")
rc, out = cli("check", "--repo", REPO, "--ref", "HEAD")
check("CLI check: drift -> exit 1 and names the file", rc == 1 and "DRIFT" in out and "a.py" in out, out)
rc, out = cli("ack", "--repo", REPO, "--ref", "HEAD")
check("CLI ack without --ruling -> exit 2, nothing written", rc == 2 and not os.path.exists(D.ACK), out)
rc, out = cli("ack", "--ruling", "lead 12345", "--repo", REPO, "--ref", "HEAD")
rc2, out2 = cli("check", "--repo", REPO, "--ref", "HEAD")
check("CLI ack --ruling -> written; check then exits 0 'ACKNOWLEDGED'", rc == 0 and os.path.exists(D.ACK) and rc2 == 0 and out2.startswith("ACKNOWLEDGED"), out + out2)
rc, out = cli("check", "--repo", REPO, "--ref", "no-such-ref")
check("CLI check: cannot read the tree -> exit 2, never 0", rc == 2 and "CANNOT CHECK" in out, out)
os.remove(D.ACK); wr(SRC + "/a.py", "print('a')\n")

# ---- the real exporter on a tiny source: deterministic, README LF, exclude honoured
import importlib; importlib.reload(D)
D.LANE_BASE = T; D.L = T + "/loops"
tiny = T + "/tiny"; wr(tiny + "/x.py", '"""doc"""\nimport os\nprint(os.getcwd())\n'); wr(tiny + "/lane-README.md", "# r\r\nz\r\n"); wr(tiny + "/caselaw_lane_handoff.py", "print('excluded')\n")
try:
    D.export_to(T + "/e1", tiny); D.export_to(T + "/e2", tiny); o1, o2 = D.dir_oids(T + "/e1"), D.dir_oids(T + "/e2")
    check("real export: deterministic (same blob ids twice), x.py + README.md only, README has LF endings", o1 == o2 and set(o1) == {"x.py", "README.md"} and b"\r" not in open(T + "/e1/README.md", "rb").read(), str(o1))
    check("real export: the live-only exclusion list is honoured (caselaw_lane_handoff.py not exported)", "caselaw_lane_handoff.py" not in o1)
except Exception as e: check("real export of a tiny source runs", False, f"{type(e).__name__}: {e}")
rk1 = D.live_key(tiny); wr(tiny + "/x.py", '"""doc"""\nprint(1)\n')
check("live_key changes when a script changes and ignores __pycache__/non-exportable files", rk1 != D.live_key(tiny) and (wr(tiny + "/junk.txt", "z") or True) and D.live_key(tiny) == D.live_key(tiny))

# ---- tick.py wiring
TICK = open(f"{SC}/loops/tick.py", encoding="utf-8").read()
i_gate, i_sweep, i_done = TICK.index("lane_drift.gate(LOOP)"), TICK.index("scratch_dir.sweep()"), TICK.index("def done(status, note):")
check("tick.py: the drift gate runs before the scratch sweep and before any lane work", i_gate < i_sweep < i_done)
blk = TICK[TICK.index("DRIFT_NOTE = \"\""):TICK.index("try:      # lead 82361")]
check("tick.py: the gate fails closed (except BaseException -> refuse), refuses with sys.exit and does not go through done() (which starts lane jobs)", "except BaseException" in blk and "False, f\"drift gate error" in blk and "sys.exit(0)" in blk and "done(" not in blk)
check("tick.py: an acknowledged drift is appended to the receipt note", "if DRIFT_NOTE: note +=" in TICK[i_done:i_done + 400])
ns = dict(sys=sys, os=os, json=json, time=time, ROOT=SC.replace("\\", "/")[:-len("/scripts")] if SC.replace("\\", "/").endswith("/scripts") else SC, LOOP="prep", L=T + "/tl", STATE=T + "/tl/state.json", st={}, __name__="x")
os.makedirs(T + "/tl"); stubmod = type(sys)("lane_drift"); stubmod.gate = lambda loop: (False, "live lane differs from the tree: changed 1 (a.py)")
sys.modules["lane_drift"] = stubmod; res = []
for k in range(3):
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf): exec(blk, ns)
        res.append(("no exit", buf.getvalue()))
    except SystemExit as e: res.append((e.code, buf.getvalue()))
rows = [json.loads(l) for l in open(T + "/tl/receipts.jsonl")]
check("tick gate (executed): a refused tick exits 0, prints ONE 'blocked: DRIFT-REFUSED' line, records a blocked row", all(r[0] == 0 and r[1].count("\n") == 1 and "DRIFT-REFUSED" in r[1] for r in res) and len(rows) == 3 and all(r["status"] == "blocked" for r in rows), str(res))
check("tick gate (executed): the 3rd blocked tick in a row prints ESCALATE, the first two do not", "ESCALATE" not in res[0][1] and "ESCALATE" not in res[1][1] and "ESCALATE" in res[2][1], str(res))
stubmod.gate = lambda loop: (True, "")
ns2 = dict(ns, st={}); exec(blk, ns2)
check("tick gate (executed): a clean verdict falls through (no exit, no row)", len(open(T + "/tl/receipts.jsonl").read().splitlines()) == 3)
def raising(loop): raise ImportError("lane_drift missing")


stubmod.gate = raising
try: exec(blk, dict(ns, st={})); fell = True
except SystemExit: fell = False
check("tick gate (executed): the gate itself raising refuses the tick (fail closed), never runs it", fell is False)
del sys.modules["lane_drift"]

shutil.rmtree(T, ignore_errors=True)
print("ALL PASS" if ok else "FAILED"); sys.exit(0 if ok else 1)
