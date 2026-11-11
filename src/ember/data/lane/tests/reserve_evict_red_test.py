# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Red test for reserve_evict + the declared protected set (issue 2450). Every claim is EXECUTED: the live declaration is read for the marker cases, and the main() cases run the real executor against a sandbox
(sandbox live dir, sandbox declaration, sandbox receipt, a stub HfApi) so no real file and no real HF repo is touched. os.remove is spied: a refused run must never reach it.
Run: python scripts/tests/reserve_evict_red_test.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from lane_config import LANE_ROOT, M_ROOT
import sys, os, json, tempfile, hashlib, shutil, types
pass
import protected_set as PS
import evict_ckpt_list as EK
import reserve_evict as R
ok = True
def check(l, c):
    global ok; ok &= bool(c); print("PASS" if c else "FAIL", l)
L = (M_ROOT + "/ember-live-receipts/")
LIVE_PATH = PS.PATH
D = PS.load()
def path_under(marker):
    return L + marker.rstrip("/") + "/m/trained-child/objects/a.pt" if marker.endswith("/") else L + marker

# 1. every declared marker (shared + reserve) is refused, whatever the hour: the test follows the file
check("declared set is non-empty (shared %d, reserve %d)" % (len(D["markers"]), len(D["reserve_markers"])), len(D["markers"]) > 0)      # reserve_markers may legally be [] (issue 2450 N4)
def cov(fn_result, path, markers):
    """fn_result must be SOME declared marker contained in the path; which of two nested markers answers first is order-dependent and is not pinned (issue 2450 N4)."""
    p = path.replace("\\", "/"); p = p if p.endswith("/") else p + "/"
    return fn_result is not None and fn_result in markers and fn_result in p
for m in D["markers"] + D["reserve_markers"]:
    check("RED declared marker refused: " + m[-48:], R.refuse_reason(path_under(m)) == "under a KEEP path")
for m in D["markers"]:
    check("RED shared marker also refused by evict_ckpt_list: " + m[-48:], cov(EK.kept(path_under(m)), path_under(m), D["markers"]) and EK.refuse_reason(path_under(m)) is not None)
check("RED a probe optimizer-state under a declared hour dir is refused", R.refuse_reason(L + D["markers"][-1].rstrip("/") + "/m/trained-child/optimizer-state.pt") == "under a KEEP path")
check("RED catalog-train-cache refused", R.refuse_reason((M_ROOT + "/ember-data/catalog-train-cache/2c557e7f/2720f6d1/x.pt")) == ("outside " + M_ROOT + "/ember-live-receipts"))
check("RED selected head json refused", R.refuse_reason(L + "selected-continuation-head.json") == "under a KEEP path")
check("GREEN old ancestor object allowed", R.refuse_reason(L + "cia-hour-a1-five-attn-stage-d4-20260927T080708Z/measurement-d6/trained-child/objects/a.pt") is None)

T = tempfile.mkdtemp(dir=(LANE_ROOT + "/scratch")).replace("\\", "/")
real_remove = os.remove; calls = []
def spy(p, *a, **k):
    calls.append(str(p).replace("\\", "/")); return real_remove(p, *a, **k)
def write_doc(path, doc):
    json.dump(doc, open(path, "w", encoding="utf-8"))
BASE_DOC = {"declared_by": "red test", "declared_at": "2099-01-01T00:00:00Z", "markers": [{"marker": "cia-hour-keep-aa/"}], "reserve_markers": [{"marker": "cia-probe-keep-bb/"}]}

# 2. the declaration is the ONLY source: a marker added to the file protects at once with no code edit; a marker removed from it unprotects (no hidden copy in the code)
decl = T + "/protected-set.json"
newp = L + "cia-hour-zz-new-hour-20991231T000000Z/m/trained-child/objects/a.pt"
doc = json.load(open(LIVE_PATH, encoding="utf-8")); doc["reserve_markers"].append({"marker": "cia-hour-zz-new-hour-20991231T000000Z/"})
write_doc(decl, doc)
check("GREEN before the declaration the new hour is not protected", R.refuse_reason(newp) is None)
try:
    PS.PATH = decl
    check("RED a newly declared marker is refused with no code change", R.refuse_reason(newp) == "under a KEEP path")
    check("RED the shared deleters read the same file on every call: EK.kept() follows the declaration (shared markers only; this marker is a reserve marker)", EK.kept(newp) is None and EK.kept(newp, PS.load()["markers"] + PS.load()["reserve_markers"]) is not None)
finally:
    PS.PATH = LIVE_PATH
check("GREEN back on the live declaration the new hour is not protected", R.refuse_reason(newp) is None)
write_doc(T + "/only-other.json", dict(BASE_DOC, markers=[{"marker": "unrelated-zz-marker/"}], reserve_markers=[]))
try:
    PS.PATH = T + "/only-other.json"
    check("RED a marker removed from the declaration no longer protects (the old hours are not hard-coded)", R.refuse_reason(path_under(D["markers"][0])) is None)
finally:
    PS.PATH = LIVE_PATH

# 3. fail closed: every malformed declaration raises ProtectedSetError (the deleter removes nothing); the guards are executed, not grepped
BAD = [
    ("missing file", None),
    ("empty markers list", dict(BASE_DOC, markers=[])),
    ("malformed JSON", "{not json"),
    ("non-object JSON", "[1,2]"),
    ("bare '/' marker", dict(BASE_DOC, markers=[{"marker": "/"}])),
    ("marker shorter than 8 chars", dict(BASE_DOC, markers=[{"marker": "short"}])),
    ("bare drive marker 'B:/'", dict(BASE_DOC, markers=[{"marker": "B:/"}])),
    ("live-receipts root marker", dict(BASE_DOC, markers=[{"marker": (M_ROOT + "/ember-live-receipts/")}])),
    ("lane scripts root marker", dict(BASE_DOC, markers=[{"marker": os.path.dirname(os.path.abspath(R.__file__)).replace("\\", "/")}])),
    ("lane root marker", dict(BASE_DOC, markers=[{"marker": os.path.dirname(os.path.dirname(os.path.abspath(R.__file__))).replace("\\", "/")}])),
    ("non-string marker", dict(BASE_DOC, markers=[{"marker": 12345678}])),
    ("non-list markers", dict(BASE_DOC, markers="cia-hour-keep-aa/")),
    ("padded marker (leading/trailing space)", dict(BASE_DOC, markers=[{"marker": " cia-hour-keep-aa/ "}])),
    ("bad reserve_markers entry", dict(BASE_DOC, reserve_markers=[{"marker": "B:/"}])),
    ("non-list reserve_markers", dict(BASE_DOC, reserve_markers="x")),
    ("absent markers key", {k: v for k, v in BASE_DOC.items() if k != "markers"}),
    ("absent reserve_markers key", {k: v for k, v in BASE_DOC.items() if k != "reserve_markers"}),
]
for i, (label, content) in enumerate(BAD):
    pth = "%s/bad%d.json" % (T, i)
    if content is not None: open(pth, "w", encoding="utf-8").write(content if isinstance(content, str) else json.dumps(content))
    try:
        PS.PATH = pth
        try: PS.load(); a = False
        except PS.ProtectedSetError: a = True
        try: R.refuse_reason(L + "cia-hour-x/m/trained-child/objects/a.pt"); b = False
        except PS.ProtectedSetError: b = True
        try: EK.kept(L + "cia-hour-x/m/trained-child/objects/a.pt"); c = False
        except PS.ProtectedSetError: c = True
    finally:
        PS.PATH = LIVE_PATH
    check("RED fail closed (protected_set, reserve_evict, evict_ckpt_list): " + label, a and b and c)
write_doc(T + "/empty-reserve.json", dict(BASE_DOC, reserve_markers=[]))
check("GREEN an explicit empty reserve_markers list is allowed", len(PS.load(T + "/empty-reserve.json")["reserve_markers"]) == 0)
os.environ["PROTECTED_SET_FILE"] = T + "/only-other.json"
try:
    check("RED no environment override: PROTECTED_SET_FILE does not change what is read", PS.load()["path"] == LIVE_PATH and PS.load()["sha256"] == D["sha256"])
finally:
    del os.environ["PROTECTED_SET_FILE"]
EK_fail = os.path.join(T, "ek_fail.py")
open(EK_fail, "w").write(("import sys; sys.path.insert(0, '" + LANE_ROOT + "/scripts')\nimport protected_set as P; P.PATH = sys.argv[1]\ntry:\n    import evict_ckpt_list\n    print('IMPORTED')\nexcept P.ProtectedSetError:\n    print('FAILCLOSED')\n"))
import subprocess
r = subprocess.run([sys.executable, EK_fail, T + "/bad2.json"], capture_output=True, text=True)
check("RED importing evict_ckpt_list on a bad declaration fails closed (no import-time snapshot of nothing)", "FAILCLOSED" in r.stdout)

# 4. manifest and acknowledgement gates
m = T + "/m.tsv"; open(m, "w").write("status\tgib\tsha256\thf\tpath\nCANDIDATE\t1\tab\tr:p\tB:/x.pt\nPROTECTED\t1\tcd\t\tB:/y.pt\n")
try: R.load(m, "0" * 64); check("RED wrong manifest sha refused", False)
except R.Refused: check("RED wrong manifest sha refused", True)
check("GREEN pinned manifest loads only CANDIDATE rows", [r["path"] for r in R.load(m, hashlib.sha256(open(m, "rb").read()).hexdigest())] == ["B:/x.pt"])
sys.argv = ["x", m]
try: R.main(); check("RED missing --ack refused", False)
except R.Refused: check("RED missing --ack refused", True)
rd = R.reserve_decl(T + "/nope.json"); check("missing reserve declaration is recorded as missing, not invented", rd.get("missing") is True)
for _label, _txt in (("{}", "{}"), ("null", "null"), ("[]", "[]"), ("a number", "7"), ("malformed JSON", "{not json")):
    open(T + "/res-bad.json", "w").write(_txt); rd = R.reserve_decl(T + "/res-bad.json")
    check("RED reserve declaration that names no reserve is recorded as missing (issue 2450 N5): " + _label, rd.get("missing") is True and "declaration" not in rd)
RF0 = R.RESERVE_FILE
import subprocess as _sp
_env = dict(os.environ, RESERVE_FILE=T + "/elsewhere.json")
_out = _sp.run([sys.executable, "-c", ("import sys; sys.path.insert(0, '" + LANE_ROOT + "/scripts'); import reserve_evict as R; print(R.RESERVE_FILE)")], capture_output=True, text=True, env=_env).stdout.strip().replace("\\", "/")
check("RED no environment override: RESERVE_FILE in the environment does not change the declaration path read (issue 2450 N5)", _out == RF0.replace("\\", "/") and "elsewhere" not in _out)
# N6: _keep normalises backslashes like refuse_reason does
_psx = dict(markers=("cia-hour-keep-aa/",), reserve_markers=("cia-probe-keep-bb/",))
check("RED _keep() catches a raw backslash path under a shared marker (issue 2450 N6)", R._keep((M_ROOT + "\\ember-live-receipts\\cia-hour-keep-aa\\m\\trained-child\\objects\\a.pt"), _psx) == "cia-hour-keep-aa/")
check("RED _keep() catches a raw backslash path under a reserve marker (issue 2450 N6)", R._keep((M_ROOT + "\\ember-live-receipts\\cia-probe-keep-bb\\m\\a.pt"), _psx) == "cia-probe-keep-bb/")
check("GREEN _keep() with a backslash path under no marker is None", R._keep((M_ROOT + "\\ember-live-receipts\\cia-hour-old-cc\\m\\a.pt"), _psx) is None)
open(T + "/res.json", "w").write('{"chain_start_floor_gib": 305}'); rd = R.reserve_decl(T + "/res.json")
check("reserve declaration is recorded with its sha256", rd["declaration"]["chain_start_floor_gib"] == 305 and rd["sha256"] == hashlib.sha256(open(T + "/res.json", "rb").read()).hexdigest())

# 5. the executor, run for real against a sandbox: receipts, refusals and the re-declaration window
class Srv:
    sha = {}; size = {}; raise_on = set(); on_call = None
class Api:
    def __init__(self, *a, **k): pass
    def list_repo_tree(self, *a, **k): return []
    def get_paths_info(self, repo, paths, expand=True, repo_type="dataset"):
        hp = paths[0]
        if Srv.on_call: Srv.on_call(hp)
        if hp in Srv.raise_on: raise RuntimeError("stub HF failure for " + hp)
        return [types.SimpleNamespace(lfs={"sha256": Srv.sha[hp]}, size=Srv.size[hp])]
fake = types.ModuleType("huggingface_hub"); fake.HfApi = Api
def sandbox(name, nfiles=2, doc=None, reserve=True, dry=False, workers=1):
    """-> (rows, files, paths): a sandbox live dir with nfiles .pt files, a manifest, the stub server, the declaration and the receipt paths wired into the executor."""
    S = "%s/%s" % (T, name); os.makedirs(S + "/live/cia-hour-old-cc/m/trained-child/objects"); doc = doc if doc is not None else BASE_DOC
    pd = S + "/protected-set.json"; write_doc(pd, doc)
    files = []; Srv.sha = {}; Srv.size = {}; Srv.raise_on = set(); Srv.on_call = None; lines = ["status\tgib\tsha256\thf\tpath"]
    for i in range(nfiles):
        p = "%s/live/cia-hour-old-cc/m/trained-child/objects/f%d.pt" % (S, i); data = ("payload-%s-%d" % (name, i)).encode() * 50
        open(p, "wb").write(data); s = hashlib.sha256(data).hexdigest(); hp = "checkpoints/f%d.pt" % i
        Srv.sha[hp] = s; Srv.size[hp] = len(data); files.append(p); lines.append("CANDIDATE\t0.00001\t%s\trepo/x:%s\t%s" % (s, hp, p))
    man = S + "/m.tsv"; open(man, "w").write("\n".join(lines) + "\n")
    if reserve: open(S + "/reserve.json", "w").write('{"chain_start_floor_gib": 316}')
    R.BASE = S + "/live/"; R.RC = S + "/rc.jsonl"; R.RESERVE_FILE = S + "/reserve.json"; PS.PATH = pd
    sys.argv = ["x", man, "--manifest-sha256", hashlib.sha256(open(man, "rb").read()).hexdigest(), "--ack", "1", "--workers", str(workers)] + (["--dry"] if dry else [])
    return S, files, pd
def run():
    """-> (exception or None, number of os.remove calls, receipt rows, summary dict or None)"""
    del calls[:]; os.remove = spy; prev = sys.modules.get("huggingface_hub"); sys.modules["huggingface_hub"] = fake; exc = None
    try: R.main()
    except BaseException as e: exc = e
    finally:
        os.remove = real_remove; PS.PATH = LIVE_PATH; R.BASE = (M_ROOT + "/ember-live-receipts/")
        if prev is None: sys.modules.pop("huggingface_hub", None)
        else: sys.modules["huggingface_hub"] = prev
    rows = [json.loads(l) for l in open(R.RC, encoding="utf-8")] if os.path.exists(R.RC) else []
    sp = os.path.join(os.path.dirname(R.RC), "reserve-evict.summary.json"); summ = json.load(open(sp)) if os.path.exists(sp) else None
    return exc, len(calls), rows, summ

# 5a. a bad declaration reaches no os.remove and writes no receipt row: the real main() is run
S, files, pd = sandbox("a-bad-decl", doc=dict(BASE_DOC, markers=[{"marker": "B:/"}]))
exc, nrem, rows, summ = run()
check("RED main() on a too-broad declaration raises ProtectedSetError", isinstance(exc, PS.ProtectedSetError))
check("RED ... os.remove is never called, every file is still there", nrem == 0 and all(os.path.exists(f) for f in files))
check("RED ... and no receipt row or summary is written", rows == [] and summ is None and not os.path.exists(R.RC))
S, files, pd = sandbox("a-missing-decl"); os.remove(pd)
exc, nrem, rows, summ = run()
check("RED main() with the declaration deleted raises ProtectedSetError and removes nothing", isinstance(exc, PS.ProtectedSetError) and nrem == 0 and rows == [] and all(os.path.exists(f) for f in files))

# 5b. a missing reserve declaration refuses a non-dry run; a dry run still works and writes no receipt row
S, files, pd = sandbox("b-no-reserve", reserve=False)
exc, nrem, rows, summ = run()
check("RED non-dry main() without loops/reserve.json raises Refused before any I/O", isinstance(exc, R.Refused) and "reserve declaration" in str(exc))
check("RED ... nothing removed, no receipt row", nrem == 0 and rows == [] and all(os.path.exists(f) for f in files))
S, files, pd = sandbox("b-no-reserve-dry", reserve=False, dry=True)
exc, nrem, rows, summ = run()
check("GREEN a --dry run without the reserve declaration completes, removes nothing and writes no run rows", exc is None and nrem == 0 and rows == [] and all(os.path.exists(f) for f in files) and summ and summ["dry"] and summ["removed"] == 2)

S, files, pd = sandbox("b-empty-reserve"); open(S + "/reserve.json", "w").write("{}")
exc, nrem, rows, summ = run()
check("RED non-dry main() with loops/reserve.json = {} raises Refused before any I/O (issue 2450 N5)", isinstance(exc, R.Refused) and "reserve declaration" in str(exc) and nrem == 0 and rows == [] and all(os.path.exists(f) for f in files))

# 5c. a normal run: run-start before the first removal, a per-file row before each os.remove, run-end last
S, files, pd = sandbox("c-normal")
psha = hashlib.sha256(open(pd, "rb").read()).hexdigest(); rsha = hashlib.sha256(open(S + "/reserve.json", "rb").read()).hexdigest()
exc, nrem, rows, summ = run()
kinds = [r.get("kind", "file") for r in rows]
check("GREEN normal run completes: both files removed, receipt = run-start, 2 file rows, run-end", exc is None and nrem == 2 and not any(os.path.exists(f) for f in files) and kinds == ["run-start", "file", "file", "run-end"])
if kinds == ["run-start", "file", "file", "run-end"]:
    rs, f1, f2, re_ = rows
    check("run-start row holds the reserve declaration (content + sha256) and the protected set (path, sha256, declared_by)", rs["reserve_declaration"]["sha256"] == rsha and rs["reserve_declaration"]["declaration"]["chain_start_floor_gib"] == 316
          and rs["protected_set"]["sha256"] == psha and rs["protected_set"]["path"] == pd and rs["protected_set"]["declared_by"] == "red test" and rs["rows"] == 2 and rs["free_before_bytes"] > 0)
    check("every file row carries the run_id and the protected-set sha256 + path it was admitted under", f1["run_id"] == f2["run_id"] == rs["run_id"] == re_["run_id"] and f1["protected_set_sha256"] == f2["protected_set_sha256"] == psha and f1["protected_set_path"] == pd)
    check("run-end row: removed 2, physical bytes == the file rows, free space after each eviction, error None", re_["removed"] == 2 and re_["skipped"] == 0 and re_["physical_bytes_by_receipts"] == f1["size"] + f2["size"]
          and len(re_["free_after_each"]) == 2 and re_["error"] is None and re_["free_after_bytes"] > 0)
    check("timestamps are in order: run-start <= file rows <= run-end", rs["ts"] <= f1["ts"] <= f2["ts"] <= re_["ts"])
check("summary file is written next to the receipt, not in the live tree", summ and summ["removed"] == 2 and os.path.exists(os.path.join(S, "reserve-evict.summary.json")))

# 5d. a worker raising mid-run still leaves the run-start row and a run-end row with the error and the files removed so far
S, files, pd = sandbox("d-raise")
Srv.raise_on = {"checkpoints/f1.pt"}
exc, nrem, rows, summ = run()
kinds = [r.get("kind", "file") for r in rows]
check("RED main() re-raises the worker failure", isinstance(exc, RuntimeError) and "stub HF failure" in str(exc))
check("RED the first file was removed, the second (whose server read raised) still exists", nrem == 1 and not os.path.exists(files[0]) and os.path.exists(files[1]))
check("RED receipt = run-start, 1 file row, run-end", kinds == ["run-start", "file", "run-end"])
if kinds == ["run-start", "file", "run-end"]:
    check("RED run-end records the error, removed 1 and the free-space series, written in a finally", rows[2]["error"] and "RuntimeError" in rows[2]["error"] and rows[2]["removed"] == 1 and len(rows[2]["free_after_each"]) == 1)
check("RED the summary file also records the error", summ and summ["error"] and "RuntimeError" in summ["error"])

# 5e. a marker declared DURING the run (between the server read and the remove) is honoured and recorded
S, files, pd = sandbox("e-redeclared")
def redeclare(hp):
    if hp == "checkpoints/f0.pt": write_doc(pd, dict(BASE_DOC, declared_by="red test redeclared", markers=BASE_DOC["markers"] + [{"marker": "cia-hour-old-cc/"}]))
Srv.on_call = redeclare
exc, nrem, rows, summ = run()
check("RED a marker declared after the start covers the files: nothing is removed", exc is None and nrem == 0 and all(os.path.exists(f) for f in files))
sk = {os.path.basename(s[0]): s[1] for s in (summ or {}).get("skipped", [])}
check("RED ... the file in the window is skipped as 'under a KEEP path (re-declared during the run)', the next one is refused up front", summ and summ["removed"] == 0 and "re-declared during the run" in sk.get("f0.pt", "") and sk.get("f1.pt") == "under a KEEP path")
check("RED ... the receipt holds only run-start and run-end (no per-file row for a file that was not removed)", [r.get("kind", "file") for r in rows] == ["run-start", "run-end"] and rows[1]["removed"] == 0 and rows[1]["skipped"] == 2)

# 5f. the declaration changing BETWEEN two files: the second file's row records the NEW set's sha256
S, files, pd = sandbox("f-between")
sha_before = hashlib.sha256(open(pd, "rb").read()).hexdigest()
def change(hp):
    if hp == "checkpoints/f1.pt": write_doc(pd, dict(BASE_DOC, declared_by="red test v2", markers=BASE_DOC["markers"] + [{"marker": "cia-hour-unrelated-zz/"}]))
Srv.on_call = change
exc, nrem, rows, summ = run()
fr = [r for r in rows if "kind" not in r]
sha_after = hashlib.sha256(open(pd, "rb").read()).hexdigest()
check("GREEN both files removed; the first row records the sha256 of the set read before it, the second the NEW set's", exc is None and len(fr) == 2 and fr[0]["protected_set_sha256"] == sha_before and fr[1]["protected_set_sha256"] == sha_after and sha_before != sha_after)
check("GREEN the run-start row recorded the set as it was at the start", rows[0]["protected_set"]["sha256"] == sha_before)

# 5g. the declared KEEP at the start still refuses before any I/O on the file
S, files, pd = sandbox("g-kept-at-start", doc=dict(BASE_DOC, markers=BASE_DOC["markers"] + [{"marker": "cia-hour-old-cc/"}]))
exc, nrem, rows, summ = run()
check("RED files under a marker declared before the run are skipped, not removed", exc is None and nrem == 0 and summ and len(summ["skipped"]) == 2 and all("KEEP" in s[1] for s in summ["skipped"]) and all(os.path.exists(f) for f in files))
shutil.rmtree(T, ignore_errors=True)
print("ALL PASS" if ok else "FAILED"); sys.exit(0 if ok else 1)
