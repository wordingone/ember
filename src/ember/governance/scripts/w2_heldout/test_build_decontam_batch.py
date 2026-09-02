# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""test_build_decontam_batch.py -- hermetic fixture tests for
src/ember/governance/scripts/w2_heldout/build_decontam_batch.py's window I/O and self-match-aware
classification logic. Real code, synthetic-only corpus (two tiny .bin shard
files under tempfile.TemporaryDirectory()) -- the real shards corpus
is never touched by this suite. This is the RED/GREEN coverage of the novel
piece of this dispatch (self-match exclusion, including the cross-shard-
boundary case that a naive (shard, offset) comparison would misclassify).
"""
from __future__ import annotations

import os
import sys
import tempfile

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_decontam_batch  # noqa: E402
from build_decontam_batch import (  # noqa: E402
    cheap_shard_sizes,
    _cumulative_token_offsets,
    window_source_position,
    read_window_tokens,
    classify_candidates,
    batch_sha256,
    reserve_pool,
)

SEQ = 3
N_MTP = 0
BLOCK_LEN = SEQ + 1 + N_MTP  # 4
WINDOW = 4  # contamination match granularity for this fixture (whole-row)

# shard0: 12 tokens. shard1: 7 tokens, whose FIRST 4 tokens ([1,2,3,4])
# deliberately duplicate shard0's first 4 tokens -- window0 and window4 will
# have identical content at two different physical locations (genuine
# cross-shard duplication, the exact class W1 found 69,811 of).
SHARD0 = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]
SHARD1 = [1, 2, 3, 4, 100, 101, 102]
# n_windows = (19 - 4)//3 + 1 = 6 -> indices 0..5, starts 0,3,6,9,12,15
# window0 start=0  -> shard0[0:4]  = [1,2,3,4]      (duplicated at window4)
# window2 start=6  -> shard0[6:10] = [7,8,9,10]     (unique -> CLEAN)
# window3 start=9  -> shard0[9:12]+shard1[0:1] = [10,11,12,1]  (boundary-spanning, unique)
# window4 start=12 -> shard1[0:4]  = [1,2,3,4]      (duplicate of window0)


@pytest.fixture
def synth_corpus():
    with tempfile.TemporaryDirectory() as td:
        np.array(SHARD0, dtype="<u2").tofile(os.path.join(td, "v0-00000.bin"))
        np.array(SHARD1, dtype="<u2").tofile(os.path.join(td, "v0-00001.bin"))
        yield td


def test_cheap_shard_sizes_reads_token_counts_without_hashing(synth_corpus):
    files = cheap_shard_sizes(synth_corpus)

    assert [f["name"] for f in files] == ["v0-00000.bin", "v0-00001.bin"]
    assert files[0]["n_tokens"] == 12
    assert files[1]["n_tokens"] == 7


def test_window_source_position_reports_correct_shard_and_global_start(synth_corpus):
    files = cheap_shard_sizes(synth_corpus)
    cum = _cumulative_token_offsets(files)

    pos0 = window_source_position(files, cum, SEQ, 0)
    pos4 = window_source_position(files, cum, SEQ, 4)

    assert pos0 == {"shard": "v0-00000.bin", "offset": 0, "global_start": 0}
    assert pos4 == {"shard": "v0-00001.bin", "offset": 0, "global_start": 12}


def test_read_window_tokens_within_single_shard(synth_corpus):
    files = cheap_shard_sizes(synth_corpus)
    cum = _cumulative_token_offsets(files)

    row = read_window_tokens(synth_corpus, files, cum, SEQ, BLOCK_LEN, 2)

    assert row == [7, 8, 9, 10]


def test_read_window_tokens_spans_shard_boundary(synth_corpus):
    files = cheap_shard_sizes(synth_corpus)
    cum = _cumulative_token_offsets(files)

    row = read_window_tokens(synth_corpus, files, cum, SEQ, BLOCK_LEN, 3)

    assert row == [10, 11, 12, 1]


def test_classify_candidates_flags_genuine_cross_shard_duplicate_as_contaminated(synth_corpus):
    files = cheap_shard_sizes(synth_corpus)
    cum = _cumulative_token_offsets(files)
    indices = [0, 4]  # identical content [1,2,3,4] at two different locations
    rows = [read_window_tokens(synth_corpus, files, cum, SEQ, BLOCK_LEN, i) for i in indices]
    positions = [window_source_position(files, cum, SEQ, i) for i in indices]

    result = classify_candidates(rows, positions, synth_corpus, window=WINDOW,
                                  files=files, cum=cum)

    assert result["clean_idx"] == []
    assert sorted(result["contaminated_idx"]) == [0, 1]
    # each candidate's own physical location is excluded as self; only the
    # OTHER candidate's identical-content location counts as non-self.
    assert len(result["non_self_matches_by_candidate"][0]) == 1
    assert len(result["non_self_matches_by_candidate"][1]) == 1


def test_classify_candidates_marks_unique_window_clean(synth_corpus):
    files = cheap_shard_sizes(synth_corpus)
    cum = _cumulative_token_offsets(files)
    indices = [2]  # [7,8,9,10] -- appears nowhere else in either shard
    rows = [read_window_tokens(synth_corpus, files, cum, SEQ, BLOCK_LEN, i) for i in indices]
    positions = [window_source_position(files, cum, SEQ, i) for i in indices]

    result = classify_candidates(rows, positions, synth_corpus, window=WINDOW,
                                  files=files, cum=cum)

    assert result["clean_idx"] == [0]
    assert result["contaminated_idx"] == []
    assert result["self_matches_excluded"] == 1  # its own trivial self-hit, excluded correctly


def test_classify_candidates_boundary_spanning_unique_window_is_clean_not_falsely_flagged(synth_corpus):
    """The bug this test guards against: window3 [10,11,12,1] spans the
    shard0/shard1 boundary, so contamination_recheck reports its OWN match
    via the {boundary, offset_in_join} shape, not {shard, offset}. Before the
    global-position fix, ANY boundary-shaped match was treated as
    automatically non-self, which would have flagged this unique,
    boundary-spanning window as contaminated against itself."""
    files = cheap_shard_sizes(synth_corpus)
    cum = _cumulative_token_offsets(files)
    indices = [3]
    rows = [read_window_tokens(synth_corpus, files, cum, SEQ, BLOCK_LEN, i) for i in indices]
    positions = [window_source_position(files, cum, SEQ, i) for i in indices]

    result = classify_candidates(rows, positions, synth_corpus, window=WINDOW,
                                  files=files, cum=cum)

    assert result["clean_idx"] == [0], (
        "boundary-spanning window incorrectly flagged as contaminated against its own "
        f"reflection: non_self_matches={result['non_self_matches_by_candidate']}")


def test_classify_candidates_without_files_cum_treats_boundary_as_non_self_safe_default(synth_corpus):
    """When files/cum are omitted, boundary matches can't be resolved to a
    global position, so the safe default (never treat as self) applies --
    this makes the filter MORE conservative, never less, so it can only
    over-replace a boundary-spanning window that was actually clean, never
    silently accept a genuine duplicate."""
    files = cheap_shard_sizes(synth_corpus)
    cum = _cumulative_token_offsets(files)
    indices = [3]
    rows = [read_window_tokens(synth_corpus, files, cum, SEQ, BLOCK_LEN, i) for i in indices]
    positions = [window_source_position(files, cum, SEQ, i) for i in indices]

    result = classify_candidates(rows, positions, synth_corpus, window=WINDOW)

    assert result["contaminated_idx"] == [0]
    assert result["self_matches_excluded"] == 0


def test_batch_sha256_changes_when_any_row_changes():
    rows_a = [[1, 2, 3, 4], [5, 6, 7, 8]]
    rows_b = [[1, 2, 3, 4], [5, 6, 7, 9]]

    sha_a = batch_sha256(rows_a, seq=3)
    sha_b = batch_sha256(rows_b, seq=3)

    assert sha_a != sha_b
    assert batch_sha256(rows_a, seq=3) == sha_a  # deterministic


def test_reserve_pool_respects_disjointness_from_training():
    # n_windows=100, pool_size=10 -> pool_start=90. ceiling_steps*train_batch-1
    # must be < 90 for disjoint=True.
    pool_start, disjoint_check = reserve_pool(100, 10, ceiling_steps=5, train_batch=16)

    assert pool_start == 90
    assert disjoint_check["disjoint"] is True
    assert disjoint_check["max_training_window_index_at_ceiling"] == 5 * 16 - 1


def test_reserve_pool_raises_when_not_disjoint():
    # ceiling_steps*train_batch-1 = 999 >= pool_start=90 -> not disjoint.
    with pytest.raises(SystemExit, match="W1_LIVE_HELDOUT_NOT_DISJOINT"):
        reserve_pool(100, 10, ceiling_steps=1000, train_batch=1)


# ---------------------------------------------------------------------------
# Adaptive MemoryError-splitting -- the fix for the real run's discovery that
# contamination_recheck's own np.isin call can require more memory than is
# available under ambient pressure from unrelated processes, and that ceiling
# is not a fixed needle count (it depends on whatever memory happens to be
# free right now). classify_candidates must retry with smaller sub-batches on
# MemoryError rather than assuming a hardcoded safe size. Simulated via
# monkeypatching contamination_recheck itself (no real corpus, no real memory
# pressure needed to exercise the retry/merge logic).
# ---------------------------------------------------------------------------

def _fake_contamination_recheck_factory(fail_above_rows: int, real_shard_dir, real_window):
    """Wraps the REAL contamination_recheck (against the synthetic fixture
    corpus) but raises MemoryError if called with more candidate rows than
    fail_above_rows -- simulating "the needle set is too big for current
    ambient memory" without needing gigabytes of real pressure."""
    real_fn = build_decontam_batch.contamination_recheck

    def _fake(candidate_rows, shard_dir, *, window=None, roll_base=None):
        if len(candidate_rows) > fail_above_rows:
            raise MemoryError(
                f"simulated: {len(candidate_rows)} rows exceeds fake ceiling {fail_above_rows}")
        return real_fn(candidate_rows, shard_dir, window=window, roll_base=roll_base)

    return _fake


def test_classify_candidates_splits_and_merges_on_simulated_memory_error(synth_corpus, monkeypatch):
    files = cheap_shard_sizes(synth_corpus)
    cum = _cumulative_token_offsets(files)
    indices = [0, 2, 3, 4]  # window0/4 duplicate each other; window2/3 unique
    rows = [read_window_tokens(synth_corpus, files, cum, SEQ, BLOCK_LEN, i) for i in indices]
    positions = [window_source_position(files, cum, SEQ, i) for i in indices]

    monkeypatch.setattr(
        build_decontam_batch, "contamination_recheck",
        _fake_contamination_recheck_factory(fail_above_rows=1, real_shard_dir=synth_corpus,
                                             real_window=WINDOW))

    result = classify_candidates(rows, positions, synth_corpus, window=WINDOW, files=files, cum=cum)

    assert result["split_occurred"] is True
    assert result["n_calls"] == 4  # forced down to one row per call
    # Same classification as the unsplit case (order-independent): indices
    # 0 and 4 in the ORIGINAL pool are the duplicate pair -> contaminated;
    # 2 and 3 are unique -> clean. Here rows list is [idx0, idx2, idx3, idx4]
    # -> local positions 0 and 3 are the contaminated pair, 1 and 2 clean.
    assert sorted(result["clean_idx"]) == [1, 2]
    assert sorted(result["contaminated_idx"]) == [0, 3]


def test_classify_candidates_reraises_memory_error_when_single_row_still_fails(synth_corpus, monkeypatch):
    indices = [2]
    files = cheap_shard_sizes(synth_corpus)
    cum = _cumulative_token_offsets(files)
    rows = [read_window_tokens(synth_corpus, files, cum, SEQ, BLOCK_LEN, i) for i in indices]
    positions = [window_source_position(files, cum, SEQ, i) for i in indices]

    monkeypatch.setattr(
        build_decontam_batch, "contamination_recheck",
        _fake_contamination_recheck_factory(fail_above_rows=0, real_shard_dir=synth_corpus,
                                             real_window=WINDOW))

    with pytest.raises(MemoryError):
        classify_candidates(rows, positions, synth_corpus, window=WINDOW, files=files, cum=cum)
