#!/usr/bin/env python3
"""c5c_readout.py -- C5(c) W-statistic readout grammar (issue #628; spec refs:
issue #123 comment 4929556629 "C5 mechanism-readout pre-registration v1" (the
SUPERSEDED two-point marginal-CI grammar) and issue #123 comment 4928342201
"F1-F4 falsifier fill" (the shared CI/bootstrap machinery this reuses -- paired
cluster-resampled bootstrap, B=10000, rng_seed=20260709). CPU-only: no model
loads, no GPU, no torch import.

GOAL.md C5(c): "a receipted scaling trend shows the gap to the dense control
WIDENING with scale -- a shrinking gap is the toy-model failure state, named."

DEFECT (independent-audit disposition, issue #628, reproduced verbatim below):
the registered two-point rule -- "C5(c) HOLDS (directionally) iff gap_claim >
gap_cheap with both gaps individually CI-resolved (lower bound > 0)" (issue
#123, comment 4929556629) -- does not actually test WIDENING. Counterexample:

    cheap = 0.20, CI95 = [0.01, 0.39]
    claim = 0.21, CI95 = [0.01, 0.41]
    -> both individually CI-resolved AND claim > cheap -> old rule says HOLDS.

    But W = gap_claim - gap_cheap = 0.01 has its OWN CI95 = [-0.27, +0.29] --
    straddles zero. Marginal CIs omit cross-rung covariance/uncertainty; W is
    not identifiable from the two marginal fields alone.

FROZEN CURE (issue #628, adopted per the #123 audit-lane disposition):
  (1) two points report DIRECTIONAL-ONLY; C5(c) itself stays UNRESOLVED.
  (2) W = gap_claim - gap_cheap, with its OWN joint cluster/seed bootstrap CI95.
        CI95(W).lower > 0  -> endpoint WIDENING
        CI95(W).upper < 0  -> endpoint SHRINKING (kills C5(c) outright)
        straddle           -> INCONCLUSIVE
  (3) constitutional clearance (a real C5(c) HOLDS) additionally requires a
      THIRD preregistered rung + a positive-slope / monotone-widening
      criterion WITH uncertainty (every step's widening itself CI-resolved,
      never just point-compared). Strengthening-only, acting-operator default
      (weakening any existing threshold would need operator word; this does
      not weaken anything -- it only adds ways for C5(c) to fail to clear).
  (4) all F1/F2/F3 falsifier gates are UNCHANGED and untouched by this module
      -- this is a pure C5(c) sub-clause reading, orthogonal to F1-F3.

STATUS AT THIS PR: this module NEVER scores a real governed run -- none has
launched as of issue #628 (queue #591 row 5 remains BLOCKED on A1/A3/Q6). It
is pre-launch readout machinery, parallel to the other scripts/c8_prelaunch/
tools (O2 compute_mde.py, O4 f2_schedule_generator.py, O5 run_ledger.py).

STAGE MARKER (reproduce-first commit): this revision of the file contains
ONLY the SUPERSEDED v1 rule (needed to reproduce the defect) plus a selftest
that ALSO calls the not-yet-implemented cure (verdict_from_w). Running
`--selftest` at this stage is EXPECTED TO FAIL (NameError) -- that failure is
the reproduce-first receipt for issue #628, executed against the exact
pre-fix blob. The next commit implements the cure and the same selftest
passes.

USAGE
-----
    python c5c_readout.py --selftest
"""
import sys


# ---------------------------------------------------------------------------
# SUPERSEDED v1 grammar (issue #123, comment 4929556629) -- kept ONLY to
# regression-test the counterexample it fails on (issue #628). Never call
# this for a real C5(c) verdict.
# ---------------------------------------------------------------------------

def marginal_two_point_rule_SUPERSEDED(gap_cheap, ci_cheap, gap_claim, ci_claim):
    """The registered v1 two-point rule (issue #123, comment 4929556629):
    'C5(c) HOLDS (directionally) iff gap_claim > gap_cheap with both gaps
    individually CI-resolved (lower bound > 0)'.

    SUPERSEDED by issue #628 -- this function is preserved verbatim, unused
    in any real verdict path, ONLY so the counterexample it fails on stays
    an executable regression test forever.
    """
    cheap_resolved = ci_cheap[0] > 0.0
    claim_resolved = ci_claim[0] > 0.0
    holds = bool(claim_resolved and cheap_resolved and gap_claim > gap_cheap)
    return "HOLDS" if holds else "UNRESOLVED"


# ---------------------------------------------------------------------------
# Selftest (reproduce-first stage: proves the defect AND that the cure is
# not yet implemented)
# ---------------------------------------------------------------------------

def _selftest() -> int:
    failures = []

    # --- REPRO: the SUPERSEDED marginal two-point rule reports HOLDS on the
    # issue #628 counterexample (the defect, executable, verbatim numbers). ---
    old_verdict = marginal_two_point_rule_SUPERSEDED(0.20, (0.01, 0.39), 0.21, (0.01, 0.41))
    if old_verdict != "HOLDS":
        failures.append(
            f"REPRO FAIL: expected the SUPERSEDED marginal rule to report HOLDS "
            f"on the issue #628 counterexample (proving the defect is real), "
            f"got {old_verdict!r}"
        )
    else:
        print("REPRO: marginal_two_point_rule_SUPERSEDED(...) == 'HOLDS' on the "
              "issue #628 counterexample -- defect reproduced")

    # --- CURE (not yet implemented at this stage): the same case must
    # resolve to INCONCLUSIVE under the W-statistic verdict rule. ---
    new_verdict = verdict_from_w(0.01, -0.27, 0.29)  # noqa: F821 (not yet defined -- expected)
    if new_verdict != "INCONCLUSIVE":
        failures.append(
            f"CURE FAIL: expected the W-statistic verdict to report INCONCLUSIVE "
            f"on the same counterexample, got {new_verdict!r}"
        )

    if failures:
        for f in failures:
            print(f"SELFTEST: {f}")
        return 1

    print("C5C_READOUT_SELFTEST_PASS")
    return 0


def main():
    import argparse
    ap = argparse.ArgumentParser(description="C5(c) W-statistic readout grammar (issue #628).")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        sys.exit(_selftest())
    ap.print_help()
    sys.exit(1)


if __name__ == "__main__":
    main()
