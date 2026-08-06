"""RED/green tests for the current-native #702 attribution boundary."""
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from scripts import factor1_702_attribution_runner as runner


class CurrentNativeAttributionTests(unittest.TestCase):
    def _snapshot(self) -> dict[str, float]:
        return {"available_commit_gib": 100.0, "available_physical_gib": 100.0, "disk_free_gib": 100.0}

    def test_refuses_without_explicit_execution(self):
        with tempfile.TemporaryDirectory(prefix="702-attribution-test-") as td:
            with self.assertRaisesRegex(PermissionError, "execute=True"):
                runner.run_attribution(Path(td), self._snapshot(), scale="tiny-test")

    def test_refuses_fewer_than_ten_steps(self):
        with tempfile.TemporaryDirectory(prefix="702-attribution-test-") as td:
            with self.assertRaisesRegex(ValueError, "at least 10"):
                runner.run_attribution(Path(td), self._snapshot(), steps=9, execute=True, scale="tiny-test")

    def test_matched_pair_has_ten_samples_per_optimizer_and_phase(self):
        with tempfile.TemporaryDirectory(prefix="702-attribution-test-") as td:
            result = runner.run_attribution(Path(td), self._snapshot(), steps=10, execute=True, scale="tiny-test")
        self.assertEqual(result["verdict"], "CURRENT_NATIVE_ATTRIBUTION_EVIDENCE_NONTERMINAL")
        self.assertTrue(result["claim_boundary"]["matched_profiled_unprofiled_pair"])
        self.assertTrue(result["claim_boundary"]["per_optimizer_spans_present"])
        for optimizer in runner.OPTIMIZERS:
            phases = result["profiled"]["optimizers"][optimizer]
            self.assertEqual(set(phases), set(runner.PHASES))
            for phase in runner.PHASES:
                self.assertEqual(phases[phase]["samples"], 10)
                self.assertEqual(len(phases[phase]["seconds"]), 10)
                self.assertTrue(all(value >= 0 for value in phases[phase]["seconds"]))
        self.assertEqual(result["runtime_boundary"]["execution_device"], "CPU")
        self.assertEqual(result["runtime_boundary"]["interval_tenancy"], "NOT_PROVEN")

    def test_source_hashes_are_computed_from_current_bytes(self):
        identity = runner._source_identity()
        self.assertEqual(identity["runner_sha256"], hashlib.sha256(Path(runner.__file__).read_bytes()).hexdigest())
        self.assertEqual(identity["producer_sha256"], hashlib.sha256(Path(runner.producer.__file__).read_bytes()).hexdigest())
        self.assertTrue(identity["hashes_computed_from_current_bytes"])

    def test_malformed_resource_is_rejected_before_builder(self):
        with tempfile.TemporaryDirectory(prefix="702-attribution-test-") as td:
            bad = {**self._snapshot(), "available_commit_gib": "100"}
            with self.assertRaisesRegex(ValueError, "available_commit_gib"):
                runner.run_attribution(Path(td), bad, steps=10, execute=True, scale="tiny-test")


if __name__ == "__main__":
    unittest.main()
