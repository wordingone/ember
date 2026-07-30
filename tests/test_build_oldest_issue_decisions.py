# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Tests for source-complete classification expansion."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_oldest_issue_disposition import MASTER, _raw_capture

from scripts.build_oldest_issue_decisions import (
    PacketError,
    build_decisions,
)
from scripts.oldest_issue_disposition import (
    build_capture,
    build_packet,
)


def _classifications(capture: dict) -> dict:
    return {
        "schema_version": "ember-oldest-issue-classifications-v1",
        "expected_issue_numbers": [
            issue["number"] for issue in capture["issues"]
        ],
        "rows": [
            {
                "issue_number": issue["number"],
                "disposition": "PARTIAL",
                "unbound_description": f"unbound {issue['number']}",
                "smallest_binding_action": f"bind {issue['number']}",
                "replacement_citation": None,
                "retained_lesson": None,
            }
            for issue in capture["issues"]
        ],
    }


class BuildOldestIssueDecisionsTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        _raw_capture(root)
        self.capture = build_capture(
            root,
            master_sha=MASTER,
            captured_at="2026-07-25T00:00:00Z",
        )

    def test_expands_every_body_and_comment_source_once(self) -> None:
        decisions = build_decisions(
            self.capture,
            _classifications(self.capture),
        )
        packet = build_packet(self.capture, decisions)
        self.assertEqual(len(packet["receipts"]), 20)
        self.assertEqual(
            len(packet["receipts"][0]["source_clause_inventory"]),
            2,
        )

    def test_rejects_live_selection_drift_and_close_generation(self) -> None:
        classifications = _classifications(self.capture)
        classifications["expected_issue_numbers"][0] = 999
        with self.assertRaisesRegex(PacketError, "live selection"):
            build_decisions(self.capture, classifications)

        classifications = _classifications(self.capture)
        classifications["rows"][0]["disposition"] = "CLOSE"
        with self.assertRaisesRegex(PacketError, "cannot generate CLOSE"):
            build_decisions(self.capture, classifications)

    def test_rejects_missing_duplicate_or_incompatible_rows(self) -> None:
        classifications = _classifications(self.capture)
        classifications["rows"].pop()
        with self.assertRaisesRegex(PacketError, "selection"):
            build_decisions(self.capture, classifications)

        classifications = _classifications(self.capture)
        classifications["rows"][1]["issue_number"] = (
            classifications["rows"][0]["issue_number"]
        )
        with self.assertRaisesRegex(PacketError, "duplicate"):
            build_decisions(self.capture, classifications)

        classifications = _classifications(self.capture)
        classifications["rows"][0]["replacement_citation"] = "issue:1"
        with self.assertRaisesRegex(PacketError, "incompatible"):
            build_decisions(self.capture, classifications)

    def test_decision_builder_accepts_final_partial_batch(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        _raw_capture(root, issue_count=3)
        capture = build_capture(
            root,
            master_sha=MASTER,
            captured_at="2026-07-25T00:00:00Z",
        )
        decisions = build_decisions(capture, _classifications(capture))
        packet = build_packet(capture, decisions)
        self.assertEqual(len(decisions["rows"]), 3)
        self.assertEqual(len(packet["receipts"]), 3)
