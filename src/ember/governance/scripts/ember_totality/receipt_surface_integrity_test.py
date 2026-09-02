#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Regression tests for issue #672 receipt-surface integrity."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.ember.governance.scripts.ember_totality import ember_totality_spec
from scripts.ember_totality import receipt_surface_integrity


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()


class ReceiptSurfaceIntegrityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        _git(self.root, "init")
        _git(self.root, "config", "user.email", "issue672@example.invalid")
        _git(self.root, "config", "user.name", "Issue 672 Test")
        (self.root / "receipts").mkdir()
        (self.root / "receipts" / "tracked.json").write_text(
            '{"status":"kept"}\n', encoding="utf-8"
        )
        (self.root / "docs").mkdir()
        (self.root / "docs" / "tracked.md").write_text("kept\n", encoding="utf-8")
        _git(self.root, "add", ".")
        _git(self.root, "commit", "-m", "fixture")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_deleted_tracked_receipt_refuses_and_writes_receipt_before_board_output(self) -> None:
        (self.root / "receipts" / "tracked.json").unlink()
        refusal_root = self.root / "refusals"
        with self.assertRaisesRegex(
            receipt_surface_integrity.ReceiptSurfaceIntegrityError,
            "TRACKED_RECEIPT_DELETION",
        ):
            receipt_surface_integrity.enforce_board_receipt_surface(
                self.root,
                refusal_root=refusal_root,
            )

        receipts = list(refusal_root.glob("receipt-surface-refusal-*.json"))
        self.assertEqual(len(receipts), 1)
        payload = json.loads(receipts[0].read_text(encoding="utf-8"))
        self.assertEqual(payload["schema_version"], "ember-receipt-surface-refusal-v1")
        self.assertEqual(payload["status"], "REFUSED")
        self.assertEqual(payload["reason_code"], "TRACKED_RECEIPT_DELETION")
        self.assertEqual(payload["deleted_tracked_receipt_paths"], ["receipts/tracked.json"])
        self.assertRegex(payload["run_tree_sha"], r"^[0-9a-f]{40}$")
        self.assertRegex(payload["evidence_sha256"], r"^[0-9a-f]{64}$")
        self.assertNotIn(str(self.root), receipts[0].read_text(encoding="utf-8"))

    def test_non_receipt_deletion_does_not_trigger_receipt_surface_refusal(self) -> None:
        (self.root / "docs" / "tracked.md").unlink()
        result = receipt_surface_integrity.enforce_board_receipt_surface(
            self.root,
            refusal_root=self.root / "refusals",
        )
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["deleted_tracked_receipt_paths"], [])
        self.assertFalse((self.root / "refusals").exists())

    def test_board_main_refuses_before_registry_or_probe_work(self) -> None:
        refusal = receipt_surface_integrity.ReceiptSurfaceIntegrityError(
            "TRACKED_RECEIPT_DELETION"
        )
        argv = [
            "ember_totality_spec.py",
            "--refusal-receipt-dir",
            str(self.root / "refusals"),
        ]
        with (
            mock.patch.object(sys, "argv", argv),
            mock.patch.object(
                ember_totality_spec.receipt_surface_integrity,
                "enforce_board_receipt_surface",
                side_effect=refusal,
            ) as guard,
            mock.patch.object(ember_totality_spec, "registry_sync_check") as registry,
            self.assertRaisesRegex(
                receipt_surface_integrity.ReceiptSurfaceIntegrityError,
                "TRACKED_RECEIPT_DELETION",
            ),
        ):
            ember_totality_spec.main()
        guard.assert_called_once()
        registry.assert_not_called()

    def test_clear_uses_only_explicit_owned_paths_inside_run_tree(self) -> None:
        run_root = self.root / "run"
        run_root.mkdir()
        owned = run_root / "derived.json"
        other = run_root / "keep.json"
        owned.write_text("{}\n", encoding="utf-8")
        other.write_text("{}\n", encoding="utf-8")
        manifest = run_root / "owned-paths.json"
        manifest.write_text(
            json.dumps(
                {
                    "schema_version": "ember-owned-derived-paths-v1",
                    "run_id": "issue-672-test",
                    "owned_paths": ["derived.json"],
                }
            )
            + "\n",
            encoding="utf-8",
        )

        result = receipt_surface_integrity.clear_owned_paths(
            run_root=run_root,
            manifest_path=manifest,
        )
        self.assertEqual(result["cleared_paths"], ["derived.json"])
        self.assertFalse(owned.exists())
        self.assertTrue(other.exists())

    def test_owned_path_manifest_rejects_escape_glob_directory_and_extra_fields(self) -> None:
        run_root = self.root / "run"
        run_root.mkdir()
        cases = [
            {
                "schema_version": "ember-owned-derived-paths-v1",
                "run_id": "escape",
                "owned_paths": ["../outside.json"],
            },
            {
                "schema_version": "ember-owned-derived-paths-v1",
                "run_id": "glob",
                "owned_paths": ["*.json"],
            },
            {
                "schema_version": "ember-owned-derived-paths-v1",
                "run_id": "directory",
                "owned_paths": ["nested"],
            },
            {
                "schema_version": "ember-owned-derived-paths-v1",
                "run_id": "extra",
                "owned_paths": [],
                "unexpected": True,
            },
        ]
        (run_root / "nested").mkdir()
        for index, payload in enumerate(cases):
            manifest = run_root / f"bad-{index}.json"
            manifest.write_text(json.dumps(payload) + "\n", encoding="utf-8")
            with self.subTest(payload=payload), self.assertRaises(
                receipt_surface_integrity.ReceiptSurfaceIntegrityError
            ):
                receipt_surface_integrity.clear_owned_paths(
                    run_root=run_root,
                    manifest_path=manifest,
                )


if __name__ == "__main__":
    unittest.main()
