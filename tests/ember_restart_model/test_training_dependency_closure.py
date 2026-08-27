# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

"""The training dependency closure: guard, hash, and the launch binding.

The certified launch chain used to bind the whole repository tip, so a
docs-only merge invalidated a pending certificate. These tests hold the
narrower binding honest at both ends: the guard proves the declared closure is
the reachable one (so the boundary cannot rot), and the launch consumer proves
a moved tip outside the closure is accepted while a changed closure file is
not.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import shutil
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
CLOSURE_MODULE_PATH = ROOT / "scripts" / "training_closure.py"
MANIFEST_RELATIVE_PATH = "manifests/training-dependency-closure.json"


def load_closure():
    specification = importlib.util.spec_from_file_location(
        "training_closure_under_test", CLOSURE_MODULE_PATH
    )
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def write_text(path: pathlib.Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def build_sandbox_repo(
    root: pathlib.Path,
    *,
    entrypoint_source: str = "import json\n",
    code: tuple[str, ...] = (),
    data: tuple[str, ...] = (),
    dynamic_call_sites: dict[str, list[str]] | None = None,
) -> pathlib.Path:
    """A miniature repo with a real closure module and a declared closure."""

    repo = root / "repo"
    (repo / "scripts").mkdir(parents=True)
    shutil.copyfile(CLOSURE_MODULE_PATH, repo / "scripts" / "training_closure.py")
    write_text(repo / "tools" / "entrypoint.py", entrypoint_source)
    write_text(repo / "configs" / "training.json", '{"steps": 1}\n')
    for relative in code:
        write_text(repo / relative, "VALUE = 1\n")
    for relative in data:
        write_text(repo / relative, "{}\n")
    write_text(
        repo / MANIFEST_RELATIVE_PATH,
        json.dumps(
            {
                "schema_version": "ember-training-dependency-closure-v1",
                "entrypoints": ["tools/entrypoint.py"],
                "dynamic_entrypoints": [],
                "code": ["scripts/training_closure.py", *code],
                "data": ["configs/training.json", *data],
                "dynamic_call_sites": dynamic_call_sites or {},
                "dynamic_call_site_notes": {
                    path: "fixture has no repo target"
                    for path, targets in (dynamic_call_sites or {}).items()
                    if not targets
                },
            },
            indent=2,
        )
        + "\n",
    )
    return repo


class TrainingClosureGuardTests(unittest.TestCase):
    def test_declared_closure_matches_the_walked_closure_at_this_tree(self) -> None:
        """The guard CI runs: every reachable file is declared, every declared file exists."""

        closure = load_closure()
        audit = closure.audit_closure(ROOT)
        self.assertTrue(audit.ok, audit.failure_report())
        self.assertIn(MANIFEST_RELATIVE_PATH, audit.declared)
        self.assertIn(
            "tools/ember-restart-3b/run_vertical_slice.py", audit.reachable
        )

    def test_guard_fails_when_an_entrypoint_imports_an_undeclared_module(self) -> None:
        closure = load_closure()
        with tempfile.TemporaryDirectory() as directory:
            repo = build_sandbox_repo(pathlib.Path(directory))
            write_text(repo / "tools" / "smuggled.py", "SECRET = 1\n")
            write_text(
                repo / "tools" / "entrypoint.py", "from smuggled import SECRET\n"
            )
            audit = closure.audit_closure(repo)
            self.assertFalse(audit.ok)
            self.assertEqual(audit.undeclared, ("tools/smuggled.py",))
            self.assertIn("tools/smuggled.py", audit.failure_report())

    def test_guard_fails_when_an_entrypoint_execs_an_undeclared_program(self) -> None:
        closure = load_closure()
        with tempfile.TemporaryDirectory() as directory:
            repo = build_sandbox_repo(pathlib.Path(directory))
            write_text(repo / "tools" / "verifier.py", "OK = True\n")
            write_text(
                repo / "tools" / "entrypoint.py",
                'import pathlib, subprocess, sys\n'
                'subprocess.run([sys.executable, str(pathlib.Path(__file__).with_name("verifier.py"))])\n',
            )
            audit = closure.audit_closure(repo)
            self.assertFalse(audit.ok)
            self.assertEqual(audit.undeclared, ("tools/verifier.py",))

    def test_guard_fails_when_a_declared_file_is_absent(self) -> None:
        closure = load_closure()
        with tempfile.TemporaryDirectory() as directory:
            repo = build_sandbox_repo(
                pathlib.Path(directory), data=("configs/vanished.json",)
            )
            (repo / "configs" / "vanished.json").unlink()
            audit = closure.audit_closure(repo)
            self.assertFalse(audit.ok)
            self.assertEqual(audit.missing, ("configs/vanished.json",))

    def test_guard_fails_on_an_undeclared_dynamic_edge(self) -> None:
        """A spec_from_file_location the walk cannot follow is a red, not a gap."""

        closure = load_closure()
        with tempfile.TemporaryDirectory() as directory:
            repo = build_sandbox_repo(pathlib.Path(directory))
            write_text(
                repo / "tools" / "entrypoint.py",
                "import importlib.util\n"
                'importlib.util.spec_from_file_location("x", "somewhere.py")\n',
            )
            audit = closure.audit_closure(repo)
            self.assertFalse(audit.ok)
            self.assertEqual(audit.undeclared_dynamic, ("tools/entrypoint.py",))
            self.assertIn("dynamic_call_sites", audit.failure_report())

    def test_guard_accepts_a_declared_dynamic_edge(self) -> None:
        closure = load_closure()
        with tempfile.TemporaryDirectory() as directory:
            repo = build_sandbox_repo(
                pathlib.Path(directory),
                entrypoint_source=(
                    "import subprocess, sys\n"
                    'subprocess.run([sys.executable, "--version"])\n'
                ),
                dynamic_call_sites={
                    "tools/entrypoint.py": []
                },
            )
            audit = closure.audit_closure(repo)
            self.assertTrue(audit.ok, audit.failure_report())

    def test_guard_fails_when_a_dynamic_caller_omits_its_repo_target(self) -> None:
        """A caller key alone must not hide a newly added repo-target edge."""

        closure = load_closure()
        with tempfile.TemporaryDirectory() as directory:
            repo = build_sandbox_repo(
                pathlib.Path(directory),
                entrypoint_source=(
                    "import importlib.util\n"
                    "from pathlib import Path\n"
                    "target = Path(__file__).resolve().parent / 'helper.py'\n"
                    "importlib.util.spec_from_file_location('helper', target)\n"
                ),
                code=("tools/helper.py",),
                dynamic_call_sites={"tools/entrypoint.py": []},
            )
            manifest_path = repo / MANIFEST_RELATIVE_PATH
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["dynamic_call_site_notes"] = {
                "tools/entrypoint.py": "fixture deliberately omits its repo target"
            }
            write_text(manifest_path, json.dumps(manifest, indent=2) + "\n")

            audit = closure.audit_closure(repo)

            self.assertFalse(audit.ok)
            self.assertEqual(
                audit.undeclared_dynamic_targets,
                ("tools/entrypoint.py -> tools/helper.py",),
            )
            self.assertIn("tools/helper.py", audit.failure_report())

    def test_guard_fails_on_a_stale_dynamic_declaration(self) -> None:
        closure = load_closure()
        with tempfile.TemporaryDirectory() as directory:
            repo = build_sandbox_repo(
                pathlib.Path(directory),
                dynamic_call_sites={"tools/entrypoint.py": ["nothing, any more"]},
            )
            audit = closure.audit_closure(repo)
            self.assertFalse(audit.ok)
            self.assertEqual(audit.stale_dynamic, ("tools/entrypoint.py",))

    def test_guard_catches_the_builtins_import_shape(self) -> None:
        """specialist_stream replaces __import__ through builtins; that counts."""

        closure = load_closure()
        with tempfile.TemporaryDirectory() as directory:
            repo = build_sandbox_repo(pathlib.Path(directory))
            write_text(
                repo / "tools" / "entrypoint.py",
                "import builtins\nbuiltins.__import__('json')\n",
            )
            audit = closure.audit_closure(repo)
            self.assertFalse(audit.ok)
            self.assertEqual(audit.undeclared_dynamic, ("tools/entrypoint.py",))

    def test_guard_failure_names_the_counter_resume_consequence(self) -> None:
        """A closure-inside counter change kills resume; the guard says so."""

        closure = load_closure()
        with tempfile.TemporaryDirectory() as directory:
            repo = build_sandbox_repo(pathlib.Path(directory))
            write_text(repo / "tools" / "smuggled.py", "SECRET = 1\n")
            write_text(
                repo / "tools" / "entrypoint.py", "from smuggled import SECRET\n"
            )
            report = closure.audit_closure(repo).failure_report()
            self.assertIn("parameter_counter.py", report)
            self.assertIn("RESUME", report)

    def test_guard_accepts_a_declared_import(self) -> None:
        closure = load_closure()
        with tempfile.TemporaryDirectory() as directory:
            repo = build_sandbox_repo(
                pathlib.Path(directory),
                entrypoint_source="from helper import VALUE\n",
                code=("tools/helper.py",),
            )
            audit = closure.audit_closure(repo)
            self.assertTrue(audit.ok, audit.failure_report())


class ClosureHashTests(unittest.TestCase):
    def test_same_tree_hashes_the_same(self) -> None:
        closure = load_closure()
        self.assertEqual(
            closure.compute_closure_hash(ROOT), closure.compute_closure_hash(ROOT)
        )

    def test_hash_ignores_files_outside_the_closure(self) -> None:
        closure = load_closure()
        with tempfile.TemporaryDirectory() as directory:
            repo = build_sandbox_repo(pathlib.Path(directory))
            before = closure.compute_closure_hash(repo)
            write_text(repo / "docs" / "governance.md", "a docs-only merge\n")
            self.assertEqual(closure.compute_closure_hash(repo), before)

    def test_hash_moves_when_a_closure_file_changes(self) -> None:
        closure = load_closure()
        with tempfile.TemporaryDirectory() as directory:
            repo = build_sandbox_repo(pathlib.Path(directory))
            before = closure.compute_closure_hash(repo)
            write_text(repo / "configs" / "training.json", '{"steps": 2}\n')
            self.assertNotEqual(closure.compute_closure_hash(repo), before)

    def test_hash_moves_when_the_manifest_itself_changes(self) -> None:
        """The manifest is inside the closure: widening it cannot pass unnoticed."""

        closure = load_closure()
        with tempfile.TemporaryDirectory() as directory:
            repo = build_sandbox_repo(pathlib.Path(directory))
            before = closure.compute_closure_hash(repo)
            manifest_path = repo / MANIFEST_RELATIVE_PATH
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["data"].append("configs/extra.json")
            write_text(repo / "configs" / "extra.json", "{}\n")
            write_text(manifest_path, json.dumps(manifest, indent=2) + "\n")
            self.assertNotEqual(closure.compute_closure_hash(repo), before)

    def test_hash_is_a_lowercase_sha256(self) -> None:
        closure = load_closure()
        value = closure.compute_closure_hash(ROOT)
        self.assertEqual(len(value), 64)
        self.assertEqual(value, value.lower())
        int(value, 16)


if __name__ == "__main__":
    unittest.main()
