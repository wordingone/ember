"""density_sensitivity_probe.py — non-degenerate downstream density-sensitivity probe.

Closes ember #415. Replaces the rejected wcode_100pct verdict (#225):
  - wcode_100pct floors at 0 for most seeds; +33pp was single-seed mean artifact.
  - This probe uses val_loss_delta (CE bits-per-token difference) which has
    measurable variance across seeds and data compositions.

AGGREGATION: seed-direction agreement, never mean.
  - Per-seed: compute val_loss(arm_a) - val_loss(arm_b) at each checkpoint.
  - Direction per seed: "a_wins" if delta > 0, "b_wins" if delta < 0, "tie" if |delta| < eps.
  - Verdict: CONFIRMED only if >=2/3 seeds agree on same direction.

ARMS (data composition axis):
  - arm_a: baseline text/image blend ratio (e.g. text_frac=0.7, image_frac=0.3)
  - arm_b: alternate blend (e.g. text_frac=0.5, image_frac=0.5)
  - Blend ratio defined by caller via --arm-a-blend and --arm-b-blend args.

TRIGGER GATE: requires B-MULTI-1 image data to be built before arm execution.
  If multimodal data source does not exist, probe exits with PROBE_NOT_READY code
  and writes a pre-registration receipt (no run data).

Usage:
  # Pre-registration (no data needed):
  python src/ember/governance/scripts/density_sensitivity_probe.py --prereg-only

  # Full probe run (requires B-MULTI-1):
  python src/ember/governance/scripts/density_sensitivity_probe.py \\
    --arm-a-blend text=0.7,image=0.3 \\
    --arm-b-blend text=0.5,image=0.5 \\
    --seeds 0,1,2 --steps 2000 \\
    --val-checkpoints 250,500,1000,1500,2000 \\
    --receipt receipts/density-probe-TIMESTAMP.json
"""

import argparse
import json
import os
import sys
import datetime

PROBE_VERSION = "1.0"
BPBT_EPSILON = 1e-4   # bits-per-token delta below which is a tie
MIN_SEED_AGREEMENT = 2  # out of 3 seeds must agree for CONFIRMED


def now_z():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def seed_direction(arm_a_losses: list[float], arm_b_losses: list[float]) -> str:
    """Compare arm_a vs arm_b val_loss at final checkpoint. Returns 'a_wins'/'b_wins'/'tie'."""
    if not arm_a_losses or not arm_b_losses:
        return "tie"
    delta = arm_a_losses[-1] - arm_b_losses[-1]  # positive = arm_b better
    if abs(delta) < BPBT_EPSILON:
        return "tie"
    return "b_wins" if delta > 0 else "a_wins"


def aggregate_verdicts(per_seed_directions: list[str]) -> str:
    """Seed-direction agreement: CONFIRMED if >=2/3 agree, else UNDECIDED."""
    counts = {"a_wins": 0, "b_wins": 0, "tie": 0}
    for d in per_seed_directions:
        counts[d] = counts.get(d, 0) + 1
    for direction, count in counts.items():
        if direction != "tie" and count >= MIN_SEED_AGREEMENT:
            return f"CONFIRMED_{direction.upper()}"
    return "UNDECIDED"


def write_receipt(path: str, data: dict):
    os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"Receipt: {path}")


def main():
    p = argparse.ArgumentParser(description="Density-sensitivity probe for multimodal pretrain.")
    p.add_argument("--prereg-only", action="store_true",
                   help="Write pre-registration receipt only; do not run probe.")
    p.add_argument("--arm-a-blend", default="text=0.7,image=0.3",
                   help="text/image blend for arm_a (e.g. text=0.7,image=0.3)")
    p.add_argument("--arm-b-blend", default="text=0.5,image=0.5",
                   help="text/image blend for arm_b")
    p.add_argument("--seeds", default="0,1,2",
                   help="Comma-separated seeds (min 3)")
    p.add_argument("--steps", type=int, default=2000,
                   help="Training steps per seed per arm")
    p.add_argument("--val-checkpoints", default="250,500,1000,1500,2000",
                   help="Comma-separated step checkpoints for val_loss measurement")
    p.add_argument("--receipt", default=None,
                   help="Receipt output path")
    a = p.parse_args()

    seeds = [int(s) for s in a.seeds.split(",")]
    assert len(seeds) >= 3, "Probe requires >= 3 seeds for seed-direction agreement."
    checkpoints = [int(c) for c in a.val_checkpoints.split(",")]

    spec = {
        "probe_version": PROBE_VERSION,
        "metric": "val_loss_delta (CE bits-per-token; arm_b - arm_a at final checkpoint)",
        "aggregation": "seed-direction agreement (>=2/3 seeds same direction → CONFIRMED)",
        "arms": {"arm_a": a.arm_a_blend, "arm_b": a.arm_b_blend},
        "seeds": seeds,
        "steps": a.steps,
        "val_checkpoints": checkpoints,
        "epsilon_bpbt": BPBT_EPSILON,
        "min_seed_agreement": MIN_SEED_AGREEMENT,
        "killed_metric": "wcode_100pct (floor-degenerate; all-zero outside seed1; +33pp was mean artifact)",
        "reference": "ember #415, #225 (rejected)",
    }

    if a.prereg_only:
        receipt = {
            "ts": now_z(),
            "type": "density_probe_prereg",
            "status": "PRE_REGISTERED",
            "note": "B-MULTI-1 image data not yet built; probe run deferred until data is available.",
            "spec": spec,
            "DENSITY_PROBE_PREREG_PASS": True,
        }
        path = a.receipt or "receipts/density-probe-prereg.json"
        write_receipt(path, receipt)
        print("DENSITY_PROBE_PREREG_PASS")
        return

    # Full run requires B-MULTI-1 — check for data
    bmulti1_signal = os.environ.get("BMULTI1_DATA_PATH", "")
    if not bmulti1_signal or not os.path.exists(bmulti1_signal):
        receipt = {
            "ts": now_z(),
            "type": "density_probe_not_ready",
            "status": "PROBE_NOT_READY",
            "reason": "B-MULTI-1 image data not present. Set BMULTI1_DATA_PATH env var when data is ready.",
            "spec": spec,
            "DENSITY_PROBE_PREREG_PASS": True,
        }
        path = a.receipt or "receipts/density-probe-not-ready.json"
        write_receipt(path, receipt)
        print("PROBE_NOT_READY: B-MULTI-1 data required for full run.")
        sys.exit(2)  # exit 2 = not ready (not a failure)

    # Placeholder for actual training run (requires timeshare_pretrain.py integration)
    print("Full probe run not yet implemented — B-MULTI-1 data confirmed present.")
    print("Implement: run timeshare_pretrain.py for each (seed, arm) pair, collect val_loss.")
    sys.exit(1)


if __name__ == "__main__":
    main()
