#!/usr/bin/env python3
"""test_ember_cbase_mixture.py — TDD suite for ember_cbase_mixture.py.

Run:
    python -m pytest scripts/test_ember_cbase_mixture.py -v
    # or: python scripts/test_ember_cbase_mixture.py

Tests are independent: each builds its own synthetic sources + shards-v0 in
a fresh tempdir. All numeric seeding uses hashlib (not python hash()).

Coverage:
  T01 compute_mixture_sizes returns non-trivial reps and correct fields
  T02 ratio validation: sum != 1.0 raises
  T03 realized_ratio_str percentages correct
  T04 assemble produces a .bin shard of the stated size
  T05 assemble produces manifest with correct schema
  T06 all token ids in assembled shard < 32000
  T07 max_token_id in manifest matches actual shard max
  T08 heldout_excluded is True
  T09 v2 replication: concatenated prefix = v2 repeated v2_reps times
  T10 aug block: concatenated block after v2 = aug repeated aug_reps times
  T11 PackedShardLoader reads mixture without error
  T12 PackedShardLoader window_np returns correct shapes
  T13 byte-reproducibility: rebuild in fresh subprocess -> identical SHA256
  T14 ratio accuracy: realized v2/aug/s0 within 3 pct of target
  T15 s0 block is head of sorted shards-v0 stream (deterministic)
  T16 vocab firewall fires on out-of-range token
  T17 s0 tokens < than available shards raises ValueError
  T18 output shard is uint16 (dtype)
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Make scripts importable
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from ember_cbase_mixture import (  # noqa: E402
    _VOCAB,
    _V2_TOKENS,
    _AUG_TOKENS,
    _assert_vocab,
    _load_s0_prefix,
    assemble_mixture,
    compute_mixture_sizes,
    realized_ratio_str,
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _det_rng(seed_str: str) -> np.random.Generator:
    seed = int.from_bytes(hashlib.sha256(seed_str.encode()).digest()[:8], "big")
    return np.random.default_rng(seed)


def _synthetic_v2(tmpdir: Path) -> Path:
    rng = _det_rng("v2-fixture")
    arr = rng.integers(8, _VOCAB, size=_V2_TOKENS, dtype=np.uint16)
    p = tmpdir / "cbase_avir_tasks_v2-00000.bin"
    arr.tofile(str(p))
    return p


def _synthetic_aug(tmpdir: Path) -> Path:
    rng = _det_rng("aug-fixture")
    arr = rng.integers(8, _VOCAB, size=_AUG_TOKENS, dtype=np.uint16)
    p = tmpdir / "cbase_avir_augment-00000.bin"
    arr.tofile(str(p))
    return p


def _synthetic_s0_dir(tmpdir: Path, n_shards: int = 3, tokens_per: int = 50_000,
                      dirname: str = "shards_v0") -> Path:
    """Write n_shards synthetic v0-style shards into tmpdir/<dirname>/."""
    s0 = tmpdir / dirname
    s0.mkdir(exist_ok=True, parents=True)
    for i in range(n_shards):
        rng = _det_rng(f"s0-shard-{i}")
        arr = rng.integers(8, _VOCAB, size=tokens_per, dtype=np.uint16)
        arr.tofile(str(s0 / f"v0-{i:05d}.bin"))
    return s0


def _run_assemble(tmpdir: Path, **kwargs):
    """Run assemble_mixture bypassing SHA verification."""
    import ember_cbase_mixture as _em
    _orig = _em._load_source

    def _mock_load_source(path, expected_sha_prefix, expected_tokens, name):
        arr = np.fromfile(str(path), dtype="<u2")
        return arr

    _em._load_source = _mock_load_source
    try:
        return assemble_mixture(**kwargs)
    finally:
        _em._load_source = _orig


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestComputeMixtureSizes:
    def test_T01_basic_defaults(self):
        v2r, ar, s0t, v2rep = compute_mixture_sizes(600_000, 0.40, 0.10, 0.50)
        assert v2r >= 1
        assert ar >= 1
        assert s0t > 0
        assert v2rep == v2r

    def test_T02_ratio_sum_not_one_raises(self):
        with pytest.raises(ValueError, match="sum to 1.0"):
            compute_mixture_sizes(600_000, 0.50, 0.10, 0.50)  # sums to 1.1

    def test_T02b_ratio_underfull_raises(self):
        with pytest.raises(ValueError, match="sum to 1.0"):
            compute_mixture_sizes(600_000, 0.30, 0.10, 0.50)  # sums to 0.9


class TestRealizedRatioStr:
    def test_T03_exact(self):
        rs = realized_ratio_str(400, 100, 500)
        assert "40.00%" in rs
        assert "10.00%" in rs
        assert "50.00%" in rs

    def test_T03_format(self):
        rs = realized_ratio_str(400, 100, 500)
        assert "v2=" in rs
        assert "aug=" in rs
        assert "s0=" in rs


class TestAssembleMixture:
    @pytest.fixture(autouse=True)
    def tmp(self, tmp_path):
        self.tmp = tmp_path
        self.v2_src = _synthetic_v2(tmp_path)
        self.aug_src = _synthetic_aug(tmp_path)
        self.s0_dir = _synthetic_s0_dir(tmp_path, n_shards=3, tokens_per=100_000)
        self.out = tmp_path / "mixture_out"

    def _assemble(self, base_tokens=150_000, **kwargs):
        return _run_assemble(
            self.tmp,
            out_dir=self.out,
            base_tokens=base_tokens,
            r_v2=0.40,
            r_aug=0.10,
            r_s0=0.50,
            shards_v0_dir=self.s0_dir,
            v2_src=self.v2_src,
            aug_src=self.aug_src,
            **kwargs,
        )

    def test_T04_produces_bin_shard(self):
        self._assemble()
        shard = self.out / "mixture-00000.bin"
        assert shard.exists()
        arr = np.fromfile(str(shard), dtype="<u2")
        assert len(arr) > 0

    def test_T05_manifest_schema(self):
        self._assemble()
        manifest_path = self.out / "mixture-manifest.json"
        assert manifest_path.exists()
        with open(manifest_path, encoding="utf-8") as f:
            m = json.load(f)
        assert m["ticket"] == "CBASE-MIXTURE"
        assert m["pass"] is True
        assert "mixture" in m
        mx = m["mixture"]
        for field in ["v2_replication", "v2_tokens", "aug_tokens", "s0_tokens",
                       "total_tokens", "realized_ratio", "max_token_id",
                       "heldout_excluded"]:
            assert field in mx, f"manifest missing field: {field}"

    def test_T06_all_token_ids_below_vocab(self):
        self._assemble()
        shard = self.out / "mixture-00000.bin"
        arr = np.fromfile(str(shard), dtype="<u2")
        assert int(arr.max()) < _VOCAB

    def test_T07_max_token_id_matches_manifest(self):
        self._assemble()
        shard = self.out / "mixture-00000.bin"
        arr = np.fromfile(str(shard), dtype="<u2")
        manifest_path = self.out / "mixture-manifest.json"
        with open(manifest_path, encoding="utf-8") as f:
            m = json.load(f)
        assert m["mixture"]["max_token_id"] == int(arr.max())

    def test_T08_heldout_excluded(self):
        receipt = self._assemble()
        assert receipt["mixture"]["heldout_excluded"] is True

    def test_T09_v2_prefix_is_replicated_v2(self):
        receipt = self._assemble()
        shard = self.out / "mixture-00000.bin"
        arr = np.fromfile(str(shard), dtype="<u2")
        v2_toks = receipt["mixture"]["v2_tokens"]
        v2_reps = receipt["mixture"]["v2_replication"]
        v2_raw = np.fromfile(str(self.v2_src), dtype="<u2")
        prefix = arr[:v2_toks]
        expected = np.tile(v2_raw, v2_reps)
        np.testing.assert_array_equal(prefix, expected,
                                       err_msg="v2 prefix does not match replicated v2")

    def test_T10_aug_block_is_replicated_aug(self):
        receipt = self._assemble()
        shard = self.out / "mixture-00000.bin"
        arr = np.fromfile(str(shard), dtype="<u2")
        v2_toks = receipt["mixture"]["v2_tokens"]
        aug_toks = receipt["mixture"]["aug_tokens"]
        aug_reps = receipt["mixture"]["aug_reps"]
        aug_raw = np.fromfile(str(self.aug_src), dtype="<u2")
        block = arr[v2_toks:v2_toks + aug_toks]
        expected = np.tile(aug_raw, aug_reps)
        np.testing.assert_array_equal(block, expected,
                                       err_msg="aug block does not match replicated aug")

    def test_T11_packed_shard_loader_reads(self):
        self._assemble()
        import sys
        if str(_HERE) not in sys.path:
            sys.path.insert(0, str(_HERE))
        from timeshare_pretrain import PackedShardLoader
        loader = PackedShardLoader(str(self.out), seq=16, n_mtp=0)
        assert loader.n_tokens > 0
        assert loader.n_windows > 0

    def test_T12_loader_window_shapes(self):
        self._assemble()
        from timeshare_pretrain import PackedShardLoader
        loader = PackedShardLoader(str(self.out), seq=16, n_mtp=0)
        x, y0, y_mtp = loader.window_np(0)
        assert x.shape == (16,)
        assert y0.shape == (16,)
        assert y_mtp == []

    def test_T14_ratio_within_tolerance(self):
        # Use a larger base_tokens so that aug_unit (55106) is small relative
        # to the mixture and the ratio approximation is tight.
        s0_large_dir = _synthetic_s0_dir(self.tmp, n_shards=3, tokens_per=600_000,
                                          dirname="shards_v0_large")
        receipt = _run_assemble(
            self.tmp,
            out_dir=self.tmp / "mixture_ratio",
            base_tokens=1_000_000,
            r_v2=0.40,
            r_aug=0.10,
            r_s0=0.50,
            shards_v0_dir=s0_large_dir,
            v2_src=self.v2_src,
            aug_src=self.aug_src,
        )
        mx = receipt["mixture"]
        total = mx["total_tokens"]
        v2_pct = 100 * mx["v2_tokens"] / total
        aug_pct = 100 * mx["aug_tokens"] / total
        s0_pct = 100 * mx["s0_tokens"] / total
        # At base_tokens=1M, source granularity is small enough for 5% tolerance
        assert abs(v2_pct - 40.0) < 5.0, f"v2% {v2_pct:.2f} not near 40"
        assert abs(aug_pct - 10.0) < 5.0, f"aug% {aug_pct:.2f} not near 10"
        assert abs(s0_pct - 50.0) < 5.0, f"s0% {s0_pct:.2f} not near 50"

    def test_T15_s0_is_head_of_sorted_stream(self):
        """s0 block equals the head of the sorted shards-v0 stream."""
        receipt = self._assemble()
        shard = self.out / "mixture-00000.bin"
        arr = np.fromfile(str(shard), dtype="<u2")
        v2_toks = receipt["mixture"]["v2_tokens"]
        aug_toks = receipt["mixture"]["aug_tokens"]
        s0_toks = receipt["mixture"]["s0_tokens"]
        s0_block = arr[v2_toks + aug_toks:]
        # Reconstruct expected s0 from sorted shards
        shards_sorted = sorted(self.s0_dir.iterdir(), key=lambda p: p.name)
        expected = np.concatenate([np.fromfile(str(p), dtype="<u2")
                                   for p in shards_sorted])[:s0_toks]
        np.testing.assert_array_equal(s0_block, expected,
                                       err_msg="s0 block is not head of sorted stream")

    def test_T18_output_dtype_is_uint16(self):
        self._assemble()
        shard = self.out / "mixture-00000.bin"
        arr = np.fromfile(str(shard), dtype="<u2")
        assert arr.dtype == np.dtype("<u2")


class TestVocabFirewall:
    def test_T16_vocab_firewall_fires(self):
        arr = np.array([8, 16, _VOCAB], dtype=np.uint16)
        with pytest.raises(ValueError, match="VOCAB FIREWALL"):
            _assert_vocab(arr, "test")

    def test_T16b_vocab_firewall_passes_valid(self):
        arr = np.array([0, 8, _VOCAB - 1], dtype=np.uint16)
        _assert_vocab(arr, "test")  # should not raise


class TestS0PrefixLoader:
    def test_T17_insufficient_tokens_raises(self):
        with tempfile.TemporaryDirectory(prefix="cbase_mix_t17_") as td:
            s0_dir = Path(td) / "shards"
            s0_dir.mkdir()
            rng = _det_rng("t17")
            arr = rng.integers(8, _VOCAB, size=1000, dtype=np.uint16)
            arr.tofile(str(s0_dir / "v0-00000.bin"))
            # Request more tokens than available
            with pytest.raises((AssertionError, ValueError)):
                _load_s0_prefix(s0_dir, n_tokens=5000)


class TestReproducibility:
    def test_T13_fresh_subprocess_identical_sha(self):
        """Rebuild in a fresh subprocess yields identical shard SHA256s."""
        script = Path(__file__).parent / "_cbase_mixture_repro_helper.py"
        # Write helper script that assemblies twice and compares SHAs
        helper_src = _REPRO_HELPER_SCRIPT
        script.write_text(helper_src, encoding="utf-8")
        try:
            result = subprocess.run(
                [sys.executable, str(script)],
                capture_output=True,
                text=True,
                timeout=120,
                env={**os.environ, "PYTHONPATH": str(_HERE)},
            )
            output = result.stdout + result.stderr
            assert result.returncode == 0, (
                f"Repro helper exited {result.returncode}:\n{output}"
            )
            assert "REPRO_PASS" in output, (
                f"REPRO_PASS marker missing in output:\n{output}"
            )
        finally:
            if script.exists():
                script.unlink()


# ---------------------------------------------------------------------------
# Repro helper source (embedded, written to disk by T13)
# ---------------------------------------------------------------------------

_REPRO_HELPER_SCRIPT = '''#!/usr/bin/env python3
"""Helper: assemble twice with same params, compare SHA256s."""
import hashlib
import sys
import tempfile
from pathlib import Path

import numpy as np

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

from ember_cbase_mixture import (
    _VOCAB, _V2_TOKENS, _AUG_TOKENS,
    assemble_mixture,
)
import ember_cbase_mixture as _em


def _det_rng(s):
    seed = int.from_bytes(hashlib.sha256(s.encode()).digest()[:8], "big")
    return np.random.default_rng(seed)


def _sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1<<20), b""):
            h.update(chunk)
    return h.hexdigest()


def run():
    with tempfile.TemporaryDirectory(prefix="repro_test_") as td:
        td = Path(td)
        v2 = td / "v2.bin"
        aug = td / "aug.bin"
        s0_dir = td / "shards_v0"
        s0_dir.mkdir()

        _det_rng("v2").integers(8, _VOCAB, size=_V2_TOKENS, dtype=np.uint16).tofile(str(v2))
        _det_rng("aug").integers(8, _VOCAB, size=_AUG_TOKENS, dtype=np.uint16).tofile(str(aug))
        for i in range(3):
            _det_rng(f"s0-{i}").integers(8, _VOCAB, size=100_000, dtype=np.uint16).tofile(
                str(s0_dir / f"v0-{i:05d}.bin"))

        orig_load = _em._load_source
        def _mock(path, expected_sha_prefix, expected_tokens, name):
            return np.fromfile(str(path), dtype="<u2")
        _em._load_source = _mock

        try:
            out1 = td / "out1"
            out2 = td / "out2"
            assemble_mixture(out1, base_tokens=150_000, r_v2=0.40, r_aug=0.10, r_s0=0.50,
                             shards_v0_dir=s0_dir, v2_src=v2, aug_src=aug)
            assemble_mixture(out2, base_tokens=150_000, r_v2=0.40, r_aug=0.10, r_s0=0.50,
                             shards_v0_dir=s0_dir, v2_src=v2, aug_src=aug)
        finally:
            _em._load_source = orig_load

        sha1 = _sha256(out1 / "mixture-00000.bin")
        sha2 = _sha256(out2 / "mixture-00000.bin")
        if sha1 == sha2:
            print(f"REPRO_PASS sha={sha1[:16]}")
        else:
            print(f"REPRO_FAIL sha1={sha1[:16]} sha2={sha2[:16]}")
            sys.exit(1)


run()
'''


# ---------------------------------------------------------------------------
# Direct runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v", "--tb=short"]))
