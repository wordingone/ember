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
whose only content is the exact adversarial shape the reviewer's exact-head
fixture used, so the artifact under measurement can never supply its own
evidence.

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
        '{"name": "ember-cli", "bin": {"ember": "./entrypoints/main.js"}}\n',
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


def _write_real_launcher_chain(root: Path, filename: str = "Real.cmd") -> None:
    """Write a root launcher that GENUINELY, executably invokes the
    package.json-declared CLI entry via `node` -- round 4 grants
    L1_root_launcher resolved-true only from the runtime sentinel probe
    actually observing control reach that entry, so this (unlike round
    3.1's fixtures) must be real, runnable code, not a text shape a
    regex recognizes. The probe overwrites entrypoints/main.js with its
    own sentinel stub before running this, so the file need not exist (or
    hold any particular content) beforehand. Used by every L3 fixture that
    needs L1 resolved-true as a precondition but is not itself testing L1's
    own execution behavior."""
    _write(
        root / filename,
        "@echo off\r\n"
        'node "%~dp0tools\\ember-cli\\src\\entrypoints\\main.js"\r\n',
    )


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
    """Item 1: the reviewer's exact-head fixture, reproduced as a permanent test."""

    def test_decoy_root_script_and_orphan_module_never_resolve_true(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _minimal_ember_root(root)
            # The decoy root script: content unrelated to ember, one line.
            _write(root / "unrelated-maintenance.ps1", "Write-Host not-ember\n")
            # README names it, exactly as the reviewer's fixture did.
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
        """Sanity control: a launcher that genuinely, executably hops into
        the CLI entry (a .cmd that shells to a .ps1 that runs `node` against
        the package.json-declared entry) must still resolve true via the
        round-4 runtime sentinel probe -- proves the RED cases above are RED
        because control never actually reaches the entry, not because L1
        always fails now."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _minimal_ember_root(root)
            _write(
                root / "Real.cmd",
                '@echo off\r\npowershell.exe -NoLogo -NoProfile -NonInteractive '
                '-ExecutionPolicy Bypass -File "%~dp0scripts\\launch.ps1"\r\n',
            )
            _write(
                root / "scripts/launch.ps1",
                '$repoRoot = Split-Path -Parent $PSScriptRoot\r\n'
                '$entry = Join-Path $repoRoot "tools\\ember-cli\\src\\entrypoints\\main.js"\r\n'
                "& node $entry\r\n",
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
            _write_real_launcher_chain(root)
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


class AmbiguousMatchTests(unittest.TestCase):
    """The near-miss defect (found by another lane, no defect shipped): a
    one-line command-description edit accidentally made `custody.ts` win the
    `checkpoint_save_load` row on alphabetical first-match, because that
    row's keyword ("checkpoint") is a bare substring with no conjunction
    guard -- silently reassigning a spine function to a command that only
    displays identity read-only and does not implement save/load at all.
    The harness reported the theft as a pass. Ambiguity must be reported as
    a defect: the row names every matching module and refuses to resolve
    true, rather than silently crediting whichever module `dict.items()`
    (insertion order == `sorted(cmd_dir.glob("*.ts"))`, i.e. alphabetical)
    happens to reach first."""

    def test_two_registered_modules_matching_one_row_never_resolve_alphabetical_winner(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _minimal_ember_root(root)
            _write_real_launcher_chain(root)
            # Alphabetically FIRST ("custody" < "save-load"): a read-only
            # identity display that happens to mention "checkpoint" in its
            # description -- the exact shape of the near-miss (a
            # description edit, not an implementation).
            _command_module(
                root, "custody", "custody",
                "shows identity and last checkpoint timestamp, read-only",
            )
            # Alphabetically LATER: the module that actually implements
            # save/load.
            _command_module(
                root, "save-load", "checkpoint",
                "save and load model checkpoints",
            )
            _registry_importing(root, ["custody", "save-load"])
            report = harness.run(root)
            row = report["spine"]["checkpoint_save_load"]
            # The defect this reproduces: silently resolving true, crediting
            # only the alphabetically-first module (custody.ts) and saying
            # nothing about the competing module.
            self.assertNotEqual(row["state"], "resolved-true", row)
            self.assertIn("custody.ts", row["evidence"], row)
            self.assertIn("save-load.ts", row["evidence"], row)

    def test_single_unambiguous_match_still_resolves_true(self):
        """Sanity control: exactly one registered, named+described module
        matching a row must still resolve true -- the ambiguity fix must
        not turn every match into a false collision."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _minimal_ember_root(root)
            _write_real_launcher_chain(root)
            _command_module(
                root, "save-load", "checkpoint",
                "save and load model checkpoints",
            )
            _registry_importing(root, ["save-load"])
            report = harness.run(root)
            row = report["spine"]["checkpoint_save_load"]
            self.assertEqual(row["state"], "resolved-true", row)

    def test_three_way_collision_names_all_three(self):
        """The collision report must name every matching module, not just
        the first two -- a reviewer needs to see the full competition."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _minimal_ember_root(root)
            _write_real_launcher_chain(root)
            _command_module(root, "aaa-decoy", "aaa", "mentions checkpoint in passing")
            _command_module(root, "bbb-decoy", "bbb", "also has checkpoint text")
            _command_module(root, "ccc-real", "checkpoint", "save and load checkpoints")
            _registry_importing(root, ["aaa-decoy", "bbb-decoy", "ccc-real"])
            report = harness.run(root)
            row = report["spine"]["checkpoint_save_load"]
            self.assertNotEqual(row["state"], "resolved-true", row)
            for name in ("aaa-decoy.ts", "bbb-decoy.ts", "ccc-real.ts"):
                self.assertIn(name, row["evidence"], row)


class Round3TextPositionTests(unittest.TestCase):
    """Round 3: an independent probe on dc6dcf3 fooled L1 with a root
    Ember.cmd whose entire body was `@echo off` / a REM comment naming the
    CLI entry / an echo printing one line -- run for real it invokes
    nothing, but the harness's own string-literal scan credited the comment
    text as evidence and returned a full PASS. These reproduce the probe's
    fixture and its two named siblings (print-argument, unreachable branch)
    as permanent tests, plus the secondary L3 duplicate-import finding."""

    def test_probe_do_nothing_launcher_never_resolves_true(self):
        """The probe's exact attack1b: @echo off / REM comment naming the
        entry path / echo. Six genuinely registered spine commands sit
        alongside it (nothing hostile in L2/L3) to isolate L1's own hole --
        this must not resolve true, and must not reach an overall PASS."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _minimal_ember_root(root)
            _write(
                root / "Ember.cmd",
                "@echo off\r\n"
                'REM stub, does nothing. "tools/ember-cli/anything-at-all" is never invoked.\r\n'
                "echo This launcher performs no action.\r\n",
            )
            _write(root / "README.md", "Run Ember.cmd to start Ember.\n")
            stems = ["custody", "tokenizer", "checkpoint", "owned", "benchmark", "train"]
            for i, kw in enumerate(stems):
                _command_module(
                    root,
                    f"spine{i}",
                    f"spine{i}",
                    "custody identity tokenizer lineage checkpoint owned serve seat "
                    "benchmark train",
                )
            _registry_importing(root, [f"spine{i}" for i in range(len(stems))])

            report = harness.run(root)
            self.assertNotEqual(
                report["checks"]["L1_root_launcher"]["state"], "resolved-true", report
            )
            self.assertFalse(report["verdict"].startswith("PASS"), report)

    def test_probe_comment_only_marker_never_resolves_true(self):
        """The probe's narrower attack1: a comment-only .cmd whose only
        quoted string is a path that was never created."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _minimal_ember_root(root)
            _write(
                root / "decoy.cmd",
                '@echo off\r\nREM "tools/ember-cli/README-not-real.md" is only mentioned here.\r\n',
            )
            report = harness.run(root)
            self.assertNotEqual(
                report["checks"]["L1_root_launcher"]["state"], "resolved-true", report
            )

    def test_echo_print_argument_never_resolves_true(self):
        """A launcher whose only mention of the entry path is inside an
        echo argument -- prints it, never runs it."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _minimal_ember_root(root)
            _write(
                root / "Ember.cmd",
                '@echo off\r\necho "tools/ember-cli/src is where the code lives"\r\n',
            )
            report = harness.run(root)
            self.assertNotEqual(
                report["checks"]["L1_root_launcher"]["state"], "resolved-true", report
            )

    def test_write_host_print_argument_never_resolves_true(self):
        """Same shape, PowerShell Write-Host instead of batch echo."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _minimal_ember_root(root)
            _write(
                root / "Real.cmd",
                '@echo off\r\npowershell.exe -File "%~dp0scripts\\launch.ps1"\r\n',
            )
            _write(
                root / "scripts/launch.ps1",
                'Write-Host "tools\\ember-cli\\src is where the code lives"\r\n',
            )
            report = harness.run(root)
            self.assertNotEqual(
                report["checks"]["L1_root_launcher"]["state"], "resolved-true", report
            )

    def test_unreachable_branch_never_resolves_true(self):
        """A launcher whose entry invocation sits after an unconditional
        top-level exit -- control leaves the script before reaching it. This
        is now proven by REAL execution (`exit /b 0` genuinely stops cmd.exe
        before the node line runs), not by static reachability tracking."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _minimal_ember_root(root)
            _write(
                root / "Ember.cmd",
                "@echo off\r\n"
                "exit /b 0\r\n"
                'node "%~dp0tools\\ember-cli\\src\\entrypoints\\main.js"\r\n',
            )
            report = harness.run(root)
            self.assertNotEqual(
                report["checks"]["L1_root_launcher"]["state"], "resolved-true", report
            )

    def test_conditional_exit_inside_block_does_not_kill_reachability(self):
        """Sanity control, and the real Ember.cmd's own shape: an exit
        INSIDE an `if (...)` block must not stop the launcher from reaching
        its real invocation when the condition is false (no args passed
        here) -- proven now by REAL execution taking the correct branch,
        not by a static depth-tracked reachability heuristic."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _minimal_ember_root(root)
            _write(
                root / "Ember.cmd",
                "@echo off\r\n"
                'if not "%~1"=="" (\r\n'
                "  echo no args allowed\r\n"
                "  exit /b 2\r\n"
                ")\r\n"
                'node "%~dp0tools\\ember-cli\\src\\entrypoints\\main.js"\r\n',
            )
            report = harness.run(root)
            self.assertEqual(report["checks"]["L1_root_launcher"]["state"], "resolved-true")

    def test_duplicate_import_binding_credits_neither_module(self):
        """Secondary L3 finding: two `import { createTrainCommand } from
        ...}` statements binding the SAME local identifier to two different
        modules -- invalid TypeScript, but the harness reads bytes, not a
        build result. Neither the real module nor the decoy may be
        credited; the row must stay unsatisfied and the ambiguity must be
        named."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _minimal_ember_root(root)
            _write(root / "Real.cmd", '@echo off\r\ncall "%~dp0tools\\ember-cli\\src\\x.ts"\r\n')
            _write(
                root / "tools/ember-cli/src/commands/real-train.ts",
                "export function createTrainCommand() {\n"
                '  return { name: "train", description: "training launch 3b" };\n'
                "}\n",
            )
            _write(
                root / "tools/ember-cli/src/commands/decoy-orphan.ts",
                "export function createTrainCommand() {\n"
                '  return { name: "train-decoy", description: "not the real training launch" };\n'
                "}\n",
            )
            _write(
                root / "tools/ember-cli/src/command-registry.ts",
                "import { createTrainCommand } from './commands/real-train.ts';\n"
                "import { createTrainCommand } from './commands/decoy-orphan.ts';\n"
                "const defaultDeps = {\n"
                "  getBuiltinCommands: () => [\n"
                "    createTrainCommand(),\n"
                "  ],\n"
                "};\n",
            )
            report = harness.run(root)
            self.assertNotEqual(
                report["spine"]["training_launch_3b"]["state"], "resolved-true", report
            )
            evidence = report["spine"]["training_launch_3b"]["evidence"]
            self.assertNotIn("train-decoy", evidence)


class Round4RuntimeSentinelTests(unittest.TestCase):
    """Round 4: an independent probe defeated round 3.1's exact grammar with
    `type "tools\\ember-cli\\src\\main.ts"` -- printing the entry's path is
    neither a comment, a print-statement argument, nor dead code, so every
    static exclusion stepped aside and it resolved-true. The reviewer's
    point generalizes: the set of non-invoking uses of a path (type,
    findstr, copy, more, fc, a redirection target, ...) has no boundary a
    static exclusion list can enumerate. These prove the round-4 runtime
    sentinel probe -- which actually executes the candidate and observes
    whether an owned sentinel fires, consulting no text at all for the
    verdict -- closes the type attack and its equivalents, and that a
    probe which cannot even be started reads as weak, not as a false
    negative about the launcher."""

    def test_type_command_prints_entry_never_resolves_true(self):
        """The exact round-4 attack: `type` prints the CLI entry's path,
        executing nothing. Must land resolved-false (the probe genuinely
        ran, for real, and the sentinel never fired), not weak."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _minimal_ember_root(root)
            _write(
                root / "Ember.cmd",
                '@echo off\r\ntype "tools\\ember-cli\\src\\main.ts"\r\n',
            )
            report = harness.run(root)
            self.assertEqual(
                report["checks"]["L1_root_launcher"]["state"], "resolved-false", report
            )

    def test_type_findstr_copy_more_fc_are_all_non_fire_reds(self):
        """The class the `type` attack names has no enumerable boundary --
        rather than add one more exclusion per verb, prove the runtime
        probe refuses the whole open-ended family at once by sweeping
        several of the reviewer's named siblings."""
        verbs = {
            "type.cmd": 'type "tools\\ember-cli\\src\\main.ts"',
            "findstr.cmd": 'findstr /c:"x" "tools\\ember-cli\\src\\main.ts"',
            "copy.cmd": 'copy "tools\\ember-cli\\src\\main.ts" "%TEMP%\\out.ts" >nul',
            "more.cmd": 'more < "tools\\ember-cli\\src\\main.ts"',
        }
        for filename, body in verbs.items():
            with self.subTest(filename=filename):
                with tempfile.TemporaryDirectory() as td:
                    root = Path(td)
                    _minimal_ember_root(root)
                    _write(root / filename, f"@echo off\r\n{body}\r\n")
                    report = harness.run(root)
                    self.assertEqual(
                        report["checks"]["L1_root_launcher"]["state"],
                        "resolved-false",
                        report,
                    )

    def test_comment_echo_deadcode_are_resolved_false_not_weak(self):
        """Reviewer's binding refinement: an executed-but-never-fired probe
        is a definite negative (resolved-false), never weak -- weak is
        reserved for a probe that could not be run at all. Re-runs the
        three round-3 siblings and asserts the tighter state."""
        fixtures = {
            "comment.cmd": (
                "@echo off\r\n"
                'REM stub, does nothing. "tools/ember-cli/anything-at-all" is never invoked.\r\n'
                "echo This launcher performs no action.\r\n"
            ),
            "echo.cmd": '@echo off\r\necho "tools/ember-cli/src is where the code lives"\r\n',
            "deadcode.cmd": (
                "@echo off\r\n"
                "exit /b 0\r\n"
                'node "%~dp0tools\\ember-cli\\src\\entrypoints\\main.js"\r\n'
            ),
        }
        for filename, body in fixtures.items():
            with self.subTest(filename=filename):
                with tempfile.TemporaryDirectory() as td:
                    root = Path(td)
                    _minimal_ember_root(root)
                    _write(root / filename, body)
                    report = harness.run(root)
                    self.assertEqual(
                        report["checks"]["L1_root_launcher"]["state"],
                        "resolved-false",
                        report,
                    )

    def test_genuine_executable_chain_resolves_true_with_bound_receipt(self):
        """Positive control: a launcher that for real, executably, invokes
        `node` DIRECTLY against the package.json-declared CLI entry (not
        through the test-mode runtime hook) must resolve true via the
        ENTRY marker specifically, and the receipt must bind the exact
        bytes/cwd/argv/exit code a reader would need to reproduce the
        verdict without rerunning it. Round 7: the entry marker now
        records the executing process's OWN resolved path (never a
        caller-supplied value), and resolved-true requires that path to
        equal the scratch tree's actual CLI entry."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _minimal_ember_root(root)
            _write_real_launcher_chain(root, "Real.cmd")
            report = harness.run(root)
            check = report["checks"]["L1_root_launcher"]
            self.assertEqual(check["state"], "resolved-true", report)
            receipt = check["receipts"]["Real.cmd"]
            for field in (
                "launcher",
                "cli_entry",
                "cli_entry_bin_rel",
                "entry_sentinel_stub_bytes",
                "cwd",
                "argv",
                "timeout_s",
                "exit_code",
                "entry_marker_content",
                "entry_marker_path_matches_declared_entry",
                "expected_entry_path",
            ):
                self.assertIn(field, receipt, f"receipt missing {field}: {receipt}")
            self.assertEqual(receipt["exit_code"], 0)
            self.assertTrue(receipt["entry_marker_path_matches_declared_entry"], receipt)
            self.assertEqual(
                receipt["entry_marker_content"], receipt["expected_entry_path"]
            )

    def test_runtime_delegation_to_genuine_run_resolves_true_via_entry_marker(self):
        """Round 6 positive control: a launcher that reaches the CLI entry
        only through the substituted test-mode runtime (as the real
        Ember.cmd chain does, since bun itself is replaced) resolves true
        via the ENTRY marker -- the faithful runtime stub genuinely
        delegates `run <file>` to real bun, so the entry's own substituted
        bytes execute for real, from their own declared (in-place)
        location. The runtime's recorded argv is present only as
        disclosed, non-verdict-bearing diagnostic colour."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _minimal_ember_root(root)
            _write(
                root / "ViaRuntime.cmd",
                "@echo off\r\n"
                'if defined EMBER_LAUNCH_TEST_RUNTIME call "%EMBER_LAUNCH_TEST_RUNTIME%" '
                "run tools/ember-cli/src/entrypoints/main.js\r\n"
                "exit /b 0\r\n",
            )
            report = harness.run(root)
            check = report["checks"]["L1_root_launcher"]
            self.assertEqual(check["state"], "resolved-true", report)
            receipt = check["receipts"]["ViaRuntime.cmd"]
            self.assertTrue(receipt.get("entry_marker_path_matches_declared_entry"), receipt)
            self.assertEqual(
                receipt.get("entry_marker_content"), receipt.get("expected_entry_path")
            )
            diag_key = "runtime_marker_argv_DIAGNOSTIC_ONLY_NOT_VERDICT_BEARING"
            self.assertIn(
                "tools/ember-cli/src/entrypoints/main.js", receipt.get(diag_key, "")
            )

    def test_decoy_copy_entry_out_of_tree_and_execute_never_resolves_true(self):
        """Round 6's defeat and round 7's reason to exist: the launcher
        copies the CLI entry's OWN substituted bytes out of the tree (to
        %TEMP%) and runs the copy. The entry marker DOES fire -- the
        bytes genuinely executed -- but the process's own reported path is
        the %TEMP% copy, not the declared CLI entry's in-place location,
        so the verdict must be resolved-false, not resolved-true. This is
        the exact reproducer that beat round 6 (CopyRun.cmd)."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _minimal_ember_root(root)
            _write(
                root / "CopyRun.cmd",
                "@echo off\r\n"
                'copy /y "tools\\ember-cli\\src\\entrypoints\\main.js" '
                '"%TEMP%\\stolen-entry.js" >nul\r\n'
                'if defined EMBER_LAUNCH_TEST_RUNTIME call "%EMBER_LAUNCH_TEST_RUNTIME%" '
                'run "%TEMP%\\stolen-entry.js"\r\n'
                "exit /b 0\r\n",
            )
            report = harness.run(root)
            check = report["checks"]["L1_root_launcher"]
            self.assertEqual(check["state"], "resolved-false", report)
            receipt = check.get("receipts", {}).get("CopyRun.cmd", {})
            if "entry_marker_content" in receipt:
                self.assertFalse(
                    receipt.get("entry_marker_path_matches_declared_entry", True), receipt
                )
                self.assertNotEqual(
                    receipt["entry_marker_content"], receipt.get("expected_entry_path"), receipt
                )

    def test_decoy_copy_entry_to_different_in_tree_directory_never_resolves_true(self):
        """Sibling of the copy-then-execute decoy: the copy destination is
        a DIFFERENT directory INSIDE the tree (not %TEMP%), so the
        laundering can't be dismissed as merely 'outside the repo'. The
        path-match requirement is location-exact, not tree-membership --
        a copy one directory over is still not the entry's own place."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _minimal_ember_root(root)
            _write(root / "tools/ember-cli/decoy-landing/.keep", "")
            _write(
                root / "CopyRunInTree.cmd",
                "@echo off\r\n"
                'copy /y "tools\\ember-cli\\src\\entrypoints\\main.js" '
                '"tools\\ember-cli\\decoy-landing\\main.js" >nul\r\n'
                'if defined EMBER_LAUNCH_TEST_RUNTIME call "%EMBER_LAUNCH_TEST_RUNTIME%" '
                'run "tools\\ember-cli\\decoy-landing\\main.js"\r\n'
                "exit /b 0\r\n",
            )
            report = harness.run(root)
            check = report["checks"]["L1_root_launcher"]
            self.assertEqual(check["state"], "resolved-false", report)
            receipt = check.get("receipts", {}).get("CopyRunInTree.cmd", {})
            if "entry_marker_content" in receipt:
                self.assertFalse(
                    receipt.get("entry_marker_path_matches_declared_entry", True), receipt
                )
                self.assertNotEqual(
                    receipt["entry_marker_content"], receipt.get("expected_entry_path"), receipt
                )

    def test_decoy_asking_runtime_version_never_resolves_true(self):
        """Round 4's original reproducer, re-verified under round 6: a
        launcher that invokes the substituted test-mode runtime with
        `--version` -- not `run` -- must not resolve true. The faithful
        runtime refuses to execute anything for a flag it doesn't
        recognise as `run <file>`, exactly as real bun would not run a
        script for `--version`."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _minimal_ember_root(root)
            _write(
                root / "Decoy.cmd",
                "@echo off\r\n"
                "rem This launcher never runs the Ember CLI entry. It only asks "
                "the runtime its version.\r\n"
                'if defined EMBER_LAUNCH_TEST_RUNTIME call "%EMBER_LAUNCH_TEST_RUNTIME%" '
                "--version\r\n"
                "exit /b 0\r\n",
            )
            report = harness.run(root)
            self.assertEqual(
                report["checks"]["L1_root_launcher"]["state"], "resolved-false", report
            )

    def test_decoy_entry_passed_to_unrelated_flag_never_resolves_true(self):
        """Round 5's own reproducer, and the reason round 6 exists: the
        entry path IS present in the runtime's argv, but as an argument to
        `--version`, not to `run` -- round 5's argv-substring test could
        not tell these apart (`norm_entry in norm_argv` matched regardless
        of position) and resolved this true. The faithful runtime only
        executes for a literal `run <file>` first token; `--version
        <entry>` runs nothing, and the entry marker -- the only thing that
        can grant true now -- never fires."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _minimal_ember_root(root)
            _write(
                root / "Decoy2.cmd",
                "@echo off\r\n"
                "rem Never executes the entry. Only mentions it as a flag "
                "argument to the runtime.\r\n"
                'if defined EMBER_LAUNCH_TEST_RUNTIME call "%EMBER_LAUNCH_TEST_RUNTIME%" '
                "--version entrypoints/main.js\r\n"
                "exit /b 0\r\n",
            )
            report = harness.run(root)
            check = report["checks"]["L1_root_launcher"]
            self.assertEqual(check["state"], "resolved-false", report)
            receipt = check.get("receipts", {}).get("Decoy2.cmd")
            if receipt:
                self.assertNotIn("entry_marker_content", receipt)

    def test_decoy_entry_passed_to_unrelated_check_flag_never_resolves_true(self):
        """Sibling of the exact round-5 reproducer, with a different
        non-`run` flag, so the class closes rather than the one `--version`
        instance."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _minimal_ember_root(root)
            _write(
                root / "Decoy3.cmd",
                "@echo off\r\n"
                'if defined EMBER_LAUNCH_TEST_RUNTIME call "%EMBER_LAUNCH_TEST_RUNTIME%" '
                "--check entrypoints/main.js\r\n"
                "exit /b 0\r\n",
            )
            report = harness.run(root)
            self.assertEqual(
                report["checks"]["L1_root_launcher"]["state"], "resolved-false", report
            )

    def test_decoy_runtime_run_of_unrelated_script_never_resolves_true(self):
        """A launcher that genuinely invokes `run <file>` on the runtime,
        but names a DIFFERENT file than the declared CLI entry -- the
        faithful runtime genuinely executes that unrelated file for real
        (proving delegation works), but since it is not the entry, the
        entry marker never fires."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _minimal_ember_root(root)
            _write(root / "tools/ember-cli/src/unrelated.js", "// not the entry\n")
            _write(
                root / "Decoy4.cmd",
                "@echo off\r\n"
                'if defined EMBER_LAUNCH_TEST_RUNTIME call "%EMBER_LAUNCH_TEST_RUNTIME%" '
                "run tools/ember-cli/src/unrelated.js\r\n"
                "exit /b 0\r\n",
            )
            report = harness.run(root)
            self.assertEqual(
                report["checks"]["L1_root_launcher"]["state"], "resolved-false", report
            )

    def test_probe_cannot_execute_is_weak_not_resolved_false(self):
        """An environment that cannot even run the candidate (here: an
        extension the probe has no runner for) has told us nothing about
        the launcher -- must be weak, never resolved-false."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _minimal_ember_root(root)
            _write(root / "launch.exe", "not a real binary, just bytes\n")
            report = harness.run(root)
            self.assertEqual(
                report["checks"]["L1_root_launcher"]["state"], "weak", report
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
