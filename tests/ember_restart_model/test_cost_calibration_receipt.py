# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Executable checks for the public seed-83 cost-calibration certificate."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VERIFIER = ROOT / "tools" / "ember-restart-3b" / "verify_cost_calibration.py"


class CostCalibrationReceiptTests(unittest.TestCase):
    @staticmethod
    def _receipt() -> dict[str, object]:
        return {
            "schema_version": "ember-native-compute-screen-v1",
            "result": "MEASURED",
            "admission": "NON_ADMISSIBLE_COMPUTE_PRIMITIVE",
            "genesis_seed": 83,
            "sequence_length": 1024,
            "required_batches": [1, 2],
            "total_parameters": 3_839_161_856,
            "active_parameters": 1_020_589_568,
            "steps": [
                {"batch_size": 1, "elapsed_seconds": 1.0601437999866903, "loss": 10.695884704589844},
                {"batch_size": 2, "elapsed_seconds": 0.7002440000069328, "loss": 10.696664810180664},
            ],
        }

    @staticmethod
    def _certificate(receipt_bytes: bytes) -> dict[str, object]:
        return {
            "schema_version": "ember-anchor-cost-calibration-certificate-v1",
            "source_commit": "04586852b76c7dd4c1e092d656850897c4c0c8d0",
            "prereg_sha256": "a32e6962eb6f88ddb2155f522191b0454851c885b6fa438ead42fa97470fbab8",
            "replication_receipt_sha256": hashlib.sha256(receipt_bytes).hexdigest(),
            "terminal_runner_sha256": "b7473516c3a60abb3e0c3a04a38ec984a5da9aeb2dd5f547ad4a9944e98efbb5",
            "measured_schedule_sha256": "5ee36a684769f9940ceb920c60b0f2bf249695afa3c70b04799cdd500ccb9006",
            "anchor": {
                "batch_1_elapsed_seconds": 1.2448199,
                "batch_2_elapsed_seconds": 0.6903238,
                "batch_1_loss": 10.6958847,
                "batch_2_loss": 10.6966648,
            },
            "thresholds": {
                "batch_1_elapsed_relative_error_max": 0.20,
                "batch_2_elapsed_relative_error_max": 0.20,
                "minimum_batch_2_throughput_speedup_over_batch_1": 1.50,
                "batch_1_loss_absolute_error_from_anchor_max": 0.02,
                "batch_2_loss_absolute_error_from_anchor_max": 0.02,
            },
            "credit": "NON_ADMISSIBLE_COMPUTE_PRIMITIVE_AND_COST_CALIBRATION_ONLY",
        }

    def _run(self, receipt: dict[str, object]) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            receipt_path = root / "receipt.json"
            receipt_bytes = json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()
            receipt_path.write_bytes(receipt_bytes)
            certificate_path = root / "certificate.json"
            certificate_path.write_text(json.dumps(self._certificate(receipt_bytes)), encoding="utf-8")
            return subprocess.run(
                [sys.executable, str(VERIFIER), "--certificate", str(certificate_path), "--receipt", str(receipt_path)],
                capture_output=True,
                text=True,
                check=False,
            )

    def test_accepts_anchor_bound_replication_that_passes_all_five_thresholds(self) -> None:
        result = self._run(self._receipt())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["adjudication"], "PASS")

    def test_rejects_replication_whose_batch_one_loss_drifts_from_anchor(self) -> None:
        receipt = self._receipt()
        receipt["steps"][0]["loss"] = 10.80  # type: ignore[index]
        result = self._run(receipt)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("batch_1_loss_absolute_error_from_anchor", result.stderr)


if __name__ == "__main__":
    unittest.main()
