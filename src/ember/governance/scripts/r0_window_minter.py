#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""r0_window_minter.py -- Window receipt minter for R0 autonomy-ladder claim.

R0 invariant: every activity row rendered on the ember-cli surface traces to a real
receipt/registry entry. This script evaluates one window of that invariant.

Spec (issue #109): evaluates one window, emits receipts/autonomy-ladder/R0-window-<n>-<ts>.json
with: window span, rows checked, provenance-match count, verdict, and the R0 provenance binding.

Window receipts must satisfy test_c_auto's checks: strictly increasing ts, resolvable refs.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def load_registry(repo_root: str) -> dict[str, Any]:
    """Load the current registry from receipts for cross-referencing."""
    registry_receipts = {}
    receipts_dir = os.path.join(repo_root, "receipts")
    if not os.path.isdir(receipts_dir):
        return registry_receipts

    # Scan receipts directory for all receipt files (excluding autonomy-ladder subdir)
    for filename in os.listdir(receipts_dir):
        if filename.startswith("autonomy-ladder/"):
            continue
        receipt_path = os.path.join(receipts_dir, filename)
        if os.path.isfile(receipt_path) and filename.endswith(".json"):
            try:
                with open(receipt_path, "r", encoding="utf-8") as fh:
                    receipt = json.load(fh)
                    registry_receipts[filename] = receipt
            except Exception:
                pass

    return registry_receipts


def evaluate_r0_window(
    repo_root: str,
    activity_rows: list[dict[str, Any]],
    window_number: int = 1,
) -> tuple[bool, dict[str, Any]]:
    """
    Evaluate one window of the R0 invariant.

    Args:
        repo_root: Path to repo root
        activity_rows: List of activity rows rendered on ember-cli surface
        window_number: Sequential window number for this evaluation

    Returns:
        (passed: bool, receipt: dict)
    """
    receipt_ts = datetime.now(timezone.utc).isoformat()

    # Load registry for cross-reference
    registry = load_registry(repo_root)

    # Anti-fixture check: every activity row must trace to a receipt
    matched_rows = 0
    unmatched_rows = []

    for row in activity_rows:
        # Extract provenance reference from the row (e.g., filename or receipt-key)
        provenance_ref = row.get("receipt_ref") or row.get("ref")

        if not provenance_ref:
            unmatched_rows.append(row)
            continue

        # Check if this ref resolves in the registry
        if provenance_ref in registry:
            matched_rows += 1
        else:
            unmatched_rows.append(row)

    # Verdict: PASS iff all rows matched
    passed = len(unmatched_rows) == 0

    receipt = {
        "ts": receipt_ts,
        "window_number": window_number,
        "rows_checked": len(activity_rows),
        "matched_rows": matched_rows,
        "unmatched_rows": len(unmatched_rows),
        "verdict": "PASS" if passed else "FAIL",
        "r0_provenance_binding": {
            "source_registry": "receipts/",
            "window_span": f"window-{window_number}",
            "shas": [],  # Would be populated with actual SHAs of the receipts checked
        }
    }

    # Include unmatched rows for diagnostics
    if unmatched_rows:
        receipt["unmatched_rows_detail"] = unmatched_rows

    return passed, receipt


def write_window_receipt(repo_root: str, receipt: dict[str, Any]) -> str:
    """Write window receipt to autonomy-ladder directory."""
    # Ensure directory exists
    receipt_dir = os.path.join(repo_root, "receipts", "autonomy-ladder")
    os.makedirs(receipt_dir, exist_ok=True)

    # Generate filename: R0-window-<n>-<ts>.json
    window_num = receipt.get("window_number", 1)
    ts = receipt["ts"].replace(":", "").replace("-", "").replace("+", "").split(".")[0] + "Z"
    # Simplify ts format to ISO8601-compatible without special chars
    ts_simple = receipt["ts"].replace("T", "T").replace("+00:00", "Z").replace(":", "").split("Z")[0] + "Z"
    filename = f"R0-window-{window_num}-{ts_simple}.json"

    receipt_path = os.path.join(receipt_dir, filename)

    with open(receipt_path, "w", encoding="utf-8") as fh:
        json.dump(receipt, fh, indent=2)
        fh.write("\n")  # LF ending per spec

    return receipt_path


def main():
    if len(sys.argv) < 2:
        print("Usage: r0_window_minter.py <repo_root> [window_number] [activity_rows_json]")
        sys.exit(1)

    repo_root = sys.argv[1]
    window_number = int(sys.argv[2]) if len(sys.argv) > 2 else 1

    # Parse activity rows from JSON if provided
    activity_rows = []
    if len(sys.argv) > 3:
        try:
            activity_rows = json.loads(sys.argv[3])
        except json.JSONDecodeError:
            print(f"ERROR: Invalid JSON for activity_rows", file=sys.stderr)
            sys.exit(1)

    # Evaluate window
    passed, receipt = evaluate_r0_window(repo_root, activity_rows, window_number)

    # Write receipt
    receipt_path = write_window_receipt(repo_root, receipt)

    # Output result
    print(json.dumps({
        "passed": passed,
        "receipt_path": receipt_path,
        "receipt": receipt
    }, indent=2))

    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
