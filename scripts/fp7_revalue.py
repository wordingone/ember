"""fp7_revalue.py — consolidator-side episode re-valuation (#60, fp-7).

fp-4 found that the banked-bits numerator B is computed against the
SAMPLER's success posterior, so the same correct episode carries a
different surprisal for a different-size core. fp-1's headline (the 1.5B
sampler banks 1.23x bits/GPU-min vs 3B) is therefore exact ONLY when the
core that samples is the core that consolidates. This re-scores the 1.5B
sampler's verified episodes under the 3B consolidator's own posterior and
asks whether the cheap-sampler advantage survives the honest denominator.

Method mirrors fp-1 (`fp1-bits-per-min` receipt): stratified surprisal,
laplace posterior, uncapped/undeduped passed rows, ext-FPR uncorrected
(flagged). The ONLY change is whose posterior values each episode:
  - sampler-valued (fp-1): bits = -log2 phat_1.5B(t)  per 1.5B episode
  - consolidator-valued (new): bits = -log2 phat_3B(t) per 1.5B episode
Both divided by the SAME 1.5B generation minutes (the cost of producing
the episodes does not change — only their worth to the consolidator does).

`python fp7_revalue.py --selftest`.
"""
import json
import sys
from datetime import datetime, timezone

from vbits import bits, laplace_phat
from receipt_write import checked_write

NC_WIN = "B:/M/avir/leo/state/nc-ladder"
RECEIPTS = f"{NC_WIN}/receipts"
Q15 = f"{RECEIPTS}/w1-floor-q15-20260610T202511Z-samples.jsonl"
Q3 = f"{RECEIPTS}/w1-floor-q3-20260610T203401Z-samples.jsonl"
GEN_MIN_1P5 = 6.06   # fp1-bits-per-min receipt, 1.5B
SELF_3B_PER_MIN = 32.7  # fp1: 3B sampling + 3B valuing (self-consistent)
SAMPLER_1P5_PER_MIN = 40.3  # fp1: 1.5B sampling + 1.5B valuing


def counts(path):
    """-> {task: {'s': passed, 'n': total}}."""
    by = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            d = by.setdefault(r["task"], {"s": 0, "n": 0})
            d["n"] += 1
            if r.get("verified"):
                d["s"] += 1
    return by


def stratum(s, n):
    if n == 0 or s == 0:
        return "dead"
    rate = s / n
    return ("frontier" if rate <= 0.25 else
            "mid" if rate <= 0.75 else "easy")


def revalue(small, big):
    """small/big: counts() tables. Re-score the small core's passed rows
    under each posterior; report stratified totals by the SMALL core's
    stratum (where its episodes live) and the BIG core's stratum (where the
    consolidator sees them)."""
    tasks = sorted(set(small) & set(big))
    sampler_total = consolidator_total = 0.0
    by_small_stratum = {}
    by_shift = {"upvalued": 0.0, "downvalued": 0.0, "unchanged": 0.0}
    for t in tasks:
        s_s, n_s = small[t]["s"], small[t]["n"]
        if s_s == 0:
            continue
        b_sampler = bits(laplace_phat(s_s, n_s))
        b_consol = bits(laplace_phat(big[t]["s"], big[t]["n"]))
        sampler_total += s_s * b_sampler
        consolidator_total += s_s * b_consol
        st = stratum(s_s, n_s)
        d = by_small_stratum.setdefault(st, {"sampler": 0.0, "consol": 0.0})
        d["sampler"] += s_s * b_sampler
        d["consol"] += s_s * b_consol
        delta = s_s * (b_consol - b_sampler)
        key = ("upvalued" if delta > 1e-9 else
               "downvalued" if delta < -1e-9 else "unchanged")
        by_shift[key] += delta
    return {
        "tasks_with_small_episodes": sum(1 for t in tasks if small[t]["s"]),
        "sampler_valued_bits": round(sampler_total, 1),
        "consolidator_valued_bits": round(consolidator_total, 1),
        "by_small_stratum": {k: {"sampler": round(v["sampler"], 1),
                                 "consolidator": round(v["consol"], 1)}
                             for k, v in by_small_stratum.items()},
        "shift_bits": {k: round(v, 1) for k, v in by_shift.items()},
    }


def main():
    small, big = counts(Q15), counts(Q3)
    res = revalue(small, big)
    consol_per_min = round(res["consolidator_valued_bits"] / GEN_MIN_1P5, 1)
    # cheap-sampler advantage survives iff consolidator-valued/min of the
    # 1.5B episodes still beats the 3B self-consistent rate.
    survives = consol_per_min > SELF_3B_PER_MIN
    ratio_revalued = round(consol_per_min / SELF_3B_PER_MIN, 2)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt = {
        "ticket": "FP7-REVALUE", "ts": ts,
        "sampler": Q15.split("/")[-1], "consolidator_posterior": Q3.split("/")[-1],
        "method": "fp1-stratified-laplace, posterior swapped sampler->consolidator; "
                  "ext-FPR uncorrected (flagged, same as fp1)",
        "gen_min_1p5B": GEN_MIN_1P5,
        "analysis": res,
        "sampler_valued_per_min": SAMPLER_1P5_PER_MIN,
        "consolidator_valued_per_min": consol_per_min,
        "self_consistent_3B_per_min": SELF_3B_PER_MIN,
        "ratio_revalued_over_3B": ratio_revalued,
        "cheap_sampler_advantage_survives_revaluation": survives,
        "fp1_ratio_sampler_valued": round(
            SAMPLER_1P5_PER_MIN / SELF_3B_PER_MIN, 2),
    }
    out = f"{RECEIPTS}/fp7-revalue-{ts}.json"
    checked_write(out, receipt)
    print(json.dumps(receipt, indent=2))
    print(f"FP7_REVALUE_DONE {out}")


def _selftest():
    # constructed: small solves a task the big core finds hard -> upvalued.
    small = {"a": {"s": 4, "n": 8}, "b": {"s": 2, "n": 8}}
    big = {"a": {"s": 4, "n": 8}, "b": {"s": 0, "n": 8}}
    r = revalue(small, big)
    # task a identical posterior -> no shift; task b big=0 -> higher bits
    assert r["sampler_valued_bits"] > 0
    assert r["consolidator_valued_bits"] > r["sampler_valued_bits"], r
    assert r["shift_bits"]["upvalued"] > 0
    # mirror case: big core finds it EASY -> downvalued
    big2 = {"a": {"s": 4, "n": 8}, "b": {"s": 8, "n": 8}}
    r2 = revalue(small, big2)
    assert r2["consolidator_valued_bits"] < r2["sampler_valued_bits"], r2
    assert r2["shift_bits"]["downvalued"] < 0
    # zero-episode tasks contribute nothing
    small3 = {"a": {"s": 0, "n": 8}}
    r3 = revalue(small3, {"a": {"s": 1, "n": 8}})
    assert r3["sampler_valued_bits"] == 0.0
    print("FP7_REVALUE_SELFTEST_PASS")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        main()
