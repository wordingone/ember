# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import yaml

from scripts.github import policy


ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())


class RepositoryPolicyTests(unittest.TestCase):
    def test_checked_in_label_manifest_is_closed_and_complete(self) -> None:
        result = policy.validate_label_manifest(ROOT / ".github" / "labels.yml")
        self.assertEqual([], result.errors)
        self.assertGreaterEqual(result.details["label_count"], 90)

    def test_checked_in_migrations_cover_every_legacy_label_once(self) -> None:
        migrations = policy.validate_label_migrations(
            ROOT / ".github" / "label-migrations.yml",
            ROOT / ".github" / "labels.yml",
        )
        self.assertEqual([], migrations.errors)
        self.assertEqual(31, migrations.details["migration_count"])

    def test_single_counter_decrement_is_not_a_durable_issue(self) -> None:
        issue = policy.example_issue(
            kind="kind:maintenance",
            outcome="Reduce the open issue counter by one.",
            scope="Close issue #12 without changing its acceptance obligations.",
        )
        result = policy.validate_issue(issue)
        self.assertIn("busywork:counter-decrement", result.errors)

    def test_feature_and_enhancement_are_distinct(self) -> None:
        feature = policy.example_issue(
            kind="kind:feature",
            outcome="Add a new offline checkpoint comparison command.",
            current_state="No such operator command exists.",
            desired_state="The operator can compare two checkpoints offline.",
        )
        enhancement = policy.example_issue(
            kind="kind:enhancement",
            outcome="Reduce existing checkpoint comparison latency.",
            current_state="The command takes 18 seconds on the baseline fixture.",
            desired_state="The same command takes at most 10 seconds.",
            extra={"baseline": "18 seconds", "success_metric": "<=10 seconds"},
        )
        self.assertEqual([], policy.validate_issue(feature).errors)
        self.assertEqual([], policy.validate_issue(enhancement).errors)

    def test_research_and_experiment_are_distinct(self) -> None:
        research = policy.example_issue(
            kind="kind:research",
            outcome="Determine whether routing entropy predicts validation loss.",
            extra={
                "hypothesis": "Lower routing entropy predicts lower held-out loss.",
                "falsification": "No preregistered association at the stated uncertainty.",
            },
        )
        experiment = policy.example_issue(
            kind="kind:experiment",
            outcome="Run the preregistered routing-entropy intervention.",
            extra={
                "treatment": "Entropy penalty enabled.",
                "control": "Matched run without the penalty.",
                "model_identity": "sha256:" + "a" * 64,
                "dataset_identity": "sha256:" + "b" * 64,
                "kill_criteria": "Resource ceiling exceeded.",
            },
        )
        self.assertEqual([], policy.validate_issue(research).errors)
        self.assertEqual([], policy.validate_issue(experiment).errors)

    def test_receipt_rewrap_cannot_masquerade_as_experiment(self) -> None:
        issue = policy.example_issue(
            kind="kind:experiment",
            outcome="Rewrap the existing receipt into a new JSON envelope.",
            extra={
                "treatment": "No new treatment.",
                "control": "No control.",
                "model_identity": "unchanged",
                "dataset_identity": "unchanged",
                "kill_criteria": "none",
            },
        )
        result = policy.validate_issue(issue)
        self.assertIn("busywork:receipt-only-experiment", result.errors)

    def test_homogeneous_repairs_require_batching_rationale(self) -> None:
        pr = policy.example_pr(
            linked_issue="#17",
            outcome="Repair one of twelve identical generated schema defects.",
            coherent_reason="",
        )
        pr["homogeneous_repair_count"] = 12
        result = policy.validate_pull_request(pr)
        self.assertIn("batching:rationale-required", result.errors)

    def test_pr_without_link_or_exception_fails(self) -> None:
        pr = policy.example_pr(linked_issue="", exception="")
        self.assertIn("pr:linked-outcome-required", policy.validate_pull_request(pr).errors)

    def test_closing_pr_without_acceptance_mapping_fails(self) -> None:
        pr = policy.example_pr(linked_issue="Closes #17", acceptance_mapping="")
        self.assertIn(
            "pr:closing-acceptance-mapping-required",
            policy.validate_pull_request(pr).errors,
        )

    def test_trunk_inactivity_is_not_repository_failure(self) -> None:
        health = policy.evaluate_repository_health(
            {"required_checks": "PASS", "trunk_inactive_days": 30}
        )
        self.assertEqual("PASS", health["status"])
        self.assertIn("trunk_inactive_days", health["measurements"])

    def test_unknown_manifest_field_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "labels.yml"
            data = yaml.safe_load((ROOT / ".github" / "labels.yml").read_text("utf-8"))
            data["labels"][0]["surprise"] = True
            path.write_text(json.dumps(data), encoding="utf-8")
            result = policy.validate_label_manifest(path)
            self.assertTrue(any("unknown fields" in e for e in result.errors))


if __name__ == "__main__":
    unittest.main()
