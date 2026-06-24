"""calibrate — P(verify) elicitation scoring (eng #6, audit §8.2).

Judgment's verifiable core: before sampling, the model states P(verify) per
task; after V runs, the prediction is Brier-scored against per-sample
outcomes. The calibrated P-hat is also vbits' preferred estimator (§3b
preference 1), making calibration part of the feed pipeline.

Pure stdlib scoring functions; elicitation itself lives in w1_mbpp
(--calibrate). `python calibrate.py --selftest`.
"""
import re

_NUM = re.compile(r"(?<![\d.])(?:0?\.\d+|0|1(?:\.0+)?)(?![\d.])")
_PCT = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*%")


def parse_prob(text):
    """First probability in the text: bare float in [0,1] or 'NN%'.
    Returns float clamped to [0.01, 0.99], or None if unparseable
    (clamping keeps -log2 and Brier finite; raw parse recorded by caller)."""
    if not text:
        return None
    m = _PCT.search(text)
    if m:
        v = float(m.group(1)) / 100.0
    else:
        m = _NUM.search(text)
        if not m:
            return None
        v = float(m.group(0))
    if not 0.0 <= v <= 1.0:
        return None
    return min(0.99, max(0.01, v))


def brier(pairs):
    """Mean squared error of probabilistic predictions.
    pairs: iterable of (p, y) with y in {0,1}. Lower = better; 0.25 = the
    uninformed-0.5 baseline on any outcome mix."""
    pairs = list(pairs)
    if not pairs:
        return None
    return sum((p - y) ** 2 for p, y in pairs) / len(pairs)


def reliability(pairs, n_bins=5):
    """Reliability table: per prediction-bin (mean_p, observed_rate, n)."""
    pairs = list(pairs)
    bins = []
    for b in range(n_bins):
        lo, hi = b / n_bins, (b + 1) / n_bins
        sel = [(p, y) for p, y in pairs
               if (lo <= p < hi) or (b == n_bins - 1 and p == hi)]
        if sel:
            bins.append({"bin": f"[{lo:.1f},{hi:.1f})",
                         "mean_p": round(sum(p for p, _ in sel) / len(sel), 4),
                         "observed": round(sum(y for _, y in sel) / len(sel), 4),
                         "n": len(sel)})
    return bins


def calibration_block(predicted_by_task, outcomes_by_task):
    """Receipt block: Brier over per-sample outcomes + reliability + coverage.
    predicted_by_task: {task: float|None}; outcomes_by_task: {task: [0/1,..]}."""
    pairs = []
    parsed = sum(1 for v in predicted_by_task.values() if v is not None)
    for task, p in predicted_by_task.items():
        if p is None:
            continue
        for y in outcomes_by_task.get(task, []):
            pairs.append((p, y))
    base_rate = None
    all_y = [y for ys in outcomes_by_task.values() for y in ys]
    if all_y:
        base_rate = sum(all_y) / len(all_y)
    b = brier(pairs)
    # reference: predicting the realized base rate for every sample
    ref = (brier([(base_rate, y) for y in all_y])
           if base_rate is not None else None)
    return {"elicited": len(predicted_by_task), "parsed": parsed,
            "brier": round(b, 4) if b is not None else None,
            "brier_base_rate_ref": round(ref, 4) if ref is not None else None,
            "skill_vs_base_rate": (round(ref - b, 4)
                                   if b is not None and ref is not None
                                   else None),
            "reliability": reliability(pairs)}


def murphy_decomposition(pairs, n_bins=10):
    """Brier = REL - RES + UNC (Murphy 1973), binned by prediction.

    REL (reliability, lower better): how far bin-mean predictions sit from
    bin-observed rates. RES (resolution, higher better): how far bin
    outcomes spread from the base rate — zero resolution = zero
    discrimination regardless of REL. UNC: base-rate variance, the
    predictor-independent floor. Exact identity when predictions are
    constant within bins; binning residual reported as `residual`."""
    pairs = list(pairs)
    n = len(pairs)
    if not n:
        return None
    obar = sum(y for _, y in pairs) / n
    rel = res = 0.0
    for b in range(n_bins):
        lo, hi = b / n_bins, (b + 1) / n_bins
        sel = [(p, y) for p, y in pairs
               if (lo <= p < hi) or (b == n_bins - 1 and p == hi)]
        if not sel:
            continue
        nk = len(sel)
        pk = sum(p for p, _ in sel) / nk
        ok = sum(y for _, y in sel) / nk
        rel += nk * (pk - ok) ** 2
        res += nk * (ok - obar) ** 2
    rel, res = rel / n, res / n
    unc = obar * (1 - obar)
    b_actual = brier(pairs)
    return {"brier": round(b_actual, 4), "reliability": round(rel, 4),
            "resolution": round(res, 4), "uncertainty": round(unc, 4),
            "residual": round(b_actual - (rel - res + unc), 4),
            "n": n, "base_rate": round(obar, 4)}


def per_task_skill(predicted_by_task, outcomes_by_task):
    """Per-task skill contributions s_t = mean_y[(obar-y)^2 - (p_t-y)^2]
    against the GLOBAL base rate (positive = beats base-rate reference).
    Returns (skills list, obar). Tasks without parsed predictions skipped."""
    all_y = [y for t, ys in outcomes_by_task.items()
             if predicted_by_task.get(t) is not None for y in ys]
    obar = sum(all_y) / len(all_y)
    skills = []
    for t, p in predicted_by_task.items():
        if p is None:
            continue
        ys = outcomes_by_task.get(t, [])
        if ys:
            skills.append(sum((obar - y) ** 2 - (p - y) ** 2
                              for y in ys) / len(ys))
    return skills, obar


def skill_mde(skills, n_tasks, z=2.8015852335973596):
    """Detectable mean skill at n_tasks elicitations (80% power, two-sided
    .05; z = z_.975 + z_.80), using the empirical per-task skill sd."""
    import math
    m = sum(skills) / len(skills)
    sd = math.sqrt(sum((s - m) ** 2 for s in skills) / (len(skills) - 1))
    return z * sd / math.sqrt(n_tasks)


def _selftest():
    assert parse_prob("0.7") == 0.7
    assert parse_prob("I'd say 70% likely") == 0.7
    assert parse_prob("probability: 0.05") == 0.05
    assert parse_prob("1") == 0.99 and parse_prob("0") == 0.01  # clamps
    assert parse_prob("no idea") is None and parse_prob("") is None
    assert parse_prob("3.5") is None  # out of range, not a probability
    # perfect predictions -> brier 0; constant 0.5 -> 0.25
    assert brier([(1.0, 1), (0.0, 0)]) == 0.0
    assert brier([(0.5, 1), (0.5, 0)]) == 0.25
    blk = calibration_block({"a": 0.9, "b": 0.1, "c": None},
                            {"a": [1, 1, 1, 1], "b": [0, 0, 0, 1],
                             "c": [1, 0]})
    assert blk["elicited"] == 3 and blk["parsed"] == 2
    assert blk["brier"] is not None and blk["brier"] < 0.25
    assert blk["skill_vs_base_rate"] is not None
    assert any(r["n"] for r in blk["reliability"])
    # murphy: perfect binary predictor -> REL~0, RES~UNC, brier~0
    perfect = [(0.99, 1)] * 5 + [(0.01, 0)] * 5
    d = murphy_decomposition(perfect)
    assert d["reliability"] < 0.001 and abs(d["resolution"] - d["uncertainty"]) < 0.001
    # constant-0.5 predictor on a 50/50 mix -> RES=0, brier=0.25=UNC
    flat = [(0.5, 1)] * 5 + [(0.5, 0)] * 5
    d2 = murphy_decomposition(flat)
    assert d2["resolution"] == 0.0 and d2["brier"] == 0.25
    assert abs(d2["residual"]) < 1e-9  # identity exact (constant in bin)
    # per-task skill: knowing predictor positive, anti-predictor negative
    pred = {"a": 0.9, "b": 0.1}
    outs = {"a": [1, 1, 1], "b": [0, 0, 0]}
    sk, _ = per_task_skill(pred, outs)
    assert all(s > 0 for s in sk)
    anti = {"a": 0.1, "b": 0.9}
    sk2, _ = per_task_skill(anti, outs)
    assert all(s < 0 for s in sk2)
    # mde shrinks with n
    assert skill_mde(sk + sk2, 200) < skill_mde(sk + sk2, 50)
    print("CALIBRATE_SELFTEST_PASS")


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        _selftest()
    else:
        print(__doc__)
