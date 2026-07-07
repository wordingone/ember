"""test_w1_live_gates.py -- hermetic regression tests for issue #121's two
spec-compliance additions to scripts/w1_collapse_control_run.py:

  Defect A: refuse_if_contaminated() -- the live launch must hard-refuse when
    this run's own fresh contamination_recheck() finds any confirmed match
    (previously computed and disclosed, never gated).
  Defect B: rebuild_batch_from_decontam_receipt() -- an external
    w2-heldout-decontam/v1 receipt's own selected_window_indices drive which
    windows are held out, with the rebuilt batch's sha256 asserted against
    the receipt's pinned batch_sha256, fail-closed on mismatch.

Plus (2026-07-07, real-launch refusal fork-A fix): classify_contamination_
self_matches() / refuse_if_non_self_contaminated() -- a held-out batch's own
true source windows will ALWAYS match themselves when contamination_recheck()
scans the real corpus (they were drawn from it); refuse_if_contaminated
cannot tell that apart from a genuine foreign duplicate. The new gate must
still refuse on a genuine foreign duplicate.

Real code under test (imported, never reimplemented), synthetic-only data
(tempfile.TemporaryDirectory() per case, a tiny made-up token stream) -- same
convention as scripts/w2_heldout/test_launch_gate.py. No real corpus or real
receipt is touched.
"""
from __future__ import annotations

import os
import sys
import tempfile

import numpy as np
import pytest
import torch

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from w1_collapse_control_run import (  # noqa: E402
    refuse_if_contaminated,
    rebuild_batch_from_decontam_receipt,
    derive_rung_receipt_from_manifest,
    sha256_tokens,
    contamination_recheck,
    classify_contamination_self_matches,
    refuse_if_non_self_contaminated,
)
from timeshare_pretrain import PackedShardLoader  # noqa: E402


SEQ = 8
N_MTP = 1


def _make_shard_dir(tmpdir: str, n_tokens: int = 400) -> str:
    """Writes one tiny synthetic .bin shard (uint16 tokens 0..n_tokens-1,
    deterministic, never touching any real corpus) and returns its dir."""
    shard_dir = os.path.join(tmpdir, "shards")
    os.makedirs(shard_dir, exist_ok=True)
    tokens = np.arange(n_tokens, dtype="<u2") % 997  # keep values small/varied
    tokens.tofile(os.path.join(shard_dir, "shard-0000.bin"))
    return shard_dir


def _batch_sha_for_indices(loader: PackedShardLoader, indices: list[int]) -> str:
    """Ground truth: the SAME convention rebuild_batch_from_decontam_receipt
    itself uses (sha256_tokens over concat([x, y], dim=1)) -- computed here
    independently, directly from the loader, to build a CORRECT receipt for
    the green-path test."""
    xs, ys = [], []
    for idx in indices:
        x_np, y_np, _y_mtp = loader.window_np(idx)
        xs.append(x_np)
        ys.append(y_np)
    eval_x = torch.as_tensor(np.stack(xs), dtype=torch.long)
    eval_y = torch.as_tensor(np.stack(ys), dtype=torch.long)
    return sha256_tokens(torch.cat([eval_x, eval_y], dim=1))


# ---------------------------------------------------------------------------
# Test 1 (Defect A): CONTAMINATED verdict -> refuses; CLEAN -> does not.
# ---------------------------------------------------------------------------

def test_contaminated_verdict_refuses():
    contaminated = {
        "verdict": "CONTAMINATED",
        "confirmed_matches": [{"shard": "shard-0000.bin", "offset": 3, "window": [1, 2, 3]}],
    }
    with pytest.raises(SystemExit, match="W1_LIVE_CONTAMINATION_REFUSED"):
        refuse_if_contaminated(contaminated)


def test_clean_verdict_does_not_refuse():
    clean = {"verdict": "CLEAN", "confirmed_matches": []}
    refuse_if_contaminated(clean)  # must not raise


# ---------------------------------------------------------------------------
# Test 2 (Defect B, RED): a receipt whose pinned batch_sha256 does not match
# the rebuilt batch (tampered/stale/wrong-shard-dir) -> refuses.
# ---------------------------------------------------------------------------

def test_sha_mismatch_refuses():
    with tempfile.TemporaryDirectory() as tmpdir:
        shard_dir = _make_shard_dir(tmpdir)
        loader = PackedShardLoader(shard_dir, SEQ, n_mtp=N_MTP)

        receipt = {
            "selected_window_indices": [0, 2, 5],
            "batch_sha256": "deadbeef" * 8,  # deliberately wrong (64 hex chars)
        }
        with pytest.raises(SystemExit, match="W1_LIVE_DECONTAM_BATCH_SHA_MISMATCH"):
            rebuild_batch_from_decontam_receipt(loader, receipt, "cpu")


# ---------------------------------------------------------------------------
# Test 3 (Defect B, GREEN): a correctly-pinned receipt is accepted, and the
# rebuilt batch corresponds EXACTLY to the receipt's selected_window_indices
# -- not silently substituted with the script's internal "last N windows"
# convention.
# ---------------------------------------------------------------------------

def test_certified_receipt_selected_windows_match_indices_exactly():
    with tempfile.TemporaryDirectory() as tmpdir:
        shard_dir = _make_shard_dir(tmpdir)
        loader = PackedShardLoader(shard_dir, SEQ, n_mtp=N_MTP)

        indices = [1, 3, 4]  # deliberately non-contiguous, deliberately NOT
                              # "the last batch-many windows" of the stream
        correct_sha = _batch_sha_for_indices(loader, indices)
        receipt = {"selected_window_indices": indices, "batch_sha256": correct_sha}

        eval_x, eval_y, eval_sha = rebuild_batch_from_decontam_receipt(
            loader, receipt, "cpu")

        assert eval_sha == correct_sha

        for row, idx in enumerate(indices):
            expected_x, expected_y, _ = loader.window_np(idx)
            assert torch.equal(eval_x[row], torch.as_tensor(expected_x, dtype=torch.long))
            assert torch.equal(eval_y[row], torch.as_tensor(expected_y, dtype=torch.long))

        # Negative control: NOT equal to the internal "last batch-many
        # windows" convention this test deliberately avoided.
        last_n_x, _last_n_y, _ = loader.window_np(loader.n_windows - len(indices))
        assert not torch.equal(eval_x[0], torch.as_tensor(last_n_x, dtype=torch.long))


# ---------------------------------------------------------------------------
# Test 4 (item 7): derive_rung_receipt_from_manifest -- reads ff_grown from a
# real per-checkpoint manifest.json, derives vocab/hidden from the actual
# model.pt embedding tensor shape, and discloses (never fabricates) the
# fields a checkpoint manifest cannot carry (params_unique_after,
# params_state_dict_sum_after, tok_s_paced).
# ---------------------------------------------------------------------------

def test_derive_rung_receipt_from_manifest():
    with tempfile.TemporaryDirectory() as tmpdir:
        ckpt_dir = os.path.join(tmpdir, "step-00000001")
        os.makedirs(ckpt_dir, exist_ok=True)
        vocab, hidden = 37, 11
        state = {"model.embed_tokens.weight": torch.zeros(vocab, hidden)}
        torch.save(state, os.path.join(ckpt_dir, "model.pt"))
        manifest_path = os.path.join(ckpt_dir, "manifest.json")
        with open(manifest_path, "w", encoding="utf-8") as f:
            import json
            json.dump({"step": 1, "extra": {"ff_grown": 4096}}, f)

        rung_receipt = derive_rung_receipt_from_manifest(manifest_path)

        assert rung_receipt["ff_grown"] == 4096
        assert rung_receipt["params_dedup"]["measured_duplicate_numel"] == vocab * hidden
        assert rung_receipt["params_unique_after"] is None
        assert rung_receipt["params_state_dict_sum_after"] is None
        assert rung_receipt["stabilization_segment"]["tok_s_paced"] is None
        assert rung_receipt["stabilization_segment"]["checkpoint"] == ckpt_dir
        assert "unavailable" in rung_receipt["_derivation"]["params_unique_after"]


# ---------------------------------------------------------------------------
# Tests 5-7 (2026-07-07 real-launch refusal, fork-A fix): a held-out batch's
# own true source windows will ALWAYS match themselves when
# contamination_recheck() scans the real corpus -- classify_contamination_
# self_matches must exclude those (matching build_decontam_batch_mp.py's
# is_self convention) while STILL refusing on a genuine foreign duplicate.
# window=13 (CONTAMINATION_WINDOW_TOKENS) needs row length (seq+1) >= 13, so
# these tests use a wider SEQ2 than the SEQ=8 fixture above.
# ---------------------------------------------------------------------------

SEQ2 = 16
N_MTP2 = 1


def _eval_rows_for_indices(loader: PackedShardLoader, indices: list[int]) -> list[list[int]]:
    rows = []
    for idx in indices:
        x_np, y_np, _y_mtp = loader.window_np(idx)
        rows.append(list(x_np) + [int(y_np[-1])])
    return rows


def test_self_match_only_refuses_raw_but_passes_classified():
    """The exact class of the 2026-07-07 refusal: a batch drawn from windows
    that ARE part of the corpus (unavoidable -- that's what 'held out'
    means) must refuse on the RAW gate (reproducing the bug) but PASS on the
    self-exclusion-aware gate (the fix)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        shard_dir = os.path.join(tmpdir, "shards")
        os.makedirs(shard_dir, exist_ok=True)
        # Unique-valued stream (no modulo) so no incidental 13-gram repeats
        # anywhere else in the corpus can confound this test's assumptions.
        n_tokens = 2000
        tokens = np.arange(n_tokens, dtype="<u2")
        tokens.tofile(os.path.join(shard_dir, "shard-0000.bin"))
        loader = PackedShardLoader(shard_dir, SEQ2, n_mtp=N_MTP2)

        candidate_indices = [5, 20, 40]  # disjoint from each other and small
        eval_rows = _eval_rows_for_indices(loader, candidate_indices)

        contamination = contamination_recheck(eval_rows, shard_dir)
        assert contamination["verdict"] == "CONTAMINATED"
        assert len(contamination["confirmed_matches"]) > 0
        with pytest.raises(SystemExit, match="W1_LIVE_CONTAMINATION_REFUSED"):
            refuse_if_contaminated(contamination)  # reproduces the 2026-07-07 bug

        classified = classify_contamination_self_matches(
            contamination, candidate_indices,
            seq=SEQ2, n_mtp=N_MTP2, shard_dir=shard_dir)
        assert classified["verdict"] == "CLEAN"
        assert classified["confirmed_non_self_matches"] == []
        assert classified["self_matches_excluded"] == len(contamination["confirmed_matches"])
        refuse_if_non_self_contaminated(classified)  # must NOT raise


def test_genuine_foreign_duplicate_still_refuses():
    """A candidate window whose token sequence ALSO appears somewhere else
    in the corpus (not at its own location) is real contamination -- the
    self-exclusion fix must not neuter this."""
    with tempfile.TemporaryDirectory() as tmpdir:
        shard_dir = os.path.join(tmpdir, "shards")
        os.makedirs(shard_dir, exist_ok=True)
        n_tokens = 3000
        tokens = np.arange(n_tokens, dtype="<u2")
        block_len = SEQ2 + 1 + N_MTP2  # 18

        candidate_idx = 5  # window covers tokens [5*16, 5*16+18) = [80, 98)
        foreign_copy_start = 2000  # far away, no overlap with any candidate
        tokens[foreign_copy_start:foreign_copy_start + block_len] = \
            tokens[candidate_idx * SEQ2: candidate_idx * SEQ2 + block_len]
        tokens.tofile(os.path.join(shard_dir, "shard-0000.bin"))

        loader = PackedShardLoader(shard_dir, SEQ2, n_mtp=N_MTP2)
        eval_rows = _eval_rows_for_indices(loader, [candidate_idx])

        contamination = contamination_recheck(eval_rows, shard_dir)
        classified = classify_contamination_self_matches(
            contamination, [candidate_idx],
            seq=SEQ2, n_mtp=N_MTP2, shard_dir=shard_dir)

        assert classified["verdict"] == "CONTAMINATED"
        assert len(classified["confirmed_non_self_matches"]) > 0
        # The candidate's OWN home-location matches are still excluded --
        # only the foreign copy's matches remain.
        assert classified["self_matches_excluded"] > 0
        with pytest.raises(SystemExit, match="W1_LIVE_CONTAMINATION_REFUSED"):
            refuse_if_non_self_contaminated(classified)


def test_boundary_match_global_start_conversion():
    """A confirmed match reported in 'boundary' form (a hit spanning two
    shard files, as contamination_recheck's join-array branch produces) must
    convert to the correct global position too, not just the plain 'shard'
    form -- otherwise a real cross-shard-boundary contamination would be
    silently misclassified as self (or vice versa)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        shard_dir = os.path.join(tmpdir, "shards")
        os.makedirs(shard_dir, exist_ok=True)
        # Two shards; candidate lives entirely in shard 0, nowhere near the
        # boundary -- so a fabricated 'boundary' match must be classified
        # non-self (it cannot overlap the candidate's true range).
        shard0 = np.arange(0, 100, dtype="<u2")
        shard1 = np.arange(100, 200, dtype="<u2")
        shard0.tofile(os.path.join(shard_dir, "shard-0000.bin"))
        shard1.tofile(os.path.join(shard_dir, "shard-0001.bin"))

        candidate_idx = 1  # tokens [16, 34) -- nowhere near the shard0|shard1 join
        contamination = {
            "confirmed_matches": [
                {"boundary": "shard-0000.bin|shard-0001.bin", "offset_in_join": 0,
                 "window": list(range(13))},
            ],
        }
        classified = classify_contamination_self_matches(
            contamination, [candidate_idx],
            seq=SEQ2, n_mtp=N_MTP2, shard_dir=shard_dir)
        assert classified["verdict"] == "CONTAMINATED"
        assert classified["self_matches_excluded"] == 0
        assert len(classified["confirmed_non_self_matches"]) == 1


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
