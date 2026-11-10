# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Red/green for free_b.py after #2454 (tmp tree, fake server + fake tree lister, nothing real touched). Importing runs nothing; the default is a dry run. shards-v0 duplicates go only when sha256-identical to a DIFFERENT file;
upload/ files go only on a fresh server entry with equal size AND LFS sha256 (no size-only match, no suffix guess that the server read does not confirm); no-copy garbage (wiki .bad partial, TextCaps zip) needs --ruling and is
labelled ruled-no-copy; the receipt row is on disk before each remove. Run: python scripts/tests/free_b_verify_red_test.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from lane_config import LANE_ROOT
import os, sys, json, shutil, hashlib, tempfile, importlib.util, io, contextlib, glob, ast
HERE = os.path.dirname(os.path.abspath(__file__)); SC = os.path.dirname(HERE)
sys.path.insert(0, SC)
ok = True
def check(label, cond):
    global ok
    ok &= bool(cond); print("PASS" if cond else "FAIL", label)
spec = importlib.util.spec_from_file_location("free_b_under_test", SC + "/free_b.py"); FB = importlib.util.module_from_spec(spec)
SCR = (LANE_ROOT + "/scratch"); os.makedirs(SCR, exist_ok=True)
T = tempfile.mkdtemp(dir=SCR, prefix="fb-test-").replace("\\", "/"); sha = lambda b: hashlib.sha256(b).hexdigest()
before = set(glob.glob((LANE_ROOT + "/audit/free-b-receipt*"))); spec.loader.exec_module(FB)
check("importing free_b.py runs nothing (no new file in the real audit dir)", set(glob.glob((LANE_ROOT + "/audit/free-b-receipt*"))) == before)
FB.SHARDS_A = T + "/A"; FB.SHARDS_B = T + "/B"; FB.UPLOAD = T + "/upload"; FB.AUDIT = T + "/audit"; FB.WIKI_PARTS = T + "/wiki/parts"; FB.TEXTCAPS_ZIP = T + "/tc/train_val_images.zip"; FB.TEXTCAPS_TRAIN = T + "/tc/images/train"
def mk(p, b): os.makedirs(os.path.dirname(p), exist_ok=True); open(p, "wb").write(b); return p
D = {n: os.urandom(2500) + n.encode() for n in ("s1", "s2", "s3", "u1", "u2", "u3", "u4", "w")}
mk(FB.SHARDS_A + "/s1.bin", D["s1"]); mk(FB.SHARDS_B + "/s1.bin", D["s1"])                                  # identical duplicate
mk(FB.SHARDS_A + "/s2.bin", D["s2"]); x = bytearray(D["s2"]); x[4] ^= 1; mk(FB.SHARDS_B + "/s2.bin", bytes(x))   # same size, different content
mk(FB.SHARDS_A + "/s3.bin", D["s3"])                                                                          # no duplicate
bad = bytearray(D["u2"]); bad[2] ^= 1
SRV = {("r", "x/u1.bin"): (len(D["u1"]), sha(D["u1"])), ("r", "x/u2.bin"): (len(D["u2"]), sha(bytes(bad))), ("r", "x/u3.bin"): (len(D["u3"]), None)}
for n in ("u1", "u2", "u3", "u4"): mk(f"{FB.UPLOAD}/raw/{n}.bin", D[n])
FB.REPOS = (("raw", "r"),); FB.READER = lambda repo, hp: SRV.get((repo, hp)); FB.TREE = lambda repo: ["x/u1.bin", "x/u2.bin", "x/u3.bin", "other/u4-not-matching.bin"]
mk(FB.WIKI_PARTS + "/part1.bz2.bad", b"partial"); mk(FB.WIKI_PARTS + "/part2.bz2", b"good")
mk(FB.TEXTCAPS_ZIP, b"zip" * 100)
os.makedirs(FB.TEXTCAPS_TRAIN, exist_ok=True)
def run(*argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf): R = FB.main(list(argv))
    return R, buf.getvalue()
def rc():
    p = glob.glob(FB.AUDIT + "/free-b-receipts-*.jsonl"); return [json.loads(l) for f in p for l in open(f)]
R, out = run()
check("RED default is a dry run: nothing deleted, no receipt rows", os.path.exists(FB.SHARDS_A + "/s1.bin") and os.path.exists(f"{FB.UPLOAD}/raw/u1.bin") and not rc() and R["mode"] == "DRY")
R, out = run("--go")
check("GREEN s1 (sha256-identical to a different file in B) is deleted, the duplicate stays", not os.path.exists(FB.SHARDS_A + "/s1.bin") and os.path.exists(FB.SHARDS_B + "/s1.bin"))
check("RED s2 (same size, different content): kept", os.path.exists(FB.SHARDS_A + "/s2.bin"))
check("RED s3 (no duplicate at all): kept", os.path.exists(FB.SHARDS_A + "/s3.bin"))
check("GREEN u1 (fresh server entry, equal size + LFS sha256) is deleted", not os.path.exists(f"{FB.UPLOAD}/raw/u1.bin"))
check("RED u2 (same-size corrupt upload): kept", os.path.exists(f"{FB.UPLOAD}/raw/u2.bin"))
check("RED u3 (server entry without LFS sha256: the old size-only acceptance): kept", os.path.exists(f"{FB.UPLOAD}/raw/u3.bin"))
check("RED u4 (the tree has no matching path): kept", os.path.exists(f"{FB.UPLOAD}/raw/u4.bin"))
check("RED no-copy garbage without --ruling: wiki .bad partial and the TextCaps zip are skipped, not deleted", os.path.exists(FB.WIKI_PARTS + "/part1.bz2.bad") and not any("TextCaps" in str(d) for d in R["deleted"]) and "needs --ruling" in " ".join(R["skipped"]))
rows = rc()
check("receipt rows: s1 local-duplicate (both hashes) and u1 server-verified, nothing else", sorted(r["kind"] for r in rows) == ["local-duplicate", "server-verified"] and all(r.get("local_sha256") for r in rows))
# the TextCaps zip needs >= 21953 extracted train images before it counts as regenerable: create them cheaply
for i in range(21953): open(f"{FB.TEXTCAPS_TRAIN}/{i}.jpg", "wb").close()
R, out = run()
PLAN = R["nocopy_plan_sha256"]
check("the dry run names the no-copy plan sha256 the lead rules on", bool(PLAN) and len(PLAN) == 64 and PLAN in out)
R, out = run("--go", "--ruling", "x", "--manifest-sha256", PLAN)
check("RED (#2459 F1) a ruling that is not a mail id ('x'): the no-copy garbage is skipped, nothing deleted", os.path.exists(FB.WIKI_PARTS + "/part1.bz2.bad") and os.path.exists(FB.TEXTCAPS_ZIP) and "needs --ruling" in " ".join(R["skipped"]))
R, out = run("--go", "--ruling", "lead 81345")
check("RED (#2459 F1) --go with a ruling but no --manifest-sha256: NO_PIN, the wiki .bad partial and the zip stay", os.path.exists(FB.WIKI_PARTS + "/part1.bz2.bad") and os.path.exists(FB.TEXTCAPS_ZIP) and "NO_PIN" in " ".join(R["skipped"]))
mk_late = FB.WIKI_PARTS + "/part9.bz2.bad"; open(mk_late, "wb").write(b"late partial")
R, out = run("--go", "--ruling", "lead 81345", "--manifest-sha256", PLAN)
check("RED (#2459 F1) a no-copy file added after the ruling changes the plan: PIN_MISMATCH, every no-copy file stays", "PIN_MISMATCH" in " ".join(R["skipped"]) and os.path.exists(FB.WIKI_PARTS + "/part1.bz2.bad") and os.path.exists(FB.TEXTCAPS_ZIP) and os.path.exists(mk_late))
os.remove(mk_late)
R, out = run("--go", "--ruling", "lead 81345", "--manifest-sha256", PLAN)
check("GREEN with --ruling the wiki .bad partial and the zip (21953 images extracted) are removed as ruled-no-copy", not os.path.exists(FB.WIKI_PARTS + "/part1.bz2.bad") and not os.path.exists(FB.TEXTCAPS_ZIP) and os.path.exists(FB.WIKI_PARTS + "/part2.bz2"))
check("the no-copy receipts are labelled ruled-no-copy-remove, never server-verified, and carry the plan pin", sorted(r["kind"] for r in rc() if r["kind"].startswith("ruled")) == ["ruled-no-copy-remove"] * 2 and all(r["plan_sha256"] == PLAN for r in rc() if r["kind"].startswith("ruled")))
src = open(SC + "/free_b.py", encoding="utf-8").read()
calls = {ast.unparse(n.func) for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Call)}
check("source: free_b.py calls neither os.remove nor shutil.rmtree; module level only defines", not (calls & {"os.remove", "shutil.rmtree", "os.unlink"}) and not [n for n in ast.parse(src).body if isinstance(n, (ast.For, ast.While)) or (isinstance(n, ast.If) and "__name__" not in ast.unparse(n.test))])
shutil.rmtree(T, ignore_errors=True)
print("ALL PASS" if ok else "FAILED"); sys.exit(0 if ok else 1)
