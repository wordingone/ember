"""fp15_bandtransfer.py — band-vs-nonband transfer yield, pre-registered (#90).

fp-12 stabilized the upvalued band (small-core laplace phat < large-core,
s15>0; kappa 0.472 p=0.0003). fp-15's claim to falsify: the band PREDICTS
where the loop should spend GPU — band tasks yield more per GPU-minute.

PRE-REGISTRATION (frozen HERE, before round-2 exists — the analysis can
never be fitted to the receipts it will judge):

  Prong A (computable from round-2 sampling receipts alone):
    yield = NEW verified episodes per sampled k, split band vs nonband
    (band = fp12_band.band_member on the ROUND-1 per-task stats, frozen
    inputs — never recomputed from round-2 outcomes). Verdict: band
    PREDICTIVE if yield_band/yield_nonband >= 1.5 with a permutation
    p < 0.05 (10k shuffles of band labels over tasks, seed 17);
    REFUTED-direction if ratio <= 1/1.5; else INCONCLUSIVE.
  Prong B (named, fires round-3 ONLY if A is PREDICTIVE): matched-step
    band-only vs nonband-only training arm pair; G1 paired delta decides
    transfer (yield alone cannot — sampling ease != transfer value).

`--selftest` pure-logic. main() on a round-2 receipt:
  python fp15_bandtransfer.py --sampling <t2-receipt.json> --r1 <stats.json>
Emits receipts/fp15-bandtransfer-<ts>.json or the STAGED sentinel if the
round-2 inputs are absent.
"""
import json
import random
import sys
from datetime import datetime, timezone

RATIO_BAR = 1.5
PERM_N = 10000
SEED = 17


def split_yield(tasks):
    """tasks: list of {task, band(bool), k_sampled, new_verified}."""
    def agg(rows):
        k = sum(r["k_sampled"] for r in rows)
        v = sum(r["new_verified"] for r in rows)
        return {"tasks": len(rows), "k": k, "verified": v,
                "yield": (v / k) if k else None}
    band = [t for t in tasks if t["band"]]
    non = [t for t in tasks if not t["band"]]
    return {"band": agg(band), "nonband": agg(non)}


def perm_pvalue(tasks, seed=SEED, n=PERM_N):
    """One-sided p for observed yield ratio under label shuffles."""
    obs = split_yield(tasks)
    if not obs["band"]["yield"] or not obs["nonband"]["yield"]:
        return None, obs
    obs_ratio = obs["band"]["yield"] / obs["nonband"]["yield"]
    labels = [t["band"] for t in tasks]
    rng = random.Random(seed)
    hits = 0
    for _ in range(n):
        rng.shuffle(labels)
        sh = split_yield([{**t, "band": b} for t, b in zip(tasks, labels)])
        if sh["band"]["yield"] and sh["nonband"]["yield"]:
            r = sh["band"]["yield"] / sh["nonband"]["yield"]
            if r >= obs_ratio:
                hits += 1
    return hits / n, obs


def verdict(obs, p):
    rb = obs["band"]["yield"]; rn = obs["nonband"]["yield"]
    if rb is None or rn in (None, 0):
        return {"verdict": "INCOMPUTABLE", "flag": "empty split"}
    ratio = rb / rn
    if ratio >= RATIO_BAR and p is not None and p < 0.05:
        v = "PREDICTIVE"
    elif ratio <= 1 / RATIO_BAR:
        v = "REFUTED-direction"
    else:
        v = "INCONCLUSIVE"
    return {"verdict": v, "ratio": round(ratio, 3), "perm_p": p,
            "bar": RATIO_BAR,
            "prong_b": ("fires round-3 (band-only vs nonband-only matched "
                        "arms)" if v == "PREDICTIVE" else "does not fire")}


def _selftest():
    mk = lambda b, k, v: {"task": f"t{b}{k}{v}", "band": b,
                          "k_sampled": k, "new_verified": v}
    # strong separation: band yields 0.5, nonband 0.1
    tasks = [mk(True, 8, 4) for _ in range(10)] + \
            [mk(False, 8, 1) for _ in range(10)] + [mk(False, 8, 0)] * 5
    p, obs = perm_pvalue(tasks, n=2000)
    assert obs["band"]["yield"] == 0.5
    v = verdict(obs, p)
    assert v["verdict"] == "PREDICTIVE" and p < 0.05, (v, p)
    # null: identical yields -> inconclusive, p high
    tasks2 = [mk(True, 8, 2) for _ in range(10)] + \
             [mk(False, 8, 2) for _ in range(10)]
    p2, obs2 = perm_pvalue(tasks2, n=2000)
    assert verdict(obs2, p2)["verdict"] == "INCONCLUSIVE"
    assert p2 > 0.05
    # reversed: band worse by >1.5x -> REFUTED-direction
    tasks3 = [mk(True, 10, 1) for _ in range(8)] + \
             [mk(False, 10, 4) for _ in range(8)]
    p3, obs3 = perm_pvalue(tasks3, n=500)
    assert verdict(obs3, p3)["verdict"] == "REFUTED-direction"
    # empty split guarded
    assert verdict(split_yield([mk(True, 8, 1)]), None)["verdict"] == \
        "INCOMPUTABLE"
    print("FP15_BANDTRANSFER_SELFTEST_PASS")


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--sampling")
    ap.add_argument("--r1-stats")
    a, _ = ap.parse_known_args()
    if not a.sampling:
        print("FP15_BANDTRANSFER_STAGED (no round-2 sampling receipt yet; "
              "prereg frozen in this file — fp-21 runs it)")
        return
    # fp-21 wires the real receipt fields here; predicate import pinned:
    from fp12_band import band_member  # noqa: F401 — frozen single source
    raise SystemExit("fp-21 implements the receipt join on real round-2 "
                     "fields; running before then would un-freeze the spec")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        main()
