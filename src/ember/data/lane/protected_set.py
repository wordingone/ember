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
from lane_config import LANE_ROOT
import os, json, hashlib

PATH = (LANE_ROOT + "/loops/protected-set.json")
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
