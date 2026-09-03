#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""test_c_enf.py — STATUS PROBE for Ember goal condition C-ENF.

Registry text: docs/domains/governance/spec/conditions-v1.md §4.2 C-ENF (gh issue #38, Class-2
cure, parent #35). R: the standalone enforcement layer (publication gate +
energy-law checker) EXECUTES and returns coherent verdicts — a GREEN board
can never again coexist with a silently broken/tampered enforcement layer.

CHK enforced here: `enforcement_leg.run_enforcement_leg(ROOT)` subprocess-
executes both checkers with dual-source verdict resolution (process exit
code cross-checked against the checker's own printed verdict line). The
condition is EXECUTION INTEGRITY, deliberately NOT the publication gate's
own open/closed verdict:

  - every registered checker: executed == True AND verdict in {PASS, FAIL}
    (a coherent, dual-source-agreed verdict either way);
  - "DISAGREEMENT" (exit code and verdict line conflict — the probe-verdict-
    gate failure class: probes that exit 0 while printing RED) = RED;
  - "UNRESOLVABLE" (timeout / missing checker / unparseable output) = RED;
  - check_energy_law_theory is a selftest: its verdict must be PASS;
  - check_publication_gate is the ENDGAME publication-readiness gate
    (kernel freeze, earned rung, BOOTSTRAP_PASS, claims map, research-focus
    test): its honest verdict pre-publication is FAIL (CLOSED). FAIL is
    therefore a GREEN-compatible state here; what this row refuses to
    tolerate is the gate not RUNNING or not making sense. Its own opening
    is judged by publication-v1.md §3, never by this row.

Fail-closed: enforcement_leg.py missing or unimportable = RED (the layer
itself is gone — that IS the regression), never UNEVALUABLE. UNEVALUABLE is
reserved for environment failure (no usable ROOT).

DISCIPLINE: status probe — always exits 0, one line, real bytes decide, no
hardcoded verdict. RED / GREEN / UNEVALUABLE(env).
"""
from __future__ import annotations

import os
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', '..', '..'))
CANDIDATE_ROOTS = [p for p in (os.environ.get("EMBER_TOTALITY_ROOT"), REPO_ROOT) if p]
ROOT = next((r for r in CANDIDATE_ROOTS if os.path.isdir(r)), None)

INVALID_TOKENS = [
    "invalid_enforcement_regression",
]

# The selftest checker whose verdict must itself be PASS (not merely coherent).
SELFTEST_CHECKERS = {"check_energy_law_theory"}
# Checkers whose honest verdict may be PASS or FAIL (endgame gates, closed
# until the goal nears completion) — coherence required, direction not.
EITHER_VERDICT_CHECKERS = {"check_publication_gate"}


def emit(color, reason):
    print(f"{color} {reason}")
    sys.exit(0)


def main():
    if ROOT is None:
        emit("UNEVALUABLE", "C-ENF: no usable contract root (env)")

    sys.path.insert(0, os.path.join(ROOT, "scripts", "ember_totality"))
    try:
        from enforcement_leg import run_enforcement_leg  # noqa: E402
    except Exception as e:  # missing/broken module IS the regression — fail closed
        emit("RED", f"C-ENF: enforcement_leg unimportable ({type(e).__name__}: {e}) "
                    f"-- the enforcement layer itself is gone [invalid_enforcement_regression]")

    from pathlib import Path
    try:
        results = run_enforcement_leg(Path(ROOT))
    except Exception as e:
        emit("RED", f"C-ENF: run_enforcement_leg raised {type(e).__name__}: {e} "
                    f"[invalid_enforcement_regression]")

    if not isinstance(results, dict) or not results:
        emit("RED", "C-ENF: leg returned no checker results [invalid_enforcement_regression]")

    expected = SELFTEST_CHECKERS | EITHER_VERDICT_CHECKERS
    missing = sorted(expected - set(results))
    if missing:
        emit("RED", f"C-ENF: registered checker(s) absent from leg results: {missing} "
                    f"[invalid_enforcement_regression]")

    problems = []
    for name, r in sorted(results.items()):
        verdict = r.get("verdict")
        if not r.get("executed"):
            problems.append(f"{name}: never executed ({r.get('reason')})")
        elif verdict not in ("PASS", "FAIL"):
            problems.append(f"{name}: verdict {verdict!r} ({r.get('reason') or r.get('verdict_line')})")
        elif name in SELFTEST_CHECKERS and verdict != "PASS":
            problems.append(f"{name}: selftest verdict {verdict} (line: {r.get('verdict_line')!r})")

    if problems:
        emit("RED", "C-ENF: enforcement layer incoherent -- " + "; ".join(problems) +
                    " [invalid_enforcement_regression]")

    detail = ", ".join(
        f"{name}={r.get('verdict')} ({r.get('wall_s')}s, exit {r.get('exit_code')})"
        for name, r in sorted(results.items())
    )
    emit("GREEN", f"C-ENF CHK satisfied: all checkers executed with coherent dual-source "
                  f"verdicts -- {detail}; publication gate direction judged by "
                  f"publication-v1.md sec3, not this row")


if __name__ == "__main__":
    main()
