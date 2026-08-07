"""CPU-only contract tests for the governed #764 factor-1 harness."""
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
            result = bench.assert_shape_list_identity(spec["intermediate"], spec)
            self.assertEqual(result["totals"]["n_muon"], bench.REF_N_MUON)
            self.assertEqual(result["totals"]["n_adamw"], bench.REF_N_ADAMW)
            self.assertEqual(result["totals"]["muon_elems_total"], spec["expected_muon_elems"])

    def test_shape_tamper_refuses_before_allocation(self):
        bad = list(bench.build_muon_shape_list(bench.FF_GROWN_2P2B))
        bad[0] = dict(bad[0], shape=(1, 1))
        totals = bench.shape_list_totals(bad, bench.build_adamw_shape_list())
        self.assertNotEqual(totals["muon_elems_total"], bench.REF_2P2B_MUON_STATE_ELEMS)

    def test_current_native_adapter_never_imports_historical_trainer(self):
        self.assertEqual(bench.native.__name__, "factor1_cpuoffload_producer")
        self.assertNotIn("timeshare_pretrain", bench._CurrentNative.__module__)
        self.assertRegex(bench.native.source_identity()["producer_sha256"], r"^[0-9a-f]{64}$")

    def test_governance_and_lease_negatives_are_fail_closed(self):
        with tempfile.TemporaryDirectory(prefix="f1bench-contract-") as td:
            root = Path(td)
            self.assertFalse(bench.preflight_gate(required_working_set_gib=1_000_000.0, run_dir=str(root))["sufficient"])
            self.assertFalse(bench.check_lease_token(None, required_scope="2.2B-cpu")["valid"])
            self.assertEqual(
                bench.lever_L2_subprocess_sweep("434M", {"dir": str(root / "missing")}, None)["status"],
                "REFUSED_UNAUTHORIZED",
            )

    def test_equivalence_and_tamper_negative(self):
        with tempfile.TemporaryDirectory(prefix="f1bench-equivalence-") as td:
            self.assertTrue(bench._selftest_equivalence_gate_corruption_fails(Path(td)))
        self.assertTrue(bench._selftest_l3a_equivalence_numeric())

    def test_all_tiles_and_aggregate_status_are_closed(self):
        self.assertTrue(bench._selftest_l3a_tile_partition_covers_all())
        self.assertTrue(bench._selftest_l3a_aggregate_status_hardened())

    def test_cli_selftest_reports_governed_markers(self):
        completed = subprocess.run(
            [sys.executable, str(Path(bench.__file__).resolve()), "--selftest"],
            capture_output=True, text=True, timeout=180,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        for marker in (
            "F1BENCH_SHAPES_BOUND_PASS PASS",
            "F1BENCH_L0_PRODUCTION_PATH_PASS PASS",
            "F1BENCH_GOVERNANCE_BOUNDARY_PASS PASS",
            "F1BENCH_LEASE_TOKEN_BOUNDARY_PASS PASS",
            "F1BENCH_EQUIVALENCE_GATE_CORRUPTION_DETECTED PASS",
            "F1BENCH_L3A_EQUIVALENCE_NUMERIC_PASS PASS",
            "F1BENCH_L3A_AGGREGATE_STATUS_HARDENED PASS",
            "F1BENCH_NEGATIVE_FIXTURES_PASS PASS",
            "F1BENCH_SELFTEST_ALL_PASS",
        ):
            self.assertIn(marker, completed.stdout)

    def test_live_requires_authority_before_scale_allocation(self):
        with tempfile.TemporaryDirectory(prefix="f1bench-live-refusal-") as td:
            result = bench.run_scale_live("2.2B", bench.ts.load_contract(), Path(td), lease_token_path=None)
        self.assertEqual(result["status"], "REFUSED_UNAUTHORIZED")
        self.assertEqual(result["L3"]["status"], "REFUSED_ANALYTICALLY_INFEASIBLE")

    def test_receipt_contract_has_no_capability_claim(self):
        receipt = bench._build_receipt({"434M": {"status": "REFUSED_UNAUTHORIZED"}}, "20260806T000000Z")
        self.assertEqual(receipt["invariant_sha256"], bench.INVARIANT_SHA256)
        self.assertEqual(receipt["api_spend_usd"], 0)
        self.assertEqual(receipt["paid_api_surface_used"], False)
        self.assertEqual(receipt["results_by_scale"]["434M"]["status"], "REFUSED_UNAUTHORIZED")


if __name__ == "__main__":
    unittest.main()
