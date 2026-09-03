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

ROOT = Path(__file__).resolve().parents[3]
VERIFIER = ROOT / "src" / "ember" / "infrastructure" / "tools" / "ember-restart-3b" / "verify_cost_calibration.py"


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
            "checkpoint_manifest_sha256": "bf20f05018991eb611b0623edd50a00ec30639da2f8ccae646f6962f152a2a2b",
            "model_config_sha256": "559959894dc603f9fbccbb091b3a084fef23b58d29add05efd14799a9a298ae0",
            "tokenizer_sha256": "2c557e7ffe64706112ea947d056be503005d90b16f64c57ec354267c7e9e9c97",
            "source_sha256": "1f4616bce05177ce85f7708353ba535bbd8c0521f0e1999719c3c1a79b3d49d6",
            "optimizer_contract_sha256": "2fb50841cdfee597d4477e3017db43db78309b9b839e05e36a97a5281c1d2914",
            "stream_receipt_sha256": "3adffdda07bf6de31c5f9a9b82aaa08134aac567898c27c5fb0eae90d8ee409d",
            "custody": {
                "source_closure_sha256": {
                    "batch.py": "093b4e3c50a6e099b1ac46746729f673522a2f902d18822fb8cef4f4a608f92d",
                    "model.py": "5609032c21aa6020ddc7a492ab5817a86d425571ae81a46efe951c784e70c5bf",
                    "native_compute_screen.py": "1f4616bce05177ce85f7708353ba535bbd8c0521f0e1999719c3c1a79b3d49d6",
                    "parameter_counter.py": "6bb505470775a5b36c764a96a7b1e3475b4eaecce339b594efbaf9e16e8ce873",
                    "run_vertical_slice.py": "9926071dcdec326aed9519b2d45d90d4d7ab9865f331366db310a569bb7b6f9d",
                    "semantic_stream.py": "143ac866cc007068cdc02526acd3684e6ad96ca6ed99debadee71d64cbc1f978",
                }
            },
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
            "receipt_binding": {
                "checkpoint_manifest_sha256": "bf20f05018991eb611b0623edd50a00ec30639da2f8ccae646f6962f152a2a2b",
                "model_config_sha256": "559959894dc603f9fbccbb091b3a084fef23b58d29add05efd14799a9a298ae0",
                "tokenizer_sha256": "2c557e7ffe64706112ea947d056be503005d90b16f64c57ec354267c7e9e9c97",
                "source_sha256": "1f4616bce05177ce85f7708353ba535bbd8c0521f0e1999719c3c1a79b3d49d6",
                "optimizer_contract_sha256": "2fb50841cdfee597d4477e3017db43db78309b9b839e05e36a97a5281c1d2914",
                "stream_receipt_sha256": "3adffdda07bf6de31c5f9a9b82aaa08134aac567898c27c5fb0eae90d8ee409d",
                "source_closure_sha256": {
                    "batch.py": "093b4e3c50a6e099b1ac46746729f673522a2f902d18822fb8cef4f4a608f92d",
                    "model.py": "5609032c21aa6020ddc7a492ab5817a86d425571ae81a46efe951c784e70c5bf",
                    "native_compute_screen.py": "1f4616bce05177ce85f7708353ba535bbd8c0521f0e1999719c3c1a79b3d49d6",
                    "parameter_counter.py": "6bb505470775a5b36c764a96a7b1e3475b4eaecce339b594efbaf9e16e8ce873",
                    "run_vertical_slice.py": "9926071dcdec326aed9519b2d45d90d4d7ab9865f331366db310a569bb7b6f9d",
                    "semantic_stream.py": "143ac866cc007068cdc02526acd3684e6ad96ca6ed99debadee71d64cbc1f978",
                },
            },
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

    def _run(self, receipt: dict[str, object], *, rebind_source_closure: bool = False) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            receipt_path = root / "receipt.json"
            receipt_bytes = json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()
            receipt_path.write_bytes(receipt_bytes)
            certificate_path = root / "certificate.json"
            certificate = self._certificate(receipt_bytes)
            if rebind_source_closure:
                certificate["receipt_binding"]["source_closure_sha256"] = dict(receipt["custody"]["source_closure_sha256"])  # type: ignore[index]
            certificate_path.write_text(json.dumps(certificate), encoding="utf-8")
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

    def test_rejects_receipt_provenance_substitution_even_when_receipt_hash_matches(self) -> None:
        substitutions = {
            "checkpoint_manifest_sha256": "0" * 64,
            "model_config_sha256": "1" * 64,
            "tokenizer_sha256": "2" * 64,
            "source_sha256": "3" * 64,
            "optimizer_contract_sha256": "4" * 64,
            "stream_receipt_sha256": "5" * 64,
        }
        for field, replacement in substitutions.items():
            with self.subTest(field=field):
                receipt = self._receipt()
                receipt[field] = replacement
                result = self._run(receipt)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(f"receipt binding {field} mismatch", result.stderr)

    def test_rejects_source_closure_substitution_even_when_receipt_hash_matches(self) -> None:
        receipt = self._receipt()
        receipt["custody"]["source_closure_sha256"]["model.py"] = "f" * 64  # type: ignore[index]
        result = self._run(receipt)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("receipt binding source_closure_sha256 mismatch", result.stderr)

    def test_rejects_source_closure_missing_a_canonical_file_even_when_rebound(self) -> None:
        receipt = self._receipt()
        del receipt["custody"]["source_closure_sha256"]["semantic_stream.py"]  # type: ignore[index]
        result = self._run(receipt, rebind_source_closure=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("canonical six-file source closure", result.stderr)

    def test_rejects_source_closure_with_an_extra_file_even_when_rebound(self) -> None:
        receipt = self._receipt()
        receipt["custody"]["source_closure_sha256"]["unreviewed.py"] = "a" * 64  # type: ignore[index]
        result = self._run(receipt, rebind_source_closure=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("canonical six-file source closure", result.stderr)

    def test_rejects_source_closure_with_noncanonical_digest_even_when_rebound(self) -> None:
        receipt = self._receipt()
        receipt["custody"]["source_closure_sha256"]["batch.py"] = "A" * 64  # type: ignore[index]
        result = self._run(receipt, rebind_source_closure=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("lowercase SHA-256", result.stderr)


if __name__ == "__main__":
    unittest.main()
