#!/usr/bin/env python3
"""Unit tests for compute_working_set() (docs/authority/GOVERNANCE.md §9 / issue #488).

Covers:
- The field appears on a real repo root with plausible (internally
  consistent, non-negative) values.
- gh unavailability / a bad root degrades to None fields, never raises.
"""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, REPO_ROOT)

from scripts.ember_totality.ember_totality_spec import compute_working_set


class TestWorkingSet(unittest.TestCase):
    """Unit tests for the repo hygiene working-set metric."""

    def test_shape_and_plausible_values_on_real_repo(self):
        """Against the real repo root, every key is present and plausible."""
        ws = compute_working_set(REPO_ROOT)

        expected_keys = {
            "tracked_files",
            "docs_files",
            "scripts_files",
            "tracked_receipts",
            "untracked_receipts_on_disk",
            "open_issues_count",
        }
        self.assertEqual(set(ws.keys()), expected_keys)

        # git is available in this environment, so the git-derived counts
        # must be real non-negative ints, not None.
        for key in ("tracked_files", "docs_files", "scripts_files",
                    "tracked_receipts", "untracked_receipts_on_disk"):
            self.assertIsInstance(ws[key], int, f"{key} should be an int")
            self.assertGreaterEqual(ws[key], 0, f"{key} should be >= 0")

        # Internal plausibility: subset counts never exceed the total.
        self.assertLessEqual(ws["docs_files"], ws["tracked_files"])
        self.assertLessEqual(ws["scripts_files"], ws["tracked_files"])
        self.assertLessEqual(ws["tracked_receipts"], ws["tracked_files"])

        # This repo really has docs/ and scripts/ trees with files in them.
        self.assertGreater(ws["docs_files"], 0)
        self.assertGreater(ws["scripts_files"], 0)

        # open_issues_count is gh-dependent: either a non-negative int, or
        # None (gh not installed / no network / repo not recognized).
        self.assertTrue(
            ws["open_issues_count"] is None or
            (isinstance(ws["open_issues_count"], int) and ws["open_issues_count"] >= 0)
        )

    def test_bad_root_degrades_to_none_without_raising(self):
        """A nonexistent root never raises; git-derived fields fall back to None."""
        bogus_root = os.path.join(REPO_ROOT, "no-such-dir-for-working-set-test")
        ws = compute_working_set(bogus_root)

        self.assertIsNone(ws["tracked_files"])
        self.assertIsNone(ws["docs_files"])
        self.assertIsNone(ws["scripts_files"])
        self.assertIsNone(ws["tracked_receipts"])
        self.assertIsNone(ws["untracked_receipts_on_disk"])
        # gh's own repo resolution is independent of this bogus root, so
        # open_issues_count is only constrained to the same int-or-None shape.
        self.assertTrue(
            ws["open_issues_count"] is None or isinstance(ws["open_issues_count"], int)
        )

    def test_default_repo_root_when_omitted(self):
        """Omitting repo_root falls back to REPO_ROOT and still returns the shape."""
        ws = compute_working_set()
        self.assertIsInstance(ws["tracked_files"], int)
        self.assertGreater(ws["tracked_files"], 0)


if __name__ == "__main__":
    unittest.main()
