"""t2_cap.py — cluster-cap wrapper for t2_round.build_dataset (eng #101).

Extends the existing per-task bits-weighted cap (frontier.DEFAULT_CAPS) one
level to the dedup-cluster level.  After build_dataset selects examples via
per-task caps, apply_cluster_cap trims to the cluster-level cap using the
dedup-cluster sidecar stamp from eng-25 (ledger/views/dedup-cluster.jsonl).

Cluster stratum = best member-task stratum ("best" = the stratum with the
highest cap among members, matching the ordering: frontier>=mid>=easy>=dead
per the DEFAULT_CAPS table: 8>=4>=2>=8 — frontier and dead both cap at 8 so
"best" is defined as MAX cap value).

Freshness gate (AC from #102 review): before reading the view, re-run a
--backfill build to a TEMP path and verify byte-identity with the committed
view (sha256, bytes on disk as-is).  On mismatch: fail-closed.  The
committed view is never overwritten by this path.

Import notes:
  - DEFAULT_CAPS imported from frontier (single source — never re-typed here).
  - build_dataset imported from t2_round (single source — cap logic wraps, not
    forks, the dataset assembly).
  - Freshness check calls ledger_dedup.build_view on a TEMP path; the
    committed view file is opened READ-ONLY.

Usage (standalone):
    from t2_cap import build_dataset_with_cluster_cap, freshness_check
    examples, counts, cap_stats = build_dataset_with_cluster_cap(
        ledger_path, view_path, cluster_cap=True)
"""

import hashlib
import json
import os
import sys
import tempfile

# Single-source caps table — never re-typed.
from frontier import DEFAULT_CAPS  # noqa: E402

# CAP ordering: highest-cap stratum wins for cluster stratum resolution.
# DEFAULT_CAPS = {"easy": 2, "mid": 4, "frontier": 8, "dead": 8}
# Ordering by cap value: frontier==dead (8) > mid (4) > easy (2)
# Tie-break: frontier preferred over dead (a cluster member in "frontier" has
# observed successes; "dead" means no observed successes — prefer the more
# evidence-rich stratum when caps are equal).
_STRATUM_RANK = {"frontier": 0, "dead": 1, "mid": 2, "easy": 3}


def _best_stratum(strata):
    """Return the stratum with the highest cap (lowest rank number = best).

    Tie-break: frontier > dead (both cap=8; frontier = observed successes).
    """
    return min(strata, key=lambda s: _STRATUM_RANK.get(s, 99))


def sha256_file(path):
    """sha256 of a file as bytes on disk, no line-ending normalization."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_dedup_view(view_path):
    """Load dedup-cluster sidecar. Returns dict: key -> {cluster_id, cluster_size, task}."""
    rows = {}
    with open(view_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            rows[r["key"]] = r
    return rows


def freshness_check(ledger_path, control_pool_path, view_path,
                    control_view_path):
    """Verify committed view is byte-identical to a fresh backfill build.

    Builds to a TEMP directory; never touches the committed view.
    Returns (ok: bool, detail: dict).  On mismatch: ok=False.

    This implements the gate-added AC from the #102 review: membership must
    be consumed from a fresh --backfill, never a stale incremental stamp.
    """
    from ledger_dedup import build_view  # single source

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_view = os.path.join(tmpdir, "dedup-cluster.jsonl")
        tmp_ctrl = os.path.join(tmpdir, "dedup-cluster-control.jsonl")

        build_view(ledger_path, tmp_view)
        build_view(control_pool_path, tmp_ctrl)

        committed_sha = sha256_file(view_path)
        fresh_sha = sha256_file(tmp_view)

        ok = committed_sha == fresh_sha
        detail = {
            "sha_convention": "bytes on disk as-is (binary read, no line-ending normalization)",
            "committed_view_sha256": committed_sha,
            "fresh_backfill_sha256": fresh_sha,
            "byte_identical": ok,
        }
    if not ok:
        detail["error"] = (
            "Freshness check FAILED: committed dedup-cluster view does not "
            "match a fresh --backfill build. Consuming a stale view is "
            "fail-closed — re-run ledger_dedup.py --backfill to regenerate "
            "the committed view before invoking the cluster-cap path."
        )
    return ok, detail


def apply_cluster_cap(examples, counts, ledger_path, view_path,
                      caps=None):
    """Apply per-cluster cap on top of a build_dataset output.

    Reads ledger to obtain per-example stratum (from the 'stratum' field
    stamped at ingest by frontier.annotate_records) and the dedup-cluster view
    to resolve cluster membership.

    Cluster stratum = best member-task stratum (best = highest cap value).
    Cap per cluster = caps[cluster_stratum].

    Within a cluster, examples are kept in the order build_dataset already
    produced them (shortest-src first within each task, tasks in sorted order
    — this ordering is preserved, not re-sorted here).

    Returns:
      trimmed_examples: list of chat examples after cluster cap
      cap_stats: dict with per-stratum before/after counts + cluster breakdown
    """
    if caps is None:
        caps = DEFAULT_CAPS

    # Load the dedup-cluster view (key -> cluster info)
    view = load_dedup_view(view_path)

    # Load ledger to get stratum per key.  Ledger opened READ-ONLY.
    task_stratum = {}  # task_id -> stratum (from ledger records)
    with open(ledger_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            if "stratum" in r:
                t = r["task"]
                # Prefer frontier over dead as best if tied on cap value;
                # use _best_stratum to combine across records for the same task.
                existing = task_stratum.get(t)
                if existing is None:
                    task_stratum[t] = r["stratum"]
                else:
                    task_stratum[t] = _best_stratum([existing, r["stratum"]])

    # Build a key lookup: for each task we need its ledger keys.
    # We correlate examples back to ledger records via task+src.
    # Re-read ledger to build (task, src) -> key mapping.
    task_src_to_key = {}
    with open(ledger_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            ts_key = (r["task"], r.get("src", ""))
            if ts_key not in task_src_to_key:
                task_src_to_key[ts_key] = r["key"]

    # We need to map each example back to a dedup cluster.
    # build_dataset produces examples with messages[0]=user, messages[1]=assistant.
    # The assistant content is ```python\n{src}\n``` (from t2_round.build_dataset).
    # Extract src from assistant content to look up (task, src) -> key -> cluster.
    # Also need the task for each example — build_dataset sorted by task_id.
    # We rebuild the task association by walking counts (same sorted order).
    # Simpler: re-read the ledger and cross-reference by assistant content.

    def _src_from_example(ex):
        """Extract src from the assistant message content."""
        content = ex["messages"][1]["content"]
        # Format: ```python\n{src}\n```
        if content.startswith("```python\n") and content.endswith("\n```"):
            return content[len("```python\n"):-len("\n```")]
        return content  # fallback

    # Map cluster_id -> list of (position_in_examples, example)
    cluster_examples = {}  # cluster_id -> [(pos, task, ex)]

    # We need the task for each example — associate via task iteration matching
    # build_dataset's sorted(by_task.items()) order and counts.
    # Rebuild task->examples mapping by iterating in sorted task order.
    task_to_examples = {}
    # Walk examples in order; use counts to attribute them to tasks.
    task_order = sorted(counts.keys())
    pos = 0
    for task_id in task_order:
        n = counts[task_id]
        task_to_examples[task_id] = examples[pos:pos + n]
        pos += n

    for task_id in task_order:
        for ex in task_to_examples[task_id]:
            src = _src_from_example(ex)
            ledger_key = task_src_to_key.get((task_id, src))
            if ledger_key and ledger_key in view:
                cid = view[ledger_key]["cluster_id"]
            else:
                # No view entry: treat as singleton (no cap binding beyond task cap)
                cid = f"_singleton_{task_id}_{src[:16]}"
            cluster_examples.setdefault(cid, []).append((task_id, ex))

    # Resolve cluster stratum: best member-task stratum across all tasks in cluster.
    cluster_strata = {}
    for cid, members in cluster_examples.items():
        strata = [task_stratum.get(t, "dead") for t, _ in members]
        cluster_strata[cid] = _best_stratum(strata) if strata else "dead"

    # Apply cluster cap: keep at most caps[cluster_stratum] examples per cluster.
    kept_set = set()  # positions of kept examples (by id(ex))
    cap_stats_per_cluster = {}  # for reporting
    per_stratum_before = {st: 0 for st in caps}
    per_stratum_after = {st: 0 for st in caps}

    for cid, members in cluster_examples.items():
        st = cluster_strata[cid]
        cluster_cap = caps.get(st, caps.get("dead", 8))
        n_before = len(members)
        st_key = st if st in caps else "dead"
        per_stratum_before[st_key] = per_stratum_before.get(st_key, 0) + n_before
        n_kept = min(n_before, cluster_cap)
        per_stratum_after[st_key] = per_stratum_after.get(st_key, 0) + n_kept
        for _, ex in members[:n_kept]:
            kept_set.add(id(ex))
        cap_stats_per_cluster[cid] = {
            "stratum": st,
            "cluster_cap": cluster_cap,
            "before": n_before,
            "kept": n_kept,
            "dropped": n_before - n_kept,
        }

    trimmed = [ex for ex in examples if id(ex) in kept_set]

    # Summary stats
    n_bound = sum(1 for v in cap_stats_per_cluster.values() if v["dropped"] > 0)
    cap_stats = {
        "clusters_total": len(cluster_examples),
        "clusters_cap_bound": n_bound,
        "examples_before_cluster_cap": len(examples),
        "examples_after_cluster_cap": len(trimmed),
        "per_stratum_before": per_stratum_before,
        "per_stratum_after": per_stratum_after,
        "caps_used": caps,
        "stratum_rank_rule": (
            "best member-task stratum = min cap rank: "
            "frontier(0)>dead(1)>mid(2)>easy(3); "
            "frontier preferred over dead on tie (both cap=8)"
        ),
    }
    return trimmed, cap_stats


def build_dataset_with_cluster_cap(ledger_path, view_path,
                                   control_pool_path=None,
                                   control_view_path=None,
                                   cluster_cap=True,
                                   caps=None,
                                   skip_freshness=False,
                                   license_allow=None):
    """High-level entry point: freshness check + build_dataset + cluster cap.

    cluster_cap=False: delegates entirely to build_dataset (no-cap path;
    default behaviour is byte-identical to the pre-#101 build).

    cluster_cap=True: freshness check (fail-closed on mismatch), then
    build_dataset (per-task caps from frontier), then apply_cluster_cap.

    skip_freshness=True: bypass the freshness check (selftest only).

    Returns (examples, counts, meta) where meta is a dict with:
      freshness: freshness_check detail dict (or {"skipped": true})
      cluster_cap_stats: apply_cluster_cap output (or {"applied": false})
    """
    from t2_round import build_dataset, LEDGER as _DEFAULT_LEDGER  # single source

    if caps is None:
        caps = DEFAULT_CAPS

    meta = {}

    if cluster_cap:
        if skip_freshness:
            meta["freshness"] = {"skipped": True}
        else:
            if control_pool_path is None or control_view_path is None:
                raise ValueError(
                    "control_pool_path and control_view_path required for "
                    "freshness check (or pass skip_freshness=True for selftests)")
            ok, detail = freshness_check(
                ledger_path, control_pool_path, view_path, control_view_path)
            meta["freshness"] = detail
            if not ok:
                raise SystemExit(detail["error"])

    examples, counts = build_dataset(ledger_path, license_allow=license_allow)
    meta["examples_from_build_dataset"] = len(examples)

    if cluster_cap:
        trimmed, cap_stats = apply_cluster_cap(
            examples, counts, ledger_path, view_path, caps=caps)
        meta["cluster_cap_stats"] = cap_stats
        return trimmed, counts, meta
    else:
        meta["cluster_cap_stats"] = {"applied": False}
        return examples, counts, meta
