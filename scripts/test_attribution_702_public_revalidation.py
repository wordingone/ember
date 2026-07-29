# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import copy
import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "attribution_702_public_revalidation.py"
HISTORICAL = (
    ROOT / "receipts" / "attribution-702-20260711T135717Z-redacted-edition.json"
)


def load_revalidator():
    if not SCRIPT.is_file():
        raise AssertionError("production attribution-702 revalidator is missing")
    spec = importlib.util.spec_from_file_location("attribution_702_revalidation", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Attribution702PublicRevalidationTests(unittest.TestCase):
    def test_exact_public_receipt_revalidates_only_combined_inner_arithmetic(self) -> None:
        revalidation = load_revalidator()
        receipt = revalidation.build_receipt(
            ROOT,
            HISTORICAL,
            timestamp="2026-07-29T12:00:00Z",
        )
        result = receipt["public_arithmetic_revalidation"]
        self.assertEqual(result["combined_inner_mean"], 0.917066)
        self.assertEqual(result["combined_inner_ci95"], [0.91644, 0.91773])
        self.assertEqual(result["stage_mean"], 0.00655)
        self.assertEqual(result["stage_ci95"], [0.006489, 0.006606])
        self.assertEqual(result["sample_count"], 24)
        self.assertTrue(result["factor1_predicate_arithmetic_revalidated"])
        self.assertEqual(
            receipt["verdict"],
            "COMBINED_INNER_ARITHMETIC_REVALIDATED_CONTRACT_GRADE_BLOCKED",
        )
        boundary = receipt["claim_boundary"]
        self.assertFalse(boundary["live_2p2b_experiment_replayed"])
        self.assertFalse(boundary["contract_grade_attribution_claim"])
        self.assertFalse(boundary["branch_a_ns5_routing_claim"])
        self.assertFalse(boundary["issue_702_completion_claim"])

    def test_ratio_tamper_is_rejected_against_recorded_bootstrap(self) -> None:
        revalidation = load_revalidator()
        historical = revalidation.load_json(HISTORICAL)
        tampered = copy.deepcopy(historical)
        tampered["per_step_span_ratios"]["inner_ratio"][0] = 0.1
        with self.assertRaisesRegex(ValueError, "T_inner_over_T_step"):
            revalidation.validate_public_arithmetic(tampered)

    def test_missing_or_nonfinite_ratio_is_rejected(self) -> None:
        revalidation = load_revalidator()
        historical = revalidation.load_json(HISTORICAL)
        missing = copy.deepcopy(historical)
        missing["per_step_span_ratios"]["stage_ratio"].pop()
        with self.assertRaisesRegex(ValueError, "equal nonzero lengths"):
            revalidation.validate_public_arithmetic(missing)

        nonfinite = copy.deepcopy(historical)
        nonfinite["per_step_span_ratios"]["gpu_ratio"][0] = float("nan")
        with self.assertRaisesRegex(ValueError, "finite numeric"):
            revalidation.validate_public_arithmetic(nonfinite)

    def test_exact_source_hash_is_required(self) -> None:
        revalidation = load_revalidator()
        with tempfile.TemporaryDirectory() as td:
            copied = Path(td) / HISTORICAL.name
            copied.write_bytes(HISTORICAL.read_bytes() + b"\n")
            with self.assertRaisesRegex(ValueError, "historical receipt SHA-256"):
                revalidation.build_receipt(
                    ROOT,
                    copied,
                    timestamp="2026-07-29T12:00:00Z",
                )

    def test_publish_is_exclusive_lf_only_and_confined(self) -> None:
        revalidation = load_revalidator()
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
