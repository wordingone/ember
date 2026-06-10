"""vbits — verifier-bits estimator (formalization §3b, eng issue #1).

The information banked by a verified episode is its surprisal under the
system's own calibrated expectation: bits(x) = -log2 P(V=1 | x, S).
B(round) = sum of bits over first-verified tasks / GPU-hours.

Estimator preference order (§3b): calibration predictor > previous-round
empirical rate > SPLIT-HALF fallback implemented here. The naive single-pool
estimator is biased (a fluke verify sets its own probability); split-half
breaks the self-reference: estimate P-hat on one half of the k samples, bank
bits only for tasks verified in the other half.

Pure stdlib; unit-checked by `python vbits.py --selftest`.
"""
import math
import random


def laplace_phat(successes, trials):
    """Laplace-smoothed success probability (s+1)/(n+2). Defined for n=0."""
    return (successes + 1) / (trials + 2)


def bits(phat):
    """Surprisal of a success at calibrated probability phat."""
    if not 0.0 < phat <= 1.0:
        raise ValueError(f"phat out of (0,1]: {phat}")
    return -math.log2(phat)


def split_half_bits(task_outcomes, seed=7):
    """Split-half episode bits for one round, no external predictor.

    task_outcomes: {task_id: [0/1 per sample]} — verify bit per sample, k>=2.
    Returns {task_id: bits} for tasks VERIFIED in the banking half, with
    P-hat estimated ONLY from the estimation half. Tasks with k<2 are skipped
    (cannot split — record and exclude rather than silently bias).
    """
    rng = random.Random(seed)
    out = {}
    for task, samples in sorted(task_outcomes.items()):
        if len(samples) < 2:
            continue
        idx = list(range(len(samples)))
        rng.shuffle(idx)
        half = len(idx) // 2
        est, bank = idx[:half], idx[half:]
        if not any(samples[i] for i in bank):
            continue  # nothing verified in the banking half -> no episode
        phat = laplace_phat(sum(samples[i] for i in est), len(est))
        out[task] = bits(phat)
    return out


def round_B(task_outcomes, gpu_hours, seed=7):
    """Round-level verifier-bits per GPU-hour (split-half estimator)."""
    if gpu_hours <= 0:
        raise ValueError("gpu_hours must be positive")
    per_task = split_half_bits(task_outcomes, seed=seed)
    total = sum(per_task.values())
    return {"per_task_bits": per_task, "total_bits": round(total, 4),
            "gpu_hours": gpu_hours,
            "B_bits_per_gpu_hour": round(total / gpu_hours, 4),
            "tasks_fed": len(per_task), "estimator": "split-half",
            "seed": seed}


def _selftest():
    # easy task: verifies always -> phat high -> ~1 bit ceiling region
    easy = {"easy": [1] * 16}
    # hard task: 1 verify in 16 -> high bits when it lands in banking half
    hard = {"hard": [1] + [0] * 15}
    # never-verifies: no episode, no bits
    dead = {"dead": [0] * 16}

    e = split_half_bits(easy)
    assert "easy" in e and e["easy"] < 0.2, e  # phat=(8+1)/(8+2)=0.9 -> .15 bits
    h = split_half_bits(hard)
    # fluke may land in estimation half (no episode) or banking half
    # (bits = -log2(1/10) ~ 3.32); both legal, neither self-inflated.
    if "hard" in h:
        assert 3.0 < h["hard"] < 3.5, h
    d = split_half_bits(dead)
    assert d == {}, d
    # k<2 excluded, not biased
    assert split_half_bits({"tiny": [1]}) == {}
    # easy mass weighs ~nothing vs one frontier solve
    combo = {}
    combo.update(easy)
    combo.update(hard)
    r = round_B(combo, gpu_hours=1.0)
    assert r["tasks_fed"] >= 1
    assert r["per_task_bits"].get("easy", 0) < 0.2
    # determinism
    assert split_half_bits(hard, seed=7) == split_half_bits(hard, seed=7)
    # bits() guards
    try:
        bits(0.0)
        raise AssertionError("bits(0) must raise")
    except ValueError:
        pass
    print("VBITS_SELFTEST_PASS")


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        _selftest()
    else:
        print(__doc__)
