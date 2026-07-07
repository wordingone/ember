"""test_w1_live_gates.py -- hermetic regression tests for issue #121's two
spec-compliance additions to scripts/w1_collapse_control_run.py:

  Defect A: refuse_if_contaminated() -- the live launch must hard-refuse when
    this run's own fresh contamination_recheck() finds any confirmed match
    (previously computed and disclosed, never gated).
  Defect B: rebuild_batch_from_decontam_receipt() -- an external
    w2-heldout-decontam/v1 receipt's own selected_window_indices drive which
    windows are held out, with the rebuilt batch's sha256 asserted against
    the receipt's pinned batch_sha256, fail-closed on mismatch.

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


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
