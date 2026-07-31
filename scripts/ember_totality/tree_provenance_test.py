#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Production-shaped tests for totality run-tree provenance (issue #511)."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import gen_readme_status
from scripts.ember_totality import ember_totality_spec
from scripts.ember_totality import tree_provenance


def _git(root: Path, *args: str) -> str:
    env = dict(os.environ)
    env.update(
        {
            "GIT_AUTHOR_NAME": "issue511-test",
            "GIT_AUTHOR_EMAIL": "issue511@example.invalid",
            "GIT_COMMITTER_NAME": "issue511-test",
            "GIT_COMMITTER_EMAIL": "issue511@example.invalid",
        }
    )
    proc = subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return proc.stdout.strip()


class TreeProvenanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.remote = root / "remote.git"
        self.seed = root / "seed"
        self.run = root / "run"
        subprocess.run(["git", "init", "--bare", str(self.remote)], check=True, capture_output=True)
        subprocess.run(["git", "init", "-b", "master", str(self.seed)], check=True, capture_output=True)
        (self.seed / "tracked.txt").write_text("one\n", encoding="utf-8", newline="\n")
        _git(self.seed, "add", "tracked.txt")
        _git(self.seed, "commit", "-m", "initial")
        _git(self.seed, "remote", "add", "origin", str(self.remote))
        _git(self.seed, "push", "-u", "origin", "master")
        subprocess.run(
            ["git", "clone", str(self.remote), str(self.run)],
            check=True,
            capture_output=True,
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _advance_remote(self) -> str:
        (self.seed / "tracked.txt").write_text("two\n", encoding="utf-8", newline="\n")
        _git(self.seed, "add", "tracked.txt")
        _git(self.seed, "commit", "-m", "advance")
        _git(self.seed, "push", "origin", "master")
        return _git(self.seed, "rev-parse", "HEAD")

    def test_clean_exact_master_is_current_and_publishable(self) -> None:
        state = tree_provenance.inspect_and_enforce(self.run)
        self.assertFalse(state["tree_is_stale"])
        self.assertEqual(state["tree_dirty"], [])
        self.assertEqual(state["behind_by"], 0)
        self.assertEqual(state["provenance_status"], "CURRENT_CLEAN")
        self.assertTrue(state["publishable_as_current"])

    def test_stale_tree_refuses_by_default_and_override_is_archaeology_only(self) -> None:
        remote_sha = self._advance_remote()
        with self.assertRaisesRegex(tree_provenance.TreeProvenanceError, "TOTALITY_TREE_REFUSED"):
            tree_provenance.inspect_and_enforce(self.run)
        state = tree_provenance.inspect_and_enforce(self.run, allow_stale_tree=True)
        self.assertTrue(state["tree_is_stale"])
        self.assertEqual(state["remote_master_sha"], remote_sha)
        self.assertEqual(state["behind_by"], 1)
        self.assertEqual(state["provenance_status"], "STALE_DIRTY_OVERRIDE")
        self.assertFalse(state["publishable_as_current"])

    def test_dirty_tracked_file_refuses_but_untracked_output_is_exempt(self) -> None:
        (self.run / "untracked.json").write_text("{}\n", encoding="utf-8")
        clean = tree_provenance.inspect_and_enforce(self.run)
        self.assertEqual(clean["tree_dirty"], [])
        (self.run / "tracked.txt").write_text("dirty\n", encoding="utf-8")
        with self.assertRaisesRegex(tree_provenance.TreeProvenanceError, "tracked files are dirty"):
            tree_provenance.inspect_and_enforce(self.run)
        state = tree_provenance.inspect_and_enforce(self.run, allow_stale_tree=True)
        self.assertTrue(state["tree_dirty"])
        self.assertEqual(state["provenance_status"], "STALE_DIRTY_OVERRIDE")

    def test_offline_fallback_is_explicitly_degraded(self) -> None:
        tree_provenance.inspect_and_enforce(self.run)
        _git(self.run, "remote", "set-url", "origin", str(Path(self.temp.name) / "missing.git"))
        state = tree_provenance.inspect_and_enforce(self.run)
        self.assertEqual(state["remote_master_source"], "FETCH_HEAD_DEGRADED")
        self.assertEqual(state["provenance_status"], "DEGRADED_REMOTE_CHECK")
        self.assertFalse(state["publishable_as_current"])

    def test_offline_fallback_refuses_unrelated_fetch_head(self) -> None:
        tree_provenance.inspect_and_enforce(self.run)
        fetch_head = Path(_git(self.run, "rev-parse", "--git-path", "FETCH_HEAD"))
        if not fetch_head.is_absolute():
            fetch_head = self.run / fetch_head
        fetch_head.write_text(
            f"{_git(self.run, 'rev-parse', 'HEAD')}\t\tbranch 'other' of origin\n",
            encoding="utf-8",
            newline="\n",
        )
        _git(self.run, "remote", "set-url", "origin", str(Path(self.temp.name) / "missing.git"))
        with self.assertRaisesRegex(
            tree_provenance.TreeProvenanceError,
            "canonical remote master and FETCH_HEAD fallback are unavailable",
        ):
            tree_provenance.inspect_and_enforce(self.run)

    def test_runner_refuses_before_registry_or_receipt_creation(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            receipt_dir = Path(td) / "receipts"
            with (
                mock.patch.object(ember_totality_spec, "RECEIPTS_DIR", str(receipt_dir)),
                mock.patch.object(
                    ember_totality_spec.tree_provenance,
                    "inspect_and_enforce",
                    side_effect=tree_provenance.TreeProvenanceError("TOTALITY_TREE_REFUSED"),
                ),
                mock.patch.object(ember_totality_spec, "registry_sync_check") as registry,
                mock.patch("sys.argv", ["ember_totality_spec.py"]),
            ):
                with self.assertRaisesRegex(tree_provenance.TreeProvenanceError, "TOTALITY_TREE_REFUSED"):
                    ember_totality_spec.main()
            registry.assert_not_called()
            self.assertFalse(receipt_dir.exists())

    def test_readme_renderer_refuses_stale_without_same_opt_out(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            receipt_path = Path(td) / "ember-totality-20990101T000000Z.json"
            receipt_path.write_text(
                json.dumps(
                    {
                        "ts": "20990101T000000Z",
                        "summary": {},
                        "run_tree_provenance": {
                            "run_tree_sha": "a" * 40,
                            "remote_master_sha": "b" * 40,
                            "remote_master_source": "LS_REMOTE",
                            "tree_is_stale": True,
                            "behind_by": 1,
                            "tree_dirty": [],
                            "stale_tree_override": True,
                            "provenance_status": "STALE_DIRTY_OVERRIDE",
                            "publishable_as_current": False,
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(tree_provenance.TreeProvenanceError, "README_TREE_REFUSED"):
                gen_readme_status.render_block(receipt_path)
            block = gen_readme_status.render_block(receipt_path, allow_stale_tree=True)
            self.assertIn("ARCHAEOLOGY_ONLY", block)
            self.assertIn("tree_is_stale=true", block)

    def test_readme_renderer_rejects_forged_current_provenance(self) -> None:
        forged = {
            "run_tree_sha": "a" * 40,
            "remote_master_sha": "b" * 40,
            "remote_master_source": "LS_REMOTE",
            "tree_is_stale": False,
            "behind_by": 0,
            "tree_dirty": [],
            "stale_tree_override": False,
            "provenance_status": "CURRENT_CLEAN",
            "publishable_as_current": True,
        }
        with self.assertRaisesRegex(
            tree_provenance.TreeProvenanceError,
            "stale flag contradicts Git SHAs",
        ):
            tree_provenance.validate_receipt_for_render(
                {"run_tree_provenance": forged}
            )

    def test_consumer_refuses_receipt_older_than_required_merge(self) -> None:
        initial_sha = _git(self.run, "rev-parse", "HEAD")
        state = tree_provenance.inspect_and_enforce(self.run)
        required_merge = self._advance_remote()
        _git(self.run, "fetch", "origin", "master")

        with self.assertRaisesRegex(
            tree_provenance.TreeProvenanceError,
            "required merge is newer than the board source",
        ):
            tree_provenance.validate_receipt_for_render(
                {"run_tree_provenance": state},
                repo_root=self.run,
                required_commits=[required_merge],
            )

        accepted = tree_provenance.validate_receipt_for_render(
            {"run_tree_provenance": state},
            repo_root=self.run,
            required_commits=[initial_sha],
        )
        self.assertEqual(accepted, state)

    def test_readme_renderer_requires_explicit_merge_in_board_source(self) -> None:
        initial_sha = _git(self.run, "rev-parse", "HEAD")
        state = tree_provenance.inspect_and_enforce(self.run)
        required_merge = self._advance_remote()
        _git(self.run, "fetch", "origin", "master")
        with tempfile.TemporaryDirectory() as td:
            receipt_path = Path(td) / "ember-totality-20990101T000000Z.json"
            receipt_path.write_text(
                json.dumps(
                    {
                        "ts": "20990101T000000Z",
                        "summary": {},
                        "run_tree_provenance": state,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                tree_provenance.TreeProvenanceError,
                "required merge is newer than the board source",
            ):
                gen_readme_status.render_block(
                    receipt_path,
                    repo_root=self.run,
                    required_commits=[required_merge],
                )
            block = gen_readme_status.render_block(
                receipt_path,
                repo_root=self.run,
                required_commits=[initial_sha],
            )
            self.assertIn(initial_sha, block)


if __name__ == "__main__":
    unittest.main()
