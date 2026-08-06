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

    def test_current_native_producer_is_used_and_history_is_not_bypassed(self):
        status = bench.production_path_status()
        self.assertTrue(status["available"])
        self.assertEqual(status["status"], "CURRENT_NATIVE_PRODUCER_AVAILABLE")
        self.assertEqual(status["producer_basename"], "factor1_cpuoffload_producer.py")
        self.assertTrue(status["historical_source_not_used"])
        self.assertRegex(status["producer_sha256"], r"^[0-9a-f]{64}$")
        self.assertRegex(status["optimizer_sha256"], r"^[0-9a-f]{64}$")

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
            "F1BENCH_CURRENT_NATIVE_PRODUCER_SMOKE_PASS",
            "F1BENCH_EXACT_SCALE_STATUS CURRENT_NATIVE_PRODUCER_AVAILABLE",
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
            raw_receipt = receipt.read_bytes()
            self.assertNotIn(b"\r", raw_receipt)
        self.assertEqual(payload["capability_claim"], "NONE")
        self.assertEqual(payload["fixture"]["status"], "FIXTURE_ONLY_NOT_SCALE_EVIDENCE")
        self.assertTrue(all(row["status"] in {"READY_EXACT_SCALE_AWAITING_EXPLICIT_EXECUTION", "REFUSED_PRODUCTION_PREFLIGHT"}
                            for row in payload["scales"].values()))

    def test_bandwidth_sanity_refuses_impossibly_fast_result(self):
        with self.assertRaisesRegex(ValueError, "bandwidth"):
            bench.validate_bandwidth_result(
                measured_s=0.1,
                bytes_moved=4 * 1024**3,
                memory_bandwidth_gib_s=10.0,
            )

    def test_identical_l0_runs_require_overlapping_ci95(self):
        first = [0.90, 1.00, 1.10, 1.00, 0.95]
        second = [0.92, 1.02, 1.08, 1.01, 0.97]
        ci_a = bench.bootstrap_ci95(first, seed=764)
        ci_b = bench.bootstrap_ci95(second, seed=764)
        self.assertTrue(bench.ci95_overlaps(ci_a, ci_b))

    def test_non_overlapping_l0_ci95_refuses(self):
        first = [0.90, 1.00, 1.10, 1.00, 0.95]
        second = [9.2, 10.2, 10.8, 10.1, 9.7]
        ci_a = bench.bootstrap_ci95(first, seed=764)
        ci_b = bench.bootstrap_ci95(second, seed=764)
        self.assertFalse(bench.ci95_overlaps(ci_a, ci_b))


    def test_fixture_receipt_reports_sanity_and_l3_skip(self):
        with tempfile.TemporaryDirectory(prefix="f1bench-receipt-shape-") as td:
            receipt = Path(td) / "receipt.json"
            completed = subprocess.run(
                [sys.executable, str(Path(bench.__file__).resolve()), "--fixture", "--receipt", str(receipt)],
                capture_output=True, text=True, timeout=180,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            payload = json.loads(receipt.read_text(encoding="utf-8"))
        self.assertIn("ci95_s", payload["fixture"]["L0"])
        self.assertTrue(payload["fixture"]["L0"]["ci95_overlap"])
        self.assertEqual(payload["fixture"]["L3"]["status"], "SKIPPED_WITH_REASON")

if __name__ == "__main__":
    unittest.main()
