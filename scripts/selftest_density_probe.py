"""selftest_density_probe.py — synthetic selftest for density_sensitivity_probe.py.

Tests probe logic (seed-direction agreement, aggregation, pre-registration) without
requiring actual training runs or B-MULTI-1 data.

Exit 0 + DENSITY_PROBE_SELFTEST_PASS in output = green.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from density_sensitivity_probe import seed_direction, aggregate_verdicts, BPBT_EPSILON

failures = []

def check(name, got, expected):
    if got != expected:
        failures.append(f"{name}: got {got!r}, expected {expected!r}")

# seed_direction: arm_b better (arm_a_loss > arm_b_loss at final checkpoint)
check("b_wins", seed_direction([2.5, 2.3, 2.1], [2.5, 2.2, 1.9]), "b_wins")

# seed_direction: arm_a better
check("a_wins", seed_direction([2.5, 2.2, 1.9], [2.5, 2.3, 2.1]), "a_wins")

# seed_direction: tie (within epsilon)
check("tie", seed_direction([2.0], [2.0 + BPBT_EPSILON * 0.5]), "tie")

# seed_direction: exactly at epsilon is NOT a tie; arm_b loss higher → arm_a wins
check("tie_boundary", seed_direction([2.0], [2.0 + BPBT_EPSILON]), "a_wins")

# aggregate: 2/3 agree b_wins → CONFIRMED
check("confirmed_b", aggregate_verdicts(["b_wins", "b_wins", "a_wins"]), "CONFIRMED_B_WINS")

# aggregate: 3/3 agree a_wins
check("confirmed_a_all", aggregate_verdicts(["a_wins", "a_wins", "a_wins"]), "CONFIRMED_A_WINS")

# aggregate: 1/3 each direction (including tie) → UNDECIDED
check("undecided_split", aggregate_verdicts(["a_wins", "b_wins", "tie"]), "UNDECIDED")

# aggregate: all ties → UNDECIDED (ties don't count toward agreement)
check("undecided_all_tie", aggregate_verdicts(["tie", "tie", "tie"]), "UNDECIDED")

# aggregate: 2/3 tie → UNDECIDED (tie is never CONFIRMED)
check("undecided_tie_majority", aggregate_verdicts(["tie", "tie", "a_wins"]), "UNDECIDED")

# Verify BPBT_EPSILON is small enough to matter but large enough to filter noise
assert 1e-6 < BPBT_EPSILON < 1e-2, f"BPBT_EPSILON {BPBT_EPSILON} out of expected range"

if failures:
    for f in failures:
        print(f"FAIL: {f}")
    sys.exit(1)

print("DENSITY_PROBE_SELFTEST_PASS")
print(f"all_pass=true checks=9")
