# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"


class WorkflowTruthfulnessTests(unittest.TestCase):
    def test_false_green_and_duplicate_workflows_are_absent(self) -> None:
        self.assertFalse((WORKFLOWS / "gpu-receipt-verify.yml").exists())
        self.assertFalse((WORKFLOWS / "issue-lifecycle-sweep.yml").exists())

    def test_inventory_and_build_smoke_are_truthfully_named(self) -> None:
        inventory = WORKFLOWS / "branch-inventory.yml"
        smoke = WORKFLOWS / "cli-build-smoke.yml"
        self.assertTrue(inventory.is_file())
        self.assertTrue(smoke.is_file())
        self.assertIn("name: Branch inventory", inventory.read_text(encoding="utf-8"))
        self.assertIn("name: cli-build-smoke", smoke.read_text(encoding="utf-8"))
        self.assertFalse((WORKFLOWS / "branch-hygiene-audit.yml").exists())
        self.assertFalse((WORKFLOWS / "release-rehearsal.yml").exists())


if __name__ == "__main__":
    unittest.main()
