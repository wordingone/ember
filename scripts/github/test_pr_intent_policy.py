# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import copy
import unittest

from scripts.github.live_pr_policy import REQUIRED_SECTIONS, SNAPSHOT_FIELDS
from scripts.github.pr_intent_policy import (
    INTENT_FIELDS,
    _names,
    build_intent_snapshot,
    validate_pr_intent,
    validate_vocabulary,
)


BASE = "a" * 40
HEAD = "b" * 40
AUTHORITY = (
    "EMBER-02",
    "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember",
    ("EMBER-02A", "EMBER-02B", "EMBER-02C"),
)
KNOWN_LABELS = [
    "kind:defect",
    "kind:governance",
    "area:ci",
    "area:governance",
    "area:tools",
    "state:review",
    "priority:p2",
    "review:self-only",
    "affects:EMBER-02",
    "needs:review",
]
KNOWN_MILESTONES = ["EMBER-02 — Three-billion-parameter foundation birth", "EMBER-03 — Body"]
MILESTONE = KNOWN_MILESTONES[0]


def intent_body() -> str:
    filler = {
        "Linked issue or governing contract": "Relates to #1285",
        "Exact base SHA": BASE,
        "Exact reviewed head SHA": HEAD,
        "Affected milestones": MILESTONE,
    }
    header = (
        "<!-- ember-template: pr/defect@v1 -->\n"
        "goal_id: EMBER-02\n"
        "workstream_id: EMBER-02A\n"
        "next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember\n"
    )
    return header + "".join(
        f"\n## {heading}\n\n{filler.get(heading, 'Stated in full for the preflight fixture.')}\n"
        for heading in REQUIRED_SECTIONS
    )


def intent() -> dict[str, object]:
    return {
        "actor_login": "wordingone",
        "title": "fix(tools): preflight a pull request before it is opened",
        "body": intent_body(),
        "base_sha": BASE,
        "head_sha": HEAD,
        "draft": False,
        "labels": [
            "kind:defect",
            "area:tools",
            "state:review",
            "priority:p2",
            "review:self-only",
        ],
        "milestone": MILESTONE,
        "changed_files": ["scripts/github/pr_intent_policy.py"],
    }


def check(payload: dict[str, object]) -> list[str]:
    return validate_pr_intent(
        payload,
        authority=AUTHORITY,
        known_labels=KNOWN_LABELS,
        known_milestones=KNOWN_MILESTONES,
    )


class IntentSchemaTest(unittest.TestCase):
    def test_intent_fields_are_the_gate_fields_minus_the_derived_pair(self) -> None:
        """The schema is derived, so a gate field addition cannot be silently ignored."""
        self.assertEqual(INTENT_FIELDS | {"event_base_sha", "event_head_sha"}, SNAPSHOT_FIELDS)

    def test_snapshot_derives_event_shas_from_the_intent(self) -> None:
        snapshot = build_intent_snapshot(intent())

        self.assertEqual(snapshot["event_base_sha"], BASE)
        self.assertEqual(snapshot["event_head_sha"], HEAD)
        self.assertEqual(set(snapshot), SNAPSHOT_FIELDS)

    def test_missing_field_is_named(self) -> None:
        payload = intent()
        del payload["milestone"]

        self.assertIn("intent:missing-fields:milestone", check(payload))

    def test_unknown_field_is_named(self) -> None:
        payload = intent()
        payload["reviewers"] = ["someone"]

        self.assertIn("intent:unknown-fields:reviewers", check(payload))


class IntentPolicyTest(unittest.TestCase):
    def test_complete_intent_passes(self) -> None:
        self.assertEqual(check(intent()), [])

    def test_missing_milestone_fails(self) -> None:
        payload = intent()
        payload["milestone"] = None

        self.assertIn("milestone:required-or-exception", check(payload))

    def test_two_kind_labels_fail(self) -> None:
        payload = intent()
        payload["labels"] = list(payload["labels"]) + ["kind:governance"]

        self.assertIn("labels:kind-cardinality", check(payload))

    def test_missing_required_section_fails(self) -> None:
        payload = intent()
        payload["body"] = str(payload["body"]).replace("## Claim boundary", "## Claim bounds")

        self.assertIn("body:section-empty:Claim boundary", check(payload))

    def test_title_grammar_is_enforced(self) -> None:
        payload = intent()
        payload["title"] = "preflight a pull request before it is opened"

        self.assertIn("title:grammar-invalid", check(payload))

    def test_template_marker_is_required(self) -> None:
        payload = intent()
        payload["body"] = str(payload["body"]).replace(
            "<!-- ember-template: pr/defect@v1 -->", ""
        )

        self.assertIn("body:template-marker-missing", check(payload))

    def test_body_head_sha_must_match_the_intended_head(self) -> None:
        payload = intent()
        payload["head_sha"] = "c" * 40

        self.assertIn("body:head-sha-mismatch", check(payload))


class VocabularyTest(unittest.TestCase):
    def test_unknown_area_label_fails(self) -> None:
        """The exact miss that shipped a green preflight and a red CI run."""
        payload = intent()
        payload["labels"] = [
            "kind:defect",
            "area:tooling",
            "state:review",
            "priority:p2",
            "review:self-only",
        ]

        errors = check(payload)

        self.assertIn("vocabulary:label-unknown:area:tooling", errors)
        # Cardinality alone cannot see it: the families are all satisfied.
        self.assertNotIn("labels:area-cardinality", errors)

    def test_unknown_milestone_fails(self) -> None:
        payload = intent()
        payload["milestone"] = "EMBER-99 — Not a milestone"
        payload["body"] = str(payload["body"]).replace(MILESTONE, payload["milestone"])

        self.assertIn(
            "vocabulary:milestone-unknown:EMBER-99 — Not a milestone", check(payload)
        )

    def test_absent_vocabulary_is_an_error_not_a_skip(self) -> None:
        self.assertEqual(
            validate_vocabulary([], None, known_labels=None, known_milestones=None),
            ["vocabulary:unavailable"],
        )
        self.assertEqual(
            validate_vocabulary(
                [], None, known_labels=KNOWN_LABELS, known_milestones=None
            ),
            ["vocabulary:unavailable"],
        )

    def test_intent_without_vocabulary_fails_closed(self) -> None:
        errors = validate_pr_intent(
            intent(), authority=AUTHORITY, known_labels=None, known_milestones=None
        )

        self.assertIn("vocabulary:unavailable", errors)


class VocabularyPayloadTest(unittest.TestCase):
    def test_plain_names_objects_and_pages_all_normalize(self) -> None:
        self.assertEqual(_names(["area:ci"], "name"), ["area:ci"])
        self.assertEqual(_names([{"name": "area:ci"}], "name"), ["area:ci"])
        self.assertEqual(
            _names([[{"name": "area:ci"}], [{"name": "area:tools"}]], "name"),
            ["area:ci", "area:tools"],
        )

    def test_malformed_payload_raises(self) -> None:
        with self.assertRaises(ValueError):
            _names([{"nope": 1}], "name")
        with self.assertRaises(ValueError):
            _names("area:ci", "name")


class NoMutationTest(unittest.TestCase):
    def test_validation_does_not_mutate_the_intent(self) -> None:
        payload = intent()
        before = copy.deepcopy(payload)

        check(payload)

        self.assertEqual(payload, before)


if __name__ == "__main__":
    unittest.main()
