# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Focused acceptance tests for issue #488 repository hygiene."""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]


def _module():
    """Resolve the producer inside each test so the RED is intentional."""
    return importlib.import_module("scripts.ember_totality.issue488_hygiene")


class Issue488HygieneTests(unittest.TestCase):
    def _fixture(self):
        root = REPO_ROOT / ".issue488-test-fixture"
        shutil.rmtree(root, ignore_errors=True)
        root.mkdir(parents=True)
        for relative, contents in {
            "docs/readme.md": "doc\n",
            "scripts/run.py": "print('run')\n",
            "receipts/canonical.json": "{\"ok\":true}\n",
            "receipts/duplicate.json": "{\"ok\":true}\n",
            "receipts/untracked.json": "scratch\n",
        }.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(contents, encoding="utf-8")
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        return root

    def test_governance_contains_closed_hygiene_law(self):
        text = (REPO_ROOT / "GOVERNANCE.md").read_text(encoding="utf-8")
        for marker in (
            "## Repository hygiene (#488)",
            "HYGIENE_REFERENCE_SCAN",
            "HYGIENE_PROTECTED_EVIDENCE",
            "HYGIENE_NO_PRIVATE_DELETE",
            "HYGIENE_EXPLICIT_APPLY",
            "HYGIENE_MANIFEST_LAST",
            "HYGIENE_PATH_FREE_RECEIPT",
        ):
            self.assertIn(marker, text)

    def test_producer_returns_closed_path_free_manifest(self):
        mod = _module()
        root = self._fixture()
        tracked = ["docs/readme.md", "scripts/run.py", "receipts/canonical.json", "receipts/duplicate.json"]
        with patch.object(mod, "_tracked_paths", return_value=tracked), patch.object(
            mod, "compute_working_set", return_value={"tracked_files": 4}
        ), patch.object(mod, "_git", side_effect=OSError("fixture has no git authority")):
            manifest = mod.build_reference_manifest(root)
        self.assertEqual(manifest["schema_version"], "ember-issue-488-reference-manifest-v1")
        self.assertEqual(set(manifest), {
            "schema_version", "source_commit", "source_clean", "working_set",
            "inventory", "candidates", "manifest_sha256",
        })
        encoded = json.dumps(manifest, sort_keys=True, separators=(",", ":"))
        self.assertNotRegex(encoded, r"[A-Za-z]:[\\/]")
        self.assertNotIn("\\\\", encoded)

    def test_manifest_covers_required_inventory_classes_and_rows(self):
        mod = _module()
        root = self._fixture()
        tracked = ["docs/readme.md", "scripts/run.py", "receipts/canonical.json", "receipts/duplicate.json"]
        with patch.object(mod, "_tracked_paths", return_value=tracked), patch.object(
            mod, "compute_working_set", return_value={"tracked_files": 4}
        ), patch.object(mod, "_git", side_effect=OSError("fixture has no git authority")):
            manifest = mod.build_reference_manifest(root)
        inventory = manifest["inventory"]
        self.assertEqual(set(inventory), {
            "docs", "scripts", "tracked_receipts", "untracked_receipts", "git_packs",
        })
        self.assertTrue(all(isinstance(inventory[name]["count"], int) for name in inventory))
        for row in manifest["candidates"]:
            self.assertEqual(set(row), {
                "path", "kind", "bytes", "sha256", "reference_count", "references",
                "action", "superseded_by", "reason",
            })
            self.assertRegex(row["sha256"], r"^[0-9a-f]{64}$")

    def test_safe_cleanup_refuses_unlisted_or_protected_paths(self):
        mod = _module()
        root = REPO_ROOT / ".issue488-test-refusal"
        shutil.rmtree(root, ignore_errors=True)
        root.mkdir(parents=True)
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        (root / "tracked.txt").write_text("keep", encoding="utf-8")
        manifest = {
            "schema_version": "ember-issue-488-reference-manifest-v1",
            "source_commit": "0" * 40,
            "source_clean": True,
            "working_set": {},
            "inventory": {},
            "candidates": [],
            "manifest_sha256": "0" * 64,
        }
        with self.assertRaises(ValueError):
            mod.apply_safe_cleanup(root, manifest, ["tracked.txt"], root / "receipt.json")

    def test_safe_cleanup_emits_path_free_before_after_receipt_and_rollback_data(self):
        mod = _module()
        root = REPO_ROOT / ".issue488-test-cleanup"
        shutil.rmtree(root, ignore_errors=True)
        root.mkdir(parents=True)
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        target = root / "duplicate.txt"
        target.write_bytes(b"duplicate")
        row = {
            "path": "duplicate.txt",
            "kind": "tracked_receipt",
            "bytes": target.stat().st_size,
            "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            "reference_count": 0,
            "references": [],
            "action": "DELETE_CANDIDATE",
            "superseded_by": "canonical.txt",
            "reason": "byte-identical and unreferenced",
        }
        manifest = {
            "schema_version": "ember-issue-488-reference-manifest-v1",
            "source_commit": "0" * 40,
            "source_clean": True,
            "working_set": {},
            "inventory": {},
            "candidates": [row],
            "manifest_sha256": "0" * 64,
        }
        receipt = root / "receipt.json"
        result = mod.apply_safe_cleanup(root, manifest, [row["path"]], receipt)
        self.assertFalse(target.exists())
        self.assertEqual(result["schema_version"], "ember-issue-488-cleanup-receipt-v1")
        self.assertIn("before", result)
        self.assertIn("after", result)
        self.assertIn("rollback", result)
        encoded = receipt.read_text(encoding="utf-8")
        self.assertNotRegex(encoded, r"[A-Za-z]:[\\/]")


if __name__ == "__main__":
    unittest.main()
