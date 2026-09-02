# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""test_packed_shard_loader_memmap.py -- regression coverage for the OPT-IN
memmap cache path added to timeshare_pretrain.PackedShardLoader (issue #118
P1 envelope sweep, coordinator ruling 2026-07-08): two ArrayMemoryError
tracebacks on the legacy np.concatenate path, at 17.5GB and 30.6GB free RAM,
banked in this lane's report to the coordinator -- a contiguous-address-
space/fragmentation ceiling, not a capacity one. The memmap path retires
that class for any caller that opts in via mmap_cache_dir; every other
caller (default mmap_cache_dir=None) must see byte-identical behavior to
before this change.

Uses tmp_path (pytest fixture) with a tiny synthetic multi-shard corpus --
no real corpus, no GPU, matches this repo's own fixture convention."""
import os
import sys

import numpy as np
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import timeshare_pretrain as tp


def _write_synthetic_shards(shard_dir, sizes, seed=42):
    os.makedirs(shard_dir, exist_ok=True)
    rng = np.random.RandomState(seed)
    for i, n in enumerate(sizes):
        arr = rng.randint(0, 32000, size=n).astype(tp.PACK_DTYPE)
        arr.tofile(os.path.join(shard_dir, f"v0-{i:05d}.bin"))


def test_memmap_path_default_none_is_untouched(tmp_path):
    """mmap_cache_dir omitted (None) must produce the EXACT same object
    shape/behavior as before this change -- regression on every existing
    caller (none of them pass the new kwarg)."""
    shard_dir = str(tmp_path / "shards")
    _write_synthetic_shards(shard_dir, [1000, 733, 1500])
    loader = tp.PackedShardLoader(shard_dir, seq=8, n_mtp=2)
    assert loader.mmap_cache_report is None
    assert isinstance(loader.stream, np.ndarray)
    assert not isinstance(loader.stream, np.memmap)


def test_memmap_matches_legacy_stream_byte_for_byte(tmp_path):
    """The memmap-backed stream must be byte-identical to what the legacy
    np.concatenate path produces for the SAME corpus -- the whole point of
    the swap is zero behavior change, only a different memory strategy."""
    shard_dir = str(tmp_path / "shards")
    _write_synthetic_shards(shard_dir, [1000, 733, 1500])
    cache_dir = str(tmp_path / "cache")

    legacy = tp.PackedShardLoader(shard_dir, seq=8, n_mtp=2)
    mm = tp.PackedShardLoader(shard_dir, seq=8, n_mtp=2, mmap_cache_dir=cache_dir)

    assert mm.n_tokens == legacy.n_tokens
    assert mm.n_windows == legacy.n_windows
    assert np.array_equal(np.asarray(mm.stream), legacy.stream)
    assert mm.mmap_cache_report["reused_existing_cache"] is False


def test_memmap_stream_is_write_protected(tmp_path):
    """mode='r' must make in-place mutation impossible -- the guard against
    silent stream corruption the coordinator's ruling required."""
    shard_dir = str(tmp_path / "shards")
    _write_synthetic_shards(shard_dir, [500, 500])
    cache_dir = str(tmp_path / "cache")
    mm = tp.PackedShardLoader(shard_dir, seq=4, n_mtp=1, mmap_cache_dir=cache_dir)
    with pytest.raises(ValueError):
        mm.stream[0] = 999


def test_memmap_cache_is_reused_on_second_open(tmp_path):
    """A second construction against the same shard_dir/cache_dir must reuse
    the on-disk cache (no rebuild) rather than re-streaming the corpus."""
    shard_dir = str(tmp_path / "shards")
    _write_synthetic_shards(shard_dir, [1000, 733, 1500])
    cache_dir = str(tmp_path / "cache")

    first = tp.PackedShardLoader(shard_dir, seq=8, n_mtp=2, mmap_cache_dir=cache_dir)
    assert first.mmap_cache_report["reused_existing_cache"] is False
    second = tp.PackedShardLoader(shard_dir, seq=8, n_mtp=2, mmap_cache_dir=cache_dir)
    assert second.mmap_cache_report["reused_existing_cache"] is True
    assert np.array_equal(np.asarray(second.stream), np.asarray(first.stream))


def test_memmap_refuses_lineage_mismatch(tmp_path):
    """expected_manifest_sha256, when given, must refuse loudly (SystemExit)
    rather than silently build/trust a cache against the wrong corpus."""
    shard_dir = str(tmp_path / "shards")
    _write_synthetic_shards(shard_dir, [500, 500])
    cache_dir = str(tmp_path / "cache")
    with pytest.raises(SystemExit, match="CORPUS_CACHE_LINEAGE_MISMATCH"):
        tp.PackedShardLoader(
            shard_dir, seq=4, n_mtp=1, mmap_cache_dir=cache_dir,
            expected_manifest_sha256="0" * 64)


def test_verify_memmap_stream_equivalence_passes_on_a_real_cache(tmp_path):
    """The equivalence check itself must pass (and cover every shard
    boundary) against a freshly-built cache."""
    shard_dir = str(tmp_path / "shards")
    _write_synthetic_shards(shard_dir, [1000, 733, 1500, 42])
    cache_dir = str(tmp_path / "cache")
    mm = tp.PackedShardLoader(shard_dir, seq=8, n_mtp=2, mmap_cache_dir=cache_dir)
    shards = sorted(p for p in os.listdir(shard_dir) if p.endswith(".bin"))
    report = tp.verify_memmap_stream_equivalence(
        mm.stream, shard_dir, shards, n_samples=16, window_tokens=8)
    assert report["verdict"] == "EQUIVALENT"
    assert report["mismatches"] == []
    assert report["n_shards_covered"] == 4


def test_verify_memmap_stream_equivalence_catches_a_real_mismatch(tmp_path):
    """The equivalence check must actually be able to FAIL -- pass it a
    stream that disagrees with the real shard files and confirm it raises,
    rather than being a check that can never trip."""
    shard_dir = str(tmp_path / "shards")
    _write_synthetic_shards(shard_dir, [500, 500])
    shards = sorted(p for p in os.listdir(shard_dir) if p.endswith(".bin"))
    # a deliberately WRONG stream (all zeros) must be caught as a mismatch
    wrong_stream = np.zeros(1000, dtype=tp.PACK_DTYPE)
    with pytest.raises(SystemExit, match="CORPUS_CACHE_EQUIVALENCE_MISMATCH"):
        tp.verify_memmap_stream_equivalence(
            wrong_stream, shard_dir, shards, n_samples=16, window_tokens=8)
