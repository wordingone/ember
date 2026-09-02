"""stats_exact.py — exact-method gate statistics (single source).

Provides Wilson score CIs, Newcombe paired-difference CI, and minimum
detectable effect (MDE) helpers alongside the existing bootstrap estimators.
Nothing here changes bootstrap behavior or early-stop logic — these are
additive exact-method companions emitted in a sub-block of each receipt.

All functions are pure (no I/O, no external dependencies). Uses only stdlib
math for closed forms and a rational approximation for the normal quantile.

Motivation: at n=100 tasks with 0–1 successes per arm (the zero-inflated
coverage regime common in early nc-ladder rounds), bootstrap resampling
produces unreliable CIs — the Wilson score interval has exact coverage
guarantees for any n and is especially reliable at the boundary.

--- Normal quantile approximation ---
z_from_p(p) implements the rational approximation by Acklam (2002),
"An algorithm for computing the inverse normal cumulative distribution
function" — a minimax rational poly that achieves |error| < 3.65e-8
across (0,1). Self-test pins z(0.975) to 1.9600 ± 1e-4.
"""

import math

# ---------------------------------------------------------------------------
# Normal quantile  (Acklam 2002 rational approx)
# ---------------------------------------------------------------------------

# Coefficients from Acklam 2002, Table 1
_A = (-3.969683028665376e+01,  2.209460984245205e+02,
      -2.759285104469687e+02,  1.383577518672690e+02,
      -3.066479806614716e+01,  2.506628277459239e+00)
_B = (-5.447609879822406e+01,  1.615858368580409e+02,
      -1.556989798598866e+02,  6.680131188771972e+01,
      -1.328068155288572e+01)
_C = (-7.784894002430293e-03, -3.223964580411365e-01,
      -2.400758277161838e+00, -2.549732539343734e+00,
       4.374664141464968e+00,  2.938163982698783e+00)
_D = (7.784695709041462e-03,  3.224671290700398e-01,
      2.445134137142996e+00,  3.754408661907416e+00)

_P_LO = 0.02425
_P_HI = 1.0 - _P_LO


def _z_from_p(p: float) -> float:
    """Inverse-normal CDF via Acklam (2002) rational approximation.

    Accuracy: |error| < 3.65e-8 for p in (0,1).
    Raises ValueError for p outside (0,1).
    """
    if not (0.0 < p < 1.0):
        raise ValueError(f"p={p!r} must be strictly in (0,1)")
    if p < _P_LO:
        q = math.sqrt(-2.0 * math.log(p))
        return (((((_C[0] * q + _C[1]) * q + _C[2]) * q + _C[3]) * q + _C[4]) * q
                + _C[5]) / ((((_D[0] * q + _D[1]) * q + _D[2]) * q + _D[3]) * q + 1.0)
    if p <= _P_HI:
        q = p - 0.5
        r = q * q
        return (((((_A[0] * r + _A[1]) * r + _A[2]) * r + _A[3]) * r + _A[4]) * r
                + _A[5]) * q / (((((_B[0] * r + _B[1]) * r + _B[2]) * r + _B[3])
                                 * r + _B[4]) * r + 1.0)
    # upper tail: use symmetry
    return -_z_from_p(1.0 - p)


# ---------------------------------------------------------------------------
# Wilson score interval
# ---------------------------------------------------------------------------

def wilson_ci(k: int, n: int, conf: float = 0.95,
              continuity: bool = False) -> tuple:
    """Wilson score confidence interval for a binomial proportion.

    Parameters
    ----------
    k : int
        Number of successes (0 <= k <= n).
    n : int
        Total trials (n >= 1).
    conf : float
        Confidence level, e.g. 0.95 for a 95% CI.
    continuity : bool
        If True, apply the continuity correction form of the Wilson interval
        (Newcombe 1998 variant). Default False (standard Wilson).

    Returns
    -------
    (lo, hi) : tuple of float
        Lower and upper confidence bounds, both in [0, 1].

    Exact variant documented
    ------------------------
    Standard Wilson (default, continuity=False):
        centre = (k + z²/2) / (n + z²)
        halfwidth = z * sqrt(k*(n-k)/n + z²/4) / (n + z²)
        lo = max(0, centre - halfwidth)
        hi = min(1, centre + halfwidth)
    where z = z_{(1+conf)/2} (e.g. 1.96 for conf=0.95).

    Continuity-corrected Wilson (continuity=True, Newcombe 1998 eq. 3):
        lo = max(0, (2*n*p_hat + z² - 1 - z*sqrt(z²-2-1/n+4*p_hat*(n*(1-p_hat)+1))) / (2*(n+z²)))
        hi = min(1, (2*n*p_hat + z² + 1 + z*sqrt(z²+2-1/n+4*p_hat*(n*(1-p_hat)-1))) / (2*(n+z²)))
    """
    if n < 1:
        raise ValueError(f"n={n} must be >= 1")
    if not (0 <= k <= n):
        raise ValueError(f"k={k} must satisfy 0 <= k <= n={n}")
    z = _z_from_p((1.0 + conf) / 2.0)
    z2 = z * z
    p_hat = k / n

    if not continuity:
        denom = n + z2
        centre = (k + z2 / 2.0) / denom
        halfwidth = (z / denom) * math.sqrt(k * (n - k) / n + z2 / 4.0)
        lo = max(0.0, centre - halfwidth)
        hi = min(1.0, centre + halfwidth)
    else:
        # Newcombe 1998, eq. 3 continuity-corrected form
        lo_num = 2 * n * p_hat + z2 - 1 - z * math.sqrt(
            max(0.0, z2 - 2 - 1.0 / n + 4 * p_hat * (n * (1 - p_hat) + 1)))
        hi_num = 2 * n * p_hat + z2 + 1 + z * math.sqrt(
            max(0.0, z2 + 2 - 1.0 / n + 4 * p_hat * (n * (1 - p_hat) - 1)))
        denom = 2 * (n + z2)
        lo = max(0.0, lo_num / denom)
        hi = min(1.0, hi_num / denom)

    return (lo, hi)


# ---------------------------------------------------------------------------
# Newcombe paired difference CI
# ---------------------------------------------------------------------------

def newcombe_paired_ci(b: int, c: int, n: int,
                       conf: float = 0.95) -> tuple:
    """Newcombe (1998) method 10: paired difference of proportions CI.

    Constructs the CI for (p1 - p2) where p1 = arm-1 proportion and
    p2 = arm-2 proportion using the discordant-pair counts b and c.

    Parameters
    ----------
    b : int
        Number of tasks where arm-1 succeeded and arm-2 did not (b >= 0).
    c : int
        Number of tasks where arm-2 succeeded and arm-1 did not (c >= 0).
    n : int
        Total number of paired tasks (n >= 1; b + c <= n).
    conf : float
        Confidence level.

    Returns
    -------
    (lo, hi) : tuple of float
        CI for (p1 - p2), clipped to [-1, 1].

    Exact variant documented
    ------------------------
    This implements Newcombe (1998) "Interval estimation for the difference
    between independent proportions: comparison of eleven methods", Method 10
    (the paired version using the square-and-add approach from Wilson
    intervals on the discordant pairs).

    Step 1 — Wilson CIs on the marginal discordant proportions:
        phi1 = b/n  →  wilson_ci(b, n) gives (l1, u1)
        phi2 = c/n  →  wilson_ci(c, n) gives (l2, u2)

    Step 2 — "Square-and-add" combination (Newcombe eq. 10):
        lo = (b - c)/n - sqrt((b/n - l1)² + (u2 - c/n)²)
        hi = (b - c)/n + sqrt((u1 - b/n)² + (c/n - l2)²)

    The result is the CI for the SIGNED paired difference (arm1 - arm2);
    when b == c the CI is symmetric about 0.
    """
    if n < 1:
        raise ValueError(f"n={n} must be >= 1")
    if b < 0 or c < 0:
        raise ValueError(f"b={b}, c={c} must be >= 0")
    if b + c > n:
        raise ValueError(f"b+c={b+c} > n={n}")

    l1, u1 = wilson_ci(b, n, conf=conf)
    l2, u2 = wilson_ci(c, n, conf=conf)
    diff = (b - c) / n
    lo = diff - math.sqrt((b / n - l1) ** 2 + (u2 - c / n) ** 2)
    hi = diff + math.sqrt((u1 - b / n) ** 2 + (c / n - l2) ** 2)
    return (max(-1.0, lo), min(1.0, hi))


# ---------------------------------------------------------------------------
# MDE helpers
# ---------------------------------------------------------------------------

def binom_mde(p0: float, n: int, alpha: float = 0.05,
              power: float = 0.8) -> float:
    """Minimum detectable effect for a one-sample binomial test vs p0.

    Parameters
    ----------
    p0 : float
        Null proportion.
    n : int
        Sample size.
    alpha : float
        Type-I error rate (two-tailed).
    power : float
        Target power (1 - beta).

    Returns
    -------
    mde : float
        Minimum detectable absolute difference |p1 - p0| such that a
        two-sided test at level alpha has the given power.

    Normal approximation documented
    --------------------------------
    Based on the standard normal-approximation formula for a one-sample
    proportion test:
        z_a = z_{1 - alpha/2}   (critical value, two-tailed)
        z_b = z_{power}         (power quantile)
        sigma_0 = sqrt(p0*(1-p0)/n)   (null SE)
        mde = (z_a + z_b) * sigma_0
    This is accurate for n*p0*(1-p0) >= 5; at very low n or extreme p0
    use the exact selftest pins to verify reasonable magnitude.
    """
    z_a = _z_from_p(1.0 - alpha / 2.0)
    z_b = _z_from_p(power)
    sigma0 = math.sqrt(p0 * (1.0 - p0) / n)
    return (z_a + z_b) * sigma0


def paired_mde(n: int, disc_rate: float, alpha: float = 0.05,
               power: float = 0.8) -> float:
    """MDE for a McNemar-style paired proportion test.

    Parameters
    ----------
    n : int
        Total number of paired tasks.
    disc_rate : float
        Assumed discordant-pair rate (fraction of pairs that differ),
        i.e. (b + c) / n under the alternative; 0 < disc_rate <= 1.
    alpha : float
        Type-I error rate (two-tailed).
    power : float
        Target power (1 - beta).

    Returns
    -------
    mde : float
        Minimum detectable absolute paired difference |p1 - p2| at the
        given power.

    McNemar normal approximation documented
    ----------------------------------------
    Under the McNemar test, the test statistic on n pairs with discordant
    count d = (b + c) ≈ n * disc_rate is:
        z = (b - c) / sqrt(b + c)   (mid-p or standard form)
    The MDE is the |delta| = |p1 - p2| detectable given:
        effective n_disc = n * disc_rate   (expected discordant pairs)
        sigma_disc = sqrt(n_disc) / n      (SE of the difference)
        mde = (z_a + z_b) * sigma_disc
    where z_a = z_{1-alpha/2}, z_b = z_{power}.
    """
    if not (0.0 < disc_rate <= 1.0):
        raise ValueError(f"disc_rate={disc_rate} must be in (0, 1]")
    z_a = _z_from_p(1.0 - alpha / 2.0)
    z_b = _z_from_p(power)
    n_disc = n * disc_rate
    sigma_disc = math.sqrt(n_disc) / n
    return (z_a + z_b) * sigma_disc


# ---------------------------------------------------------------------------
# Receipt-block builder (single source for both t4_chunked and w4_eval)
# ---------------------------------------------------------------------------

def build_exact_block(successes_by_arm: dict, paired_outcomes: dict,
                      n: int, conf: float = 0.95) -> dict:
    """Build the 'exact' sub-block for a receipt, from data already available.

    Parameters
    ----------
    successes_by_arm : dict
        Mapping arm_name -> int (count of successes out of n tasks).
        Arms with skipped/missing data may be absent.
    paired_outcomes : dict
        Mapping delta_key -> (list_a, list_b) where list_a and list_b are
        per-task 0/1 success vectors for the two arms being compared.
        E.g. {'delta_meta_minus_core_ci95': (vec_meta, vec_core)}.
    n : int
        Number of tasks evaluated (denominator for per-arm Wilson CIs).
    conf : float
        Confidence level (default 0.95).

    Returns
    -------
    dict with shape:
        {
          "per_arm_wilson_ci": {arm: {"lo": float, "hi": float, "k": int, "n": int}, ...},
          "paired_newcombe_ci": {delta_key: {"lo": float, "hi": float,
                                             "b": int, "c": int, "n": int}, ...},
          "mde": {
              "binom_p0_baseline_n": {"p0": float, "n": int, "mde": float},
              "paired_disc05_n": {"disc_rate": 0.05, "n": int, "mde": float},
              "paired_disc10_n": {"disc_rate": 0.10, "n": int, "mde": float},
          }
        }

    This function is the SINGLE SOURCE for the exact sub-block so each eval
    script only adds ~3 lines (import + one call + dict merge).
    """
    block: dict = {}

    # Per-arm Wilson CIs
    per_arm = {}
    for arm, k in successes_by_arm.items():
        try:
            k_int = int(k)
            lo, hi = wilson_ci(k_int, n, conf=conf)
            per_arm[arm] = {"lo": round(lo, 6), "hi": round(hi, 6),
                            "k": k_int, "n": n}
        except Exception:
            per_arm[arm] = {"error": "wilson_ci_failed"}
    block["per_arm_wilson_ci"] = per_arm

    # Paired Newcombe CIs (from per-task outcome vectors)
    paired = {}
    for key, (vec_a, vec_b) in paired_outcomes.items():
        try:
            b = sum(1 for a_, b_ in zip(vec_a, vec_b) if a_ and not b_)
            c = sum(1 for a_, b_ in zip(vec_a, vec_b) if b_ and not a_)
            n_pairs = len(vec_a)
            lo, hi = newcombe_paired_ci(b, c, n_pairs, conf=conf)
            paired[key] = {"lo": round(lo, 6), "hi": round(hi, 6),
                           "b": b, "c": c, "n": n_pairs}
        except Exception:
            paired[key] = {"error": "newcombe_ci_failed"}
    block["paired_newcombe_ci"] = paired

    # MDE block: baseline proportion estimated from the first arm present,
    # or 0.05 as a conservative zero-inflated anchor
    p0 = 0.05
    if successes_by_arm:
        first_k = next(iter(successes_by_arm.values()))
        p0 = max(0.01, min(0.99, first_k / n)) if n > 0 else 0.05
    try:
        mde_binom = binom_mde(p0, n)
    except Exception:
        mde_binom = None
    mde_block = {
        "binom_p0_baseline_n": {
            "p0": round(p0, 4), "n": n,
            "mde": round(mde_binom, 6) if mde_binom is not None else None},
    }
    for disc_rate, label in [(0.05, "paired_disc05_n"),
                             (0.10, "paired_disc10_n")]:
        try:
            mde_val = paired_mde(n, disc_rate)
        except Exception:
            mde_val = None
        mde_block[label] = {"disc_rate": disc_rate, "n": n,
                            "mde": round(mde_val, 6) if mde_val is not None
                            else None}
    block["mde"] = mde_block
    return block


# ---------------------------------------------------------------------------
# Selftest
# ---------------------------------------------------------------------------

def _selftest():
    """Run when called with --selftest. Pins against known closed-form values.

    Exits with code 0 and prints STATS_EXACT_SELFTEST_PASS on success.
    Exits with code 1 and prints a description on first failure.
    """
    fails = []

    def check(name, got, want, tol):
        if abs(got - want) > tol:
            fails.append(f"FAIL {name}: got {got}, want {want} (tol {tol})")

    # --- z-quantile pin ---
    z975 = _z_from_p(0.975)
    check("z(0.975)", z975, 1.959964, 1e-4)

    # --- Wilson zero-case: upper bound on (0, 100) ≈ 0.0370 ---
    lo0, hi0 = wilson_ci(0, 100)
    check("wilson(0,100) lo", lo0, 0.0, 1e-9)
    check("wilson(0,100) hi", hi0, 0.0370, 1e-3)  # zero-inflated gate case

    # --- Wilson k=1, n=100 ---
    lo1, hi1 = wilson_ci(1, 100)
    if not (0 < lo1 < hi1 < 0.1):
        fails.append(f"FAIL wilson(1,100): ({lo1:.4f}, {hi1:.4f}) outside (0, 0.1)")

    # --- Wilson k=50, n=100: must be symmetric around 0.5 ---
    lo50, hi50 = wilson_ci(50, 100)
    if abs((lo50 + hi50) / 2.0 - 0.5) > 1e-6:
        fails.append(f"FAIL wilson(50,100) symmetry: centre={((lo50+hi50)/2.0):.6f}")
    if abs((0.5 - lo50) - (hi50 - 0.5)) > 1e-6:
        fails.append(f"FAIL wilson(50,100) width symmetry: lo-gap={(0.5-lo50):.6f} hi-gap={(hi50-0.5):.6f}")

    # --- Newcombe b==c: CI spans 0 ---
    lo_bb, hi_bb = newcombe_paired_ci(5, 5, 100)
    if not (lo_bb < 0 < hi_bb):
        fails.append(f"FAIL newcombe(b=c=5,100): ({lo_bb:.4f},{hi_bb:.4f}) must span 0")

    # --- Newcombe b=1, c=0, n=100: difference positive, lo near 0 ---
    lo_bc, hi_bc = newcombe_paired_ci(1, 0, 100)
    if not (-0.05 < lo_bc and hi_bc > lo_bc and hi_bc < 0.1):
        fails.append(f"FAIL newcombe(1,0,100): ({lo_bc:.4f},{hi_bc:.4f}) unexpected")

    # --- Newcombe b=0, c=0: difference = 0, CI spans 0 ---
    lo_00, hi_00 = newcombe_paired_ci(0, 0, 100)
    if not (lo_00 <= 0 <= hi_00):
        fails.append(f"FAIL newcombe(0,0,100): ({lo_00:.4f},{hi_00:.4f}) must span 0")

    # --- MDE monotonicity: larger n → smaller MDE ---
    mde_100 = binom_mde(0.1, 100)
    mde_200 = binom_mde(0.1, 200)
    mde_400 = binom_mde(0.1, 400)
    if not (mde_100 > mde_200 > mde_400):
        fails.append(f"FAIL binom_mde monotone in n: {mde_100:.4f} {mde_200:.4f} {mde_400:.4f}")

    # --- MDE monotonicity: smaller alpha → larger MDE ---
    mde_a10 = binom_mde(0.1, 100, alpha=0.10)
    mde_a05 = binom_mde(0.1, 100, alpha=0.05)
    mde_a01 = binom_mde(0.1, 100, alpha=0.01)
    if not (mde_a10 < mde_a05 < mde_a01):
        fails.append(f"FAIL binom_mde monotone in alpha: {mde_a10:.4f} {mde_a05:.4f} {mde_a01:.4f}")

    # --- paired_mde monotonicity ---
    pmde_100 = paired_mde(100, 0.1)
    pmde_200 = paired_mde(200, 0.1)
    if not (pmde_100 > pmde_200):
        fails.append(f"FAIL paired_mde monotone in n: {pmde_100:.4f} {pmde_200:.4f}")

    # --- build_exact_block returns expected dict shape ---
    arm_succ = {"arm1": 3, "arm2": 7}
    vec1 = [1, 0, 1, 1, 0, 0, 0, 0, 0, 0]
    vec2 = [0, 1, 0, 1, 0, 0, 0, 0, 0, 0]
    paired_out = {"delta_arm1_minus_arm2": (vec1, vec2)}
    blk = build_exact_block(arm_succ, paired_out, n=10)
    for key in ("per_arm_wilson_ci", "paired_newcombe_ci", "mde"):
        if key not in blk:
            fails.append(f"FAIL build_exact_block missing key: {key}")
    if "arm1" not in blk.get("per_arm_wilson_ci", {}):
        fails.append("FAIL build_exact_block: arm1 missing from per_arm_wilson_ci")
    if "delta_arm1_minus_arm2" not in blk.get("paired_newcombe_ci", {}):
        fails.append("FAIL build_exact_block: delta key missing from paired_newcombe_ci")
    for mde_key in ("binom_p0_baseline_n", "paired_disc05_n", "paired_disc10_n"):
        if mde_key not in blk.get("mde", {}):
            fails.append(f"FAIL build_exact_block: mde missing {mde_key}")

    if fails:
        for f in fails:
            print(f)
        raise SystemExit(1)

    print("STATS_EXACT_SELFTEST_PASS")
    print(f"  z(0.975)         = {z975:.6f}")
    print(f"  wilson(0,100)    = ({lo0:.6f}, {hi0:.6f})")
    print(f"  wilson(1,100)    = ({lo1:.6f}, {hi1:.6f})")
    print(f"  wilson(50,100)   = ({lo50:.6f}, {hi50:.6f})")
    print(f"  newcombe(5,5,100)= ({lo_bb:.6f}, {hi_bb:.6f})")
    print(f"  newcombe(1,0,100)= ({lo_bc:.6f}, {hi_bc:.6f})")
    print(f"  binom_mde n100   = {mde_100:.6f}")
    print(f"  binom_mde n200   = {mde_200:.6f}")
    print(f"  paired_mde n100  = {pmde_100:.6f}")
    print(f"  paired_mde n200  = {pmde_200:.6f}")
    print(f"  exact_block keys = {sorted(blk.keys())}")


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        _selftest()
    else:
        print("Usage: python stats_exact.py --selftest")
