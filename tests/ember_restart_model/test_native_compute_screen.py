# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Contract tests for the clean-genesis native full-step compute screen."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "ember-restart-3b"))

from native_compute_screen import screen_plan, screen_receipt


class NativeComputeScreenTests(unittest.TestCase):
    def test_plan_requires_the_two_full_step_arms_and_bounds_probe_arms(self) -> None:
        plan = screen_plan(total_vram_bytes=24 * 1024**3)

        self.assertEqual(plan["sequence_length"], 1024)
        self.assertEqual(plan["required_batches"], [1, 2])
        self.assertEqual(plan["memory_gate_only_batches"], [4, 8])
        self.assertEqual(plan["max_peak_allocated_bytes"], int(24 * 1024**3 * 0.8))
        self.assertEqual(plan["minimum_free_margin_bytes"], int(1.5 * 1024**3))

    def test_receipt_rejects_a_measurement_above_the_vram_governor(self) -> None:
        with self.assertRaisesRegex(MemoryError, "0.8 VRAM governor"):
            screen_receipt(
                model_config_sha256="a" * 64,
                optimizer_contract_sha256="b" * 64,
                tokenizer_sha256="c" * 64,
                checkpoint_manifest_sha256="d" * 64,
                source_sha256="e" * 64,
                total_vram_bytes=24 * 1024**3,
                batch_measurements=[
                    {"batch_size": 1, "elapsed_seconds": 1.0, "peak_allocated_bytes": int(24 * 1024**3 * 0.8) + 1, "peak_reserved_bytes": 1}
                ],
            )

    def test_receipt_rejects_peak_that_leaves_less_than_the_required_free_margin(self) -> None:
        total = 24 * 1024**3
        with self.assertRaisesRegex(MemoryError, "1.5 GiB"):
            screen_receipt(
                model_config_sha256="a" * 64,
                optimizer_contract_sha256="b" * 64,
                tokenizer_sha256="c" * 64,
                checkpoint_manifest_sha256="d" * 64,
                source_sha256="e" * 64,
                total_vram_bytes=total,
                available_vram_bytes=int(total * 0.75) + 1024**3,
                batch_measurements=[
                    {"batch_size": 1, "elapsed_seconds": 1.0, "peak_allocated_bytes": int(total * 0.75), "peak_reserved_bytes": int(total * 0.75)},
                    {"batch_size": 2, "elapsed_seconds": 1.0, "peak_allocated_bytes": int(total * 0.75), "peak_reserved_bytes": int(total * 0.75)},
                ],
            )
    def test_receipt_rejects_missing_required_batch_two(self) -> None:
        with self.assertRaisesRegex(ValueError, "batch-1 then batch-2"):
            screen_receipt(
                model_config_sha256="a" * 64, optimizer_contract_sha256="b" * 64,
                tokenizer_sha256="c" * 64, checkpoint_manifest_sha256="d" * 64,
                source_sha256="e" * 64, total_vram_bytes=24 * 1024**3,
                batch_measurements=[{"batch_size": 1, "elapsed_seconds": 1.0, "peak_allocated_bytes": 10, "peak_reserved_bytes": 11}],
            )
    def test_receipt_binds_full_steps_and_native_identities(self) -> None:
        receipt = screen_receipt(
            model_config_sha256="a" * 64,
            optimizer_contract_sha256="b" * 64,
            tokenizer_sha256="c" * 64,
            checkpoint_manifest_sha256="d" * 64,
            source_sha256="e" * 64,
            total_vram_bytes=24 * 1024**3,
            batch_measurements=[
                {"batch_size": 1, "elapsed_seconds": 1.0, "peak_allocated_bytes": 10, "peak_reserved_bytes": 11},
                {"batch_size": 2, "elapsed_seconds": 2.0, "peak_allocated_bytes": 12, "peak_reserved_bytes": 13},
            ],
        )

        self.assertEqual(receipt["result"], "MEASURED")
        self.assertEqual(receipt["admission"], "NON_ADMISSIBLE_COMPUTE_PRIMITIVE")
        self.assertEqual(receipt["operation"], "CLEAN_GENESIS_FULL_FORWARD_BACKWARD_OPTIMIZER_STEP")
        self.assertEqual(receipt["sequence_length"], 1024)
        self.assertEqual([item["batch_size"] for item in receipt["steps"]], [1, 2])
        self.assertEqual(receipt["checkpoint_manifest_sha256"], "d" * 64)
        self.assertEqual(receipt["optimizer_contract_sha256"], "b" * 64)


if __name__ == "__main__":
    unittest.main()
