# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Eligibility guard for the "terminal-probe payload" reclaim class: branch (c) of ckpt_lineage_delete.py only (lead ruling 82451, issue #2454).

A checkpoint probe (2 measured updates) writes a trained-child that the NEXT governed hour reopens in full at hour preparation and again at worker
launch (cia_hour.validate_checkpoint_probe -> parameter_counter._cia_realization_receipt), and that smoke_load_child_v1.py reopens once before the press.
Nothing opens its bytes after the consuming hour is terminal: the verify tail skips the probe, the score chain reads the HOUR child, a probe is never
published as a lineage candidate. So the payload may go once no live or pending hour can still need it. This module decides that, per probe dir.

probe_eligibility(path) -> dict(ok, clause, reason, probe, consumers, terminal_receipt). `path` is a probe's trained-child dir, or a
.checkpoint-quarantine/candidate-trained-child-* dir inside a probe measurement. ok=True carries the clause that passed (it goes into the manifest row).
Refusals (stable codes in `reason`), checked in this order:
  NOT_A_PROBE            the path is not under a cia-probe-* measurement
  KEEP                   an evict_ckpt_list KEEP marker covers it
  PENDING_CONSUMER       a cia-hour-* prediction.json names this probe's measurement and that hour has no hour-result.json / worker-terminal.json
                         (the running H49 v5 hour's probe is this shape)
  WINDOW_NEWEST          gpu-window-open exists and this is the newest cia-probe dir
  FRESH_ORPHAN           no consumer names it and a file under the probe changed within MIN_ORPHAN_IDLE_S (covers the b-floor wait between probe and hour prep)
  LINKED_OUTSIDE         a file of 1 MiB or more has a hard link whose other name is not inside this child (the delete set is never allowed to free it by name)
Clauses that pass: A (every consumer hour has a terminal receipt) and B (no hour names the probe and it has been idle >= MIN_ORPHAN_IDLE_S).
The module never removes or writes anything."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from lane_config import M_ROOT, SEAT_LEAD
import glob
import os
import re
import time

RECEIPTS = (M_ROOT + "/ember-live-receipts")
IN_RECEIPTS = (M_ROOT + "/avir/" + SEAT_LEAD + "/state/issue1945-receipts")
WINDOW_MARKER = (M_ROOT + "/avir/" + SEAT_LEAD + "/state/gpu-window-open")
MIN_ORPHAN_IDLE_S = 2 * 3600
BIG = 1 << 20
_PROBE = re.compile(r"(?P<probe>.*/cia-probe-[^/]+)/measurement-(?P<mid>[0-9a-f]{32})(?:/|$)")
_TERMINAL = ("hour-result.json", "worker-terminal.json")


def _norm(p):
    return os.path.abspath(p).replace("\\", "/")


def locate(path):
    """(probe_dir, measurement_id) for a path under a cia-probe-* measurement, else (None, None)."""
    m = _PROBE.match(_norm(path))
    return (m.group("probe"), m.group("mid")) if m else (None, None)


def _read(p):
    try:
        with open(p, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def consumers(mid, receipts=RECEIPTS, in_root=IN_RECEIPTS):
    """Hours that name this probe measurement: [(kind, dir, terminal_receipt or None)]. kind 'hour' = a cia-hour-* prediction.json, 'ref' = a
    checkpoint-probe-reference.json (a dispatch that has the probe but may not have prepared its hour yet; a REUSE_PROBE_IN retry reads one)."""
    out = []
    for p in sorted(glob.glob(receipts + "/cia-hour-*/prediction.json")):
        if mid in _read(p):
            d = os.path.dirname(_norm(p))
            term = next((t for t in sorted(glob.glob(d + "/measurement-*/" + _TERMINAL[0]) + glob.glob(d + "/measurement-*/" + _TERMINAL[1]))), None)
            out.append(("hour", d, term))
    if os.path.isdir(in_root):
        for p in sorted(glob.glob(in_root + "/**/checkpoint-probe-reference.json", recursive=True)):
            if mid in _read(p):
                out.append(("ref", _norm(p), None))
    return out


def _newest_mtime(d):
    newest = 0.0
    for dp, _, fs in os.walk(d):
        for f in fs:
            try:
                newest = max(newest, os.path.getmtime(os.path.join(dp, f)))
            except OSError:
                pass
    return newest


def _linked_outside(child):
    """Files of >= 1 MiB under `child` whose st_nlink exceeds the number of names for that inode inside `child`."""
    names = {}
    for dp, _, fs in os.walk(child):
        for f in fs:
            p = os.path.join(dp, f)
            try:
                st = os.stat(p)
            except OSError:
                continue
            if st.st_size >= BIG:
                rec = names.setdefault((st.st_dev, st.st_ino), [st.st_nlink, 0, _norm(p)])
                rec[1] += 1
    return [v[2] for v in names.values() if v[0] != v[1]]


def probe_eligibility(path, kept=None, receipts=RECEIPTS, in_root=IN_RECEIPTS, window=WINDOW_MARKER, now=None):
    now = time.time() if now is None else now
    probe, mid = locate(path)
    res = dict(ok=False, clause=None, reason=None, probe=probe, consumers=[], terminal_receipt=None)
    if probe is None:
        res["reason"] = "NOT_A_PROBE"
        return res
    if kept is not None and kept(_norm(path)):
        res["reason"] = "KEEP"
        return res
    allc = consumers(mid, receipts, in_root)
    res["consumers"] = [(k, d) for k, d, _ in allc]
    # A checkpoint-probe-reference.json stays on disk for ever after its hour ended, so a ref alone decides nothing (it is listed for the manifest);
    # the hours that name the probe decide. Current chains `unset REUSE_PROBE_IN` and refuse H*_REUSE_PROBE_IN, so no retry reads an old ref.
    cons = [c for c in allc if c[0] == "hour"]
    if any(t is None for _, _, t in cons):
        res["reason"] = "PENDING_CONSUMER"
        return res
    if os.path.exists(window):
        newest = max(glob.glob(receipts + "/cia-probe-*"), key=lambda d: d.replace("\\", "/").rsplit("-", 1)[-1], default=None)
        if newest is not None and _norm(newest) == probe:
            res["reason"] = "WINDOW_NEWEST"
            return res
    idle = now - _newest_mtime(probe)
    if not cons and idle < MIN_ORPHAN_IDLE_S:
        res["reason"] = "FRESH_ORPHAN"
        return res
    outside = _linked_outside(_norm(path))
    if outside:
        res["reason"] = "LINKED_OUTSIDE " + outside[0]
        return res
    res["ok"] = True
    if cons:
        res["clause"] = "A: every consumer hour has a terminal receipt"
        res["terminal_receipt"] = [t for _, _, t in cons]
    else:
        res["clause"] = "B: no hour names this probe, idle %.1f h" % (idle / 3600)
    return res
