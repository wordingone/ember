"""test_w1b_fp32_check_mmap_forward.py -- regression coverage for issue
#575's w1b_fp32_check.py:72 site: run_paired_fp32_check's PackedShardLoader
construction (the real external-shard-mount eval loader) never forwarded
mmap_cache_dir, so every invocation silently rode the legacy
np.fromfile+np.concatenate path -- the same ArrayMemoryError/fragmentation
class #570/#573 fixed for run_v0_segment.

Exercises the REAL run_paired_fp32_check function end-to-end (never
reimplements it), over a real tiny multi-shard synthetic corpus through a
REAL PackedShardLoader -- the actual code under test. The heavy, unrelated
downstream collaborators (derive_real_arch_config, build_real_model,
checkpoint loading, eval_loss_fn, derive_continuation_arch,
load_continuation_checkpoint) are monkeypatched to trivial stand-ins:
building two real 20-layer transformers through the full real-arch
pipeline is unrelated to this parameter-forwarding fix and would make this
test heavy and fragile for no coverage gain (no existing test in this repo
exercises build_real_model/RealW1Model at all -- a pre-existing gap, not
one this PR introduces or is scoped to close).

Asserts on the observable, black-box side effect PR #573's own test used
(the on-disk memmap cache bin materializes iff the memmap branch engaged),
AND that the eval batch rebuilt through the loader
(rebuild_batch_from_decontam_receipt, left un-stubbed and running for real)
matches an independently precomputed sha256 -- proving the memmap-backed
loader is genuinely readable end-to-end, not merely that a file appeared."""
import json
import os
import sys

import numpy as np
import pytest
import torch

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import timeshare_pretrain as ts  # noqa: E402
from w1_collapse_control_run import sha256_tokens  # noqa: E402
import w1b_fp32_check as w1b  # noqa: E402

TINY_SEQ = 8
TINY_NMTP = 0


class _StubModel:
    """Trivial stand-in for RealW1Model -- supports exactly the two calls
    run_paired_fp32_check makes on a built model (load_state_dict, .to()),
    nothing else. See module docstring for why the real model isn't built."""

    def load_state_dict(self, state, strict=True):
        pass

    def to(self, *_a, **_k):
        return self


def _write_synthetic_shards(shard_dir, n_shards=3, tokens_per_shard=400, seed=42):
    os.makedirs(shard_dir, exist_ok=True)
    rng = np.random.RandomState(seed)
    for i in range(n_shards):
        toks = rng.randint(1, 64, size=tokens_per_shard).astype(np.int64)
        toks[::37] = 0  # plant <|endoftext|>=0 doc separators
        ts.write_packed_shard(os.path.join(shard_dir, f"v0-{i:05d}.bin"),
                              toks.astype(np.uint16).tolist())


def _make_decontam_receipt_fixture(shard_dir, tmpdir, window_indices=(0, 1)):
    """A real decontam receipt, internally consistent with the synthetic
    corpus above -- built against a REAL (legacy-path, mmap_cache_dir=None)
    reference loader over the same shards, sha256'd the identical way
    rebuild_batch_from_decontam_receipt itself recomputes it (never
    hand-invented)."""
    ref_loader = ts.PackedShardLoader(shard_dir, TINY_SEQ, TINY_NMTP)
    xs, ys = [], []
    for idx in window_indices:
        x_np, y_np, _y_mtp = ref_loader.window_np(idx)
        xs.append(x_np)
        ys.append(y_np)
    eval_x = torch.as_tensor(np.stack(xs), dtype=torch.long)
    eval_y = torch.as_tensor(np.stack(ys), dtype=torch.long)
    batch_sha = sha256_tokens(torch.cat([eval_x, eval_y], dim=1))
    receipt = {"selected_window_indices": list(window_indices), "batch_sha256": batch_sha}
    path = os.path.join(tmpdir, "decontam-receipt.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(receipt, f)
    return path, batch_sha


def _stub_heavy_collaborators(monkeypatch):
    """Stubs everything downstream of eval-loader construction -- unrelated
    to the mmap_cache_dir forwarding fix under test (see module docstring)."""
    monkeypatch.setattr(w1b, "derive_rung_receipt_from_manifest",
                        lambda manifest_path: {"stub": True})
    monkeypatch.setattr(w1b, "derive_real_arch_config",
                        lambda pricing, rung: {"seq": TINY_SEQ, "n_mtp": TINY_NMTP})
    monkeypatch.setattr(w1b, "build_real_model",
                        lambda real_arch, device, seed=None: _StubModel())
    monkeypatch.setattr(w1b, "load_checkpoint",
                        lambda ckpt_dir: ({}, None, None, {}))
    monkeypatch.setattr(w1b, "verify_checkpoint_key_shape_parity",
                        lambda state, model: None)
    monkeypatch.setattr(w1b, "derive_continuation_arch",
                        lambda ckpt_dir, real_arch: dict(real_arch))
    monkeypatch.setattr(w1b, "load_continuation_checkpoint",
                        lambda ckpt_dir, model: None)
    monkeypatch.setattr(w1b, "eval_loss_fn", lambda model, x, y: 0.5)


def _run(tmp_path, monkeypatch, *, mmap_kwargs):
    shard_dir = str(tmp_path / "shards")
    out_dir = str(tmp_path / "out")
    _write_synthetic_shards(shard_dir)
    decontam_path, expected_sha = _make_decontam_receipt_fixture(shard_dir, str(tmp_path))
    # pricing_receipt_path is read for real via load_json (only
    # derive_real_arch_config, which consumes its parsed contents, is
    # stubbed) -- must exist as valid JSON, contents unused.
    pricing_path = os.path.join(str(tmp_path), "fake-pricing.json")
    with open(pricing_path, "w", encoding="utf-8") as f:
        json.dump({}, f)
    _stub_heavy_collaborators(monkeypatch)

    result = w1b.run_paired_fp32_check(
        repo_root=str(tmp_path),
        shard_dir=shard_dir,
        decontam_receipt_path=decontam_path,
        rung_manifest=str(tmp_path / "fake-manifest.json"),  # stubbed reader never opens this
        seed_checkpoint_dir=str(tmp_path / "fake-seed-ckpt"),  # stubbed reader never opens this
        grown_checkpoint_dir=str(tmp_path / "fake-grown-ckpt"),  # stubbed reader never opens this
        pricing_receipt_path=pricing_path,
        expected_batch_sha=expected_sha,
        device="cpu",
        out_dir=out_dir,
        **mmap_kwargs,
    )
    return result, out_dir


def test_explicit_mmap_cache_dir_engages_memmap(tmp_path, monkeypatch):
    """AC2: mmap_cache_dir set -> the memmap branch engages through
    run_paired_fp32_check's own construction site, over a 3-shard corpus
    that would otherwise hit np.concatenate."""
    cache_dir = str(tmp_path / "cache")
    result, _out_dir = _run(tmp_path, monkeypatch, mmap_kwargs={"mmap_cache_dir": cache_dir})

    assert result["certified_batch_check"]["matches_expected"] is True
    cache_bin = os.path.join(cache_dir, ts.CORPUS_CACHE_BIN_NAME)
    assert os.path.exists(cache_bin), (
        "mmap cache bin absent -- run_paired_fp32_check did not forward "
        "mmap_cache_dir through to PackedShardLoader (the #575 defect)")


def test_default_mmap_cache_dir_engages_memmap_under_out_dir(tmp_path, monkeypatch):
    """AC1: mmap_cache_dir OMITTED entirely -> the sane default is a cache
    dir under out_dir, and the memmap branch engages automatically -- the
    actual fix for the CLI's real invocation, which never passes this
    parameter at all (the #575 bug report's exact scenario)."""
    result, out_dir = _run(tmp_path, monkeypatch, mmap_kwargs={})

    assert result["certified_batch_check"]["matches_expected"] is True
    default_cache_bin = os.path.join(out_dir, "mmap_cache", ts.CORPUS_CACHE_BIN_NAME)
    assert os.path.exists(default_cache_bin), (
        "default mmap cache absent under out_dir -- run_paired_fp32_check's "
        "sane default did not engage the memmap path")


def test_explicit_none_preserves_legacy_path(tmp_path, monkeypatch):
    """Explicit None must still opt OUT -- byte-identical legacy behavior
    for any caller that wants it, no cache written anywhere."""
    result, out_dir = _run(tmp_path, monkeypatch, mmap_kwargs={"mmap_cache_dir": None})

    assert result["certified_batch_check"]["matches_expected"] is True
    assert not os.path.exists(os.path.join(out_dir, "mmap_cache"))


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
