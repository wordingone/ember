# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
#!/usr/bin/env python3
"""Permanent acceptance tests for verify_nosource_operability.py.

Born from PR #1051's rejection at bcf1057 (state/specs/nosource-harness-
rework-2026-07-25.md): the harness's own acceptance for L1/L3 was a real-tree
run plus a wrong-root run -- two HONEST trees. Neither is hostile. These
tests are the hostile-artifact probes the rework's own acceptance map
requires (items 1-5 of that spec): a synthetic minimal ember-shaped tree
whose only content is the exact adversarial shape Kai's exact-head fixture
used, so the artifact under measurement can never supply its own evidence.

Item 6 (genuine Ember.cmd + genuinely registered commands still resolve
true, on the REAL current tree) and item 7 (wrong-root exit 2, WEAK ranking
fails the gate) are exercised separately against the real repository -- see
rework-harness-report.md for those receipts, which this file's fixtures
cannot reach (they build a synthetic minimal tree on purpose, to keep the
hostile probes independent of the real command-registry.ts's contents).

Run:  python scripts/test_verify_nosource_operability.py
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

_HARNESS_PATH = Path(__file__).resolve().parent / "verify_nosource_operability.py"
_spec = importlib.util.spec_from_file_location("verify_nosource_operability", _HARNESS_PATH)
harness = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(harness)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _minimal_ember_root(root: Path) -> None:
    """Root markers only -- no launcher, no registered commands. Every test
    below adds exactly the artifacts its scenario needs on top of this."""
    _write(root / "INVARIANT.md", "placeholder\n")
    _write(root / "GOAL.md", "placeholder\n")
    _write(
        root / "tools/ember-cli/src/package.json",
        '{"name": "ember-cli", "bin": {"ember": "./entrypoints/main.ts"}}\n',
    )
    _write(
        root / "tools/ember-cli/src/command-registry.ts",
        "import { getModeHistory } from './state/app-state.ts';\n"
        "const defaultDeps = {\n"
        "  getBuiltinCommands: () => [],\n"
        "};\n",
    )


def _registry_importing(root: Path, stems: list[str]) -> None:
    """Overwrite command-registry.ts so it imports and calls createXCommand()
    for each given stem under tools/ember-cli/src/commands/<stem>.ts."""
    imports = "\n".join(
        f"import {{ create{_camel(s)}Command }} from './commands/{s}.ts';" for s in stems
    )
    calls = "\n".join(f"    create{_camel(s)}Command()," for s in stems)
    _write(
        root / "tools/ember-cli/src/command-registry.ts",
        f"{imports}\n"
        "const defaultDeps = {\n"
        "  getBuiltinCommands: () => [\n"
        f"{calls}\n"
        "  ],\n"
        "};\n",
    )


def _camel(stem: str) -> str:
    return "".join(p.capitalize() for p in stem.replace("-", "_").split("_"))


def _command_module(root: Path, stem: str, name: str, description: str) -> None:
    _write(
        root / f"tools/ember-cli/src/commands/{stem}.ts",
        f"export function create{_camel(stem)}Command() {{\n"
        "  return {\n"
        f'    name: "{name}",\n'
        f'    description: "{description}",\n'
        "  };\n"
        "}\n",
    )


class HostileFixtureTests(unittest.TestCase):
    """Item 1: Kai's exact-head fixture, reproduced as a permanent test."""

    def test_decoy_root_script_and_orphan_module_never_resolve_true(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _minimal_ember_root(root)
            # The decoy root script: content unrelated to ember, one line.
            _write(root / "unrelated-maintenance.ps1", "Write-Host not-ember\n")
            # README names it, exactly as Kai's fixture did.
            _write(root / "README.md", "See unrelated-maintenance.ps1 for maintenance tasks.\n")
            # The orphan module: right keywords, right shape, NOT imported
            # by command-registry.ts (which stays empty, per _minimal_ember_root).
            _write(
                root / "tools/ember-cli/src/commands/all.ts",
                "export function createAllSpineCommand() {\n"
                "  return {\n"
                '    name: "all-spine",\n'
                '    description: "custody identity tokenizer lineage checkpoint '
                'owned serve seat benchmark train",\n'
                "  };\n"
                "}\n",
            )

            harness.assert_ember_root(root)
            report = harness.run(root)

            self.assertNotEqual(
                report["checks"]["L1_root_launcher"]["state"],
                "resolved-true",
                report,
            )
            for func, c in report["spine"].items():
                self.assertNotEqual(c["state"], "resolved-true", (func, c, report))
            self.assertEqual(report["verdict"], "FAIL")


class L1DecoyAndEmptyTests(unittest.TestCase):
    """Items 2-3: a decoy launcher pointing outside the repo, and an empty
    launcher, are both RED (never resolved-true)."""

    def test_decoy_launcher_invoking_outside_repo_is_red(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _minimal_ember_root(root)
            with tempfile.NamedTemporaryFile(
                suffix=".exe", delete=False
            ) as outside:
                outside_path = Path(outside.name)
            try:
                _write(
                    root / "decoy.cmd",
                    f'@echo off\r\n"{outside_path}"\r\n',
                )
                report = harness.run(root)
                self.assertNotEqual(
                    report["checks"]["L1_root_launcher"]["state"], "resolved-true", report
                )
            finally:
                outside_path.unlink(missing_ok=True)

    def test_empty_launcher_is_red(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _minimal_ember_root(root)
            _write(root / "empty.cmd", "")
            report = harness.run(root)
            self.assertNotEqual(
                report["checks"]["L1_root_launcher"]["state"], "resolved-true", report
            )

    def test_comment_only_launcher_is_red(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _minimal_ember_root(root)
            _write(root / "comment.cmd", "REM nothing here\r\n:: still nothing\r\n")
            report = harness.run(root)
            self.assertNotEqual(
                report["checks"]["L1_root_launcher"]["state"], "resolved-true", report
            )

    def test_real_launcher_chain_resolves_true(self):
        """Sanity control: a launcher that genuinely hops into the CLI entry
        must still resolve true -- proves the RED cases above are RED
        because of their content, not because L1 always fails now."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _minimal_ember_root(root)
            _write(
                root / "Real.cmd",
                '@echo off\r\npowershell.exe -File "%~dp0scripts\\launch.ps1"\r\n',
            )
            _write(
                root / "scripts/launch.ps1",
                'bun run "tools\\ember-cli\\src\\entrypoints\\main.ts"\r\n',
            )
            report = harness.run(root)
            self.assertEqual(report["checks"]["L1_root_launcher"]["state"], "resolved-true")


class L3RegistryGraphTests(unittest.TestCase):
    """Items 4-5: an orphan module never satisfies a row, and a half-concept
    match on a conjunction function is weak, never resolved-true."""

    def test_orphan_module_row_stays_unsatisfied(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _minimal_ember_root(root)
            _write(root / "Real.cmd", '@echo off\r\ncall "%~dp0tools\\ember-cli\\src\\x.ts"\r\n')
            # a correctly-named, correctly-keyworded module that nothing imports
            _command_module(root, "orphan-bench", "orphan-bench", "benchmark suite runner")
            # command-registry.ts registers nothing
            _registry_importing(root, [])
            report = harness.run(root)
            self.assertNotEqual(
                report["spine"]["benchmarking"]["state"], "resolved-true", report
            )

    def test_half_concept_conjunction_is_weak_not_true(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _minimal_ember_root(root)
            _write(root / "Real.cmd", '@echo off\r\ncall "%~dp0tools\\ember-cli\\src\\x.ts"\r\n')
            # registered module whose name+description carry ONLY "custody"
            _command_module(root, "seatmod", "custody", "custody status only")
            _registry_importing(root, ["seatmod"])
            report = harness.run(root)
            row = report["spine"]["custody_and_identity_manifest"]
            self.assertNotEqual(row["state"], "resolved-true", row)

    def test_conjunction_full_match_registered_resolves_true(self):
        """Sanity control: both required nouns, in a REGISTERED module's
        name+description, with a resolved L1 -- must resolve true."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _minimal_ember_root(root)
            _write(root / "Real.cmd", '@echo off\r\ncall "%~dp0tools\\ember-cli\\src\\x.ts"\r\n')
            _command_module(
                root, "seatmod", "custody", "custody and identity manifest, read-only"
            )
            _registry_importing(root, ["seatmod"])
            report = harness.run(root)
            self.assertEqual(
                report["spine"]["custody_and_identity_manifest"]["state"], "resolved-true"
            )

    def test_registered_module_keyword_in_body_only_is_weak(self):
        """A registered module whose command is named+described elsewhere,
        with the keyword only in its body, must be weak, not resolved-true
        (the pre-existing undiscoverable-capability rule, preserved)."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _minimal_ember_root(root)
            _write(root / "Real.cmd", '@echo off\r\ncall "%~dp0tools\\ember-cli\\src\\x.ts"\r\n')
            _write(
                root / "tools/ember-cli/src/commands/modelish.ts",
                "export function createModelishCommand() {\n"
                "  // implements checkpoint save/load internally\n"
                "  return {\n"
                '    name: "modelish",\n'
                '    description: "load|unload|status",\n'
                "  };\n"
                "}\n",
            )
            _registry_importing(root, ["modelish"])
            report = harness.run(root)
            self.assertEqual(report["spine"]["checkpoint_save_load"]["state"], "weak")


if __name__ == "__main__":
    unittest.main(verbosity=2)
