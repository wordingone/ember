# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Upload refuse-list (lead 82100): the pre-redaction originals are local-only forever - they hold the secrets TruffleHog found, operator does not delete data, and nothing may ever upload them.
check(path) raises UploadRefused when the resolved path (symlinks/junctions followed) sits under <lane-root>/scratch/*pre-redaction* or any component contains 'pre-redaction'/'pre_redaction'.
Wired into every funnel: upload_worker.upload_with_watchdog, tick.py pack pushes, bulk_lane raw uploads, raw_roll.roll. Red: scripts/tests/upload_refuse_red_test.py."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import LANE_ROOT
import os, glob
from lane_config import LANE_ROOT as ROOT
MARKS = ("pre-redaction", "pre_redaction")


class UploadRefused(RuntimeError):
    pass


def _norm(p): return os.path.realpath(p).replace(chr(92), "/").lower()


def refused(path):
    """Returns the reason string if path must never be uploaded, else ''. A directory is refused when it IS or CONTAINS (one level) a refused dir."""
    for p in {path, os.path.abspath(path)}:
        hold = os.path.join(p, "HOLD-UPLOAD")      # a pack dir with this marker file is held (reason inside) until the marker is removed: no upload, no delete
        if os.path.isfile(hold):
            try: why = open(hold, encoding="utf-8").read().strip()[:160]
            except OSError: why = "unreadable marker"
            return f"HOLD-UPLOAD marker ({why}): {path}"
        n = _norm(p); raw = p.replace(chr(92), "/").lower()
        if any(m in n or m in raw for m in MARKS): return f"path contains a pre-redaction marker: {path}"
        for d in glob.glob(ROOT + "/scratch/*pre-redaction*") + glob.glob(ROOT + "/scratch/*pre_redaction*"):
            dn = _norm(d)
            if n == dn or n.startswith(dn + "/") or dn.startswith(n.rstrip("/") + "/"): return f"overlaps refused dir {d}: {path}"
    return ""


def check(path):
    r = refused(path)
    if r: raise UploadRefused("UPLOAD REFUSED (lead 82100, pre-redaction originals are local-only): " + r)
