# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import unittest

from scripts.github.branch_hygiene import build as branch_report
from scripts.github.issue_intake import validate
from scripts.github.repo_health import build as health_report


class HealthAndIntakeTests(unittest.TestCase):
    def test_branch_audit_never_grants_delete(self) -> None:
        report = branch_report(
            {
                "repository": "wordingone/ember",
                "snapshot_sha256": "a" * 64,
                "branches": [{"name": "topic", "sha": "b" * 40, "protected": False}],
            }
        )
        self.assertEqual(0, report["verified_delete_count"])
        self.assertEqual("NOT_GRANTED", report["deletion_authority"])

    def test_health_does_not_call_activity_progress(self) -> None:
        report = health_report(
            {
                "repository": "wordingone/ember",
                "snapshot_sha256": "a" * 64,
                "open_items": [],
                "branches": [],
                "workflows": [],
            }
        )
        self.assertEqual("ADVISORY", report["status"])
        self.assertIn("commits_per_day", report["prohibited_progress_proxies"])

    def test_intake_requires_marker_and_closed_cardinality(self) -> None:
        errors = validate({"body": "plain prose", "labels": []})
        self.assertIn("missing Ember issue-form marker", errors)
        valid = validate(
            {
                "body": "<!-- ember-work-item:defect/v1 -->",
                "labels": [
                    {"name": "kind:defect"},
                    {"name": "area:runtime"},
                    {"name": "state:triage"},
                    {"name": "severity:s2"},
                ],
            }
        )
        self.assertEqual([], valid)


if __name__ == "__main__":
    unittest.main()
