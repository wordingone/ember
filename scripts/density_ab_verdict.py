"""density_ab_verdict.py — aggregate 4 density A/B receipts into a combined verdict.

Reads all 4 per-cell receipts (arm-a-seed0, arm-a-seed1, arm-b-seed0, arm-b-seed1),
computes per-arm mean wcode_rate at 50% and 100% probe points, delta in percentage
points, slope direction, and emits a verdict receipt.

Verdict classes (directional; n=2 per arm, no formal power):
  DENSITY_CONFIRMED  — arm B (code-only) > arm A (bulk-mix) by >2pp at 100pct, BOTH seeds agree
  DENSITY_MARGINAL   — arm B > arm A by 0..2pp at 100pct, both seeds agree
  DENSITY_REVERSED   — arm A > arm B at 100pct, both seeds agree (mixed corpus wins)
  DENSITY_FLAT       — |delta| <= 0.5pp, both seeds agree (indistinguishable at this n)
  NO_VERDICT         — seeds disagree on direction; third seed required before any axis mapping
  INCOMPLETE         — fewer than 4 valid cells in receipts dir

c04 routing: route() from c04_pick_rehearsal.py is called with the density axis.
Only DENSITY_CONFIRMED maps to D-CONF (clears n=400 MDE in both seeds, directionally
agreeing). All under-MDE results (MARGINAL/REVERSED/FLAT) map to D-BELOW. NO_VERDICT
exits non-zero with no c04_pick block — spec rule 4, table must not fire on seed
disagreement.
"""
import glob
import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
NC = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from receipt_write import checked_write                # noqa: E402
from c04_pick_rehearsal import route                   # noqa: E402

RECEIPTS = f"{NC}/receipts"
TICKET = "DENSITY-AB-V1"

# arm B (code-only) > arm A by this many pp = CONFIRMED
CONFIRM_THRESHOLD_PP = 2.0
# |delta| <= this = FLAT
FLAT_THRESHOLD_PP = 0.5

# cap applied by route() at L10-FULL band-low: budget must be <=1.05 x tok_s x day
# 2.2B at 25.6k tok/s (PASS), 2.5B = 1.13d (MARGINAL). Table v1.1.
_C04_BUDGET_HI_PASS = 2.2e9


def _density_to_axis(verdict):
    """Map density verdict to c04-pick-table density axis.
    Only DENSITY_CONFIRMED clears the n=400 MDE in both seeds → D-CONF.
    All under-MDE outcomes (MARGINAL/REVERSED/FLAT) → D-BELOW.
    NO_VERDICT must never reach this function.
    """
    return "D-CONF" if verdict == "DENSITY_CONFIRMED" else "D-BELOW"


def _load_cell_receipts():
    """Load all DENSITY-AB-V1 receipts with status OK from the receipts dir."""
    cells = {}
    for path in sorted(glob.glob(f"{RECEIPTS}/density-ab-arm*-seed*.json")):
        try:
            r = json.load(open(path))
        except Exception:
            continue
        if r.get("ticket") != TICKET:
            continue
        arm = r.get("arm")
        seed = r.get("seed")
        cell = r.get("cell", {})
        status = cell.get("status")
        if status == "OK" and arm is not None and seed is not None:
            key = (arm, seed)
            # keep the latest receipt if multiple exist for same (arm, seed)
            if key not in cells or r["ts"] > cells[key]["ts"]:
                cells[key] = r
    return cells


def _extract_wcode(receipt):
    probes = receipt.get("cell", {}).get("probes", {})
    wr_50 = probes.get("50pct", {}).get("wcode_rate")
    wr_100 = probes.get("100pct", {}).get("wcode_rate")
    slope = receipt.get("cell", {}).get("slope")
    return wr_50, wr_100, slope


def main():
    cells = _load_cell_receipts()

    required = [("a", 0), ("a", 1), ("b", 0), ("b", 1)]
    missing = [k for k in required if k not in cells]

    ts_now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    if missing:
        receipt = {
            "ticket": "DENSITY-AB-VERDICT",
            "ts": ts_now,
            "issue": 225,
            "verdict": "INCOMPLETE",
            "missing_cells": [f"arm-{a}-seed{s}" for a, s in missing],
            "available_cells": [f"arm-{a}-seed{s}" for a, s in sorted(cells.keys())],
            "c04_pick": None,
        }
        out = f"{RECEIPTS}/density-ab-verdict-{ts_now}.json"
        checked_write(out, receipt)
        print(json.dumps({"verdict": "INCOMPLETE", "missing": missing}))
        return

    # Extract per-cell wcode rates
    rows = {}
    for (arm, seed) in required:
        wr50, wr100, slope = _extract_wcode(cells[(arm, seed)])
        rows[(arm, seed)] = {
            "wcode_50pct": wr50,
            "wcode_100pct": wr100,
            "slope": slope,
            "receipt_ts": cells[(arm, seed)]["ts"],
        }

    # Per-arm means
    arm_a_wr50 = [rows[("a", s)]["wcode_50pct"] for s in [0, 1] if rows[("a", s)]["wcode_50pct"] is not None]
    arm_a_wr100 = [rows[("a", s)]["wcode_100pct"] for s in [0, 1] if rows[("a", s)]["wcode_100pct"] is not None]
    arm_b_wr50 = [rows[("b", s)]["wcode_50pct"] for s in [0, 1] if rows[("b", s)]["wcode_50pct"] is not None]
    arm_b_wr100 = [rows[("b", s)]["wcode_100pct"] for s in [0, 1] if rows[("b", s)]["wcode_100pct"] is not None]

    mean_a_50 = round(sum(arm_a_wr50) / len(arm_a_wr50), 4) if arm_a_wr50 else None
    mean_a_100 = round(sum(arm_a_wr100) / len(arm_a_wr100), 4) if arm_a_wr100 else None
    mean_b_50 = round(sum(arm_b_wr50) / len(arm_b_wr50), 4) if arm_b_wr50 else None
    mean_b_100 = round(sum(arm_b_wr100) / len(arm_b_wr100), 4) if arm_b_wr100 else None

    # delta = B - A in percentage points (positive = code-only arm wins)
    delta_pp_100 = round((mean_b_100 - mean_a_100) * 100, 2) if (mean_b_100 is not None and mean_a_100 is not None) else None
    delta_pp_50 = round((mean_b_50 - mean_a_50) * 100, 2) if (mean_b_50 is not None and mean_a_50 is not None) else None

    # Spec rule 4: check per-seed direction agreement at 100pct before classifying.
    # If seed 0 and seed 1 disagree (one has B>A, other has A>=B) → NO_VERDICT.
    a0_wr100 = rows[("a", 0)]["wcode_100pct"]
    a1_wr100 = rows[("a", 1)]["wcode_100pct"]
    b0_wr100 = rows[("b", 0)]["wcode_100pct"]
    b1_wr100 = rows[("b", 1)]["wcode_100pct"]
    seed_agreement = None
    seed_disagree = False
    if all(v is not None for v in (a0_wr100, a1_wr100, b0_wr100, b1_wr100)):
        s0_b_wins = b0_wr100 > a0_wr100
        s1_b_wins = b1_wr100 > a1_wr100
        seed_disagree = s0_b_wins != s1_b_wins
        seed_agreement = {"seed0_b_wins": s0_b_wins, "seed1_b_wins": s1_b_wins}

    if seed_disagree:
        receipt = {
            "ticket": "DENSITY-AB-VERDICT",
            "ts": ts_now,
            "issue": 225,
            "verdict": "NO_VERDICT",
            "reason": "seeds disagree on direction at 100pct — spec rule 4 demands third seed before axis mapping",
            "seed_agreement": seed_agreement,
            "delta_pp_100pct": delta_pp_100,
            "delta_pp_50pct": delta_pp_50,
            "c04_pick": None,
        }
        out = f"{RECEIPTS}/density-ab-verdict-{ts_now}.json"
        checked_write(out, receipt)
        print(json.dumps({"verdict": "NO_VERDICT",
                          "error": "seed disagreement — third seed required before c04 pick"}))
        sys.exit(1)

    # Classify (both seeds agree on direction)
    if delta_pp_100 is None:
        verdict = "INCOMPLETE"
    elif abs(delta_pp_100) <= FLAT_THRESHOLD_PP:
        verdict = "DENSITY_FLAT"
    elif delta_pp_100 >= CONFIRM_THRESHOLD_PP:
        verdict = "DENSITY_CONFIRMED"
    elif delta_pp_100 > 0:
        verdict = "DENSITY_MARGINAL"
    else:
        verdict = "DENSITY_REVERSED"

    density_axis = _density_to_axis(verdict)
    c04_pick = {
        l10: route(l10, density_axis, budget_hi=_C04_BUDGET_HI_PASS if l10 == "FULL" else None)
        for l10 in ("FULL", "PART", "FAIL")
    }

    receipt = {
        "ticket": "DENSITY-AB-VERDICT",
        "ts": ts_now,
        "issue": 225,
        "verdict": verdict,
        "delta_pp_100pct": delta_pp_100,
        "delta_pp_50pct": delta_pp_50,
        "arm_a": {
            "label": "bulk-v0-mix",
            "code_fraction_proxy": 0.581,
            "mean_wcode_50pct": mean_a_50,
            "mean_wcode_100pct": mean_a_100,
            "cells": {f"seed{s}": rows[("a", s)] for s in [0, 1]},
        },
        "arm_b": {
            "label": "curated-code-only",
            "code_fraction_proxy": 1.0,
            "mean_wcode_50pct": mean_b_50,
            "mean_wcode_100pct": mean_b_100,
            "cells": {f"seed{s}": rows[("b", s)] for s in [0, 1]},
        },
        "thresholds": {
            "confirm_pp": CONFIRM_THRESHOLD_PP,
            "flat_pp": FLAT_THRESHOLD_PP,
        },
        "c04_pick": {
            "density_axis": density_axis,
            "budget_hi_cap": _C04_BUDGET_HI_PASS,
            "routes": c04_pick,
        },
        "caveats": [
            "code_fraction is a PROXY for the verified-density axis",
            "c01→c03 scale transfer is an assumption (directional, not precision)",
            f"n=2 seeds per arm — no formal statistical power; verdict is directional only",
            "c04_pick routes from c04_pick_rehearsal.route() — table v1.1, PASS cap=2.2B at L10-FULL",
        ],
    }

    out = f"{RECEIPTS}/density-ab-verdict-{ts_now}.json"
    checked_write(out, receipt)

    print(json.dumps({
        "verdict": verdict,
        "delta_pp_100pct": delta_pp_100,
        "arm_a_mean_wcode_100": mean_a_100,
        "arm_b_mean_wcode_100": mean_b_100,
        "c04_pick_L10_FULL": c04_pick["FULL"],
    }, indent=2))
    print(f"DENSITY_AB_VERDICT_DONE {os.path.relpath(out, NC)}")


if __name__ == "__main__":
    main()
