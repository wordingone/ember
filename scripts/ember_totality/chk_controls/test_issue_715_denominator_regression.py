#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""test_issue_715_denominator_regression.py -- CPU-only regression test for
gh issue #715 ("C-MANIFEST denominator regex blind to C-MANIFEST/C-TALLY
bullets; both genuinely unmanifested, board shows GREEN").

Issue #715 root cause: test_c_manifest.py's `_CID_RE` separator alternation
had no bare "." token, so the two goal-file bullets that use a period
separator -- "- **C-MANIFEST.** ..." and "- **C-TALLY.** ..." (both in
docs/domains/governance/spec/conditions-v1.md S4.3, the two roll-up/meta-conditions) -- never
matched and silently vanished from the planned-piece denominator (probe
counted 38 vs the true count, which was 40 at fix time and has since grown
to 41 as the registry gained further conditions -- see conditions-v1.md
line 451's own running tally). This regression suite proves BOTH halves of
the fix stay true against PRODUCTION-SHAPED inputs -- the real
docs/domains/governance/spec/conditions-v1.md and docs/domains/governance/contracts/ember-completeness.md files copied
byte-for-byte into an isolated fixture root, never a helper-invented mini
goal/manifest shape:

  1. test_positive_denominator_floor_and_rollups_counted: the real §4
     bullet count is >= 40 (the floor established by the fix; it may only
     grow, never shrink back under 40) AND explicitly includes both
     C-MANIFEST and C-TALLY -- the exact two ids the punctuation-accident
     regex used to drop. Running the real probe against an unmodified
     production-shaped fixture must emit GREEN.
  2. test_red_on_c_manifest_row_removed: an INDEPENDENT fixture with the
     production manifest's C-MANIFEST row deleted must turn the real probe
     RED, naming C-MANIFEST as the missing condition -- proving the
     C-MANIFEST row's own presence is load-bearing, not merely counted.
  3. test_red_on_c_tally_row_removed: the same, independently, for the
     C-TALLY row -- proving the two conditions are checked independently
     (removing one must not be maskable by the other still being present).

Hermetic: every case builds its own fresh tempfile.TemporaryDirectory()
fixture root, seeded from copies of the REAL repo files (never mutating the
real tree), and runs the real src/ember/governance/scripts/ember_totality/test_c_manifest.py as a
subprocess with EMBER_TOTALITY_ROOT pointed at that fixture -- exactly the
isolation convention chk_controls/run_controls.py already uses for every
other CHK-adequacy control in this package (see build_c_manifest() there for
the synthetic-fixture precedent this file deliberately does NOT reuse --
issue #715's own audit finding was specifically about the PRODUCTION file's
literal separator characters, so the regression must exercise the real
bytes, not a re-typed analogue that could quietly diverge from them again).

CPU-only, no network, no GPU. Runs in well under 60s (each of the 3 cases is
a single short-lived Python subprocess).

Run (Git Bash / native Windows python, repo root or any cwd):
  PYTHONIOENCODING=utf-8 python \\
    scripts/ember_totality/chk_controls/test_issue_715_denominator_regression.py
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent                      # .../scripts/ember_totality/chk_controls
PROBES_DIR = HERE.parent                                     # .../scripts/ember_totality
REPO_ROOT = PROBES_DIR.parent.parent                         # repo root
PROBE_PATH = PROBES_DIR / "test_c_manifest.py"
REAL_CONDITIONS_SPEC = REPO_ROOT / "docs" / "spec" / "conditions-v1.md"
REAL_MANIFEST = REPO_ROOT / "docs" / "ember-completeness.md"

DENOMINATOR_FLOOR = 40  # the fix's own established floor (gh #715); real count may only grow from here

failures: list[str] = []


def check(label: str, cond: bool) -> None:
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {label}")
    if not cond:
        failures.append(label)


# PR955 round-2 repair (reviewer defect P2): the two removal cases used to
# assert absence of a substring ("missing=C-TALLY" not in line / not
# line.endswith(",C-TALLY")) instead of the actual parsed id set -- fragile
# against reordering, additional missing ids, or any cosmetic reason-string
# change in test_c_manifest.py's RED line. This helper extracts the exact
# structured missing_condition_ids list from the probe's own "missing=..."
# segment so every caller (this file AND run_controls.py, which wires this
# regression into the canonical control battery) asserts SET EQUALITY
# against real parsed data, never a substring guess.
_MISSING_RE = re.compile(r"missing=([^\s;]+)")


def parse_missing_condition_ids(line: str) -> list[str]:
    """Return the exact list of condition ids test_c_manifest.py's RED line
    names as missing (empty list for a GREEN line, which has no `missing=`
    segment)."""
    m = _MISSING_RE.search(line)
    if not m:
        return []
    return [cid for cid in m.group(1).split(",") if cid]


def _run_probe(fixture_root: Path) -> tuple[str, str]:
    """Execute the REAL test_c_manifest.py as a subprocess against
    fixture_root via EMBER_TOTALITY_ROOT. Returns (status_token, full_line)."""
    env = dict(os.environ)
    env["EMBER_TOTALITY_ROOT"] = str(fixture_root)
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run(
        [sys.executable, str(PROBE_PATH)],
        cwd=str(PROBES_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=30,
    )
    out_lines = (proc.stdout or "").strip().splitlines()
    line = out_lines[0] if out_lines else "<no stdout>"
    status = line.split(" ", 1)[0] if line else "<empty>"
    return status, line


def _seed_production_fixture(root: Path) -> None:
    """Copy the REAL conditions-v1.md and ember-completeness.md byte-for-byte
    into root at the same relative paths the probe resolves -- production-
    shaped inputs, not a helper-invented mini goal/manifest."""
    spec_dst = root / "docs" / "spec" / "conditions-v1.md"
    manifest_dst = root / "docs" / "ember-completeness.md"
    spec_dst.parent.mkdir(parents=True, exist_ok=True)
    spec_dst.write_bytes(REAL_CONDITIONS_SPEC.read_bytes())
    manifest_dst.write_bytes(REAL_MANIFEST.read_bytes())
    return spec_dst, manifest_dst


def _delete_manifest_row(manifest_path: Path, condition_id: str) -> None:
    """Remove the single markdown table row whose first cell is exactly
    condition_id from manifest_path, in place. Fails loudly (AssertionError)
    if the row cannot be uniquely located -- a silent no-op here would make
    the removal test vacuous."""
    text = manifest_path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    matches = [
        i for i, ln in enumerate(lines)
        if ln.strip().startswith(f"| {condition_id} |")
    ]
    assert len(matches) == 1, (
        f"expected exactly one '{condition_id}' manifest row in the real "
        f"docs/domains/governance/contracts/ember-completeness.md, found {len(matches)} -- fixture "
        "assumption invalid, cannot construct the removal control"
    )
    del lines[matches[0]]
    manifest_path.write_text("".join(lines), encoding="utf-8")


# --- (1) positive: real production files, denominator floor + roll-ups counted, GREEN ---

def test_positive_denominator_floor_and_rollups_counted() -> None:
    # Independently recompute the §4 denominator straight from the real repo
    # file, importing the probe's own parser (not re-deriving a second regex
    # that could silently disagree with it) so this assertion tracks whatever
    # the probe actually counts, not a re-typed expectation.
    sys.path.insert(0, str(PROBES_DIR))
    import test_c_manifest as probe_mod  # noqa: E402

    goal_text = REAL_CONDITIONS_SPEC.read_text(encoding="utf-8")
    section4_ids = probe_mod._goal_section4_condition_ids(goal_text)

    check(
        f"positive: real §4 denominator >= {DENOMINATOR_FLOOR} (issue #715 fix floor; got {len(section4_ids)})",
        len(section4_ids) >= DENOMINATOR_FLOOR,
    )
    check(
        "positive: C-MANIFEST is counted in the denominator (the exact id gh #715 found dropped)",
        "C-MANIFEST" in section4_ids,
    )
    check(
        "positive: C-TALLY is counted in the denominator (the exact id gh #715 found dropped)",
        "C-TALLY" in section4_ids,
    )

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _seed_production_fixture(root)
        status, line = _run_probe(root)
        check(f"positive: real probe against unmodified production-shaped fixture emits GREEN (got: {line!r})",
              status == "GREEN")
        missing_ids = parse_missing_condition_ids(line)
        check(f"positive: structured missing_condition_ids is empty (got {missing_ids!r})",
              missing_ids == [])


# --- (2) INDEPENDENT removal: C-MANIFEST row deleted -> RED naming C-MANIFEST ---

def test_red_on_c_manifest_row_removed() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _spec_dst, manifest_dst = _seed_production_fixture(root)
        _delete_manifest_row(manifest_dst, "C-MANIFEST")

        status, line = _run_probe(root)
        check(f"C-MANIFEST removal: probe turns RED (got: {line!r})", status == "RED")
        missing_ids = parse_missing_condition_ids(line)
        # structured equality (not substring): the removed row is the ONLY
        # missing id -- independence from C-TALLY (untouched) is proven by
        # the exact list, not by absence of a guessed substring.
        check(f"C-MANIFEST removal: structured missing_condition_ids == ['C-MANIFEST'] (got {missing_ids!r})",
              missing_ids == ["C-MANIFEST"])


# --- (3) INDEPENDENT removal: C-TALLY row deleted -> RED naming C-TALLY ---

def test_red_on_c_tally_row_removed() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _spec_dst, manifest_dst = _seed_production_fixture(root)
        _delete_manifest_row(manifest_dst, "C-TALLY")

        status, line = _run_probe(root)
        check(f"C-TALLY removal: probe turns RED (got: {line!r})", status == "RED")
        missing_ids = parse_missing_condition_ids(line)
        check(f"C-TALLY removal: structured missing_condition_ids == ['C-TALLY'] (got {missing_ids!r})",
              missing_ids == ["C-TALLY"])


def main() -> int:
    test_positive_denominator_floor_and_rollups_counted()
    test_red_on_c_manifest_row_removed()
    test_red_on_c_tally_row_removed()
    print()
    if failures:
        print(f"FAILED {len(failures)}: {failures}")
        return 1
    print("ALL CASES PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
