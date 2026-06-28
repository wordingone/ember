"""power — exact intervals + power/MDE helpers for gate statistics (eng #2).

Why: the gate's bootstrap percentile CIs UNDERCOVER at zero-inflated counts —
the q3 receipt reports base solve CI95 [0.0, 3.0]% for 1/100, while the
Wilson score interval is [0.18, 5.45]%: the bootstrap can never exceed the
resample range of the observed data and collapses at 0-1 successes. Frozen
gate semantics are NOT yet frozen (pre-freeze window), so the correction is
legitimate now: receipts keep the deterministic bootstrap (replayable) and
ADD Wilson/Newcombe intervals computed post-hoc from counts by this module.
t4 wiring waits for ARC-chain idle (staged-job module-edit hazard); this
module is standalone on receipt counts.

Methods:
  wilson(s, n)                  — Wilson score interval (binomial, 95%)
  newcombe_paired_delta(...)    — MOVER/square-and-add CI for p1−p2 (paired
                                  marginals, no correlation correction —
                                  conservative under positive pairing; stated)
  mde_two_prop(n, p0)           — minimum detectable uplift, two-sided alpha
                                  .05, 80% power, normal approximation
  n_required(p0, delta)         — tasks needed to detect uplift delta

Pure stdlib. `python power.py --selftest` must print POWER_SELFTEST_PASS.
"""
import math

Z975 = 1.959963984540054
Z80 = 0.8416212335729143


def wilson(successes, n, z=Z975):
    """Wilson score interval for a binomial proportion. Returns (lo, hi)."""
    if n <= 0:
        raise ValueError("n must be positive")
    p = successes / n
    z2 = z * z
    denom = 1 + z2 / n
    center = (p + z2 / (2 * n)) / denom
    half = (z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n))) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def newcombe_paired_delta(s1, s2, n, z=Z975):
    """CI for p1 - p2 from per-arm success counts over the SAME n tasks.

    MOVER / square-and-add on Wilson marginals (Newcombe 1998 method 10
    family) WITHOUT the correlation correction: under positive pairing
    (shared tasks) this is conservative (wider). Returns (lo, hi) for the
    difference in proportions.
    """
    p1, p2 = s1 / n, s2 / n
    l1, u1 = wilson(s1, n, z)
    l2, u2 = wilson(s2, n, z)
    d = p1 - p2
    lo = d - math.sqrt((p1 - l1) ** 2 + (u2 - p2) ** 2)
    hi = d + math.sqrt((u1 - p1) ** 2 + (p2 - l2) ** 2)
    return (max(-1.0, lo), min(1.0, hi))


def mde_two_prop(n, p0, z_alpha=Z975, z_beta=Z80, tol=1e-7):
    """Minimum detectable uplift delta (p1 = p0 + delta) at the given n,
    two-sided alpha, target power. Normal approximation, two independent
    proportions (upper bound for paired designs — pairing only helps).
    Solved by fixed-point iteration on the pooled variance."""
    if not 0 <= p0 < 1:
        raise ValueError("p0 in [0,1)")
    delta = 0.05
    for _ in range(200):
        p1 = min(0.999999, p0 + delta)
        pbar = (p0 + p1) / 2
        se = math.sqrt(2 * pbar * (1 - pbar) / n)
        new = (z_alpha + z_beta) * se
        if abs(new - delta) < tol:
            return new
        delta = new
    return delta


def n_required(p0, delta, z_alpha=Z975, z_beta=Z80):
    """Tasks per arm to detect uplift delta over base rate p0 (same approx)."""
    if delta <= 0:
        raise ValueError("delta must be positive")
    p1 = min(0.999999, p0 + delta)
    pbar = (p0 + p1) / 2
    return math.ceil(((z_alpha + z_beta) ** 2) * 2 * pbar * (1 - pbar)
                     / (delta * delta))


def paired_se(rates_ref, delta, k):
    """SE of the mean paired per-task rate difference at sampling depth k.

    Binomial sampling noise per task for both arms at true rates p (ref)
    and p+delta (arm, clipped to [0,1]); homogeneous true delta, so
    between-task delta variance is 0 by construction (stated assumption —
    heterogeneous true effects make the real SE larger)."""
    n = len(rates_ref)
    tot = 0.0
    for p in rates_ref:
        pa = min(1.0, max(0.0, p + delta))
        tot += pa * (1 - pa) / k + p * (1 - p) / k
    return math.sqrt(tot / (n * n))


def mde_paired_rates(rates_ref, k, z_alpha=Z975, z_beta=Z80, tol=1e-7):
    """Minimum detectable homogeneous shift for the paired sample-level
    design (validation task set rates_ref, k samples/task/arm). Fixed-point
    on the shift-dependent SE, as in mde_two_prop."""
    delta = 0.05
    for _ in range(200):
        new = (z_alpha + z_beta) * paired_se(rates_ref, delta, k)
        if abs(new - delta) < tol:
            return new
        delta = new
    return delta


def power_mc_paired(rates_ref, delta, k, sims=2000, seed=16, z=Z975):
    """Monte-Carlo power of the paired sample-level test: per sim, draw
    Bin(k, p+delta) vs Bin(k, p) per task, reject when |mean diff| exceeds
    z * estimated SE (normal proxy for the registered bootstrap CI).
    Returns rejection fraction."""
    import random as _r
    rng = _r.Random(seed)
    n = len(rates_ref)
    rej = 0
    for _ in range(sims):
        diffs = []
        for p in rates_ref:
            pa = min(1.0, max(0.0, p + delta))
            sa = sum(1 for _ in range(k) if rng.random() < pa)
            sb = sum(1 for _ in range(k) if rng.random() < p)
            diffs.append(sa / k - sb / k)
        m = sum(diffs) / n
        var = sum((d - m) ** 2 for d in diffs) / (n - 1)
        se = math.sqrt(var / n)
        if se > 0 and abs(m) / se > z:
            rej += 1
    return rej / sims


def power_mc_feed(rates_ref, delta, k, sims=2000, seed=16):
    """Monte-Carlo power of the task-level any-of-k (feed) McNemar exact
    test under a homogeneous per-sample shift delta. Captures the ceiling:
    feed probability 1-(1-p)^k saturates as k grows."""
    import random as _r
    from g1_paired import mcnemar_exact
    rng = _r.Random(seed)
    rej = 0
    for _ in range(sims):
        b = c = 0
        for p in rates_ref:
            pa = min(1.0, max(0.0, p + delta))
            fa = any(rng.random() < pa for _ in range(k))
            fr = any(rng.random() < p for _ in range(k))
            if fr and not fa:
                b += 1
            elif fa and not fr:
                c += 1
        if mcnemar_exact(b, c) < 0.05:
            rej += 1
    return rej / sims


def _close(a, b, tol):
    return abs(a - b) <= tol


def _selftest():
    # Wilson 1/100 — textbook value ~[0.0018, 0.0545]
    lo, hi = wilson(1, 100)
    assert _close(lo, 0.0018, 0.0005) and _close(hi, 0.0545, 0.0010), (lo, hi)
    # Wilson 0/100 — upper ~0.0370 (Clopper-Pearson would give 0.0362,
    # rule-of-three 0.03; Wilson is the chosen method, value verified by hand:
    # hi = 2*(z^2/2n)/(1+z^2/n) = 0.0370), lower 0 to fp tolerance
    lo, hi = wilson(0, 100)
    assert _close(lo, 0.0, 1e-12) and _close(hi, 0.0370, 0.0010), (lo, hi)
    # Wilson 50/100 symmetric around 0.5
    lo, hi = wilson(50, 100)
    assert _close((lo + hi) / 2, 0.5, 1e-9) and _close(lo, 0.4038, 0.002)
    # the q3 receipt regime: bootstrap said [0, 3.0]%; Wilson upper is ~5.45%
    assert wilson(1, 100)[1] > 0.03, "Wilson must exceed bootstrap's 3% cap"
    # paired delta of identical arms contains 0, symmetric
    lo, hi = newcombe_paired_delta(1, 1, 100)
    assert lo < 0 < hi and _close(-lo, hi, 1e-9), (lo, hi)
    # trained-0 vs base-1 of 100 (the q3 verdict deltas)
    lo, hi = newcombe_paired_delta(0, 1, 100)
    assert lo < -0.01 and hi > 0, (lo, hi)  # cannot exclude 0 — no power
    # MDE shrinks with n; sane magnitudes
    m100 = mde_two_prop(100, 0.01)
    m1000 = mde_two_prop(1000, 0.01)
    assert m1000 < m100 < 0.20 and m100 > 0.05, (m100, m1000)
    # n_required round-trips mde approximately
    n = n_required(0.30, 0.10)
    assert 300 < n < 420, n
    back = mde_two_prop(n, 0.30)
    assert _close(back, 0.10, 0.01), back
    print(f"  q3 regime: 1/100 Wilson [{wilson(1,100)[0]:.4f},"
          f" {wilson(1,100)[1]:.4f}]; MDE at p0=1%, n=100:"
          f" {mde_two_prop(100, 0.01)*100:.1f}pp")
    print(f"  round-2 sizing: detect +10pp over 30% floor -> n>="
          f" {n_required(0.30, 0.10)}; +5pp -> n>= {n_required(0.30, 0.05)}")
    # paired-design extensions (eng tracker #29)
    rates = [0.2, 0.5, 0.8] * 14 + [0.5]  # 43 synthetic task rates
    se8, se32 = paired_se(rates, 0.0, 8), paired_se(rates, 0.0, 32)
    assert _close(se8 / se32, 2.0, 0.01), (se8, se32)  # SE ~ 1/sqrt(k)
    m8, m16 = mde_paired_rates(rates, 8), mde_paired_rates(rates, 16)
    assert m16 < m8 < 0.20 and m16 > 0.0, (m8, m16)
    p0 = power_mc_paired(rates, 0.0, 8, sims=400)
    assert p0 < 0.12, p0  # null rejection ~ alpha
    p_big = power_mc_paired(rates, 0.15, 8, sims=400)
    assert p_big > 0.85, p_big
    pf0 = power_mc_feed(rates, 0.0, 8, sims=200)
    assert pf0 < 0.12, pf0
    print("POWER_SELFTEST_PASS")


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        _selftest()
    else:
        print(__doc__)
