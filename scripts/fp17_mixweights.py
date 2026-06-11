"""fp17_mixweights.py — implicit training-mix weights under duplication (#96, fp-17).

fp-16: rows and evidence disagree (arc-dsl 67% of rows, ~45% of effective
programs). Eval surfaces are task-bootstrap and unaffected; TRAINING is
row-driven. One mitigation already exists in-code: build_dataset dedups
exact srcs WITHIN a task (uniq.setdefault(r["src"])). The remaining
channel is CROSS-TASK duplication — re-arc variants are separate task
keys (tid, tid#a1, ...) sharing the same completion text — so the same
program is the SFT target under many prompts. This receipt measures what
the REALIZED builds actually train on, counted as completion evidence.

Replayed builds (the live shapes, real files, real filters; replay views
written to /tmp — production ledger/views NEVER touched):
  A. arc_round  — t2_round.build_dataset(LEDGER, default caps, no
     license filter): the r1/r2 ARC-side shape.
  B. wcode_arm  — t2_wcode arm shape: mbpp:* view -> ext-flag filter ->
     caps_from_records (bits-weighted per-task caps) -> build_dataset.
  C. wcode_license_clean — B + allow {arc-dsl-mit, apache-2.0}: expected
     0 examples (the #79 demo), quoted as a count.

Per build, over the ASSISTANT completion texts:
  - exact-dup groups (same completion under k examples = k-fold implicit
    upweighting);
  - near-dup clusters (fp-13/fp-16 machinery imported, single source:
    3-gram-bag cosine >= 0.95 union-find + chaining diagnostic);
  - the implicit-weight table: examples-per-cluster distribution (max /
    median / giant-component share), fraction of steps on non-unique
    completion text.

Round-3 pre-registration (frozen on this receipt, my call per the
design-calls rule): named choice = CLUSTER-CAP — extend the existing
bits-weighted cap discipline one level: cap examples per dedup cluster
with the same {easy 2, mid 4, frontier 8} table applied at cluster level
(cluster stratum = best member-task stratum), consuming the eng-25
stamp. Revision criterion: if the cluster-capped arm's G1 held-out delta
underperforms the row-build control beyond CI in round-3, revert to
row-build and move the dedup lever to loss-weighting.

CPU-from-ledger via the daemon window (t2 imports are WSL-pathed).
`python fp17_mixweights.py --selftest` is pure-logic and runs anywhere.
"""
import json
import os
import sys
from datetime import datetime, timezone

NC = "/mnt/b/M/avir/leo/state/nc-ladder"
RECEIPTS = f"{NC}/receipts"
TMP = "/tmp/fp17-views"


def completion_texts(examples):
    return [ex["messages"][1]["content"] for ex in examples]


def weight_table(texts):
    """Implicit-weight metrics over a build's completion texts."""
    n = len(texts)
    if n == 0:
        return {"examples": 0}
    groups = {}
    for t in texts:
        groups[t] = groups.get(t, 0) + 1
    sizes = sorted(groups.values(), reverse=True)
    dup_steps = sum(s for s in sizes if s > 1)
    out = {
        "examples": n,
        "exact_unique_completions": len(groups),
        "steps_on_duplicated_text": dup_steps,
        "dup_step_fraction": round(dup_steps / n, 4),
        "exact_group_sizes_top5": sizes[:5],
        "implicit_weight_max": sizes[0],
        "implicit_weight_median": sizes[len(sizes) // 2],
    }
    try:
        from fp10_idiom import trigram_bag
        from fp13_concentration import (row_normalize, near_dup_edges,
                                        union_find_clusters,
                                        chaining_diagnostic)
        uniq = list(groups)
        bags = row_normalize([trigram_bag(t) for t in uniq])
        n_cl, cl_sizes, big = union_find_clusters(len(uniq),
                                                  near_dup_edges(bags))
        # cluster weight = total EXAMPLES landing in the cluster
        idx_of = {t: i for i, t in enumerate(uniq)}
        parent_examples = {}
        # recompute roots by re-running union-find on the same edges
        # (union_find_clusters returns largest-members; map via a second
        # pass): assign each unique text to a cluster id by find()
        # — reimplemented tiny UF here for example-weight aggregation.
        par = list(range(len(uniq)))

        def find(x):
            while par[x] != x:
                par[x] = par[par[x]]
                x = par[x]
            return x

        for i, j in near_dup_edges(bags):
            ri, rj = find(i), find(j)
            if ri != rj:
                par[rj] = ri
        for t, cnt in groups.items():
            r = find(idx_of[t])
            parent_examples[r] = parent_examples.get(r, 0) + cnt
        cl_example_sizes = sorted(parent_examples.values(), reverse=True)
        out.update({
            "near_dup_clusters_cos95": n_cl,
            "cluster_example_sizes_top5": cl_example_sizes[:5],
            "giant_cluster_step_share": round(cl_example_sizes[0] / n, 4),
            "largest_cluster_chaining_diag": (
                chaining_diagnostic(bags, big) if cl_sizes[0] > 10 else None),
        })
    except ImportError:
        out["near_dup_clusters_cos95"] = None
    return out


def replay_builds():
    sys.path.insert(0, f"{NC}/scripts")
    from t2_round import LEDGER, build_dataset
    from t2_wcode import write_view
    from frontier import caps_from_records, ext_clean, load_ext_flags
    from ledger_license import filter_records, parse_allow

    os.makedirs(TMP, exist_ok=True)
    builds = {}

    # A: ARC-side full-ledger build, default caps, no license filter
    ex_a, counts_a = build_dataset(LEDGER)
    builds["arc_round"] = {"tasks": len(counts_a),
                           **weight_table(completion_texts(ex_a))}

    # B: wcode arm — replay t2_wcode's view->ext_clean->caps chain to /tmp
    arm = write_view(LEDGER, f"{TMP}/wcode-r1.jsonl")
    flags = load_ext_flags([f"{RECEIPTS}/v-ext-flags-*.jsonl"])
    n_pre = len(arm)
    arm = ext_clean(arm, flags)
    with open(f"{TMP}/wcode-r1.jsonl", "w", encoding="utf-8", newline="\n") as f:
        for r in arm:
            f.write(json.dumps(r) + "\n")
    caps = caps_from_records(arm)
    ex_b, counts_b = build_dataset(f"{TMP}/wcode-r1.jsonl", cap=caps)
    builds["wcode_arm"] = {"tasks": len(counts_b),
                           "ext_excluded": n_pre - len(arm),
                           **weight_table(completion_texts(ex_b))}

    # C: wcode under the license-clean allow set — expected empty
    allow = parse_allow("arc-dsl-mit,apache-2.0")
    clean = filter_records(arm, allow)
    builds["wcode_license_clean"] = {"records_after_filter": len(clean)}
    return builds


def main():
    builds = replay_builds()
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt = {
        "ticket": "FP17-MIXWEIGHTS", "ts": ts,
        "note": "build_dataset already dedups exact srcs WITHIN a task; "
                "the measured channel is CROSS-TASK completion duplication "
                "(re-arc variants are separate task keys sharing text)",
        "builds": builds,
        "round3_prereg": {
            "choice": "cluster-cap: per-dedup-cluster example cap with the "
                      "existing bits-weighted table {easy 2, mid 4, "
                      "frontier 8} applied at cluster level (cluster "
                      "stratum = best member-task stratum); consumes the "
                      "eng-25 dedup-cluster stamp",
            "alternatives_rejected": [
                "dedup-collapse at build (loses prompt diversity the "
                "augmentation was built to provide)",
                "weight ∝ 1/cluster-size loss-weighting (no trainer "
                "support in the current SFT path without surgery)"],
            "revision_criterion": "if the cluster-capped arm's G1 held-out "
                                  "delta underperforms the row-build "
                                  "control beyond CI in round-3, revert to "
                                  "row-build and move the dedup lever to "
                                  "loss-weighting",
        },
        "flags": ["replay views under /tmp — production ledger/views "
                  "untouched by this script",
                  "near-dup machinery imported from fp13/fp16 (single "
                  "source); chaining caveat carries over"],
    }
    out = f"{RECEIPTS}/fp17-mixweights-{ts}.json"
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(receipt, f, indent=2)
    print(json.dumps(receipt, indent=2))
    print(f"FP17_MIXWEIGHTS_DONE {out}")


def _selftest():
    # weight_table exact-dup math on constructed completions
    t = ["A"] * 3 + ["B"] * 2 + ["C"]
    w = weight_table(t)
    assert w["examples"] == 6 and w["exact_unique_completions"] == 3
    assert w["steps_on_duplicated_text"] == 5
    assert abs(w["dup_step_fraction"] - 5 / 6) < 1e-3
    assert w["exact_group_sizes_top5"] == [3, 2, 1]
    assert w["implicit_weight_max"] == 3 and w["implicit_weight_median"] == 2
    # empty build
    assert weight_table([])["examples"] == 0
    # all-unique build: zero dup steps
    w2 = weight_table(["x", "y", "z"])
    assert w2["dup_step_fraction"] == 0.0 and w2["implicit_weight_max"] == 1
    # completion extraction shape
    ex = [{"messages": [{"role": "user", "content": "u"},
                        {"role": "assistant", "content": "CODE"}]}]
    assert completion_texts(ex) == ["CODE"]
    # near-dup aggregation (numpy leg): two near-identical long texts in
    # separate exact groups collapse into one cluster carrying both counts
    try:
        import numpy as np  # noqa: F401
    except ImportError:
        print("FP17_MIXWEIGHTS_SELFTEST_PASS (numpy legs skipped)")
        return
    base = "def f(x):\n    return hupscale(x, THREE)\n" * 4
    t3 = [base] * 2 + [base + "# tail\n"] * 3 + ["zz completely other " * 9]
    w3 = weight_table(t3)
    assert w3["exact_unique_completions"] == 3
    assert w3["near_dup_clusters_cos95"] == 2, w3
    assert w3["cluster_example_sizes_top5"][0] == 5, w3
    assert abs(w3["giant_cluster_step_share"] - 5 / 6) < 1e-3
    print("FP17_MIXWEIGHTS_SELFTEST_PASS")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        main()
