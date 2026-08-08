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
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]


def _module():
    """Resolve the producer inside each test so the RED is intentional."""
    return importlib.import_module("scripts.ember_totality.issue488_hygiene")


def _seal_manifest(mod, manifest):
    body = dict(manifest)
    body.pop("manifest_sha256", None)
    manifest["manifest_sha256"] = mod._sha256_bytes(mod._canonical(body))
    return manifest


def _seal_receipt(mod, receipt):
    body = dict(receipt)
    body.pop("receipt_sha256", None)
    receipt["receipt_sha256"] = mod._sha256_bytes(mod._canonical(body))
    return receipt


def _empty_inventory(mod):
    digest = mod._sha256_bytes(mod._canonical([]))
    return {
        name: {"count": 0, "bytes": 0, "sha256": digest}
        for name in ("docs", "scripts", "tracked_receipts", "untracked_receipts", "git_packs")
    }


def _fixture_git(_root, *args):
    if args == ("rev-parse", "HEAD"):
        return "0" * 40
    if args == ("status", "--porcelain"):
        return ""
    raise OSError("isolated fixture has no repository root")


class Issue488HygieneTests(unittest.TestCase):
    def _fixture(self):
        root = Path(tempfile.mkdtemp(prefix="issue488-fixture-", dir=os.environ.get("TEMP") or os.environ.get("TMP")))
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
            "HYGIENE_DOC_SUPERSESSION",
            "HYGIENE_RECEIPT_RETENTION",
            "HYGIENE_SCRIPT_TAXONOMY",
            "HYGIENE_ISSUE_CADENCE",
            "HYGIENE_TREND_WINCE",
            "HYGIENE_CARRIER_DISCIPLINE",
            "HYGIENE_ENG_SYNC_TALLY",
            "HYGIENE_RECEIPT_ATOMICITY",
            "HYGIENE_LEDGER_ARCHIVE",
            "HYGIENE_DISPATCH_EQUIVALENCE",
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
            "policy", "inventory", "candidates", "selected_cleanup", "completed_cleanup", "manifest_sha256",
        })
        self.assertTrue(manifest["policy"]["first_bounded_cleanup_pass"])
        self.assertEqual(manifest["policy"]["canonical_carrier"], "GOVERNANCE.md")
        self.assertTrue(manifest["policy"]["remaining_cadence_transferred"])
        self.assertIn("5101881455", manifest["policy"]["transfer_basis"])
        encoded = json.dumps(manifest, sort_keys=True, separators=(",", ":"))
        self.assertNotRegex(encoded, r"(?<![A-Za-z])[A-Za-z]:[\\/]")
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

    def test_checked_in_manifest_and_receipt_bind_full_cadence_policy(self):
        mod = _module()
        manifest = json.loads(
            (REPO_ROOT / "docs/hygiene/issue-488-reference-manifest-v1.json").read_text(
                encoding="utf-8"
            )
        )
        receipt = json.loads(
            (REPO_ROOT / "receipts/hygiene/issue-488-first-cleanup-v1.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(manifest["policy"], mod._policy_contract())
        self.assertEqual(receipt["policy"], manifest["policy"])
        self.assertEqual(receipt["manifest_sha256"], manifest["manifest_sha256"])
        self.assertEqual(
            receipt["cleanup_scope"],
            {
                "kind": "first_bounded_cleanup_pass",
                "canonical_carrier": "GOVERNANCE.md",
                "remaining_cadence_transferred": True,
                "transfer_basis": "https://github.com/wordingone/ember/issues/488#issuecomment-5101881455",
            },
        )

    def test_safe_cleanup_refuses_unlisted_or_protected_paths(self):
        mod = _module()
        root = Path(tempfile.mkdtemp(prefix="issue488-refusal-", dir=os.environ.get("TEMP") or os.environ.get("TMP")))
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        (root / "tracked.txt").write_text("keep", encoding="utf-8")
        manifest = _seal_manifest(mod, {
            "schema_version": "ember-issue-488-reference-manifest-v1",
            "source_commit": "0" * 40,
            "source_clean": True,
            "working_set": {},
            "inventory": _empty_inventory(mod),
            "candidates": [],
            "selected_cleanup": [],
            "completed_cleanup": [],
            "policy": mod._policy_contract(),
            "manifest_sha256": "0" * 64,
        })
        with patch.object(mod, "_git", side_effect=_fixture_git):
            with self.assertRaises(ValueError):
                mod.apply_safe_cleanup(root, manifest, ["tracked.txt"], root / "receipt.json")

    def test_safe_cleanup_emits_path_free_before_after_receipt_and_rollback_data(self):
        mod = _module()
        root = Path(tempfile.mkdtemp(prefix="issue488-cleanup-", dir=os.environ.get("TEMP") or os.environ.get("TMP")))
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        target = root / "duplicate.txt"
        (root / "canonical.txt").write_bytes(b"duplicate")
        target.write_bytes(b"duplicate")
        row = {
            "path": "duplicate.txt",
            "kind": "tracked_duplicate",
            "bytes": target.stat().st_size,
            "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            "reference_count": 0,
            "references": [],
            "action": "DELETE_CANDIDATE",
            "superseded_by": "canonical.txt",
            "reason": "byte-identical and unreferenced",
        }
        manifest = _seal_manifest(mod, {
            "schema_version": "ember-issue-488-reference-manifest-v1",
            "source_commit": "0" * 40,
            "source_clean": True,
            "working_set": {},
            "inventory": _empty_inventory(mod),
            "candidates": [row],
            "selected_cleanup": [],
            "completed_cleanup": [],
            "policy": mod._policy_contract(),
            "manifest_sha256": "0" * 64,
        })
        receipt = root / "receipt.json"
        with patch.object(mod, "_git", side_effect=_fixture_git):
            result = mod.apply_safe_cleanup(root, manifest, [row["path"]], receipt)
        self.assertFalse(target.exists())
        self.assertEqual(result["schema_version"], "ember-issue-488-cleanup-receipt-v1")
        self.assertEqual(result["cleanup_scope"]["kind"], "first_bounded_cleanup_pass")
        self.assertEqual(result["cleanup_scope"]["canonical_carrier"], "GOVERNANCE.md")
        self.assertTrue(result["cleanup_scope"]["remaining_cadence_transferred"])
        self.assertIn("before", result)
        self.assertIn("after", result)
        self.assertIn("rollback", result)
        encoded = receipt.read_text(encoding="utf-8")
        self.assertNotRegex(encoded, r"(?<![A-Za-z])[A-Za-z]:[\\/]")
        target.write_bytes(b"duplicate")
        with patch.object(mod, "_git", side_effect=_fixture_git):
            with self.assertRaises(ValueError):
                mod.apply_safe_cleanup(root, manifest, [row["path"]], receipt)
        self.assertTrue(target.exists())

    def test_cleanup_rejects_manifest_hash_and_action_tamper_before_mutation(self):
        mod = _module()
        root = Path(tempfile.mkdtemp(prefix="issue488-tamper-", dir=os.environ.get("TEMP") or os.environ.get("TMP")))
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        target = root / "duplicate.txt"
        target.write_bytes(b"duplicate")
        row = {
            "path": "duplicate.txt",
            "kind": "tracked_duplicate",
            "bytes": target.stat().st_size,
            "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            "reference_count": 0,
            "references": [],
            "action": "DELETE_CANDIDATE",
            "superseded_by": "canonical.txt",
            "reason": "byte-identical and unreferenced",
        }
        canonical = root / "canonical.txt"
        canonical.write_bytes(b"duplicate")
        manifest = _seal_manifest(mod, {
            "schema_version": "ember-issue-488-reference-manifest-v1",
            "source_commit": "0" * 40,
            "source_clean": True,
            "working_set": {},
            "inventory": _empty_inventory(mod),
            "candidates": [row],
            "selected_cleanup": [],
            "completed_cleanup": [],
            "policy": mod._policy_contract(),
            "manifest_sha256": "0" * 64,
        })
        receipt = root / "receipt.json"
        tampered_hash = dict(manifest)
        tampered_hash["manifest_sha256"] = "0" * 64
        with patch.object(mod, "_git", side_effect=_fixture_git):
            with self.assertRaises(ValueError):
                mod.apply_safe_cleanup(root, tampered_hash, [row["path"]], receipt)
        tampered_action = json.loads(json.dumps(manifest))
        tampered_action["candidates"][0]["action"] = "PROTECTED_EVIDENCE"
        tampered_action = _seal_manifest(mod, tampered_action)
        with patch.object(mod, "_git", side_effect=_fixture_git):
            with self.assertRaises(ValueError):
                mod.apply_safe_cleanup(root, tampered_action, [row["path"]], receipt)
        self.assertTrue(target.exists())

    def test_cleanup_recomputes_references_and_rejects_rehashed_protected_row(self):
        mod = _module()
        root = Path(tempfile.mkdtemp(prefix="issue488-recompute-", dir=os.environ.get("TEMP") or os.environ.get("TMP")))
        (root / "docs").mkdir(parents=True)
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        (root / "receipts").mkdir()
        target = root / "receipts" / "duplicate.txt"
        canonical = root / "receipts" / "canonical.txt"
        target.write_bytes(b"duplicate")
        canonical.write_bytes(b"duplicate")
        (root / "docs" / "readme.md").write_text("duplicate.txt\n", encoding="utf-8")
        tracked = ["docs/readme.md", "receipts/duplicate.txt", "receipts/canonical.txt"]
        with patch.object(mod, "_tracked_paths", return_value=tracked), patch.object(
            mod, "_git", side_effect=_fixture_git
        ), patch.object(mod, "compute_working_set", return_value={}):
            manifest = mod.build_reference_manifest(root)
        protected = next(row for row in manifest["candidates"] if row["path"] == "receipts/duplicate.txt")
        self.assertEqual(protected["action"], "PROTECTED_EVIDENCE")
        tampered = json.loads(json.dumps(manifest))
        tampered_row = next(row for row in tampered["candidates"] if row["path"] == "receipts/duplicate.txt")
        tampered_row["action"] = "DELETE_CANDIDATE"
        tampered_row["reference_count"] = 0
        tampered_row["references"] = []
        tampered = _seal_manifest(mod, tampered)
        with patch.object(mod, "_tracked_paths", return_value=tracked), patch.object(
            mod, "_git", side_effect=_fixture_git
        ), patch.object(mod, "compute_working_set", return_value={}):
            with self.assertRaises(ValueError):
                mod.apply_safe_cleanup(root, tampered, ["receipts/duplicate.txt"], root / "receipt.json")
        self.assertTrue(target.exists())

    def test_cleanup_rejects_path_alias_before_mutation(self):
        mod = _module()
        root = Path(tempfile.mkdtemp(prefix="issue488-alias-", dir=os.environ.get("TEMP") or os.environ.get("TMP")))
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        target = root / "duplicate.txt"
        canonical = root / "canonical.txt"
        target.write_bytes(b"duplicate")
        canonical.write_bytes(b"duplicate")
        row = {
            "path": "duplicate.txt",
            "kind": "tracked_duplicate",
            "bytes": target.stat().st_size,
            "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            "reference_count": 0,
            "references": [],
            "action": "DELETE_CANDIDATE",
            "superseded_by": "canonical.txt",
            "reason": "byte-identical and unreferenced",
        }
        manifest = _seal_manifest(mod, {
            "schema_version": "ember-issue-488-reference-manifest-v1",
            "source_commit": "0" * 40,
            "source_clean": True,
            "working_set": {},
            "inventory": _empty_inventory(mod),
            "candidates": [row],
            "selected_cleanup": [],
            "completed_cleanup": [],
            "policy": mod._policy_contract(),
            "manifest_sha256": "0" * 64,
        })
        with patch.object(mod, "_git", side_effect=_fixture_git):
            with self.assertRaises(ValueError):
                mod.apply_safe_cleanup(root, manifest, [".\\duplicate.txt"], root / "receipt.json")
        self.assertTrue(target.exists())

    def test_cleanup_rejects_non_git_source_authority(self):
        mod = _module()
        root = Path(tempfile.mkdtemp(prefix="issue488-non-git-", dir=os.environ.get("TEMP") or os.environ.get("TMP")))
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        target = root / "duplicate.txt"
        canonical = root / "canonical.txt"
        target.write_bytes(b"duplicate")
        canonical.write_bytes(b"duplicate")
        row = {
            "path": "duplicate.txt",
            "kind": "tracked_duplicate",
            "bytes": target.stat().st_size,
            "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            "reference_count": 0,
            "references": [],
            "action": "DELETE_CANDIDATE",
            "superseded_by": "canonical.txt",
            "reason": "byte-identical and unreferenced",
        }
        manifest = _seal_manifest(mod, {
            "schema_version": "ember-issue-488-reference-manifest-v1",
            "source_commit": "0" * 40,
            "source_clean": True,
            "working_set": {},
            "inventory": _empty_inventory(mod),
            "candidates": [row],
            "selected_cleanup": [],
            "completed_cleanup": [],
            "policy": mod._policy_contract(),
            "manifest_sha256": "0" * 64,
        })
        with patch.object(mod, "_git", side_effect=OSError("no git")):
            with self.assertRaisesRegex(ValueError, "live Git authority"):
                mod.apply_safe_cleanup(root, manifest, [row["path"]], root / "receipt.json")
        self.assertTrue(target.exists())

    def test_apply_rejects_foreign_or_dirty_source_commit(self):
        mod = _module()
        root = self._fixture()
        manifest = _seal_manifest(mod, {
            "schema_version": "ember-issue-488-reference-manifest-v1",
            "source_commit": "0" * 40,
            "source_clean": True,
            "working_set": {},
            "inventory": _empty_inventory(mod),
            "candidates": [],
            "selected_cleanup": [],
            "completed_cleanup": [],
            "policy": mod._policy_contract(),
            "manifest_sha256": "0" * 64,
        })
        receipt = root / "receipt.json"
        def foreign_git(_root, *args):
            if args == ("rev-parse", "HEAD"):
                return "f" * 40
            if args == ("status", "--porcelain"):
                return ""
            raise OSError("isolated fixture has no repository root")
        with patch.object(mod, "_git", side_effect=foreign_git):
            with self.assertRaisesRegex(ValueError, "source commit drift"):
                mod.apply_safe_cleanup(root, manifest, [], receipt)

        def dirty_git(_root, *args):
            if args == ("rev-parse", "HEAD"):
                return "0" * 40
            if args == ("status", "--porcelain"):
                return " M tracked.txt"
            raise OSError("isolated fixture has no repository root")
        with patch.object(mod, "_git", side_effect=dirty_git):
            with self.assertRaisesRegex(ValueError, "source tree is not clean"):
                mod.apply_safe_cleanup(root, manifest, [], receipt)

    def test_checked_artifact_selected_candidate_cli_positive(self):
        """A receipt may select one DELETE_CANDIDATE while others remain queued."""
        mod = _module()
        source_manifest = REPO_ROOT / "docs/hygiene/issue-488-reference-manifest-v1.json"
        source_receipt = REPO_ROOT / "receipts/hygiene/issue-488-first-cleanup-v1.json"
        manifest = json.loads(source_manifest.read_text(encoding="utf-8"))
        receipt = json.loads(source_receipt.read_text(encoding="utf-8"))
        manifest["completed_cleanup"] = []
        selected_candidate = next(row for row in manifest["candidates"] if row["action"] == "DELETE_CANDIDATE")
        manifest["selected_cleanup"] = [{
            "path": selected_candidate["path"],
            "bytes": selected_candidate["bytes"],
            "sha256": selected_candidate["sha256"],
            "superseded_by": selected_candidate["superseded_by"],
        }]
        manifest = _seal_manifest(mod, manifest)
        receipt["manifest_sha256"] = manifest["manifest_sha256"]
        receipt = _seal_receipt(mod, receipt)
        with tempfile.TemporaryDirectory(dir=os.environ.get("TEMP") or os.environ.get("TMP")) as directory:
            manifest_path = Path(directory) / "manifest.json"
            receipt_path = Path(directory) / "receipt.json"
            manifest_path.write_bytes(mod._canonical(manifest) + b"\n")
            receipt_path.write_bytes(mod._canonical(receipt) + b"\n")
            real_git = mod._git
            def clean_view(root, *args):
                if args == ("status", "--porcelain"):
                    return ""
                return real_git(root, *args)
            with patch.object(mod, "_git", side_effect=clean_view), patch.object(mod, "_validate_manifest"):
                mod.validate_post_cleanup(REPO_ROOT, manifest_path, receipt_path)

    def test_checked_artifact_rejects_selected_cleanup_omission_and_foreign_row(self):
        mod = _module()
        source_manifest = REPO_ROOT / "docs/hygiene/issue-488-reference-manifest-v1.json"
        source_receipt = REPO_ROOT / "receipts/hygiene/issue-488-first-cleanup-v1.json"
        manifest = json.loads(source_manifest.read_text(encoding="utf-8"))
        receipt = json.loads(source_receipt.read_text(encoding="utf-8"))
        delete_row = next(row for row in manifest["candidates"] if row["action"] == "DELETE_CANDIDATE")
        manifest["completed_cleanup"] = []
        manifest["selected_cleanup"] = [{
            "path": delete_row["path"],
            "bytes": delete_row["bytes"],
            "sha256": delete_row["sha256"],
            "superseded_by": delete_row["superseded_by"],
        }]
        manifest = _seal_manifest(mod, manifest)
        receipt["manifest_sha256"] = manifest["manifest_sha256"]
        with tempfile.TemporaryDirectory(dir=os.environ.get("TEMP") or os.environ.get("TMP")) as directory:
            manifest_path = Path(directory) / "manifest.json"
            receipt_path = Path(directory) / "receipt.json"
            manifest_path.write_bytes(mod._canonical(manifest) + b"\n")
            receipt["deleted"] = []
            receipt_path.write_bytes(mod._canonical(receipt) + b"\n")
            real_git = mod._git
            def clean_view(root, *args):
                if args == ("status", "--porcelain"):
                    return ""
                return real_git(root, *args)
            with patch.object(mod, "_git", side_effect=clean_view):
                with patch.object(mod, "_git_archive", return_value=b""), patch.object(mod, "_extract_validated_git_archive"), patch.object(mod, "_validate_manifest"):
                    with self.assertRaises(ValueError):
                        mod.validate_post_cleanup(REPO_ROOT, manifest_path, receipt_path)
            receipt["deleted"] = [{
                "path": "docs/not-a-candidate.txt",
                "bytes": delete_row["bytes"],
                "sha256": delete_row["sha256"],
            }]
            receipt_path.write_bytes(mod._canonical(receipt) + b"\n")
            with patch.object(mod, "_git", side_effect=clean_view):
                with patch.object(mod, "_git_archive", return_value=b""), patch.object(mod, "_extract_validated_git_archive"), patch.object(mod, "_validate_manifest"):
                    with self.assertRaises(ValueError):
                        mod.validate_post_cleanup(REPO_ROOT, manifest_path, receipt_path)

    def test_checked_artifact_rejects_selected_delete_that_remains_or_canonical_drifts(self):
        mod = _module()
        source_manifest = REPO_ROOT / "docs/hygiene/issue-488-reference-manifest-v1.json"
        source_receipt = REPO_ROOT / "receipts/hygiene/issue-488-first-cleanup-v1.json"
        manifest = json.loads(source_manifest.read_text(encoding="utf-8"))
        receipt = json.loads(source_receipt.read_text(encoding="utf-8"))
        candidate = next(
            row for row in manifest["candidates"]
            if row["action"] == "DELETE_CANDIDATE" and Path(row["path"]).exists()
        )
        manifest["completed_cleanup"] = []
        manifest["selected_cleanup"] = [{
            "path": candidate["path"],
            "bytes": candidate["bytes"],
            "sha256": candidate["sha256"],
            "superseded_by": candidate["superseded_by"],
        }]
        manifest = _seal_manifest(mod, manifest)
        receipt["manifest_sha256"] = manifest["manifest_sha256"]
        receipt["deleted"] = [{
            "path": candidate["path"],
            "bytes": candidate["bytes"],
            "sha256": candidate["sha256"],
        }]
        with tempfile.TemporaryDirectory(dir=os.environ.get("TEMP") or os.environ.get("TMP")) as directory:
            manifest_path = Path(directory) / "manifest.json"
            receipt_path = Path(directory) / "receipt.json"
            manifest_path.write_bytes(mod._canonical(manifest) + b"\n")
            receipt_path.write_bytes(mod._canonical(receipt) + b"\n")
            real_git = mod._git
            def clean_view(root, *args):
                if args == ("status", "--porcelain"):
                    return ""
                return real_git(root, *args)
            with patch.object(mod, "_git", side_effect=clean_view), patch.object(
                mod, "_git_archive", return_value=b""
            ), patch.object(mod, "_extract_validated_git_archive"), patch.object(mod, "_validate_manifest"):
                with self.assertRaises(ValueError):
                    mod.validate_post_cleanup(REPO_ROOT, manifest_path, receipt_path)
    def test_historical_working_set_is_recomputed_not_self_overridden(self):
        mod = _module()
        root = self._fixture()
        tracked = ["docs/readme.md", "scripts/run.py", "receipts/canonical.json", "receipts/duplicate.json"]
        with patch.object(mod, "_git", side_effect=_fixture_git):
            manifest = mod.build_reference_manifest(
                root,
                tracked_override=tracked,
                source_commit_override="0" * 40,
                source_clean_override=True,
            )
        manifest["working_set"] = dict(manifest["working_set"])
        manifest["working_set"]["tracked_files"] = 999999
        manifest = _seal_manifest(mod, manifest)
        with patch.object(mod, "_git", side_effect=_fixture_git):
            with self.assertRaises(ValueError):
                mod._validate_manifest(root, manifest, historical=True, tracked_override=tracked)

    def test_manifest_binds_canonical_working_set_producer(self):
        mod = _module()
        root = self._fixture()
        tracked = [
            "docs/readme.md",
            "scripts/run.py",
            "receipts/canonical.json",
            "receipts/duplicate.json",
        ]
        canonical = {
            "tracked_files": 4,
            "docs_files": 1,
            "scripts_files": 1,
            "tracked_receipts": 2,
            "untracked_receipts_on_disk": 1,
            "open_issues_count": 123,
        }
        with patch.object(mod, "compute_working_set", return_value=canonical):
            with patch.object(mod, "_git", side_effect=_fixture_git):
                manifest = mod.build_reference_manifest(
                    root,
                    tracked_override=tracked,
                    source_commit_override="0" * 40,
                    source_clean_override=True,
                )
        self.assertEqual(manifest["working_set"], canonical)

    def _checked_post_cleanup_inputs(self, mod):
        manifest = json.loads(
            (REPO_ROOT / "docs/hygiene/issue-488-reference-manifest-v1.json").read_text(encoding="utf-8")
        )
        receipt = json.loads(
            (REPO_ROOT / "receipts/hygiene/issue-488-first-cleanup-v1.json").read_text(encoding="utf-8")
        )
        manifest["source_commit"] = "e8a3768bcc2a1623ac4fcaa2acdc98b1a3e22079"
        manifest = _seal_manifest(mod, manifest)
        receipt["manifest_sha256"] = manifest["manifest_sha256"]
        source = manifest["source_commit"]
        archive = mod._git_archive(REPO_ROOT, source)
        with tempfile.TemporaryDirectory(dir=os.environ.get("TEMP") or os.environ.get("TMP")) as directory:
            historical_root = Path(directory)
            mod._extract_validated_git_archive(archive, historical_root)
            tracked = subprocess.run(
                ["git", "-C", str(REPO_ROOT), "ls-tree", "-r", "--name-only", source],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.splitlines()
            tracked_set = set(tracked)
            def working_set(tracked_view):
                untracked = sum(
                    1
                    for path in (historical_root / "receipts").rglob("*")
                    if path.is_file() and path.relative_to(historical_root).as_posix() not in tracked_set
                ) if (historical_root / "receipts").is_dir() else 0
                return {
                    "tracked_files": len(tracked_view),
                    "docs_files": sum(path.startswith("docs/") for path in tracked_view),
                    "scripts_files": sum(path.startswith("scripts/") for path in tracked_view),
                    "tracked_receipts": sum(path.startswith("receipts/") for path in tracked_view),
                    "untracked_receipts_on_disk": untracked,
                    "open_issues_count": None,
                }
            receipt["before"] = mod._snapshot(historical_root)
            receipt["working_set_before"] = working_set(tracked)
            for row in receipt["deleted"]:
                (historical_root / Path(row["path"])).unlink()
            receipt["after"] = mod._snapshot(historical_root)
            deleted_paths = {row["path"] for row in receipt["deleted"]}
            receipt["working_set_after_cleanup"] = working_set(
                [path for path in tracked if path not in deleted_paths]
            )
        receipt = _seal_receipt(mod, receipt)
        return manifest, _seal_receipt(mod, receipt)

    def _historical_git(self, _root, *args):
        if args == ("status", "--porcelain"):
            return ""
        if args[:1] in {("cat-file",), ("merge-base",)}:
            return ""
        if args[:1] == ("ls-tree",):
            result = subprocess.run(
                ["git", "-C", str(REPO_ROOT), *args],
                check=True,
                capture_output=True,
                text=True,
            )
            return result.stdout.strip()
        if args[:1] == ("diff",):
            return "D\tdocs/verification/receipts-20260706/resize-probe/resize-after-100x30.txt\n"
        raise AssertionError(f"unexpected git query: {args}")

    def test_post_cleanup_rejects_unselected_tracked_deletion(self):
        mod = _module()
        manifest, receipt = self._checked_post_cleanup_inputs(mod)
        with tempfile.TemporaryDirectory(dir=os.environ.get("TEMP") or os.environ.get("TMP")) as directory:
            manifest_path = Path(directory) / "manifest.json"
            receipt_path = Path(directory) / "receipt.json"
            manifest_path.write_bytes(mod._canonical(manifest) + b"\n")
            receipt_path.write_bytes(mod._canonical(receipt) + b"\n")
            def extra_deletion_git(root, *args):
                if args[:1] == ("diff",):
                    return "D\tforeign-unselected.txt\n"
                return self._historical_git(root, *args)
            with patch.object(mod, "_git", side_effect=extra_deletion_git), patch.object(mod, "_validate_manifest"):
                with self.assertRaisesRegex(ValueError, "tracked deletion"):
                    mod.validate_post_cleanup(REPO_ROOT, manifest_path, receipt_path)

    def test_post_cleanup_authenticates_receipt_schema_snapshots_and_content(self):
        mod = _module()
        mutations = {
            "schema": lambda receipt: receipt.update({"schema_version": "forged"}),
            "policy": lambda receipt: receipt.update({"policy": {"forged": True}}),
            "scope": lambda receipt: receipt.update({"cleanup_scope": {"forged": True}}),
            "before": lambda receipt: receipt["before"].update({"files": 1}),
            "after": lambda receipt: receipt["after"].update({"bytes": 1}),
            "working_set_before": lambda receipt: receipt["working_set_before"].update({"tracked_files": 1}),
            "working_set_after": lambda receipt: receipt["working_set_after_cleanup"].update({"tracked_files": 1}),
            "rollback": lambda receipt: receipt.update({"rollback": {"files": [], "action": "forged"}}),
            "content_hash": lambda receipt: receipt.update({"receipt_sha256": "0" * 64}),
            "extra_field": lambda receipt: receipt.update({"unexpected": True}),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                manifest, receipt = self._checked_post_cleanup_inputs(mod)
                mutate(receipt)
                with tempfile.TemporaryDirectory(dir=os.environ.get("TEMP") or os.environ.get("TMP")) as directory:
                    manifest_path = Path(directory) / "manifest.json"
                    receipt_path = Path(directory) / "receipt.json"
                    manifest_path.write_bytes(mod._canonical(manifest) + b"\n")
                    receipt_path.write_bytes(mod._canonical(receipt) + b"\n")
                    with patch.object(mod, "_git", side_effect=self._historical_git), patch.object(mod, "_validate_manifest"):
                        with self.assertRaises(ValueError):
                            mod.validate_post_cleanup(REPO_ROOT, manifest_path, receipt_path)

    def test_apply_receipt_working_set_excludes_deleted_path(self):
        mod = _module()
        root = self._fixture()
        duplicate = root / "docs" / "duplicate.md"
        duplicate.write_text("doc\n", encoding="utf-8")
        tracked = [
            "docs/readme.md",
            "docs/duplicate.md",
            "scripts/run.py",
            "receipts/canonical.json",
            "receipts/duplicate.json",
        ]
        with patch.object(mod, "_git", side_effect=_fixture_git):
            manifest = mod.build_reference_manifest(
                root,
                tracked_override=tracked,
                source_commit_override="0" * 40,
                source_clean_override=True,
            )
        candidate = next(row for row in manifest["candidates"] if row["action"] == "DELETE_CANDIDATE")
        receipt_path = root / "cleanup-receipt.json"
        def apply_git(_root, *args):
            if args == ("rev-parse", "--show-toplevel"):
                return str(root)
            if args == ("rev-parse", "HEAD"):
                return "0" * 40
            if args == ("status", "--porcelain"):
                return ""
            if args == ("ls-files", "-z"):
                return "\x00".join(tracked)
            raise OSError("isolated fixture has no other Git query")
        with patch.object(mod, "_validate_manifest"), patch.object(mod, "_git", side_effect=apply_git):
            receipt = mod.apply_safe_cleanup(root, manifest, [candidate["path"]], receipt_path)
        self.assertEqual(
            receipt["working_set_after_cleanup"]["tracked_files"],
            receipt["working_set_before"]["tracked_files"] - 1,
        )
        self.assertEqual(
            receipt["working_set_after_cleanup"]["docs_files"],
            receipt["working_set_before"]["docs_files"] - 1,
        )


if __name__ == "__main__":
    unittest.main()
