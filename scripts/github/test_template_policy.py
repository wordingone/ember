# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import unittest
from pathlib import Path

from scripts.github import template_policy


ROOT = Path(__file__).resolve().parents[2]


class TemplatePolicyTests(unittest.TestCase):
    def test_repository_templates_are_complete_and_parse(self) -> None:
        result = template_policy.validate(ROOT)
        self.assertEqual([], result["errors"])
        self.assertEqual(10, result["issue_form_count"])
        self.assertEqual(10, result["pr_template_count"])


if __name__ == "__main__":
    unittest.main()
