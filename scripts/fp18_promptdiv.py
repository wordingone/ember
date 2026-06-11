"""fp18_promptdiv.py — prompt-side diversity within exact-dup completion
groups (#100, fp-18).

fp-17 froze the round-3 prereg choice (cluster-cap) and REJECTED
dedup-collapse on the claim that the prompts over a duplicated
completion are diverse ("the prompt diversity the augmentation exists
to provide"). That claim is UNMEASURED. This receipt measures it: for
the arc_round build's exact-dup completion groups (fp-17: 390
multi-groups, 1,519 examples, 65.5% of steps), how diverse are the
PROMPTS within each group?

Pre-registered verdict rule (frozen HERE, before the measuring run):

  FALSE-ACCEPT (prereg rationale fails, dedup-collapse re-enters) iff
  BOTH prongs trip:
    P1. within-group prompt near-dup fraction >= 0.50
        (majority of within-group prompt pairs are near-dup at the
        standing NEAR_DUP_COS = 0.95 bar — "predominantly near-dup"),
    P2. within-group near-dup fraction >= 2x the between-group sampled
        baseline (anchoring: ARC grid prompts share format texture —
        digits/brackets — so high cosine alone may be a property of the
        PROMPT FORMAT, not of duplication; the rationale only fails if
        dup groups are redundant RELATIVE to the build's prompt space).

  Both prongs must trip — conservative by construction. Anything else =
  rationale STANDS (cluster-cap stays the round-3 choice). If
  false-accept fires, the fp-17 prereg is amended ON THIS RECEIPT and
  the amendment recorded as a deviation (audit-§6 registry rule), not
  silently.

Method: replay build A exactly as fp-17 (t2_round.build_dataset(LEDGER),
default caps — same build, same machinery); group examples by ASSISTANT
completion text; within each multi-group compute pairwise cosine over
trigram_bag(prompt) (fp-10/fp-13 single-source machinery); baseline =
seeded sample of between-group prompt pairs.

CPU-from-ledger via the daemon window (t2 imports are WSL-pathed).
`python fp18_promptdiv.py --selftest` is pure-logic and runs anywhere.
"""
import json
import random
import sys
from datetime import datetime, timezone

NC = "/mnt/b/M/avir/leo/state/nc-ladder"
RECEIPTS = f"{NC}/receipts"

NEAR_DUP_BAR = 0.95     # standing NEAR_DUP_COS bar (fp13), quoted inline
P1_FRAC = 0.50          # prong 1: within-group near-dup pair fraction
P2_RATIO = 2.0          # prong 2: within vs between-group ratio
BETWEEN_SAMPLE = 5000   # between-group baseline pair sample
SEED = 18


def _cos(u, v):
    num = sum(a * b for a, b in zip(u, v))
    return num  # rows are L2-normalized upstream


def group_examples(examples):
    """completion-text -> list of prompt texts (ledger order)."""
    groups = {}
    for ex in examples:
        comp = ex["messages"][1]["content"]
        groups.setdefault(comp, []).append(ex["messages"][0]["content"])
    return groups


def prompt_pairs_stats(groups):
    """Within-group pairwise prompt cosines (multi-groups only) +
    seeded between-group baseline. Pure python on normalized bags."""
    from fp10_idiom import trigram_bag
    from fp13_concentration import row_normalize

    multi = {c: ps for c, ps in groups.items() if len(ps) > 1}
    # one bag per (group, member) prompt
    flat, owner = [], []
    for gi, (_c, ps) in enumerate(sorted(multi.items())):
        for p in ps:
            flat.append(p)
            owner.append(gi)
    if not flat:
        return {"n_multi_groups": 0, "n_within_pairs": 0}
    bags = row_normalize([trigram_bag(p) for p in flat])

    within = []
    idx_by_group = {}
    for i, g in enumerate(owner):
        idx_by_group.setdefault(g, []).append(i)
    for g, idxs in idx_by_group.items():
        for a in range(len(idxs)):
            for b in range(a + 1, len(idxs)):
                within.append(_cos(bags[idxs[a]], bags[idxs[b]]))

    rng = random.Random(SEED)
    between = []
    n = len(flat)
    tries = 0
    while len(between) < BETWEEN_SAMPLE and tries < BETWEEN_SAMPLE * 20:
        tries += 1
        i, j = rng.randrange(n), rng.randrange(n)
        if i == j or owner[i] == owner[j]:
            continue
        between.append(_cos(bags[i], bags[j]))

    def stats(xs):
        if not xs:
            return None
        s = sorted(xs)
        return {
            "n_pairs": len(s),
            "median": round(s[len(s) // 2], 4),
            "p5": round(s[int(0.05 * len(s))], 4),
            "p95": round(s[int(0.95 * len(s))], 4),
            "near_dup_frac": round(
                sum(1 for x in s if x >= NEAR_DUP_BAR) / len(s), 4),
        }

    return {
        "n_multi_groups": len(multi),
        "n_multi_examples": len(flat),
        "within": stats(within),
        "between_sampled": stats(between),
    }


def verdict(within, between):
    """Pre-registered two-prong rule. Fail-closed: missing legs = no
    false-accept claim, flagged instead."""
    if not within or not between:
        return {"false_accept": None,
                "flag": "missing leg — verdict not computable"}
    p1 = within["near_dup_frac"] >= P1_FRAC
    ratio = (within["near_dup_frac"] / between["near_dup_frac"]
             if between["near_dup_frac"] > 0 else float("inf"))
    p2 = ratio >= P2_RATIO
    return {
        "p1_within_near_dup_frac": within["near_dup_frac"],
        "p1_bar": P1_FRAC, "p1_trips": p1,
        "p2_within_over_between_ratio": (round(ratio, 3)
                                         if ratio != float("inf") else "inf"),
        "p2_bar": P2_RATIO, "p2_trips": p2,
        "false_accept": bool(p1 and p2),
    }


def main():
    sys.path.insert(0, f"{NC}/scripts")
    from t2_round import LEDGER, build_dataset

    ex_a, _counts = build_dataset(LEDGER)
    groups = group_examples(ex_a)
    st = prompt_pairs_stats(groups)
    v = verdict(st.get("within"), st.get("between_sampled"))

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt = {
        "ticket": "FP18-PROMPTDIV", "ts": ts,
        "build": "arc_round replay — t2_round.build_dataset(LEDGER), "
                 "default caps (same shape as fp-17 build A)",
        "examples": len(ex_a),
        "exact_unique_completions": len(groups),
        "prompt_stats": st,
        "prereg": {
            "rule": "false-accept iff P1 (within-group prompt near-dup "
                    f"pair fraction >= {P1_FRAC} at cos >= {NEAR_DUP_BAR}) "
                    f"AND P2 (within >= {P2_RATIO}x between-group sampled "
                    "baseline); frozen in-script before the measuring run",
            "consequence_if_false_accept": "fp-17 round-3 prereg amended "
                    "on this receipt (dedup-collapse re-enters as the "
                    "simpler lever); amendment recorded as a deviation",
            "consequence_otherwise": "fp-17 rationale STANDS; cluster-cap "
                    "remains the round-3 choice",
        },
        "verdict": v,
        "flags": [
            "prompt texture via 3-gram bags — format-level similarity is "
            "anchored out by the between-group baseline (P2), not ignored",
            f"between-group baseline is a seeded sample "
            f"(n<={BETWEEN_SAMPLE}, seed {SEED}), not exhaustive",
        ],
    }
    out = f"{RECEIPTS}/fp18-promptdiv-{ts}.json"
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(receipt, f, indent=2)
    print(json.dumps(receipt, indent=2))
    print(f"FP18_PROMPTDIV_DONE {out}")


def _selftest():
    sys.path.insert(0, f"{NC}/scripts")
    # group_examples shape
    mk = lambda p, c: {"messages": [{"role": "user", "content": p},
                                    {"role": "assistant", "content": c}]}
    exs = [mk("p1", "A"), mk("p2", "A"), mk("p3", "B")]
    g = group_examples(exs)
    assert sorted(g) == ["A", "B"] and g["A"] == ["p1", "p2"]

    # identical prompts in a group -> within near-dup frac 1.0
    base = "grid 1 2 3 | 4 5 6 -> transform " * 6
    other = "totally different prompt text zz " * 8
    groups = {"A": [base, base], "B": [other, other]}
    st = prompt_pairs_stats(groups)
    assert st["n_multi_groups"] == 2
    assert st["within"]["near_dup_frac"] == 1.0, st
    # between-group pairs (base vs other) are far apart
    assert st["between_sampled"]["near_dup_frac"] < 1.0, st

    # orthogonal prompts within a group -> within frac 0
    g2 = {"A": ["aaaa bbbb cccc " * 8, "zzzz yyyy xxxx " * 8],
          "B": ["1111 2222 3333 " * 8, "qqqq wwww eeee " * 8]}
    st2 = prompt_pairs_stats(g2)
    assert st2["within"]["near_dup_frac"] == 0.0, st2

    # verdict prong logic
    v1 = verdict({"near_dup_frac": 0.6}, {"near_dup_frac": 0.1})
    assert v1["false_accept"] is True and v1["p1_trips"] and v1["p2_trips"]
    v2 = verdict({"near_dup_frac": 0.6}, {"near_dup_frac": 0.5})
    assert v2["false_accept"] is False and not v2["p2_trips"]  # ratio 1.2
    v3 = verdict({"near_dup_frac": 0.3}, {"near_dup_frac": 0.01})
    assert v3["false_accept"] is False and not v3["p1_trips"]
    v4 = verdict({"near_dup_frac": 0.6}, {"near_dup_frac": 0.0})
    assert v4["false_accept"] is True and v4["p2_within_over_between_ratio"] == "inf"
    v5 = verdict(None, {"near_dup_frac": 0.1})
    assert v5["false_accept"] is None and "flag" in v5

    # degenerate: no multi-groups
    st3 = prompt_pairs_stats({"A": ["only one"]})
    assert st3["n_multi_groups"] == 0
    print("FP18_PROMPTDIV_SELFTEST_PASS")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        main()
