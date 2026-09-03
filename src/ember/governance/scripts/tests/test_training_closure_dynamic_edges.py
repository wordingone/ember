# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

"""Adversarial coverage for training-closure dynamic execution edges."""

from __future__ import annotations

import importlib.util
import json
import pathlib
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[5]
MODULE_PATH = ROOT / "src" / "ember" / "governance" / "scripts" / "training_closure.py"
MANIFEST_PATH = "manifests/training-dependency-closure.json"
LEGACY_TOOL_ROOT = "tools/ember-restart-3b"
CANONICAL_TOOL_ROOT = "src/ember/infrastructure/tools/ember-restart-3b"
LEGACY_RECEIPT = "tools/corpus_connectors/receipt.py"
CANONICAL_RECEIPT = "src/ember/infrastructure/tools/corpus_connectors/receipt.py"


def restart_tool(name: str) -> str:
    """Repo-relative path of an ember-restart-3b tool at whichever root holds it.

    The tool tree moves from the legacy root to the canonical root in the EMBER-02B
    cutover; this test binds to the location that exists at the head under test, so
    it holds on both sides of that move without editing.
    """
    canonical = f"{CANONICAL_TOOL_ROOT}/{name}"
    if (ROOT / canonical).is_file():
        return canonical
    return f"{LEGACY_TOOL_ROOT}/{name}"


def receipt_module_for(caller: str) -> str:
    """The corpus-connector receipt module a tool at ``caller`` resolves by location."""
    if caller.startswith(CANONICAL_TOOL_ROOT + "/"):
        return CANONICAL_RECEIPT
    return LEGACY_RECEIPT


def load_closure():
    specification = importlib.util.spec_from_file_location(
        "training_closure_dynamic_edges_under_test", MODULE_PATH
    )
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def write_text(path: pathlib.Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def build_repo(
    root: pathlib.Path,
    source: str,
    *,
    declared_target: str | None = None,
    declare_dynamic: bool = False,
) -> pathlib.Path:
    repo = root / "repo"
    write_text(repo / "tools" / "entrypoint.py", source)
    code = ["src/ember/governance/scripts/training_closure.py"]
    if declared_target is not None:
        write_text(repo / declared_target, "# fixture executable\n")
        code.append(declared_target)
    write_text(
        repo / MANIFEST_PATH,
        json.dumps(
            {
                "schema_version": "ember-training-dependency-closure-v1",
                "entrypoints": ["tools/entrypoint.py"],
                "dynamic_entrypoints": [],
                "code": code,
                "data": [],
                "dynamic_call_sites": (
                    {
                        "tools/entrypoint.py": (
                            [declared_target] if declared_target is not None else []
                        )
                    }
                    if declare_dynamic
                    else {}
                ),
                "dynamic_call_site_notes": (
                    {"tools/entrypoint.py": "fixture-declared dynamic edge"}
                    if declare_dynamic
                    else {}
                ),
            },
            indent=2,
        )
        + "\n",
    )
    write_text(
        repo / "src" / "ember" / "governance" / "scripts" / "training_closure.py",
        MODULE_PATH.read_text(encoding="utf-8"),
    )
    return repo


class TrainingClosureDynamicEdgeTests(unittest.TestCase):
    def assert_dynamic_shape_is_fail_closed(self, source: str) -> None:
        closure = load_closure()
        with tempfile.TemporaryDirectory() as directory:
            repo = build_repo(pathlib.Path(directory), source)
            audit = closure.audit_closure(repo)
            self.assertFalse(audit.ok)
            self.assertEqual(audit.undeclared_dynamic, ("tools/entrypoint.py",))

        with tempfile.TemporaryDirectory() as directory:
            repo = build_repo(
                pathlib.Path(directory), source, declare_dynamic=True
            )
            audit = closure.audit_closure(repo)
            self.assertTrue(audit.ok, audit.failure_report())

    def test_bare_and_builtins_exec_eval_are_dynamic_edges(self) -> None:
        sources = (
            'exec("VALUE = 1")\n',
            'eval("1 + 1")\n',
            'import builtins\nbuiltins.exec("VALUE = 1")\n',
            'import builtins\nbuiltins.eval("1 + 1")\n',
        )
        for source in sources:
            with self.subTest(source=source):
                self.assert_dynamic_shape_is_fail_closed(source)

    def test_os_process_families_are_dynamic_edges(self) -> None:
        sources = (
            'import os\nos.system("echo ok")\n',
            'import os\nos.popen("echo ok")\n',
            'import os\nos.spawnl(0, "tool", "tool")\n',
            'import os\nos.execv("tool", ["tool"])\n',
            'import os\nos.posix_spawn("tool", ["tool"], {})\n',
        )
        for source in sources:
            with self.subTest(source=source):
                self.assert_dynamic_shape_is_fail_closed(source)

    def test_non_python_literal_executables_are_reachable_edges(self) -> None:
        closure = load_closure()
        for suffix in (".ps1", ".cmd", ".sh"):
            relative = f"tools/runner{suffix}"
            source = f'import subprocess\nsubprocess.run(["runner{suffix}"])\n'
            with self.subTest(suffix=suffix), tempfile.TemporaryDirectory() as directory:
                repo = build_repo(pathlib.Path(directory), source)
                write_text(repo / relative, "# fixture executable\n")
                audit = closure.audit_closure(repo)
                self.assertFalse(audit.ok)
                self.assertEqual(audit.undeclared, (relative,))

            with self.subTest(suffix=f"{suffix}-declared"), tempfile.TemporaryDirectory() as directory:
                repo = build_repo(
                    pathlib.Path(directory),
                    source,
                    declared_target=relative,
                    declare_dynamic=True,
                )
                audit = closure.audit_closure(repo)
                self.assertTrue(audit.ok, audit.failure_report())

    def test_specialist_stream_declares_hash_bound_exec(self) -> None:
        closure = load_closure()
        note = closure.load_manifest(ROOT)["dynamic_call_site_notes"][
            restart_tool("specialist_stream.py")
        ]
        self.assertIn("exec", note.lower())
        self.assertIn("sha256", note.lower())

    def test_github_license_partition_declares_connector_receipt_import(self) -> None:
        closure = load_closure()
        manifest = closure.load_manifest(ROOT)
        caller = restart_tool("mint_github_license_partition.py")
        resolved = receipt_module_for(caller)
        self.assertIn(CANONICAL_RECEIPT, manifest["code"])
        self.assertIn(resolved, manifest["code"])
        self.assertIn(resolved, manifest["dynamic_call_sites"][caller])
        if resolved == LEGACY_RECEIPT:
            # The legacy receipt module is a bridge onto the canonical one.
            self.assertIn(CANONICAL_RECEIPT, manifest["dynamic_call_sites"][resolved])

    def test_real_text_lab_dynamic_targets_are_machine_detected(self) -> None:
        closure = load_closure()
        caller = restart_tool("text_lab_corpus.py")
        expected = {
            receipt_module_for(caller),
            restart_tool("mint_github_license_partition.py"),
        }

        detected = set(closure.dynamic_repo_targets(ROOT, caller))

        self.assertTrue(expected <= detected, detected)
        self.assertTrue(closure.audit_closure(ROOT).ok)


if __name__ == "__main__":
    unittest.main()
