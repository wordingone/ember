"""fp39_density_power_audit.py — unit-of-analysis audit of the density A/B verdict.

The density A/B (#359 half-2 / verdict DENSITY-AB-VERDICT) reported
DENSITY_CONFIRMED at delta=33.33pp, read as decisive because the spec sized
n=400 prompts -> 3.85pp MDE and 33.33 >> 3.85. This audit shows that reasoning
is a PSEUDOREPLICATION error, and computes the honest seed-level power.

THE FLAW
--------
The wcode probe is empirically BIMODAL: every observed rate (12 of 12 across the
6 cells x {50pct,100pct}) is exactly 0.0 or 1.0. A graded model at, say, 0.5
competence would give ~200/400; getting exactly 0/400 or 400/400 in every cell
means each trained model's pass-probability is ~0 or ~1. So the 400 prompts do
NOT supply 400 independent trials of the density effect — they re-measure ONE
trained model 400 times (correlated to ~1). The unit of analysis for the density
comparison is the SEED (an independent training run), not the prompt.

  spec's claim:   n=400 prompts -> 3.85pp MDE  (assumes prompt-level independence)
  reality:        n=3 seeds per arm, binary cell outcome (crossed / did not)

SEED-LEVEL POWER (the honest number)
------------------------------------
At the seed level the data is: arm_b crossed in 1 of 3 seeds, arm_a in 0 of 3.
Fisher exact (hypergeometric) one-sided p for "arm_b >= observed crossings":
  observed 1/3 vs 0/3  -> p = 0.50   (cannot reject null)
  best case 3/3 vs 0/3 -> p = 0.05   (even a clean sweep is only borderline)
So with 3 seeds and a binary probe the experiment is STRUCTURALLY underpowered;
the prompt count manufactured an illusion of power.

CONSEQUENCE (does NOT rewrite the frozen rule)
----------------------------------------------
The frozen aggregator (density_ab_verdict.py) was written assuming wcode_rate is
a graded continuous metric, so it maps CONFIRMED->D-CONF. That rule was frozen
pre-data; this audit does NOT retro-tighten it. It registers a DEVIATION: the
verdict is DIRECTIONALLY correct (curated crossed, bulk never did) but NOT
statistically powered at the seed level. The c04 pick consuming D-CONF must treat
it as a directional prior, not powered evidence. The 2.2B budget-cap corner and
the user-owned <=1-day pretrain bar are the hedges that make an underpowered
D-CONF non-catastrophic. The hardening path (successor): a GRADED probe (so
within-cell prompts add real power) + more seeds.

Emits a receipt; selftest validates the hypergeometric on known cases.
"""
import glob
import json
import math
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
NC = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from receipt_write import checked_write  # noqa: E402

RECEIPTS = f"{NC}/receipts"
SPEC_CLAIMED_MDE_PP = 3.85   # docs/c04-token-budget-v1.md F-4: n=400 -> 3.85pp
EXTREME_TOL = 1e-9
REAL_VERDICTS = {"DENSITY_CONFIRMED", "DENSITY_MARGINAL",
                 "DENSITY_REVERSED", "DENSITY_FLAT"}


def fisher_one_sided_ge(a, b, c, d):
    """One-sided Fisher exact p for P(arm_b crossings >= a) in the 2x2

        [[a, b],   # arm_b: crossed=a, not=b
         [c, d]]   # arm_a: crossed=c, not=d

    Sum hypergeometric tail over k from a up to min(a+b, a+c).
    """
    n = a + b + c + d
    row1 = a + b          # arm_b seeds
    col1 = a + c          # total crossings
    kmax = min(row1, col1)
    denom = math.comb(n, col1)
    p = 0.0
    for k in range(a, kmax + 1):
        # k crossings in arm_b, (col1-k) in arm_a; choose which seeds crossed
        p += math.comb(row1, k) * math.comb(n - row1, col1 - k) / denom
    return p


def _load_verdict():
    """Read the latest REAL density verdict receipt (the committed, reproducible
    6-cell aggregation). The individual arm_a seed0/seed1 cell receipts were
    never committed (only embedded here), so the verdict is the authoritative
    source — re-globbing individual cells undercounts. Returns the receipt dict
    or None."""
    chosen = None
    for path in sorted(glob.glob(f"{RECEIPTS}/density-ab-verdict-*.json")):
        try:
            r = json.load(open(path))
        except Exception:
            continue
        if r.get("verdict") in REAL_VERDICTS:
            if chosen is None or r["ts"] > chosen["ts"]:
                chosen = r
    return chosen


def _seed_ints(cells_block):
    out = []
    for k in cells_block:
        if k.startswith("seed"):
            try:
                out.append(int(k[4:]))
            except ValueError:
                pass
    return sorted(out)


def _vrate(cells_block, seed, point):
    return cells_block.get(f"seed{seed}", {}).get(f"wcode_{point}")


def audit():
    v = _load_verdict()
    if v is None:
        print(json.dumps({"verdict": "NO_REAL_VERDICT_ON_DISK"}))
        sys.exit(2)
    a_cells = v["arm_a"]["cells"]
    b_cells = v["arm_b"]["cells"]
    seeds = sorted(set(_seed_ints(a_cells)) & set(_seed_ints(b_cells)))

    # 1. bimodality evidence: count observations at the {0,1} extremes
    obs, extreme = [], 0
    for cells_block in (a_cells, b_cells):
        for s in _seed_ints(cells_block):
            for pt in ("50pct", "100pct"):
                val = _vrate(cells_block, s, pt)
                if val is None:
                    continue
                obs.append(val)
                if abs(val) <= EXTREME_TOL or abs(val - 1.0) <= EXTREME_TOL:
                    extreme += 1
    bimodal = (len(obs) > 0 and extreme == len(obs))

    # 2. seed-level crossings at 100pct (crossed == rate 1.0)
    b_cross = sum(1 for s in seeds if abs((_vrate(b_cells, s, "100pct") or 0) - 1.0) <= EXTREME_TOL)
    a_cross = sum(1 for s in seeds if abs((_vrate(a_cells, s, "100pct") or 0) - 1.0) <= EXTREME_TOL)
    n_seeds = len(seeds)

    # 3. seed-level Fisher exact (observed and best-case)
    p_observed = fisher_one_sided_ge(b_cross, n_seeds - b_cross, a_cross, n_seeds - a_cross)
    p_bestcase = fisher_one_sided_ge(n_seeds, 0, 0, n_seeds)

    powered = p_observed < 0.05
    verdict = ("DENSITY_POWERED" if powered else
               "DENSITY_UNDERPOWERED_PSEUDOREPLICATION")

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt = {
        "ticket": "FP39-DENSITY-POWER-AUDIT",
        "ts": ts,
        "issue": 359,
        "audited_verdict_ts": v["ts"],
        "audited_verdict_class": v["verdict"],
        "verdict": verdict,
        "unit_of_analysis": "seed" if bimodal else "prompt",
        "bimodal_probe": bimodal,
        "extreme_observations": f"{extreme}/{len(obs)}",
        "n_seeds_per_arm": n_seeds,
        "arm_b_crossings": b_cross,
        "arm_a_crossings": a_cross,
        "seed_level_fisher_p_one_sided": round(p_observed, 4),
        "seed_level_fisher_p_bestcase_3of3": round(p_bestcase, 4),
        "spec_claimed_mde_pp_n400": SPEC_CLAIMED_MDE_PP,
        "finding": (
            "wcode probe is bimodal (all rates in {0,1}); 400 prompts re-measure "
            "ONE model so the comparison unit is the seed, not the prompt. The "
            "spec's n=400 -> 3.85pp MDE assumed prompt-level independence "
            "(pseudoreplication). Honest seed-level power: 1/3 vs 0/3 -> p=0.50; "
            "even a clean 3/3 vs 0/3 sweep -> p=0.05."
        ),
        "consequence": (
            "Frozen aggregator maps CONFIRMED->D-CONF; this audit does NOT rewrite "
            "that rule (frozen pre-data). It registers the deviation: D-CONF is a "
            "DIRECTIONAL prior here, not powered evidence. c04 pick must consume it "
            "as such; the 2.2B budget-cap corner + user-owned <=1-day pretrain bar "
            "are the hedges. Hardening successor: graded probe + more seeds."
        ),
        "caveats": [
            "directional finding stands: curated crossed in 1/3 seeds, bulk in 0/3",
            "bimodality is empirical (12/12 obs at extremes), not assumed",
            "read from the verdict receipt: arm_a seed0/seed1 individual cell "
            "receipts were never committed (only embedded in the verdict) — a "
            "minor reproducibility gap flagged to eli",
        ],
    }
    out = f"{RECEIPTS}/fp39-density-power-audit-{ts}.json"
    checked_write(out, receipt)
    print(json.dumps({
        "verdict": verdict,
        "unit_of_analysis": receipt["unit_of_analysis"],
        "n_seeds_per_arm": n_seeds,
        "crossings_b_vs_a": f"{b_cross}/{n_seeds} vs {a_cross}/{n_seeds}",
        "seed_level_p": round(p_observed, 4),
        "bestcase_p": round(p_bestcase, 4),
    }, indent=2))
    print(f"FP39_DENSITY_POWER_AUDIT_DONE {os.path.relpath(out, NC)}")
    return verdict


def selftest():
    cases = [
        # (b_cross, b_not, a_cross, a_not, expected_p, label)
        (1, 2, 0, 3, 0.50, "observed 1/3 vs 0/3"),
        (3, 0, 0, 3, 0.05, "best-case 3/3 vs 0/3"),
        (2, 1, 0, 3, 0.20, "2/3 vs 0/3"),
        (0, 3, 0, 3, 1.00, "0/3 vs 0/3 (no crossings)"),
    ]
    ok = True
    for b, bn, a, an, exp, lbl in cases:
        p = round(fisher_one_sided_ge(b, bn, a, an), 4)
        match = abs(p - exp) <= 1e-9
        ok = ok and match
        print(f"  [{'PASS' if match else 'FAIL'}] {lbl}: p={p} (expected {exp})")
    print("FP39_POWER_AUDIT_SELFTEST_" + ("PASS" if ok else "FAIL"))
    return ok


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(0 if selftest() else 1)
    audit()
