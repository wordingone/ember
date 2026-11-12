# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Red for scripts/pack_gates.py and its wiring in loops/tick.py (#2449 item 2, lead 82716 item 3 / 83284). python scripts/tests/pack_gates_red_test.py
Real degenerate_scan.py and heldout_check_pack.py run on tiny synthetic packs in a temp dir (HC_PACK_ROOT / HC_INDEX point the held-out check at a planted index); the REAL intake() and upload()
of loops/tick.py run against a temp lane (stubbed spawn, Hub, mail). Cases:
 a) clean pack: both gates PASS, two rows bound to the ledger sha, status pass
 b) a held-out sentence planted in one object: heldout row REFUSED, status refused, no document text in the row
 c) a period-2 run planted in a shard: degenerate row REFUSED (object sha named), the held-out gate is not run
 d) a gate that errors (exit 2) is never a pass; a stale row (ledger changed after the run) is pending
 e) intake(): pack without rows -> no intake.json, no NEW_PACKED, GATES_PENDING named, one pack_gates run spawned; refused rows -> no intake.json, GATE_REFUSED; PASS rows -> intake.json + NEW_PACKED
 f) upload(): text pack without rows -> not pushed (Hub never listed), pack_gates run spawned; refused -> blocked line; PASS -> the upload gets past the gate (Hub listed)
 g) mutants: status() that always says pass makes e) and f) FAIL (the assertions bite); a runner that treats exit 2 as pass makes d) FAIL
Needs numpy, zstandard, xxhash (as the lane). No network, no live lane files; writes only under a temp dir."""
import os, sys, json, glob, time, types, hashlib, tempfile, shutil, subprocess
import numpy as np
os.environ["HS_SAMP"] = "1"      # before common is imported: the planted index and the subprocess must hash the same sentences
LANE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, LANE)
import pack_gates as PG
from common import gram_hashes
import zstandard

TMP = tempfile.mkdtemp(prefix="pgates_red_").replace(chr(92), "/")      # forward slashes, as the lane ROOT
ok = True
rng = np.random.default_rng(20261112)
res = []


def chk(n, c):
    global ok
    ok = ok and bool(c); res.append((n, bool(c))); print(("PASS " if c else "FAIL ") + n)


def sha(t): return hashlib.sha256(t.encode()).hexdigest()
def text(n): return np.minimum(rng.zipf(1.3, n), 31999).astype(np.uint16) + np.uint16(1)
SENT = "the quick onyx falcon quietly arranged seventeen amber lanterns beside the frozen harbour wall before dawn"
CLEAN = ["a gentle reading of some ordinary prose about gardens and rain and the long road home through the hills",
         "another unrelated paragraph that talks about bread, salt, and the slow work of mending a wooden boat in winter"]


def make_pack(root, name, docs, period2=False):
    d = root + "/packed/" + name
    for sub in ("shards", "objects"): os.makedirs(d + "/" + sub, exist_ok=True)
    toks = text(20000)
    if period2: toks[3000:9000] = np.tile(np.array([111, 222], dtype=np.uint16), 3000)
    toks.astype("<u2").tofile(d + "/shards/v1-00000-000000000000.bin")
    objs = [("obj-%d" % i, 0) for i in range(2)]
    spans = [dict(sha256=sha("O1"), token_start=0, token_end=9000), dict(sha256=sha("O2"), token_start=9000, token_end=20000)]
    open(d + "/ledger.jsonl", "w").write(json.dumps(dict(index=0, n_tokens=20000, name="v1-00000-000000000000.bin", prev_row_sha256="0" * 64, spans=spans)) + "\n")
    with open(d + "/objects/o0.jsonl.zst", "wb") as fh:
        w = zstandard.ZstdCompressor().stream_writer(fh)
        for i, t in enumerate(docs): w.write((json.dumps(dict(id="%s:%d" % (name, i), text=t)) + "\n").encode())
        w.close()
    open(d + "/docs-index.jsonl.zst", "wb").write(b"x")
    open(d + "/receipt.json", "w").write(json.dumps(dict(dataset_id="ds-" + name, docs=len(docs), content_tokens=20000, shards=1, objects=[1, 2], tokenizer_sha256="t" * 64, mode="text")))
    open(d + "/source-manifest.jsonl", "w").write(json.dumps(dict(content_date_max="2020-01-01", modality="text")) + "\n")
    return d


HIDX = TMP + "/held.npy"
os.environ["HS_SAMP"] = "1"
np.save(HIDX, np.sort(np.array(gram_hashes(SENT + "."), dtype=np.uint64)))
assert len(gram_hashes(SENT + ".")) >= 1, "the planted sentence must give at least one hash"
ENV = dict(HC_INDEX=HIDX, HC_PACK_ROOT=TMP + "/packed", HS_SAMP="1")
OUT = TMP + "/gates"
PG.OUT = OUT


def real_run(name, pack_dir): return PG.run(name, pack_dir, out=OUT, env=ENV)


# a) clean
d = make_pack(TMP, "clean", CLEAN)
st, det = real_run("clean", d)
rows = [PG.read_row("clean", g, OUT) for g in PG.GATES]
chk("a) clean pack: PASS", st == "pass")
chk("a) clean pack: one row per gate, bound to the ledger sha, verdict pass", all(r and r["verdict"] == "pass" and r["ledger_sha256"] == PG._sha256f(d + "/ledger.jsonl") for r in rows))
# b) held-out sentence planted
d = make_pack(TMP, "planted", CLEAN + [SENT + ". " + CLEAN[0]])
st, det = real_run("planted", d); r = PG.read_row("planted", "heldout", OUT)
chk("b) planted held-out sentence: REFUSED by the held-out gate", st == "refused" and r and r["verdict"] == "refused" and "heldout" in det)
chk("b) the row carries counts only, never document text", r and "onyx" not in json.dumps(r) and "falcon" not in json.dumps(r))
# c) degenerate run planted
d = make_pack(TMP, "degen", CLEAN, period2=True)
st, det = real_run("degen", d); r = PG.read_row("degen", "degenerate", OUT)
chk("c) planted period-2 run: REFUSED by the degenerate gate", st == "refused" and r and r["verdict"] == "refused" and "object=" in r["summary"])
chk("c) the held-out gate is not run after a refusal", PG.read_row("degen", "heldout", OUT) is None)
# d) error / stale
d = make_pack(TMP, "errpack", CLEAN)
st, det = PG.run("errpack", d, out=OUT, runner=lambda cmd, e: (2, "cannot scan"))
chk("d) a gate that errors (exit 2) is never a pass: pending", st == "pending")
d = make_pack(TMP, "stalepack", CLEAN); real_run("stalepack", d)
chk("d) before the change: PASS", PG.status("stalepack", d, OUT)[0] == "pass")
open(d + "/ledger.jsonl", "a").write(json.dumps(dict(index=1, n_tokens=1, name="x", prev_row_sha256="0" * 64, spans=[])) + "\n")
chk("d) the ledger changed after the run: the rows are stale = pending", PG.status("stalepack", d, OUT)[0] == "pending")
chk("d) no ledger at all: pending (fail closed)", PG.status("nopack", TMP + "/nopack", OUT)[0] == "pending")

# ---- tick wiring
SRC = open(os.environ.get("TICK_SRC", LANE + "/loops/tick.py"), encoding="utf-8").read()
INTAKE_SRC = SRC[SRC.index("\ndef intake()"):SRC.index("\ndef upload()")]
UPLOAD_SRC = SRC[SRC.index("\ndef upload()"):SRC.index("\ndef census()")]


class Done(Exception):
    def __init__(self, s, n): self.status, self.note = s, n


def lane_ns(root, spawns):
    L = root + "/loops"; os.makedirs(L, exist_ok=True)
    def done(s, n): raise Done(s, n)
    return dict(os=os, sys=sys, json=json, time=time, glob=glob, hashlib=hashlib, ROOT=root, L=L, subprocess=None, mglob=lambda t: [], gate_ok=lambda *a: False,
                sha256f=lambda p: "0", alive=lambda pat: 0, spawn=lambda cmd, log: (spawns.append(cmd) or True), done=done, refresh_listing=lambda: "", MEDIA_DIRS=[])


def tick_intake(root, spawns):
    ns = lane_ns(root, spawns); exec(INTAKE_SRC, ns)
    try: ns["intake"]()
    except Done as e: return e.status, e.note


def tick_upload(root, spawns, listed):
    ns = lane_ns(root, spawns); bad = []
    loc = root + "/packed/pk"
    json.dump([dict(name="train-pk", repo="acct/x-private", path="text/pk", local=loc, approved_by="test")], open(root + "/loops/approved-uploads.json", "w"))
    class Api:
        def list_repo_tree(self, *a, **k): listed.append(1); raise RuntimeError("stop here: past the gate")
    mods = dict(upload_refuse=types.ModuleType("upload_refuse"), huggingface_hub=types.ModuleType("huggingface_hub"))
    mods["upload_refuse"].refused = lambda p: False; mods["huggingface_hub"].HfApi = Api
    old = {k: sys.modules.get(k) for k in mods}; sys.modules.update(mods)
    ns["sha256f"] = PG._sha256f
    try:
        exec(UPLOAD_SRC, ns)
        try: ns["upload"]()
        except Done as e: return e.status, e.note
    finally:
        for k, v in old.items():
            if v is None: sys.modules.pop(k, None)
            else: sys.modules[k] = v


def fresh_root(name):
    r = TMP + "/lane-" + name; os.makedirs(r + "/logs"); return r


def e_cases(tag):
    out = {}
    clear_rows()
    # no rows
    r = fresh_root("e0" + tag); make_pack(r, "pk", CLEAN); sp = []
    out["none"] = (tick_intake(r, sp), sp, os.path.exists(r + "/packed/pk/intake.json"))
    # refused rows
    clear_rows(); r = fresh_root("e1" + tag); d = make_pack(r, "pk", CLEAN, period2=True); sp = []; PG.run("pk", d, out=OUT, env=ENV)
    out["refused"] = (tick_intake(r, sp), sp, os.path.exists(r + "/packed/pk/intake.json"))
    # pass rows
    clear_rows(); r = fresh_root("e2" + tag); d = make_pack(r, "pk", CLEAN); sp = []; PG.run("pk", d, out=OUT, env=ENV)
    out["pass"] = (tick_intake(r, sp), sp, os.path.exists(r + "/packed/pk/intake.json"))
    return out


def clear_rows():
    for p in glob.glob(OUT + "/*-pk.json*"): os.remove(p)


def run_wiring(tag):
    clear_rows(); e = e_cases(tag)
    (dn, spn, intn), (dr, spr, intr), (dp, spp, intp) = e["none"], e["refused"], e["pass"]
    chk("e%s) no rows: no intake.json, not announced, GATES_PENDING named, one pack_gates run spawned" % tag, not intn and "NEW_PACKED" not in dn[1] and "GATES_PENDING" in dn[1] and len([s for s in spn if "pack_gates.py run pk" in s]) == 1)
    chk("e%s) refused rows: no intake.json, GATE_REFUSED named, nothing spawned" % tag, not intr and "GATE_REFUSED" in dr[1] and "NEW_PACKED" not in dr[1] and not [s for s in spr if "pack_gates" in s])
    chk("e%s) PASS rows: intake.json written and NEW_PACKED announced" % tag, intp and "NEW_PACKED pk" in dp[1])
    clear_rows(); res_ = {}
    for label, mk, run_first in (("none", dict(), False), ("refused", dict(period2=True), True), ("pass", dict(), True)):
        r = fresh_root("f" + label + tag); d = make_pack(r, "pk", CLEAN, **mk)
        open(d + "/intake.json", "w").write("{}")
        if run_first: PG.run("pk", d, out=OUT, env=ENV)
        sp = []; listed = []; res_[label] = (tick_upload(r, sp, listed), sp, listed)
        clear_rows()
    (dn, spn, ln), (dr, spr, lr), (dp, spp, lp) = res_["none"], res_["refused"], res_["pass"]
    chk("f%s) upload, no rows: Hub never listed (not pushed), pack_gates run spawned, named in the note" % tag, not ln and any("pack_gates.py run pk" in s for s in spn) and dn and "pack gates pending" in dn[1])
    chk("f%s) upload, refused: Hub never listed, named blocked/ESCALATE" % tag, not lr and dr and "pack gate" in dr[1] and "ESCALATE" in dr[1])
    chk("f%s) upload, PASS rows: gets past the gate (Hub listed)" % tag, bool(lp))


run_wiring("")
# g) mutants
real_status = PG.status
PG.status = lambda name, pack_dir, out=None: ("pass", "MUTANT")
n0 = len(res); ok0 = ok
try:
    clear_rows(); e = e_cases("m")
    mut_e = e["none"][2] is True       # the mutant announces a pack that has no rows
    chk("g) MUTANT status() always pass: the intake assertion can FAIL (pack without rows is announced)", mut_e)
finally: PG.status = real_status
real_verdict = PG.verdict_of
PG.verdict_of = lambda rc: "pass" if rc in (0, 2) else "refused"
try:
    d = make_pack(TMP, "errmut", CLEAN); st, _ = PG.run("errmut", d, out=OUT, runner=lambda cmd, e: (2, "cannot scan"))
    chk("g) MUTANT exit 2 treated as pass: the error assertion can FAIL", st == "pass")
finally: PG.verdict_of = real_verdict
bad = [n for n, c in res if not c]
shutil.rmtree(TMP, ignore_errors=True)
print("FAILCOUNT", len(bad), "of", len(res)); print("ALL PASS" if not bad else "FAILED"); sys.exit(1 if bad else 0)
