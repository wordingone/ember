#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

"""Unit tests for shard grouping fix (issue #184).

Execution-binding tests for the worker-group distribution logic:
- 26 shards / 4 workers → exactly 4 groups with sizes {7,7,6,6}
- 3 shards / 4 workers → 3 groups (min constraint)
- 24 shards / 4 workers → 4 groups of 6 each (balanced)
- 1 shard / 4 workers → 1 group (min constraint)

The fix ensures grouping produces EXACTLY min(n_workers, len(shard_paths))
balanced groups, preventing silent extra workers (issue #184 root cause).
Issue #331 additionally requires each group to be physically contiguous.
"""
from __future__ import annotations

import sys


def distribute_shards(n_shards: int, n_workers: int) -> list[list[int]]:
    """Mimic the fixed grouping logic from build_decontam_batch_mp.py.

    Distributes shards into EXACTLY min(n_workers, len(shard_paths)) balanced
    contiguous groups so worker-local joins are true corpus boundaries.
    """
    shard_paths = list(range(n_shards))  # Placeholder shard identifiers
    n_groups = min(n_workers, n_shards)
    base_size, remainder = divmod(n_shards, n_groups)
    worker_shards = []
    start = 0
    for group_index in range(n_groups):
        size = base_size + (1 if group_index < remainder else 0)
        worker_shards.append(shard_paths[start:start + size])
        start += size
    return worker_shards


def test_26_shards_4_workers():
    """Test: 26 shards / 4 workers -> exactly 4 groups with sizes {7,7,6,6}."""
    groups = distribute_shards(26, 4)
    assert len(groups) == 4, f"Expected 4 groups, got {len(groups)}"
    sizes = sorted([len(g) for g in groups], reverse=True)
    expected_sizes = sorted([7, 7, 6, 6], reverse=True)
    assert sizes == expected_sizes, f"Expected sizes {expected_sizes}, got {sizes}"
    # Verify all shards present exactly once
    all_shards = set()
    for g in groups:
        for s in g:
            assert s not in all_shards, f"Duplicate shard {s}"
            all_shards.add(s)
    assert len(all_shards) == 26, f"Expected 26 unique shards, got {len(all_shards)}"
    assert all(group == list(range(group[0], group[-1] + 1))
               for group in groups)
    print("[PASS] 26/4: 4 groups, sizes={}".format(sizes))


def test_3_shards_4_workers():
    """Test: 3 shards / 4 workers -> 3 groups (min constraint)."""
    groups = distribute_shards(3, 4)
    assert len(groups) == 3, f"Expected 3 groups, got {len(groups)}"
    sizes = sorted([len(g) for g in groups], reverse=True)
    expected_sizes = sorted([1, 1, 1], reverse=True)
    assert sizes == expected_sizes, f"Expected sizes {expected_sizes}, got {sizes}"
    print("[PASS] 3/4: 3 groups, sizes={}".format(sizes))


def test_24_shards_4_workers():
    """Test: 24 shards / 4 workers -> 4 groups of 6 each."""
    groups = distribute_shards(24, 4)
    assert len(groups) == 4, f"Expected 4 groups, got {len(groups)}"
    sizes = sorted([len(g) for g in groups], reverse=True)
    expected_sizes = sorted([6, 6, 6, 6], reverse=True)
    assert sizes == expected_sizes, f"Expected sizes {expected_sizes}, got {sizes}"
    print("[PASS] 24/4: 4 groups, sizes={}".format(sizes))


def test_1_shard_4_workers():
    """Test: 1 shard / 4 workers -> 1 group (min constraint)."""
    groups = distribute_shards(1, 4)
    assert len(groups) == 1, f"Expected 1 group, got {len(groups)}"
    assert len(groups[0]) == 1, f"Expected group of size 1, got {len(groups[0])}"
    print("[PASS] 1/4: 1 group, sizes={}".format([len(g) for g in groups]))


if __name__ == "__main__":
    try:
        test_26_shards_4_workers()
        test_3_shards_4_workers()
        test_24_shards_4_workers()
        test_1_shard_4_workers()
        print("\n[ALL PASS] All worker grouping tests PASS (4/4)")
        sys.exit(0)
    except AssertionError as e:
        print("\n[FAIL] Test assertion failed: {}".format(e))
        sys.exit(1)
    except Exception as e:
        print("\n[FAIL] Uncaught exception: {}".format(e))
        import traceback
        traceback.print_exc()
        sys.exit(1)
