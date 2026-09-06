# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""#2159: the governed semantic launcher exposes the segment's micro_batch as --micro-batch.

The segment (#2136) already consumes ``micro_batch`` consecutive receipt-bound episodes per optimizer
step; before this unit the launcher never passed it, so every governed semantic run was mb 1. These
tests prove the flag is wired end to end (argparse -> run_semantic) and that a non-positive shape is
refused before any preflight, without CUDA.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src" / "ember" / "infrastructure" / "tools" / "ember-restart-3b"))

_COMMON = dict(
    seed=0, artifact_root=Path("unused"), receipt_path=Path("unused"), shards_root=Path("unused"), tokenizer_path=Path("unused"),
    expected_receipt_sha256="r" * 64, expected_tokenizer_sha256="t" * 64, expected_architecture_sha256="a" * 64,
    steps=1, sequence_length=1, checkpoint_interval=1, write_budget_bytes=1,
)


class MicroBatchLaunchShapeTests(unittest.TestCase):
    def test_a_non_positive_micro_batch_refuses_before_any_preflight(self) -> None:
        import run_vertical_slice  # noqa: PLC0415

        for bad in (0, -1, 2.0, True):
            with self.assertRaises(ValueError) as caught:
                run_vertical_slice.run_semantic(**_COMMON, micro_batch=bad)
            self.assertTrue(str(caught.exception).startswith("SEMANTIC_MICRO_BATCH_INVALID"), (bad, str(caught.exception)))

    def test_the_flag_reaches_run_semantic_through_the_semantic_subcommand(self) -> None:
        import run_vertical_slice  # noqa: PLC0415

        argv = [
            "run_vertical_slice.py", "semantic", "--seed", "0", "--artifact-root", "unused", "--receipt", "unused",
            "--shards-root", "unused", "--tokenizer", "unused", "--expected-receipt-sha256", "r" * 64,
            "--expected-tokenizer-sha256", "t" * 64, "--expected-architecture-sha256", "a" * 64,
            "--steps", "1", "--sequence-length", "1", "--checkpoint-interval", "1", "--write-budget-gib", "1",
            "--micro-batch", "0",
        ]
        saved = sys.argv
        sys.argv = argv
        try:
            with self.assertRaises(ValueError) as caught:
                run_vertical_slice.main()
        finally:
            sys.argv = saved
        self.assertTrue(str(caught.exception).startswith("SEMANTIC_MICRO_BATCH_INVALID"))

    def test_the_default_launch_shape_is_micro_batch_one(self) -> None:
        import inspect  # noqa: PLC0415

        import run_vertical_slice  # noqa: PLC0415

        parameter = inspect.signature(run_vertical_slice.run_semantic).parameters["micro_batch"]
        self.assertEqual(parameter.default, 1)


if __name__ == "__main__":
    unittest.main()
