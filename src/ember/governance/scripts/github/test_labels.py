# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from scripts.github import labels


ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())


def snapshot() -> dict:
    return {
        "schema_version": "ember-github-label-snapshot/v1",
        "repository": "wordingone/ember",
        "captured_at": "2026-07-29T00:00:00Z",
        "labels": [
            {"name": "bug", "color": "d73a4a", "description": "old"},
            {"name": "auto-merge-ok", "color": "0E8A16", "description": "old"},
            {"name": "question", "color": "d876e3", "description": "old"},
        ],
        "items": [
            {
                "number": 1,
                "node_id": "I_1",
                "item_type": "issue",
                "state": "OPEN",
                "title": "title must not drive migration",
                "labels": ["bug"],
            },
            {
                "number": 2,
                "node_id": "PR_2",
                "item_type": "pull_request",
                "state": "CLOSED",
                "title": "also ignored",
                "labels": ["auto-merge-ok"],
            },
        ],
    }


class LabelMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = labels.load_data(ROOT / ".github" / "labels.yml")
        self.migrations = labels.load_data(ROOT / ".github" / "label-migrations.yml")

    def test_plan_is_deterministic_and_content_addressed(self) -> None:
        first = labels.build_plan(snapshot(), self.manifest, self.migrations)
        second = labels.build_plan(snapshot(), self.manifest, self.migrations)
        self.assertEqual(first, second)
        self.assertEqual(labels.canonical_sha256(first["plan"]), first["plan_sha256"])
        self.assertNotIn("title", json.dumps(first["plan"]))

    def test_deterministic_renames_preserve_associations(self) -> None:
        plan = labels.build_plan(snapshot(), self.manifest, self.migrations)
        changes = {
            (row["item_type"], row["number"]): row
            for row in plan["plan"]["item_label_changes"]
        }
        self.assertEqual(["kind:defect"], changes[("issue", 1)]["add"])
        self.assertEqual(["bug"], changes[("issue", 1)]["remove"])
        self.assertEqual(
            ["merge:auto-approved"], changes[("pull_request", 2)]["add"]
        )

    def test_unknown_live_label_fails_closed(self) -> None:
        data = snapshot()
        data["labels"].append(
            {"name": "mystery", "color": "ffffff", "description": "unknown"}
        )
        data["items"][0]["labels"].append("mystery")
        with self.assertRaises(labels.MigrationError):
            labels.build_plan(data, self.manifest, self.migrations)

    def test_ambiguous_historical_mapping_is_never_inferred_from_title(self) -> None:
        data = snapshot()
        data["labels"].append(
            {"name": "roadmap:historical", "color": "000000", "description": ""}
        )
        data["items"][0]["labels"] = ["roadmap:historical"]
        plan = labels.build_plan(data, self.manifest, self.migrations)
        issue_changes = [
            row
            for row in plan["plan"]["item_label_changes"]
            if row["item_type"] == "issue" and row["number"] == 1
        ]
        self.assertEqual([], issue_changes)
        self.assertEqual(1, len(plan["plan"]["manual_judgment_required"]))

    def test_delete_is_refused_while_label_remains_in_use(self) -> None:
        data = snapshot()
        data["items"][0]["labels"] = ["question"]
        with self.assertRaises(labels.MigrationError):
            labels.build_plan(data, self.manifest, self.migrations)

    def test_snapshot_digest_detects_mutation(self) -> None:
        data = snapshot()
        digest = labels.canonical_sha256(data)
        mutated = copy.deepcopy(data)
        mutated["items"][0]["labels"].append("question")
        self.assertNotEqual(digest, labels.canonical_sha256(mutated))

    def test_apply_defaults_to_dry_run(self) -> None:
        plan = labels.build_plan(snapshot(), self.manifest, self.migrations)
        client = labels.RecordingClient()
        receipt = labels.apply_plan(plan, client=client, apply=False)
        self.assertEqual([], client.calls)
        self.assertEqual("DRY_RUN", receipt["result"]["mode"])

    def test_apply_requires_exact_before_snapshot_digest(self) -> None:
        plan = labels.build_plan(snapshot(), self.manifest, self.migrations)
        plan["before_snapshot_sha256"] = "0" * 64
        with self.assertRaises(labels.MigrationError):
            labels.apply_plan(
                plan,
                client=labels.RecordingClient(),
                apply=True,
                current_snapshot=snapshot(),
            )


if __name__ == "__main__":
    unittest.main()
