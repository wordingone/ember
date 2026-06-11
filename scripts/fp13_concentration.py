"""fp13_concentration.py — majority-class concentration of the seed mass (#85, fp-13).

fp-10 probed the ledger's 33% minority (Qwen-emitted W-code) and demoted
its style signature. The 67% MAJORITY — 1,909 arc-dsl-MIT episodes,
essentially single-author (Hodel) DSL code, 399 originals + 1,510 re-arc
variants — was never probed for ITS concentration. A from-scratch core
inherits the DOMINANT distribution: if the seed mass is a near-
monoculture, the '1,909 episodes' headline overstates effective
diversity. Cross-WORLD separability is confounded by task domain (issue
#85 design note), so concentration is measured WITHIN-corpus.

Pre-registered measurements (issue #85, binding):
  1. Effective-N over the 1,909: exact-duplicate count + near-duplicate
     clusters (cosine >= 0.95 on the fp-10 hashed char-3gram bags,
     union-find); effective-unique cluster count + the realized
     variant-to-original expansion factor.
  2. Intra-class dispersion in the fp-10 feature space (7 stylometry +
     256 crc32 3-gram buckets, z-scored over the POOLED corpus) for
     arc-dsl vs qwen-mbpp vs human-mbpp: mean pairwise Euclidean
     distance per class (+ mean pairwise 3-gram cosine similarity as the
     scale-free complement). The two MBPP classes calibrate what
     'diverse' looks like in this space (their cross-class separation is
     receipted at AUC 0.7431, fp-10).
  3. Verdict bar (frozen in #85): effective-unique < 30% of 1,909 OR
     arc-dsl dispersion < half the qwen-mbpp dispersion -> CONCENTRATED
     — every NC2-own design doc quoting '1,909' must carry effective-N
     alongside, and §8.15d dilution preferences re-rank (the majority
     class becomes the diluTED, not the diluTER).

Needs the datasets lib for the human-mbpp reference texts (same leg as
fp-10) -> main runs via the daemon eval window (WSL). numpy required for
the pairwise legs. `python fp13_concentration.py --selftest` is
pure-logic and runs anywhere.
"""
import json
import sys
from datetime import datetime, timezone

NC = "/mnt/b/M/avir/leo/state/nc-ladder"
RECEIPTS = f"{NC}/receipts"
LEDGER = f"{NC}/ledger/episodes.jsonl"

NEAR_DUP_COS = 0.95
BAR_EFFECTIVE_FRAC = 0.30
BAR_DISPERSION_RATIO = 0.5


def is_arc_dsl(rec):
    return str(rec.get("origin", "")).startswith(
        ("seed-dsl", "seed-verifier-rearc"))


def union_find_clusters(n, edges):
    """Pure-logic union-find; edges = iterable of (i, j).
    Returns (n_clusters, sizes_desc, members_of_largest)."""
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i, j in edges:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[rj] = ri
    roots = [find(i) for i in range(n)]
    counts = {}
    for r in roots:
        counts[r] = counts.get(r, 0) + 1
    big = max(counts, key=lambda k: counts[k]) if counts else None
    members = [i for i, r in enumerate(roots) if r == big]
    return len(counts), sorted(counts.values(), reverse=True), members


def chaining_diagnostic(mat_norm, members, seed=16, n_pairs=2000):
    """Union-find merges transitively: A~B~C can land cos(A,C)<threshold
    in one cluster. Sample direct cosines inside the largest cluster to
    show whether it is a genuine near-dup neighborhood or a chain
    artifact. Deterministic (seeded)."""
    import random
    rng = random.Random(seed)
    cs = []
    for _ in range(n_pairs):
        i, j = rng.choice(members), rng.choice(members)
        if i != j:
            cs.append(float(mat_norm[i] @ mat_norm[j]))
    cs.sort()
    return {
        "sampled_pairs": len(cs),
        "min": round(cs[0], 4), "p5": round(cs[len(cs) // 20], 4),
        "median": round(cs[len(cs) // 2], 4),
        "mean": round(sum(cs) / len(cs), 4),
        "frac_direct_ge_threshold": round(
            sum(1 for c in cs if c >= NEAR_DUP_COS) / len(cs), 4),
    }


def design_effect_ess(n, mean_cos):
    """Chaining-free effective sample size under equicorrelation:
    ESS = n / (1 + (n-1)*rho), rho = mean pairwise similarity."""
    return n / (1 + (n - 1) * max(mean_cos, 0.0))


def near_dup_edges(mat, threshold=NEAR_DUP_COS, block=512):
    """Yield (i, j) index pairs with cosine >= threshold. mat: numpy
    (n, d) row-normalized. Blocked matmul keeps memory bounded."""
    import numpy as np
    n = mat.shape[0]
    for a in range(0, n, block):
        sims = mat[a:a + block] @ mat.T
        ii, jj = np.where(sims >= threshold)
        for i, j in zip(ii, jj):
            gi = a + int(i)
            if gi < int(j):
                yield gi, int(j)


def row_normalize(vectors):
    import numpy as np
    m = np.asarray(vectors, dtype=np.float64)
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return m / norms


def mean_pairwise_euclid(mat):
    """Exact mean pairwise distance via the identity
    sum_ij ||x_i - x_j||^2 = 2n*sum||x_i||^2 - 2||sum x_i||^2 gives the
    SQUARED mean cheaply; for the plain mean we sample is unnecessary —
    n<=2000 here, do it blocked exact."""
    import numpy as np
    n = mat.shape[0]
    total = 0.0
    cnt = 0
    for a in range(0, n, 256):
        blockm = mat[a:a + 256]
        d2 = ((blockm[:, None, :] - mat[None, a:, :]) ** 2).sum(-1)
        iu = np.triu_indices(blockm.shape[0], k=1, m=d2.shape[1])
        # only pairs (i, j) with global i < j: block rows vs mat[a:]
        total += np.sqrt(d2[iu]).sum()
        cnt += len(iu[0])
    return total / cnt, cnt


def mean_pairwise_cosine(mat_norm):
    import numpy as np
    n = mat_norm.shape[0]
    s = mat_norm.sum(axis=0)
    # sum of all pairwise dots = ||sum||^2 - n (self-dots are 1)
    total = float(s @ s) - n
    return total / (n * (n - 1))


def zscore_pooled(rows):
    import numpy as np
    m = np.asarray(rows, dtype=np.float64)
    mu = m.mean(axis=0)
    sd = m.std(axis=0)
    sd[sd < 1e-12] = 1.0
    return (m - mu) / sd, mu, sd


def main():
    sys.path.insert(0, f"{NC}/scripts")
    from fp10_idiom import featurize, trigram_bag
    from datasets import load_dataset
    import numpy as np

    arc, qwen_tasks, qwen = [], set(), []
    with open(LEDGER, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            src = r.get("src")
            if not src:
                continue
            if is_arc_dsl(r):
                arc.append((str(r.get("origin", "")), src))
            elif str(r.get("task", "")).startswith("mbpp:") \
                    and r.get("verified"):
                qwen.append(src)
                qwen_tasks.add(r["task"])
    ds = load_dataset("google-research-datasets/mbpp", "sanitized",
                      split="train")
    human = [r["code"] for r in ds
             if f"mbpp:{int(r['task_id'])}" in qwen_tasks]
    arc_srcs = [s for _, s in arc]
    n_arc = len(arc_srcs)

    # 1. effective-N on arc-dsl
    exact_unique = len(set(arc_srcs))
    bags = row_normalize([trigram_bag(s) for s in arc_srcs])
    n_clusters, cluster_sizes, big_members = union_find_clusters(
        n_arc, near_dup_edges(bags))
    eff_frac = n_clusters / n_arc
    chain = chaining_diagnostic(bags, big_members)
    n_orig = sum(1 for o, _ in arc if o.startswith("seed-dsl"))
    n_variant = n_arc - n_orig

    # 2. pooled-space dispersion per class
    feats = [featurize(s) for s in arc_srcs + qwen + human]
    z, _, _ = zscore_pooled(feats)
    z_arc, z_qwen, z_human = (z[:n_arc], z[n_arc:n_arc + len(qwen)],
                              z[n_arc + len(qwen):])
    disp = {}
    for name, m in (("arc_dsl", z_arc), ("qwen_mbpp", z_qwen),
                    ("human_mbpp", z_human)):
        mean_d, n_pairs = mean_pairwise_euclid(np.asarray(m))
        disp[name] = {"mean_pairwise_euclid": round(float(mean_d), 4),
                      "n": int(m.shape[0]), "n_pairs": int(n_pairs)}
    cos = {}
    for name, srcs in (("arc_dsl", arc_srcs), ("qwen_mbpp", qwen),
                       ("human_mbpp", human)):
        cos[name] = round(float(mean_pairwise_cosine(
            row_normalize([trigram_bag(s) for s in srcs]))), 4)

    ratio = disp["arc_dsl"]["mean_pairwise_euclid"] / \
        disp["qwen_mbpp"]["mean_pairwise_euclid"]
    concentrated = (eff_frac < BAR_EFFECTIVE_FRAC
                    or ratio < BAR_DISPERSION_RATIO)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt = {
        "ticket": "FP13-CONCENTRATION", "ts": ts,
        "prereg": "issue #85 (frozen): CONCENTRATED iff effective-unique "
                  f"< {BAR_EFFECTIVE_FRAC:.0%} of corpus OR arc dispersion "
                  f"< {BAR_DISPERSION_RATIO} x qwen dispersion",
        "corpus": {"arc_dsl": n_arc, "originals": n_orig,
                   "variants": n_variant,
                   "realized_expansion_factor": round(n_arc / max(n_orig, 1), 2),
                   "qwen_mbpp": len(qwen), "human_mbpp": len(human)},
        "effective_n": {
            "exact_unique_srcs": exact_unique,
            "near_dup_clusters_cos95": n_clusters,
            "effective_unique_fraction": round(eff_frac, 4),
            "method": "union-find over 3-gram-bag cosine >= 0.95",
            "cluster_sizes_desc": cluster_sizes[:20],
            "largest_cluster_chaining_diag": chain,
            "chaining_note": "union-find merges transitively; the cluster "
                             "count is a LOWER bound on distinct "
                             "neighborhoods — the diagnostic shows whether "
                             "the giant component is genuinely near-dup "
                             "(high direct median) or a chain artifact",
            "design_effect_ess": round(design_effect_ess(
                n_arc, cos_arc_mean := float(mean_pairwise_cosine(bags))), 1),
            "design_effect_rho": round(cos_arc_mean, 4),
            "ess_note": "chaining-FREE complement: ESS = n/(1+(n-1)*rho) "
                        "under equicorrelation, rho = mean pairwise "
                        "3-gram cosine",
        },
        "dispersion_pooled_zspace": disp,
        "dispersion_ratio_arc_over_qwen": round(ratio, 4),
        "mean_pairwise_trigram_cosine": cos,
        "verdict": "CONCENTRATED" if concentrated else "NOT-CONCENTRATED",
        "consequence_if_concentrated": "every '1,909' quote carries "
                                       "effective-N; §8.15d dilution "
                                       "preferences re-rank (majority "
                                       "class = the diluted, not diluter)",
        "flags": [
            "cross-class dispersion LEVELS are domain-confounded (DSL vs "
            "general Python); the bar uses the qwen class only as a "
            "same-space calibration point, per the issue design note",
            "near-dup threshold 0.95 on hashed bags is a proxy for text "
            "near-duplication (hash collisions can merge, never split)",
        ],
    }
    out = f"{RECEIPTS}/fp13-concentration-{ts}.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(receipt, f, indent=2)
    print(json.dumps(receipt, indent=2))
    print(f"FP13_CONCENTRATION_DONE {out}")


def _selftest():
    # union-find: 5 nodes, edges chain 0-1-2 and pair 3-4 -> 2 clusters,
    # sizes [3,2], largest members = {0,1,2}
    nc, sizes, big = union_find_clusters(5, [(0, 1), (1, 2), (3, 4)])
    assert (nc, sizes, sorted(big)) == (2, [3, 2], [0, 1, 2])
    assert union_find_clusters(3, [])[0] == 3
    assert union_find_clusters(4, [(0, 1), (2, 3), (1, 2)])[0] == 1
    # design-effect ESS: rho=0 -> n; rho=1 -> 1
    assert design_effect_ess(100, 0.0) == 100
    assert abs(design_effect_ess(100, 1.0) - 1.0) < 1e-9
    # origin classifier mirrors fp6 families
    assert is_arc_dsl({"origin": "seed-dsl-orig"})
    assert is_arc_dsl({"origin": "seed-verifier-rearc-v2"})
    assert not is_arc_dsl({"origin": "w2-ingest"})
    try:
        import numpy as np
    except ImportError:
        print("FP13_CONCENTRATION_SELFTEST_PASS (numpy legs skipped)")
        return
    # row-normalize + near-dup edges: identical rows are found, distinct not
    m = row_normalize([[1, 0], [1, 0], [0, 1]])
    edges = list(near_dup_edges(m))
    assert (0, 1) in edges and len(edges) == 1, edges
    # cluster count from those edges
    assert union_find_clusters(3, edges)[0] == 2
    # mean pairwise cosine: identical rows -> 1.0; orthogonal -> 0
    assert abs(mean_pairwise_cosine(row_normalize([[1, 0]] * 3)) - 1.0) < 1e-9
    assert abs(mean_pairwise_cosine(row_normalize([[1, 0], [0, 1]]))) < 1e-9
    # dispersion: tight cluster < spread cluster, exact pair count n(n-1)/2
    tight = np.asarray([[0.0, 0.0], [0.1, 0.0], [0.0, 0.1]])
    spread = np.asarray([[0.0, 0.0], [3.0, 0.0], [0.0, 3.0]])
    dt, ct = mean_pairwise_euclid(tight)
    dsp, cs = mean_pairwise_euclid(spread)
    assert ct == cs == 3 and dt < dsp, (dt, dsp, ct, cs)
    # blocked == naive on a random-ish fixed matrix
    fixed = np.asarray([[float(i % 7), float((i * 3) % 5)] for i in range(20)])
    d_blocked, c_blocked = mean_pairwise_euclid(fixed)
    naive = [float(np.linalg.norm(fixed[i] - fixed[j]))
             for i in range(20) for j in range(i + 1, 20)]
    assert c_blocked == len(naive) and abs(d_blocked - sum(naive) / len(naive)) < 1e-9
    # z-score pooling: zero-mean, unit-ish variance, constant cols safe
    z, mu, sd = zscore_pooled([[1.0, 5.0], [3.0, 5.0]])
    assert abs(z[:, 0].mean()) < 1e-9 and z[0][1] == 0.0
    print("FP13_CONCENTRATION_SELFTEST_PASS")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        main()
