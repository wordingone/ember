#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""governed_abort_observability_guard.py -- EMBER-01 C0 GOVERNED_ABORT_OBSERVABILITY guard.

Cures the GOVERNED_ABORT_OBSERVABILITY row in
manifests/ember-01-custody/c0-failure-class-ledger.json (conjunct-3, PR #1017,
increment 2): "a governed abort (resource cap, headroom violation, kill-discipline
stop) that leaves no receipt is indistinguishable from an unexplained hang, masking
the real defect from post-mortem review." The ledger's blocking_reason names the gap
precisely: "Receipted-abort logging exists for kill-discipline (kill-receipts.jsonl)
but nothing wires a training-loop abort to a mandatory receipt write with a
regression guard that reds on a silent-abort recurrence."

Two halves, same "receipt first" law as kill-discipline.md ("BEFORE any kill: write
a receipt"), generalized to any governed training abort (resource-cap trip,
headroom violation, phase-boundary commit-charge breach, etc.):

  1. emit_abort_receipt() -- the call every governed-abort site must make BEFORE the
     abort completes. Builds + writes a structured receipt naming WHO fired it
     (trigger), WHY (thresholds), the live state at the moment (live_reading), and
     WHEN in the run (phase). Fail-closed: a receipt that cannot name all four is
     never constructed, let alone written -- there is no "abort receipt" that omits
     the reason.

  2. verify_abort_observed() -- given a DETECTED abort event (a trigger + a time
     window it fired in), fail-closed-checks that a matching receipt exists on disk.
     No receipt for a detectable abort is RED (ok=False) -- exactly the silent-abort
     failure this class names, never silently treated as "nothing to verify."
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

REQUIRED_ABORT_RECEIPT_FIELDS = {
    "ticket", "ts", "class", "trigger", "thresholds", "live_reading", "phase",
}


def _utc_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def build_abort_receipt(
    *, trigger: str, thresholds: dict, live_reading: dict, phase: str, extra: Optional[dict] = None
) -> dict:
    """Pure construction, no I/O. Raises ValueError if any required field is
    missing/malformed -- an abort receipt that cannot describe WHO/WHY/WHAT-STATE/
    WHEN is not a real observability receipt; this refuses to build a hollow shell
    rather than emitting one."""
    if not isinstance(trigger, str) or not trigger.strip():
        raise ValueError("build_abort_receipt: trigger must be a non-empty string")
    if not isinstance(thresholds, dict) or not thresholds:
        raise ValueError("build_abort_receipt: thresholds must be a non-empty dict")
    if not isinstance(live_reading, dict) or not live_reading:
        raise ValueError("build_abort_receipt: live_reading must be a non-empty dict")
    if not isinstance(phase, str) or not phase.strip():
        raise ValueError("build_abort_receipt: phase must be a non-empty string")

    receipt = {
        "ticket": "GOVERNED-ABORT-OBSERVABILITY",
        "ts": _utc_ts(),
        "class": "GOVERNED_ABORT_OBSERVABILITY",
        "trigger": trigger,
        "thresholds": thresholds,
        "live_reading": live_reading,
        "phase": phase,
    }
    if extra:
        receipt.update(extra)
    return receipt


def emit_abort_receipt(
    receipt_dir, *, trigger: str, thresholds: dict, live_reading: dict, phase: str, extra: Optional[dict] = None
) -> Path:
    """Builds + WRITES the receipt -- the call every governed-abort site must make
    BEFORE the abort completes. Checked write: reloads and re-validates the schema
    before returning (same discipline as v0_pretrain_launch_gate.emit()); an
    emitted receipt missing a required field raises rather than being silently
    trusted."""
    receipt = build_abort_receipt(
        trigger=trigger, thresholds=thresholds, live_reading=live_reading, phase=phase, extra=extra
    )
    receipt_dir = Path(receipt_dir)
    receipt_dir.mkdir(parents=True, exist_ok=True)
    path = receipt_dir / f"governed-abort-{receipt['ts']}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(receipt, f, indent=2)

    reloaded = json.loads(path.read_text(encoding="utf-8"))
    missing = REQUIRED_ABORT_RECEIPT_FIELDS - reloaded.keys()
    if missing:
        raise RuntimeError(
            f"emit_abort_receipt: EMITTED RECEIPT MISSING FIELDS {sorted(missing)} "
            f"at {path} -- write is void, this must never be silently accepted"
        )
    return path


def verify_abort_observed(event: dict, receipts_dir) -> tuple[bool, str]:
    """Fail-closed check: given a DETECTED abort event
    {"trigger": str, "ts_start": "YYYYMMDDTHHMMSSZ", "ts_end": "YYYYMMDDTHHMMSSZ"},
    scans receipts_dir for a governed-abort-*.json receipt whose trigger matches
    exactly and whose ts falls within [ts_start, ts_end] (inclusive). Returns
    (ok, detail).

    ok=False (RED) when:
      - event is malformed (missing/wrong-type trigger, ts_start, or ts_end;
        ts_start > ts_end),
      - receipts_dir does not exist,
      - no matching receipt is found.
    An abort that fired with no matching receipt on disk is EXACTLY the failure
    this class names -- never silently treated as 'nothing to check'."""
    if not isinstance(event, dict):
        return False, f"GOVERNED_ABORT_OBSERVABILITY: event is not a dict: {event!r}"
    trigger = event.get("trigger")
    ts_start = event.get("ts_start")
    ts_end = event.get("ts_end")
    for name, val in (("trigger", trigger), ("ts_start", ts_start), ("ts_end", ts_end)):
        if not isinstance(val, str) or not val:
            return False, f"GOVERNED_ABORT_OBSERVABILITY: event.{name} missing/invalid: {val!r}"
    if ts_start > ts_end:
        return False, (
            f"GOVERNED_ABORT_OBSERVABILITY: event.ts_start {ts_start!r} > "
            f"event.ts_end {ts_end!r} (malformed window)"
        )

    receipts_dir = Path(receipts_dir)
    if not receipts_dir.is_dir():
        return False, f"GOVERNED_ABORT_OBSERVABILITY: receipts_dir does not exist: {receipts_dir}"

    for candidate in sorted(receipts_dir.glob("governed-abort-*.json")):
        try:
            obj = json.loads(candidate.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(obj, dict):
            continue
        if obj.get("trigger") != trigger:
            continue
        ts = obj.get("ts")
        if not isinstance(ts, str):
            continue
        if ts_start <= ts <= ts_end:
            return True, (
                f"GOVERNED_ABORT_OBSERVABILITY: matching receipt found "
                f"{candidate.name} (trigger={trigger!r}, ts={ts})"
            )

    return False, (
        f"GOVERNED_ABORT_OBSERVABILITY: no matching receipt in {receipts_dir} for "
        f"trigger={trigger!r} within window [{ts_start}, {ts_end}] -- silent abort"
    )
