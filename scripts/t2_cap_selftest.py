"""t2_cap_selftest.py — pure-logic selftest for t2_cap (eng #101).

Runs without torch, unsloth, t1_probe, or any WSL-only module.
Covers:
  1. cap binds (cluster larger than cap is trimmed)
  2. cap does not bind (cluster smaller than cap passes through)
  3. singleton clusters (cluster_size=1 — no binding)
  4. stratum resolution to best member (frontier > mid > easy > dead on cap)
  5. freshness check fails closed on a doctored stale view (temp files)

All assertions use constructed in-memory data; no ledger files required.

`python t2_cap_selftest.py` -> exits 0 on pass, non-zero on failure.
"""

import hashlib
import json
import os
import sys
import tempfile

# Path bootstrap for repo scripts + nc-ladder scripts
_REPO_SCRIPTS = os.path.join(os.path.dirname(os.path.abspath(__file__)))
_NC_SCRIPTS = "/mnt/b/M/avir/leo/state/nc-ladder/scripts"
if _REPO_SCRIPTS not in sys.path:
    sys.path.insert(0, _REPO_SCRIPTS)
if _NC_SCRIPTS not in sys.path:
    sys.path.insert(0, _NC_SCRIPTS)

from frontier import DEFAULT_CAPS  # noqa: E402
from t2_cap import (  # noqa: E402
    _best_stratum,
    _STRATUM_RANK,
    apply_cluster_cap,
    freshness_check,
    sha256_file,
)


def _make_example(task, src):
    return {
        "messages": [
            {"role": "user", "content": f"solve {task}"},
            {"role": "assistant",
             "content": f"```python\n{src}\n```"},
        ]
    }


def _write_ledger(path, records):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


def _write_view(path, rows):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def test_cap_binds():
    """Cluster with 5 examples, stratum=easy (cap=2) -> trimmed to 2."""
    caps = DEFAULT_CAPS  # easy=2, mid=4, frontier=8, dead=8

    # Build 5 examples from 5 different tasks, all in cluster "c0"
    tasks = [f"task{i}" for i in range(5)]
    srcs = [f"def f{i}(): return {i}" for i in range(5)]
    examples = [_make_example(t, s) for t, s in zip(tasks, srcs)]
    counts = {t: 1 for t in tasks}

    with tempfile.TemporaryDirectory() as td:
        # Ledger: all tasks in "easy" stratum
        ledger_recs = [
            {"key": f"{t}:k{i}", "task": t, "src": s, "stratum": "easy"}
            for i, (t, s) in enumerate(zip(tasks, srcs))
        ]
        ledger_path = os.path.join(td, "episodes.jsonl")
        _write_ledger(ledger_path, ledger_recs)

        # View: all 5 rows in same cluster "c0", cluster_size=5
        view_rows = [
            {"key": f"{t}:k{i}", "task": t,
             "is_exact_dup": False, "cluster_id": "c0", "cluster_size": 5}
            for i, t in enumerate(tasks)
        ]
        view_path = os.path.join(td, "view.jsonl")
        _write_view(view_path, view_rows)

        trimmed, cap_stats = apply_cluster_cap(
            examples, counts, ledger_path, view_path, caps=caps)

        assert len(trimmed) == 2, (
            f"easy cluster of 5 should trim to cap=2, got {len(trimmed)}")
        assert cap_stats["clusters_cap_bound"] == 1
        assert cap_stats["examples_before_cluster_cap"] == 5
        assert cap_stats["examples_after_cluster_cap"] == 2
        assert cap_stats["per_stratum_before"]["easy"] == 5
        assert cap_stats["per_stratum_after"]["easy"] == 2
    print("PASS: test_cap_binds (easy cluster 5->2)")


def test_cap_does_not_bind():
    """Cluster with 2 examples, stratum=frontier (cap=8) -> all kept."""
    caps = DEFAULT_CAPS

    tasks = [f"ft_task{i}" for i in range(2)]
    srcs = [f"def frontier_{i}(): return {i}" for i in range(2)]
    examples = [_make_example(t, s) for t, s in zip(tasks, srcs)]
    counts = {t: 1 for t in tasks}

    with tempfile.TemporaryDirectory() as td:
        ledger_recs = [
            {"key": f"{t}:k{i}", "task": t, "src": s, "stratum": "frontier"}
            for i, (t, s) in enumerate(zip(tasks, srcs))
        ]
        ledger_path = os.path.join(td, "episodes.jsonl")
        _write_ledger(ledger_path, ledger_recs)

        view_rows = [
            {"key": f"{t}:k{i}", "task": t,
             "is_exact_dup": False, "cluster_id": "c0", "cluster_size": 2}
            for i, t in enumerate(tasks)
        ]
        view_path = os.path.join(td, "view.jsonl")
        _write_view(view_path, view_rows)

        trimmed, cap_stats = apply_cluster_cap(
            examples, counts, ledger_path, view_path, caps=caps)

        assert len(trimmed) == 2, (
            f"frontier cluster of 2 should keep all (cap=8), got {len(trimmed)}")
        assert cap_stats["clusters_cap_bound"] == 0
        assert cap_stats["examples_before_cluster_cap"] == 2
        assert cap_stats["examples_after_cluster_cap"] == 2
    print("PASS: test_cap_does_not_bind (frontier cluster 2, cap=8, kept all)")


def test_singleton_clusters():
    """Each task in its own cluster (size=1) — no cap binding for any."""
    caps = DEFAULT_CAPS

    tasks = [f"s_task{i}" for i in range(6)]
    srcs = [f"def singleton_{i}(): return {i}" for i in range(6)]
    examples = [_make_example(t, s) for t, s in zip(tasks, srcs)]
    counts = {t: 1 for t in tasks}

    with tempfile.TemporaryDirectory() as td:
        ledger_recs = [
            {"key": f"{t}:k{i}", "task": t, "src": s, "stratum": "easy"}
            for i, (t, s) in enumerate(zip(tasks, srcs))
        ]
        ledger_path = os.path.join(td, "episodes.jsonl")
        _write_ledger(ledger_path, ledger_recs)

        # Each in its own cluster
        view_rows = [
            {"key": f"{t}:k{i}", "task": t,
             "is_exact_dup": False, "cluster_id": f"c{i}", "cluster_size": 1}
            for i, t in enumerate(tasks)
        ]
        view_path = os.path.join(td, "view.jsonl")
        _write_view(view_path, view_rows)

        trimmed, cap_stats = apply_cluster_cap(
            examples, counts, ledger_path, view_path, caps=caps)

        # Each singleton cluster has 1 example; easy cap=2, so 1 <= 2, no binding
        assert len(trimmed) == 6, (
            f"6 singletons, all easy but cluster size=1 <= cap=2, should keep all; got {len(trimmed)}")
        assert cap_stats["clusters_cap_bound"] == 0
    print("PASS: test_singleton_clusters (6 singletons, easy cap=2, all kept)")


def test_stratum_resolution_best_member():
    """Cluster spans easy and frontier tasks — should resolve to frontier (cap=8)."""
    caps = DEFAULT_CAPS

    # One easy task (cap would be 2) and one frontier task (cap=8)
    # both in same cluster -> cluster stratum = frontier (best cap)
    tasks_easy = ["easy_task0", "easy_task1"]
    tasks_front = ["front_task0"]
    all_tasks = tasks_easy + tasks_front
    srcs = [f"def mixed_{i}(): return {i}" for i in range(len(all_tasks))]
    examples = [_make_example(t, s) for t, s in zip(all_tasks, srcs)]
    counts = {t: 1 for t in all_tasks}

    with tempfile.TemporaryDirectory() as td:
        ledger_recs = []
        for i, (t, s) in enumerate(zip(all_tasks, srcs)):
            st = "easy" if t.startswith("easy") else "frontier"
            ledger_recs.append(
                {"key": f"{t}:k{i}", "task": t, "src": s, "stratum": st})
        ledger_path = os.path.join(td, "episodes.jsonl")
        _write_ledger(ledger_path, ledger_recs)

        # All in same cluster "c0"
        view_rows = [
            {"key": f"{t}:k{i}", "task": t,
             "is_exact_dup": False, "cluster_id": "c0",
             "cluster_size": len(all_tasks)}
            for i, t in enumerate(all_tasks)
        ]
        view_path = os.path.join(td, "view.jsonl")
        _write_view(view_path, view_rows)

        trimmed, cap_stats = apply_cluster_cap(
            examples, counts, ledger_path, view_path, caps=caps)

        # Cluster stratum = frontier (best member), cap=8, cluster has 3 -> keep all 3
        assert len(trimmed) == 3, (
            f"cluster with frontier member -> cap=8, 3 examples should all be kept; got {len(trimmed)}")
        assert cap_stats["clusters_cap_bound"] == 0

    # Cross-check: purely easy cluster with 3 examples would bind at 2
    tasks_easy3 = [f"e3_task{i}" for i in range(3)]
    srcs3 = [f"def e3_{i}(): return {i}" for i in range(3)]
    examples3 = [_make_example(t, s) for t, s in zip(tasks_easy3, srcs3)]
    counts3 = {t: 1 for t in tasks_easy3}
    with tempfile.TemporaryDirectory() as td2:
        ledger_recs3 = [
            {"key": f"{t}:k{i}", "task": t, "src": s, "stratum": "easy"}
            for i, (t, s) in enumerate(zip(tasks_easy3, srcs3))
        ]
        ledger_path3 = os.path.join(td2, "episodes.jsonl")
        _write_ledger(ledger_path3, ledger_recs3)
        view_rows3 = [
            {"key": f"{t}:k{i}", "task": t,
             "is_exact_dup": False, "cluster_id": "c0", "cluster_size": 3}
            for i, t in enumerate(tasks_easy3)
        ]
        view_path3 = os.path.join(td2, "view.jsonl")
        _write_view(view_path3, view_rows3)
        trimmed3, cap_stats3 = apply_cluster_cap(
            examples3, counts3, ledger_path3, view_path3, caps=caps)
        assert len(trimmed3) == 2, (
            f"pure easy cluster 3 -> cap=2, got {len(trimmed3)}")
        assert cap_stats3["clusters_cap_bound"] == 1

    print("PASS: test_stratum_resolution_best_member (mixed cluster -> frontier; pure-easy cross-check)")


def test_freshness_check_fails_closed():
    """Freshness check must fail-closed on a doctored stale view."""
    from ledger_dedup import build_view  # single source

    base_src = "def solve(grid):\n    " + "x = grid[0][0]\n    " * 20 + "return x\n"

    with tempfile.TemporaryDirectory() as td:
        # Build a small ledger
        ledger_path = os.path.join(td, "episodes.jsonl")
        control_path = os.path.join(td, "control_pool.jsonl")
        view_path = os.path.join(td, "dedup-cluster.jsonl")
        ctrl_view_path = os.path.join(td, "dedup-cluster-control.jsonl")

        recs = [
            {"key": f"t{i}:k{i}", "task": f"t{i}",
             "src": base_src + f"# row {i}\n"}
            for i in range(3)
        ]
        _write_ledger(ledger_path, recs)
        _write_ledger(control_path, recs[:1])

        # Build fresh view
        build_view(ledger_path, view_path)
        build_view(control_path, ctrl_view_path)

        # First: should pass (view is fresh)
        ok, detail = freshness_check(ledger_path, control_path,
                                     view_path, ctrl_view_path)
        assert ok, f"freshness check should PASS on fresh view, got: {detail}"

        # Doctrine the view: append a bogus row to make it stale
        with open(view_path, "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps({"key": "bogus:xxx", "task": "bogus",
                                "is_exact_dup": False,
                                "cluster_id": "c99", "cluster_size": 1}) + "\n")

        ok_stale, detail_stale = freshness_check(
            ledger_path, control_path, view_path, ctrl_view_path)
        assert not ok_stale, "freshness check should FAIL on doctored stale view"
        assert "error" in detail_stale
        assert not detail_stale["byte_identical"]
    print("PASS: test_freshness_check_fails_closed (fresh=ok, doctored=fail)")


def test_stratum_rank_ordering():
    """_STRATUM_RANK must order: frontier(0) < dead(1) < mid(2) < easy(3)."""
    assert _STRATUM_RANK["frontier"] < _STRATUM_RANK["dead"]
    assert _STRATUM_RANK["dead"] < _STRATUM_RANK["mid"]
    assert _STRATUM_RANK["mid"] < _STRATUM_RANK["easy"]
    # best of all four -> frontier
    assert _best_stratum(["easy", "mid", "dead", "frontier"]) == "frontier"
    # best of easy and mid -> mid
    assert _best_stratum(["easy", "mid"]) == "mid"
    # singleton
    assert _best_stratum(["easy"]) == "easy"
    print("PASS: test_stratum_rank_ordering")


def main():
    print("=== t2_cap selftest ===")
    test_stratum_rank_ordering()
    test_cap_binds()
    test_cap_does_not_bind()
    test_singleton_clusters()
    test_stratum_resolution_best_member()
    test_freshness_check_fails_closed()
    print("=== T2_CAP_SELFTEST_PASS ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
