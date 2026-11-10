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
def under(marker, tail="/m/trained-child/objects/ab.pt"):
    return R + marker.rstrip("/") + tail if marker.endswith("/") else R + marker
check("declared shared set is non-empty (%d markers)" % len(D["markers"]), len(D["markers"]) > 0)
for _m in D["markers"]:
    check("RED shared marker object refused: " + _m[-48:], E.refuse_reason(under(_m)) and E.kept(under(_m)) == _m)
    check("RED shared marker: optimizer / replay state under it is KEEP: " + _m[-48:], E.kept(under(_m, "/m/trained-child/optimizer-state.pt")) == _m and E.kept(under(_m, "/m/trained-child/replay-state.pt")) == _m)
    check("RED kept() covers a bare directory path under the marker (no trailing slash): " + _m[-48:], E.kept(under(_m, "/measurement-x/trained-child")) == _m)
_m0 = D["markers"][0]
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
check("main refuses partial links unless --allow-partial-links", "--allow-partial-links" in src and "raise EvictRefused(f\"{len(partial)} inodes have links outside" in src)
print("ALL PASS" if ok else "FAILED"); sys.exit(0 if ok else 1)
