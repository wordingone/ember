#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Regression tests for issue #788 quarantine-blindness hardening."""

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.ember.governance.scripts.ember_totality import quarantine_sweep


def _load_continuity_renderer():
    path = REPO_ROOT / "scripts" / "gen_readme_status.py"
    spec = importlib.util.spec_from_file_location("issue788_gen_readme_status", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class Issue788QuarantineSweepTests(unittest.TestCase):
    def test_exact_suffix_is_detected_but_benign_quarantine_word_is_not(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "receipts").mkdir()
            bad = root / "receipts" / "c12.json.INVALID.quarantine"
            bad.write_text(json.dumps({"condition": "C12"}), encoding="utf-8")
            (root / "receipts" / "A1-prefreeze-quarantine-register.json").write_text(
                "{}", encoding="utf-8"
            )

            findings = quarantine_sweep.discover_quarantines(
                [("receipts", root / "receipts")]
            )

        self.assertEqual(1, len(findings))
        self.assertEqual("receipts/c12.json.INVALID.quarantine", findings[0]["path"])
        self.assertEqual("C12", findings[0]["condition_hint"])

    def test_targeted_quarantine_demotes_only_its_consuming_state_condition(self):
        rows = [
            {"condition": "C0", "status": "AUDIT-OK", "reason": "clean"},
            {"condition": "C12", "status": "GREEN", "reason": "old receipt"},
            {"condition": "C14", "status": "GREEN", "reason": "fresh receipt"},
        ]
        findings = [
            {
                "path": "receipts/c12.json.INVALID.quarantine",
                "condition_hint": "C12",
            }
        ]

        quarantine_sweep.apply_quarantine_flags(rows, findings, {"C0", "C9", "C15"})

        by_condition = {row["condition"]: row for row in rows}
        self.assertEqual("UNEVALUABLE", by_condition["C12"]["status"])
        self.assertIn("INVALID.quarantine", by_condition["C12"]["reason"])
        self.assertEqual("GREEN", by_condition["C14"]["status"])
        self.assertEqual("AUDIT-OK", by_condition["C0"]["status"])

    def test_same_physical_root_is_not_counted_twice_under_overlapping_labels(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            bad = root / "same.json.INVALID.quarantine"
            bad.write_text(json.dumps({"condition": "C12"}), encoding="utf-8")

            findings = quarantine_sweep.discover_quarantines(
                [("receipts", root), ("artifact-receipts", root)]
            )

        self.assertEqual(1, len(findings))

    def test_unattributed_quarantine_becomes_c0_audit_incident(self):
        rows = [
            {"condition": "C0", "status": "AUDIT-OK", "reason": "clean"},
            {"condition": "C12", "status": "GREEN", "reason": "fresh"},
        ]
        findings = [
            {
                "path": "staging/unknown.INVALID.quarantine",
                "condition_hint": None,
            }
        ]

        quarantine_sweep.apply_quarantine_flags(rows, findings, {"C0", "C9", "C15"})

        self.assertEqual("AUDIT-INCIDENT", rows[0]["status"])
        self.assertIn("unattributed", rows[0]["reason"])
        self.assertEqual("GREEN", rows[1]["status"])

    def test_renderer_refuses_stale_fallback_when_exact_suffix_exists(self):
        renderer = _load_continuity_renderer()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            normal = root / "ember-totality-20990101T000000Z.json"
            normal.write_text("{}", encoding="utf-8")
            (root / "ember-totality-20990102T000000Z.json.INVALID.quarantine").write_text(
                "{}", encoding="utf-8"
            )

            with self.assertRaises(SystemExit) as caught:
                renderer.newest_receipt_path(str(root))

        self.assertIn("INVALID.quarantine", str(caught.exception))

    def test_renderer_ignores_benign_filename_containing_quarantine_word(self):
        renderer = _load_continuity_renderer()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            normal = root / "ember-totality-20990101T000000Z.json"
            normal.write_text("{}", encoding="utf-8")
            (root / "A1-prefreeze-quarantine-register.json").write_text(
                "{}", encoding="utf-8"
            )

            selected = renderer.newest_receipt_path(str(root))

        self.assertEqual(str(normal), selected)


if __name__ == "__main__":
    unittest.main()
