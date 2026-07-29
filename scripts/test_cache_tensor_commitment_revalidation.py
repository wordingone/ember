# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "cache_tensor_commitment_revalidation.py"
SPEC = importlib.util.spec_from_file_location("cache_commitment", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
revalidation = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(revalidation)


class CacheTensorCommitmentRevalidationTests(unittest.TestCase):
    def test_current_public_commitment_revalidates_without_private_replay(self) -> None:
        receipt = revalidation.build_receipt(
            ROOT,
            ROOT / "receipts" / "580rerun-20260710-cache-tensor-commitment.json",
            timestamp="2026-07-29T12:00:00Z",
        )
        self.assertEqual(receipt["ticket"], "580RERUN-CACHE-TENSOR-COMMITMENT")
        self.assertTrue(receipt["public_commitment_validation"]["all_checks_passed"])
        self.assertEqual(receipt["public_commitment_validation"]["tensor_count"], 4)
        self.assertFalse(receipt["claim_boundary"]["exact_private_tensor_bytes_replayed"])
        self.assertFalse(receipt["claim_boundary"]["private_tensor_hashes_recomputed"])
        self.assertEqual(
            receipt["verdict"],
            "PUBLIC_COMMITMENT_REVALIDATED_PRIVATE_BYTES_UNAVAILABLE",
        )

    def test_missing_tensor_digest_fails_closed(self) -> None:
        historical = json.loads(
            (ROOT / "receipts" / "580rerun-20260710-cache-tensor-commitment.json")
            .read_text(encoding="utf-8")
        )
        historical["cache_tensors"]["grad_pre_gate"]["sha256"] = ""
        with self.assertRaisesRegex(ValueError, "grad_pre_gate sha256"):
            revalidation.validate_commitment(
                historical,
                revalidation.load_siblings(ROOT, historical),
                revalidation.validate_current_source(ROOT),
            )

    def test_sibling_cache_path_drift_fails_closed(self) -> None:
        historical = json.loads(
            (ROOT / "receipts" / "580rerun-20260710-cache-tensor-commitment.json")
            .read_text(encoding="utf-8")
        )
        historical["cache_tensors"]["pre_momentum"]["cache_path_as_recorded"] = (
            "receipts\\.rung2-event-cache\\wrong.pt"
        )
        with self.assertRaisesRegex(ValueError, "pre_momentum cache path"):
            revalidation.validate_commitment(
                historical,
                revalidation.load_siblings(ROOT, historical),
                revalidation.validate_current_source(ROOT),
            )

    def test_publish_is_exclusive_lf_only_and_confined(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            receipts = root / "receipts"
            receipts.mkdir()
            target = receipts / "successor.json"
            revalidation.publish({"ticket": "x"}, target, root)
            self.assertNotIn(b"\r\n", target.read_bytes())
            with self.assertRaises(FileExistsError):
                revalidation.publish({"ticket": "x"}, target, root)
            with self.assertRaisesRegex(ValueError, "output must be under receipts"):
                revalidation.publish({"ticket": "x"}, root / "outside.json", root)


if __name__ == "__main__":
    unittest.main()
