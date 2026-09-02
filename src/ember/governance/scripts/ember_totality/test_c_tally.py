#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""
Totality test for Ember goal condition C-TALLY (status probe / TDD).

Authoritative condition text (docs/domains/governance/spec/conditions-v1.md sec 4.3):

  C-TALLY. `src/ember/governance/scripts/ember_tally.py` walks the manifest, verifies each row's
  receipt exists AND passes its named check, emits
  `receipts/tally-<ts>.json {total, implemented, pct, missing[]}`.
  The tally receipt is the only completion authority; prose claims void.
  Each sec-4 condition's CHK must be backed by an executable check (a
  script/verifier the tally invokes against the receipt) -- a condition
  whose CHK is not yet executable counts as missing[], never pass.
  INVALID-TOKEN: `pct<100`.
  CHK: pct=100, missing[] empty, every condition's check is executable.

LANE-14 HARDENING (2026-07-02, R8 probe-faithfulness audit,
docs/goalforge-debate-ledger.md row R8): the pre-hardening version of this
probe trusted the newest receipts/tally-*.json's *self-reported* pct field
outright -- "MISAIMED both directions (RED-by-accident on a 19-day-stale
receipt; one fixture tally file flips the completion headline GREEN)". A
tally-*.json is written by `src/ember/governance/scripts/ember_tally.py` from ITS OWN reading of
the manifest, not from the totality board itself -- nothing forced the two
to agree, and nothing stopped a hand-placed fixture tally file from claiming
pct=100 while the real board was mostly RED.

Fix: RECOMPUTE from the live board rows. The newest
scripts/ember_totality/receipts-totality/ember-totality-*.json receipt IS
the live board (every other probe's rows, aggregated by the runner one
level up) -- this probe reads that receipt's `rows` array directly and
recounts GREEN/total itself, never trusting the runner's own precomputed
`summary.completion_math.complete` boolean either (recompute, don't relay).
A tally-*.json file may still exist and is cited when FRESH (its ts >= the
board receipt's ts), but it is never load-bearing for the verdict -- GREEN
or RED is decided from board rows alone, so a stale or fabricated tally
file can no longer move the needle either direction.

This file is a STATUS PROBE, not a pytest assertion harness:
  - It really inspects the newest receipts-totality/ember-totality-*.json.
  - It prints exactly ONE line: "RED <reason>" or "GREEN <reason>".
  - It ALWAYS exits 0 so the board can aggregate.
  - RED/GREEN is determined by inspecting state, never hardcoded.

Positive CHK (must hold for GREEN):
  the newest board receipt has >=1 STATE-condition row, ALL STATE-condition
  rows (rows whose is_process_invariant is falsy) are GREEN, AND zero
  process-invariant rows carry AUDIT-INCIDENT (mirrors conditions-v1.md
  S4.3's "GOAL SATISFIED" conjunction, recomputed from raw rows).

Negative assertion (the C-TALLY does-NOT-count / invalid-token):
  pct<100 recomputed from the SAME board rows (not any tally-*.json field).
"""

import glob
from datetime import datetime
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _lane14_common import parse_compact_ts  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
CONVERGE = next(
    (p for p in (os.environ.get("EMBER_TOTALITY_ROOT"), REPO_ROOT,
                 os.path.join(REPO_ROOT, "<external-state>"))
     if p and os.path.isdir(p)),
    os.path.join(REPO_ROOT, "<external-state>"),
)

# The live board lives under THIS package's own receipts-totality/ dir when
# resolving against the real repo layout; under an EMBER_TOTALITY_ROOT
# override (control fixtures) it lives at <root>/receipts-totality/ instead,
# mirroring how a fixture root stands in for "this package's directory".
_BOARD_DIR_CANDIDATES = [
    os.path.join(CONVERGE, "scripts", "ember_totality", "receipts-totality"),
    os.path.join(CONVERGE, "receipts-totality"),
    os.path.join(HERE, "receipts-totality"),
]
BOARD_DIR = next((d for d in _BOARD_DIR_CANDIDATES if os.path.isdir(d)),
                  _BOARD_DIR_CANDIDATES[-1])
BOARD_GLOB = os.path.join(BOARD_DIR, "ember-totality-*.json")

TALLY_RECEIPTS_GLOB = os.path.join(CONVERGE, "receipts", "tally-*.json")


def _valid_ts(ts):
    """[HARDENED 2026-07-03] a filename timestamp must be a REAL datetime.
    Two fabricated placeholder-seconds receipts (hour 99) landed in
    receipts-totality/ and, being lexically greatest, would have won every
    'newest' sort forever - this probe was recomputing from their stale
    content. Fail-closed: unparsable timestamps never compete for newest."""
    try:
        datetime.strptime(ts, "%Y%m%dT%H%M%SZ")
        return True
    except (ValueError, TypeError):
        return False


def _newest_by_ts_suffix(paths, prefix, suffix=".json"):
    def ts_of(p):
        base = os.path.basename(p)
        if base.startswith(prefix) and base.endswith(suffix):
            return base[len(prefix):-len(suffix)]
        return base
    valid = [p for p in paths if _valid_ts(ts_of(p))]
    return sorted(valid, key=ts_of)[-1] if valid else None


def _newest_board_path():
    return _newest_by_ts_suffix(glob.glob(BOARD_GLOB), "ember-totality-")


def _newest_tally_path():
    return _newest_by_ts_suffix(glob.glob(TALLY_RECEIPTS_GLOB), "tally-")


def main():
    board_path = _newest_board_path()
    if board_path is None:
        print("RED no ember-totality-*.json board receipt exists under "
              + BOARD_DIR)
        return 0

    try:
        with open(board_path, "r", encoding="utf-8") as fh:
            board = json.load(fh)
    except Exception as exc:
        print("RED newest board receipt %s unreadable: %s"
              % (os.path.basename(board_path), exc))
        return 0

    rows = board.get("rows")
    if not isinstance(rows, list) or not rows:
        print("RED %s has no usable rows[] array" % os.path.basename(board_path))
        return 0

    state_rows = [r for r in rows if not r.get("is_process_invariant")]
    invariant_rows = [r for r in rows if r.get("is_process_invariant")]
    bname = os.path.basename(board_path)

    if not state_rows:
        print("RED %s rows[] present but zero STATE-condition rows found" % bname)
        return 0

    green = sum(1 for r in state_rows if r.get("status") == "GREEN")
    total = len(state_rows)
    pct = round(100.0 * green / total, 1)
    not_green = [r.get("condition") for r in state_rows if r.get("status") != "GREEN"]

    audit_incident = [r.get("condition") for r in invariant_rows
                       if r.get("status") == "AUDIT-INCIDENT"]

    # --- freshness cross-check on any cited tally-*.json (never load-bearing) --
    board_ts = parse_compact_ts(board.get("ts")) or parse_compact_ts(
        (re.search(r"ember-totality-(\d{8}T\d{6}Z)\.json$", bname) or [None, None])[1] or "")
    tally_path = _newest_tally_path()
    tally_note = "no tally-*.json present"
    if tally_path is not None:
        tname = os.path.basename(tally_path)
        m = re.search(r"tally-(\d{8}T\d{6}Z)\.json$", tname)
        tally_ts = parse_compact_ts(m.group(1)) if m else None
        if board_ts is None or tally_ts is None:
            tally_note = f"{tname} present but ts unparseable -> IGNORED (never load-bearing)"
        elif tally_ts >= board_ts:
            tally_note = f"{tname} ts={tally_ts.isoformat()}Z >= board ts -> FRESH (cited, not load-bearing)"
        else:
            tally_note = f"{tname} ts={tally_ts.isoformat()}Z < board ts -> STALE, IGNORED"

    # --- (2) negative assertion: pct<100 recomputed from board rows, not any tally file
    if pct < 100.0:
        print("RED invalid-token pct<100 matched (recomputed from %s: "
              "green=%d/%d=%.1f%%, not-green=%s, audit_incident=%s); tally: %s"
              % (bname, green, total, pct, not_green[:8], audit_incident, tally_note))
        return 0

    if audit_incident:
        print("RED %s: recomputed pct=100 but %d unresolved AUDIT-INCIDENT "
              "process-invariant row(s) %s -> GOAL SATISFIED requires zero; tally: %s"
              % (bname, len(audit_incident), audit_incident, tally_note))
        return 0

    print("GREEN %s: recomputed from live board rows, ALL %d STATE-conditions "
          "GREEN (pct=100), zero AUDIT-INCIDENT among %d process-invariant "
          "row(s); tally: %s"
          % (bname, total, len(invariant_rows), tally_note))
    return 0


if __name__ == "__main__":
    sys.exit(main())
