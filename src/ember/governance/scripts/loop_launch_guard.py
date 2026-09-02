#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Fail-closed launch-order guard for loop runners.

Ensures that any loop launch is guarded by a prior C14 RESIDENT_TRAINING_GATE_PASS receipt
with timestamp strictly before the launch timestamp. Prevents invalid-precondition-bypass
incidents by fail-closed refusal when no PASS receipt exists or PASS postdates the launch.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def parse_iso8601_z(ts_str: str) -> datetime | None:
    """Parse ISO8601Z timestamp strings like '20260704T062951Z'."""
    try:
        return datetime.strptime(ts_str, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def find_resident_training_gate_pass(repo: Path) -> dict[str, Any] | None:
    """Find the most recent C14 RESIDENT_TRAINING_GATE_PASS receipt.

    Returns the parsed receipt dict if found (even if ts is unparseable), None otherwise.
    """
    receipts_dir = repo / "receipts" / "ember-resident-training-gate"
    if not receipts_dir.exists():
        return None

    # Search for ALL resident-training-gate receipt(s) with PASS verdict
    # Sort by filename to get the most recent one
    pass_receipts: list[tuple[Path, dict[str, Any]]] = []
    for receipt_path in sorted(receipts_dir.glob("resident-training-gate-*.json"), reverse=True):
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            if receipt.get("verdict") == "RESIDENT_TRAINING_GATE_PASS":
                pass_receipts.append((receipt_path, receipt))
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            # Skip unparseable JSON files
            continue

    if not pass_receipts:
        return None

    # Return the first (most recent) one found
    return pass_receipts[0][1]


def check_launch_precondition(repo: Path, launch_ts: datetime) -> tuple[bool, dict[str, Any]]:
    """Check if a loop launch is allowed given the C14 RESIDENT_TRAINING_GATE_PASS.

    Args:
        repo: The repository root path
        launch_ts: The launch timestamp (typically datetime.now(timezone.utc))

    Returns:
        (allowed: bool, receipt_dict: dict)
        If allowed is True, receipt_dict contains the guard verdict.
        If allowed is False, receipt_dict contains the named refusal with both timestamps.
    """
    pass_receipt = find_resident_training_gate_pass(repo)

    if pass_receipt is None:
        # No PASS receipt found at all; check if there are any receipts (to distinguish ABSENT from no-receipts-dir)
        receipts_dir = repo / "receipts" / "ember-resident-training-gate"
        if receipts_dir.exists() and any(receipts_dir.glob("resident-training-gate-*.json")):
            # Receipts exist but none are PASS (could be other verdicts, or unparseable)
            return False, {
                "named_precondition": "C14_RESIDENT_TRAINING_GATE_PASS",
                "status": "NO_PASS_VERDICT",
                "launch_ts": launch_ts.strftime("%Y%m%dT%H%M%SZ"),
                "verdict": "LOOP_LAUNCH_PRECONDITION_MISSING",
            }
        else:
            return False, {
                "named_precondition": "C14_RESIDENT_TRAINING_GATE_PASS",
                "status": "ABSENT",
                "launch_ts": launch_ts.strftime("%Y%m%dT%H%M%SZ"),
                "verdict": "LOOP_LAUNCH_PRECONDITION_MISSING",
            }

    pass_ts_str = pass_receipt.get("ts")
    if not pass_ts_str:
        return False, {
            "named_precondition": "C14_RESIDENT_TRAINING_GATE_PASS",
            "status": "UNPARSEABLE_TS",
            "launch_ts": launch_ts.strftime("%Y%m%dT%H%M%SZ"),
            "pass_ts_string": "missing or empty",
            "verdict": "LOOP_LAUNCH_PRECONDITION_UNPARSEABLE",
        }

    pass_ts = parse_iso8601_z(pass_ts_str)
    if pass_ts is None:
        return False, {
            "named_precondition": "C14_RESIDENT_TRAINING_GATE_PASS",
            "status": "UNPARSEABLE_TS",
            "launch_ts": launch_ts.strftime("%Y%m%dT%H%M%SZ"),
            "pass_ts_string": pass_ts_str,
            "verdict": "LOOP_LAUNCH_PRECONDITION_UNPARSEABLE",
        }

    # Check that PASS precedes launch
    if pass_ts >= launch_ts:
        return False, {
            "named_precondition": "C14_RESIDENT_TRAINING_GATE_PASS",
            "status": "POSTDATES_LAUNCH",
            "pass_ts": pass_ts_str,
            "launch_ts": launch_ts.strftime("%Y%m%dT%H%M%SZ"),
            "verdict": "LOOP_LAUNCH_PRECONDITION_POSTDATES",
        }

    # Precondition met
    return True, {
        "named_precondition": "C14_RESIDENT_TRAINING_GATE_PASS",
        "status": "SATISFIED",
        "pass_ts": pass_ts_str,
        "launch_ts": launch_ts.strftime("%Y%m%dT%H%M%SZ"),
        "verdict": "LOOP_LAUNCH_PRECONDITION_PASS",
    }


def guard_loop_launch(repo: Path, launch_ts: datetime | None = None) -> None:
    """Guard a loop launch with the C14 RESIDENT_TRAINING_GATE_PASS precondition.

    If the precondition is not met, raises a RuntimeError with a named refusal.
    If launch_ts is None, uses the current UTC time.

    Args:
        repo: The repository root path
        launch_ts: The launch timestamp (default: now in UTC)

    Raises:
        RuntimeError: If the precondition is not satisfied
    """
    if launch_ts is None:
        launch_ts = datetime.now(timezone.utc)

    allowed, receipt = check_launch_precondition(repo, launch_ts)
    if not allowed:
        verdict = receipt.get("verdict", "UNKNOWN")
        msg = f"Loop launch precondition not met: {verdict}\n{json.dumps(receipt, indent=2)}"
        raise RuntimeError(msg)
