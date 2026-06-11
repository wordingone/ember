"""fp4_cross_core.py — is on-policy-ness core-size-transferable? (#52)

CPU-only analysis over RECEIPTED samples (no new sampling): the 1.5B core
(w1-floor-q15, 120 train tasks x k=8 seed 14) and the 3B core
(w1-floor-q3, same tasks/k/seed — identical prompts, different core)
solved the same pool. If a small sampler is to feed a larger
consolidator, the small core's cracks must point at the large core's
cracks. Three measurables, receipted:

  1. Per-task solve-rate agreement: Pearson r (+ rank r) across the 120
     paired tasks, bootstrap CI (10k, seed 16).
  2. Stratum confusion matrix (frontier.stratum bands): where do bits
     live per core, and is the frontier/dead set (the high-bits band)
     the SAME set? Jaccard on frontier+dead membership.
  3. Verbatim program overlap: sha1 of verified srcs — are the small
     core's verified programs literally the big core's programs? High
     overlap = "on-policy" at SFT reduces toward data quality, not
     source identity; low overlap = distributions genuinely differ.

This receipt DESIGNS the GPU falsification arm (named in audit §8.12:
3B-MTP trained on 1.5B-generated episodes, matched budget) — it does not
replace it. `python fp4_cross_core.py --selftest`.
"""
import hashlib
import json
import math
import random
from datetime import datetime, timezone

from frontier import stratum
from receipt_write import checked_write

NC_WIN = "B:/M/avir/leo/state/nc-ladder"
RECEIPTS = f"{NC_WIN}/receipts"
Q15 = f"{RECEIPTS}/w1-floor-q15-20260610T202511Z-samples.jsonl"
Q3 = f"{RECEIPTS}/w1-floor-q3-20260610T203401Z-samples.jsonl"
STRATA = ("dead", "frontier", "mid", "easy")


def load(path):
    """-> {task: {"s": int, "n": int, "shas": set(verified src sha1)}}"""
    by = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            t = r["task"]
            d = by.setdefault(t, {"s": 0, "n": 0, "shas": set()})
            d["n"] += 1
            if r.get("verified"):
                d["s"] += 1
                if r.get("src"):
                    d["shas"].add(hashlib.sha1(
                        r["src"].encode("utf-8")).hexdigest())
    return by


def pearson(xs, ys):
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
    vx = sum((a - mx) ** 2 for a in xs)
    vy = sum((b - my) ** 2 for b in ys)
    if vx == 0 or vy == 0:
        return 0.0
    return cov / math.sqrt(vx * vy)


def ranks(xs):
    """midrank transform (ties averaged)."""
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    rk = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        r = (i + j) / 2 + 1
        for k in range(i, j + 1):
            rk[order[k]] = r
        i = j + 1
    return rk


def boot_ci(xs, ys, n_boot=10000, seed=16):
    rng = random.Random(seed)
    n = len(xs)
    vals = []
    for _ in range(n_boot):
        idx = [rng.randrange(n) for _ in range(n)]
        vals.append(pearson([xs[i] for i in idx], [ys[i] for i in idx]))
    vals.sort()
    return (vals[int(0.025 * n_boot)], vals[int(0.975 * n_boot) - 1])


def analyze(a, b):
    """a, b: load() tables sharing a task set."""
    tasks = sorted(set(a) & set(b))
    ra = [a[t]["s"] / a[t]["n"] for t in tasks]
    rb = [b[t]["s"] / b[t]["n"] for t in tasks]
    sa = [stratum(a[t]["s"], a[t]["n"]) for t in tasks]
    sb = [stratum(b[t]["s"], b[t]["n"]) for t in tasks]
    conf = {x: {y: 0 for y in STRATA} for x in STRATA}
    for x, y in zip(sa, sb):
        conf[x][y] += 1
    hot_a = {t for t, s in zip(tasks, sa) if s in ("dead", "frontier")}
    hot_b = {t for t, s in zip(tasks, sb) if s in ("dead", "frontier")}
    jacc = (len(hot_a & hot_b) / len(hot_a | hot_b)) if hot_a | hot_b else 1.0
    # verbatim verified-program overlap (task-scoped shas)
    pairs_a = {(t, h) for t in tasks for h in a[t]["shas"]}
    pairs_b = {(t, h) for t in tasks for h in b[t]["shas"]}
    overlap = (len(pairs_a & pairs_b) / len(pairs_a)) if pairs_a else 0.0
    lo, hi = boot_ci(ra, rb)
    return {
        "n_tasks": len(tasks),
        "rate_pearson": round(pearson(ra, rb), 4),
        "rate_pearson_ci95": [round(lo, 4), round(hi, 4)],
        "rate_rank_r": round(pearson(ranks(ra), ranks(rb)), 4),
        "stratum_confusion_rows_small_cols_big": conf,
        "hot_band": {"small_n": len(hot_a), "big_n": len(hot_b),
                     "intersection": len(hot_a & hot_b),
                     "jaccard": round(jacc, 4)},
        "verified_program_verbatim_overlap": {
            "small_pairs": len(pairs_a), "big_pairs": len(pairs_b),
            "shared": len(pairs_a & pairs_b),
            "frac_of_small_in_big": round(overlap, 4)},
    }


def main():
    a, b = load(Q15), load(Q3)
    res = analyze(a, b)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt = {
        "ticket": "FP4-CROSS-CORE", "ts": ts,
        "small": Q15.split("/")[-1], "big": Q3.split("/")[-1],
        "pairing": "identical prompts/split/k/seed (train 120 x k=8 "
                   "seed 14); only the core differs",
        "analysis": res,
        "falsification_arm": "3B-MTP trained on 1.5B-q15 verified episodes "
                             "(w2-pipeline build, matched to t2-r1w-q3-mtp "
                             "budget) -> G1 paired vs the receipted "
                             "MTP-on-own arm; round-3 GPU window",
    }
    out = f"{RECEIPTS}/fp4-cross-core-{ts}.json"
    checked_write(out, receipt)
    print(json.dumps(receipt, indent=2))
    print(f"FP4_CROSS_CORE_DONE {out}")


def _selftest():
    mk = lambda s, n, tag: {"s": s, "n": n,  # noqa: E731
                            "shas": {f"{tag}{i}" for i in range(s)}}
    # identical tables -> r=1, diagonal confusion, jaccard 1, overlap 0
    # (shas disjoint by tag) then shared-sha variant -> overlap 1
    a = {f"t{i}": mk(i % 9, 8, "x") for i in range(40)}
    b = {f"t{i}": mk(i % 9, 8, "x") for i in range(40)}
    r = analyze(a, b)
    assert r["rate_pearson"] == 1.0 and r["rate_rank_r"] == 1.0
    conf = r["stratum_confusion_rows_small_cols_big"]
    assert all(conf[x][y] == 0 for x in STRATA for y in STRATA if x != y)
    assert r["hot_band"]["jaccard"] == 1.0
    assert r["verified_program_verbatim_overlap"][
        "frac_of_small_in_big"] == 1.0
    # anti-correlated rates -> r == -1
    a2 = {f"t{i}": mk(i % 9, 8, "p") for i in range(36)}
    b2 = {f"t{i}": mk(8 - i % 9, 8, "q") for i in range(36)}
    r2 = analyze(a2, b2)
    assert r2["rate_pearson"] == -1.0
    assert r2["verified_program_verbatim_overlap"][
        "frac_of_small_in_big"] == 0.0
    # ranks: ties get midranks
    assert ranks([1, 1, 2]) == [1.5, 1.5, 3.0]
    # bootstrap deterministic
    xs, ys = [0.1, 0.5, 0.9, 0.3, 0.7], [0.2, 0.4, 0.8, 0.35, 0.65]
    assert boot_ci(xs, ys) == boot_ci(xs, ys)
    print("FP4_CROSS_CORE_SELFTEST_PASS")


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        _selftest()
    else:
        main()
