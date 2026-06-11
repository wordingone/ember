"""fp16_census.py — dedup-aware standing census of the ledger (#94, fp-16).

fp-13 found the majority class collapses 1,909 rows -> 780 exact-unique
-> ESS ~1.1 at the texture level. Row-count claims ('2,865 episodes',
'67/33 split', control sizes) are quoted as if rows were independent
evidence. This receipt is the STANDING census: per-class effective
composition over BOTH ledger files, plus the standing-claims delta
table — each headline quantity re-quoted under rows | exact-unique |
ESS, with a binding rule: any claim that flips sign or majority under
dedup accounting switches its canonical quote to the dedup-aware number.

Class mapping is fp6_provenance.classify (single source). Metrics per
(file, class): rows, exact-unique srcs, near-dup clusters (3-gram-bag
cosine >= 0.95, union-find, fp-13 chaining diagnostic on the largest
component), design-effect ESS. CPU-from-ledger, runs anywhere (no
datasets dependency). `python fp16_census.py --selftest`.
"""
import json
import sys
from datetime import datetime, timezone

NC_WIN = "B:/M/avir/leo/state/nc-ladder"
RECEIPTS = f"{NC_WIN}/receipts"
FILES = {"episodes": f"{NC_WIN}/ledger/episodes.jsonl",
         "control_pool": f"{NC_WIN}/ledger/control_pool.jsonl"}


def class_stats(srcs):
    """Per-class composition block. srcs: list of program texts."""
    from fp10_idiom import trigram_bag
    from fp13_concentration import (row_normalize, near_dup_edges,
                                    union_find_clusters, chaining_diagnostic,
                                    design_effect_ess, mean_pairwise_cosine)
    n = len(srcs)
    if n < 2:
        return {"rows": n, "exact_unique": n, "clusters": n, "ess": float(n)}
    bags = row_normalize([trigram_bag(s) for s in srcs])
    n_clusters, sizes, big = union_find_clusters(n, near_dup_edges(bags))
    rho = float(mean_pairwise_cosine(bags))
    out = {
        "rows": n,
        "exact_unique": len(set(srcs)),
        "clusters_cos95": n_clusters,
        "cluster_sizes_top5": sizes[:5],
        "rho_mean_pairwise_cos": round(rho, 4),
        "ess": round(design_effect_ess(n, rho), 1),
    }
    if sizes and sizes[0] > 10:
        out["largest_cluster_chaining_diag"] = chaining_diagnostic(bags, big)
    return out


def composition(path):
    from fp6_provenance import classify
    by_class = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            src = r.get("src")
            if not src:
                continue
            cls, _basis = classify(r)
            by_class.setdefault(cls, []).append(src)
    return {cls: class_stats(srcs) for cls, srcs in sorted(by_class.items())}


def majority(table, metric):
    """Which class carries the majority under a given accounting metric."""
    vals = {c: t.get(metric, t["rows"]) for c, t in table.items()}
    total = sum(vals.values())
    top = max(vals, key=lambda c: vals[c])
    return {"class": top, "share": round(vals[top] / total, 4) if total else None,
            "by_class": {c: round(v, 1) for c, v in vals.items()}}


def main():
    sys.path.insert(0, f"{NC_WIN}/scripts")
    census = {name: composition(path) for name, path in FILES.items()}

    eps = census["episodes"]
    deltas = {
        "ledger_total": {m: round(sum(t.get(m, t["rows"])
                                      for t in eps.values()), 1)
                         for m in ("rows", "exact_unique", "ess")},
        "majority_class_under": {m: majority(eps, m)
                                 for m in ("rows", "exact_unique", "ess")},
    }
    flips = []
    row_major = deltas["majority_class_under"]["rows"]["class"]
    for m in ("exact_unique", "ess"):
        if deltas["majority_class_under"][m]["class"] != row_major:
            flips.append(f"majority class flips under {m}: {row_major} -> "
                         f"{deltas['majority_class_under'][m]['class']}")

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt = {
        "ticket": "FP16-CENSUS", "ts": ts,
        "mapping_source": "fp6_provenance.classify (single source)",
        "census": census,
        "standing_claims_delta": deltas,
        "flipped_claims": flips,
        "binding_rule": "any standing claim that flips sign or majority "
                        "under dedup accounting switches its canonical "
                        "quote to the dedup-aware number; corpus quotes "
                        "carry rows AND effective-N from this receipt on",
        "eng_slice_candidate": "ingest-side dedup-cluster stamp (sidecar "
                               "view, files byte-unchanged) — mint as "
                               "eng-25 after this receipt is gated",
        "flags": [
            "bits totals are NOT affected (seed rows carry zero bits — "
            "fp-13); this census corrects ROW-COUNT claims",
            "ESS under equicorrelation is a texture-level diversity "
            "proxy, not a sample-size for any specific estimator",
        ],
    }
    out = f"{RECEIPTS}/fp16-census-{ts}.json"
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(receipt, f, indent=2)
    print(json.dumps(receipt, indent=2))
    print(f"FP16_CENSUS_DONE {out}")


def _selftest():
    sys.path.insert(0, f"{NC_WIN}/scripts")
    # class_stats on constructed texts: 3 identical + 1 distinct
    s = class_stats(["abcdefg" * 10] * 3 + ["zyxwvut" * 10])
    assert s["rows"] == 4 and s["exact_unique"] == 2
    assert s["clusters_cos95"] == 2, s
    assert s["ess"] < 4.0
    # degenerate sizes
    assert class_stats(["only-one"])["rows"] == 1
    assert class_stats([])["rows"] == 0
    # majority under different metrics
    table = {"a": {"rows": 100, "exact_unique": 10, "ess": 1.0},
             "b": {"rows": 50, "exact_unique": 40, "ess": 30.0}}
    assert majority(table, "rows")["class"] == "a"
    assert majority(table, "exact_unique")["class"] == "b"
    assert majority(table, "ess")["class"] == "b"
    assert abs(majority(table, "rows")["share"] - 100 / 150) < 1e-3  # rounded
    print("FP16_CENSUS_SELFTEST_PASS")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        main()
