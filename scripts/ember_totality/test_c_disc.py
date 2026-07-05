#!/usr/bin/env python3
"""test_c_disc.py -- STATUS PROBE for Ember goal condition C-DISC.

Registry text: docs/spec/conditions-v1.md sec 4.2 C-DISC (gh issue #94, Class-2 unwatched-
mandate recon rank #1, docs/audit/class2-unwatched-mandates-recon-20260704.md #3). R: GOAL
sec 8's program-level disconfirmation triggers (the project's own "central conjecture false"
kill signal -- EARNED_GROWTH, H0_CEILING, B2_BOOTSTRAP) are machine-evaluated on every board
run, never prose-only. "A trigger with no evaluator is prose" (GOAL.md's own words) -- before
this CHK, zero code referenced BOOTSTRAP_FAIL or the escalation-object path outside GOAL.md's
own text (docs/audit/class2-unwatched-mandates-recon-20260704.md #3, blast-radius rank #1).

CHK enforced here: `disconfirmation_leg.run_disconfirmation_leg(ROOT)` subprocess-executes
scripts/check_disconfirmation_triggers.py with dual-source verdict resolution (process exit
code cross-checked against the checker's own printed verdict line, reusing enforcement_leg.py's
_run_one_checker UNMODIFIED -- the same C-ENF/C-MILE pattern, not a reimplementation):

  - executed == True AND verdict == "PASS" (no hinge fired-and-unacknowledged: either no hinge
    has fired yet, or every fired hinge carries a valid escalation or override object) -- GREEN;
  - "FAIL" (checker ran, agreed at least one hinge fired with no escalation/override) -- RED;
  - "DISAGREEMENT" (exit code and verdict line conflict -- the probe-verdict-gate failure
    class) -- RED;
  - "UNRESOLVABLE" (timeout / missing checker / unparseable output) -- RED.

Unlike C-MILE (which has NO honestly-closed non-PASS state), a FIRED hinge here is not itself a
violation -- GOAL sec 8's own text is "the system may not continue past a fired trigger AS IF
IT HAD NOT FIRED," i.e. the violation is an unacknowledged fire, not the fire itself. Fire
history is permanent (maintainer ruling R7): an operator override returns this CHK to GREEN,
but the underlying attempts record keeps the fire; nothing here erases that a trigger fired.

Fail-closed: disconfirmation_leg.py or enforcement_leg.py missing/unimportable = RED (the leg
itself is gone -- that IS the regression), never UNEVALUABLE. UNEVALUABLE is reserved for
environment failure (no usable ROOT).

DISCIPLINE: status probe -- always exits 0, one line, real bytes decide, no hardcoded verdict.
RED / GREEN / UNEVALUABLE(env).
"""
from __future__ import annotations

import os
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
CANDIDATE_ROOTS = [p for p in (os.environ.get("EMBER_TOTALITY_ROOT"), REPO_ROOT) if p]
ROOT = next((r for r in CANDIDATE_ROOTS if os.path.isdir(r)), None)

INVALID_TOKENS = [
    "invalid_disconfirmation_regression",
]

CHECKER_NAME = "check_disconfirmation_triggers"


def emit(color, reason):
    print(f"{color} {reason}")
    sys.exit(0)


def main():
    if ROOT is None:
        emit("UNEVALUABLE", "C-DISC: no usable contract root (env)")

    sys.path.insert(0, os.path.join(ROOT, "scripts", "ember_totality"))
    try:
        from disconfirmation_leg import run_disconfirmation_leg  # noqa: E402
    except Exception as e:  # missing/broken module IS the regression -- fail closed
        emit("RED", f"C-DISC: disconfirmation_leg unimportable ({type(e).__name__}: {e}) "
                    f"-- the disconfirmation-trigger leg itself is gone [invalid_disconfirmation_regression]")

    from pathlib import Path
    try:
        results = run_disconfirmation_leg(Path(ROOT))
    except Exception as e:
        emit("RED", f"C-DISC: run_disconfirmation_leg raised {type(e).__name__}: {e} "
                    f"[invalid_disconfirmation_regression]")

    if not isinstance(results, dict) or CHECKER_NAME not in results:
        emit("RED", f"C-DISC: leg returned no result for {CHECKER_NAME!r} [invalid_disconfirmation_regression]")

    r = results[CHECKER_NAME]
    verdict = r.get("verdict")

    if not r.get("executed"):
        emit("RED", f"C-DISC: {CHECKER_NAME} never executed ({r.get('reason')}) "
                    f"[invalid_disconfirmation_regression]")

    if verdict != "PASS":
        emit("RED", f"C-DISC: {CHECKER_NAME} verdict {verdict!r} "
                    f"({r.get('reason') or r.get('verdict_line')}) [invalid_disconfirmation_regression]")

    emit("GREEN", f"C-DISC CHK satisfied: {CHECKER_NAME} executed with coherent PASS "
                  f"dual-source verdict -- {r.get('verdict_line')!r} "
                  f"({r.get('wall_s')}s, exit {r.get('exit_code')})")


if __name__ == "__main__":
    main()
