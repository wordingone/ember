# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.ember.governance.src.ember.governance.scripts.github.labels_engine import canonical_bytes
from src.ember.governance.scripts.github.work_items import WorkItemError, apply_plan, apply_semantic_reviews, main
from scripts.github import work_items_engine as engine


class SemanticWorkItemTests(unittest.TestCase):
    def _plan(self) -> dict:
        return {
            "authority": {
                "goal_id": "EMBER-02",
                "workstream_id": "EMBER-02A",
                "next_executed_outcome": "owned 3B checkpoint",
            },
            "repository": "wordingone/ember",
            "source_snapshot_sha256": "a" * 64,
            "rows": [
                {
                    "number": 286,
                    "title_sha256": "b" * 64,
                    "body_sha256": "c" * 64,
                    "comments_sha256": "d" * 64,
                    "desired_labels": [
                        "kind:defect",
                        "area:cockpit",
                        "state:triage",
                        "needs:review",
                    ],
                    "review_status": "MACHINE_CLASSIFIED",
                    "classification_basis": "machine proposal only",
                }
            ],
            "coverage": {"open_issue_count": 1, "reviewed_issue_count": 0},
        }

    def _reviews(self) -> dict:
        return {
            "schema_version": "ember-priority-semantic-review/v2",
            "repository": "wordingone/ember",
            "source_snapshot_sha256": "a" * 64,
            "reviewer_identity": (
                "codex-thread:00000000-0000-0000-0000-000000000001"
            ),
            "reviewed_at": "2026-07-29T00:00:00Z",
            "rows": [
                {
                    "number": 286,
                    "title_sha256": "b" * 64,
                    "body_sha256": "c" * 64,
                    "comments_sha256": "d" * 64,
                    "desired_labels": [
                        "kind:defect",
                        "area:cockpit",
                        "state:ready",
                        "priority:p2",
                        "severity:s3",
                    ],
                    "classification_basis": (
                        "UI layout/rendering defect; no security, data-loss, or "
                        "model-integrity impact is alleged."
                    ),
                }
            ],
        }

    def test_semantic_review_binds_reviewer_snapshot_and_full_source(self) -> None:
        result = apply_semantic_reviews(self._plan(), self._reviews())
        row = result["rows"][0]
        self.assertEqual("SEMANTICALLY_REVIEWED", row["review_status"])
        self.assertEqual(
            "codex-thread:00000000-0000-0000-0000-000000000001",
            row["reviewer_identity"],
        )
        self.assertEqual("a" * 64, row["review_source_snapshot_sha256"])
        self.assertIn("severity:s3", row["desired_labels"])
        self.assertNotIn("needs:review", row["desired_labels"])
        self.assertEqual(1, result["coverage"]["reviewed_issue_count"])

    def test_semantic_plan_digest_matches_apply_contract(self) -> None:
        result = apply_semantic_reviews(self._plan(), self._reviews())
        expected = engine._sha(
            {
                key: value
                for key, value in result.items()
                if key not in {"authority", "plan_sha256"}
            }
        )
        self.assertEqual(expected, result["plan_sha256"])

    def test_noop_apply_emits_receipt_without_live_mutation(self) -> None:
        plan = self._plan()
        row = plan["rows"][0]
        row.update(
            {
                "before_labels": sorted(row["desired_labels"]),
                "node_id": "I_286",
                "primary_milestone": "EMBER-03",
            }
        )
        live = {
            "repository": "wordingone/ember",
            "open_items": [
                {
                    "item_type": "issue",
                    "number": 286,
                    "node_id": "I_286",
                    "title": "ignored because test patches hashes below",
                    "body": "",
                    "comments": [],
                    "labels": list(row["before_labels"]),
                    "milestone": "EMBER-03",
                }
            ],
        }
        row["title_sha256"] = engine._sha(live["open_items"][0]["title"])
        row["body_sha256"] = hashlib.sha256(b"").hexdigest()
        row["comments_sha256"] = hashlib.sha256(b"").hexdigest()
        plan["plan_sha256"] = engine._sha(
            {
                key: value
                for key, value in plan.items()
                if key not in {"authority", "plan_sha256"}
            }
        )
        with mock.patch("src.ember.governance.scripts.github.work_items.engine.apply_plan") as mutation:
            receipt = apply_plan(
                plan, live_snapshot=live, wrapper=Path("unused.ps1"), confirm=True
            )
        mutation.assert_not_called()
        self.assertEqual("APPLIED_NO_CHANGES", receipt["status"])
        self.assertEqual(1, receipt["verified_issue_count"])

    def test_review_source_or_row_hash_drift_fails_closed(self) -> None:
        for field, value in (
            ("source_snapshot_sha256", "f" * 64),
            ("repository", "other/repo"),
        ):
            reviews = self._reviews()
            reviews[field] = value
            with self.subTest(field=field), self.assertRaises(WorkItemError):
                apply_semantic_reviews(self._plan(), reviews)
        reviews = self._reviews()
        reviews["rows"][0]["body_sha256"] = "f" * 64
        with self.assertRaises(WorkItemError):
            apply_semantic_reviews(self._plan(), reviews)

    def test_semantic_review_rejects_duplicate_or_invalid_label_cardinality(self) -> None:
        reviews = self._reviews()
        reviews["rows"].append(copy.deepcopy(reviews["rows"][0]))
        with self.assertRaises(WorkItemError):
            apply_semantic_reviews(self._plan(), reviews)
        reviews = self._reviews()
        reviews["rows"][0]["desired_labels"].append("severity:s0")
        with self.assertRaises(WorkItemError):
            apply_semantic_reviews(self._plan(), reviews)

    def test_plan_cli_applies_content_bound_semantic_review_overlay(self) -> None:
        snapshot = {
            "schema_version": "ember-github-snapshot/v1",
            "repository": "wordingone/ember",
            "public_master_sha": "f" * 40,
            "captured_at": "2026-07-29T00:00:00Z",
            "open_items": [
                {
                    "item_type": "issue",
                    "number": 286,
                    "node_id": "I_286",
                    "title": "Layout corruption",
                    "body": (
                        "Cockpit border layout breaks in the narrow terminal. "
                        "Reproduce at 60 columns; expected panes remain bounded."
                    ),
                    "comments": [],
                    "labels": [],
                    "milestone": "EMBER-03",
                    "author": "operator",
                }
            ],
            "branches": [],
            "workflows": [],
            "snapshot_sha256": "a" * 64,
        }
        manifest = {
            "schema_version": "ember-label-manifest/v1",
            "repository": "wordingone/ember",
            "labels": [
                {"name": name, "color": "000000", "description": name}
                for name in (
                    "kind:defect",
                    "area:cockpit",
                    "state:triage",
                    "state:ready",
                    "priority:p2",
                    "severity:s3",
                    "needs:review",
                )
            ],
        }
        reviews = self._reviews()
        issue = snapshot["open_items"][0]
        reviews["rows"][0]["title_sha256"] = hashlib.sha256(
            canonical_bytes(issue["title"])
        ).hexdigest()
        reviews["rows"][0]["body_sha256"] = hashlib.sha256(
            issue["body"].encode()
        ).hexdigest()
        reviews["rows"][0]["comments_sha256"] = hashlib.sha256(b"").hexdigest()
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            paths = {
                "snapshot": root / "snapshot.json",
                "manifest": root / "labels.json",
                "reviews": root / "reviews.json",
                "output": root / "plan.json",
            }
            for key, value in (
                ("snapshot", snapshot),
                ("manifest", manifest),
                ("reviews", reviews),
            ):
                paths[key].write_bytes(canonical_bytes(value) + b"\n")
            self.assertEqual(
                0,
                main(
                    [
                        "plan",
                        "--snapshot",
                        str(paths["snapshot"]),
                        "--manifest",
                        str(paths["manifest"]),
                        "--semantic-reviews",
                        str(paths["reviews"]),
                        "--output",
                        str(paths["output"]),
                    ]
                ),
            )
            result = json.loads(paths["output"].read_text(encoding="utf-8"))
            self.assertEqual(
                "SEMANTICALLY_REVIEWED", result["rows"][0]["review_status"]
            )


if __name__ == "__main__":
    unittest.main()
