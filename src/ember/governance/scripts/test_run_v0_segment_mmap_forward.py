# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""test_run_v0_segment_mmap_forward.py -- regression coverage for issue #570:
run_v0_segment's hardcoded `PackedShardLoader(shard_dir, seq, n_mtp)`
construction never forwarded mmap_cache_dir, so every run_v0_segment caller
silently rode the legacy np.fromfile + np.concatenate path (the #118 P1
sweep ArrayMemoryError class -- two contiguous-13GiB-allocation crashes
banked at 17.5GB and 30.6GB free RAM) no matter what it configured.

Builds the loader THROUGH run_v0_segment's own dry-run path (never
constructs PackedShardLoader directly -- test_packed_shard_loader_memmap.py
already covers the loader in isolation) and asserts on the observable,
black-box side effect of which branch engaged: the on-disk memmap cache
file materializes iff the memmap branch ran, which is exactly "the memmap
branch engaged / no N-shard concatenate" from the caller's point of view.

Uses tmp_path (pytest fixture), a tiny MULTI-shard synthetic corpus (a
single shard never reaches np.concatenate at all, so >1 shard is needed to
make legacy-vs-memmap an actual behavioral fork), and the tiny stand-in
model (live=False, real_arch=None) -- CPU-only, no GPU, matches this
repo's own fixture convention (test_packed_shard_loader_memmap.py,
_selftest_v0ext's dry-run block)."""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import timeshare_pretrain as ts

TINY_DIMS = {"vocab": 64, "hidden": 32, "depth": 2, "seq": 8}


def _write_synthetic_shards(shard_dir, n_shards=3, tokens_per_shard=400, seed=42):
    os.makedirs(shard_dir, exist_ok=True)
    rng = np.random.RandomState(seed)
    for i in range(n_shards):
        toks = rng.randint(1, 64, size=tokens_per_shard).astype(np.int64)
        toks[::37] = 0  # plant <|endoftext|>=0 doc separators
        ts.write_packed_shard(os.path.join(shard_dir, f"v0-{i:05d}.bin"),
                              toks.astype(np.uint16).tolist())


def _run(run_dir, shard_dir, **kwargs):
    cfg = ts.load_contract()
    return ts.run_v0_segment(
        run_dir, cfg, n_steps=1, total_steps=1, pace_s=0.0,
        shard_dir=shard_dir, tiny_dims=TINY_DIMS, batch_size=2,
        ce_chunk_tokens=8, segment_id="issue-570-regression",
        **kwargs)


def test_explicit_mmap_cache_dir_engages_memmap_through_run_v0_segment(tmp_path):
    """AC2: mmap_cache_dir set -> the memmap branch engages (the cache bin
    materializes) via run_v0_segment's own construction site, over a
    3-shard corpus that would otherwise hit np.concatenate."""
    run_dir = str(tmp_path / "run")
    shard_dir = str(tmp_path / "shards")
    cache_dir = str(tmp_path / "cache")
    _write_synthetic_shards(shard_dir)

    receipt = _run(run_dir, shard_dir, mmap_cache_dir=cache_dir)

    assert receipt["pass"] is True
    cache_bin = os.path.join(cache_dir, ts.CORPUS_CACHE_BIN_NAME)
    assert os.path.exists(cache_bin), (
        "mmap cache bin absent -- run_v0_segment did not forward "
        "mmap_cache_dir through to PackedShardLoader (the #570 defect)")


def test_default_mmap_cache_dir_engages_memmap_under_run_dir(tmp_path):
    """AC1: mmap_cache_dir OMITTED entirely -> the sane default is a cache
    dir under run_dir, and the memmap branch engages automatically -- the
    actual fix for every existing run_v0_segment caller that passes
    nothing (the #570 bug report's exact scenario)."""
    run_dir = str(tmp_path / "run")
    shard_dir = str(tmp_path / "shards")
    _write_synthetic_shards(shard_dir)

    receipt = _run(run_dir, shard_dir)  # mmap_cache_dir not passed at all

    assert receipt["pass"] is True
    default_cache_bin = os.path.join(run_dir, "mmap_cache", ts.CORPUS_CACHE_BIN_NAME)
    assert os.path.exists(default_cache_bin), (
        "default mmap cache absent under run_dir -- run_v0_segment's sane "
        "default did not engage the memmap path")


def test_explicit_none_preserves_legacy_path(tmp_path):
    """Explicit None must still opt OUT -- byte-identical legacy behavior
    for any caller that wants it, no cache written anywhere."""
    run_dir = str(tmp_path / "run")
    shard_dir = str(tmp_path / "shards")
    _write_synthetic_shards(shard_dir)

    receipt = _run(run_dir, shard_dir, mmap_cache_dir=None)

    assert receipt["pass"] is True
    assert not os.path.exists(os.path.join(run_dir, "mmap_cache"))
