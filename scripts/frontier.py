"""frontier — solve-rate posterior + bits-weighted episode caps (eng #5).

Formalization §3b made bits the objective; the focused top-up receipt
(`w1-floor-q3-focus-20260610T210228Z.json`) made the strata measurable:
half the pool is easy mass carrying ~0 bits, the high-bits band is thin.
This module is the ingest/dataset half of that math:

  - outcome_stats: per-task (successes, attempts) pooled across sample files
    (k=8 probe + k=24 top-up combine into one posterior).
  - stratum: raw-rate bands matching the gate language — dead (s==0),
    frontier (0,.25], mid (.25,.75], easy (.75,1].
  - annotate_records: stamps phat (Laplace, = vbits preference-2 estimator),
    bits, stratum, prior_s/prior_n onto ledger records at INGEST, so the
    ledger carries its own bits accounting and nothing re-mines sample files.
  - caps_from_records: per-task dataset-build caps by stratum. The ledger
    keeps every verified episode (memory is not where the discount lives);
    the DATASET build is where easy mass is discounted — t2_round's
    build_dataset takes the dict.

Default caps (receipts-grounded, 2026-06-10): easy 2, mid 4, frontier 8,
dead 8 (a dead-stratum task with verified episodes can only mean the
posterior came from a different pool than the records — cap high, never
drop). No silent caps: report_block() returns per-stratum ingested/dropped
counts + bits banked for the receipt.

Pure stdlib (+ vbits, same dir). `python frontier.py --selftest`.
"""
from vbits import bits, laplace_phat

DEFAULT_CAPS = {"easy": 2, "mid": 4, "frontier": 8, "dead": 8}


def outcome_stats(rows):
    """Sample rows -> {task: (s, n)}. Every row is an attempt (extraction
    failures count against the task — they are failed samples)."""
    stats = {}
    for r in rows:
        s, n = stats.get(r["task"], (0, 0))
        stats[r["task"]] = (s + int(bool(r.get("verified"))), n + 1)
    return stats


def stratum(s, n):
    if n == 0:
        return "dead"
    rate = s / n
    if rate == 0:
        return "dead"
    if rate <= 0.25:
        return "frontier"
    if rate <= 0.75:
        return "mid"
    return "easy"


def annotate_records(records, stats):
    """Stamp phat/bits/stratum/prior_s/prior_n on ledger records (mutates +
    returns). Tasks absent from stats get the no-data posterior (0,0)."""
    for rec in records:
        s, n = stats.get(rec["task"], (0, 0))
        p = laplace_phat(s, n)
        rec["phat"] = round(p, 6)
        rec["bits"] = round(bits(p), 4)
        rec["stratum"] = stratum(s, n)
        rec["prior_s"], rec["prior_n"] = s, n
    return records


def caps_from_records(records, caps=None):
    """Annotated ledger records -> {task: cap} for t2_round.build_dataset."""
    caps = caps or DEFAULT_CAPS
    return {rec["task"]: caps[rec["stratum"]] for rec in records
            if "stratum" in rec}


def report_block(records, caps=None):
    """Receipt block: per-stratum task/episode counts, post-cap episode
    counts (distinct-src, shortest-first — mirrors build_dataset), dropped
    easy mass, bits banked over post-cap episodes. No silent caps."""
    caps = caps or DEFAULT_CAPS
    by_task = {}
    for rec in records:
        by_task.setdefault(rec["task"], []).append(rec)
    out = {st: {"tasks": 0, "episodes": 0, "post_cap": 0, "dropped": 0,
                "bits_banked": 0.0} for st in caps}
    for task, recs in by_task.items():
        st = recs[0]["stratum"]
        uniq = {}
        for r in sorted(recs, key=lambda r: len(r["src"])):
            uniq.setdefault(r["src"], r)
        kept = list(uniq.values())[:caps[st]]
        b = out[st]
        b["tasks"] += 1
        b["episodes"] += len(recs)
        b["post_cap"] += len(kept)
        b["dropped"] += len(recs) - len(kept)
        b["bits_banked"] += sum(r["bits"] for r in kept)
    for b in out.values():
        b["bits_banked"] = round(b["bits_banked"], 2)
    out["total_bits_banked"] = round(
        sum(v["bits_banked"] for k, v in out.items() if k in caps), 2)
    return out


def _selftest():
    rows = (
        [{"task": "mbpp:1", "verified": True}] * 7
        + [{"task": "mbpp:1", "verified": False}] * 1     # easy 7/8
        + [{"task": "mbpp:2", "verified": True}] * 1
        + [{"task": "mbpp:2", "verified": False}] * 31    # frontier 1/32
        + [{"task": "mbpp:3", "verified": False}] * 8     # dead 0/8
        + [{"task": "mbpp:4", "verified": True}] * 4
        + [{"task": "mbpp:4", "verified": False}] * 4     # mid 4/8
    )
    stats = outcome_stats(rows)
    assert stats["mbpp:1"] == (7, 8) and stats["mbpp:2"] == (1, 32)
    assert stratum(*stats["mbpp:1"]) == "easy"
    assert stratum(*stats["mbpp:2"]) == "frontier"
    assert stratum(*stats["mbpp:3"]) == "dead"
    assert stratum(*stats["mbpp:4"]) == "mid"
    recs = [{"task": "mbpp:2", "src": "def f(): pass"},
            {"task": "mbpp:2", "src": "def f():  pass"},
            {"task": "mbpp:1", "src": "def g(): pass"}]
    annotate_records(recs, stats)
    assert recs[0]["stratum"] == "frontier" and recs[0]["prior_n"] == 32
    # frontier bits > easy bits, both finite
    assert recs[0]["bits"] > recs[2]["bits"] > 0
    caps = caps_from_records(recs)
    assert caps == {"mbpp:2": 8, "mbpp:1": 2}
    # cap drops easy excess, keeps frontier; dedup by src
    many = [{"task": "mbpp:1", "src": f"def g{i}(): pass"} for i in range(5)]
    annotate_records(many, stats)
    rb = report_block(recs + many)
    assert rb["easy"]["tasks"] == 1 and rb["easy"]["post_cap"] == 2
    assert rb["easy"]["dropped"] == 4          # 6 easy episodes, cap 2
    assert rb["frontier"]["post_cap"] == 2 and rb["frontier"]["dropped"] == 0
    assert rb["total_bits_banked"] > 0
    # no-data task -> phat 0.5, bits 1, dead
    nd = annotate_records([{"task": "mbpp:99", "src": "x"}], stats)
    assert nd[0]["phat"] == 0.5 and nd[0]["stratum"] == "dead"
    print("FRONTIER_SELFTEST_PASS")


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        _selftest()
    else:
        print(__doc__)
