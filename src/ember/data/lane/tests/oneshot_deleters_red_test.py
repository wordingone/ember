# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Red/green for the four one-shot deleters after #2454: _pg_obj_del.py, _wiki_del.py, _ws_del.py, delete_approved_dirs.py. Importing any of them runs nothing (AST: only imports/constants/defs and the __main__ guard at module level, no
os.remove / shutil.rmtree call); the default is a DRY RUN that deletes nothing. _pg_obj_del goes through the server path (fresh entry, size AND LFS sha256; corrupt / no-LFS-sha / missing keep the file; receipt before remove). The three
no-copy scripts refuse --go without a mail-id --ruling or without --manifest-sha256 (the PLAN_SHA256 the dry run printed; a plan that differs, e.g. a file added after the ruling, refuses everything), write the manifest of every file before the first remove, delete only files that are still the manifest's files, and label their receipts ruled-no-copy-remove.
Tmp tree only; nothing real is read or deleted. Run: python scripts/tests/oneshot_deleters_red_test.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from lane_config import LANE_ROOT
import os, sys, json, shutil, hashlib, tempfile, importlib.util, io, contextlib, ast, time, re
HERE = os.path.dirname(os.path.abspath(__file__)); SC = os.path.dirname(HERE)
sys.path.insert(0, SC)
ok = True


def check(label, cond):
    global ok
    ok &= bool(cond); print("PASS" if cond else "FAIL", label)


SCR = (LANE_ROOT + "/scratch"); os.makedirs(SCR, exist_ok=True)
T = tempfile.mkdtemp(dir=SCR, prefix="os-test-").replace("\\", "/"); sha = lambda b: hashlib.sha256(b).hexdigest()


def load(name):
    spec = importlib.util.spec_from_file_location(name + "_under_test", f"{SC}/{name}.py"); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m


def mk(p, b): os.makedirs(os.path.dirname(p), exist_ok=True); open(p, "wb").write(b); return p


def run(m, *argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf): rc = m.main(list(argv))
    return rc, buf.getvalue()


def lines(p): return [json.loads(l) for l in open(p)] if os.path.exists(p) else []


for name in ("_pg_obj_del", "_wiki_del", "_ws_del", "delete_approved_dirs"):
    src = open(f"{SC}/{name}.py", encoding="utf-8").read(); tree = ast.parse(src)
    bad_top = [type(n).__name__ for n in tree.body if not (isinstance(n, (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.Assign)) or (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))
               or (isinstance(n, ast.Expr) and ast.unparse(n.value.func) == "sys.path.insert" if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call) else False) or (isinstance(n, ast.If) and "__name__" in ast.unparse(n.test)))]
    calls = {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
    check(f"{name}: importing runs nothing (module level is imports/constants/defs/__main__ guard) and no os.remove/rmtree call", not bad_top and not (calls & {"os.remove", "shutil.rmtree", "os.unlink"}))

# ---- _pg_obj_del (server path)
PG = load("_pg_obj_del"); PG.PACKED = T + "/packed"; PG.MD = T + "/pgmd"
D = {n: os.urandom(2600) + n.encode() for n in "abcd"}
P = {n: mk(f"{PG.PACKED}/pg-1/objects/{n}.bin", D[n]) for n in "abcd"}
cor = bytearray(D["b"]); cor[2] ^= 1
SRV = {"text/pg-1/objects/a.bin": (len(D["a"]), sha(D["a"])), "text/pg-1/objects/b.bin": (len(D["b"]), sha(bytes(cor))), "text/pg-1/objects/c.bin": (len(D["c"]), None)}
PG.READER = lambda repo, hp: SRV.get(hp)
rc, out = run(PG)
check("_pg_obj_del: default is a dry run, nothing deleted, no receipt", all(os.path.exists(p) for p in P.values()) and not os.path.exists(T + "/pgmd/pg-objects-receipts.jsonl") and "DRY VERIFIED 1 files" in out)
rc, out = run(PG, "--go")
check("_pg_obj_del GREEN: a (fresh entry, size + LFS sha256) deleted; exit 7 because the others did not verify", not os.path.exists(P["a"]) and rc == 7)
check("_pg_obj_del RED: b (same-size corrupt upload), c (no LFS sha256), d (no server entry) all kept", all(os.path.exists(P[n]) for n in "bcd"))
rr = lines(T + "/pgmd/pg-objects-receipts.jsonl")
check("_pg_obj_del: one receipt row (server-verified, both hashes), plan manifest has all 4 rows", len(rr) == 1 and rr[0]["kind"] == "server-verified" and rr[0]["local_sha256"] == rr[0]["server_sha256"] and len(lines(T + "/pgmd/pg-objects-manifest.jsonl")) == 4)

# ---- _wiki_del (ruled, no copy)
W = load("_wiki_del"); W.D = T + "/wiki"; W.MD = T + "/wikimd"
big = lambda n: os.urandom(12000) + n.encode()
for f in ("enwiki-part1.bz2", "verified-part1.bz2", "derived-1.jsonl.zst"): mk(f"{W.D}/{f}", big(f))
for f in sorted(W.KEEP): mk(f"{W.D}/{f}", big(f))
mk(f"{W.D}/small.txt", b"tiny")
rc, out = run(W)
check("_wiki_del: default is a dry run (nothing deleted)", rc == 0 and len(os.listdir(W.D)) == 7 and "DRY MANIFEST 3 files" in out)
PW = re.search(r"PLAN_SHA256 ([0-9a-f]{64})", out).group(1)
rc, out = run(W, "--go")
check("_wiki_del RED: --go without --ruling refused (exit 5), nothing deleted, no manifest", rc == 5 and len(os.listdir(W.D)) == 7 and not os.path.exists(T + "/wikimd/wikipedia-20220501-manifest.jsonl"))
rc, out = run(W, "--go", "--ruling", "x", "--manifest-sha256", PW)
check("_wiki_del RED (#2459 F1): a ruling that is not a mail id ('x') is refused, nothing deleted", rc == 5 and len(os.listdir(W.D)) == 7)
rc, out = run(W, "--go", "--ruling", "lead 99999")
check("_wiki_del RED (#2459 F1): --go with a ruling but no --manifest-sha256 is refused (NO_PIN), nothing deleted, no manifest", rc == 5 and "NO_PIN" in out and len(os.listdir(W.D)) == 7 and not os.path.exists(T + "/wikimd/wikipedia-20220501-manifest.jsonl"))
mk(f"{W.D}/derived-2.jsonl.zst", big("late"))
rc, out = run(W, "--go", "--ruling", "lead 99999", "--manifest-sha256", PW)
check("_wiki_del RED (#2459 F1): a file added after the ruling changes the plan: PIN_MISMATCH (exit 6), every file stays, no manifest", rc == 6 and "PIN_MISMATCH" in out and os.path.exists(f"{W.D}/derived-2.jsonl.zst") and len(os.listdir(W.D)) == 8 and not os.path.exists(T + "/wikimd/wikipedia-20220501-manifest.jsonl"))
os.remove(f"{W.D}/derived-2.jsonl.zst")
rc, out = run(W, "--go", "--ruling", "lead 99999", "--manifest-sha256", PW)
check("_wiki_del GREEN with a ruling: the 3 big non-kept files are removed; KEEP files and the small file stay", rc == 0 and sorted(os.listdir(W.D)) == sorted(list(W.KEEP) + ["small.txt"]))
mrows = lines(T + "/wikimd/wikipedia-20220501-manifest.jsonl"); rr = lines(T + "/wikimd/wikipedia-20220501-receipts.jsonl")
check("_wiki_del: manifest rows carry sha256 + inode + the ruling; receipts are ruled-no-copy-remove (never server-verified)", len(mrows) == 3 and all(r["sha256"] and r["ino"] and r["ruling"] == "lead 99999" for r in mrows) and len(rr) == 3 and all(r["kind"] == "ruled-no-copy-remove" for r in rr))

# ---- _ws_del
S = load("_ws_del"); S.D = T + "/ws"; S.MD = T + "/wsmd"
for f in ("a.xml.bz2", "b.jsonl"): mk(f"{S.D}/{f}", big(f))
rc, out = run(S)
PS = re.search(r"PLAN_SHA256 ([0-9a-f]{64})", out).group(1)
rc, out = run(S, "--go")
check("_ws_del RED: --go without --ruling refused, files stay", rc == 5 and len(os.listdir(S.D)) == 2)
rc, out = run(S, "--go", "--ruling", "lead 99998")
check("_ws_del RED (#2459 F1): no --manifest-sha256 -> NO_PIN, files stay", rc == 5 and "NO_PIN" in out and len(os.listdir(S.D)) == 2)
rc, out = run(S, "--go", "--ruling", "lead 99998", "--manifest-sha256", "0" * 64)
check("_ws_del RED (#2459 F1): a pin that is not the plan: PIN_MISMATCH (exit 6), files stay, no manifest", rc == 6 and "PIN_MISMATCH" in out and len(os.listdir(S.D)) == 2 and not os.path.exists(T + "/wsmd/wikisource-manifest.jsonl"))
rc, out = run(S, "--go", "--ruling", "lead 99998", "--manifest-sha256", PS)
check("_ws_del GREEN with a ruling: files removed, emptied directory removed with rmdir", rc == 0 and not os.path.exists(S.D) and len(lines(T + "/wsmd/wikisource-manifest.jsonl")) == 2)
rc, out = run(S)
check("_ws_del: a directory that no longer exists is a no-op (the script is inert after its one run)", rc == 0 and "absent" in out)

# ---- delete_approved_dirs
A = load("delete_approved_dirs"); A.ROOT = T + "/staging"; A.MD = A.ROOT + "/logs/manifests"
os.makedirs(A.ROOT + "/logs")
for f in ("w1.zst", "w2.zst", "keep.done"): mk(f"{A.ROOT}/pg/work/sub/{f}", big(f))
for f in ("a.mp3", "b.txt", "pairs.jsonl"): mk(f"{A.ROOT}/lvpilot/{f}", big(f))
rc, out = run(A)
check("delete_approved_dirs: default is a dry run, nothing deleted", rc == 0 and os.path.exists(A.ROOT + "/pg/work/sub/w1.zst") and "DRY pg-work 2 files" in out)
PINS = re.findall(r"PLAN_SHA256 (\S+=[0-9a-f]{64})", out)
check("delete_approved_dirs: the dry run prints one PLAN_SHA256 NAME=SHA per job", len(PINS) == 2 and {p.split("=")[0] for p in PINS} == {"pg-work", "lvpilot"})
rc, out = run(A, "--go")
check("delete_approved_dirs RED: --go without --ruling refused, nothing deleted", rc == 5 and os.path.exists(A.ROOT + "/pg/work/sub/w1.zst") and os.path.exists(A.ROOT + "/lvpilot/a.mp3"))
rc, out = run(A, "--go", "--ruling", "lead 99997")
check("delete_approved_dirs RED (#2459 F1): --go with a ruling but no pins: every job refused (NO_PIN, exit 7), nothing deleted", rc == 7 and out.count("NO_PIN") >= 2 and os.path.exists(A.ROOT + "/pg/work/sub/w1.zst") and os.path.exists(A.ROOT + "/lvpilot/a.mp3"))
pin_args = [x for p in PINS for x in ("--manifest-sha256", p)]
mk(f"{A.ROOT}/pg/work/sub/w3.zst", big("w3"))
rc, out = run(A, "--go", "--ruling", "lead 99997", "--manifest-sha256", [p for p in PINS if p.startswith("pg-work=")][0], "--manifest-sha256", "lvpilot=" + "0" * 64)
check("delete_approved_dirs RED (#2459 F1): a file added after the ruling changes pg-work's plan: PIN_MISMATCH (exit 7), pg-work files stay", rc == 7 and "PIN_MISMATCH" in out and os.path.exists(A.ROOT + "/pg/work/sub/w1.zst") and os.path.exists(f"{A.ROOT}/pg/work/sub/w3.zst"))
rc, out = run(A, "--go", "--ruling", "lead 99997", "--manifest-sha256", "lvpilot=" + "0" * 64, "--manifest-sha256", "pg-work=" + "0" * 64)
check("delete_approved_dirs RED (#2459 F1): wrong pins on both jobs: both refused, nothing deleted", rc == 7 and os.path.exists(A.ROOT + "/lvpilot/a.mp3") and os.path.exists(A.ROOT + "/pg/work/sub/w1.zst"))
os.remove(f"{A.ROOT}/pg/work/sub/w3.zst")
rc, out = run(A, "--go", "--ruling", "lead 99997", *pin_args)
check("delete_approved_dirs GREEN with a ruling: only the listed extensions go; .done and pairs.jsonl stay", rc == 0 and not os.path.exists(A.ROOT + "/pg/work/sub/w1.zst") and os.path.exists(A.ROOT + "/pg/work/sub/keep.done") and os.path.exists(A.ROOT + "/lvpilot/pairs.jsonl") and not os.path.exists(A.ROOT + "/lvpilot/a.mp3"))
rr = lines(A.ROOT + "/logs/delete-approved-dirs-rows.jsonl")
check("delete_approved_dirs: 4 ruled-no-copy-remove receipt rows (2 pg + 2 lvpilot) and a manifest per job with sha256", len(rr) == 4 and all(r["kind"] == "ruled-no-copy-remove" and r["ruling"] == "lead 99997" and r["plan_sha256"] for r in rr) and all(m["sha256"] for m in lines(A.MD + "/pg-work-manifest.jsonl")))
shutil.rmtree(T, ignore_errors=True)
print("ALL PASS" if ok else "FAILED"); sys.exit(0 if ok else 1)
