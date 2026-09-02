"""test_exposure_ledger_mmap_forward.py -- regression coverage for issue
#575's exposure_ledger.py:93 site: ExposureLedgerBuilder.__init__'s
PackedShardLoader construction never forwarded mmap_cache_dir, so every
real per-shard exposure/rung-consumption replay (this tool's actual
purpose) silently rode the legacy np.fromfile+np.concatenate path -- the
same ArrayMemoryError/fragmentation class #570/#573 fixed for
run_v0_segment.

Builds the loader THROUGH ExposureLedgerBuilder's own construction site
(never PackedShardLoader directly -- test_packed_shard_loader_memmap.py
already covers the loader in isolation), against a tiny MULTI-shard
synthetic corpus (a single shard never reaches np.concatenate, so >1 shard
is needed to make legacy-vs-memmap an actual behavioral fork). Asserts on
the observable, black-box side effect PR #573's own test used: the on-disk
memmap cache bin materializes iff the memmap branch engaged."""
import os
import sys

import numpy as np
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_DIR = os.path.dirname(HERE)
for _p in (SCRIPTS_DIR, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import timeshare_pretrain as ts  # noqa: E402
import exposure_ledger as el  # noqa: E402

TINY_SEQ = 8
TINY_NMTP = 0


def _write_synthetic_shards(shard_dir, n_shards=3, tokens_per_shard=400, seed=42):
    os.makedirs(shard_dir, exist_ok=True)
    rng = np.random.RandomState(seed)
    for i in range(n_shards):
        toks = rng.randint(1, 64, size=tokens_per_shard).astype(np.int64)
        toks[::37] = 0  # plant <|endoftext|>=0 doc separators
        ts.write_packed_shard(os.path.join(shard_dir, f"v0-{i:05d}.bin"),
                              toks.astype(np.uint16).tolist())


def test_explicit_mmap_cache_dir_engages_memmap_through_builder(tmp_path):
    """AC2: mmap_cache_dir set -> the memmap branch engages (the cache bin
    materializes) via ExposureLedgerBuilder's own construction site, over a
    3-shard corpus that would otherwise hit np.concatenate."""
    shard_dir = str(tmp_path / "shards")
    cache_dir = str(tmp_path / "cache")
    _write_synthetic_shards(shard_dir)

    builder = el.ExposureLedgerBuilder(shard_dir=shard_dir, seq=TINY_SEQ,
                                       n_mtp=TINY_NMTP, mmap_cache_dir=cache_dir)

    assert builder.loader is not None
    cache_bin = os.path.join(cache_dir, ts.CORPUS_CACHE_BIN_NAME)
    assert os.path.exists(cache_bin), (
        "mmap cache bin absent -- ExposureLedgerBuilder did not forward "
        "mmap_cache_dir through to PackedShardLoader (the #575 defect)")


def test_default_mmap_cache_dir_engages_memmap_under_default_output_dir(tmp_path, monkeypatch):
    """AC1: mmap_cache_dir OMITTED entirely -> the sane default is
    `<_DEFAULT_OUTPUT_DIR>/mmap_cache` relative to CWD, and the memmap
    branch engages automatically -- the fix for any direct
    ExposureLedgerBuilder construction that passes nothing."""
    shard_dir = str(tmp_path / "shards")
    _write_synthetic_shards(shard_dir)
    monkeypatch.chdir(tmp_path)

    builder = el.ExposureLedgerBuilder(shard_dir=shard_dir, seq=TINY_SEQ, n_mtp=TINY_NMTP)

    default_cache_bin = os.path.join(el._DEFAULT_OUTPUT_DIR, "mmap_cache",
                                     ts.CORPUS_CACHE_BIN_NAME)
    assert os.path.exists(default_cache_bin), (
        "default mmap cache absent under _DEFAULT_OUTPUT_DIR -- "
        "ExposureLedgerBuilder's sane default did not engage the memmap path")


def test_explicit_none_preserves_legacy_path(tmp_path):
    """Explicit None must still opt OUT -- byte-identical legacy behavior
    for any caller that wants it, no cache written anywhere."""
    shard_dir = str(tmp_path / "shards")
    _write_synthetic_shards(shard_dir)

    builder = el.ExposureLedgerBuilder(shard_dir=shard_dir, seq=TINY_SEQ,
                                       n_mtp=TINY_NMTP, mmap_cache_dir=None)

    assert builder.loader is not None
    assert builder.loader.mmap_cache_report is None


def test_main_cli_wires_mmap_cache_dir_under_custom_output_dir(tmp_path, monkeypatch):
    """The literal #575 CLI-wiring regression: main()'s real-reconstruction
    call site must pass mmap_cache_dir under THIS invocation's own
    --output-dir (not always the constructor's generic default), so a
    custom --output-dir is honored precisely."""
    shard_dir = str(tmp_path / "shards")
    output_dir = str(tmp_path / "custom-output")
    _write_synthetic_shards(shard_dir)

    argv_backup = sys.argv
    try:
        sys.argv = ["exposure_ledger.py", "--shard-dir", shard_dir,
                   "--seq", str(TINY_SEQ), "--n-mtp", str(TINY_NMTP),
                   "--step-start", "0", "--step-end", "2", "--batch-size", "1",
                   "--output-dir", output_dir]
        rc = el.main()
    finally:
        sys.argv = argv_backup

    assert rc == 0
    cache_bin = os.path.join(output_dir, "mmap_cache", ts.CORPUS_CACHE_BIN_NAME)
    assert os.path.exists(cache_bin), (
        "main() did not wire mmap_cache_dir under the CLI's own --output-dir")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
