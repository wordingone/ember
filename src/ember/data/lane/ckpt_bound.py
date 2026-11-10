# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Bound set for checkpoint/child dirs (lead 81958): bound = the TRANSITIVE ANCESTOR CLOSURE of every bound child (walk lineage.parent_checkpoint in each checkpoint-manifest.json up to genesis),
plus the newest trained child and every child dir of a live/pending hour. Nothing in the bound set may be deleted, renamed or re-linked by any lane script.
bound_dirs() -> set of normalized child dirs.   is_bound(dir)   assert_deletable(dir) raises Bound if bound.
Roots (bound children): training's declared bound children (default H39 d4a908e3, H38 by rule) - override with env CKPT_BOUND_ROOTS (';' separated dirs) - + newest trained-child under ember-live-receipts.
Selftest (the red): python ckpt_bound.py selftest"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT, M_ROOT
import os, sys, json, glob, tempfile, shutil

BS = chr(92)
pass


class Bound(Exception):
    pass


def norm(p):
    return p.replace(BS, "/").rstrip("/")


def ancestors(d, max_depth=500):
    """-> list of dirs from d upward (d first), following lineage.parent_checkpoint; stops at genesis, a missing manifest or a cycle."""
    out = []; seen = set(); d = norm(d)
    while d and d not in seen and len(out) < max_depth:
        seen.add(d); out.append(d); mp = d + "/checkpoint-manifest.json"
        if not os.path.exists(mp):
            break
        try:
            pc = (json.load(open(mp)).get("lineage") or {}).get("parent_checkpoint")
        except Exception:
            break
        d = norm(pc) if pc else None
    return out


def newest_trained_child(live_glob=(M_ROOT + "/ember-live-receipts/*/*/trained-child")):
    best = None; bt = 0
    for d in glob.glob(live_glob):
        mp = d + "/checkpoint-manifest.json"
        if os.path.exists(mp) and os.path.getmtime(mp) > bt:
            bt = os.path.getmtime(mp); best = norm(d)
    return best


def roots():
    env = os.environ.get("CKPT_BOUND_ROOTS")
    if env:
        r = [norm(x) for x in env.split(";") if x.strip()]
    else:
        import ckpt_children as C
        r = [norm(C.CH["H39"][1]), norm(C.CH["H38"][1])]
    nt = newest_trained_child()
    return r + ([nt] if nt else [])


def bound_dirs(root_list=None):
    b = set()
    for r in (root_list if root_list is not None else roots()):
        b.update(ancestors(r))
    return b


def is_bound(d, bound=None):
    return norm(d) in (bound if bound is not None else bound_dirs())


def assert_deletable(d, bound=None):
    if is_bound(d, bound):
        raise Bound("refused: %s is the bound set (ancestor closure of a bound child)" % d)
    return True


def selftest():
    t = tempfile.mkdtemp(dir=(LANE_ROOT + "/scratch"), prefix="boundself-"); ok = True

    def mk(name, parent=None):
        d = t.replace(BS, "/") + "/" + name + "/trained-child"; os.makedirs(d)
        json.dump({"lineage": ({"parent_checkpoint": parent} if parent else {})}, open(d + "/checkpoint-manifest.json", "w")); return d

    c = mk("C_genesis"); b = mk("B_mid", c.replace("/", BS)); a = mk("A_head", b); d = mk("D_unrelated")
    bound = bound_dirs([a])

    def chk(n, cond):
        nonlocal ok
        print(("PASS " if cond else "FAIL ") + n); ok = ok and bool(cond)

    chk("closure of head A = {A, B, C}", bound == {norm(a), norm(b), norm(c)})
    try:
        assert_deletable(c, bound); refused = False
    except Bound:
        refused = True
    chk("RED: deleting the genesis ancestor C of bound A is refused", refused)
    try:
        assert_deletable(b, bound); refused = False
    except Bound:
        refused = True
    chk("RED: deleting the mid ancestor B (parent given with backslashes) is refused", refused)
    chk("unrelated child D is deletable", assert_deletable(d, bound) is True)
    shutil.rmtree(t, ignore_errors=True); print("ALL PASS" if ok else "FAILED"); sys.exit(0 if ok else 1)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "selftest":
        selftest()
    else:
        b = bound_dirs(); print(len(b), "bound dirs (ancestor closure + newest trained child)")
