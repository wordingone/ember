#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""milestone_leg_test.py -- hermetic unit tests + RED-then-GREEN sandbox proof for
src/ember/governance/scripts/ember_totality/milestone_leg.py (Class-2 item 2, docs/audit/class2-unwatched-
mandates-recon-20260704.md #2, parent gh issue #35 DISPATCH 3 of 3).

Unlike enforcement_leg_test.py's precedent (which had to fixture-mimic
check_publication_gate.py because that checker did not exist in the builder's tree),
this suite uses the REAL, UNMODIFIED src/ember/governance/scripts/check_milestone_reconciliation.py copied
byte-for-byte into each per-case sandbox -- real code, real dual-source verdict
resolution (enforcement_leg._run_one_checker, also unmodified), only the 5 INPUT
documents it reads are minimal fixture content. Every case gets a fresh
tempfile.TemporaryDirectory() -- never a shared or reused path (the #85 gate-rejection
discipline this repo already learned the hard way: a fixture that outlives its own case
corrupts the next run).

Run: python -m pytest src/ember/governance/scripts/ember_totality/milestone_leg_test.py -v
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from milestone_leg import MILESTONE_CHECKER, run_milestone_leg  # noqa: E402
# issue2015 exact-local-import:scripts/ember_totality/enforcement_leg.py
import importlib.util as _ember_e1051383780249b3_importlib
import sys as _ember_e1051383780249b3_sys
from pathlib import Path as _ember_e1051383780249b3_Path
_ember_e1051383780249b3_path = _ember_e1051383780249b3_Path(__file__).resolve().parents[5].joinpath('scripts', 'ember_totality', 'enforcement_leg.py')
if not _ember_e1051383780249b3_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:scripts/ember_totality/enforcement_leg.py')
_ember_e1051383780249b3_aliases = ('_ember_issue2015_e1051383780249b3', 'enforcement_leg', 'scripts.ember_totality.enforcement_leg')
_ember_e1051383780249b3_existing = []
for _ember_e1051383780249b3_alias in _ember_e1051383780249b3_aliases:
    _ember_e1051383780249b3_candidate = _ember_e1051383780249b3_sys.modules.get(_ember_e1051383780249b3_alias)
    if _ember_e1051383780249b3_candidate is not None and all(_ember_e1051383780249b3_candidate is not item for item in _ember_e1051383780249b3_existing):
        _ember_e1051383780249b3_existing.append(_ember_e1051383780249b3_candidate)
if len(_ember_e1051383780249b3_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:scripts/ember_totality/enforcement_leg.py')
if _ember_e1051383780249b3_existing:
    _ember_e1051383780249b3_module = _ember_e1051383780249b3_existing[0]
    _ember_e1051383780249b3_observed = getattr(_ember_e1051383780249b3_module, '__file__', None)
    if _ember_e1051383780249b3_observed is None or _ember_e1051383780249b3_Path(_ember_e1051383780249b3_observed).resolve() != _ember_e1051383780249b3_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:scripts/ember_totality/enforcement_leg.py')
else:
    _ember_e1051383780249b3_spec = _ember_e1051383780249b3_importlib.spec_from_file_location('_ember_issue2015_e1051383780249b3', _ember_e1051383780249b3_path)
    if _ember_e1051383780249b3_spec is None or _ember_e1051383780249b3_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:scripts/ember_totality/enforcement_leg.py')
    _ember_e1051383780249b3_module = _ember_e1051383780249b3_importlib.module_from_spec(_ember_e1051383780249b3_spec)
    for _ember_e1051383780249b3_alias in _ember_e1051383780249b3_aliases:
        _ember_e1051383780249b3_prior = _ember_e1051383780249b3_sys.modules.get(_ember_e1051383780249b3_alias)
        if _ember_e1051383780249b3_prior is not None and _ember_e1051383780249b3_prior is not _ember_e1051383780249b3_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:scripts/ember_totality/enforcement_leg.py')
        _ember_e1051383780249b3_sys.modules[_ember_e1051383780249b3_alias] = _ember_e1051383780249b3_module
    try:
        _ember_e1051383780249b3_spec.loader.exec_module(_ember_e1051383780249b3_module)
    except BaseException:
        for _ember_e1051383780249b3_alias in _ember_e1051383780249b3_aliases:
            if _ember_e1051383780249b3_sys.modules.get(_ember_e1051383780249b3_alias) is _ember_e1051383780249b3_module:
                _ember_e1051383780249b3_sys.modules.pop(_ember_e1051383780249b3_alias, None)
        raise
for _ember_e1051383780249b3_alias in _ember_e1051383780249b3_aliases:
    _ember_e1051383780249b3_prior = _ember_e1051383780249b3_sys.modules.get(_ember_e1051383780249b3_alias)
    if _ember_e1051383780249b3_prior is not None and _ember_e1051383780249b3_prior is not _ember_e1051383780249b3_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:scripts/ember_totality/enforcement_leg.py')
    _ember_e1051383780249b3_sys.modules[_ember_e1051383780249b3_alias] = _ember_e1051383780249b3_module
_run_one_checker = getattr(_ember_e1051383780249b3_module, '_run_one_checker')
# issue2015 exact-local-import-end:scripts/ember_totality/enforcement_leg.py  # noqa: E402

REAL_CHECKER_SRC = (
    Path(__file__).resolve().parent.parent / "check_milestone_reconciliation.py"
)


def _write_valid_fixture_tree(root: Path) -> None:
    """Build a complete, minimal-but-real-shaped fixture tree: the REAL checker script
    plus 5 input docs sized exactly to its own parse contract (55 legacy ids, a 6-row
    SS D / floor-contract pair, matching H0..H2 lattice/gates groups). Every milestone
    is mapped with a non-empty target -- this is the INTACT-mirror case."""
    scripts_dir = root / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(REAL_CHECKER_SRC, scripts_dir / "check_milestone_reconciliation.py")

    docs_dir = root / "docs"
    spec_dir = docs_dir / "spec"
    spec_dir.mkdir(parents=True, exist_ok=True)

    # docs/contracts/ember-completeness.md -- exactly C1..C55, one row each.
    completeness_lines = [f"| C{n} | piece{n} | desc{n} | test{n} | receipt{n} |" for n in range(1, 56)]
    (docs_dir / "ember-completeness.md").write_text(
        "# Completeness\n\n" + "\n".join(completeness_lines) + "\n", encoding="utf-8"
    )

    # docs/spec/milestones-v1.md -- SS A (M1..M55, all mapped) + SS C lattice + SS D (6 rows).
    section_a_lines = [f"| M{n} | legacy-piece-{n} | target-{n} |" for n in range(1, 56)]
    lattice_block = (
        "H0\n"
        "  requires C-EFF, C-BASE\n"
        "H1\n"
        "  requires C1, C2\n"
        "H2\n"
        "  requires C-SCALE\n"
    )
    section_d_rows = [
        "| comp-a | why-a | pilot-a | trigger-a | owner-a | status-a | kill-a | tier-a |",
        "| comp-b | why-b | pilot-b | trigger-b | owner-b | status-b | kill-b | tier-b |",
        "| comp-c | why-c | pilot-c | trigger-c | owner-c | status-c | kill-c | tier-c |",
        "| comp-d | why-d | pilot-d | trigger-d | owner-d | status-d | kill-d | tier-d |",
        "| comp-e | why-e | pilot-e | trigger-e | owner-e | status-e | kill-e | tier-e |",
        "| comp-f | why-f | pilot-f | trigger-f | owner-f | status-f | kill-f | tier-f |",
    ]
    milestones_text = (
        "# Milestones v1 (fixture)\n\n"
        "## A. Legacy mapping\n\n"
        + "\n".join(section_a_lines) + "\n\n"
        "## C. Dependency lattice\n\n"
        "```\n" + lattice_block + "```\n\n"
        "## D. Deferred-component floor-contract pattern\n\n"
        "| Component | Why deferred | Pilot | Trigger | Owner | Status | Kill/promote | Tier |\n"
        "|---|---|---|---|---|---|---|---|\n"
        + "\n".join(section_d_rows) + "\n\n"
        "**Invariant carried forward** -- fixture boilerplate, end of SS D.\n"
    )
    (spec_dir / "milestones-v1.md").write_text(milestones_text, encoding="utf-8")

    # docs/roadmap/PROBLEMS.md -- H0..H2 gates lines matching the lattice groups (check_b never
    # flips the verdict either way, but a real-shaped input is still built for fidelity).
    problems_text = (
        "# Problems (fixture)\n\n"
        "- **H0** meta-problem: gates C-EFF, C-BASE\n"
        "- **H1** meta-problem: gates C1, C2\n"
        "- **H2** meta-problem: gates C-SCALE\n"
    )
    (docs_dir / "PROBLEMS.md").write_text(problems_text, encoding="utf-8")

    # docs/problems-meta.yaml -- provenance only, never deep-parsed.
    (docs_dir / "problems-meta.yaml").write_text("# fixture provenance stub\n", encoding="utf-8")

    # docs/contracts/ember-floor-contract.md -- names the SAME 6 SS-D components.
    fc_rows = [f"| comp-{c} | ... | ... | ... | ... | ... | ... |" for c in "abcdef"]
    fc_text = (
        "# Floor contract (fixture)\n\n"
        "## Deferral rows\n\n"
        "| Component | col2 | col3 | col4 | col5 | col6 | col7 |\n"
        "|---|---|---|---|---|---|---|\n"
        + "\n".join(fc_rows) + "\n"
    )
    (docs_dir / "ember-floor-contract.md").write_text(fc_text, encoding="utf-8")


def _break_one_milestone_target(root: Path, n: int = 7) -> None:
    """Empty milestone M<n>'s SS A target cell -- a genuine milestone/lattice-mirror
    divergence (the exact failure mode SS 13-2 names), not a parse crash."""
    path = root / "docs" / "spec" / "milestones-v1.md"
    text = path.read_text(encoding="utf-8")
    text = text.replace(f"| M{n} | legacy-piece-{n} | target-{n} |", f"| M{n} | legacy-piece-{n} |  |")
    path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. Dual-source verdict-line contract: the real checker's PASS line parses correctly
#    through MILESTONE_CHECKER's verdict_regex/pass_values (the thing this module adds
#    on top of enforcement_leg's already-proven generic dual-source mechanism).
# ---------------------------------------------------------------------------

def test_real_checker_intact_mirror_yields_pass():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _write_valid_fixture_tree(root)
        r = _run_one_checker(root, MILESTONE_CHECKER, timeout_s=30)
        assert r["executed"] is True
        assert r["exit_code"] == 0
        assert r["verdict"] == "PASS", r
        assert r["verdict_line"] is not None and r["verdict_line"].startswith("mapped=55/55")


# ---------------------------------------------------------------------------
# 2. RED: a genuine milestone/lattice divergence (one milestone's target emptied)
#    -> the real checker's own (a) assertion fires -> FAIL, both exit code and printed
#    line agree -> dual-source verdict "FAIL", never silently masked.
# ---------------------------------------------------------------------------

def test_real_checker_broken_mirror_yields_fail():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _write_valid_fixture_tree(root)
        _break_one_milestone_target(root, n=7)
        r = _run_one_checker(root, MILESTONE_CHECKER, timeout_s=30)
        assert r["executed"] is True
        assert r["exit_code"] == 1
        assert r["verdict"] == "FAIL", r
        assert "unmapped=1" in r["verdict_line"]


# ---------------------------------------------------------------------------
# 3. RED-then-GREEN, same sandbox, sequential -- the exact shape team-lead asked for:
#    break it -> RED; repair it -> GREEN, proving the leg reacts to real state change,
#    not a cached/stale verdict.
# ---------------------------------------------------------------------------

def test_red_then_green_same_sandbox():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _write_valid_fixture_tree(root)

        _break_one_milestone_target(root, n=12)
        r_red = run_milestone_leg(root, timeout_s=30, receipt_dir=root / "scratch")
        assert r_red["check_milestone_reconciliation"]["verdict"] == "FAIL"

        # repair: rewrite the whole tree fresh (equivalent to a real reconciliation fix)
        _write_valid_fixture_tree(root)
        r_green = run_milestone_leg(root, timeout_s=30, receipt_dir=root / "scratch")
        assert r_green["check_milestone_reconciliation"]["verdict"] == "PASS"


# ---------------------------------------------------------------------------
# 4. Missing checker -> UNRESOLVABLE, exactly the enforcement_leg-generic contract
#    (already proven in enforcement_leg_test.py; re-asserted here against
#    MILESTONE_CHECKER's own rel_path to prove the wiring, not re-testing
#    _run_one_checker's internals from scratch).
# ---------------------------------------------------------------------------

def test_missing_checker_script_is_unresolvable():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        # deliberately do NOT copy the checker script.
        r = _run_one_checker(root, MILESTONE_CHECKER, timeout_s=10)
        assert r["executed"] is False
        assert r["verdict"] == "UNRESOLVABLE"
        assert "not found" in r["reason"]


# ---------------------------------------------------------------------------
# 5. RED-then-GREEN regression for the C0-row/legacy-id collision (live-tree finding,
#    reported to the maintainer, follow-up dispatch: fix check_milestone_reconciliation
#    .py's row-id parsing structurally, never via a hardcoded name skip-list).
#
#    BEFORE the fix, this exact scenario (a "C0" board-condition row sharing
#    ember-completeness.md with the 55 legacy rows) crashed the real checker with a
#    ParseError -- ids {0, 1, ..., 55} != expected {1, ..., 55} -- which
#    _run_one_checker resolves to UNRESOLVABLE (no stdout verdict line to match). That
#    was RED: run this test against the pre-fix checker and it fails on the
#    `verdict == "PASS"` assertion below (receipted in the builder report before the fix
#    was applied). AFTER the fix, a bare-digit condition-row is structurally excluded
#    from the legacy id set (out-of-[1,55]-range id, independently also matched by the
#    conditions-v1.md content marker) -- the real checker now parses this fixture
#    cleanly and the leg reports a coherent PASS. GREEN.
# ---------------------------------------------------------------------------

def test_condition_row_c0_no_longer_breaks_legacy_parse():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _write_valid_fixture_tree(root)
        # the exact live-tree shape: a bare-digit board-condition row ("C0") sharing
        # ember-completeness.md with the 55 legacy C1..C55 rows, citing the condition
        # registry the same way the real docs/contracts/ember-completeness.md:79 row does.
        completeness_path = root / "docs" / "ember-completeness.md"
        text = completeness_path.read_text(encoding="utf-8")
        text += ("| C0 | S3 | No additional loops before resident-training preconditions "
                 "(registry: @docs/domains/governance/spec/conditions-v1.md) | per its own R:/CHK text in "
                 "conditions-v1; probe scripts/ember_totality/test_c0.py | "
                 "— (none certified) | OPEN |\n")
        completeness_path.write_text(text, encoding="utf-8")

        r = _run_one_checker(root, MILESTONE_CHECKER, timeout_s=30)
        assert r["executed"] is True
        assert r["exit_code"] == 0
        assert r["verdict"] == "PASS", r
        assert r["verdict_line"].startswith("mapped=55/55")


# ---------------------------------------------------------------------------
# 5b. The fix must not go blind to a GENUINE legacy gap. Compose both cases in one
#     sandbox: a "C0" condition-row present (proving it's silently, correctly excluded,
#     never raising ParseError) AND a real SS-A target emptied (proving the checker's
#     own (a)-assertion still fires a coherent FAIL on an actual mirror divergence) --
#     the structural exclusion targets condition-rows specifically, not "any surprise
#     row," and does not mask a real milestone/lattice gap.
# ---------------------------------------------------------------------------

def test_genuine_legacy_gap_still_fails_after_fix():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _write_valid_fixture_tree(root)
        completeness_path = root / "docs" / "ember-completeness.md"
        text = completeness_path.read_text(encoding="utf-8")
        text += "| C0 | S3 | (registry: @docs/domains/governance/spec/conditions-v1.md) | ... | ... | OPEN |\n"
        completeness_path.write_text(text, encoding="utf-8")
        _break_one_milestone_target(root, n=30)

        r = _run_one_checker(root, MILESTONE_CHECKER, timeout_s=30)
        assert r["executed"] is True
        assert r["exit_code"] == 1
        assert r["verdict"] == "FAIL", r
        assert "unmapped=1" in r["verdict_line"]


# ---------------------------------------------------------------------------
# 6. milestone_leg's own receipt is written with the required envelope fields, and its
#    ticket/chk_name are milestone-specific (not accidentally the C-ENF ticket, since
#    this module writes its own receipt rather than reusing enforcement_leg's private
#    _write_leg_receipt as-is).
# ---------------------------------------------------------------------------

def test_leg_receipt_written_with_milestone_ticket():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _write_valid_fixture_tree(root)
        receipt_dir = root / "scratch"
        run_milestone_leg(root, timeout_s=30, receipt_dir=receipt_dir)
        files = sorted(receipt_dir.glob("milestone-leg-*.json"))
        assert len(files) == 1
        payload = json.loads(files[0].read_text(encoding="utf-8"))
        assert payload["ticket"] == "EMBER-TOTALITY-MILESTONE-LEG"
        assert payload["api_spend_usd"] == 0.0
        assert payload["paid_api_surface_used"] is False
        assert payload["overall_verdict"] == "PASS"
        assert "check_milestone_reconciliation" in payload["checkers"]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
