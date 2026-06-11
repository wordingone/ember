"""r2_power.py — round-2 G1 power pre-registration runs (#29).

Loads the EMPIRICAL per-task base rates from the G1 base leg samples
(validation 43 x k=8, receipt w1-floor-g1-base-*) and executes the power.py
paired-design extensions on them: MDE-vs-k table + Monte-Carlo power grid
(sample-level normal-proxy test and task-level any-of-k McNemar), so every
number in research/math/r2-power-prereg.md comes from an executed run.

Receipt: receipts/r2-power-prereg-<ts>.json. Pure stdlib.
"""
import glob as globlib
import json
import os
from datetime import datetime, timezone

from g1_paired import load_samples
from power import mde_paired_rates, power_mc_feed, power_mc_paired
from receipt_write import checked_write

NC = "B:/M/avir/leo/state/nc-ladder"
RECEIPTS = f"{NC}/receipts"
KS = (8, 16, 24, 32)
DELTAS = (0.03, 0.05, 0.08)
SIMS = 2000


def main():
    hits = sorted(globlib.glob(f"{RECEIPTS}/w1-floor-g1-base-*-samples.jsonl"))
    if not hits:
        raise SystemExit("r2_power: no g1-base samples receipt")
    tab = load_samples(hits[-1])
    rates = [sum(xs) / len(xs) for xs in tab.values()]

    mde = {k: round(mde_paired_rates(rates, k), 4) for k in KS}
    grid_sample = {f"k={k}": {f"+{int(d*100)}pp": round(
        power_mc_paired(rates, d, k, sims=SIMS), 3)
        for d in DELTAS} for k in KS}
    grid_feed = {f"k={k}": {f"+{int(d*100)}pp": round(
        power_mc_feed(rates, d, k, sims=SIMS), 3)
        for d in DELTAS} for k in KS}
    null_rej = {f"k={k}": round(power_mc_paired(rates, 0.0, k, sims=SIMS), 3)
                for k in KS}

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt = {
        "ticket": "R2-POWER-PREREG", "ts": ts,
        "rates_source": os.path.basename(hits[-1]),
        "n_tasks": len(rates),
        "base_mean_rate": round(sum(rates) / len(rates), 4),
        "assumption": "homogeneous per-sample shift; binomial sampling "
                      "noise only (heterogeneous true effects widen SE — "
                      "MDEs are optimistic lower bounds)",
        "mde_sample_level_by_k": mde,
        "power_sample_level": grid_sample,
        "power_task_feed": grid_feed,
        "null_rejection_rate": null_rej,
        "sims_per_cell": SIMS, "seed": 16,
    }
    os.makedirs(RECEIPTS, exist_ok=True)
    out = f"{RECEIPTS}/r2-power-prereg-{ts}.json"
    checked_write(out, receipt)
    print(json.dumps(receipt, indent=2))
    print(f"R2_POWER_DONE {out}")


if __name__ == "__main__":
    main()
