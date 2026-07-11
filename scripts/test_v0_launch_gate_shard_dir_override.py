"""test_v0_launch_gate_shard_dir_override.py -- regression coverage for #682
(v0_pretrain_launch_gate g_shards() ignoring --shard-dir and structurally
refusing in every worktree).

Root cause (scripts/token_shards_v0.py validate_shards_receipt): every
declared shard file was resolved as `f"{nc}/{shard_dir}/{name}"`, where `nc`
is v0_pretrain_launch_gate.py's own worktree/repo root and `shard_dir` is the
manifest's declared RELATIVE field (e.g. "../shards-v0"). That resolution is
repo/worktree-root-relative, so it silently points at a different (usually
nonexistent) location whenever the gate runs from a git worktree instead of
the main tree -- independent of what --shard-dir the caller actually passed
(the CLI argument was decorative for this row).

The cure (#682): thread the caller's --shard-dir through g_shards() /
gate() into validate_shards_receipt() as a `shard_dir_override` that takes
precedence over the NC-relative math; NC-relative resolution remains the
fallback when no override is supplied (byte-identical for every
pre-existing caller). An override pointing at a missing/wrong directory
must still fail closed -- this file proves all three shapes plus the
wiring from g_shards()/gate() down to the validator.

No real corpus, no GPU -- matches this repo's own fixture convention
(test_packed_shard_loader_memmap.py).
"""
import hashlib
import os
import sys
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import token_shards_v0 as tsv0                        # noqa: E402
import v0_pretrain_launch_gate as gate_mod             # noqa: E402


def _sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def _write_shard(path, n_tokens=600):
    # BLOCK_LEN (seq+1+n_mtp) = 1027; give it a few full windows worth of
    # in-vocab, non-reserved uint16 tokens so the byte-true scan is clean.
    import numpy as np
    rng = np.random.RandomState(7)
    arr = rng.randint(8, tsv0.VOCAB_SIZE, size=n_tokens).astype("<u2")  # skip 0..7
    os.makedirs(os.path.dirname(path), exist_ok=True)
    arr.tofile(path)
    return arr.nbytes // tsv0.BYTES_PER_TOKEN


def _minimal_receipt(shard_dir_field, shard_name, sha, n_tokens):
    """Just enough fields to reach the shard-resolution code path under
    test. Deliberately omits `premises` / `per_source` — those are orthogonal
    to the #682 fix and their absence produces its own (expected, ignored)
    violations that every assertion below scopes past via the shard[0]-only
    filter."""
    return {
        "ticket": tsv0.TICKET,
        "ts": "20260101T000000Z",
        "sha_convention": tsv0.SHA_CONVENTION,
        "shard_dir": shard_dir_field,
        "shards": [{"name": shard_name, "sha256": sha, "n_tokens": n_tokens}],
        "total_stream_tokens": n_tokens,
        "separator_id": tsv0.SEPARATOR_ID,
        "reserved_band_guard": {
            "reserved_ids": tsv0.RESERVED_IDS, "max_id_lt": tsv0.VOCAB_SIZE,
            "reserved_ids_observed_in_stream": 0,
        },
        "loader_windows": {"seq": tsv0.SEQ, "n_mtp": tsv0.N_MTP,
                           "block_len": tsv0.BLOCK_LEN, "n_windows": 0},
    }


def _shard_violations(violations):
    """Violations naming shard[0] specifically (existence/sha/n_tokens/scan)
    -- the exact class this fix changes the resolution for."""
    return [v for v in violations if v.startswith("shard[0]")]


# ---------------------------------------------------------------------------
# token_shards_v0.validate_shards_receipt -- the actual resolution site
# ---------------------------------------------------------------------------

def test_no_override_preserves_nc_relative_resolution(tmp_path):
    """Default (shard_dir_override=None) must resolve EXACTLY as before this
    fix: f"{nc}/{shard_dir}/{name}". When that math is correct, the shard is
    found clean -- proves the fallback path is byte-identical, not removed."""
    nc = tmp_path / "worktree-root"
    real_dir = nc / "real-shards"
    name = "v0-00000.bin"
    n = _write_shard(str(real_dir / name))
    sha = _sha256_bytes((real_dir / name).read_bytes())

    d = _minimal_receipt("real-shards", name, sha, n)
    violations = tsv0.validate_shards_receipt(d, nc=str(nc))
    assert _shard_violations(violations) == [], violations


def test_no_override_fails_when_nc_relative_math_is_wrong(tmp_path):
    """Same fixture, but nc points at a DIFFERENT root than where the shard
    actually lives (the worktree-drift shape from #682) -- with no override,
    NC-relative resolution misses the file and fails closed."""
    real_root = tmp_path / "main-tree"
    worktree_root = tmp_path / "some-worktree"
    name = "v0-00000.bin"
    n = _write_shard(str(real_root / "real-shards" / name))
    sha = _sha256_bytes((real_root / "real-shards" / name).read_bytes())

    d = _minimal_receipt("real-shards", name, sha, n)
    violations = tsv0.validate_shards_receipt(d, nc=str(worktree_root))
    assert any("not on disk" in v for v in _shard_violations(violations)), violations


def test_override_resolves_worktree_invariant_path(tmp_path):
    """The #682 cure: even when nc/shard_dir math is wrong (worktree drift),
    an explicit shard_dir_override pointing at the REAL location resolves
    the shard cleanly -- the override is authoritative, not a fallback of
    the fallback."""
    real_root = tmp_path / "main-tree"
    worktree_root = tmp_path / "some-worktree"
    real_dir = real_root / "real-shards"
    name = "v0-00000.bin"
    n = _write_shard(str(real_dir / name))
    sha = _sha256_bytes((real_dir / name).read_bytes())

    d = _minimal_receipt("real-shards", name, sha, n)
    violations = tsv0.validate_shards_receipt(
        d, nc=str(worktree_root), shard_dir_override=str(real_dir))
    assert _shard_violations(violations) == [], violations


def test_override_missing_dir_still_fails_closed(tmp_path):
    """An override pointing at a missing/empty directory must still refuse
    -- the fix is a resolution change, never a gate weakening."""
    name = "v0-00000.bin"
    d = _minimal_receipt("irrelevant", name, "0" * 64, 600)
    violations = tsv0.validate_shards_receipt(
        d, nc=str(tmp_path), shard_dir_override=str(tmp_path / "does-not-exist"))
    assert any("not on disk" in v for v in _shard_violations(violations)), violations


def test_override_wrong_bytes_still_fails_closed(tmp_path):
    """An override directory that EXISTS but holds a byte-mismatched file
    must still refuse (sha drift), not silently pass on presence alone."""
    override_dir = tmp_path / "override"
    name = "v0-00000.bin"
    _write_shard(str(override_dir / name), n_tokens=600)
    # receipt declares a sha that does not match the bytes actually on disk
    d = _minimal_receipt("irrelevant", name, "0" * 64, 600)
    violations = tsv0.validate_shards_receipt(
        d, nc=str(tmp_path), shard_dir_override=str(override_dir))
    assert any("sha drift" in v for v in _shard_violations(violations)), violations


# ---------------------------------------------------------------------------
# v0_pretrain_launch_gate wiring -- g_shards()/gate() must actually forward
# the override down to the validator (the literal #682 defect: the CLI
# argument was decorative because nothing threaded it through).
# ---------------------------------------------------------------------------

def test_g_shards_forwards_override_to_validator():
    with mock.patch.object(gate_mod, "_receipt_clean",
                            return_value=(True, {"fake": "receipt"})), \
         mock.patch.object(gate_mod.glob, "glob",
                            return_value=[f"{gate_mod.NC}/receipts/token-shards-v0-x.json"]), \
         mock.patch.object(gate_mod.token_shards_v0, "validate_shards_receipt",
                            return_value=[]) as mocked:
        st, dt = gate_mod.g_shards(shard_dir_override="/some/real/shard/dir")
    assert st == "GREEN", dt
    assert mocked.call_args.kwargs.get("shard_dir_override") == "/some/real/shard/dir"


def test_gate_forwards_shard_dir_override_to_g_shards():
    import datetime
    with mock.patch.object(gate_mod, "g_shards",
                            return_value=("GREEN", "stub")) as mocked_gs, \
         mock.patch.object(gate_mod, "g_corpus", return_value=("GREEN", "")), \
         mock.patch.object(gate_mod, "g_tokenizer", return_value=("GREEN", "")), \
         mock.patch.object(gate_mod, "g_config", return_value=("GREEN", "")), \
         mock.patch.object(gate_mod, "g_governor", return_value=("GREEN", "")), \
         mock.patch.object(gate_mod, "g_world", return_value=("GREEN", "")), \
         mock.patch.object(gate_mod, "g_budget", return_value=("GREEN", "")), \
         mock.patch.object(gate_mod, "g_prereg", return_value=("GREEN", "")), \
         mock.patch.object(gate_mod, "g_efficiency", return_value=("GREEN", "")):
        gate_mod.gate(datetime.date(2026, 6, 11), shard_dir_override="/some/real/shard/dir")
    mocked_gs.assert_called_once_with(shard_dir_override="/some/real/shard/dir")


def test_gate_default_shard_dir_override_is_none():
    """Every pre-existing caller of gate() (none pass shard_dir_override) must
    see byte-identical behavior -- the default forwards None."""
    import datetime
    with mock.patch.object(gate_mod, "g_shards",
                            return_value=("GREEN", "stub")) as mocked_gs, \
         mock.patch.object(gate_mod, "g_corpus", return_value=("GREEN", "")), \
         mock.patch.object(gate_mod, "g_tokenizer", return_value=("GREEN", "")), \
         mock.patch.object(gate_mod, "g_config", return_value=("GREEN", "")), \
         mock.patch.object(gate_mod, "g_governor", return_value=("GREEN", "")), \
         mock.patch.object(gate_mod, "g_world", return_value=("GREEN", "")), \
         mock.patch.object(gate_mod, "g_budget", return_value=("GREEN", "")), \
         mock.patch.object(gate_mod, "g_prereg", return_value=("GREEN", "")), \
         mock.patch.object(gate_mod, "g_efficiency", return_value=("GREEN", "")):
        gate_mod.gate(datetime.date(2026, 6, 11))
    mocked_gs.assert_called_once_with(shard_dir_override=None)
