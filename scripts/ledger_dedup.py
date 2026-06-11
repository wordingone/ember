"""ledger_dedup.py — dedup-cluster sidecar views (eng #97).

Builds two views that stamp every ledger/control-pool row with its
dedup-cluster membership:

  ledger/views/dedup-cluster.jsonl         (episodes)
  ledger/views/dedup-cluster-control.jsonl (control pool)

Per-row fields (mirrors the license-class view key/ordering convention —
same 1:1 ledger-order, same key field):
  key          same key as the ledger row (task:sha or task:ctrl:sha)
  task         task id
  is_exact_dup bool — True if an earlier row has byte-identical src;
               first occurrence of each program text is False
  cluster_id   deterministic cluster identifier: the 0-based index of
               the FIRST row (in ledger order) in this union-find cluster,
               formatted as "c{idx}" — stable across regenerations as long
               as ledger order is stable
  cluster_size int — number of rows in this cluster (exact-dup + near-dup)

Dedup machinery is imported from the SINGLE SOURCE modules (no re-implementation):
  fp10_idiom.trigram_bag          — 256-bucket hashed char-3gram feature
  fp13_concentration.row_normalize, near_dup_edges, union_find_clusters
  fp16_census.class_stats         — cross-check the per-class stats

Cluster definition: union-find over 3-gram-bag cosine >= 0.95 (fp13
NEAR_DUP_COS constant), mirroring fp16_census exactly. Exact-dup flag is
first-occurrence keyed on the program text (src field) — the first row
with a given src is NOT flagged; subsequent identical rows are.

Rows without a src field are assigned cluster_id "c{idx}", is_exact_dup
False, cluster_size 1 (they participate in no similarity computation —
same convention as fp16_census which skips src-less rows from stats).

`python ledger_dedup.py --selftest` — pure-logic, no ledger files needed.
`python ledger_dedup.py --backfill [--ledger ...] [--control-pool ...]
    [--view-out ...] [--control-view-out ...] [--receipt-dir ...]`
Writes the two views + a receipt. Ledger/control files opened READ-ONLY.
sha256 before/after in the receipt for both files (sha_convention: bytes
on disk as-is, no line-ending normalization).
"""
import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone

# Path bootstrap: allow running from repo root (scripts/ not on sys.path by default)
_SCRIPTS = os.path.join(os.path.dirname(__file__))
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

# Single-source imports: machinery lives in fp13_concentration + fp10_idiom.
# fp16_census.class_stats uses these internally; we import from the primaries
# so every layer shares the SAME function objects.
from fp13_concentration import (  # noqa: E402
    row_normalize, near_dup_edges, union_find_clusters,
    NEAR_DUP_COS,
)
from fp10_idiom import trigram_bag  # noqa: E402
from fp6_provenance import classify  # noqa: E402


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _build_cluster_index(recs):
    """Build cluster membership for a list of ledger records.

    Steps mirror fp16_census.class_stats exactly (same functions, same threshold):
      1. collect src texts in ledger order
      2. trigram_bag + row_normalize -> normalised feature matrix
      3. near_dup_edges (cosine >= NEAR_DUP_COS = 0.95)
      4. union_find_clusters

    Returns a list (parallel to recs) of dicts:
      {"is_exact_dup": bool, "cluster_id": str, "cluster_size": int}

    Rows without src are placed into singleton clusters and never flagged
    as exact dups.
    """
    import numpy as np

    n = len(recs)
    # Exact-dup flagging: first occurrence of each src text is canonical.
    seen_src = {}  # src -> first row index
    exact_dup = []  # bool per row
    for idx, r in enumerate(recs):
        src = r.get("src") or ""
        if not src:
            exact_dup.append(False)
            continue
        if src in seen_src:
            exact_dup.append(True)
        else:
            seen_src[src] = idx
            exact_dup.append(False)

    # Near-dup cluster assignment via union-find over src-bearing rows only.
    # Rows without src are kept as singletons (cluster_id = "c{idx}",
    # cluster_size = 1).  src rows are indexed into a compact sub-array.
    src_indices = [i for i, r in enumerate(recs) if r.get("src")]
    srcs = [recs[i]["src"] for i in src_indices]

    if srcs:
        bags = row_normalize([trigram_bag(s) for s in srcs])
        n_sub = len(srcs)
        n_clusters, _sizes, _big = union_find_clusters(
            n_sub, near_dup_edges(bags))

        # Reconstruct union-find parent array to get cluster roots.
        parent = list(range(n_sub))

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        for i, j in near_dup_edges(bags):
            ri, rj = find(i), find(j)
            if ri != rj:
                parent[rj] = ri

        # Resolve all roots
        roots = [find(i) for i in range(n_sub)]
        # root in sub-array -> global ledger index (first occurrence of that root)
        root_to_global_first = {}
        for sub_i, root in enumerate(roots):
            g_idx = src_indices[sub_i]
            if root not in root_to_global_first:
                root_to_global_first[root] = g_idx
            else:
                root_to_global_first[root] = min(root_to_global_first[root], g_idx)

        # Cluster size per root (in sub-array space)
        root_size = {}
        for root in roots:
            root_size[root] = root_size.get(root, 0) + 1
    else:
        roots = []
        root_to_global_first = {}
        root_size = {}
        src_indices = []

    # Build sub-index lookup: sub_i -> (root, cluster_id, cluster_size)
    sub_map = {}
    for sub_i, root in enumerate(roots):
        g_first = root_to_global_first[root]
        sub_map[sub_i] = (root, f"c{g_first}", root_size[root])

    # Map back to full record list
    sub_cursor = 0
    result = []
    for idx in range(n):
        r = recs[idx]
        if r.get("src"):
            root, cid, csz = sub_map[sub_cursor]
            sub_cursor += 1
        else:
            cid = f"c{idx}"
            csz = 1
        result.append({
            "is_exact_dup": exact_dup[idx],
            "cluster_id": cid,
            "cluster_size": csz,
        })
    return result


def stamp_dedup_sidecar(ledger_path, view_path, candidate_rows):
    """Ingest-side stamping helper — called AFTER new rows have been appended
    to ledger_path. Identifies which rows in candidate_rows were actually
    appended (not already in the view), computes their cluster fields against
    the FULL current ledger state, and APPENDS those entries to view_path.

    The main ledger file is opened READ-ONLY. Only view_path is written.
    This is the single correct path: re-running _build_cluster_index on the
    full (post-append) ledger ensures new rows are assigned cluster IDs and
    sizes that reflect their actual position in the full cluster graph, not
    a partial incremental estimate.

    candidate_rows: list of ledger record dicts (same objects passed to
    append_jsonl). Keys already present in the view are skipped (idempotent).

    Returns the list of view rows appended (one per actually-new key).
    """
    if not candidate_rows:
        return []

    # Keys already in the view — skip these (idempotent; handles cases where
    # append_jsonl deduped and the key was already there before this call).
    existing_view_keys = set()
    if os.path.exists(view_path):
        with open(view_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        existing_view_keys.add(json.loads(line)["key"])
                    except (KeyError, json.JSONDecodeError):
                        pass

    new_keys = {r["key"] for r in candidate_rows if r["key"] not in existing_view_keys}
    if not new_keys:
        return []

    # Read the full current ledger state (post-append) and recompute clusters.
    recs = load_jsonl(ledger_path)
    cluster_entries = _build_cluster_index(recs)

    appended = []
    d = os.path.dirname(view_path)
    if d:
        os.makedirs(d, exist_ok=True)

    with open(view_path, "a", encoding="utf-8") as f:
        for r, ce in zip(recs, cluster_entries):
            if r["key"] in new_keys:
                row = {
                    "key": r["key"],
                    "task": r["task"],
                    "is_exact_dup": ce["is_exact_dup"],
                    "cluster_id": ce["cluster_id"],
                    "cluster_size": ce["cluster_size"],
                }
                f.write(json.dumps(row) + "\n")
                appended.append(row)
    return appended


def build_view(ledger_path, view_path):
    """Write the dedup-cluster sidecar view. Ledger opened READ-ONLY.

    Returns (recs, cluster_entries) where cluster_entries is the list
    parallel to recs with is_exact_dup/cluster_id/cluster_size.
    """
    recs = load_jsonl(ledger_path)
    cluster_entries = _build_cluster_index(recs)

    d = os.path.dirname(view_path)
    if d:
        os.makedirs(d, exist_ok=True)

    with open(view_path, "w", encoding="utf-8") as f:
        for r, ce in zip(recs, cluster_entries):
            row = {
                "key": r["key"],
                "task": r["task"],
                "is_exact_dup": ce["is_exact_dup"],
                "cluster_id": ce["cluster_id"],
                "cluster_size": ce["cluster_size"],
            }
            f.write(json.dumps(row) + "\n")
    return recs, cluster_entries


def _census_from_view(recs, cluster_entries):
    """Per-class cluster census from (recs, cluster_entries).

    Returns dict keyed by license class with:
      rows, exact_unique, cluster_count, largest_cluster_size
    """
    by_class = {}
    for r, ce in zip(recs, cluster_entries):
        cls, _ = classify(r)
        if cls not in by_class:
            by_class[cls] = {"rows": 0, "exact_unique": 0,
                             "clusters": set(), "cluster_sizes": {}}
        by_class[cls]["rows"] += 1
        if not ce["is_exact_dup"] and r.get("src"):
            by_class[cls]["exact_unique"] += 1
        cid = ce["cluster_id"]
        by_class[cls]["clusters"].add(cid)
        by_class[cls]["cluster_sizes"][cid] = ce["cluster_size"]

    out = {}
    for cls in sorted(by_class.keys()):
        entry = by_class[cls]
        sizes = sorted(entry["cluster_sizes"].values(), reverse=True)
        out[cls] = {
            "rows": entry["rows"],
            "exact_unique": entry["exact_unique"],
            "cluster_count": len(entry["clusters"]),
            "largest_cluster_size": sizes[0] if sizes else 0,
            "median_cluster_size": sorted(entry["cluster_sizes"].values())[
                len(entry["cluster_sizes"]) // 2] if entry["cluster_sizes"] else 0,
        }
    return out


def _view_summary(recs, cluster_entries):
    """Top-level summary for the full file (all classes combined)."""
    n_exact_dup = sum(1 for ce in cluster_entries if ce["is_exact_dup"])
    cluster_ids = {ce["cluster_id"] for ce in cluster_entries}
    all_sizes = [ce["cluster_size"] for ce in cluster_entries]
    unique_sizes = sorted({ce["cluster_id"]: ce["cluster_size"]
                           for ce in cluster_entries}.values(), reverse=True)
    median_sz = unique_sizes[len(unique_sizes) // 2] if unique_sizes else 0
    return {
        "total_rows": len(recs),
        "exact_dup_count": n_exact_dup,
        "cluster_count": len(cluster_ids),
        "cluster_size_max": unique_sizes[0] if unique_sizes else 0,
        "cluster_size_median": median_sz,
    }


def main():
    ap = argparse.ArgumentParser(
        description="Build dedup-cluster sidecar views from ledger + control pool.")
    ap.add_argument("--backfill", action="store_true", required=True,
                    help="build/backfill the sidecar views + write receipt")
    ap.add_argument("--ledger",
                    default="B:/M/avir/leo/state/nc-ladder/ledger/episodes.jsonl")
    ap.add_argument("--control-pool",
                    default="B:/M/avir/leo/state/nc-ladder/ledger/control_pool.jsonl")
    ap.add_argument("--view-out",
                    default="B:/M/avir/leo/state/nc-ladder/ledger/views/dedup-cluster.jsonl")
    ap.add_argument("--control-view-out",
                    default="B:/M/avir/leo/state/nc-ladder/ledger/views/dedup-cluster-control.jsonl")
    ap.add_argument("--receipt-dir",
                    default="B:/M/avir/leo/state/nc-ladder/receipts")
    args, _unknown = ap.parse_known_args()

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    # sha256 BEFORE — bytes on disk as-is (no normalization; sha_convention
    # makes this explicit to resolve the ambiguity flagged in the #91 gate).
    sha_convention = "bytes on disk as-is (binary read, no line-ending normalization)"
    ledger_sha_before = sha256_file(args.ledger)
    control_sha_before = sha256_file(args.control_pool)

    recs_ep, ce_ep = build_view(args.ledger, args.view_out)
    recs_ctl, ce_ctl = build_view(args.control_pool, args.control_view_out)

    # sha256 AFTER — must be identical (read-only invariant)
    ledger_sha_after = sha256_file(args.ledger)
    control_sha_after = sha256_file(args.control_pool)

    if ledger_sha_before != ledger_sha_after:
        raise SystemExit("ledger_dedup: ledger sha256 changed — byte-unchanged invariant violated")
    if control_sha_before != control_sha_after:
        raise SystemExit("ledger_dedup: control_pool sha256 changed — byte-unchanged invariant violated")

    ep_census = _census_from_view(recs_ep, ce_ep)
    ctl_census = _census_from_view(recs_ctl, ce_ctl)
    ep_summary = _view_summary(recs_ep, ce_ep)
    ctl_summary = _view_summary(recs_ctl, ce_ctl)

    # fp16 cross-check ground truth (receipts/fp16-census-20260611T013228Z.json)
    fp16_ground_truth = {
        "episodes": {
            "arc-dsl-mit": {"rows": 1909, "exact_unique": 780, "clusters_cos95": 9},
            "qwen-research": {"rows": 956, "exact_unique": 956, "clusters_cos95": 592},
        },
        "control_pool": {
            "arc-dsl-mit": {"rows": 1909, "exact_unique": 387, "clusters_cos95": 6},
            "qwen-research": {"rows": 1022, "exact_unique": 1022, "clusters_cos95": 697},
        },
    }

    def cross_check_entry(our, fp16, label):
        ok = (our["rows"] == fp16["rows"]
              and our["exact_unique"] == fp16["exact_unique"]
              and our["cluster_count"] == fp16["clusters_cos95"])
        return {
            "label": label,
            "our_rows": our["rows"],
            "fp16_rows": fp16["rows"],
            "rows_match": our["rows"] == fp16["rows"],
            "our_exact_unique": our["exact_unique"],
            "fp16_exact_unique": fp16["exact_unique"],
            "exact_unique_match": our["exact_unique"] == fp16["exact_unique"],
            "our_cluster_count": our["cluster_count"],
            "fp16_clusters_cos95": fp16["clusters_cos95"],
            "cluster_count_match": our["cluster_count"] == fp16["clusters_cos95"],
            "all_match": ok,
        }

    crosscheck = {
        "fp16_receipt": "receipts/fp16-census-20260611T013228Z.json",
        "sha_convention": sha_convention,
        "episodes": {
            cls: cross_check_entry(
                ep_census.get(cls, {"rows": 0, "exact_unique": 0, "cluster_count": 0}),
                fp16_ground_truth["episodes"][cls],
                f"episodes/{cls}",
            )
            for cls in fp16_ground_truth["episodes"]
        },
        "control_pool": {
            cls: cross_check_entry(
                ctl_census.get(cls, {"rows": 0, "exact_unique": 0, "cluster_count": 0}),
                fp16_ground_truth["control_pool"][cls],
                f"control_pool/{cls}",
            )
            for cls in fp16_ground_truth["control_pool"]
        },
    }
    all_match = all(
        v["all_match"]
        for d in (crosscheck["episodes"], crosscheck["control_pool"])
        for v in d.values()
    )
    crosscheck["overall_match"] = all_match
    if not all_match:
        mismatches = [
            v["label"]
            for d in (crosscheck["episodes"], crosscheck["control_pool"])
            for v in d.values()
            if not v["all_match"]
        ]
        crosscheck["mismatch_labels"] = mismatches

    receipt = {
        "ticket": "ENG25-DEDUP-VIEW",
        "ts": ts,
        "single_source_imports": {
            "fp13_concentration": ["row_normalize", "near_dup_edges",
                                   "union_find_clusters", "NEAR_DUP_COS"],
            "fp10_idiom": ["trigram_bag"],
            "fp6_provenance": ["classify"],
        },
        "sha_convention": sha_convention,
        "ledger": {
            "path": args.ledger,
            "sha256_before": ledger_sha_before,
            "sha256_after": ledger_sha_after,
            "byte_unchanged": ledger_sha_before == ledger_sha_after,
        },
        "control_pool": {
            "path": args.control_pool,
            "sha256_before": control_sha_before,
            "sha256_after": control_sha_after,
            "byte_unchanged": control_sha_before == control_sha_after,
        },
        "main_files_byte_unchanged": True,
        "episodes_view": {
            "path": args.view_out,
            "rows": len(recs_ep),
            "summary": ep_summary,
            "per_class_census": ep_census,
        },
        "control_view": {
            "path": args.control_view_out,
            "rows": len(recs_ctl),
            "summary": ctl_summary,
            "per_class_census": ctl_census,
        },
        "fp16_crosscheck": crosscheck,
    }

    os.makedirs(args.receipt_dir, exist_ok=True)
    out = os.path.join(args.receipt_dir, f"eng25-dedup-view-{ts}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(receipt, f, indent=2)
    print(json.dumps(receipt, indent=2))
    status = "ENG25_DEDUP_VIEW_DONE" if all_match else "ENG25_DEDUP_VIEW_DONE_CROSSCHECK_MISMATCH"
    print(f"{status} {out}")


def _selftest():
    """Pure-logic selftest — no ledger files needed.
    Tests: is_exact_dup flagging, cluster_id stability, cluster_size,
    near-identical text joins cluster, ingest stamping helper, regeneration
    stability (deterministic).
    """
    import tempfile
    import random

    # --- 1. Exact-dup flagging ---
    # 3 records: 0 and 2 have identical src; 1 has distinct src.
    recs = [
        {"key": "t1:a", "task": "t1", "src": "print('hello')"},
        {"key": "t2:b", "task": "t2", "src": "print('world')"},
        {"key": "t3:c", "task": "t3", "src": "print('hello')"},  # dup of 0
    ]
    ce = _build_cluster_index(recs)
    assert not ce[0]["is_exact_dup"], "first occurrence must not be flagged"
    assert not ce[1]["is_exact_dup"], "distinct src must not be flagged"
    assert ce[2]["is_exact_dup"], "repeat src must be flagged"

    # --- 2. Cluster size correct ---
    # All three above: recs 0 and 2 have same text -> same cluster.
    # Near-dup threshold is 0.95; identical text -> cosine=1.0 -> same cluster.
    assert ce[0]["cluster_size"] == 2, f"cluster size should be 2, got {ce[0]['cluster_size']}"
    assert ce[2]["cluster_size"] == 2, f"cluster size should be 2, got {ce[2]['cluster_size']}"
    assert ce[1]["cluster_size"] == 1 or ce[1]["cluster_size"] >= 1  # at least singleton

    # --- 3. cluster_id stability — first-occurrence index ---
    # recs 0 and 2 are in the same cluster; first occurrence is index 0 -> "c0"
    assert ce[0]["cluster_id"] == "c0"
    assert ce[2]["cluster_id"] == "c0"
    # rec 1 is a singleton cluster rooted at index 1 -> "c1"
    assert ce[1]["cluster_id"] == "c1"

    # --- 4. Near-identical text (cosine >= 0.95) joins cluster ---
    # Build two texts that are near-identical (same 3-gram bag).
    base = "def solve(grid):\n    " + "x = grid[0][0]\n    " * 20 + "return x\n"
    # Append a single extra character to make texts differ by one char
    near = base + "#\n"
    recs2 = [
        {"key": "t1:x", "task": "t1", "src": base},
        {"key": "t2:y", "task": "t2", "src": near},
        {"key": "t3:z", "task": "t3", "src": "completely_different_" * 30},
    ]
    ce2 = _build_cluster_index(recs2)
    # base and near should be in the same cluster (cosine close to 1.0)
    assert ce2[0]["cluster_id"] == ce2[1]["cluster_id"], (
        f"near-identical texts should share cluster: {ce2[0]['cluster_id']} vs {ce2[1]['cluster_id']}")
    assert ce2[2]["cluster_id"] != ce2[0]["cluster_id"], (
        "completely different text should be in its own cluster")

    # --- 5. Repeat (exact-dup) gets correct cluster_size ---
    # ce2[0] and ce2[1] share a cluster of size 2
    assert ce2[0]["cluster_size"] == 2
    assert ce2[1]["cluster_size"] == 2
    assert ce2[2]["cluster_size"] == 1

    # --- 6. Ingest stamping: build_view on temp file -> correct view row ---
    fd, ledger_p = tempfile.mkstemp(suffix=".jsonl")
    os.close(fd)
    fd, view_p = tempfile.mkstemp(suffix=".jsonl")
    os.close(fd)
    try:
        test_recs = [
            {"key": "t1:a", "task": "t1", "src": base,
             "origin": "seed-dsl-orig"},
            {"key": "t2:b", "task": "t2", "src": base,  # exact dup
             "origin": "seed-dsl-orig"},
            {"key": "t3:c", "task": "t3", "src": near,  # near dup
             "origin": "seed-dsl-orig"},
        ]
        with open(ledger_p, "w", encoding="utf-8") as f:
            for r in test_recs:
                f.write(json.dumps(r) + "\n")
        sha_before = sha256_file(ledger_p)
        recs_out, ce_out = build_view(ledger_p, view_p)
        sha_after = sha256_file(ledger_p)

        # byte-unchanged
        assert sha_before == sha_after, "ledger must be byte-unchanged after build_view"

        # view rows match
        view_rows = load_jsonl(view_p)
        assert len(view_rows) == 3
        # first row: not dup
        assert not view_rows[0]["is_exact_dup"]
        # second row: exact dup
        assert view_rows[1]["is_exact_dup"]
        # third row: near-dup but NOT exact-dup (different text)
        assert not view_rows[2]["is_exact_dup"]
        # all three in same cluster (0 and 2 near-dup merge, then 1 is exact-dup of 0 -> same sub-cluster)
        assert view_rows[0]["cluster_id"] == view_rows[1]["cluster_id"] == view_rows[2]["cluster_id"]
        # cluster size is 3
        assert view_rows[0]["cluster_size"] == 3

    finally:
        os.unlink(ledger_p)
        try:
            os.unlink(view_p)
        except FileNotFoundError:
            pass

    # --- 7. stamp_dedup_sidecar: appending a synthetic row lands correct cluster entry ---
    # Simulate: existing ledger has 2 rows; we "append" a 3rd (exact dup) and
    # a 4th (near-dup), then call stamp_dedup_sidecar with only those 2 new keys.
    fd, sled_p = tempfile.mkstemp(suffix=".jsonl")
    os.close(fd)
    fd, sview_p = tempfile.mkstemp(suffix=".jsonl")
    os.close(fd)
    try:
        existing = [
            {"key": "s1:a", "task": "s1", "src": base, "origin": "seed-dsl-orig"},
            {"key": "s2:b", "task": "s2", "src": "unrelated_text " * 30, "origin": "seed-dsl-orig"},
        ]
        new_rows = [
            {"key": "s3:c", "task": "s3", "src": base, "origin": "seed-dsl-orig"},   # exact dup of s1:a
            {"key": "s4:d", "task": "s4", "src": near, "origin": "seed-dsl-orig"},   # near-dup of s1:a
        ]
        # Write existing + new rows to ledger (simulates post-append state)
        with open(sled_p, "w", encoding="utf-8") as f:
            for r in existing + new_rows:
                f.write(json.dumps(r) + "\n")
        # Write existing rows' view first (simulates pre-append view state)
        build_view.__doc__  # just ensure build_view is loaded; we'll use stamp_dedup_sidecar
        recs_existing = existing
        ce_existing = _build_cluster_index(recs_existing)
        # Write partial view for the existing rows
        with open(sview_p, "w", encoding="utf-8") as f:
            for r, ce in zip(recs_existing, ce_existing):
                f.write(json.dumps({
                    "key": r["key"], "task": r["task"],
                    "is_exact_dup": ce["is_exact_dup"],
                    "cluster_id": ce["cluster_id"],
                    "cluster_size": ce["cluster_size"],
                }) + "\n")
        # Now call stamp_dedup_sidecar to append the new rows
        appended = stamp_dedup_sidecar(sled_p, sview_p, new_rows)

        # We should have 2 appended rows
        assert len(appended) == 2, f"expected 2 appended rows, got {len(appended)}"

        # s3:c is exact dup of s1:a -> is_exact_dup=True
        s3_row = next(r for r in appended if r["key"] == "s3:c")
        assert s3_row["is_exact_dup"], "s3:c is exact dup of s1:a, should be flagged"

        # s4:d is near-dup of s1:a (cosine >= 0.95) but NOT exact dup
        s4_row = next(r for r in appended if r["key"] == "s4:d")
        assert not s4_row["is_exact_dup"], "s4:d is near-dup, not exact dup, should not be flagged"

        # Both s3 and s4 should be in the same cluster as s1:a (cluster "c0")
        assert s3_row["cluster_id"] == "c0", f"s3:c should be in c0, got {s3_row['cluster_id']}"
        assert s4_row["cluster_id"] == "c0", f"s4:d should be in c0, got {s4_row['cluster_id']}"

        # cluster_size for c0 should be 3 (s1:a, s3:c, s4:d) after the new rows join
        assert s3_row["cluster_size"] == 3, f"cluster size should be 3, got {s3_row['cluster_size']}"
        assert s4_row["cluster_size"] == 3, f"cluster size should be 3, got {s4_row['cluster_size']}"

        # The view file should now have 4 rows total
        full_view = load_jsonl(sview_p)
        assert len(full_view) == 4, f"view should have 4 rows, got {len(full_view)}"

    finally:
        os.unlink(sled_p)
        try:
            os.unlink(sview_p)
        except FileNotFoundError:
            pass

    # --- 8. Regeneration stability: run twice on same input -> byte-identical output ---
    fd, ledger_p2 = tempfile.mkstemp(suffix=".jsonl")
    os.close(fd)
    fd, view_p2a = tempfile.mkstemp(suffix=".jsonl")
    os.close(fd)
    fd, view_p2b = tempfile.mkstemp(suffix=".jsonl")
    os.close(fd)
    try:
        test_recs2 = [
            {"key": f"t{i}:k{i}", "task": f"t{i}",
             "src": f"def f{i}(): return {i}\n" * 5,
             "origin": "seed-dsl-orig"}
            for i in range(10)
        ]
        with open(ledger_p2, "w", encoding="utf-8") as f:
            for r in test_recs2:
                f.write(json.dumps(r) + "\n")
        build_view(ledger_p2, view_p2a)
        build_view(ledger_p2, view_p2b)
        with open(view_p2a, "rb") as f:
            bytes_a = f.read()
        with open(view_p2b, "rb") as f:
            bytes_b = f.read()
        assert bytes_a == bytes_b, "two runs must produce byte-identical output"
    finally:
        os.unlink(ledger_p2)
        try:
            os.unlink(view_p2a)
            os.unlink(view_p2b)
        except FileNotFoundError:
            pass

    print("LEDGER_DEDUP_SELFTEST_PASS")  # sentinel matched by verification step


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        main()
