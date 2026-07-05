"""test_launch_gate.py -- hermetic fixture tests for scripts/w2_heldout/launch_gate.py.

Real code (launch_gate.refuse_or_pass / assert_launch_allowed), synthetic-only
data (tempfile.TemporaryDirectory() per case, tiny made-up token rows) -- same
convention as the *_leg_test.py hermetic suites (disconfirmation_leg_test.py,
milestone_leg_test.py). No real corpus or real receipt is touched.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from launch_gate import refuse_or_pass, assert_launch_allowed  # noqa: E402


SEQ = 4
ROWS = np.array([[1, 2, 3, 4, 5], [6, 7, 8, 9, 10], [11, 12, 13, 14, 15]], dtype=np.int64)


def _row_sha(rows: np.ndarray, seq: int) -> str:
    xs, ys = rows[:, :seq], rows[:, 1:seq + 1]
    return hashlib.sha256(np.concatenate([xs, ys], axis=1).tobytes()).hexdigest()


def _write_receipt(path, **fields):
    base = {"pass": True, "seq": SEQ, "batch_sha256": _row_sha(ROWS, SEQ),
            "contamination_recheck": {"confirmed_non_self_matches": 0}}
    base.update(fields)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(base, fh)
    return path


def test_green_pinned_batch_matching_sha_zero_contamination_passes():
    with tempfile.TemporaryDirectory() as td:
        batch_path = os.path.join(td, "batch.npy")
        np.save(batch_path, ROWS)
        receipt_path = _write_receipt(os.path.join(td, "receipt.json"))

        result = refuse_or_pass(batch_path=batch_path, receipt_path=receipt_path)

        assert result.allowed is True
        assert "ALLOWED" in result.reason


def test_red_tampered_batch_sha_mismatch_refuses():
    with tempfile.TemporaryDirectory() as td:
        batch_path = os.path.join(td, "batch.npy")
        np.save(batch_path, ROWS)
        receipt_path = _write_receipt(os.path.join(td, "receipt.json"))

        # Tamper the batch file AFTER the receipt was pinned.
        np.save(batch_path, ROWS + 1)

        result = refuse_or_pass(batch_path=batch_path, receipt_path=receipt_path)

        assert result.allowed is False
        assert "sha256" in result.reason


def test_red_nonzero_contamination_recheck_refuses():
    with tempfile.TemporaryDirectory() as td:
        batch_path = os.path.join(td, "batch.npy")
        np.save(batch_path, ROWS)
        receipt_path = _write_receipt(
            os.path.join(td, "receipt.json"),
            contamination_recheck={"confirmed_non_self_matches": 3})

        result = refuse_or_pass(batch_path=batch_path, receipt_path=receipt_path)

        assert result.allowed is False
        assert "confirmed_non_self_matches" in result.reason


def test_red_pass_field_false_refuses():
    with tempfile.TemporaryDirectory() as td:
        batch_path = os.path.join(td, "batch.npy")
        np.save(batch_path, ROWS)
        receipt_path = _write_receipt(os.path.join(td, "receipt.json"), **{"pass": False})

        result = refuse_or_pass(batch_path=batch_path, receipt_path=receipt_path)

        assert result.allowed is False


def test_red_missing_receipt_refuses():
    with tempfile.TemporaryDirectory() as td:
        batch_path = os.path.join(td, "batch.npy")
        np.save(batch_path, ROWS)

        result = refuse_or_pass(batch_path=batch_path,
                                 receipt_path=os.path.join(td, "does-not-exist.json"))

        assert result.allowed is False
        assert "does not exist" in result.reason


def test_red_missing_batch_file_refuses():
    with tempfile.TemporaryDirectory() as td:
        receipt_path = _write_receipt(os.path.join(td, "receipt.json"))

        result = refuse_or_pass(batch_path=os.path.join(td, "no-such-batch.npy"),
                                 receipt_path=receipt_path)

        assert result.allowed is False
        assert "batch file" in result.reason


def test_red_unparseable_receipt_json_refuses():
    with tempfile.TemporaryDirectory() as td:
        batch_path = os.path.join(td, "batch.npy")
        np.save(batch_path, ROWS)
        receipt_path = os.path.join(td, "receipt.json")
        with open(receipt_path, "w", encoding="utf-8") as fh:
            fh.write("{not valid json")

        result = refuse_or_pass(batch_path=batch_path, receipt_path=receipt_path)

        assert result.allowed is False
        assert "unparseable" in result.reason or "unreadable" in result.reason


def test_newest_receipt_auto_discovery_picks_highest_ts():
    with tempfile.TemporaryDirectory() as td:
        batch_path = os.path.join(td, "batch.npy")
        np.save(batch_path, ROWS)
        receipt_dir = os.path.join(td, "receipts")
        os.makedirs(receipt_dir)
        _write_receipt(os.path.join(receipt_dir, "w2-heldout-decontam-20260101T000000Z.json"),
                       **{"pass": False})
        _write_receipt(os.path.join(receipt_dir, "w2-heldout-decontam-20260704T235959Z.json"))

        result = refuse_or_pass(batch_path=batch_path, receipt_dir=receipt_dir)

        assert result.allowed is True
        assert result.receipt_path.endswith("20260704T235959Z.json")


def test_assert_launch_allowed_raises_systemexit_on_refusal():
    with tempfile.TemporaryDirectory() as td:
        batch_path = os.path.join(td, "batch.npy")
        np.save(batch_path, ROWS)
        with pytest.raises(SystemExit, match="W2_LAUNCH_GATE_REFUSED"):
            assert_launch_allowed(batch_path=batch_path,
                                   receipt_path=os.path.join(td, "missing.json"))


def test_assert_launch_allowed_returns_result_on_pass():
    with tempfile.TemporaryDirectory() as td:
        batch_path = os.path.join(td, "batch.npy")
        np.save(batch_path, ROWS)
        receipt_path = _write_receipt(os.path.join(td, "receipt.json"))

        result = assert_launch_allowed(batch_path=batch_path, receipt_path=receipt_path)

        assert result.allowed is True
