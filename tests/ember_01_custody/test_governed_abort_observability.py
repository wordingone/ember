# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""GOVERNED_ABORT_OBSERVABILITY failure-class regression guard (C0 ledger #1017).

Failure class: a GOVERNED abort (in-run pace-gate / watchdog / resource-headroom
self-abort) must be OBSERVABLE -- it must surface a readable record carrying the
abort REASON, never a silent exit. The failure mode = a governed abort fires but
produces no observable record, so a consumer/operator cannot tell a clean
governed abort from a crash or a hang.

Why this file and not tests/test_stabilize_v9_cure.py (the adjacent infra the
build spec named): that file's governed-abort observability coverage
(TestGovernedAbortReceipt / TestZeroStepAbortComposed) imports
`timeshare_pretrain` / `cbase_grow_rung2_stabilize`, and BOTH modules now raise
`SystemExit("historical_only: ... execution-denied")` unconditionally at import
(landed in origin/master; the sub-3B cbase trainer stack is retired). Those tests
can no longer be COLLECTED -- they are a dead guard, not a live one. So the birth
-relevant (clean-genesis 3B) governed-abort observability is guarded here against
the ACTIVE, non-denied governor: `scripts/governor.py`. That module's
`commit_margin_preflight` is the live headroom/commit-charge governed abort; it
is imported directly (torch is NOT required for the commit-margin path), CPU /
synthetic only, no GPU, no training, no real memory pressure.

RED-first / falsifiability: the observability property is asserted against the
REAL production `governor.commit_margin_preflight`, and a positive control proves
the reason-assertion is not vacuous -- a silenced variant (a governed abort that
raises with NO reason) is caught by the same predicate, so the guard REDs if
production ever regresses to a reason-less / silent abort.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import governor  # noqa: E402  (non-denied; commit-margin path needs no torch)

_GIB = 1 << 30


def _abort_record_is_observable(exc: BaseException) -> bool:
    """A governed abort is OBSERVABLE iff its surfaced record carries the abort
    REASON a consumer can read: the class token AND the discriminating
    arithmetic (required-vs-available), not a bare/blank exit. This predicate is
    what makes the guard fail-closed on a silent abort."""
    msg = str(exc)
    return ("COMMIT_MARGIN_REFUSED" in msg
            and "required" in msg
            and "commit available" in msg
            and "refusing launch" in msg)


class TestGovernedAbortObservability(unittest.TestCase):
    def test_over_budget_governed_abort_surfaces_a_readable_reason(self):
        # Feed the REAL production governor an impossible commit request so the
        # headroom governed abort MUST fire regardless of the host's actual free
        # commit (1 EiB expected-mapped is unsatisfiable on any machine).
        with self.assertRaises(SystemExit) as ctx:
            governor.commit_margin_preflight(1 << 60, margin_gb=4.0)
        self.assertTrue(
            _abort_record_is_observable(ctx.exception),
            "governed abort must surface the abort REASON (class token + "
            f"required-vs-available arithmetic), never a silent exit; got: "
            f"{str(ctx.exception)!r}")

    def test_within_budget_does_not_abort_and_returns_a_receipt(self):
        # Fail-closed ONLY on a real shortfall: a satisfiable request must not
        # raise. It returns either a PASS receipt (win32: real commit read) or a
        # NOT_APPLICABLE receipt (no commit-status source) -- both are the
        # non-abort branch, and both are readable receipts (never a silent exit).
        receipt = governor.commit_margin_preflight(1024, margin_gb=0.0)
        self.assertIsInstance(receipt, dict)
        self.assertIn(receipt.get("status"), ("PASS", "NOT_APPLICABLE"), receipt)

    def test_reason_predicate_is_falsifiable_positive_control(self):
        # The guard would be vacuous if _abort_record_is_observable accepted a
        # reason-less abort. Prove it distinguishes: the real production message
        # is observable; a silenced governed abort (the regression this class
        # guards) is NOT -- so the assertion above REDs the moment production
        # goes silent.
        try:
            governor.commit_margin_preflight(1 << 60, margin_gb=4.0)
            self.fail("expected the over-budget refusal to raise")
        except SystemExit as real_exc:
            self.assertTrue(_abort_record_is_observable(real_exc))
        silent_abort = SystemExit("")  # a governed abort with no observable reason
        self.assertFalse(
            _abort_record_is_observable(silent_abort),
            "predicate must reject a reason-less (silent) governed abort")


if __name__ == "__main__":
    unittest.main(verbosity=2)
