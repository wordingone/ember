"""fp9_parity.py — is the re-valued 1.07x distinguishable from parity? (#68, fp-9)

fp-7 re-valued the 1.5B sampler's episodes under the 3B consolidator's
posterior: the cheap-sampler advantage collapsed 1.23x -> 1.07x. A 7%
edge sits within reach of two factors both legs carried UNCORRECTED
(flagged since fp-1). This receipt closes both:

1. **Bootstrap CI** (task-level resample with replacement, seed 16, 10k)
   on the re-valued ratio:
     ratio = [sum_t s15(t) * b3(t) / 6.06] / [sum_t s3(t) * b3(t) / 7.14]
   where b3(t) = bits(laplace_phat(s3(t), n3(t))) — the consolidator's
   own posterior values BOTH numerators (fp-7's honest denominator).

2. **ext-FPR propagation** into BOTH legs: per-stratum extended-test
   fail rates (measured at 3B, v-extended receipt: easy 23.4% / mid
   19.7% / frontier 27.1%) discount each task's success count
   s'(t) = s(t) * (1 - f(stratum)), and the DISCOUNTED count re-enters
   the posterior (fewer true successes -> lower phat -> HIGHER bits per
   episode, fewer episodes counted — the two effects partially cancel;
   the receipt measures the net). FLAG carried from fp-1: f is measured
   at 3B and applied to the 1.5B as a model (unmeasured there).

Verdict shape (pre-registered in #68): corrected CI excludes 1.0 ->
cheap-sampler edge REAL, quote re-valued+corrected; CI includes 1.0 ->
the line is COST PARITY and fp-7's upvalued band (easy-for-small,
hard-for-big) is the only surviving cheap-sampler rationale.

`python fp9_parity.py --selftest`.
"""
import json
import random
import sys
from datetime import datetime, timezone

from vbits import bits, laplace_phat
from fp7_revalue import counts, stratum
from receipt_write import checked_write

NC_WIN = "B:/M/avir/leo/state/nc-ladder"
RECEIPTS = f"{NC_WIN}/receipts"
Q15 = f"{RECEIPTS}/w1-floor-q15-20260610T202511Z-samples.jsonl"
Q3 = f"{RECEIPTS}/w1-floor-q3-20260610T203401Z-samples.jsonl"
GEN_MIN_15 = 6.06   # fp1 receipt
GEN_MIN_3 = 7.14    # fp1 receipt
# v-extended receipt (eng #7): per-stratum extended-test FAIL rates at 3B
EXT_FAIL = {"easy": 0.234, "mid": 0.197, "frontier": 0.271, "dead": 0.0}
SEED = 16
N_BOOT = 10_000


def ratio_on(tasks, small, big, ext_correct):
    """Re-valued bits/min ratio over a task multiset (bootstrap-ready).
    ext_correct: discount success counts per-stratum AND re-derive the
    valuing posterior from the discounted counts."""
    num15 = num3 = 0.0
    for t in tasks:
        s15, n15 = small[t]["s"], small[t]["n"]
        s3, n3 = big[t]["s"], big[t]["n"]
        if ext_correct:
            s15 = s15 * (1 - EXT_FAIL[stratum(s15, n15)])
            s3 = s3 * (1 - EXT_FAIL[stratum(big[t]["s"], n3)])
        b3 = bits(laplace_phat(s3, n3))
        num15 += s15 * b3
        num3 += s3 * b3
    if num3 == 0:
        return None
    return (num15 / GEN_MIN_15) / (num3 / GEN_MIN_3)


def boot_ci(tasks, small, big, ext_correct, seed=SEED, n_boot=N_BOOT):
    rng = random.Random(seed)
    point = ratio_on(tasks, small, big, ext_correct)
    draws = []
    for _ in range(n_boot):
        sample = [tasks[rng.randrange(len(tasks))] for _ in tasks]
        r = ratio_on(sample, small, big, ext_correct)
        if r is not None:
            draws.append(r)
    draws.sort()
    lo = draws[int(0.025 * len(draws))]
    hi = draws[int(0.975 * len(draws)) - 1]
    return round(point, 3), round(lo, 3), round(hi, 3), len(draws)


def main():
    small, big = counts(Q15), counts(Q3)
    tasks = sorted(set(small) & set(big))
    p_u, lo_u, hi_u, n_u = boot_ci(tasks, small, big, ext_correct=False)
    p_c, lo_c, hi_c, n_c = boot_ci(tasks, small, big, ext_correct=True)
    verdict_unc = "edge-real" if lo_u > 1.0 else \
        "cost-parity" if hi_u >= 1.0 >= lo_u else "edge-negative"
    verdict_cor = "edge-real" if lo_c > 1.0 else \
        "cost-parity" if hi_c >= 1.0 >= lo_c else "edge-negative"
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt = {
        "ticket": "FP9-PARITY", "ts": ts,
        "tasks_joint": len(tasks),
        "method": "task-level bootstrap (seed 16, 10k) on the fp-7 "
                  "re-valued ratio; ext-FPR correction discounts success "
                  "counts per-stratum AND re-derives the valuing posterior",
        "flags": ["ext fail-rates measured at 3B, modeled at 1.5B",
                  "gen minutes are governed wall-clock (fp-11 pending)"],
        "uncorrected": {"point": p_u, "ci95": [lo_u, hi_u],
                        "n_draws": n_u, "verdict": verdict_unc},
        "ext_corrected": {"point": p_c, "ci95": [lo_c, hi_c],
                          "n_draws": n_c, "verdict": verdict_cor},
        "prereg_verdict_rule": "corrected CI excludes 1.0 -> edge real; "
                               "includes 1.0 -> cost parity, upvalued-band "
                               "filter is the surviving rationale",
    }
    out = f"{RECEIPTS}/fp9-parity-{ts}.json"
    checked_write(out, receipt)
    print(json.dumps(receipt, indent=2))
    print(f"FP9_PARITY_DONE {out}")


def _selftest():
    # two-task constructed world: small core strictly better per minute
    small = {"a": {"s": 4, "n": 8}, "b": {"s": 2, "n": 8}}
    big = {"a": {"s": 2, "n": 8}, "b": {"s": 1, "n": 8}}
    tasks = ["a", "b"]
    r = ratio_on(tasks, small, big, ext_correct=False)
    # numerators share b3; small has 2x the successes; gen-min favor 3B
    # slightly (6.06 vs 7.14) -> ratio > 2
    assert r > 2.0, r
    # ext correction with EQUAL strata rates rescales both numerators by
    # the same factor on counts but ALSO lowers phat -> raises b3 equally
    # -> ratio moves but stays > 1 in this construction
    rc = ratio_on(tasks, small, big, ext_correct=True)
    assert rc > 1.0, rc
    # bootstrap determinism: same seed -> identical CI
    a1 = boot_ci(tasks, small, big, False, seed=7, n_boot=200)
    a2 = boot_ci(tasks, small, big, False, seed=7, n_boot=200)
    assert a1 == a2, (a1, a2)
    # degenerate: big core with zero successes everywhere -> None ratio
    big0 = {"a": {"s": 0, "n": 8}, "b": {"s": 0, "n": 8}}
    assert ratio_on(tasks, small, big0, False) is None
    # CI ordering sane
    p, lo, hi, n = boot_ci(tasks, small, big, False, seed=3, n_boot=500)
    assert lo <= p <= hi and n == 500, (p, lo, hi, n)
    print("FP9_PARITY_SELFTEST_PASS")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        main()
