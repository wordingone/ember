#!/usr/bin/env python3
"""Ember state-dependent cognitive-mode selector (C12).

Deterministic policy: a six-field state vector (evidence_strength,
uncertainty, verifier_state, headroom, blocker_present, risk_level) selects
exactly one of the 12 registry-named cognitive modes:

    observe, orient, hypothesize, simulate, act, verify,
    consolidate, sleep, ask, refuse, rollback, report

This is a decision policy, not a fixed schedule: the same input state always
produces the same mode (deterministic), but different states produce
different modes (state-conditioned) -- the property C12's "does NOT count"
clause rules out for a fixed equal-duration / round-robin timer substitute.

Each mode carries a MODE_GATE entry describing how a consuming cycle must
change its real behavior for that mode (forced_promotion, skip_act,
retry_verifier, budget_multiplier). src/ember/governance/scripts/ember_mvp_cycle.py binds this
gate load-bearingly -- see run_fixture_cycle(use_cognitive_mode_policy=...).

CLI:
    --selftest    Exercises all 12 modes (canonical + boundary states) and
                  the gate-table shape. Prints
                  EMBER_COGNITIVE_MODE_POLICY_SELFTEST_PASS on success.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import asdict, dataclass
from typing import Any

MODES: tuple[str, ...] = (
    "observe", "orient", "hypothesize", "simulate", "act", "verify",
    "consolidate", "sleep", "ask", "refuse", "rollback", "report",
)

VERIFIER_STATES: tuple[str, ...] = ("none", "pending", "pass", "fail")
RISK_LEVELS: tuple[str, ...] = ("low", "medium", "high")

# --- Thresholds (named, so a boundary test can assert on both sides) --------
SLEEP_HEADROOM_THRESHOLD = 0.10
CONSOLIDATE_HEADROOM_THRESHOLD = 0.40
LOW_EVIDENCE_THRESHOLD = 0.30
REPORT_EVIDENCE_THRESHOLD = 0.75
HIGH_UNCERTAINTY_THRESHOLD = 0.60
MODERATE_UNCERTAINTY_THRESHOLD = 0.30
REPORT_UNCERTAINTY_THRESHOLD = 0.20


class CognitiveModePolicyError(ValueError):
    """Raised on a malformed state vector."""


@dataclass(frozen=True)
class CognitiveState:
    evidence_strength: float   # 0.0-1.0: observation/evidence gathered so far
    uncertainty: float         # 0.0-1.0: unresolved ambiguity in the current plan
    verifier_state: str        # "none" | "pending" | "pass" | "fail"
    headroom: float            # 0.0-1.0: remaining resource/time budget fraction
    blocker_present: bool      # execution cannot proceed without external input/resource
    risk_level: str            # "low" | "medium" | "high"

    def __post_init__(self) -> None:
        if not (0.0 <= self.evidence_strength <= 1.0):
            raise CognitiveModePolicyError(f"evidence_strength out of [0,1]: {self.evidence_strength!r}")
        if not (0.0 <= self.uncertainty <= 1.0):
            raise CognitiveModePolicyError(f"uncertainty out of [0,1]: {self.uncertainty!r}")
        if not (0.0 <= self.headroom <= 1.0):
            raise CognitiveModePolicyError(f"headroom out of [0,1]: {self.headroom!r}")
        if self.verifier_state not in VERIFIER_STATES:
            raise CognitiveModePolicyError(f"verifier_state invalid: {self.verifier_state!r}")
        if self.risk_level not in RISK_LEVELS:
            raise CognitiveModePolicyError(f"risk_level invalid: {self.risk_level!r}")


def select_mode(state: CognitiveState) -> tuple[str, str]:
    """Return (mode, reason) for the given state. Pure function, no I/O.

    Priority order (first match wins) -- this is the state-dependent
    cognitive_mode_selector: resource exhaustion and verifier failure are
    checked ahead of blockers, which are checked ahead of the normal
    observe->orient->hypothesize->simulate->act->verify->consolidate->report
    progression.
    """
    s = state

    if s.headroom <= SLEEP_HEADROOM_THRESHOLD:
        return "sleep", "sleep_pressure_exceeds_threshold"

    if s.verifier_state == "fail":
        return "rollback", "verifier_state_fail_triggers_rollback"

    if s.blocker_present and s.risk_level == "high":
        return "refuse", "blocker_present_and_risk_high_triggers_refuse"

    if s.blocker_present:
        return "ask", "blocker_present_without_high_risk_triggers_ask"

    if s.verifier_state == "pass" and s.headroom <= CONSOLIDATE_HEADROOM_THRESHOLD:
        return "consolidate", "verifier_pass_and_headroom_below_consolidate_threshold"

    if (
        s.verifier_state == "pass"
        and s.evidence_strength >= REPORT_EVIDENCE_THRESHOLD
        and s.uncertainty <= REPORT_UNCERTAINTY_THRESHOLD
    ):
        return "report", "verifier_pass_high_evidence_low_uncertainty_triggers_report"

    if s.verifier_state == "pending":
        return "verify", "verifier_state_pending_triggers_verify"

    if s.evidence_strength < LOW_EVIDENCE_THRESHOLD:
        return "observe", "evidence_strength_below_threshold_triggers_observe"

    if s.uncertainty >= HIGH_UNCERTAINTY_THRESHOLD:
        return "orient", "uncertainty_at_or_above_high_threshold_triggers_orient"

    if s.uncertainty >= MODERATE_UNCERTAINTY_THRESHOLD:
        return "hypothesize", "uncertainty_at_or_above_moderate_threshold_triggers_hypothesize"

    if s.risk_level != "low":
        return "simulate", "risk_not_low_triggers_simulate_before_acting"

    return "act", "evidence_sufficient_uncertainty_low_risk_low_triggers_act"


def classify(
    evidence_strength: float,
    uncertainty: float,
    verifier_state: str,
    headroom: float,
    blocker_present: bool,
    risk_level: str,
) -> tuple[str, str]:
    """Convenience wrapper: build the state vector and select a mode."""
    return select_mode(
        CognitiveState(
            evidence_strength=evidence_strength,
            uncertainty=uncertainty,
            verifier_state=verifier_state,
            headroom=headroom,
            blocker_present=blocker_present,
            risk_level=risk_level,
        )
    )


# ---------------------------------------------------------------------------
# Mode -> real-cycle gate. A consuming cycle (ember_mvp_cycle.run_fixture_cycle)
# reads this table to decide: does the requested promotion get overridden
# (forced_promotion), is the candidate action skipped (skip_act), does the
# verifier stage retry (retry_verifier), and does the remaining budget shrink
# (budget_multiplier). Every one of the 12 modes has an entry, even the
# pass-through ones -- there is no default/fallback gate, so a mode can never
# silently be un-gated by omission.
# ---------------------------------------------------------------------------
MODE_GATE: dict[str, dict[str, Any]] = {
    "observe":     {"forced_promotion": None,       "skip_act": False, "retry_verifier": False, "budget_multiplier": 1.0},
    "orient":      {"forced_promotion": None,       "skip_act": False, "retry_verifier": False, "budget_multiplier": 1.0},
    "hypothesize": {"forced_promotion": None,       "skip_act": False, "retry_verifier": False, "budget_multiplier": 1.0},
    "simulate":    {"forced_promotion": None,       "skip_act": False, "retry_verifier": False, "budget_multiplier": 1.0},
    "act":         {"forced_promotion": None,       "skip_act": False, "retry_verifier": False, "budget_multiplier": 1.0},
    "verify":      {"forced_promotion": None,       "skip_act": False, "retry_verifier": True,  "budget_multiplier": 1.0},
    "consolidate": {"forced_promotion": None,       "skip_act": False, "retry_verifier": False, "budget_multiplier": 0.5},
    "report":      {"forced_promotion": "accepted", "skip_act": False, "retry_verifier": False, "budget_multiplier": 1.0},
    "sleep":       {"forced_promotion": "rejected", "skip_act": True,  "retry_verifier": False, "budget_multiplier": 0.25},
    "ask":         {"forced_promotion": "rejected", "skip_act": True,  "retry_verifier": False, "budget_multiplier": 1.0},
    "refuse":      {"forced_promotion": "rejected", "skip_act": True,  "retry_verifier": False, "budget_multiplier": 1.0},
    "rollback":    {"forced_promotion": "rejected", "skip_act": True,  "retry_verifier": False, "budget_multiplier": 1.0},
}

assert set(MODE_GATE.keys()) == set(MODES), "MODE_GATE must cover exactly the 12 registry modes"


def gate_for_mode(mode: str) -> dict[str, Any]:
    if mode not in MODE_GATE:
        raise CognitiveModePolicyError(f"no gate registered for mode: {mode!r}")
    return MODE_GATE[mode]


# ---------------------------------------------------------------------------
# Selftest
# ---------------------------------------------------------------------------

def _selftest() -> int:
    failures: list[str] = []

    def check(label: str, state_kwargs: dict[str, Any], expected_mode: str) -> None:
        state = CognitiveState(**state_kwargs)
        mode, reason = select_mode(state)
        if mode != expected_mode:
            failures.append(f"{label}: expected mode={expected_mode!r}, got {mode!r} (reason={reason!r})")
        if mode not in MODE_GATE:
            failures.append(f"{label}: mode {mode!r} has no MODE_GATE entry")

    base = dict(evidence_strength=0.70, uncertainty=0.10, verifier_state="none", headroom=0.90,
                blocker_present=False, risk_level="low")

    # --- Canonical state for each of the 12 modes -------------------------
    check("canonical-observe", {**base, "evidence_strength": 0.10}, "observe")
    check("canonical-orient", {**base, "evidence_strength": 0.50, "uncertainty": 0.80}, "orient")
    check("canonical-hypothesize", {**base, "evidence_strength": 0.50, "uncertainty": 0.45}, "hypothesize")
    check("canonical-simulate", {**base, "uncertainty": 0.10, "risk_level": "medium"}, "simulate")
    check("canonical-act", base, "act")
    check("canonical-verify", {**base, "verifier_state": "pending"}, "verify")
    check("canonical-consolidate", {**base, "verifier_state": "pass", "headroom": 0.30}, "consolidate")
    check("canonical-report", {**base, "evidence_strength": 0.90, "uncertainty": 0.05, "verifier_state": "pass"}, "report")
    check("canonical-sleep", {**base, "headroom": 0.05}, "sleep")
    check("canonical-ask", {**base, "blocker_present": True}, "ask")
    check("canonical-refuse", {**base, "blocker_present": True, "risk_level": "high"}, "refuse")
    check("canonical-rollback", {**base, "verifier_state": "fail"}, "rollback")

    # --- Boundary cases (threshold edges, both sides) ---------------------
    check("boundary-sleep-at-threshold", {**base, "headroom": SLEEP_HEADROOM_THRESHOLD}, "sleep")
    check("boundary-sleep-just-above", {**base, "headroom": SLEEP_HEADROOM_THRESHOLD + 0.0001}, "act")

    check("boundary-observe-just-below", {**base, "evidence_strength": LOW_EVIDENCE_THRESHOLD - 0.0001}, "observe")
    check("boundary-observe-at-threshold-not-observe", {**base, "evidence_strength": LOW_EVIDENCE_THRESHOLD}, "act")

    check("boundary-orient-at-threshold", {**base, "evidence_strength": 0.50, "uncertainty": HIGH_UNCERTAINTY_THRESHOLD}, "orient")
    check("boundary-orient-just-below-is-hypothesize", {**base, "evidence_strength": 0.50, "uncertainty": HIGH_UNCERTAINTY_THRESHOLD - 0.0001}, "hypothesize")

    check("boundary-hypothesize-at-threshold", {**base, "evidence_strength": 0.50, "uncertainty": MODERATE_UNCERTAINTY_THRESHOLD}, "hypothesize")
    check("boundary-hypothesize-just-below-is-act", {**base, "uncertainty": MODERATE_UNCERTAINTY_THRESHOLD - 0.0001}, "act")

    check("boundary-consolidate-at-threshold", {**base, "verifier_state": "pass", "headroom": CONSOLIDATE_HEADROOM_THRESHOLD}, "consolidate")
    check("boundary-consolidate-just-above-falls-through", {**base, "verifier_state": "pass", "headroom": CONSOLIDATE_HEADROOM_THRESHOLD + 0.0001, "evidence_strength": 0.50, "uncertainty": 0.50}, "hypothesize")

    check("boundary-report-at-threshold", {**base, "verifier_state": "pass", "headroom": 0.90, "evidence_strength": REPORT_EVIDENCE_THRESHOLD, "uncertainty": REPORT_UNCERTAINTY_THRESHOLD}, "report")
    check("boundary-report-just-below-evidence-falls-to-act", {**base, "verifier_state": "pass", "headroom": 0.90, "evidence_strength": REPORT_EVIDENCE_THRESHOLD - 0.0001, "uncertainty": REPORT_UNCERTAINTY_THRESHOLD}, "act")

    # --- Priority ordering: earlier rules win over later ones --------------
    check("priority-sleep-beats-verifier-fail", {**base, "headroom": 0.05, "verifier_state": "fail"}, "sleep")
    check("priority-verifier-fail-beats-blocker-refuse", {**base, "verifier_state": "fail", "blocker_present": True, "risk_level": "high"}, "rollback")
    check("priority-refuse-beats-ask-on-high-risk", {**base, "blocker_present": True, "risk_level": "high"}, "refuse")

    # --- Determinism: same input twice -> same output ----------------------
    st = CognitiveState(**base)
    if select_mode(st) != select_mode(st):
        failures.append("determinism: select_mode(same state) produced different results across calls")

    # --- Gate table shape ---------------------------------------------------
    if set(MODE_GATE.keys()) != set(MODES):
        failures.append(f"MODE_GATE keys {sorted(MODE_GATE.keys())} != MODES {sorted(MODES)}")
    for mode, gate in MODE_GATE.items():
        for field in ("forced_promotion", "skip_act", "retry_verifier", "budget_multiplier"):
            if field not in gate:
                failures.append(f"MODE_GATE[{mode!r}] missing field {field!r}")

    # --- classify() convenience wrapper matches select_mode() ---------------
    mode1, reason1 = select_mode(CognitiveState(**base))
    mode2, reason2 = classify(**base)
    if (mode1, reason1) != (mode2, reason2):
        failures.append("classify() diverged from select_mode() on identical input")

    if failures:
        for f in failures:
            print(f"FAIL: {f}", file=sys.stderr)
        return 1

    print("EMBER_COGNITIVE_MODE_POLICY_SELFTEST_PASS")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--classify", action="store_true", help="classify a state vector given as flags below")
    ap.add_argument("--evidence-strength", type=float, default=0.5)
    ap.add_argument("--uncertainty", type=float, default=0.5)
    ap.add_argument("--verifier-state", default="none", choices=VERIFIER_STATES)
    ap.add_argument("--headroom", type=float, default=1.0)
    ap.add_argument("--blocker-present", action="store_true")
    ap.add_argument("--risk-level", default="low", choices=RISK_LEVELS)
    args = ap.parse_args()

    if args.selftest:
        return _selftest()

    if args.classify:
        mode, reason = classify(
            evidence_strength=args.evidence_strength,
            uncertainty=args.uncertainty,
            verifier_state=args.verifier_state,
            headroom=args.headroom,
            blocker_present=args.blocker_present,
            risk_level=args.risk_level,
        )
        print(f"mode={mode} reason={reason} gate={gate_for_mode(mode)}")
        return 0

    ap.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
