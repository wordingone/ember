"""g1_paired.py — W-code round-1 G1 paired analysis (pre-registered).

Executes the EXACT invocation pre-registered in
research/r1w-g1-decision-tree.md (#32, committed BEFORE the control/MTP
legs landed): samples files (base/a/control/mtp, + grpo when its leg
landed via #24; validation 43 x k=8, seed 16 across arms -> per-task
pairing), two metrics with fixed roles —

  - task-level feed (any-of-8): McNemar exact test on discordant pairs +
    Newcombe paired-delta interval (power.newcombe_paired_delta).
    PRIMARY metric for HARM (ceiling: base feeds 39/43).
  - sample-level per-task verify rate: paired mean difference, bootstrap
    CI (10k resamples, seed 16) + paired MDE. PRIMARY metric for GAINS.

Verdict flags per pair: UP/DOWN = 95% CI excludes 0 (bootstrap for
sample-level, Newcombe for task-level); FLAT = CI includes 0, reported
with MDE. Sharpening-narrowing signature = task-feed DOWN AND sample UP.
Cell -> named round-2 design per the tree; the receipt records the fired
cell. Pure stdlib (+ power, same dir). `python g1_paired.py --selftest`.
"""
import argparse
import glob as globlib
import json
import math
import os
import random
from datetime import datetime, timezone

from power import Z80, Z975, newcombe_paired_delta

NC_WIN = "B:/M/avir/leo/state/nc-ladder"
RECEIPTS = f"{NC_WIN}/receipts"
ARMS = ("base", "a", "control", "mtp", "grpo")
PAIRS = (("a", "base"), ("control", "base"), ("mtp", "base"),
         ("a", "control"), ("mtp", "a"), ("mtp", "control"),
         ("grpo", "base"), ("grpo", "control"), ("grpo", "a"),
         ("grpo", "mtp"))


def load_samples(path):
    """samples.jsonl -> {task: [0/1, ...]} in file order."""
    by_task = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            by_task.setdefault(r["task"], []).append(
                1 if r.get("verified") else 0)
    return by_task


def mcnemar_exact(b, c):
    """Two-sided exact McNemar p over discordant pairs (binomial p=.5)."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(0, k + 1)) / (2 ** n)
    return min(1.0, 2 * tail)


def paired_bootstrap(diffs, n_boot=10000, seed=16):
    """Percentile CI (2.5/97.5) of the mean of per-task diffs."""
    rng = random.Random(seed)
    n = len(diffs)
    means = []
    for _ in range(n_boot):
        means.append(sum(diffs[rng.randrange(n)] for _ in range(n)) / n)
    means.sort()
    return (means[int(0.025 * n_boot)], means[int(0.975 * n_boot) - 1])


def mde_paired(diffs):
    """Detectable mean shift at alpha .05 two-sided, 80% power."""
    n = len(diffs)
    m = sum(diffs) / n
    var = sum((d - m) ** 2 for d in diffs) / (n - 1)
    return (Z975 + Z80) * math.sqrt(var / n)


def compare(tab, arm, ref):
    """tab: {arm: {task: [0/1 x k]}}. Returns the full paired block."""
    tasks = sorted(tab[ref])
    n = len(tasks)
    fed_a = {t: int(any(tab[arm][t])) for t in tasks}
    fed_r = {t: int(any(tab[ref][t])) for t in tasks}
    b = sum(1 for t in tasks if fed_r[t] and not fed_a[t])  # ref-only
    c = sum(1 for t in tasks if fed_a[t] and not fed_r[t])  # arm-only
    nc_lo, nc_hi = newcombe_paired_delta(
        sum(fed_a.values()), sum(fed_r.values()), n)
    rate = lambda xs: sum(xs) / len(xs)  # noqa: E731
    diffs = [rate(tab[arm][t]) - rate(tab[ref][t]) for t in tasks]
    bs_lo, bs_hi = paired_bootstrap(diffs)
    mean_d = sum(diffs) / n
    flag = lambda lo, hi: "UP" if lo > 0 else ("DOWN" if hi < 0 else "FLAT")  # noqa: E731
    return {
        "pair": f"{arm} - {ref}", "n_tasks": n,
        "feed": {"arm": sum(fed_a.values()), "ref": sum(fed_r.values()),
                 "discordant_ref_only_b": b, "discordant_arm_only_c": c,
                 "mcnemar_p": round(mcnemar_exact(b, c), 4),
                 "newcombe_ci95": [round(nc_lo, 4), round(nc_hi, 4)],
                 "flag": flag(nc_lo, nc_hi)},
        "sample": {"mean_diff": round(mean_d, 4),
                   "bootstrap_ci95": [round(bs_lo, 4), round(bs_hi, 4)],
                   "mde": round(mde_paired(diffs), 4),
                   "flag": flag(bs_lo, bs_hi)},
    }


def fire_cell(blocks):
    """Decision-tree cell from the registered rules. blocks keyed by pair."""
    ab, ac = blocks["a - base"], blocks["a - control"]
    sig = (ab["feed"]["flag"] == "DOWN" and ab["sample"]["flag"] == "UP")
    if ac["sample"]["flag"] == "DOWN" and ac["feed"]["flag"] == "DOWN":
        return "R2-INVERT", "A below control on both metrics"
    if sig:
        return "R2-PRESERVE", "sharpening-narrowing signature confirmed"
    a_up = ab["sample"]["flag"] == "UP"
    a_beats_c = ac["sample"]["flag"] == "UP"
    if a_up and a_beats_c:
        return "R2-SCALE", "A>base and A>control on the gains metric"
    if a_up and not a_beats_c:
        return "R2-RETHINK", "A>base but not >control: format effect"
    if a_beats_c:
        return "R2-PRESERVE", "content signal (A>control) but no lift vs base"
    return "R2-RETHINK", "content null at this scale (A~base, A~control)"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--glob-dir", default=RECEIPTS)
    args = ap.parse_args()

    tab, files = {}, {}
    for arm in ARMS:
        hits = sorted(globlib.glob(
            f"{args.glob_dir}/w1-floor-g1-{arm}-*-samples.jsonl"))
        if not hits:
            raise SystemExit(f"g1_paired: no samples file for arm {arm}")
        files[arm] = os.path.basename(hits[-1])
        tab[arm] = load_samples(hits[-1])
    base_tasks = set(tab["base"])
    for arm in ARMS:  # fail-closed pairing asserts
        assert set(tab[arm]) == base_tasks, f"task-set mismatch: {arm}"
        for t, xs in tab[arm].items():
            assert len(xs) == 8, f"{arm}/{t}: {len(xs)} samples != k=8"

    blocks = {f"{a} - {r}": compare(tab, a, r) for a, r in PAIRS}
    cell, why = fire_cell(blocks)
    mtp_a = blocks["mtp - a"]["sample"]["flag"]
    d3 = {"UP": "MTP joins round-2 default recipe",
          "FLAT": "drop MTP at SFT scale; re-evaluate at NC2-own pretrain",
          "DOWN": "MTP harmful at SFT scale: receipt the negative; "
                  "pretrain-rung re-evaluation only"}[mtp_a]
    grpo_b = blocks["grpo - base"]["sample"]["flag"]
    grpo_read = {
        "UP": "GRPO advances on the gains metric: t5-grpo harm gate "
              "fires before any round-2 role",
        "FLAT": "GRPO flat vs base at k=8 (MDE in block); joins r2 "
                "arm-4 via the trainability precondition only (#24)",
        "DOWN": "GRPO regresses vs base: receipt the negative; r2 "
                "arm-4 requires redesign before dispatch"}[grpo_b]

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt = {
        "ticket": "G1-PAIRED-R1W", "ts": ts, "files": files,
        "pre_registration": "research/r1w-g1-decision-tree.md (#32, PR #40)",
        "comparisons": blocks,
        "tree": {"cell": cell, "why": why,
                 "d3_mtp_overlay": {"flag": mtp_a, "reading": d3},
                 "grpo_overlay": {
                     "flag": grpo_b,
                     "vs_control": blocks["grpo - control"]["sample"]["flag"],
                     "vs_mtp": blocks["grpo - mtp"]["sample"]["flag"],
                     "reading": grpo_read},
                 "t5_gate": "any advancing arm must show t5 non-regression"},
    }
    os.makedirs(RECEIPTS, exist_ok=True)
    out = f"{RECEIPTS}/g1-paired-r1w-{ts}.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(receipt, f, indent=2)
    print(json.dumps(receipt, indent=2))
    print(f"G1_PAIRED_DONE {out}")


def _selftest():
    # mcnemar: no discordance -> 1.0; strong asymmetry -> small
    assert mcnemar_exact(0, 0) == 1.0
    assert mcnemar_exact(8, 0) < 0.01
    assert abs(mcnemar_exact(1, 1) - 1.0) < 1e-9
    # identical arms -> FLAT everywhere, p=1
    k8 = lambda s: [1] * s + [0] * (8 - s)  # noqa: E731
    tab = {"x": {f"t{i}": k8(i % 5) for i in range(40)},
           "y": {f"t{i}": k8(i % 5) for i in range(40)}}
    blk = compare(tab, "x", "y")
    assert blk["feed"]["flag"] == "FLAT" and blk["sample"]["flag"] == "FLAT"
    assert blk["feed"]["mcnemar_p"] == 1.0
    lo, hi = blk["sample"]["bootstrap_ci95"]
    assert lo <= 0 <= hi
    # constructed +2/8 shift on every task -> sample-level UP
    tab2 = {"hi": {f"t{i}": k8(min(8, i % 5 + 2)) for i in range(40)},
            "lo": {f"t{i}": k8(i % 5) for i in range(40)}}
    blk2 = compare(tab2, "hi", "lo")
    assert blk2["sample"]["flag"] == "UP", blk2["sample"]
    # feed: i%5==0 tasks go 0->2 verified = newly fed; c=8, b=0
    assert blk2["feed"]["discordant_arm_only_c"] == 8
    assert blk2["feed"]["discordant_ref_only_b"] == 0
    assert blk2["feed"]["mcnemar_p"] < 0.01
    # bootstrap deterministic under fixed seed
    d = [0.1, -0.2, 0.3, 0.0, 0.25, -0.05]
    assert paired_bootstrap(d) == paired_bootstrap(d)
    # fire_cell: SCALE cell when A up on gains metric vs both
    up = {"feed": {"flag": "FLAT"}, "sample": {"flag": "UP"}}
    fl = {"feed": {"flag": "FLAT"}, "sample": {"flag": "FLAT"}}
    cell, _ = fire_cell({"a - base": up, "a - control": up})
    assert cell == "R2-SCALE"
    cell, _ = fire_cell({"a - base": fl, "a - control": fl})
    assert cell == "R2-RETHINK"
    sigblk = {"feed": {"flag": "DOWN"}, "sample": {"flag": "UP"}}
    cell, why = fire_cell({"a - base": sigblk, "a - control": fl})
    assert cell == "R2-PRESERVE" and "signature" in why
    print("G1_PAIRED_SELFTEST_PASS")


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        _selftest()
    else:
        main()
