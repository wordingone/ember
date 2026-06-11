"""calibration_decomp.py — Brier decomposition + skill-detection budget (#31).

Runs on the EXISTING first-calibration data (no GPU): the k=24 focused
top-up samples (`w1-floor-q3-focus-20260610T210228Z-samples.jsonl`, 59
tasks, predicted_p per row). Murphy decomposition separates the two ways
the receipt's skill -0.2716 can be bad — miscalibrated confidence (REL)
vs zero discrimination (RES) — and the per-task skill spread gives the
minimum elicitation n to DETECT positive skill per round.

Positive-skill criterion (binding for vbits preference-1 re-qualification):
bootstrap CI (10k, seed 16, over tasks) of mean per-task skill must exclude
0 from above AND resolution > 0.01 (a predictor can beat the base-rate
reference by deflating confidence while still discriminating nothing —
resolution is the discrimination floor).

Receipt: receipts/calibration-decomp-<ts>.json. Pure stdlib.
"""
import json
import os
import random
from datetime import datetime, timezone

from calibrate import murphy_decomposition, per_task_skill, skill_mde
from receipt_write import checked_write

NC = "B:/M/avir/leo/state/nc-ladder"
RECEIPTS = f"{NC}/receipts"
SRC = f"{RECEIPTS}/w1-floor-q3-focus-20260610T210228Z-samples.jsonl"


def main():
    predicted, outcomes = {}, {}
    with open(SRC, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            t = r["task"]
            predicted.setdefault(t, r.get("predicted_p"))
            outcomes.setdefault(t, []).append(1 if r.get("verified") else 0)

    pairs = [(p, y) for t, p in predicted.items() if p is not None
             for y in outcomes[t]]
    decomp = murphy_decomposition(pairs)
    skills, obar = per_task_skill(predicted, outcomes)
    n_obs = len(skills)
    mean_skill = sum(skills) / n_obs

    rng = random.Random(16)
    boots = []
    for _ in range(10000):
        boots.append(sum(skills[rng.randrange(n_obs)]
                         for _ in range(n_obs)) / n_obs)
    boots.sort()
    ci = (round(boots[250], 4), round(boots[9749], 4))

    mde_table = {n: round(skill_mde(skills, n), 4)
                 for n in (43, 59, 120, 200, 400)}

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt = {
        "ticket": "CALIBRATION-DECOMP", "ts": ts,
        "source": os.path.basename(SRC), "n_tasks": n_obs,
        "base_rate": round(obar, 4),
        "murphy": decomp,
        "mean_skill": round(mean_skill, 4),
        "skill_bootstrap_ci95": ci,
        "skill_mde_by_n_tasks": mde_table,
        "positive_skill_criterion": "bootstrap CI lower bound > 0 AND "
                                    "resolution > 0.01",
        "selection_caveat": "hard-subset elicitation (rate<=0.75 tasks); "
                            "single-bin concentration is selection-"
                            "independent (carried from 99f539e1)",
    }
    os.makedirs(RECEIPTS, exist_ok=True)
    out = f"{RECEIPTS}/calibration-decomp-{ts}.json"
    checked_write(out, receipt)
    print(json.dumps(receipt, indent=2))
    print(f"CALIBRATION_DECOMP_DONE {out}")


if __name__ == "__main__":
    main()
