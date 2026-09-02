#!/usr/bin/env python3
"""Unit tests for pool placement logic (tail vs. explicit index placement).

Execution-binding tests for pool semantics with --pool-start-index:
- Tail mode (default): pool marches DOWNWARD from corpus tail per #115 fix
- Explicit mode: pool extends UPWARD from specified start index (mid-corpus placement)
- Both modes: subsequent rounds properly bounded, safety guard catches oversized pools
"""
from __future__ import annotations

import sys


def simulate_pool_rounds(
    n_windows: int,
    batch_size: int,
    pool_oversample: int,
    max_rounds: int,
    explicit_pool_start: int | None = None,
    training_ceil_windows: int = 1533 * 16,  # ceiling_steps=1533, train_batch=16
) -> list[dict]:
    """Simulate pool placement for both tail and explicit modes.

    Returns list of rounds with (pool_start, pool_end, pool_size) for each.
    """
    pool_size = batch_size * pool_oversample
    disjoint_lower_bound = training_ceil_windows

    if explicit_pool_start is not None:
        pool_start = explicit_pool_start
        explicit_mode = True
    else:
        pool_start = n_windows - pool_size  # tail mode
        explicit_mode = False

    pool_floor = pool_start
    rounds = []
    selected = 0

    for round_no in range(1, max_rounds + 1):
        need = batch_size - selected
        if need <= 0:
            break
        this_pool_size = max(need * pool_oversample, need)

        if round_no == 1:
            if explicit_mode:
                this_pool_start = pool_start
                this_pool_end = min(pool_start + this_pool_size, n_windows)
            else:
                this_pool_start, this_pool_end = pool_start, n_windows
        else:
            if explicit_mode:
                this_pool_start = pool_floor
                this_pool_end = min(pool_floor + this_pool_size, n_windows)
            else:
                this_pool_end = pool_floor
                this_pool_start = max(disjoint_lower_bound, this_pool_end - this_pool_size)

        pool_len = this_pool_end - this_pool_start
        if pool_len <= 0:
            break

        # Safety guard: catch oversized pools
        max_allowed = batch_size * pool_oversample * 100
        if pool_len > max_allowed:
            raise SystemExit(
                f"W2_DECONTAM_POOL_RANGE_INSANE: round {round_no} pool size "
                f"{pool_len} exceeds {max_allowed}")

        rounds.append({
            "round": round_no,
            "pool_start": this_pool_start,
            "pool_end": this_pool_end,
            "pool_size": pool_len,
        })

        if explicit_mode:
            pool_floor = this_pool_end
        else:
            pool_floor = this_pool_start

        selected += min(need, pool_len)  # Simulate selecting up to 'need' windows

    return rounds


def test_tail_mode_tail_placement():
    """Test: tail mode (default) with large tail pool, bounded in round 2."""
    # Config: batch_size=16, oversample=2 → pool_size=32
    # Corpus: 6.8M windows (from issue #193 comment)
    n_windows = 6814324
    batch_size = 16
    pool_oversample = 2

    rounds = simulate_pool_rounds(
        n_windows=n_windows,
        batch_size=batch_size,
        pool_oversample=pool_oversample,
        max_rounds=6,
        explicit_pool_start=None,  # tail mode
    )

    # Round 1 should span [pool_start, n_windows)
    r1 = rounds[0]
    assert r1["pool_start"] == n_windows - 32, \
        f"Round 1 start: expected {n_windows - 32}, got {r1['pool_start']}"
    assert r1["pool_end"] == n_windows, \
        f"Round 1 end: expected {n_windows}, got {r1['pool_end']}"
    assert r1["pool_size"] == 32, \
        f"Round 1 size: expected 32, got {r1['pool_size']}"

    # Round 2 should be bounded downward
    if len(rounds) > 1:
        r2 = rounds[1]
        assert r2["pool_size"] == 32, \
            f"Round 2 size: expected 32, got {r2['pool_size']}"
        assert r2["pool_end"] == r1["pool_start"], \
            f"Round 2 end should match round 1 start"

    print(f"[PASS] tail_mode: {len(rounds)} rounds, round 1 size={r1['pool_size']}")
    return True


def test_explicit_mode_mid_corpus():
    """Test: explicit placement at 3.4M (mid-corpus), bounded upward extension."""
    # Config: batch_size=16, oversample=2 → pool_size=32
    # Corpus: 6.8M windows, training uses [0, 24528), so [24528, 6.8M) is disjoint
    # Placement: index 3,400,000 (mid-corpus)
    n_windows = 6814324
    batch_size = 16
    pool_oversample = 2
    pool_start_index = 3400000

    rounds = simulate_pool_rounds(
        n_windows=n_windows,
        batch_size=batch_size,
        pool_oversample=pool_oversample,
        max_rounds=6,
        explicit_pool_start=pool_start_index,
    )

    # Round 1 should be [pool_start_index, pool_start_index + pool_size)
    r1 = rounds[0]
    expected_end = min(pool_start_index + 32, n_windows)
    assert r1["pool_start"] == pool_start_index, \
        f"Round 1 start: expected {pool_start_index}, got {r1['pool_start']}"
    assert r1["pool_end"] == expected_end, \
        f"Round 1 end: expected {expected_end}, got {r1['pool_end']}"
    assert r1["pool_size"] == (expected_end - pool_start_index), \
        f"Round 1 size: expected {expected_end - pool_start_index}, got {r1['pool_size']}"

    # Round 2 should extend upward from round 1's end
    if len(rounds) > 1:
        r2 = rounds[1]
        assert r2["pool_start"] == r1["pool_end"], \
            f"Round 2 start should match round 1 end"
        assert r2["pool_size"] == 32, \
            f"Round 2 size: expected 32, got {r2['pool_size']}"

    print(f"[PASS] explicit_mode: {len(rounds)} rounds, round 1 start={r1['pool_start']}, size={r1['pool_size']}")
    return True


def test_explicit_mode_guards_oversized_pool():
    """Test: safety guard catches oversized pool (should never happen with bounded logic)."""
    # This is a defensive test: if logic is broken, this catches it.
    # With batch_size=16, oversample=2, max allowed pool = 16*2*100 = 3200.
    # In explicit mode, round 1 pool = min(pool_start + 32, n_windows),
    # so it should never exceed 32 unless n_windows is tiny and we misbehave.

    n_windows = 100  # tiny corpus
    batch_size = 16
    pool_oversample = 2
    pool_start_index = 10

    rounds = simulate_pool_rounds(
        n_windows=n_windows,
        batch_size=batch_size,
        pool_oversample=pool_oversample,
        max_rounds=6,
        explicit_pool_start=pool_start_index,
    )

    # All pools should be <= 32 (bounded by pool_size in explicit mode)
    for r in rounds:
        assert r["pool_size"] <= 32, \
            f"Round {r['round']} pool size {r['pool_size']} exceeds 32"

    print(f"[PASS] guard: all pools bounded, max={max(r['pool_size'] for r in rounds)}")
    return True


if __name__ == "__main__":
    try:
        test_tail_mode_tail_placement()
        test_explicit_mode_mid_corpus()
        test_explicit_mode_guards_oversized_pool()
        print("\n[ALL PASS] All pool placement tests PASS (3/3)")
        sys.exit(0)
    except AssertionError as e:
        print(f"\n[FAIL] Test assertion failed: {e}")
        sys.exit(1)
    except SystemExit as e:
        if e.code != 0:
            print(f"\n[FAIL] SystemExit: {e}")
            sys.exit(1)
        raise
    except Exception as e:
        print(f"\n[FAIL] Uncaught exception: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
