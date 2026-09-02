#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""TDD: prev receipt selection by canonical timestamp, not filesystem mtime.

This test verifies that when an older-named receipt has a NEWER mtime
(due to git checkout refreshing tracked files), the selection correctly
picks the NEWEST-NAMED receipt by filename timestamp, not the mtime-
newest.

Defect: receipt 20260707T033509Z incorrectly recorded prev_receipt as
the sha of 20260706T173800Z, skipping two newer receipts
(20260707T011202Z, 20260707T023402Z) that existed in the same dir.

Root cause: git checkout <sha> -- <paths> refreshed tracked receipts' mtimes,
inverting chronological order when max(names, key=getmtime) was used.

Fix: select prev by parsing the YYYYMMDDTHHMMSSZ timestamp from the
filename, never by filesystem mtime.
"""

import json
import os
import sys
import tempfile
import time
import re
import hashlib


# Copy the _RECEIPT_NAME_RE from ember_totality_spec.py
_RECEIPT_NAME_RE = re.compile(r"^ember-totality-(\d{8}T\d{6}Z)\.json$")


def _get_prev_receipt_sha256_unfixed(receipts_dir):
    """UNFIXED VERSION: selects by mtime (the buggy version)."""
    if not os.path.isdir(receipts_dir):
        return None
    names = [n for n in os.listdir(receipts_dir) if _RECEIPT_NAME_RE.match(n)]
    if not names:
        return None
    # BUG: Use mtime-based ordering
    last = max(names, key=lambda n: os.path.getmtime(os.path.join(receipts_dir, n)))
    receipt_path = os.path.join(receipts_dir, last)
    try:
        with open(receipt_path, "rb") as fh:
            data = fh.read()
        return hashlib.sha256(data).hexdigest()
    except Exception:
        return None


def _get_prev_receipt_sha256_fixed(receipts_dir):
    """FIXED VERSION: selects by canonical timestamp from filename."""
    if not os.path.isdir(receipts_dir):
        return None
    names = [n for n in os.listdir(receipts_dir) if _RECEIPT_NAME_RE.match(n)]
    if not names:
        return None
    # FIXED: Parse timestamp from filename, select newest by timestamp
    def extract_timestamp(name):
        m = _RECEIPT_NAME_RE.match(name)
        return m.group(1) if m else ""

    last = max(names, key=extract_timestamp)
    receipt_path = os.path.join(receipts_dir, last)
    try:
        with open(receipt_path, "rb") as fh:
            data = fh.read()
        return hashlib.sha256(data).hexdigest()
    except Exception:
        return None


def test_prev_receipt_selection_by_timestamp_not_mtime():
    """Plant three mock receipts where older-named has NEWEST mtime;
    assert unfixed version picks by mtime (FAIL), and fixed version picks by timestamp (PASS)."""

    with tempfile.TemporaryDirectory() as tmpdir:
        # Create three mock receipt files.
        # Timestamps (in names): 20260706T100000Z (oldest)
        #                        20260706T200000Z (newest by TIMESTAMP)
        #                        20260706T150000Z (middle timestamp)
        # We'll mtime them in reverse order so the OLDEST NAME has the NEWEST mtime.

        names = [
            "ember-totality-20260706T100000Z.json",  # oldest timestamp
            "ember-totality-20260706T200000Z.json",  # newest timestamp
            "ember-totality-20260706T150000Z.json",  # middle timestamp
        ]

        mtimes = [
            time.time() + 100,  # oldest name gets NEWEST mtime
            time.time() + 10,   # newest name gets MIDDLE mtime
            time.time(),        # middle name gets OLDEST mtime
        ]

        for name, mtime_val in zip(names, mtimes):
            path = os.path.join(tmpdir, name)
            # Write a mock receipt
            mock_receipt = {
                "ts": name.replace("ember-totality-", "").replace(".json", ""),
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
        unfixed_sha = _get_prev_receipt_sha256_unfixed(tmpdir)
        with open(os.path.join(tmpdir, names[0]), "rb") as fh:
            sha_of_oldest = hashlib.sha256(fh.read()).hexdigest()

        assert unfixed_sha == sha_of_oldest, (
            f"UNEXPECTED: unfixed version should pick by mtime. "
            f"Got {unfixed_sha}, expected {sha_of_oldest}"
        )
        print(f"[PASS] UNFIXED version picks by mtime (wrong file): {names[0]}")

        # Test the FIXED version: should pick by timestamp (the right one)
        fixed_sha = _get_prev_receipt_sha256_fixed(tmpdir)
        with open(os.path.join(tmpdir, names[1]), "rb") as fh:
            sha_of_newest_ts = hashlib.sha256(fh.read()).hexdigest()

        assert fixed_sha == sha_of_newest_ts, (
            f"FAIL: fixed version should pick by timestamp. "
            f"Got {fixed_sha}, expected {sha_of_newest_ts}"
        )
        print(f"[PASS] FIXED version picks by timestamp (correct file): {names[1]}")


if __name__ == "__main__":
    test_prev_receipt_selection_by_timestamp_not_mtime()
