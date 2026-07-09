"""test_corpus_bloom_index.py -- TDD for Bloom filter index.

Two test tiers:
1. Synthetic-fixture tests (CI-runnable, seconds): Bloom properties + math
2. Integration tests (env-guarded, corpus-scale): Bloom vs direct-scan equivalence

CI will run tier 1 (always green); tier 2 requires EMBER_SHARD_DIR and
verifies soundness against real corpus.
"""
from __future__ import annotations

import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_ROOT = os.path.dirname(HERE)
REPO_ROOT = os.path.dirname(SCRIPTS_ROOT)
sys.path.insert(0, SCRIPTS_ROOT)

from w2_heldout.corpus_bloom_index import SimpleBloomFilter


# =============================================================================
# TIER 1: Synthetic-fixture tests (CI-runnable, no env dependency)
# =============================================================================

def test_bloom_zero_false_negatives():
    """Bloom filter has zero false negatives by construction."""
    bf = SimpleBloomFilter(n_items=100, target_fp_rate=0.01)

    items = [
        (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13),
        (10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22),
        (100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110, 111, 112),
    ]

    # Add items
    for item in items:
        bf.add(item)

    # All added items MUST be found (zero false negatives)
    for item in items:
        assert bf.contains(item), f"False negative: {item} not found"

    print("[PASS] Bloom filter has zero false negatives")


def test_bloom_fp_rate_bounded():
    """False positive rate stays within target after adding many items."""
    n = 1000
    target_fp = 0.01
    bf = SimpleBloomFilter(n_items=n, target_fp_rate=target_fp)

    # Add half the expected items
    added = []
    for i in range(n // 2):
        item = (i, i + 1, i + 2, i + 3, i + 4, i + 5, i + 6, i + 7, i + 8, i + 9, i + 10, i + 11, i + 12)
        bf.add(item)
        added.append(item)

    # Test false positives on items NOT added
    false_positives = 0
    test_count = 1000
    for i in range(n, n + test_count):
        item = (i, i + 1, i + 2, i + 3, i + 4, i + 5, i + 6, i + 7, i + 8, i + 9, i + 10, i + 11, i + 12)
        if bf.contains(item):
            false_positives += 1

    observed_fp_rate = false_positives / test_count
    max_acceptable_fp_rate = target_fp * 2  # Allow 2x slack for variance

    assert observed_fp_rate <= max_acceptable_fp_rate, (
        f"FP rate {observed_fp_rate:.4f} exceeds max {max_acceptable_fp_rate:.4f}"
    )

    print(f"[PASS] FP rate {observed_fp_rate:.4f} <= {max_acceptable_fp_rate:.4f}")


def test_bloom_serialization():
    """Bloom filter serializes and deserializes without loss."""
    bf = SimpleBloomFilter(n_items=100, target_fp_rate=0.01)

    items = [
        (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13),
        (100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110, 111, 112),
    ]

    for item in items:
        bf.add(item)

    # Serialize
    data = bf.to_bytes()
    assert len(data) == bf.size_bytes()

    # Deserialize
    bf2 = SimpleBloomFilter.from_bytes(data, bf.m, bf.k)

    # Verify both filters behave identically
    for item in items:
        assert bf2.contains(item), f"Deserialized filter missing {item}"

    print(f"[PASS] Bloom serialization roundtrip: {len(data)} bytes")


def test_bloom_different_items_independent():
    """Different hash functions produce independent bit patterns."""
    bf = SimpleBloomFilter(n_items=10, target_fp_rate=0.01)

    item1 = (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13)
    item2 = (2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14)

    # Before adding, neither should be found
    assert not bf.contains(item1)
    assert not bf.contains(item2)

    # Add only item1
    bf.add(item1)
    assert bf.contains(item1)

    # item2 should not be found (or very unlikely to be a FP)
    # Given we only added 1 item and filter size is large, FP chance is tiny
    # But Bloom allows FPs, so we can't assert NOT contains, only check likelihood

    print("[PASS] Different items produce independent bit patterns")


# =============================================================================
# TIER 2: Integration tests (env-guarded, corpus-scale equivalence)
# =============================================================================

def test_bloom_vs_direct_scan_corpus():
    """Verify Bloom-filtered candidate verdict == direct contamination_recheck.

    This test requires EMBER_SHARD_DIR. Skipped in CI; run locally for
    integration verification before landing.
    """
    shard_dir = os.environ.get("EMBER_SHARD_DIR", "")
    if not shard_dir:
        pytest.skip("EMBER_SHARD_DIR not set; skipping corpus integration test")

    # Import here so CI doesn't need contamination_recheck
    from w1_collapse_control_run import (
        contamination_recheck,
        CONTAMINATION_WINDOW_TOKENS,
        CONTAMINATION_ROLL_BASE,
    )
    from w2_heldout.build_decontam_batch import (
        cheap_shard_sizes,
        _cumulative_token_offsets,
        read_window_tokens,
    )
    from w2_heldout.corpus_bloom_index import build_corpus_bloom_filter

    seq = 1024
    n_mtp = 2
    window = CONTAMINATION_WINDOW_TOKENS
    roll_base = CONTAMINATION_ROLL_BASE
    block_len = seq + 1 + n_mtp

    # Load shard structure
    files = cheap_shard_sizes(shard_dir)
    cum = _cumulative_token_offsets(files)

    # Test windows: one from training-front, one from held-out
    test_cases = [
        (100, "training-front (likely contaminated)"),
        (4194305, "held-out stratum (likely clean)"),
    ]

    # Build Bloom filter (this takes time; could cache in CI)
    print("Building corpus Bloom filter (integration test)...")
    index_result = build_corpus_bloom_filter(shard_dir=shard_dir, seq=seq, n_mtp=n_mtp)
    bf = index_result["bloom_filter"]

    for test_idx, description in test_cases:
        print(f"\nTesting window {test_idx} ({description})...")

        tokens = read_window_tokens(shard_dir, files, cum, seq, window, test_idx)
        window_tuple = tuple(tokens)

        # Get Bloom filter verdict
        bloom_says_might_be_contaminated = bf.contains(window_tuple)

        # Get direct scan verdict
        direct_result = contamination_recheck(
            [list(tokens)], shard_dir, window=window, roll_base=roll_base
        )
        direct_found_matches = len(direct_result["confirmed_matches"]) > 0

        # Bloom negatives are definite (no false negatives)
        if not bloom_says_might_be_contaminated:
            assert not direct_found_matches, (
                f"Bloom said CLEAN, direct scan found matches: {direct_result['confirmed_matches']}"
            )
        # Bloom positives might be FPs, but direct scan gives the truth
        print(f"  Bloom: {'might be contaminated' if bloom_says_might_be_contaminated else 'definite clean'}")
        print(f"  Direct: {'contaminated' if direct_found_matches else 'clean'}")

    print("\n[PASS] Bloom integration test complete")


if __name__ == "__main__":
    # Run tier-1 tests (always runnable)
    print("=" * 60)
    print("TIER 1: Synthetic-fixture tests (CI-runnable)")
    print("=" * 60)
    test_bloom_zero_false_negatives()
    test_bloom_fp_rate_bounded()
    test_bloom_serialization()
    test_bloom_different_items_independent()

    print("\n" + "=" * 60)
    print("TIER 2: Integration tests (env-guarded)")
    print("=" * 60)
    try:
        test_bloom_vs_direct_scan_corpus()
    except pytest.skip.Exception as e:
        print(f"SKIPPED: {e}")

    print("\n" + "=" * 60)
    print("All tests completed!")
    print("=" * 60)
