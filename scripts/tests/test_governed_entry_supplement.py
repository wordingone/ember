# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

"""The launcher-shape supplemental exceptions policy: parity, precedence, refusals.

The base registry is EMBER-02A guard metadata; a workstream whose enumerated
file changes repins its digest in a supplemental registry inside its own path
scope. Absent supplement is exactly the legacy behavior; a present but invalid
supplement refuses; a supplemental entry overrides the base entry only for an
exact duplicate path; the governed-entry rule has no supplement and ignores
the file entirely.
"""

import hashlib
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
CHECKER_RELATIVE = "tools/check_governed_entry_exceptions.py"
BASE_POLICY_RELATIVE = "tools/launcher-shape-exceptions.json"
SUPPLEMENT_RELATIVE = "tools/ember-restart-3b/launcher-shape-exceptions.json"
SCHEMA_VERSION = "ember-launcher-shape-exceptions-v1"


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_text(path: pathlib.Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def build_fixture(root: pathlib.Path) -> pathlib.Path:
    repo = root / "repo"
    repo.mkdir(parents=True)
    shutil.copyfile(ROOT / CHECKER_RELATIVE, repo / "checker.py")
    write_text(repo / "launcher_a.py", "A = 1\n")
    write_text(repo / "launcher_b.py", "B = 2\n")
    write_text(
        repo / BASE_POLICY_RELATIVE,
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "exceptions": [
                    {"path": "launcher_a.py", "sha256": sha256_text("A = 1\n")}
                ],
            },
            indent=1,
        )
        + "\n",
    )
    return repo


def write_supplement(repo: pathlib.Path, exceptions: list[dict]) -> None:
    write_text(
        repo / SUPPLEMENT_RELATIVE,
        json.dumps(
            {"schema_version": SCHEMA_VERSION, "exceptions": exceptions}, indent=1
        )
        + "\n",
    )


def run_checker(
    repo: pathlib.Path, rule: str, matched: str
) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(repo / "checker.py"), rule],
        cwd=repo,
        env={
            "PATH": "",
            "SYSTEMROOT": "C:\\Windows",
            "LAUNCHER_SHAPE_PATHS": matched if rule == "launcher-shape" else "",
            "GOVERNED_ENTRY_PATHS": matched if rule == "governed-entry" else "",
        },
        capture_output=True,
        text=True,
    )


class LauncherShapeSupplementTests(unittest.TestCase):
    def test_absent_supplement_is_exactly_legacy_behavior(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = build_fixture(pathlib.Path(directory))
            result = run_checker(repo, "launcher-shape", "launcher_a.py")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_supplement_covers_a_path_the_base_does_not(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = build_fixture(pathlib.Path(directory))
            uncovered = run_checker(repo, "launcher-shape", "launcher_b.py")
            self.assertEqual(uncovered.returncode, 1, uncovered.stdout)
            write_supplement(
                repo, [{"path": "launcher_b.py", "sha256": sha256_text("B = 2\n")}]
            )
            covered = run_checker(repo, "launcher-shape", "launcher_b.py")
            self.assertEqual(covered.returncode, 0, covered.stdout + covered.stderr)

    def test_supplement_overrides_base_only_for_exact_duplicate_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = build_fixture(pathlib.Path(directory))
            write_text(repo / "launcher_a.py", "A = 2\n")
            stale = run_checker(repo, "launcher-shape", "launcher_a.py")
            self.assertEqual(stale.returncode, 1, stale.stdout)
            write_supplement(
                repo, [{"path": "launcher_a.py", "sha256": sha256_text("A = 2\n")}]
            )
            repinned = run_checker(repo, "launcher-shape", "launcher_a.py")
            self.assertEqual(repinned.returncode, 0, repinned.stdout + repinned.stderr)

    def test_malformed_supplement_refuses_instead_of_being_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = build_fixture(pathlib.Path(directory))
            write_text(repo / SUPPLEMENT_RELATIVE, "{not json\n")
            result = run_checker(repo, "launcher-shape", "launcher_a.py")
            self.assertEqual(result.returncode, 1, result.stdout)
            self.assertIn("unparseable", result.stdout)

    def test_wrong_supplement_schema_refuses(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = build_fixture(pathlib.Path(directory))
            write_text(
                repo / SUPPLEMENT_RELATIVE,
                json.dumps({"schema_version": "wrong", "exceptions": []}) + "\n",
            )
            result = run_checker(repo, "launcher-shape", "launcher_a.py")
            self.assertEqual(result.returncode, 1, result.stdout)
            self.assertIn("schema_version", result.stdout)

    def test_duplicate_path_within_supplement_refuses(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = build_fixture(pathlib.Path(directory))
            digest = sha256_text("B = 2\n")
            write_supplement(
                repo,
                [
                    {"path": "launcher_b.py", "sha256": digest},
                    {"path": "launcher_b.py", "sha256": digest},
                ],
            )
            result = run_checker(repo, "launcher-shape", "launcher_b.py")
            self.assertEqual(result.returncode, 1, result.stdout)
            self.assertIn("duplicate entry", result.stdout)

    def test_supplement_is_validated_even_with_nothing_to_adjudicate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = build_fixture(pathlib.Path(directory))
            write_text(repo / SUPPLEMENT_RELATIVE, "{not json\n")
            result = run_checker(repo, "launcher-shape", "")
            self.assertEqual(result.returncode, 1, result.stdout)

    def test_staged_scope_adjudicates_the_index_not_the_worktree(self) -> None:
        import os

        with tempfile.TemporaryDirectory() as directory:
            repo = build_fixture(pathlib.Path(directory))
            env = {**os.environ, "LAUNCHER_SHAPE_PATHS": "launcher_b.py"}

            def git(*arguments: str) -> None:
                subprocess.run(
                    ["git", *arguments], cwd=repo, check=True, capture_output=True
                )

            git("init", "-q")
            git("config", "user.email", "fixture@invalid")
            git("config", "user.name", "fixture")
            write_supplement(
                repo, [{"path": "launcher_b.py", "sha256": sha256_text("B = 2\n")}]
            )
            git("add", "-A")
            # Valid index, malformed worktree: staged scope must PASS.
            write_text(repo / SUPPLEMENT_RELATIVE, "{not json\n")
            staged_valid = subprocess.run(
                [sys.executable, str(repo / "checker.py"), "launcher-shape"],
                cwd=repo,
                env={**env, "REPO_GUARD_SCOPE": "staged"},
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                staged_valid.returncode, 0, staged_valid.stdout + staged_valid.stderr
            )
            # Malformed index, valid worktree: staged scope must FAIL.
            git("add", "-A")
            write_supplement(
                repo, [{"path": "launcher_b.py", "sha256": sha256_text("B = 2\n")}]
            )
            staged_malformed = subprocess.run(
                [sys.executable, str(repo / "checker.py"), "launcher-shape"],
                cwd=repo,
                env={**env, "REPO_GUARD_SCOPE": "staged"},
                capture_output=True,
                text=True,
            )
            self.assertEqual(staged_malformed.returncode, 1, staged_malformed.stdout)
            self.assertIn("unparseable", staged_malformed.stdout)

    def test_governed_entry_rule_has_no_supplement(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = build_fixture(pathlib.Path(directory))
            write_text(
                repo / "tools" / "governed-entry-exceptions.json",
                json.dumps(
                    {
                        "schema_version": "ember-governed-entry-exceptions-v1",
                        "exceptions": [],
                    }
                )
                + "\n",
            )
            write_supplement(
                repo, [{"path": "launcher_b.py", "sha256": sha256_text("B = 2\n")}]
            )
            result = run_checker(repo, "governed-entry", "launcher_b.py")
            self.assertEqual(result.returncode, 1, result.stdout)
            self.assertIn("not enumerated", result.stdout)


if __name__ == "__main__":
    unittest.main()
