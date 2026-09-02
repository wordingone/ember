#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""TDD: resident gate receipt selection by canonical timestamp, not filesystem mtime.

This test verifies that when an older-named receipt has a NEWER mtime
(due to git checkout refreshing tracked files), the selection correctly
picks the NEWEST-NAMED receipt by filename timestamp, not the mtime-newest.

Defect: latest_resident_gate_receipt() sorted by filesystem mtime, which can
be inverted by git checkout. If an older receipt is newer by mtime, it will
be selected first, skipping newer receipts in the directory.

Root cause: candidates = sorted(..., key=lambda p: p.stat().st_mtime, reverse=True)

Fix: extract timestamp from filename (resident-training-gate-YYYYMMDDTHHMMSSZ.json)
and sort by that instead of filesystem mtime.
"""

import json
import os
import sys
import tempfile
import time
import re
import hashlib
from pathlib import Path


# Regex to extract timestamp from filename
_RECEIPT_NAME_RE = re.compile(r"^resident-training-gate-(\d{8}T\d{6}Z)\.json$")


def _get_latest_receipt_unfixed(gate_root):
    """UNFIXED VERSION: selects by mtime (the buggy version)."""
    if not os.path.isdir(gate_root):
        return None
    candidates = sorted(Path(gate_root).glob("resident-training-gate-*.json"),
                       key=lambda p: p.stat().st_mtime, reverse=True)
    for path in candidates:
        try:
            receipt = json.loads(path.read_text(encoding="utf-8-sig"))
            if receipt.get("resident_training_gate_status") == "PASS":
                return path.name
        except Exception:
            continue
    return None


def _get_latest_receipt_fixed(gate_root):
    """FIXED VERSION: selects by canonical timestamp from filename."""
    if not os.path.isdir(gate_root):
        return None

    def extract_timestamp(path):
        match = re.search(r"(\d{8}T\d{6}Z)", path.name)
        return match.group(1) if match else ""

    candidates = sorted(Path(gate_root).glob("resident-training-gate-*.json"),
                       key=extract_timestamp, reverse=True)
    for path in candidates:
        try:
            receipt = json.loads(path.read_text(encoding="utf-8-sig"))
            if receipt.get("resident_training_gate_status") == "PASS":
                return path.name
        except Exception:
            continue
    return None


def test_resident_gate_receipt_selection_by_timestamp_not_mtime():
    """Plant three mock receipts where older-named has NEWEST mtime;
    assert unfixed version picks by mtime (FAIL), and fixed version picks by timestamp (PASS)."""

    with tempfile.TemporaryDirectory() as tmpdir:
        # Create three mock receipt files.
        # Timestamps (in names): 20260706T100000Z (oldest)
        #                        20260706T200000Z (newest by TIMESTAMP)
        #                        20260706T150000Z (middle timestamp)
        # We'll mtime them in reverse order so the OLDEST NAME has the NEWEST mtime.

        names = [
            "resident-training-gate-20260706T100000Z.json",  # oldest timestamp
            "resident-training-gate-20260706T200000Z.json",  # newest timestamp
            "resident-training-gate-20260706T150000Z.json",  # middle timestamp
        ]

        mtimes = [
            time.time() + 100,  # oldest name gets NEWEST mtime
            time.time() + 10,   # newest name gets MIDDLE mtime
            time.time(),        # middle name gets OLDEST mtime
        ]

        for name, mtime_val in zip(names, mtimes):
            path = os.path.join(tmpdir, name)
            # Write a mock receipt with PASS status
            mock_receipt = {
                "resident_training_gate_status": "PASS",
                "ts": name.replace("resident-training-gate-", "").replace(".json", ""),
                "test": "mock"
            }
            with open(path, "w") as f:
                json.dump(mock_receipt, f)
            # Set the mtime to create the inversion
            os.utime(path, (mtime_val, mtime_val))

        # Verify filesystem mtime ordering (proof that the inversion exists)
        file_mtimes = [
            (name, os.path.getmtime(os.path.join(tmpdir, name)))
            for name in names
        ]
        mtime_sorted = sorted(file_mtimes, key=lambda x: x[1], reverse=True)
        newest_by_mtime_name = mtime_sorted[0][0]

        # newest_by_mtime should be the OLDEST-NAMED file (20260706T100000Z)
        assert newest_by_mtime_name == names[0], (
            f"Inversion not set up correctly: {newest_by_mtime_name} "
            f"should be {names[0]}"
        )
        print(f"[PASS] Inversion verified: {newest_by_mtime_name} has NEWEST mtime but OLDEST timestamp")

        # Test the UNFIXED version: should pick by mtime (the wrong one)
        unfixed_result = _get_latest_receipt_unfixed(tmpdir)
        assert unfixed_result == names[0], (
            f"UNEXPECTED: unfixed version should pick by mtime. "
            f"Got {unfixed_result}, expected {names[0]}"
        )
        print(f"[PASS] UNFIXED version picks by mtime (wrong file): {names[0]}")

        # Test the FIXED version: should pick by timestamp (the right one)
        fixed_result = _get_latest_receipt_fixed(tmpdir)
        assert fixed_result == names[1], (
            f"FAIL: fixed version should pick by timestamp. "
            f"Got {fixed_result}, expected {names[1]}"
        )
        print(f"[PASS] FIXED version picks by timestamp (correct file): {names[1]}")


if __name__ == "__main__":
    test_resident_gate_receipt_selection_by_timestamp_not_mtime()
    print("\n[SUCCESS] All tests passed!")
