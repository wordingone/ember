#!/usr/bin/env python3
"""receipt_ts_authority.py -- shared ordering-authority helper for any probe
that orders, latest()-picks, or supersedes gate receipts by timestamp.

Frozen spec: #60. Finding: a resident-training-gate receipt's
on-disk filename stamp and its own internal `ts` field can diverge (the
2026-06-22 15:03/15:50 incident -- `resident-training-gate-20260622T155000Z-
real-avir-observation-blocked.json` internally stamps `ts`="20260622T150327Z",
~47 minutes earlier than its filename). The receipt's `next_command_if_blocked`
field shows the OUTPUT filename was pre-generated with a rounded-forward
stamp before the receipt's actual content-build time. Any probe that orders
by filename first (`ts_from_name(path) or data.get("ts")`) can be fooled: a
forward-named BLOCKED receipt retroactively "supersedes" a PASS it
chronologically preceded, or a real, later BLOCK is hidden behind an
earlier-looking filename.

Rule (this module is the ONLY place it is implemented -- no per-probe drift):
  ordering authority = the receipt's internal `ts` field, when present and
  parseable as YYYYMMDDTHHMMSSZ; the filename-embedded timestamp is used ONLY
  as a fallback when no internal ts exists or it fails to parse.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone

TS_RE = re.compile(r"(\d{8}T\d{6}Z)")
DIVERGENCE_TOLERANCE_S = 120


def ts_from_name(path):
    """Extract a sortable YYYYMMDDTHHMMSSZ stamp from a filename, or None."""
    m = TS_RE.search(os.path.basename(path))
    return m.group(1) if m else None


def _parse_ts_seconds(ts):
    """Parse a YYYYMMDDTHHMMSSZ stamp to a comparable UTC epoch int, or None
    if `ts` is not a full, valid match of that exact format."""
    if not ts or not TS_RE.fullmatch(ts):
        return None
    try:
        dt = datetime.strptime(ts, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except ValueError:
        return None


def effective_event_ts(path, data):
    """Return (effective_ts, source, divergence_note).

    effective_ts : str|None -- the authoritative sortable YYYYMMDDTHHMMSSZ
      stamp for this receipt, or None if neither internal ts nor filename
      stamp is present/parseable.
    source : "internal" | "filename" | None -- which one won.
    divergence_note : str|None -- populated ONLY when both an internal ts and
      a filename stamp exist, both parse, and they diverge by more than
      DIVERGENCE_TOLERANCE_S seconds. Names both stamps and the delta -- a
      receipt-hygiene smell independent of which one a caller trusts, meant
      to be surfaced as an audit line by the caller.
    """
    internal_raw = (data or {}).get("ts")
    internal = internal_raw if (internal_raw and TS_RE.fullmatch(str(internal_raw))) else None
    fname = ts_from_name(path)

    divergence_note = None
    if internal and fname and internal != fname:
        i_sec = _parse_ts_seconds(internal)
        f_sec = _parse_ts_seconds(fname)
        if i_sec is not None and f_sec is not None:
            delta = abs(f_sec - i_sec)
            if delta > DIVERGENCE_TOLERANCE_S:
                divergence_note = (
                    f"{os.path.basename(path)}: filename stamp {fname} diverges from "
                    f"internal ts {internal} by {delta}s (> {DIVERGENCE_TOLERANCE_S}s "
                    "tolerance) -- ordering authority is internal ts, not filename"
                )

    if internal:
        return internal, "internal", divergence_note
    if fname:
        return fname, "filename", divergence_note
    return None, None, divergence_note


def sort_key(path, data):
    """Tuple sort key for `sorted(...)[-1]`-style latest-picking:
    (effective_ts_or_empty, filename_ts_or_empty, path). filename_ts is kept
    as a tiebreak only (two receipts sharing one internal ts, or both lacking
    one) -- it never overrides a present, parseable internal ts."""
    eff, _source, _div = effective_event_ts(path, data)
    fname = ts_from_name(path) or ""
    return (eff or "", fname, path)
