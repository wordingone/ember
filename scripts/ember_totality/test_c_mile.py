#!/usr/bin/env python3
"""test_c_mile.py -- STATUS PROBE for Ember goal condition C-MILE.

Registry text: docs/spec/conditions-v1.md SS4.2 C-MILE (Class-2 item 2, docs/audit/
class2-unwatched-mandates-recon-20260704.md #2, parent gh issue #35). R: the milestone
lattice (docs/spec/milestones-v1.md sections A/C/D) EXECUTES and returns a coherent
verdict against its own source-of-truth inputs -- a GREEN board can never again coexist
with a silently broken/tampered/stale milestone-vs-lattice mirror (the checker existed,
landed 2026-07-01, but the board only ever tamper-hashed it, never ran it -- the same
un-wired shape C-ENF cured for the publication/energy-law layer, issue #38).

CHK enforced here: `milestone_leg.run_milestone_leg(ROOT)` subprocess-executes
scripts/check_milestone_reconciliation.py with dual-source verdict resolution (process
exit code cross-checked against the checker's own printed verdict line, reusing
enforcement_leg.py's _run_one_checker UNMODIFIED -- exactly the C-ENF pattern, not a
reimplementation):

  - executed == True AND verdict == "PASS" (both exit code and printed verdict line
    agree the checker passed) -- GREEN;
  - "FAIL" (checker ran, agreed it failed) -- RED;
  - "DISAGREEMENT" (exit code and verdict line conflict -- the probe-verdict-gate
    failure class) -- RED;
  - "UNRESOLVABLE" (timeout / missing checker / unparseable output -- including the
    checker's own ParseError/exception path, which prints only to stderr and leaves no
    stdout line matching the verdict regex) -- RED.

Unlike C-ENF's check_publication_gate conjunct (an endgame gate honestly CLOSED
pre-completion, so a coherent FAIL is GREEN-compatible there), check_milestone_
reconciliation.py's own contract has no such "honestly closed" state: docs/spec/
milestones-v1.md's Validation hook section treats (a) and (c) as FATAL-on-violation and
only (b) (the lattice-vs-PROBLEMS.md gates diff) as report-only-never-fatal. So here,
unlike C-ENF, a coherent FAIL is NOT GREEN-compatible -- only PASS is.

Fail-closed: milestone_leg.py or enforcement_leg.py missing/unimportable = RED (the leg
itself is gone -- that IS the regression), never UNEVALUABLE. UNEVALUABLE is reserved for
environment failure (no usable ROOT).

DISCIPLINE: status probe -- always exits 0, one line, real bytes decide, no hardcoded
verdict. RED / GREEN / UNEVALUABLE(env).
"""
from __future__ import annotations

import os
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
CANDIDATE_ROOTS = [p for p in (os.environ.get("EMBER_TOTALITY_ROOT"), REPO_ROOT) if p]
ROOT = next((r for r in CANDIDATE_ROOTS if os.path.isdir(r)), None)

INVALID_TOKENS = [
    "invalid_milestone_regression",
]

CHECKER_NAME = "check_milestone_reconciliation"


def emit(color, reason):
    print(f"{color} {reason}")
    sys.exit(0)


def main():
    if ROOT is None:
        emit("UNEVALUABLE", "C-MILE: no usable contract root (env)")

    sys.path.insert(0, os.path.join(ROOT, "scripts", "ember_totality"))
    try:
        from milestone_leg import run_milestone_leg  # noqa: E402
    except Exception as e:  # missing/broken module IS the regression -- fail closed
        emit("RED", f"C-MILE: milestone_leg unimportable ({type(e).__name__}: {e}) "
                    f"-- the milestone-reconciliation leg itself is gone [invalid_milestone_regression]")

    from pathlib import Path
    try:
        results = run_milestone_leg(Path(ROOT))
    except Exception as e:
        emit("RED", f"C-MILE: run_milestone_leg raised {type(e).__name__}: {e} "
                    f"[invalid_milestone_regression]")

    if not isinstance(results, dict) or CHECKER_NAME not in results:
        emit("RED", f"C-MILE: leg returned no result for {CHECKER_NAME!r} [invalid_milestone_regression]")

    r = results[CHECKER_NAME]
    verdict = r.get("verdict")

    if not r.get("executed"):
        emit("RED", f"C-MILE: {CHECKER_NAME} never executed ({r.get('reason')}) "
                    f"[invalid_milestone_regression]")

    if verdict != "PASS":
        emit("RED", f"C-MILE: {CHECKER_NAME} verdict {verdict!r} "
                    f"({r.get('reason') or r.get('verdict_line')}) [invalid_milestone_regression]")

    emit("GREEN", f"C-MILE CHK satisfied: {CHECKER_NAME} executed with coherent PASS "
                  f"dual-source verdict -- {r.get('verdict_line')!r} "
                  f"({r.get('wall_s')}s, exit {r.get('exit_code')})")


if __name__ == "__main__":
    main()
