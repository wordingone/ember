# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""The declared protected set for checkpoint deletion (issue 2450).
One file, <lane-root>/loops/protected-set.json (override: env PROTECTED_SET_FILE, tests only), read by every checkpoint-deleting script:
evict_ckpt_list.KEEP_MARKERS (shared by ckpt_backup, ckpt_lineage_delete, reserve_manifest, probe_*) and reserve_evict.KEEP (= shared markers + reserve_markers).
Fail closed: a missing, unreadable, malformed or empty file raises ProtectedSetError, so a deleter that cannot read the declaration removes nothing.
Usage: python scripts/protected_set.py      (prints the markers and the file sha256 that the receipts record)"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT, M_ROOT
import os, json, hashlib

PATH = os.environ.get("PROTECTED_SET_FILE", (LANE_ROOT + "/loops/protected-set.json"))


class ProtectedSetError(RuntimeError):
    pass


def _markers(doc, key, required):
    rows = doc.get(key)
    if rows is None and not required: return ()
    if not isinstance(rows, list) or (required and not rows): raise ProtectedSetError("protected set: '%s' must be a non-empty list" % key)
    out = []
    for r in rows:
        m = r.get("marker") if isinstance(r, dict) else r
        if not isinstance(m, str) or len(m.strip()) < 8 or m.strip() in ("/", "B:/", (M_ROOT + "/")):
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
