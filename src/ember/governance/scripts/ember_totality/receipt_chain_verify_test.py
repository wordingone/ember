#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Unit tests for receipt_chain_verify.py

Tests cover:
- Intact chain -> chain_ok true for all receipts
- Missing predecessor -> chain_ok false with detail
- Sha mismatch (tampered/fabricated receipt) -> chain_ok false with detail
- Pre-chain epoch receipts (lacking prev field) -> treated as boundaries
- Parse errors -> properly reported
"""

import hashlib
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

# Add repo root to path
HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, REPO_ROOT)

from scripts.ember_totality import receipt_chain_verify as rcv


def _sha256_data(data: bytes) -> str:
    """Compute sha256 of data."""
    return hashlib.sha256(data).hexdigest()


def _create_test_receipt(ts: str, prev_sha: str = None) -> dict:
    """Create a minimal test receipt."""
    receipt = {
        "receipt_type": "ember_totality_board",
        "ts": ts,
        "summary": {"total": 0},
        "rows": [],
    }
    if prev_sha is not None:
        receipt["prev_totality_receipt_sha256"] = prev_sha
    return receipt


class TestReceiptChainVerify(unittest.TestCase):
    """Unit tests for receipt chain verification."""

    def setUp(self):
        """Create a temporary directory for test receipts."""
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        """Clean up temporary directory."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _write_receipt(self, name: str, data: dict) -> str:
        """Write a receipt JSON file and return its path."""
        path = os.path.join(self.temp_dir, name)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        return path

    def _receipt_sha256(self, name: str) -> str:
        """Compute sha256 of a receipt file."""
        path = os.path.join(self.temp_dir, name)
        with open(path, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()

    def test_empty_directory(self):
        """Empty receipts directory returns empty list."""
        result = rcv.chain_verify(self.temp_dir)
        self.assertEqual(result["receipt_count"], 0)
        self.assertTrue(result["chain_ok"])
        self.assertEqual(result["summary"]["total_receipts"], 0)

    def test_nonexistent_directory(self):
        """Non-existent directory returns empty result."""
        result = rcv.chain_verify("/nonexistent/path/to/receipts")
        self.assertEqual(result["receipt_count"], 0)
        self.assertTrue(result["chain_ok"])

    def test_single_receipt_with_zero_prev(self):
        """Single receipt with prev=0*64 is valid chain start."""
        # First receipt references 0*64 as predecessor (no prior receipt)
        receipt = _create_test_receipt("20260701T100000Z", "0" * 64)
        self._write_receipt("ember-totality-20260701T100000Z.json", receipt)

        result = rcv.chain_verify(self.temp_dir, verbose=True)
        self.assertTrue(result["chain_ok"])
        self.assertEqual(len(result["receipts"]), 1)
        self.assertTrue(result["receipts"][0]["chain_ok"])

    def test_single_receipt_pre_chain_epoch(self):
        """Single receipt without prev field is treated as pre-chain epoch."""
        # Receipt without prev field -> pre-chain epoch boundary
        receipt = _create_test_receipt("20260701T100000Z")
        # Explicitly don't add prev_totality_receipt_sha256
        self._write_receipt("ember-totality-20260701T100000Z.json", receipt)

        result = rcv.chain_verify(self.temp_dir, verbose=True)
        self.assertTrue(result["chain_ok"])
        self.assertEqual(result["summary"]["epoch_boundaries"], 1)
        self.assertTrue(result["receipts"][0]["epoch_boundary"])

    def test_intact_two_receipt_chain(self):
        """Two receipts with correct chain link."""
        # First receipt
        receipt1 = _create_test_receipt("20260701T100000Z", "0" * 64)
        self._write_receipt("ember-totality-20260701T100000Z.json", receipt1)
        sha1 = self._receipt_sha256("ember-totality-20260701T100000Z.json")

        # Second receipt references first receipt's sha256
        receipt2 = _create_test_receipt("20260701T110000Z", sha1)
        self._write_receipt("ember-totality-20260701T110000Z.json", receipt2)

        result = rcv.chain_verify(self.temp_dir, verbose=True)
        self.assertTrue(result["chain_ok"])
        self.assertEqual(len(result["receipts"]), 2)
        self.assertTrue(result["receipts"][0]["chain_ok"])
        self.assertTrue(result["receipts"][1]["chain_ok"])

    def test_chain_break_wrong_sha(self):
        """Chain break: second receipt references wrong sha for first."""
        # First receipt
        receipt1 = _create_test_receipt("20260701T100000Z", "0" * 64)
        self._write_receipt("ember-totality-20260701T100000Z.json", receipt1)

        # Second receipt references WRONG sha (tampered/fabricated)
        wrong_sha = "1" * 64
        receipt2 = _create_test_receipt("20260701T110000Z", wrong_sha)
        self._write_receipt("ember-totality-20260701T110000Z.json", receipt2)

        result = rcv.chain_verify(self.temp_dir, verbose=True)
        self.assertFalse(result["chain_ok"])
        self.assertEqual(result["summary"]["chain_breaks"], 1)
        self.assertFalse(result["receipts"][1]["chain_ok"])
        self.assertIn("chain link broken", result["receipts"][1]["chain_break"])

    def test_three_receipt_chain_intact(self):
        """Three receipts with intact chain."""
        # Receipt 1
        receipt1 = _create_test_receipt("20260701T100000Z", "0" * 64)
        self._write_receipt("ember-totality-20260701T100000Z.json", receipt1)
        sha1 = self._receipt_sha256("ember-totality-20260701T100000Z.json")

        # Receipt 2
        receipt2 = _create_test_receipt("20260701T110000Z", sha1)
        self._write_receipt("ember-totality-20260701T110000Z.json", receipt2)
        sha2 = self._receipt_sha256("ember-totality-20260701T110000Z.json")

        # Receipt 3
        receipt3 = _create_test_receipt("20260701T120000Z", sha2)
        self._write_receipt("ember-totality-20260701T120000Z.json", receipt3)

        result = rcv.chain_verify(self.temp_dir, verbose=True)
        self.assertTrue(result["chain_ok"])
        self.assertEqual(len(result["receipts"]), 3)
        for r in result["receipts"]:
            self.assertTrue(r["chain_ok"])

    def test_three_receipt_chain_with_break_in_middle(self):
        """Three receipts with chain break in the middle."""
        # Receipt 1
        receipt1 = _create_test_receipt("20260701T100000Z", "0" * 64)
        self._write_receipt("ember-totality-20260701T100000Z.json", receipt1)
        sha1 = self._receipt_sha256("ember-totality-20260701T100000Z.json")

        # Receipt 2 - BROKEN LINK (references wrong sha)
        receipt2 = _create_test_receipt("20260701T110000Z", "a" * 64)
        self._write_receipt("ember-totality-20260701T110000Z.json", receipt2)
        sha2 = self._receipt_sha256("ember-totality-20260701T110000Z.json")

        # Receipt 3 - correctly references receipt 2's sha, but chain is broken upstream
        receipt3 = _create_test_receipt("20260701T120000Z", sha2)
        self._write_receipt("ember-totality-20260701T120000Z.json", receipt3)

        result = rcv.chain_verify(self.temp_dir, verbose=True)
        self.assertFalse(result["chain_ok"])
        self.assertEqual(result["summary"]["chain_breaks"], 1)
        self.assertTrue(result["receipts"][0]["chain_ok"])
        self.assertFalse(result["receipts"][1]["chain_ok"])
        self.assertTrue(result["receipts"][2]["chain_ok"])  # Correctly linked despite upstream break

    def test_first_receipt_wrong_prev_not_zero(self):
        """First receipt references non-zero sha (should be 0*64)."""
        receipt = _create_test_receipt("20260701T100000Z", "1" * 64)
        self._write_receipt("ember-totality-20260701T100000Z.json", receipt)

        result = rcv.chain_verify(self.temp_dir, verbose=True)
        self.assertFalse(result["chain_ok"])
        self.assertEqual(result["summary"]["chain_breaks"], 1)
        self.assertFalse(result["receipts"][0]["chain_ok"])
        self.assertIn("First receipt should reference 0*64", result["receipts"][0]["chain_break"])

    def test_mixed_chain_and_pre_chain_epochs(self):
        """Mix of pre-chain epoch receipts and chain receipts."""
        # Pre-chain receipt (no prev field)
        receipt_pre = _create_test_receipt("20260701T100000Z")
        self._write_receipt("ember-totality-20260701T100000Z.json", receipt_pre)
        sha_pre = self._receipt_sha256("ember-totality-20260701T100000Z.json")

        # Epoch boundary: receipt with no prev field
        receipt_boundary = _create_test_receipt("20260701T110000Z")
        self._write_receipt("ember-totality-20260701T110000Z.json", receipt_boundary)
        sha_boundary = self._receipt_sha256("ember-totality-20260701T110000Z.json")

        # Chain start after boundary: references 0*64 (not the previous file)
        receipt_chain = _create_test_receipt("20260701T120000Z", "0" * 64)
        self._write_receipt("ember-totality-20260701T120000Z.json", receipt_chain)

        result = rcv.chain_verify(self.temp_dir, verbose=True)
        self.assertTrue(result["chain_ok"])
        self.assertEqual(result["summary"]["epoch_boundaries"], 2)
        self.assertEqual(result["summary"]["chain_valid"], 3)

    def test_malformed_json_receipt(self):
        """Malformed JSON receipt is reported as parse error."""
        path = os.path.join(self.temp_dir, "ember-totality-20260701T100000Z.json")
        with open(path, "w") as fh:
            fh.write("{invalid json")

        result = rcv.chain_verify(self.temp_dir, verbose=True)
        self.assertFalse(result["chain_ok"])
        self.assertEqual(result["summary"]["parse_errors"], 1)
        self.assertIsNotNone(result["receipts"][0]["issue"])

    def test_extract_ts_from_filename(self):
        """Test timestamp extraction from filename."""
        ts = rcv.extract_ts_from_filename("ember-totality-20260701T120000Z.json")
        self.assertEqual(ts, "20260701T120000Z")

        ts_invalid = rcv.extract_ts_from_filename("not-a-receipt.json")
        self.assertIsNone(ts_invalid)

    def test_list_receipts_in_order(self):
        """Test that receipts are listed in timestamp order."""
        # Write receipts out of chronological order
        self._write_receipt("ember-totality-20260701T120000Z.json", {})
        self._write_receipt("ember-totality-20260701T100000Z.json", {})
        self._write_receipt("ember-totality-20260701T110000Z.json", {})

        receipts = rcv.list_receipts_in_order(self.temp_dir)
        self.assertEqual(len(receipts), 3)
        # Should be sorted by timestamp
        self.assertEqual(receipts[0][0], "ember-totality-20260701T100000Z.json")
        self.assertEqual(receipts[1][0], "ember-totality-20260701T110000Z.json")
        self.assertEqual(receipts[2][0], "ember-totality-20260701T120000Z.json")

    def test_chain_status_summary(self):
        """Test chain status summary reporting."""
        # Create a chain with 1 valid link and 1 break
        receipt1 = _create_test_receipt("20260701T100000Z", "0" * 64)
        self._write_receipt("ember-totality-20260701T100000Z.json", receipt1)

        receipt2 = _create_test_receipt("20260701T110000Z", "a" * 64)  # BREAK
        self._write_receipt("ember-totality-20260701T110000Z.json", receipt2)

        result = rcv.chain_verify(self.temp_dir, verbose=False)
        self.assertEqual(result["summary"]["total_receipts"], 2)
        self.assertEqual(result["summary"]["chain_breaks"], 1)
        self.assertIn("CHAIN BROKEN", result["summary"]["details"])


if __name__ == "__main__":
    unittest.main()
