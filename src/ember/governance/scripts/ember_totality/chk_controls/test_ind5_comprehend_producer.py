#!/usr/bin/env python3
"""test_ind5_comprehend_producer.py -- issue #88 selftest: fixture cases for
each of the four comprehend_v2 legs' RED path, plus one full POS case.

Hermetic: every case builds its OWN fresh tempfile.TemporaryDirectory() --
no shared static fixture directory, no mutation carried between cases. This
is deliberate: the fixture-leak class (a shared fixture directory mutated
by one test case and read by another) cost another builder a gate reject,
and this file exists specifically to not repeat that.

Run:  PYTHONIOENCODING=utf-8 python test_ind5_comprehend_producer.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))  # producer lives one level up; selftest sits in chk_controls/ to stay outside the board-probe registry glob

import ind5_comprehend_producer as prod  # noqa: E402

failures: list[str] = []


def check(label: str, cond: bool) -> None:
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {label}")
    if not cond:
        failures.append(label)


README_OK = """# Operator entry point (fixture)

- [Interact](interact.md)
- [Cockpit](cockpit.md)
"""

README_MISSING_DOC = """# Operator entry point (fixture)

- [Interact](interact.md)
- [Ghost page](does-not-exist.md)
"""


# --- POS: all four legs pass -------------------------------------------------

def test_pos_all_four_legs_pass() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ops = root / "docs" / "operator"
        ops.mkdir(parents=True)
        (ops / "README.md").write_text(README_OK, encoding="utf-8")
        (ops / "interact.md").write_text("# Interact\n\nOne real command: `/model`.\n", encoding="utf-8")
        (ops / "cockpit.md").write_text("# Cockpit\n\nSee `/cockpit`.\n", encoding="utf-8")

        epi = prod.check_entry_point_integrity(root)
        check("POS: entry_point_integrity passes on a fixture with no dead links", epi["passed"])

        live_commands = [{"name": "model", "aliases": []}, {"name": "cockpit", "aliases": ["world"]}]
        completeness = prod.check_completeness(live_commands, ops)
        check("POS: completeness passes when every live command is named in docs", completeness["passed"])

        freshness = prod.check_freshness(live_commands, ops)
        check("POS: freshness passes when every doc-cited command is live", freshness["passed"])

        (ops / "customize.md").write_text(
            "# Customize\n\nRun it:\n\n`python -c \"print('ok')\"`\n", encoding="utf-8",
        )
        executability = prod.check_executability(ops, root)
        check("POS: executability passes on a trivially-true python -c example", executability["passed"])


# --- RED path 1: missing doc (entry_point_integrity) -------------------------

def test_red_missing_doc() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ops = root / "docs" / "operator"
        ops.mkdir(parents=True)
        (ops / "README.md").write_text(README_MISSING_DOC, encoding="utf-8")
        (ops / "interact.md").write_text("# Interact\n", encoding="utf-8")
        # deliberately do NOT create does-not-exist.md

        epi = prod.check_entry_point_integrity(root)
        check("RED missing-doc: entry_point_integrity fails", not epi["passed"])
        check("RED missing-doc: dead_links names the missing file",
              "does-not-exist.md" in epi["dead_links"])


def test_red_missing_readme_itself() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "docs" / "operator").mkdir(parents=True)
        # no README.md written at all
        epi = prod.check_entry_point_integrity(root)
        check("RED missing-README: entry_point_integrity fails when README.md itself is absent",
              not epi["passed"])


# --- RED path 2: stale keybind/command (freshness) ---------------------------

def test_red_stale_keybind() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ops = root / "docs" / "operator"
        ops.mkdir(parents=True)
        (ops / "interact.md").write_text(
            "# Interact\n\nOne documented, real slash command: `/model`.\n\n"
            "Also try `/ghost-command` for advanced use.\n",
            encoding="utf-8",
        )
        live_commands = [{"name": "model", "aliases": []}]  # /ghost-command does NOT exist live
        freshness = prod.check_freshness(live_commands, ops)
        check("RED stale-keybind: freshness fails on a doc-cited command absent from the live registry",
              not freshness["passed"])
        check("RED stale-keybind: stale_citations names the exact stale token",
              "ghost-command" in freshness["stale_citations"])


def test_freshness_ignores_documented_bad_input_example() -> None:
    """/xyzzy in interact.md is an intentional bad-input demonstration, not a
    claim of realness -- must NOT be flagged stale (false-positive guard)."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ops = root / "docs" / "operator"
        ops.mkdir(parents=True)
        (ops / "interact.md").write_text(
            "# Interact\n\n"
            "One recoverable bad-input case: any unrecognized slash command (e.g. `/xyzzy`) renders "
            "`Unknown command: /xyzzy`.\n",
            encoding="utf-8",
        )
        freshness = prod.check_freshness([{"name": "model", "aliases": []}], ops)
        check("freshness: /xyzzy bad-input example is not flagged stale (documented non-claim)",
              "xyzzy" not in freshness["stale_citations"])


# --- RED path 3: failing example (executability) -----------------------------

def test_red_failing_example() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ops = root / "docs" / "operator"
        ops.mkdir(parents=True)
        (ops / "customize.md").write_text(
            "# Customize\n\nRun it:\n\n`python -c \"import sys; sys.exit(1)\"`\n",
            encoding="utf-8",
        )
        executability = prod.check_executability(ops, root)
        check("RED failing-example: executability fails when an example exits nonzero",
              not executability["passed"])
        failing = [e for e in executability["examples"] if e.get("status") == "candidate" and not e.get("passed")]
        check("RED failing-example: the failing example is present in the receipt, not silently dropped",
              len(failing) == 1)


def test_executability_excludes_interactive_with_disclosed_reason() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ops = root / "docs" / "operator"
        ops.mkdir(parents=True)
        (ops / "activate.md").write_text(
            "# Activate\n\n```sh\ncd tools/ember-cli/src\nnode core/ember-world-state-repl.ts\n```\n",
            encoding="utf-8",
        )
        executability = prod.check_executability(ops, root)
        excluded = [e for e in executability["examples"] if e["status"] == "excluded_interactive"]
        check("executability: interactive REPL boot is excluded, never executed",
              len(excluded) == 1 and bool(excluded[0].get("reason")))


# --- bonus RED path: completeness (undocumented live command) ---------------

def test_red_completeness_gap() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ops = root / "docs" / "operator"
        ops.mkdir(parents=True)
        (ops / "interact.md").write_text("# Interact\n\nOne command: `/model`.\n", encoding="utf-8")
        live_commands = [{"name": "model", "aliases": []}, {"name": "watch", "aliases": []}]
        completeness = prod.check_completeness(live_commands, ops)
        check("RED completeness-gap: fails when a live command is named nowhere in docs",
              not completeness["passed"])
        undoc_names = [c["name"] for c in completeness["undocumented_commands"]]
        check("RED completeness-gap: undocumented_commands names exactly the missing command",
              undoc_names == ["watch"])


def main() -> int:
    test_pos_all_four_legs_pass()
    test_red_missing_doc()
    test_red_missing_readme_itself()
    test_red_stale_keybind()
    test_freshness_ignores_documented_bad_input_example()
    test_red_failing_example()
    test_executability_excludes_interactive_with_disclosed_reason()
    test_red_completeness_gap()
    print()
    if failures:
        print(f"FAILED {len(failures)}: {failures}")
        return 1
    print("ALL CASES PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
