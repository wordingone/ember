# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Regression tests for the issue #457 commit-exhaustion acceptance probe."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import issue457_acceptance as acceptance  # noqa: E402


class Issue457AcceptanceTests(unittest.TestCase):
    def test_first_step_commit_classification_passes_bounded_delta(self) -> None:
        result = acceptance.classify_first_step_commit(
            before_bytes=100, after_bytes=120, limit_bytes=20
        )
        self.assertEqual(result["charged_delta_bytes"], 20)
        self.assertEqual(result["verdict"], "PASS")

    def test_first_step_commit_classification_rejects_large_delta(self) -> None:
        result = acceptance.classify_first_step_commit(
            before_bytes=100, after_bytes=121, limit_bytes=20
        )
        self.assertEqual(result["charged_delta_bytes"], 21)
        self.assertEqual(result["verdict"], "FAIL")

    def test_first_step_commit_classification_rejects_invalid_inputs(self) -> None:
        with self.assertRaisesRegex(ValueError, "limit_bytes must be positive"):
            acceptance.classify_first_step_commit(
                before_bytes=1, after_bytes=1, limit_bytes=0
            )
        with self.assertRaisesRegex(ValueError, "before_bytes"):
            acceptance.classify_first_step_commit(
                before_bytes=-1, after_bytes=1, limit_bytes=1
            )

    def test_historical_rung2_receipt_binds_full_measured_probe(self) -> None:
        result = acceptance.validate_historical_rung2_receipt()
        self.assertEqual(result["param_count"], 2_228_265_984)
        self.assertEqual(result["optimizer_steps"], 20)
        self.assertEqual(result["verdict"], "MEASURED_PASS")
        self.assertGreater(result["commit_available_gib"], 0)
        self.assertGreater(result["free_physical_gib_not_the_gate"], 0)

    def test_cpu_first_step_uses_all_file_backed_surfaces(self) -> None:
        readings = iter((100, 120))
        result = acceptance.run_first_step_probe(
            commit_reader=lambda: next(readings),
            tensor_side=8,
            limit_bytes=20,
        )
        self.assertEqual(result["verdict"], "PASS")
        self.assertEqual(result["parameter_count"], 64)
        self.assertEqual(
            result["file_backed_surfaces"],
            [
                "probe_weight.exp_avg.f32",
                "probe_weight.exp_avg_sq.f32",
                "probe_weight.grad.f32",
                "probe_weight.shadow.f32",
            ],
        )

    def test_checked_in_receipt_is_bound_to_current_sources(self) -> None:
        receipt_path = ROOT / "receipts" / "issue-457-current-acceptance-20260730.json"
        receipt = json.loads(receipt_path.read_text(encoding="utf-8", errors="strict"))
        self.assertEqual(receipt["verdict"], "ISSUE_457_ACCEPTANCE_PASS")
        self.assertLessEqual(
            receipt["first_step_private_commit"]["charged_delta_bytes"],
            receipt["first_step_private_commit"]["limit_bytes"],
        )
        sources = receipt["source"]
        for key, path in (
            ("acceptance_probe_sha256", SCRIPTS / "issue457_acceptance.py"),
            ("cpu_offload_adamw_sha256", SCRIPTS / "cpu_offload_adamw.py"),
            ("governor_sha256", SCRIPTS / "governor.py"),
        ):
            self.assertEqual(sources[key], hashlib.sha256(path.read_bytes()).hexdigest())
    @unittest.skipUnless(sys.platform == "win32", "Windows private-commit probe")
    def test_native_commit_reader_releases_windows_memmap_handles(self) -> None:
        result = acceptance.run_first_step_probe(tensor_side=8)
        self.assertEqual(result["verdict"], "PASS")
        self.assertLessEqual(result["charged_delta_bytes"], result["limit_bytes"])

if __name__ == "__main__":
    unittest.main()
