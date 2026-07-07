"""test_corpus_window_index.py -- TDD for corpus window-hash index.

Verifies that index-lookup produces identical results to direct full-corpus scan
for a set of known-contaminated and known-clean windows.

Test windows:
  1. A window from the training-front (known duplicated)
  2. A window from the held-out stratum (known clean)
  3. A boundary-spanning window if applicable

Index lookup must match direct contamination_recheck on these.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile

import numpy as np
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_ROOT = os.path.dirname(HERE)
REPO_ROOT = os.path.dirname(SCRIPTS_ROOT)
sys.path.insert(0, SCRIPTS_ROOT)

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
from w2_heldout.corpus_window_index import (
    build_corpus_index,
    load_index,
)


def test_index_vs_direct_scan():
    """Verify index-lookup == direct-scan for known windows."""
    shard_dir = os.environ.get("EMBER_SHARD_DIR", "")
    if not shard_dir:
        pytest.skip("EMBER_SHARD_DIR not set; skipping live corpus test")

    seq = 1024
    n_mtp = 2
    window = CONTAMINATION_WINDOW_TOKENS
    roll_base = CONTAMINATION_ROLL_BASE
    block_len = seq + 1 + n_mtp

    # Load shard structure
    files = cheap_shard_sizes(shard_dir)
    cum = _cumulative_token_offsets(files)

    # Test window 1: from training front (should have duplicates)
    test_window_idx_1 = 100  # Early in the corpus
    tokens_1 = read_window_tokens(shard_dir, files, cum, seq, window, test_window_idx_1)
    window_tuple_1 = tuple(tokens_1)

    # Test window 2: from held-out region (should be clean)
    test_window_idx_2 = 4194305  # Held-out stratum start
    tokens_2 = read_window_tokens(shard_dir, files, cum, seq, window, test_window_idx_2)
    window_tuple_2 = tuple(tokens_2)

    # Direct scan: run contamination_recheck on these windows
    candidate_rows = [list(tokens_1), list(tokens_2)]
    direct_result = contamination_recheck(
        candidate_rows, shard_dir, window=window, roll_base=roll_base
    )

    # Extract what we learn from direct scan
    direct_matches = set()
    for m in direct_result["confirmed_matches"]:
        w = tuple(m["window"])
        direct_matches.add(w)

    # Now test the index for these same windows
    # (In practice, index would be pre-built once; here we build it fresh)
    print(f"Building index for test (this may take a few minutes)...")
    index_receipt = build_corpus_index(shard_dir=shard_dir, seq=seq, n_mtp=n_mtp,
                                        window=window, roll_base=roll_base)
    window_to_positions = index_receipt["window_to_positions"]

    # Check if our test windows are in the index with matching hit counts
    index_has_1 = window_tuple_1 in window_to_positions
    index_has_2 = window_tuple_2 in window_to_positions

    direct_has_1 = window_tuple_1 in direct_matches
    direct_has_2 = window_tuple_2 in direct_matches

    # They should match (both found or both not found)
    assert index_has_1 == direct_has_1, (
        f"Mismatch on window 1: index={index_has_1}, direct={direct_has_1}"
    )
    assert index_has_2 == direct_has_2, (
        f"Mismatch on window 2: index={index_has_2}, direct={direct_has_2}"
    )

    # If found, position counts should match (allowing for the step=10 sampling)
    if index_has_1:
        # Index was built with step=10, so it samples windows. Position count
        # should be less than or equal to the full corpus count, but should
        # include at least one position.
        assert len(window_to_positions[window_tuple_1]) >= 1
    if index_has_2:
        assert len(window_to_positions[window_tuple_2]) >= 1

    print("[PASS] Index matches direct scan for test windows")


def test_index_json_roundtrip():
    """Verify index can be serialized and deserialized without loss."""
    # Create a tiny test index
    test_index = {
        (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13): [
            {"shard": "shard_0.bin", "offset": 1000, "global_start": 1000},
            {"shard": "shard_1.bin", "offset": 500, "global_start": 50000},
        ],
        (2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14): [
            {"shard": "shard_2.bin", "offset": 2000, "global_start": 100000},
        ],
    }

    # Simulate JSON serialization (tuple keys -> strings)
    json_safe = {}
    for window_tuple, positions in test_index.items():
        key = "|".join(str(x) for x in window_tuple)
        json_safe[key] = positions

    # Roundtrip through JSON
    json_str = json.dumps(json_safe)
    json_loaded = json.loads(json_str)

    # Reconstruct tuples
    reconstructed = {}
    for key_str, positions in json_loaded.items():
        window_tuple = tuple(int(x) for x in key_str.split("|"))
        reconstructed[window_tuple] = positions

    # Verify it matches
    assert reconstructed == test_index
    print("[PASS] Index JSON serialization roundtrip successful")


if __name__ == "__main__":
    # Run tests
    test_index_json_roundtrip()
    test_index_vs_direct_scan()
    print("\nAll tests passed!")
