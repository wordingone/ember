# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Behavior tests for the changed-receipt landing gate."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
CHECKER = REPO / "src" / "ember" / "governance" / "scripts" / "check_changed_receipts.py"
INVARIANT = "08a0eb7418c09a8088be4658e10785107abbb7507fc2dbcdc789936aa54e02a6"


class ChangedReceiptGateTests(unittest.TestCase):
    def test_canonical_frozen_policy_layout_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = self.seed(td)
            legacy = root / "tools/frozen-receipt-exceptions.json"
            canonical = root / "src/ember/infrastructure/tools/frozen-receipt-exceptions.json"
            canonical.parent.mkdir(parents=True, exist_ok=True)
            legacy.replace(canonical)
            result = self.run_checker(root)
            self.assertEqual(result.returncode, 0, self.output(result))

    def test_duplicate_frozen_policy_layout_refuses(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = self.seed(td)
            canonical = root / "src/ember/infrastructure/tools/frozen-receipt-exceptions.json"
            canonical.parent.mkdir(parents=True, exist_ok=True)
            canonical.write_bytes((root / "tools/frozen-receipt-exceptions.json").read_bytes())
            result = self.run_checker(root)
            self.assertEqual(result.returncode, 1, self.output(result))
            self.assertIn("exactly one", self.output(result))

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

    def seed(self, td: str, *entries: dict[str, str]) -> Path:
        """Root with a valid frozen-receipt exceptions policy (empty by default).

        The policy is parsed on every run and is fail-closed, so every fixture
        root needs one exactly as a real clone does.
        """
        root = Path(td)
        self.write_json(
            root,
            "src/ember/infrastructure/tools/frozen-receipt-exceptions.json",
            {"schema": "frozen-receipt-exceptions-v1", "entries": list(entries)},
        )
        return root

    def write_json(self, root: Path, relative: str, payload: object) -> None:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    def output(self, result: subprocess.CompletedProcess[bytes]) -> str:
        return (result.stdout + result.stderr).decode(errors="replace")

    def test_rejects_changed_post_genesis_receipt_without_invariant_stamp(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = self.seed(td)
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
            root = self.seed(td)
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
            root = self.seed(td)
            path = root / "receipts" / "broken.json"
            path.parent.mkdir(parents=True)
            path.write_text("{", encoding="utf-8")

            result = self.run_checker(root, "receipts/broken.json")

            self.assertEqual(result.returncode, 1, self.output(result))
            self.assertIn("parse error", self.output(result))

    def test_ignores_non_receipt_paths_and_training_config(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = self.seed(td)
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
            root = self.seed(td)
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
            root = self.seed(td)
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
            root = self.seed(td)
            relative = "receipts/name with spaces.json"
            self.write_json(
                root,
                relative,
                {"ticket": "ISSUE-700", "ts": "2026-07-29T00:00:00Z"},
            )

            result = self.run_checker(root, relative, null_delimited=True)

            self.assertEqual(result.returncode, 1, self.output(result))
            self.assertIn("MISSING_INVARIANT_SHA256", self.output(result))

    def frozen_fixture(self, root: Path) -> tuple[str, str]:
        """Write a floor-violating receipt and return its path and digest."""
        relative = "receipts/frozen/evidence.json"
        self.write_json(root, relative, {"schema": "frozen-v1", "note": "no ticket"})
        digest = hashlib.sha256((root / relative).read_bytes()).hexdigest()
        return relative, digest

    def test_exempts_frozen_evidence_matching_its_recorded_digest(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = self.seed(td)
            relative, digest = self.frozen_fixture(root)
            self.write_json(
                root,
                "src/ember/infrastructure/tools/frozen-receipt-exceptions.json",
                {
                    "schema": "frozen-receipt-exceptions-v1",
                    "entries": [
                        {
                            "path": relative,
                            "sha256": digest,
                            "reason": "frozen evidence copied in verbatim",
                        }
                    ],
                },
            )

            result = self.run_checker(root, relative)

            self.assertEqual(result.returncode, 0, self.output(result))
            self.assertIn("frozen=1", self.output(result))

    def test_rejects_frozen_entry_whose_content_drifted(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = self.seed(td)
            relative, _ = self.frozen_fixture(root)
            self.write_json(
                root,
                "src/ember/infrastructure/tools/frozen-receipt-exceptions.json",
                {
                    "schema": "frozen-receipt-exceptions-v1",
                    "entries": [
                        {
                            "path": relative,
                            "sha256": "0" * 64,
                            "reason": "digest deliberately does not match",
                        }
                    ],
                },
            )

            result = self.run_checker(root, relative)

            self.assertEqual(result.returncode, 1, self.output(result))
            self.assertIn("does not match its recorded digest", self.output(result))

    def test_path_alone_never_exempts_an_unenumerated_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = self.seed(td)
            relative, _ = self.frozen_fixture(root)

            result = self.run_checker(root, relative)

            self.assertEqual(result.returncode, 1, self.output(result))
            self.assertIn("MISSING_REQUIRED", self.output(result))

    def frozen_jsonl_fixture(self, root: Path) -> tuple[str, str]:
        """Write a frozen non-.json ledger and return its path and digest.

        Mirrors receipts/ember-02-launch-authority/declaration-ledger.jsonl
        (issue #1506): a frozen evidence file whose extension is not .json.
        """
        relative = "receipts/frozen/declaration-ledger.jsonl"
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'{"row":1}\n')
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        return relative, digest

    def test_exempts_frozen_non_json_evidence_matching_its_recorded_digest(
        self,
    ) -> None:
        """issue #1506: a frozen .jsonl path is admitted and hash-checked.

        Before this fix, _candidate's .json-only suffix gate dropped every
        .jsonl path before it ever reached the frozen-exceptions lookup, so a
        frozen ledger like declaration-ledger.jsonl was never inspected at
        all -- silently rewriting it would have passed this gate uninspected.
        """
        with tempfile.TemporaryDirectory() as td:
            root = self.seed(td)
            relative, digest = self.frozen_jsonl_fixture(root)
            self.write_json(
                root,
                "src/ember/infrastructure/tools/frozen-receipt-exceptions.json",
                {
                    "schema": "frozen-receipt-exceptions-v1",
                    "entries": [
                        {
                            "path": relative,
                            "sha256": digest,
                            "reason": "frozen declaration ledger copied in verbatim",
                        }
                    ],
                },
            )

            result = self.run_checker(root, relative)

            self.assertEqual(result.returncode, 0, self.output(result))
            self.assertIn("frozen=1", self.output(result))

    def test_rejects_frozen_non_json_entry_whose_content_drifted(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = self.seed(td)
            relative, _ = self.frozen_jsonl_fixture(root)
            self.write_json(
                root,
                "src/ember/infrastructure/tools/frozen-receipt-exceptions.json",
                {
                    "schema": "frozen-receipt-exceptions-v1",
                    "entries": [
                        {
                            "path": relative,
                            "sha256": "0" * 64,
                            "reason": "digest deliberately does not match",
                        }
                    ],
                },
            )

            result = self.run_checker(root, relative)

            self.assertEqual(result.returncode, 1, self.output(result))
            self.assertIn("does not match its recorded digest", self.output(result))

    def test_ignores_unenumerated_jsonl_ledger_outside_the_frozen_policy(
        self,
    ) -> None:
        """A growing .jsonl ledger not named in the frozen policy is still

        skipped entirely, exactly as before this fix -- the .jsonl admission
        path added for issue #1506 is scoped strictly to paths the frozen
        policy enumerates, never to the extension on its own.
        """
        with tempfile.TemporaryDirectory() as td:
            root = self.seed(td)
            relative = "receipts/ledger/episodes.jsonl"
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'{"episode":1}\n')

            result = self.run_checker(root, relative)

            self.assertEqual(result.returncode, 0, self.output(result))
            self.assertIn("CHANGED_RECEIPTS_PASS count=0", self.output(result))

    def test_unusable_exceptions_policy_fails_closed_on_a_clean_run(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "tools").mkdir(parents=True)
            (root / "tools" / "frozen-receipt-exceptions.json").write_text(
                "{", encoding="utf-8"
            )

            result = self.run_checker(root, "README.md")

            self.assertEqual(result.returncode, 1, self.output(result))
            self.assertIn("exceptions policy unusable", self.output(result))

    def test_real_declaration_ledger_is_enumerated_and_matches_its_frozen_digest(
        self,
    ) -> None:
        """issue #1506, against the real tree (not a fixture).

        receipts/ember-02-launch-authority/declaration-ledger.jsonl is a real
        committed evidence-pack file. This proves the production
        frozen-receipt-exceptions.json entry this fix adds actually covers
        it, using the real checker against the real repo root -- the same
        invocation shape tools/repo-guard.sh uses on a changed path.
        """
        relative = "receipts/ember-02-launch-authority/declaration-ledger.jsonl"
        real_path = REPO / relative
        self.assertTrue(real_path.is_file(), real_path)

        result = self.run_checker(REPO, relative)

        self.assertEqual(result.returncode, 0, self.output(result))
        self.assertIn("frozen=1", self.output(result))

    def test_absent_exceptions_policy_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            result = self.run_checker(Path(td), "README.md")

            self.assertEqual(result.returncode, 1, self.output(result))
            self.assertIn("exceptions policy unusable", self.output(result))


if __name__ == "__main__":
    unittest.main()
