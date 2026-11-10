# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Red/green for drop_execute.py after #2454 (tmp tree, fake server injected as READER, nothing real is read or deleted).
Tier 1: a file is dropped only when the server entry read back NOW has equal size AND LFS sha256; a same-size corrupt upload, an entry without an LFS sha256, a missing entry, a stale scan/manifest row, a path outside packed/ and
a path reached through a junction all keep the file; the default (no --go) is a dry run that verifies and deletes nothing. Tier 2 (no copy): ruling-bound, manifest first, receipts labelled ruled-no-copy, no rmtree; a linked or
hard-linked dir is skipped. Run: python scripts/tests/drop_execute_verify_red_test.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from lane_config import HF_TRAIN_REPO, LANE_ROOT
import os, sys, json, time, shutil, hashlib, tempfile, subprocess, importlib.util, io, contextlib
HERE = os.path.dirname(os.path.abspath(__file__)); SC = os.path.dirname(HERE)
sys.path.insert(0, SC)
ok = True


def check(label, cond):
    global ok
    ok &= bool(cond); print("PASS" if cond else "FAIL", label)


SCR = (LANE_ROOT + "/scratch"); os.makedirs(SCR, exist_ok=True)
T = tempfile.mkdtemp(dir=SCR, prefix="dx-test-").replace("\\", "/"); sha = lambda b: hashlib.sha256(b).hexdigest(); old = time.time() - 7200
spec = importlib.util.spec_from_file_location("drop_execute_under_test", SC + "/drop_execute.py"); M = importlib.util.module_from_spec(spec); spec.loader.exec_module(M)
M.ROOT = T; M.RC = T + "/logs/exec.jsonl"; os.makedirs(T + "/logs"); os.makedirs(T + "/packed/p1/shards"); os.makedirs(T + "/other")


def mk(path, data, age=True):
    os.makedirs(os.path.dirname(path), exist_ok=True); open(path, "wb").write(data)
    if age: os.utime(path, (old, old))
    return path


D = {n: os.urandom(4000) + n.encode() for n in ("a", "b", "c", "d", "e", "f", "g")}
P = {n: mk(f"{T}/packed/p1/shards/{n}.bin", D[n]) for n in ("a", "b", "c", "d", "e")}
P["f"] = mk(f"{T}/other/f.bin", D["f"])                              # outside packed/
P["g"] = None
cor = bytearray(D["b"]); cor[3] ^= 1
SRV = {"text/p1/shards/a.bin": (len(D["a"]), sha(D["a"])), "text/p1/shards/b.bin": (len(D["b"]), sha(bytes(cor))), "text/p1/shards/c.bin": (len(D["c"]), None),
       "text/p1/shards/e.bin": (len(D["e"]), sha(D["e"])), "text/other/f.bin": (len(D["f"]), sha(D["f"]))}
J = f"{T}/packed/jlink"; r = subprocess.run(["cmd", "/c", "mklink", "/J", J.replace("/", "\\"), (T + "/other").replace("/", "\\")], capture_output=True, text=True)
check("setup: junction packed/jlink -> other", os.path.isdir(J))
hdr = "class\tgib\tpack\tsub\tkey\tpath\n"
rows = [("DROP-FREE", "p1", "shards", "text/p1/shards/a.bin", P["a"]), ("DROP-HF-ONLY", "p1", "shards", "text/p1/shards/b.bin", P["b"]), ("DROP-HF-ONLY", "p1", "shards", "text/p1/shards/c.bin", P["c"]),
        ("DROP-HF-ONLY", "p1", "shards", "text/p1/shards/d.bin", P["d"]), ("DROP-FREE", "p1", "shards", "text/p1/shards/e.bin", P["e"]),
        ("DROP-FREE", "other", "x", "text/other/f.bin", P["f"]), ("DROP-FREE", "other", "x", "text/other/f.bin", J + "/f.bin")]
MAN = T + "/drop.tsv"; open(MAN, "w").write(hdr + "".join(f"{c}\t0.0\t{p}\t{s}\t{k}\t{pa}\n" for c, p, s, k, pa in rows))
M.READER = lambda repo, hp: SRV.get(hp)
def run(*argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf): M.main(list(argv))
    return buf.getvalue()
def rcpts(): return [json.loads(l) for l in open(M.RC)] if os.path.exists(M.RC) else []
out = run(MAN)
check("RED default is a dry run: it verifies but nothing is deleted and no receipt is written", all(os.path.exists(p) for p in (P["a"], P["b"], P["c"], P["d"], P["e"], P["f"])) and not rcpts() and "DRY tier1" in out)
out = run(MAN, "--go")
left = {n: os.path.exists(p) for n, p in P.items() if p}
check("GREEN a and e (server size + LFS sha256 equal, read back now) are deleted", not left["a"] and not left["e"])
check("RED b (same-size corrupt upload): kept", left["b"] and "MISMATCH kept" in out)
check("RED c (server entry equal size, no LFS sha256): kept", left["c"])
check("RED d (stale manifest row, the server has no entry): kept", left["d"])
check("RED f (a manifest row pointing outside packed/, server matches): kept", left["f"] and "outside" in out)
check("RED a path through a junction inside packed/ that resolves to other/: kept", os.path.exists(P["f"]))
rr = rcpts()
check("receipt rows exist for exactly the two deleted files, each with the compared server and local sha256 (no fixed sentence)", len(rr) == 2 and all(x["kind"] == "server-verified" and x["server_sha256"] == x["local_sha256"] for x in rr) and rr[0]["tier"] == 1)
check("HF-ONLY waiver text only on HF-ONLY rows (none deleted here)", all(x.get("waiver") is None for x in rr))
os.rmdir(J)

# orphan scan row claiming a copy, the server says no
mk(f"{T}/scratch/orphan-packs/o1.bin", D["g"]); open(T + "/logs/drop-scan-1.jsonl", "w").write(json.dumps(dict(path=f"{T}/scratch/orphan-packs/o1.bin", hf=[("wordingone/" + HF_TRAIN_REPO + ":text/o1.bin")], nlink=1)) + "\n")
out = run(MAN, "--go")
check("RED orphan-pack file whose scan says 'on HF' but the server has no entry now: kept", os.path.exists(f"{T}/scratch/orphan-packs/o1.bin"))
SRV["text/o1.bin"] = (len(D["g"]), sha(D["g"]))
out = run(MAN, "--go")
check("GREEN the same orphan file once the server entry matches is deleted", not os.path.exists(f"{T}/scratch/orphan-packs/o1.bin"))

# tier 2 (no copy): ruling-bound, manifest first, no rmtree
M.TIER2 = ["t2-ok", "t2-hard", "t2-junc"]
for i in range(3): mk(f"{T}/scratch/t2-ok/sub/f{i}.zst", os.urandom(500))
mk(f"{T}/scratch/t2-hard/h.zst", b"h" * 800); os.link(f"{T}/scratch/t2-hard/h.zst", f"{T}/other/h-second-name.zst")
mk(f"{T}/other/keepme.zst", b"k" * 700)
Jt = f"{T}/scratch/t2-junc"; subprocess.run(["cmd", "/c", "mklink", "/J", Jt.replace("/", "\\"), (T + "/other").replace("/", "\\")], capture_output=True, text=True)
out = run(MAN, "--go", "--tier2", "--no-orphan")
check("GREEN tier 2 dir with no links: every file removed, emptied dirs pruned by rmdir", not os.path.exists(f"{T}/scratch/t2-ok"))
check("RED tier 2 dir containing a hard-linked file is skipped whole", os.path.exists(f"{T}/scratch/t2-hard/h.zst") and "hard-linked" in out)
check("RED tier 2 name that is a junction to another dir is skipped and the target is untouched", os.path.exists(f"{T}/other/keepme.zst") and "link or junction" in out)
t2 = [x for x in rcpts() if x["kind"] == "ruled-no-copy-remove"]
tm = [json.loads(l) for l in open(T + "/logs/drop-exec-tier2-manifest.jsonl")]
check("tier 2 receipts say ruled-no-copy-remove with the ACK as ruling, and the manifest rows (sha256, inode) were written for all 3 files", len(t2) == 3 and len(tm) == 3 and all(x["ruling"] == M.ACK and x["sha256"] and x["ino"] for x in tm))
try: os.rmdir(Jt)
except OSError: pass
src = open(SC + "/drop_execute.py", encoding="utf-8").read()
import ast
calls = {ast.unparse(n.func) for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Call)}
check("source: drop_execute.py calls neither shutil.rmtree nor os.remove (docstring mentions aside)", not (calls & {"shutil.rmtree", "os.remove", "os.unlink"}))
shutil.rmtree(T, ignore_errors=True)
print("ALL PASS" if ok else "FAILED"); sys.exit(0 if ok else 1)
