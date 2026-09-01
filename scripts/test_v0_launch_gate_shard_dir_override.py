# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""test_v0_launch_gate_shard_dir_override.py -- regression coverage for #682
(v0_pretrain_launch_gate g_shards() ignoring --shard-dir and structurally
refusing in every worktree).

Root cause (src/ember/governance/scripts/token_shards_v0.py validate_shards_receipt): every
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

# issue2015 exact-local-import:src/ember/governance/scripts/token_shards_v0.py
import importlib.util as _ember_0c6ba95c4d327f51_importlib
import sys as _ember_0c6ba95c4d327f51_sys
from pathlib import Path as _ember_0c6ba95c4d327f51_Path
_ember_0c6ba95c4d327f51_path = _ember_0c6ba95c4d327f51_Path(__file__).resolve().parents[1].joinpath('src', 'ember', 'governance', 'scripts', 'token_shards_v0.py')
if not _ember_0c6ba95c4d327f51_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/token_shards_v0.py')
_ember_0c6ba95c4d327f51_aliases = ('_ember_issue2015_0c6ba95c4d327f51', 'scripts.token_shards_v0', 'token_shards_v0')
_ember_0c6ba95c4d327f51_existing = []
for _ember_0c6ba95c4d327f51_alias in _ember_0c6ba95c4d327f51_aliases:
    _ember_0c6ba95c4d327f51_candidate = _ember_0c6ba95c4d327f51_sys.modules.get(_ember_0c6ba95c4d327f51_alias)
    if _ember_0c6ba95c4d327f51_candidate is not None and all(_ember_0c6ba95c4d327f51_candidate is not item for item in _ember_0c6ba95c4d327f51_existing):
        _ember_0c6ba95c4d327f51_existing.append(_ember_0c6ba95c4d327f51_candidate)
if len(_ember_0c6ba95c4d327f51_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/token_shards_v0.py')
if _ember_0c6ba95c4d327f51_existing:
    _ember_0c6ba95c4d327f51_module = _ember_0c6ba95c4d327f51_existing[0]
    _ember_0c6ba95c4d327f51_observed = getattr(_ember_0c6ba95c4d327f51_module, '__file__', None)
    if _ember_0c6ba95c4d327f51_observed is None or _ember_0c6ba95c4d327f51_Path(_ember_0c6ba95c4d327f51_observed).resolve() != _ember_0c6ba95c4d327f51_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/token_shards_v0.py')
else:
    _ember_0c6ba95c4d327f51_spec = _ember_0c6ba95c4d327f51_importlib.spec_from_file_location('_ember_issue2015_0c6ba95c4d327f51', _ember_0c6ba95c4d327f51_path)
    if _ember_0c6ba95c4d327f51_spec is None or _ember_0c6ba95c4d327f51_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/token_shards_v0.py')
    _ember_0c6ba95c4d327f51_module = _ember_0c6ba95c4d327f51_importlib.module_from_spec(_ember_0c6ba95c4d327f51_spec)
    for _ember_0c6ba95c4d327f51_alias in _ember_0c6ba95c4d327f51_aliases:
        _ember_0c6ba95c4d327f51_prior = _ember_0c6ba95c4d327f51_sys.modules.get(_ember_0c6ba95c4d327f51_alias)
        if _ember_0c6ba95c4d327f51_prior is not None and _ember_0c6ba95c4d327f51_prior is not _ember_0c6ba95c4d327f51_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/token_shards_v0.py')
        _ember_0c6ba95c4d327f51_sys.modules[_ember_0c6ba95c4d327f51_alias] = _ember_0c6ba95c4d327f51_module
    try:
        _ember_0c6ba95c4d327f51_spec.loader.exec_module(_ember_0c6ba95c4d327f51_module)
    except BaseException:
        for _ember_0c6ba95c4d327f51_alias in _ember_0c6ba95c4d327f51_aliases:
            if _ember_0c6ba95c4d327f51_sys.modules.get(_ember_0c6ba95c4d327f51_alias) is _ember_0c6ba95c4d327f51_module:
                _ember_0c6ba95c4d327f51_sys.modules.pop(_ember_0c6ba95c4d327f51_alias, None)
        raise
for _ember_0c6ba95c4d327f51_alias in _ember_0c6ba95c4d327f51_aliases:
    _ember_0c6ba95c4d327f51_prior = _ember_0c6ba95c4d327f51_sys.modules.get(_ember_0c6ba95c4d327f51_alias)
    if _ember_0c6ba95c4d327f51_prior is not None and _ember_0c6ba95c4d327f51_prior is not _ember_0c6ba95c4d327f51_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/token_shards_v0.py')
    _ember_0c6ba95c4d327f51_sys.modules[_ember_0c6ba95c4d327f51_alias] = _ember_0c6ba95c4d327f51_module
tsv0 = _ember_0c6ba95c4d327f51_module
# issue2015 exact-local-import-end:src/ember/governance/scripts/token_shards_v0.py                        # noqa: E402
# issue2015 exact-local-import:src/ember/governance/scripts/v0_pretrain_launch_gate.py
import importlib.util as _ember_fbb2699a8f4bfd8b_importlib
import sys as _ember_fbb2699a8f4bfd8b_sys
from pathlib import Path as _ember_fbb2699a8f4bfd8b_Path
_ember_fbb2699a8f4bfd8b_path = _ember_fbb2699a8f4bfd8b_Path(__file__).resolve().parents[1].joinpath('src', 'ember', 'governance', 'scripts', 'v0_pretrain_launch_gate.py')
if not _ember_fbb2699a8f4bfd8b_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/v0_pretrain_launch_gate.py')
_ember_fbb2699a8f4bfd8b_aliases = ('_ember_issue2015_fbb2699a8f4bfd8b', 'scripts.v0_pretrain_launch_gate', 'v0_pretrain_launch_gate')
_ember_fbb2699a8f4bfd8b_existing = []
for _ember_fbb2699a8f4bfd8b_alias in _ember_fbb2699a8f4bfd8b_aliases:
    _ember_fbb2699a8f4bfd8b_candidate = _ember_fbb2699a8f4bfd8b_sys.modules.get(_ember_fbb2699a8f4bfd8b_alias)
    if _ember_fbb2699a8f4bfd8b_candidate is not None and all(_ember_fbb2699a8f4bfd8b_candidate is not item for item in _ember_fbb2699a8f4bfd8b_existing):
        _ember_fbb2699a8f4bfd8b_existing.append(_ember_fbb2699a8f4bfd8b_candidate)
if len(_ember_fbb2699a8f4bfd8b_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/v0_pretrain_launch_gate.py')
if _ember_fbb2699a8f4bfd8b_existing:
    _ember_fbb2699a8f4bfd8b_module = _ember_fbb2699a8f4bfd8b_existing[0]
    _ember_fbb2699a8f4bfd8b_observed = getattr(_ember_fbb2699a8f4bfd8b_module, '__file__', None)
    if _ember_fbb2699a8f4bfd8b_observed is None or _ember_fbb2699a8f4bfd8b_Path(_ember_fbb2699a8f4bfd8b_observed).resolve() != _ember_fbb2699a8f4bfd8b_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/v0_pretrain_launch_gate.py')
else:
    _ember_fbb2699a8f4bfd8b_spec = _ember_fbb2699a8f4bfd8b_importlib.spec_from_file_location('_ember_issue2015_fbb2699a8f4bfd8b', _ember_fbb2699a8f4bfd8b_path)
    if _ember_fbb2699a8f4bfd8b_spec is None or _ember_fbb2699a8f4bfd8b_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/v0_pretrain_launch_gate.py')
    _ember_fbb2699a8f4bfd8b_module = _ember_fbb2699a8f4bfd8b_importlib.module_from_spec(_ember_fbb2699a8f4bfd8b_spec)
    for _ember_fbb2699a8f4bfd8b_alias in _ember_fbb2699a8f4bfd8b_aliases:
        _ember_fbb2699a8f4bfd8b_prior = _ember_fbb2699a8f4bfd8b_sys.modules.get(_ember_fbb2699a8f4bfd8b_alias)
        if _ember_fbb2699a8f4bfd8b_prior is not None and _ember_fbb2699a8f4bfd8b_prior is not _ember_fbb2699a8f4bfd8b_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/v0_pretrain_launch_gate.py')
        _ember_fbb2699a8f4bfd8b_sys.modules[_ember_fbb2699a8f4bfd8b_alias] = _ember_fbb2699a8f4bfd8b_module
    try:
        _ember_fbb2699a8f4bfd8b_spec.loader.exec_module(_ember_fbb2699a8f4bfd8b_module)
    except BaseException:
        for _ember_fbb2699a8f4bfd8b_alias in _ember_fbb2699a8f4bfd8b_aliases:
            if _ember_fbb2699a8f4bfd8b_sys.modules.get(_ember_fbb2699a8f4bfd8b_alias) is _ember_fbb2699a8f4bfd8b_module:
                _ember_fbb2699a8f4bfd8b_sys.modules.pop(_ember_fbb2699a8f4bfd8b_alias, None)
        raise
for _ember_fbb2699a8f4bfd8b_alias in _ember_fbb2699a8f4bfd8b_aliases:
    _ember_fbb2699a8f4bfd8b_prior = _ember_fbb2699a8f4bfd8b_sys.modules.get(_ember_fbb2699a8f4bfd8b_alias)
    if _ember_fbb2699a8f4bfd8b_prior is not None and _ember_fbb2699a8f4bfd8b_prior is not _ember_fbb2699a8f4bfd8b_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/v0_pretrain_launch_gate.py')
    _ember_fbb2699a8f4bfd8b_sys.modules[_ember_fbb2699a8f4bfd8b_alias] = _ember_fbb2699a8f4bfd8b_module
gate_mod = _ember_fbb2699a8f4bfd8b_module
# issue2015 exact-local-import-end:src/ember/governance/scripts/v0_pretrain_launch_gate.py             # noqa: E402


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
                            return_value=[]) as mocked, \
         mock.patch.object(gate_mod, "_shards_exclusion_check",
                            return_value=("GREEN", "isolated")) as mocked_exclusion:
        st, dt = gate_mod.g_shards(shard_dir_override="/some/real/shard/dir")
    assert st == "GREEN", dt
    assert mocked.call_args.kwargs.get("shard_dir_override") == "/some/real/shard/dir"
    mocked_exclusion.assert_called_once_with("token-shards-v0-x.json", {"fake": "receipt"})


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
