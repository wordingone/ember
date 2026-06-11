"""fp12_band.py — upvalued-band stability across independent samplings (#78, fp-12).

fp-9 left the band (easy-for-small / hard-for-big, +60.9 bits under the
3B posterior) as the LAST cheap-sampler rationale. Is membership a stable
property of tasks, or sampling noise?

PREMISE CORRECTION (modified-spec rule, recorded): issue #78 says the
1.5B was sampled twice — the receipts inventory says otherwise. The two
INDEPENDENT samplings on disk are both 3B: q3 (k=8, seed 14, 120 tasks)
and q3-focus (k=24, seed 15, the 59 tasks at k8-rate <= 0.75). The 1.5B
leg exists ONCE (q15, k=8, seed 14). So this receipt tests the stability
of the HARD-FOR-BIG coordinate — the only resampled coordinate — and the
band membership it induces with the (fixed) 1.5B leg. The easy-for-small
coordinate's stability is UNTESTED and stays a named gap: a decisive
NOISE verdict here kills the band outright (membership needs both
coordinates); a STABLE verdict is conditional on the untested half.

Band predicate (fp-7's, mirrored exactly): task t is in the band iff
s15(t) > 0 AND laplace_phat(q3 leg) < laplace_phat(q15) — the episode is
worth MORE to the consolidator than the sampler priced it.

Measurements (pre-registered):
  1. Band membership computed twice — m_A (q15 x q3-k8) and m_B
     (q15 x q3focus-k24) — over the 59 joint tasks: Jaccard, Cohen's
     kappa, permutation p-value (task-label shuffle, seed 16, 10k).
  2. Posterior-probability variant (small-k flicker control): membership
     via P(p3 < p15) >= 0.8 under independent Beta posteriors
     (deterministic grid integration), same agreement stats.
  3. Bits-weighted stability: of the upvalued bits the k8 leg assigns on
     these 59 tasks, the fraction still upvalued under the k24 leg.

Verdict (frozen): STABLE iff kappa > 0 with permutation p < 0.05 on
measurement 1; else NOISE -> the targeting filter is dead and sampler
choice is license-only (fp-6). Caveats carried: hard-subset selection
was ON the k8 leg (regression-to-the-mean biases agreement DOWN — a
stable verdict is conservative, a noise verdict must mind this);
conditional n=59; the q15 coordinate is single-sampled.

CPU-from-receipts. `python fp12_band.py --selftest`.
"""
import json
import math
import random
import sys
from datetime import datetime, timezone

from vbits import laplace_phat
from fp7_revalue import counts, stratum
from receipt_write import checked_write

NC_WIN = "B:/M/avir/leo/state/nc-ladder"
RECEIPTS = f"{NC_WIN}/receipts"
Q15 = f"{RECEIPTS}/w1-floor-q15-20260610T202511Z-samples.jsonl"
Q3A = f"{RECEIPTS}/w1-floor-q3-20260610T203401Z-samples.jsonl"
Q3B = f"{RECEIPTS}/w1-floor-q3-focus-20260610T210228Z-samples.jsonl"
SEED = 16
N_PERM = 10_000
POSTERIOR_BAR = 0.8


def band_member(s15, n15, s3, n3):
    """fp-7 predicate: small-core episodes exist AND the 3B posterior
    prices them above the 1.5B's own posterior."""
    return s15 > 0 and laplace_phat(s3, n3) < laplace_phat(s15, n15)


def p_small_easier(s15, n15, s3, n3, grid=2001):
    """P(p3 < p15) under independent Beta(s+1, n-s+1) posteriors —
    deterministic trapezoid grid, no sampling."""
    a3, b3 = s3 + 1, n3 - s3 + 1
    a15, b15 = s15 + 1, n15 - s15 + 1
    lg = math.lgamma
    logc3 = lg(a3 + b3) - lg(a3) - lg(b3)
    logc15 = lg(a15 + b15) - lg(a15) - lg(b15)
    total = 0.0
    cdf3 = 0.0
    prev_pdf3 = 0.0
    prev_int = None
    step = 1.0 / (grid - 1)
    for i in range(grid):
        x = i * step
        pdf3 = (math.exp(logc3 + (a3 - 1) * math.log(x) +
                         (b3 - 1) * math.log(1 - x))
                if 0 < x < 1 else 0.0)
        if i > 0:
            cdf3 += 0.5 * (prev_pdf3 + pdf3) * step
        pdf15 = (math.exp(logc15 + (a15 - 1) * math.log(x) +
                          (b15 - 1) * math.log(1 - x))
                 if 0 < x < 1 else 0.0)
        integrand = pdf15 * min(cdf3, 1.0)
        if prev_int is not None:
            total += 0.5 * (prev_int + integrand) * step
        prev_pdf3 = pdf3
        prev_int = integrand
    return min(total, 1.0)


def jaccard(a, b):
    u = a | b
    return len(a & b) / len(u) if u else None


def kappa(m1, m2, tasks):
    """Cohen's kappa for two binary labelings over tasks."""
    n = len(tasks)
    p11 = sum(1 for t in tasks if t in m1 and t in m2) / n
    p00 = sum(1 for t in tasks if t not in m1 and t not in m2) / n
    po = p11 + p00
    q1, q2 = len(m1) / n, len(m2) / n
    pe = q1 * q2 + (1 - q1) * (1 - q2)
    if pe == 1.0:
        return None
    return (po - pe) / (1 - pe)


def perm_pvalue(m1, m2, tasks, seed=SEED, n_perm=N_PERM):
    """One-sided: P(kappa_perm >= kappa_obs) under task-label shuffle of
    the SECOND labeling (membership counts preserved)."""
    obs = kappa(m1, m2, tasks)
    rng = random.Random(seed)
    labels2 = [t in m2 for t in tasks]
    ge = 0
    for _ in range(n_perm):
        rng.shuffle(labels2)
        mp = {t for t, lab in zip(tasks, labels2) if lab}
        k = kappa(m1, mp, tasks)
        if k is not None and k >= obs:
            ge += 1
    return obs, ge / n_perm


def main():
    small = counts(Q15)
    big_a, big_b = counts(Q3A), counts(Q3B)
    tasks = sorted(set(big_b) & set(big_a) & set(small))

    def members(big, bar=None):
        out = set()
        for t in tasks:
            s15, n15 = small[t]["s"], small[t]["n"]
            s3, n3 = big[t]["s"], big[t]["n"]
            if bar is None:
                if band_member(s15, n15, s3, n3):
                    out.add(t)
            else:
                if s15 > 0 and p_small_easier(s15, n15, s3, n3) >= bar:
                    out.add(t)
        return out

    m_a, m_b = members(big_a), members(big_b)
    k_obs, p_perm = perm_pvalue(m_a, m_b, tasks)
    mp_a, mp_b = members(big_a, POSTERIOR_BAR), members(big_b, POSTERIOR_BAR)
    kp_obs, pp_perm = perm_pvalue(mp_a, mp_b, tasks)

    # bits-weighted: upvalued bits on these tasks per the k8 leg, and the
    # share of those bits still upvalued under the k24 leg
    from vbits import bits
    up_bits_a = up_bits_stable = 0.0
    for t in m_a:
        s15, n15 = small[t]["s"], small[t]["n"]
        delta = s15 * (bits(laplace_phat(big_a[t]["s"], big_a[t]["n"])) -
                       bits(laplace_phat(s15, n15)))
        up_bits_a += delta
        if t in m_b:
            up_bits_stable += delta

    # context: raw 3B-coordinate stability independent of the q15 leg
    strata_agree = sum(1 for t in tasks
                       if stratum(big_a[t]["s"], big_a[t]["n"]) ==
                       stratum(big_b[t]["s"], big_b[t]["n"]))
    rate_pairs = [(big_a[t]["s"] / big_a[t]["n"],
                   big_b[t]["s"] / big_b[t]["n"]) for t in tasks]
    mean_a = sum(p[0] for p in rate_pairs) / len(rate_pairs)
    mean_b = sum(p[1] for p in rate_pairs) / len(rate_pairs)

    verdict = ("STABLE-conditional" if k_obs is not None and k_obs > 0
               and p_perm < 0.05 else "NOISE")
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt = {
        "ticket": "FP12-BAND", "ts": ts,
        "premise_correction": "issue #78 said the 1.5B was sampled twice; "
                              "receipts show the two independent samplings "
                              "are both 3B (k=8 seed14 / k=24 seed15). The "
                              "tested coordinate is hard-for-big; the "
                              "easy-for-small coordinate is single-sampled "
                              "and stays a NAMED GAP.",
        "legs": {"q15": Q15.split("/")[-1], "q3_k8": Q3A.split("/")[-1],
                 "q3_focus_k24": Q3B.split("/")[-1]},
        "joint_tasks": len(tasks),
        "band_membership": {
            "n_k8_leg": len(m_a), "n_k24_leg": len(m_b),
            "n_both": len(m_a & m_b),
            "jaccard": round(jaccard(m_a, m_b), 4),
            "kappa": round(k_obs, 4),
            "perm_p_one_sided": p_perm,
        },
        "posterior_variant": {
            "rule": f"P(p3 < p15) >= {POSTERIOR_BAR} (Beta posteriors, "
                    "grid integration)",
            "n_k8_leg": len(mp_a), "n_k24_leg": len(mp_b),
            "n_both": len(mp_a & mp_b),
            "jaccard": round(jaccard(mp_a, mp_b), 4) if (mp_a | mp_b) else None,
            "kappa": round(kp_obs, 4) if kp_obs is not None else None,
            "perm_p_one_sided": pp_perm,
        },
        "bits_weighted": {
            "upvalued_bits_k8_leg_on_joint": round(up_bits_a, 1),
            "still_upvalued_under_k24": round(up_bits_stable, 1),
            "stable_fraction": round(up_bits_stable / up_bits_a, 4)
            if up_bits_a else None,
        },
        "raw_3b_coordinate_context": {
            "strata_agreement": f"{strata_agree}/{len(tasks)}",
            "mean_rate_k8_leg": round(mean_a, 4),
            "mean_rate_k24_leg": round(mean_b, 4),
            "note": "k8-selected tasks drifting UP at k24 = regression to "
                    "the mean from selection on the k8 leg",
        },
        "verdict": verdict,
        "verdict_rule": "STABLE iff kappa>0 AND perm p<0.05 on the raw "
                        "predicate; STABLE is CONDITIONAL on the untested "
                        "q15 coordinate; NOISE kills the targeting filter "
                        "outright (both coordinates required)",
        "flags": [
            "selection bias: the 59 tasks were chosen ON the k8 leg "
            "(rate<=0.75) — regression to the mean biases agreement DOWN; "
            "stable verdict conservative, noise verdict must mind this",
            "q15 coordinate single-sampled — band stability tested on the "
            "3B half only",
            "conditional n=59 (the hard-subset overlap), per the issue",
        ],
    }
    out = f"{RECEIPTS}/fp12-band-{ts}.json"
    checked_write(out, receipt)
    print(json.dumps(receipt, indent=2))
    print(f"FP12_BAND_DONE {out}")


def _selftest():
    # band predicate mirrors fp-7: phat3 < phat15 with episodes present
    assert band_member(4, 8, 1, 8)            # small easier -> in band
    assert not band_member(0, 8, 0, 8)        # no small episodes
    assert not band_member(2, 8, 6, 8)        # big easier
    assert not band_member(3, 8, 3, 8)        # equal posteriors
    # posterior grid: strong separation -> near 1; symmetric -> 0.5
    assert p_small_easier(7, 8, 1, 8) > 0.97
    assert abs(p_small_easier(4, 8, 4, 8) - 0.5) < 0.01
    assert p_small_easier(1, 8, 7, 8) < 0.03
    # k-asymmetry sanity: same rate, more evidence -> still ~0.5
    assert abs(p_small_easier(4, 8, 12, 24) - 0.5) < 0.02
    # jaccard / kappa
    assert jaccard({1, 2}, {2, 3}) == 1 / 3
    t = list(range(10))
    m = {0, 1, 2, 3}
    assert kappa(m, m, t) == 1.0
    assert abs(kappa(m, {6, 7, 8, 9}, t) - (-2 / 3)) < 1e-9
    # permutation: identical labelings -> p ~ small; independent -> large
    k1, p1 = perm_pvalue(m, m, t, seed=3, n_perm=500)
    assert k1 == 1.0 and p1 < 0.1, (k1, p1)
    k2, p2 = perm_pvalue(m, {4, 5, 6, 7}, t, seed=3, n_perm=500)
    assert p2 > 0.5, (k2, p2)  # disjoint equal-size = below-chance overlap
    # determinism
    assert perm_pvalue(m, {2, 3, 4}, t, seed=7, n_perm=300) == \
        perm_pvalue(m, {2, 3, 4}, t, seed=7, n_perm=300)
    print("FP12_BAND_SELFTEST_PASS")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        main()
