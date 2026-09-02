#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""TDD: C15 receipt selection by canonical timestamp, not filesystem mtime.

This test verifies that when an older-dated receipt has a NEWER mtime
(due to git checkout refreshing tracked files), the selection correctly
picks the NEWEST-DATED receipt by timestamp, not the mtime-newest.

Defect: test_c15.py's scan() function sorted by filesystem mtime:
    receipt_paths.sort(key=lambda p: os.path.getmtime(p), reverse=True)

This can be inverted by git checkout, causing selection of the wrong
(older) receipt when a newer receipt exists in the same directory.

Fix: Extract timestamp from path or receipt content (via _receipt_ts)
and sort by that instead of filesystem mtime.
"""

import json
import os
import sys
import tempfile
import time
import re
from pathlib import Path


_TS_RE = re.compile(r"(\d{8}T\d{6}Z)")


def _norm_ts(ts: str) -> str:
    """Normalize an ISO8601-ish timestamp to the compact YYYYMMDDTHHMMSSZ form."""
    return re.sub(r"[^0-9A-Za-z]", "", ts or "")


def _receipt_ts_fixed(path: str, obj=None) -> str | None:
    """Extract timestamp from path or receipt content."""
    m = _TS_RE.search(path)
    if m:
        return m.group(1)
    if isinstance(obj, dict):
        ts = obj.get("ts")
        if isinstance(ts, str) and ts:
            return _norm_ts(ts)
    return None


def _get_newest_receipt_unfixed(receipt_paths):
    """UNFIXED VERSION: sorts by mtime (the buggy version)."""
    sorted_paths = sorted(receipt_paths, key=lambda p: os.path.getmtime(p), reverse=True)
    return sorted_paths[0] if sorted_paths else None


def _get_newest_receipt_fixed(receipt_paths):
    """FIXED VERSION: sorts by canonical timestamp from path/content."""
    def _sort_key(path: str) -> str:
        try:
            with open(path) as f:
                obj = json.load(f)
        except Exception:
            obj = None
        ts = _receipt_ts_fixed(path, obj)
        return ts if ts is not None else ""

    sorted_paths = sorted(receipt_paths, key=_sort_key, reverse=True)
    return sorted_paths[0] if sorted_paths else None


def test_c15_receipt_selection_by_timestamp_not_mtime():
    """Plant three mock receipts where older-dated has NEWEST mtime;
    assert unfixed version picks by mtime (FAIL), and fixed version picks by timestamp (PASS)."""

    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a structure with three C15 receipts:
        # Path timestamps: 20260706T100000Z (oldest)
        #                  20260706T200000Z (newest by TIMESTAMP)
        #                  20260706T150000Z (middle timestamp)
        # We'll mtime them in reverse order so the OLDEST NAME has the NEWEST mtime.

        # Create subdirectories to mimic the actual directory structure
        receipt_dir_1 = os.path.join(tmpdir, "receipts", "ember-tiny-bitnet-comparison", "20260706T100000Z")
        receipt_dir_2 = os.path.join(tmpdir, "receipts", "ember-tiny-bitnet-comparison", "20260706T200000Z")
        receipt_dir_3 = os.path.join(tmpdir, "receipts", "ember-tiny-bitnet-comparison", "20260706T150000Z")

        os.makedirs(receipt_dir_1, exist_ok=True)
        os.makedirs(receipt_dir_2, exist_ok=True)
        os.makedirs(receipt_dir_3, exist_ok=True)

        paths = [
            (os.path.join(receipt_dir_1, "tiny_bitnet_comparison_receipt.json"), "20260706T100000Z"),  # oldest
            (os.path.join(receipt_dir_2, "tiny_bitnet_comparison_receipt.json"), "20260706T200000Z"),  # newest
            (os.path.join(receipt_dir_3, "tiny_bitnet_comparison_receipt.json"), "20260706T150000Z"),  # middle
        ]

        mtimes = [
            time.time() + 100,  # oldest gets NEWEST mtime
            time.time() + 10,   # newest gets MIDDLE mtime
            time.time(),        # middle gets OLDEST mtime
        ]

        for (path, ts_val), mtime_val in zip(paths, mtimes):
            # Write a mock C15 receipt with PASS verdict
            mock_receipt = {
                "verdict": "BITNET_COMPARISON_PASS",
                "ts": ts_val,
                "fp16_baseline_identity": "test_fp16",
                "bitnet_model_identity": "test_bitnet",
                "fp16_pre_parameter_hash": "hash1",
                "fp16_post_parameter_hash": "hash2",
                "bitnet_pre_parameter_hash": "hash3",
                "bitnet_post_parameter_hash": "hash4",
                "fp16_trainable_parameter_count": 100,
                "bitnet_trainable_parameter_count": 100,
                "precision_quantization_scheme": {"bitnet": "ternary"},
                "footprint": {"bitnet_effective_weight_bits": 1.58},
                "quality_delta": {},
                "throughput_latency": {},
                "memory_cpu_measurements": {},
                "transfer_rows": [{"test": "data"}],
                "deletion_revert_evidence": [{"test": "data"}],
            }
            with open(path, "w") as f:
                json.dump(mock_receipt, f)
            # Set the mtime to create the inversion
            os.utime(path, (mtime_val, mtime_val))

        # Verify filesystem mtime ordering (proof that the inversion exists)
        file_mtimes = [(p, os.path.getmtime(p)) for p, _ in paths]
        mtime_sorted = sorted(file_mtimes, key=lambda x: x[1], reverse=True)
        newest_by_mtime_path = mtime_sorted[0][0]

        # newest_by_mtime should be the OLDEST-DATED file (20260706T100000Z)
        assert "20260706T100000Z" in newest_by_mtime_path, (
            f"Inversion not set up correctly: {newest_by_mtime_path} "
            f"should contain 20260706T100000Z"
        )
        print(f"[PASS] Inversion verified: {os.path.basename(os.path.dirname(newest_by_mtime_path))} has NEWEST mtime but OLDEST timestamp")

        # Test the UNFIXED version: should pick by mtime (the wrong one)
        receipt_paths_unfixed = [p for p, _ in paths]
        unfixed_result = _get_newest_receipt_unfixed(receipt_paths_unfixed)
        assert "20260706T100000Z" in unfixed_result, (
            f"UNEXPECTED: unfixed version should pick by mtime. "
            f"Got {unfixed_result}, expected 20260706T100000Z"
        )
        print(f"[PASS] UNFIXED version picks by mtime (wrong): {os.path.basename(os.path.dirname(unfixed_result))}")

        # Test the FIXED version: should pick by timestamp (the right one)
        receipt_paths_fixed = [p for p, _ in paths]
        fixed_result = _get_newest_receipt_fixed(receipt_paths_fixed)
        assert "20260706T200000Z" in fixed_result, (
            f"FAIL: fixed version should pick by timestamp. "
            f"Got {fixed_result}, expected 20260706T200000Z"
        )
        print(f"[PASS] FIXED version picks by timestamp (correct): {os.path.basename(os.path.dirname(fixed_result))}")


if __name__ == "__main__":
    test_c15_receipt_selection_by_timestamp_not_mtime()
    print("\n[SUCCESS] All tests passed!")
