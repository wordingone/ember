"""Issue #115 regression tests: replacement-pool draws must extend
DOWNWARD from the tail toward the training-disjoint boundary, never
upward off the corpus end.

Before the fix, build_batch's round loop set next_pool_start =
pool_indices[-1] + 1 after every round -- so once round 1's tail pool
(the LAST pool_size windows) came back fully contaminated, round 2's
pool started at n_windows (one past the corpus end), producing an empty
pool_indices and an immediate, premature W2_DECONTAM_POOL_EXHAUSTED --
even though the ~6.79M training-disjoint mid-corpus windows below the
tail were never examined.

These tests exercise the REAL build_batch code path (not a
reimplementation of its arithmetic) by mocking out every I/O-dependent
helper (corpus reading, manifest, classify_candidates) so the round loop
runs against a tiny synthetic n_windows space in milliseconds, with a
deterministic scripted classifier standing in for the real corpus scan.
"""
import os
import sys
import unittest
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import build_decontam_batch_mp as mp  # noqa: E402

N_WINDOWS = 1000
CEILING_STEPS = 10
TRAIN_BATCH = 4
DISJOINT_LOWER_BOUND = CEILING_STEPS * TRAIN_BATCH  # = 40
BATCH_SIZE = 4
POOL_OVERSAMPLE = 2
# pool_size = 8 -> held_out_window_start(1000, 8) = 992 (round-1 tail pool
# is windows [992, 1000)).


def _fake_cheap_shard_sizes(shard_dir):
    return [{"name": "fake-0.bin", "size_bytes": 0, "n_tokens": 0}]


def _fake_cumulative_token_offsets(files):
    return [0, 0]


def _fake_shard_manifest_for_window_count(shard_dir):
    return {"total_size_bytes": 0}


def _fake_compute_n_windows(manifest, seq, n_mtp=0):
    return N_WINDOWS


def _fake_read_window_tokens(shard_dir, files, cum, seq, block_len, i):
    return [i]  # placeholder row -- content is irrelevant, classify is scripted


def _fake_window_source_position(files, cum, seq, i):
    return {"shard": "fake", "offset": i, "global_start": i}


class ScriptedClassify:
    """Deterministic stand-in for classify_candidates: any pool whose
    indices are ALL >= TAIL_CONTAMINATED_FLOOR is fully contaminated;
    everything else is fully clean. Encodes issue #115's exact scenario
    (tail unusable, mid-corpus clean) without touching real corpus I/O."""

    def __init__(self, tail_contaminated_floor):
        self.tail_contaminated_floor = tail_contaminated_floor
        self.calls: list[list[int]] = []

    def __call__(self, candidate_rows, candidate_positions, shard_dir, **kwargs):
        idx = [p["global_start"] for p in candidate_positions]
        self.calls.append(idx)
        if idx and min(idx) >= self.tail_contaminated_floor:
            clean_idx, contam_idx = [], list(range(len(idx)))
        else:
            clean_idx, contam_idx = list(range(len(idx))), []
        return {
            "clean_idx": clean_idx,
            "contaminated_idx": contam_idx,
            "wall_s": 0.0,
            "n_calls": 1,
            "split_occurred": False,
            "self_matches_excluded": 0,
            "non_self_matches_by_candidate": [[] for _ in idx],
            "raw": {"method": "scripted", "shards_scanned": 0, "windows_hashed": 0},
        }


def _patched_build_batch(**kwargs):
    with patch.object(mp, "cheap_shard_sizes", _fake_cheap_shard_sizes), \
         patch.object(mp, "_cumulative_token_offsets", _fake_cumulative_token_offsets), \
         patch.object(mp, "shard_manifest_for_window_count", _fake_shard_manifest_for_window_count), \
         patch.object(mp, "compute_n_windows_from_manifest", _fake_compute_n_windows), \
         patch.object(mp, "read_window_tokens", _fake_read_window_tokens), \
         patch.object(mp, "window_source_position", _fake_window_source_position), \
         patch.object(mp, "batch_sha256", lambda rows, seq: "deadbeef"):
        return mp.build_batch(**kwargs)


class TestPoolDownwardExtension(unittest.TestCase):

    def _run(self, tail_contaminated_floor):
        scripted = ScriptedClassify(tail_contaminated_floor)
        with patch.object(mp, "classify_candidates", scripted):
            result = _patched_build_batch(
                shard_dir="unused", seq=1, n_mtp=0,
                batch_size=BATCH_SIZE, ceiling_steps=CEILING_STEPS,
                train_batch=TRAIN_BATCH, pool_oversample=POOL_OVERSAMPLE,
                max_rounds=6, use_mp=False)
        return result, scripted

    def test_tail_exhausted_reaches_mid_corpus(self):
        """Round 1's tail pool (>=992) is fully contaminated; round 2 must
        extend DOWNWARD into disjoint mid-corpus space, never wrap past
        n_windows, and never dip at-or-below the training boundary."""
        result, scripted = self._run(tail_contaminated_floor=992)

        self.assertGreaterEqual(len(scripted.calls), 2)
        round1, round2 = scripted.calls[0], scripted.calls[1]

        self.assertEqual(min(round1), 992)
        self.assertEqual(max(round1), 999)

        # Round 2 is the contiguous slice immediately BELOW round 1 -- not
        # an empty pool, not wrapped past n_windows.
        self.assertLess(max(round2), min(round1))
        self.assertGreaterEqual(min(round2), DISJOINT_LOWER_BOUND)

        self.assertEqual(len(result["selected_rows"]), BATCH_SIZE)
        self.assertEqual(len(result["selected_window_indices"]), BATCH_SIZE)
        # The assembled batch must come from the disjoint range actually
        # examined (round 2's clean mid-corpus slice), not the tail.
        self.assertTrue(all(i < 992 for i in result["selected_window_indices"]))

    def test_downward_extension_is_deterministic(self):
        """Same inputs -> identical sequence of pool ranges across two
        independent runs (no RNG anywhere in the selection path)."""
        _, scripted_a = self._run(tail_contaminated_floor=992)
        _, scripted_b = self._run(tail_contaminated_floor=992)
        self.assertEqual(scripted_a.calls, scripted_b.calls)

    def test_exhaustion_only_when_disjoint_range_truly_consumed(self):
        """If EVERY window in the entire disjoint range [40, 1000) is
        contaminated, POOL_EXHAUSTED must fire only after the pool has
        marched all the way down to the boundary -- not on round 2."""
        scripted = ScriptedClassify(tail_contaminated_floor=0)  # everything contaminated
        with patch.object(mp, "classify_candidates", scripted):
            with self.assertRaises(SystemExit) as ctx:
                _patched_build_batch(
                    shard_dir="unused", seq=1, n_mtp=0,
                    batch_size=BATCH_SIZE, ceiling_steps=CEILING_STEPS,
                    train_batch=TRAIN_BATCH, pool_oversample=POOL_OVERSAMPLE,
                    max_rounds=200, use_mp=False)
        self.assertIn("W2_DECONTAM_POOL_EXHAUSTED", str(ctx.exception))

        # The lowest index ever drawn must equal the disjoint lower bound
        # exactly -- proof the full range was consumed, not abandoned early.
        lowest_drawn = min(min(c) for c in scripted.calls if c)
        self.assertEqual(lowest_drawn, DISJOINT_LOWER_BOUND)

        # And no round ever drew at-or-below the training boundary.
        for call in scripted.calls:
            if call:
                self.assertGreaterEqual(min(call), DISJOINT_LOWER_BOUND)

    def test_round1_pool_unchanged_tail_start(self):
        """Round 1 must still be the ORIGINAL tail pool established by
        reserve_pool -- this fix only changes what happens on replacement,
        not the initial pool."""
        result, scripted = self._run(tail_contaminated_floor=1_000_000)  # nothing contaminated
        # 2 calls expected: round 1 (satisfies batch_size alone) + the final
        # verification pass build_batch always runs on the selected rows.
        self.assertEqual(len(scripted.calls), 2)
        self.assertEqual(min(scripted.calls[0]), 992)
        self.assertEqual(max(scripted.calls[0]), 999)
        self.assertEqual(result["pool_reservation"]["pool_start"], 992)


if __name__ == "__main__":
    unittest.main()
