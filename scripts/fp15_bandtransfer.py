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
import os
import random
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from receipt_write import checked_write  # noqa: E402 (eng #107)

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


def _per_task_stats(samples_path):
    """samples jsonl -> {task: (verified, sampled)}."""
    stats = {}
    with open(samples_path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            row = json.loads(line)
            v, n = stats.get(row["task"], (0, 0))
            stats[row["task"]] = (v + (1 if row.get("verified") else 0), n + 1)
    return stats


def main():
    """fp-21 (#120): the receipt join, implemented at fire time on real
    round-2 fields. The analysis above (split_yield/perm_pvalue/verdict,
    RATIO_BAR/PERM_N/SEED) is the FROZEN prereg — untouched here.

    JOIN CHOICES (declared before any yield was computed; recorded
    in-receipt):
      - band inputs: ROUND-1 per-task stats from the three fp12-receipt-
        pinned samples files; q3 side = POOLED k8 + focus-k24 (all round-1
        stats, no leg selection — fp-12 showed the two legs disagree,
        jaccard 0.42; pooling avoids an outcome-dependent leg pick).
      - universe: tasks sampled in round-2 WITH joint round-1 coverage
        (n15>0 and n3>0 — band_member needs both posteriors);
        out-of-universe counts recorded, never silently dropped.
      - new_verified: round==2 rows in ledger/episodes.jsonl per task
        (post-dedup banked NEW episodes = the accumulation the loop kept).
      - k_sampled: round-2 sample rows per task (k=8 by prereg pin).
    """
    import argparse
    import os
    ap = argparse.ArgumentParser()
    ap.add_argument("--sampling", help="round-2 w1 *-samples.jsonl")
    ap.add_argument("--ledger", default=None)
    a, _ = ap.parse_known_args()
    if not a.sampling:
        print("FP15_BANDTRANSFER_STAGED (no round-2 sampling receipt yet; "
              "prereg frozen in this file — fp-21 runs it)")
        return
    from fp12_band import band_member  # frozen single source

    NC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ledger = a.ledger or f"{NC}/ledger/episodes.jsonl"
    R = f"{NC}/receipts"
    legs = {  # pinned in receipts/fp12-band-20260611T010941Z.json
        "q15": f"{R}/w1-floor-q15-20260610T202511Z-samples.jsonl",
        "q3_k8": f"{R}/w1-floor-q3-20260610T203401Z-samples.jsonl",
        "q3_focus_k24": f"{R}/w1-floor-q3-focus-20260610T210228Z-samples.jsonl",
    }
    s15 = _per_task_stats(legs["q15"])
    q3a = _per_task_stats(legs["q3_k8"])
    q3b = _per_task_stats(legs["q3_focus_k24"])
    q3 = {}
    for t in set(q3a) | set(q3b):
        va, na = q3a.get(t, (0, 0))
        vb, nb = q3b.get(t, (0, 0))
        q3[t] = (va + vb, na + nb)

    r2_k = {}
    with open(a.sampling, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                t = json.loads(line)["task"]
                r2_k[t] = r2_k.get(t, 0) + 1
    new_v = {}
    with open(ledger, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            rec = json.loads(line)
            if rec.get("round") == 2 and rec.get("verified"):
                new_v[rec["task"]] = new_v.get(rec["task"], 0) + 1

    tasks, no_joint = [], []
    for t, k in sorted(r2_k.items()):
        v15, n15 = s15.get(t, (0, 0))
        v3, n3 = q3.get(t, (0, 0))
        if n15 == 0 or n3 == 0:
            no_joint.append(t)
            continue
        tasks.append({"task": t, "band": band_member(v15, n15, v3, n3),
                      "k_sampled": k, "new_verified": new_v.get(t, 0)})

    p, obs = perm_pvalue(tasks)
    v = verdict(obs, p)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt = {
        "ticket": "FP15-BANDTRANSFER", "ts": ts, "prong": "A",
        "frozen_bars": {"ratio_bar": RATIO_BAR, "perm_n": PERM_N,
                        "seed": SEED},
        "join": {
            "band_inputs": legs,
            "q3_side": "POOLED k8 + focus-k24 (declared pre-yield; "
                       "no outcome-dependent leg pick)",
            "new_verified_source": "ledger round==2 verified rows "
                                   "(post-dedup banked NEW)",
            "sampling": os.path.basename(a.sampling),
        },
        "universe": {"r2_sampled_tasks": len(r2_k),
                     "joint_coverage_tasks": len(tasks),
                     "no_joint_round1_stats": len(no_joint),
                     "band_tasks": sum(1 for t in tasks if t["band"]),
                     "nonband_tasks": sum(1 for t in tasks if not t["band"])},
        "observed": obs,
        "perm_p": p,
        "result": v,
        "prong_b_rule": "fires round-3 ONLY on PREDICTIVE (frozen)",
    }
    out = f"{R}/fp15-bandtransfer-{ts}.json"
    checked_write(out, receipt)
    print(json.dumps(receipt, indent=2))
    print(f"FP15_BANDTRANSFER_DONE {out}")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        main()
