# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Reds for evict_ckpt_list.py guards. Run: python scripts/tests/evict_ckpt_red_test.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from lane_config import LANE_ROOT, M_ROOT
import sys, os, tempfile, shutil
pass
import evict_ckpt_list as E
ok = True
def check(l, c):
    global ok
    ok &= bool(c); print("PASS" if c else "FAIL", l)
R = (M_ROOT + "/ember-live-receipts/")
import protected_set as PS
D = PS.load()      # the hour paths below come FROM loops/protected-set.json: a re-declaration can never leave this test pinned to old hours (issue 2450)
def cov(path, markers=None):
    """kept(path) must be SOME declared marker that is contained in the path; which one (first match) is order-dependent, so the test does not pin it (issue 2450 N4)."""
    k = E.kept(path); p = path.replace("\\", "/"); p = p if p.endswith("/") else p + "/"
    return k is not None and k in (D["markers"] if markers is None else markers) and k in p
def under(marker, tail="/m/trained-child/objects/ab.pt"):
    return R + marker.rstrip("/") + tail if marker.endswith("/") else R + marker
check("declared shared set is non-empty (%d markers)" % len(D["markers"]), len(D["markers"]) > 0)
for _m in D["markers"]:
    check("RED shared marker object refused: " + _m[-48:], E.refuse_reason(under(_m)) and cov(under(_m)))
    check("RED shared marker: optimizer / replay state under it is KEEP: " + _m[-48:], cov(under(_m, "/m/trained-child/optimizer-state.pt")) and cov(under(_m, "/m/trained-child/replay-state.pt")))
    check("RED kept() covers a bare directory path under the marker (no trailing slash): " + _m[-48:], cov(under(_m, "/measurement-x/trained-child")))
_m0 = D["markers"][0]

# issue 2450 N4: a legal declaration with a nested pair, broad marker first: kept() answers with a declared marker that covers the path (the first one); the old "== the marker under test" shape fails on it
T0 = tempfile.mkdtemp(dir=(LANE_ROOT + "/scratch")).replace("\\", "/")
try:
    import json as _j
    _nest = ["cia-hour-nest-aa/", "cia-hour-nest-aa/m/trained-child/"]
    open(T0 + "/nest.json", "w").write(_j.dumps({"markers": [{"marker": m} for m in _nest], "reserve_markers": []}))
    _p0 = PS.PATH
    try:
        PS.PATH = T0 + "/nest.json"
        _pn = R + "cia-hour-nest-aa/m/trained-child/objects/ab.pt"
        check("GREEN nested pair declared broad-first: kept() names a declared marker that covers the path", cov(_pn, _nest) and E.kept(_pn) == _nest[0] and E.refuse_reason(_pn))
        check("GREEN ... a path under neither is not kept", E.kept(R + "cia-hour-other-zz/m/trained-child/objects/ab.pt") is None)
    finally:
        PS.PATH = _p0
finally:
    shutil.rmtree(T0, ignore_errors=True)
check("RED manifest / receipt (not objects/*.pt) under a marker refused", E.refuse_reason(under(_m0, "/measurement-9/trained-child/checkpoint-manifest.json")))
check("GREEN a hour dir that is not declared is not a KEEP node (an old ancestor)", E.refuse_reason(R + "cia-hour-a1-five-attn-stage-d4-20260927T080708Z/measurement-d6/trained-child/objects/ab.pt") is None and not E.kept(R + "cia-hour-a1-five-attn-stage-d4-20260927T080708Z/measurement-d6/trained-child"))
check("GREEN an undeclared marker-lookalike (same hour name, one character off) is not a KEEP node", not E.kept(under(_m0.rstrip("/") + "0/")))
_S = (LANE_ROOT + "/scripts/")
for _f in ("evict_ckpt_list.py", "reserve_manifest.py", "reserve_evict.py", "ckpt_backup.py", "ckpt_lineage_delete.py"):
    _t = open(_S + _f, encoding="utf-8").read()
    check("every checkpoint-deleting script consults the KEEP set: " + _f, "KEEP_MARKERS" in _t or ".kept(" in _t or '"evict_ckpt_list").kept(' in _t or "_keep(" in _t)      # the declared set (loops/protected-set.json) via evict_ckpt_list.kept()/KEEP_MARKERS; the behaviour is executed in reserve_evict_red_test.py and below
T0 = tempfile.mkdtemp(dir=(LANE_ROOT + "/scratch")).replace("\\", "/")
try:
    import json as _j, subprocess
    open(T0 + "/bad.json", "w").write(_j.dumps({"markers": [{"marker": "B:/"}], "reserve_markers": []}))
    _p = PS.PATH
    try:
        PS.PATH = T0 + "/bad.json"
        try: E.kept(R + "cia-hour-x/m/trained-child/objects/ab.pt"); _a = False
        except PS.ProtectedSetError: _a = True
        try: E.refuse_reason(R + "cia-hour-x/m/trained-child/objects/ab.pt"); _b = False
        except PS.ProtectedSetError: _b = True
    finally:
        PS.PATH = _p
    check("RED E.kept() and E.refuse_reason() fail closed (ProtectedSetError) on a too-broad declaration", _a and _b)
    open(T0 + "/imp.py", "w").write(("import sys; sys.path.insert(0, '" + LANE_ROOT + "/scripts')\nimport protected_set as P; P.PATH = sys.argv[1]\ntry:\n    import evict_ckpt_list\n    print('IMPORTED')\nexcept P.ProtectedSetError:\n    print('FAILCLOSED')\n"))
    check("RED importing evict_ckpt_list on a bad declaration fails closed (subprocess)", "FAILCLOSED" in subprocess.run([sys.executable, T0 + "/imp.py", T0 + "/bad.json"], capture_output=True, text=True).stdout)
    open(T0 + "/ok.json", "w").write(_j.dumps({"markers": [{"marker": "cia-hour-only-here/"}], "reserve_markers": []}))
    try:
        PS.PATH = T0 + "/ok.json"
        _in = E.kept(R + "cia-hour-only-here/m/trained-child/objects/ab.pt"); _out = E.kept(under(D["markers"][0]))
    finally:
        PS.PATH = _p
    check("RED kept() re-reads the declaration on every call: a marker declared now protects, a marker removed no longer does", _in == "cia-hour-only-here/" and _out is None)
finally:
    shutil.rmtree(T0, ignore_errors=True)
T = tempfile.mkdtemp(dir=(LANE_ROOT + "/scratch"))
try:
    open(T + "/l.tsv", "w").write("0\t5\tB:/x/trained-child/objects/ab.pt\n")
    try: E.load_list(T + "/l.tsv", "0" * 64); check("RED list with the wrong sha256 refused", False)
    except E.EvictRefused: check("RED list with the wrong sha256 refused", True)
finally:
    shutil.rmtree(T, ignore_errors=True)
rows = E.load_list(); check("GREEN pinned list loads (910 rows)", len(rows) == 910)
check("GREEN every row of the (spent) pinned list is either evictable or under a KEEP node", all(E.refuse_reason(p) is None or E.kept(p) for _, _, p in rows))
src = open((LANE_ROOT + "/scripts/evict_ckpt_list.py"), encoding="utf-8").read()
check("receipt row is written before os.remove", src.index("f.write(json.dumps(dict(st_nlink=nlink") < src.index("os.remove(p)"))

T2 = tempfile.mkdtemp(dir=(LANE_ROOT + "/scratch"))
try:
    a = T2 + "/a.bin"; b = T2 + "/b.bin"; c = T2 + "/c.bin"; d = T2 + "/d_outside.bin"
    open(a, "wb").write(b"x" * 100); open(c, "wb").write(b"y" * 50)
    os.link(a, b); os.link(c, d)           # inode A: links a,b ; inode C: links c,d
    ph, part = E.link_plan([a, b])
    check("GREEN inode with every link in the list counts once", ph == 100 and part == [])
    ph, part = E.link_plan([a, b, c])
    check("RED a link outside the list is named and the inode counts 0", ph == 100 and len(part) == 1 and E._norm(d) in part[0][1])
    open(T2 + "/solo.bin", "wb").write(b"z" * 7); ph, part = E.link_plan([T2 + "/solo.bin"])
    check("GREEN nlink==1 file counts its size", ph == 7 and part == [])
finally:
    shutil.rmtree(T2, ignore_errors=True)
import json
T3 = tempfile.mkdtemp(dir=(LANE_ROOT + "/scratch"))
try:
    meas = T3 + "/cia-hour-x/measurement-1"; ch = meas + "/trained-child"; os.makedirs(ch + "/objects")
    A, B = "a" * 64, "b" * 64
    json.dump(dict(core=dict(sha256=A, bytes=3), optimizer=dict(sha256="c" * 64, bytes=5), replay=dict(sha256="d" * 64, bytes=2)), open(ch + "/checkpoint-manifest.json", "w"))
    json.dump(dict(experts=[dict(expert_id=0, sha256=B, bytes=4)]), open(ch + "/expert-index-x.json", "w"))
    for f in ("objects/" + A + ".pt", "objects/" + B + ".pt", "optimizer-state.pt", "replay-state.pt"): open(ch + "/" + f, "wb").write(b"x")
    open(meas + "/hour-result.json", "w").write("{}")
    none, onlyA = (lambda s, b: False), (lambda s, b: s == A and b == 3)
    check("GREEN scored child with every item local: nothing removed -> no gap (lead 82370)", E.child_gaps(ch, [], none) == [])
    check("RED removing the core object with no HF copy leaves a gap", [g[0] for g in E.child_gaps(ch, [ch + "/objects/" + A + ".pt"], none)] == ["core"])
    check("GREEN removing the core object is fine once a server-verified copy exists (sha AND size)", E.child_gaps(ch, [ch + "/objects/" + A + ".pt"], onlyA) == [])
    check("RED a server copy with the wrong size does not count", E.child_gaps(ch, [ch + "/objects/" + A + ".pt"], lambda s, b: s == A and b == 99) != [])
    check("RED optimizer-state.pt (the only copy) is never removable without an HF copy", [g[0] for g in E.child_gaps(ch, [ch + "/optimizer-state.pt"], none)] == ["optimizer-state.pt"])
    check("RED guard_children names the child with a gap", list(E.guard_children([ch + "/objects/" + B + ".pt"], none)) == [E.child_of(ch + "/x")])
    os.remove(ch + "/replay-state.pt")
    check("RED an item already gone locally and not on HF is reported (the H41 shape)", [g[0] for g in E.child_gaps(ch, [], none)] == ["replay-state.pt"])
    os.remove(meas + "/hour-result.json")
    check("GREEN a dir without hour-result.json is not a scored child: rule not applicable", E.child_gaps(ch, [ch + "/objects/" + A + ".pt"], none) == [])
finally:
    shutil.rmtree(T3, ignore_errors=True)
# issue 2450 N3: the per-file path of evict_ckpt_list.main() EXECUTED against a sandbox (stub HfApi, sandbox declaration, receipt and list; os.remove spied): it re-reads the declaration before each remove,
# skips a file that became KEEP, and records the protected-set sha256 + path in each row
import types, hashlib, json as _J
real_remove = os.remove; calls = []
def _spy(p, *a, **k): calls.append(str(p).replace("\\", "/")); return real_remove(p, *a, **k)
class _Srv: on_call = None; sha = {}; size = {}
class RepoFile:
    def __init__(self, path, sha, size): self.path = path; self.lfs = {"sha256": sha}; self.size = size
class _Api:
    def __init__(self, *a, **k): pass
    def list_repo_tree(self, *a, **k): return [RepoFile("checkpoints/" + s + ".pt", s, _Srv.size[s]) for s in _Srv.sha.values()]
    def get_paths_info(self, repo, paths, expand=True, repo_type="dataset"):
        s = os.path.basename(paths[0])[:-3]
        if _Srv.on_call: _Srv.on_call(s)
        return [types.SimpleNamespace(lfs={"sha256": s}, size=_Srv.size[s])]
_fake = types.ModuleType("huggingface_hub"); _fake.HfApi = _Api
BASE_DOC = {"declared_by": "red test", "declared_at": "2099-01-01T00:00:00Z", "markers": [{"marker": "cia-hour-keep-aa/"}], "reserve_markers": []}
def _write(path, doc): _J.dump(doc, open(path, "w", encoding="utf-8"))
SANDBOXES = []
def sandbox_main(name, n=2):
    S = tempfile.mkdtemp(dir=(LANE_ROOT + "/scratch")).replace("\\", "/"); SANDBOXES.append(S); d = S + "/live/cia-hour-old-cc/m/trained-child/objects"; os.makedirs(d)
    pd = S + "/protected-set.json"; _write(pd, BASE_DOC); files = []; shas = []; lines = []
    _Srv.on_call = None; _Srv.sha = {}; _Srv.size = {}
    for i in range(n):
        data = ("payload-%s-%d" % (name, i)).encode() * 50; s = hashlib.sha256(data).hexdigest(); p = "%s/%s.pt" % (d, s)
        open(p, "wb").write(data); files.append(p); shas.append(s); _Srv.sha[i] = s; _Srv.size[s] = len(data); lines.append("0\t%d\t%s" % (len(data), p))
    open(S + "/l.tsv", "w").write("\n".join(lines) + "\n"); _J.dump({}, open(S + "/walk.json", "w"))
    return S, files, shas, pd
def run_main(S, pd):
    orig_load = E.load_list; saved = (E.WALK, E.RC, PS.PATH)
    E.load_list = lambda: orig_load(S + "/l.tsv", None); E.WALK = S + "/walk.json"; E.RC = S + "/rc.jsonl"; PS.PATH = pd
    del calls[:]; os.remove = _spy; prev = sys.modules.get("huggingface_hub"); sys.modules["huggingface_hub"] = _fake; sys.argv = ["x", "--workers", "1"]; exc = None
    try: E.main()
    except BaseException as e: exc = e
    finally:
        os.remove = real_remove; E.load_list = orig_load; E.WALK, E.RC, PS.PATH = saved
        if prev is None: sys.modules.pop("huggingface_hub", None)
        else: sys.modules["huggingface_hub"] = prev
    rows = [_J.loads(l) for l in open(S + "/rc.jsonl", encoding="utf-8")] if os.path.exists(S + "/rc.jsonl") else []
    sp = S + "/evict-ckpt-20261109.summary.json"; summ = _J.load(open(sp)) if os.path.exists(sp) else None
    return exc, len(calls), rows, summ
_real_summary = (LANE_ROOT + "/logs/evict-ckpt-20261109.summary.json"); _before = os.path.getmtime(_real_summary) if os.path.exists(_real_summary) else None
S, files, shas, pd = sandbox_main("normal")
psha = hashlib.sha256(open(pd, "rb").read()).hexdigest()
exc, nrem, rows, summ = run_main(S, pd)
check("GREEN main() sandbox run: both files removed, one receipt row each carrying the protected-set sha256 + path read before the remove", exc is None and nrem == 2 and not any(os.path.exists(f) for f in files) and len(rows) == 2 and all(r["protected_set_sha256"] == psha and r["protected_set_path"] == pd for r in rows))
check("GREEN the summary lands next to the sandbox receipt; the real summary file is untouched", summ and summ["deleted"] == 2 and (os.path.getmtime(_real_summary) if os.path.exists(_real_summary) else None) == _before)
S, files, shas, pd = sandbox_main("redeclared")
def _redeclare(s):
    if s == shas[0]: _write(pd, dict(BASE_DOC, declared_by="red test redeclared", markers=BASE_DOC["markers"] + [{"marker": "cia-hour-old-cc/"}]))
_Srv.on_call = _redeclare
exc, nrem, rows, summ = run_main(S, pd)
check("RED a marker declared during the server-read window is honoured: nothing removed, no per-file row", exc is None and nrem == 0 and all(os.path.exists(f) for f in files) and rows == [] and summ and summ["deleted"] == 0)
check("RED ... the file in the window is skipped as re-declared during the run, the other is refused up front", summ and any("re-declared during the run" in s[1] for s in summ["skipped"]) and any(s[1].startswith("under a KEEP node") and "re-declared" not in s[1] for s in summ["skipped"]))
S, files, shas, pd = sandbox_main("between")
sha_before = hashlib.sha256(open(pd, "rb").read()).hexdigest()
def _change(s):
    if s == shas[1]: _write(pd, dict(BASE_DOC, declared_by="red test v2", markers=BASE_DOC["markers"] + [{"marker": "cia-hour-unrelated-zz/"}]))
_Srv.on_call = _change
exc, nrem, rows, summ = run_main(S, pd); sha_after = hashlib.sha256(open(pd, "rb").read()).hexdigest()
check("GREEN the declaration changing between two files: row 1 records the old set's sha256, row 2 the new set's", exc is None and len(rows) == 2 and rows[0]["protected_set_sha256"] == sha_before and rows[1]["protected_set_sha256"] == sha_after and sha_before != sha_after)
for _s in SANDBOXES: shutil.rmtree(_s, ignore_errors=True)
check("main refuses partial links unless --allow-partial-links", "--allow-partial-links" in src and "raise EvictRefused(f\"{len(partial)} inodes have links outside" in src)
print("ALL PASS" if ok else "FAILED"); sys.exit(0 if ok else 1)
