# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Behavior tests for the changed-receipt landing gate."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
CHECKER = REPO / "scripts" / "check_changed_receipts.py"
INVARIANT = "08a0eb7418c09a8088be4658e10785107abbb7507fc2dbcdc789936aa54e02a6"


class ChangedReceiptGateTests(unittest.TestCase):
    def run_checker(
        self, root: Path, *paths: str, null_delimited: bool = False
    ) -> subprocess.CompletedProcess[bytes]:
        argv = [sys.executable, "-B", str(CHECKER), "--root", str(root)]
        if null_delimited:
            argv.append("--null")
        data = (
            ("\0".join(paths) + "\0").encode()
            if null_delimited
            else ("\n".join(paths) + "\n").encode()
        )
        return subprocess.run(
            argv,
            input=data,
            capture_output=True,
            check=False,
        )

    def write_json(self, root: Path, relative: str, payload: object) -> None:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    def output(self, result: subprocess.CompletedProcess[bytes]) -> str:
        return (result.stdout + result.stderr).decode(errors="replace")

    def test_rejects_changed_post_genesis_receipt_without_invariant_stamp(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.write_json(
                root,
                "receipts/new.json",
                {"ticket": "ISSUE-700", "ts": "2026-07-29T00:00:00Z"},
            )

            result = self.run_checker(root, "receipts/new.json")

            self.assertEqual(result.returncode, 1, self.output(result))
            self.assertIn("MISSING_INVARIANT_SHA256", self.output(result))

    def test_accepts_changed_receipt_with_correct_invariant_stamp(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.write_json(
                root,
                "receipts/nested/new.json",
                {
                    "ticket": "ISSUE-700",
                    "ts": "2026-07-29T00:00:00Z",
                    "invariant_sha256": INVARIANT,
                    "sha_convention": "bytes on disk as-is",
                },
            )

            result = self.run_checker(root, "receipts/nested/new.json")

            self.assertEqual(result.returncode, 0, self.output(result))
            self.assertIn("CHANGED_RECEIPTS_PASS count=1", self.output(result))

    def test_rejects_malformed_changed_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "receipts" / "broken.json"
            path.parent.mkdir(parents=True)
            path.write_text("{", encoding="utf-8")

            result = self.run_checker(root, "receipts/broken.json")

            self.assertEqual(result.returncode, 1, self.output(result))
            self.assertIn("parse error", self.output(result))

    def test_ignores_non_receipt_paths_and_training_config(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.write_json(root, "receipts/train_config.json", {"batch_size": 1})
            (root / "README.md").write_text("not a receipt\n", encoding="utf-8")

            result = self.run_checker(
                root,
                "README.md",
                "receipts/train_config.json",
                "receipts/deleted.json",
            )

            self.assertEqual(result.returncode, 0, self.output(result))
            self.assertIn("CHANGED_RECEIPTS_PASS count=0", self.output(result))

    def test_validates_approved_disposition_packet_with_native_schema(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = (
                REPO
                / "receipts"
                / "oldest-issue-disposition"
                / "ember-oldest-issue-disposition-015-packet-v1.json"
            )
            relative = (
                "receipts/oldest-issue-disposition/approved/batch-015.json"
            )
            self.write_json(
                root,
                relative,
                json.loads(source.read_text(encoding="utf-8")),
            )

            result = self.run_checker(root, relative)

            self.assertEqual(result.returncode, 0, self.output(result))
            self.assertIn("CHANGED_RECEIPTS_PASS count=1", self.output(result))

    def test_rejects_malformed_approved_disposition_packet(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            relative = (
                "receipts/oldest-issue-disposition/approved/broken.json"
            )
            self.write_json(
                root,
                relative,
                {"master_sha": "0" * 40, "packet_sha256": "1" * 64},
            )

            result = self.run_checker(root, relative)

            self.assertEqual(result.returncode, 1, self.output(result))
            self.assertIn(
                "approved disposition packet validation failed",
                self.output(result),
            )

    def test_null_delimited_input_preserves_space_bearing_receipt_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            relative = "receipts/name with spaces.json"
            self.write_json(
                root,
                relative,
                {"ticket": "ISSUE-700", "ts": "2026-07-29T00:00:00Z"},
            )

            result = self.run_checker(root, relative, null_delimited=True)

            self.assertEqual(result.returncode, 1, self.output(result))
            self.assertIn("MISSING_INVARIANT_SHA256", self.output(result))


if __name__ == "__main__":
    unittest.main()
