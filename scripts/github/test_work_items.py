# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import copy
import unittest

from scripts.github.work_items import (
    WorkItemError,
    build_review_plan,
    verify_live_snapshot,
)


class WorkItemReviewTests(unittest.TestCase):
    def _manifest(self) -> dict:
        return {
            "labels": [
                {"name": name}
                for name in (
                    "kind:defect",
                    "area:runtime",
                    "state:ready",
                    "priority:p2",
                    "severity:s1",
                    "severity:s2",
                )
            ]
        }

    def _snapshot(self) -> dict:
        return {
            "repository": {
                "nameWithOwner": "wordingone/ember",
            },
            "snapshot_sha256": "b" * 64,
            "open_items": [
                {
                    "number": 9999,
                    "node_id": "I_1",
                    "item_type": "issue",
                    "title": "Runtime crash",
                    "body": (
                        "Observed behavior: runtime crash. Expected behavior: the "
                        "runtime stays alive. Reproduction is deterministic. " * 2
                    ),
                    "comments": [],
                    "labels": [],
                    "milestone": None,
                }
            ],
        }

    def test_insufficient_body_fails_closed(self) -> None:
        snapshot = self._snapshot()
        snapshot["repository"] = "wordingone/ember"
        snapshot["open_items"][0]["body"] = ""
        with self.assertRaises(WorkItemError):
            build_review_plan(snapshot, self._manifest())

    def test_reviewed_defect_has_closed_cardinality(self) -> None:
        snapshot = self._snapshot()
        snapshot["repository"] = "wordingone/ember"
        row = build_review_plan(snapshot, self._manifest())["rows"][0]
        self.assertEqual("FULL_BODY_AND_COMMENT_REVIEWED", row["review_status"])
        self.assertEqual(
            1, len([x for x in row["desired_labels"] if x.startswith("kind:")])
        )
        self.assertEqual(
            1, len([x for x in row["desired_labels"] if x.startswith("state:")])
        )
        self.assertEqual(
            1, len([x for x in row["desired_labels"] if x.startswith("severity:")])
        )

    def test_live_preflight_detects_every_review_input_drift(self) -> None:
        snapshot = self._snapshot()
        plan_source = copy.deepcopy(snapshot)
        plan_source["repository"] = "wordingone/ember"
        plan = build_review_plan(plan_source, self._manifest())
        verify_live_snapshot(plan, snapshot)
        for field, changed in (
            ("title", "Different title"),
            ("body", "Different body"),
            ("labels", ["bug"]),
            ("milestone", "Different milestone"),
            ("node_id", "I_other"),
        ):
            drifted = copy.deepcopy(snapshot)
            drifted["open_items"][0][field] = changed
            with self.subTest(field=field), self.assertRaises(WorkItemError):
                verify_live_snapshot(plan, drifted)

    def test_live_preflight_detects_comment_and_population_drift(self) -> None:
        snapshot = self._snapshot()
        plan_source = copy.deepcopy(snapshot)
        plan_source["repository"] = "wordingone/ember"
        plan = build_review_plan(plan_source, self._manifest())
        drifted = copy.deepcopy(snapshot)
        drifted["open_items"][0]["comments"] = [
            {
                "id": 1,
                "author": "wordingone",
                "body": "new",
                "created_at": "2026-07-29T00:00:00Z",
                "updated_at": "2026-07-29T00:00:00Z",
            }
        ]
        with self.assertRaises(WorkItemError):
            verify_live_snapshot(plan, drifted)
        drifted = copy.deepcopy(snapshot)
        drifted["open_items"].append(
            {
                **drifted["open_items"][0],
                "number": 10000,
                "node_id": "I_2",
            }
        )
        with self.assertRaises(WorkItemError):
            verify_live_snapshot(plan, drifted)


if __name__ == "__main__":
    unittest.main()
