"""Bounded CPU-only tests for issue #764's fail-closed harness."""
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from scripts import factor1_lever_microbench as bench


class Factor1LeverMicrobenchTests(unittest.TestCase):
    def test_exact_shape_contract_binds_both_scales(self):
        for scale, spec in bench.SCALES.items():
            result = bench.assert_shape_contract(scale)
            self.assertEqual(result["totals"]["n_muon"], bench.REF_N_MUON)
            self.assertEqual(result["totals"]["n_adamw"], bench.REF_N_ADAMW)
            self.assertEqual(result["totals"]["muon_elems_total"], spec["expected_muon_elems"])

    def test_shape_tamper_refuses_before_allocation(self):
        bad = list(bench.build_muon_shape_list(bench.FF_GROWN_2P2B))
        bad[0] = dict(bad[0], shape=(1, 1))
        totals = bench.shape_list_totals(bad, bench.build_adamw_shape_list())
        self.assertNotEqual(totals["muon_elems_total"], bench.REF_2P2B_MUON_STATE_ELEMS)

    def test_resource_gate_refuses_impossible_input(self):
        result = bench.preflight_scale(
            "2.2B", disk_free_gib=0.0,
            available_physical_gib=0.0, available_commit_gib=0.0,
        )
        self.assertFalse(result["sufficient"])
        self.assertGreaterEqual(len(result["refusal_reasons"]), 3)

    def test_current_historical_only_consumer_is_not_bypassed(self):
        status = bench.production_path_status()
        self.assertFalse(status["available"])
        self.assertEqual(status["status"], "PRODUCTION_PATH_UNAVAILABLE_HISTORICAL_ONLY")
        self.assertRegex(status["source_sha256"], r"^[0-9a-f]{64}$")

    def test_real_cpu_offload_wrapper_records_inner_step(self):
        with tempfile.TemporaryDirectory(prefix="f1bench-test-") as td:
            result = bench._fixture_step(Path(td), threads=1, iterations=20)
        self.assertEqual(result["iterations"], 20)
        self.assertGreater(result["median_s"], 0)

    def test_l2_worker_is_fresh_subprocess_and_bounded(self):
        with tempfile.TemporaryDirectory(prefix="f1bench-worker-test-") as td:
            command = [sys.executable, str(Path(bench.__file__).resolve()),
                       "--worker", "--threads", "1", "--iterations", "20",
                       "--replicate", "2", "--tmp", td]
            completed = subprocess.run(command, capture_output=True, text=True, timeout=120)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        rows = [line for line in completed.stdout.splitlines() if line.startswith("F1BENCH_WORKER ")]
        self.assertEqual(len(rows), 1)
        self.assertEqual(json.loads(rows[0].split(" ", 1)[1])["iterations"], 20)

    def test_cli_selftest_reports_required_markers(self):
        completed = subprocess.run(
            [sys.executable, str(Path(bench.__file__).resolve()), "--selftest"],
            capture_output=True, text=True, timeout=180,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        for marker in (
            "F1BENCH_SHAPES_BOUND_PASS",
            "F1BENCH_L0_PRODUCTION_PATH_PASS",
            "F1BENCH_NEGATIVE_FIXTURES_PASS",
            "F1BENCH_EXACT_SCALE_STATUS PRODUCTION_PATH_UNAVAILABLE_HISTORICAL_ONLY",
            "F1BENCH_SELFTEST_ALL_PASS",
        ):
            self.assertIn(marker, completed.stdout)

    def test_fixture_receipt_is_explicitly_non_claiming(self):
        with tempfile.TemporaryDirectory(prefix="f1bench-receipt-test-") as td:
            receipt = Path(td) / "receipt.json"
            completed = subprocess.run(
                [sys.executable, str(Path(bench.__file__).resolve()),
                 "--fixture", "--receipt", str(receipt)],
                capture_output=True, text=True, timeout=180,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            payload = json.loads(receipt.read_text(encoding="utf-8"))
        self.assertEqual(payload["capability_claim"], "NONE")
        self.assertEqual(payload["fixture"]["status"], "FIXTURE_ONLY_NOT_SCALE_EVIDENCE")
        self.assertTrue(all(row["status"].startswith("REFUSED_") for row in payload["scales"].values()))


if __name__ == "__main__":
    unittest.main()
