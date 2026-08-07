"""Fail-closed contract tests for the exact CPU L0-L2 runner."""
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import factor1_exact_cpu_l0_l2 as runner


class ExactCpuL0L2Tests(unittest.TestCase):
    def test_execute_is_required_before_any_work(self):
        with tempfile.TemporaryDirectory(prefix="factor1-exact-contract-") as td:
            with self.assertRaisesRegex(PermissionError, "--execute"):
                runner.run_exact(Path(td), scale="434M", execute=False)

    def test_required_windows_are_fail_closed(self):
        with tempfile.TemporaryDirectory(prefix="factor1-exact-contract-") as td:
            with self.assertRaisesRegex(ValueError, "warmup >=3"):
                runner.run_exact(Path(td), scale="434M", execute=True, warmup=2)
            with self.assertRaisesRegex(ValueError, "active >=20"):
                runner.run_exact(Path(td), scale="434M", execute=True, active=19)

    def test_receipt_contract_is_nonterminal_and_records_all_l2_threads(self):
        stub = {
            "scale": "434M",
            "threads": 1,
            "warmup_steps": 3,
            "active_steps": 20,
            "wall_median_seconds": 1.0,
            "spans": {},
            "transfer_bytes": {},
        }
        with tempfile.TemporaryDirectory(prefix="factor1-exact-contract-") as td:
            with mock.patch.object(runner, "_one_run", return_value=stub), mock.patch.object(
                runner, "_compile_probe", return_value={"status": "PROBE_PASS"}
            ):
                result = runner.run_exact(Path(td), scale="434M", execute=True, l2_replicates=1)
        self.assertEqual(result["schema"], "ember-764-exact-cpu-l0-l2-v1")
        self.assertEqual(result["warmup_steps"], 3)
        self.assertEqual(result["active_steps"], 20)
        self.assertEqual(set(result["l2_thread_sweep"]), {"1", "8", "16", "24", "32"})
        self.assertFalse(result["claim_boundary"]["issue_764_completion"])
        self.assertFalse(result["claim_boundary"]["gpu"])
        self.assertEqual(result["verdict"], "CPU_L0_L2_EXECUTED_NONTERMINAL_PENDING_GPU_L3_AND_CURE_A_B")


if __name__ == "__main__":
    unittest.main()
