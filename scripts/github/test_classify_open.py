# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import unittest

from scripts.github.classify_open import classify


class ClassificationTests(unittest.TestCase):
    def test_title_only_is_never_classified(self) -> None:
        row = classify(
            {
                "number": 1,
                "title": "Crash in checkpoint save",
                "body": "",
                "comments": [],
                "labels": [],
                "milestone": None,
            }
        )
        self.assertEqual("TRIAGE_REQUIRED", row["review_status"])

    def test_preregistered_treatment_control_is_experiment(self) -> None:
        row = classify(
            {
                "number": 2,
                "title": "Frozen run",
                "body": (
                    "This pre-registration specifies a treatment, matched control arm, "
                    "run count, kill criteria, and frozen protocol. " * 2
                ),
                "comments": [],
                "labels": [],
                "milestone": "EMBER-05",
            }
        )
        self.assertIn("kind:experiment", row["labels"])

    def test_roadmap_parent_is_initiative(self) -> None:
        row = classify(
            {
                "number": 3,
                "title": "Roadmap",
                "body": "This canonical roadmap body defines many independently closable outcomes. " * 3,
                "comments": [],
                "labels": ["roadmap:parent"],
                "milestone": "EMBER-03",
            }
        )
        self.assertIn("kind:initiative", row["labels"])


if __name__ == "__main__":
    unittest.main()
