# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""The declared protected set for checkpoint deletion (issue 2450).
One file, <lane-root>/loops/protected-set.json, read by every checkpoint-deleting script:
evict_ckpt_list.KEEP_MARKERS (shared by ckpt_backup, ckpt_lineage_delete, reserve_manifest, probe_*) and reserve_evict (shared markers + reserve_markers).
The path is fixed: there is no environment override. A test points protected_set.PATH at a temporary file; every receipt that uses the set records the path and the sha256 it read.
Fail closed (ProtectedSetError, so the deleter removes nothing) on: a missing, unreadable or non-object file; a missing 'markers' or 'reserve_markers' key (an explicit empty reserve_markers list is allowed, an absent key is not);
an empty 'markers' list; a marker that is not a string, has leading or trailing whitespace, is shorter than 8 characters, or is a bare root (the lane root, the live-receipts root, a drive).
Usage: python scripts/protected_set.py      (prints the markers and the file sha256 that the receipts record)"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT, M_ROOT, SEAT_TRAIN
import os, re, json, glob, hashlib

PATH = (LANE_ROOT + "/loops/protected-set.json")
GATE_RECEIPTS = (M_ROOT + "/avir/" + SEAT_TRAIN + "/state")          # gate receipts (c1c2-*.json, c1c2-*/**/*.json): every path in a receipt's `inputs` is bound (lead 83469; 2026-11-13 the C2 trained ledger was deleted as "regenerable")
_HERE = os.path.dirname(os.path.abspath(__file__)).replace("\\", "/").rstrip("/")
_BROAD = {"", "b:", "b:/m", _HERE.lower(), os.path.dirname(_HERE).lower(), "ember-live-receipts", "b:/m/ember-live-receipts"}


class ProtectedSetError(RuntimeError):
    pass


def _markers(doc, key, nonempty):
    if key not in doc: raise ProtectedSetError("protected set: key '%s' is missing (an explicit [] is allowed for reserve_markers, an absent key is not)" % key)
    rows = doc[key]
    if not isinstance(rows, list) or (nonempty and not rows): raise ProtectedSetError("protected set: '%s' must be a %slist" % (key, "non-empty " if nonempty else ""))
    out = []
    for r in rows:
        m = r.get("marker") if isinstance(r, dict) else r
        if not isinstance(m, str): raise ProtectedSetError("protected set: marker %r in '%s' is not a string" % (m, key))
        if m != m.strip(): raise ProtectedSetError("protected set: marker %r in '%s' has leading or trailing whitespace (it would never match a path)" % (m, key))
        n = m.replace("\\", "/").rstrip("/").lower()
        if len(m) < 8 or n in _BROAD:
            raise ProtectedSetError("protected set: marker %r in '%s' is empty or too broad to be a path marker" % (m, key))
        out.append(m.replace("\\", "/"))
    return tuple(out)


def load(path=None):
    """-> dict(markers=tuple, reserve_markers=tuple, sha256=str, path=str, declared_by=str, declared_at=str). Raises ProtectedSetError (fail closed)."""
    p = path or PATH
    try:
        raw = open(p, "rb").read()
        doc = json.loads(raw.decode("utf-8"))
    except Exception as e:
        raise ProtectedSetError("protected set unreadable (%s: %s): deleters refuse" % (type(e).__name__, str(e)[:120]))
    if not isinstance(doc, dict): raise ProtectedSetError("protected set is not a JSON object")
    return dict(markers=_markers(doc, "markers", True), reserve_markers=_markers(doc, "reserve_markers", False), sha256=hashlib.sha256(raw).hexdigest(),
                path=p, declared_by=str(doc.get("declared_by", "")), declared_at=str(doc.get("declared_at", "")))


def markers(path=None):
    return load(path)["markers"]


def reserve_markers(path=None):
    d = load(path); return d["markers"] + d["reserve_markers"]


if __name__ == "__main__":
    d = load()
    print("protected set", d["path"], "sha256", d["sha256"], "declared_by", d["declared_by"], "at", d["declared_at"])
    for m in d["markers"]: print("  shared ", m)
    for m in d["reserve_markers"]: print("  reserve", m)


# ---- gate-bound paths (lead 83469, 2026-11-13) --------------------------------------------------------------------------------------------------------------------------------------
# Every path a gate receipt names under `inputs` (trained ledger, candidate ledger, source manifest, ...) plus the optional `bound_paths` list in protected-set.json (the training seat's own protect list)
# is BOUND: a deleter refuses the path itself, anything inside it, and any directory that contains it. Fail closed: an unreadable receipt, an empty receipt set or a bad `bound_paths` raises ProtectedSetError.
_DRIVE = re.compile(r"^[A-Za-z]:[/\\]")
_cache = {}


def _norm(p):
    return p.replace("\\", "/").rstrip("/").lower()


def _receipt_files(gate_dir):
    d = gate_dir.rstrip("/")
    return sorted(set(glob.glob(d + "/c1c2-*.json") + glob.glob(d + "/c1c2-*/**/*.json", recursive=True)))


def bound_paths(gate_dir=None, ps_path=None):
    """-> dict(paths=frozenset of normalised lower-case bound paths, receipts=int, source=dict path -> first receipt naming it). Raises ProtectedSetError (fail closed)."""
    gd = gate_dir or GATE_RECEIPTS; files = _receipt_files(gd)
    if not files: raise ProtectedSetError("gate-bound paths: no c1c2 receipts under %s (cannot know what is bound): deleters refuse" % gd)
    sig = tuple((f, os.stat(f).st_mtime_ns, os.stat(f).st_size) for f in files)
    got = _cache.get(sig)
    if got is None:
        paths = {}; n = 0
        for f in files:
            try: doc = json.loads(open(f, "rb").read().decode("utf-8"))
            except Exception as e: raise ProtectedSetError("gate-bound paths: receipt %s unreadable (%s): deleters refuse" % (os.path.basename(f), type(e).__name__))
            inp = doc.get("inputs") if isinstance(doc, dict) else None
            if not isinstance(inp, dict): continue
            n += 1
            for k, v in inp.items():
                if isinstance(v, str) and _DRIVE.match(v): paths.setdefault(_norm(v), os.path.basename(f) + ":" + k)
        if not n: raise ProtectedSetError("gate-bound paths: no receipt under %s has an `inputs` object: deleters refuse" % gd)
        got = _cache[sig] = (paths, n)
    paths, n = got; paths = dict(paths)
    try: doc = json.loads(open(ps_path or PATH, "rb").read().decode("utf-8"))
    except Exception as e: raise ProtectedSetError("protected set unreadable for bound_paths (%s): deleters refuse" % type(e).__name__)
    extra = doc.get("bound_paths", [])
    if not isinstance(extra, list): raise ProtectedSetError("protected set: 'bound_paths' must be a list")
    for e in extra:
        q = e.get("path") if isinstance(e, dict) else e
        if not isinstance(q, str) or not _DRIVE.match(q) or len(_norm(q)) < 8: raise ProtectedSetError("protected set: bound_paths entry %r is not an absolute drive path" % (e,))
        paths.setdefault(_norm(q), "protected-set.json:bound_paths")
    return dict(paths=frozenset(paths), receipts=n, source=paths)


def bound_hit(path, gate_dir=None, ps_path=None):
    """-> (bound path, why) when `path` is a gate-bound path, inside one, or a directory that contains one; else (None, ''). ProtectedSetError propagates (the caller refuses)."""
    b = bound_paths(gate_dir, ps_path); n = _norm(path)
    for q in b["paths"]:
        if n == q or n.startswith(q + "/") or q.startswith(n + "/"):
            return q, "gate-bound path (%s names %s)" % (b["source"][q], q)
    return None, ""
