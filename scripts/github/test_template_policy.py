# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import unittest
from pathlib import Path

from scripts.github import template_policy
from scripts.check_pr_authority_binding import load_goal_binding, validate_pr_body


ROOT = Path(__file__).resolve().parents[2]


class TemplatePolicyTests(unittest.TestCase):
    def test_repository_templates_are_complete_and_parse(self) -> None:
        result = template_policy.validate(ROOT)
        self.assertEqual([], result["errors"])
        self.assertEqual(10, result["issue_form_count"])
        self.assertEqual(10, result["pr_template_count"])

    def test_every_pr_template_passes_literal_authority_validator(self) -> None:
        goal, outcome, workstreams = load_goal_binding(ROOT)
        paths = sorted((ROOT / ".github" / "PULL_REQUEST_TEMPLATE").glob("*.md"))
        paths.append(ROOT / ".github" / "PULL_REQUEST_TEMPLATE.md")
        self.assertEqual(11, len(paths))
        for path in paths:
            with self.subTest(path=path.name):
                self.assertTrue(path.is_file())
                self.assertEqual(
                    [],
                    validate_pr_body(
                        path.read_text(encoding="utf-8"),
                        goal,
                        outcome,
                        workstreams,
                    ),
                )

    def test_defect_form_preserves_truthful_uncertainty(self) -> None:
        form = template_policy._strict_yaml(
            ROOT / ".github" / "ISSUE_TEMPLATE" / "01-defect.yml"
        )
        required_by_id = {
            row["id"]: row.get("validations", {}).get("required")
            for row in form["body"]
            if isinstance(row, dict) and "id" in row
        }
        for field in (
            "observed_behavior",
            "expected_behavior",
            "exact_reproduction",
            "environment",
            "commit_or_build_identity",
            "impact",
        ):
            self.assertIs(True, required_by_id[field])
        for field in (
            "first_known_failing_version",
            "last_known_working_version",
            "workaround",
            "required_regression_proof",
        ):
            self.assertIsNot(True, required_by_id[field])


if __name__ == "__main__":
    unittest.main()
