#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""test_ember_cbase_avir_data.py — TDD tests for ember_cbase_avir_data.py.

Tests:
  1. executing_verified: every emitted trace is R=1 executing-verified;
     synthesis_trusted_count == 0.
  2. train_only_firewall: no heldout (h0xx) task ID enters the corpus;
     attempting to run with a heldout ID raises ValueError.
  3. tokenizer_consistent: all token IDs < 32000 (vocab 32000).
  4. loads_back: written shards load via PackedShardLoader and windows decode.

Run:
    python scripts/test_ember_cbase_avir_data.py
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import tempfile

_HERE = pathlib.Path(__file__).resolve().parent
_REPO = _HERE.parent
sys.path.insert(0, str(_HERE))

# ---------------------------------------------------------------------------
# Import under test
# ---------------------------------------------------------------------------
# issue2015 exact-local-import:src/ember/governance/scripts/ember_cbase_avir_data.py
import importlib.util as _ember_46d4d551e87bceea_importlib
import sys as _ember_46d4d551e87bceea_sys
from pathlib import Path as _ember_46d4d551e87bceea_Path
_ember_46d4d551e87bceea_path = _ember_46d4d551e87bceea_Path(__file__).resolve().parents[1].joinpath('src', 'ember', 'governance', 'scripts', 'ember_cbase_avir_data.py')
if not _ember_46d4d551e87bceea_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/ember_cbase_avir_data.py')
_ember_46d4d551e87bceea_aliases = ('_ember_issue2015_46d4d551e87bceea', 'ember_cbase_avir_data', 'scripts.ember_cbase_avir_data')
_ember_46d4d551e87bceea_existing = []
for _ember_46d4d551e87bceea_alias in _ember_46d4d551e87bceea_aliases:
    _ember_46d4d551e87bceea_candidate = _ember_46d4d551e87bceea_sys.modules.get(_ember_46d4d551e87bceea_alias)
    if _ember_46d4d551e87bceea_candidate is not None and all(_ember_46d4d551e87bceea_candidate is not item for item in _ember_46d4d551e87bceea_existing):
        _ember_46d4d551e87bceea_existing.append(_ember_46d4d551e87bceea_candidate)
if len(_ember_46d4d551e87bceea_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/ember_cbase_avir_data.py')
if _ember_46d4d551e87bceea_existing:
    _ember_46d4d551e87bceea_module = _ember_46d4d551e87bceea_existing[0]
    _ember_46d4d551e87bceea_observed = getattr(_ember_46d4d551e87bceea_module, '__file__', None)
    if _ember_46d4d551e87bceea_observed is None or _ember_46d4d551e87bceea_Path(_ember_46d4d551e87bceea_observed).resolve() != _ember_46d4d551e87bceea_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/ember_cbase_avir_data.py')
else:
    _ember_46d4d551e87bceea_spec = _ember_46d4d551e87bceea_importlib.spec_from_file_location('_ember_issue2015_46d4d551e87bceea', _ember_46d4d551e87bceea_path)
    if _ember_46d4d551e87bceea_spec is None or _ember_46d4d551e87bceea_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/ember_cbase_avir_data.py')
    _ember_46d4d551e87bceea_module = _ember_46d4d551e87bceea_importlib.module_from_spec(_ember_46d4d551e87bceea_spec)
    for _ember_46d4d551e87bceea_alias in _ember_46d4d551e87bceea_aliases:
        _ember_46d4d551e87bceea_prior = _ember_46d4d551e87bceea_sys.modules.get(_ember_46d4d551e87bceea_alias)
        if _ember_46d4d551e87bceea_prior is not None and _ember_46d4d551e87bceea_prior is not _ember_46d4d551e87bceea_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/ember_cbase_avir_data.py')
        _ember_46d4d551e87bceea_sys.modules[_ember_46d4d551e87bceea_alias] = _ember_46d4d551e87bceea_module
    try:
        _ember_46d4d551e87bceea_spec.loader.exec_module(_ember_46d4d551e87bceea_module)
    except BaseException:
        for _ember_46d4d551e87bceea_alias in _ember_46d4d551e87bceea_aliases:
            if _ember_46d4d551e87bceea_sys.modules.get(_ember_46d4d551e87bceea_alias) is _ember_46d4d551e87bceea_module:
                _ember_46d4d551e87bceea_sys.modules.pop(_ember_46d4d551e87bceea_alias, None)
        raise
for _ember_46d4d551e87bceea_alias in _ember_46d4d551e87bceea_aliases:
    _ember_46d4d551e87bceea_prior = _ember_46d4d551e87bceea_sys.modules.get(_ember_46d4d551e87bceea_alias)
    if _ember_46d4d551e87bceea_prior is not None and _ember_46d4d551e87bceea_prior is not _ember_46d4d551e87bceea_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/ember_cbase_avir_data.py')
    _ember_46d4d551e87bceea_sys.modules[_ember_46d4d551e87bceea_alias] = _ember_46d4d551e87bceea_module
_M = _ember_46d4d551e87bceea_module
# issue2015 exact-local-import-end:src/ember/governance/scripts/ember_cbase_avir_data.py  # noqa: E402
# issue2015 exact-local-import:src/ember/governance/scripts/ember_avir_tasks.py
import importlib.util as _ember_6c243c4c73ac7e2b_importlib
import sys as _ember_6c243c4c73ac7e2b_sys
from pathlib import Path as _ember_6c243c4c73ac7e2b_Path
_ember_6c243c4c73ac7e2b_path = _ember_6c243c4c73ac7e2b_Path(__file__).resolve().parents[1].joinpath('src', 'ember', 'governance', 'scripts', 'ember_avir_tasks.py')
if not _ember_6c243c4c73ac7e2b_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/ember_avir_tasks.py')
_ember_6c243c4c73ac7e2b_aliases = ('_ember_issue2015_6c243c4c73ac7e2b', 'ember_avir_tasks', 'scripts.ember_avir_tasks')
_ember_6c243c4c73ac7e2b_existing = []
for _ember_6c243c4c73ac7e2b_alias in _ember_6c243c4c73ac7e2b_aliases:
    _ember_6c243c4c73ac7e2b_candidate = _ember_6c243c4c73ac7e2b_sys.modules.get(_ember_6c243c4c73ac7e2b_alias)
    if _ember_6c243c4c73ac7e2b_candidate is not None and all(_ember_6c243c4c73ac7e2b_candidate is not item for item in _ember_6c243c4c73ac7e2b_existing):
        _ember_6c243c4c73ac7e2b_existing.append(_ember_6c243c4c73ac7e2b_candidate)
if len(_ember_6c243c4c73ac7e2b_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/ember_avir_tasks.py')
if _ember_6c243c4c73ac7e2b_existing:
    _ember_6c243c4c73ac7e2b_module = _ember_6c243c4c73ac7e2b_existing[0]
    _ember_6c243c4c73ac7e2b_observed = getattr(_ember_6c243c4c73ac7e2b_module, '__file__', None)
    if _ember_6c243c4c73ac7e2b_observed is None or _ember_6c243c4c73ac7e2b_Path(_ember_6c243c4c73ac7e2b_observed).resolve() != _ember_6c243c4c73ac7e2b_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/ember_avir_tasks.py')
else:
    _ember_6c243c4c73ac7e2b_spec = _ember_6c243c4c73ac7e2b_importlib.spec_from_file_location('_ember_issue2015_6c243c4c73ac7e2b', _ember_6c243c4c73ac7e2b_path)
    if _ember_6c243c4c73ac7e2b_spec is None or _ember_6c243c4c73ac7e2b_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/ember_avir_tasks.py')
    _ember_6c243c4c73ac7e2b_module = _ember_6c243c4c73ac7e2b_importlib.module_from_spec(_ember_6c243c4c73ac7e2b_spec)
    for _ember_6c243c4c73ac7e2b_alias in _ember_6c243c4c73ac7e2b_aliases:
        _ember_6c243c4c73ac7e2b_prior = _ember_6c243c4c73ac7e2b_sys.modules.get(_ember_6c243c4c73ac7e2b_alias)
        if _ember_6c243c4c73ac7e2b_prior is not None and _ember_6c243c4c73ac7e2b_prior is not _ember_6c243c4c73ac7e2b_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/ember_avir_tasks.py')
        _ember_6c243c4c73ac7e2b_sys.modules[_ember_6c243c4c73ac7e2b_alias] = _ember_6c243c4c73ac7e2b_module
    try:
        _ember_6c243c4c73ac7e2b_spec.loader.exec_module(_ember_6c243c4c73ac7e2b_module)
    except BaseException:
        for _ember_6c243c4c73ac7e2b_alias in _ember_6c243c4c73ac7e2b_aliases:
            if _ember_6c243c4c73ac7e2b_sys.modules.get(_ember_6c243c4c73ac7e2b_alias) is _ember_6c243c4c73ac7e2b_module:
                _ember_6c243c4c73ac7e2b_sys.modules.pop(_ember_6c243c4c73ac7e2b_alias, None)
        raise
for _ember_6c243c4c73ac7e2b_alias in _ember_6c243c4c73ac7e2b_aliases:
    _ember_6c243c4c73ac7e2b_prior = _ember_6c243c4c73ac7e2b_sys.modules.get(_ember_6c243c4c73ac7e2b_alias)
    if _ember_6c243c4c73ac7e2b_prior is not None and _ember_6c243c4c73ac7e2b_prior is not _ember_6c243c4c73ac7e2b_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/ember_avir_tasks.py')
    _ember_6c243c4c73ac7e2b_sys.modules[_ember_6c243c4c73ac7e2b_alias] = _ember_6c243c4c73ac7e2b_module
load_split = getattr(_ember_6c243c4c73ac7e2b_module, 'load_split')
# issue2015 exact-local-import-end:src/ember/governance/scripts/ember_avir_tasks.py  # noqa: E402
from timeshare_pretrain import PackedShardLoader  # noqa: E402

_FILE_STATE_TRAIN_IDS = [
    "t001", "t002", "t003", "t004", "t005", "t006",
    "t007", "t008", "t009", "t010", "t011", "t012",
    "t013", "t014", "t015", "t016", "t017", "t018",
    "t019", "t020", "t021", "t022", "t023", "t024",
]

_HELDOUT_IDS = frozenset(t["id"] for t in load_split("heldout"))


def _run_pipeline_to_tmpdir():
    """Run the full pipeline into a fresh temp dir. Returns (result, tmp_dir)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        result = _M.run_pipeline(
            _FILE_STATE_TRAIN_IDS,
            output_dir=tmpdir,
            verbose=False,
        )
        # Copy relevant fields before tmpdir is cleaned up
        shard_path = result["shard_path"]
        # Read the shard bytes into memory for subsequent tests
        with open(shard_path, "rb") as f:
            shard_bytes = f.read()
        return result, shard_bytes, tmpdir


def test_executing_verified():
    """Every emitted trace is R=1 executing-verified; synthesis_trusted == 0."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        result = _M.run_pipeline(
            _FILE_STATE_TRAIN_IDS,
            output_dir=tmpdir,
            verbose=False,
        )
    assert result["synthesis_trusted_count"] == 0, (
        f"synthesis_trusted_count must be 0, got {result['synthesis_trusted_count']}"
    )
    assert result["traces_emitted"] > 0, "No traces emitted — pipeline produced nothing"
    assert result["traces_emitted"] == result["traces_executing_verified"], (
        f"Emitted {result['traces_emitted']} traces but only "
        f"{result['traces_executing_verified']} are executing-verified"
    )
    # All 24 train tasks should verify
    assert result["traces_emitted"] == len(_FILE_STATE_TRAIN_IDS), (
        f"Expected {len(_FILE_STATE_TRAIN_IDS)} traces, got {result['traces_emitted']}. "
        f"Dropped: {result['dropped']}"
    )
    print(f"PASS test_executing_verified: {result['traces_emitted']} traces, "
          f"all R=1, synthesis_trusted=0")


def test_train_only_firewall():
    """Heldout (h0xx) task IDs NEVER enter the corpus.

    Two checks:
    (a) The pipeline result contains only train IDs (emitted set ∩ heldout = empty).
    (b) Calling run_pipeline() with a heldout ID raises ValueError.
    """
    import tempfile

    # (a) Normal run: no heldout leakage
    with tempfile.TemporaryDirectory() as tmpdir:
        result = _M.run_pipeline(
            _FILE_STATE_TRAIN_IDS,
            output_dir=tmpdir,
            verbose=False,
        )
    # Emitted set = FILE_STATE_TRAIN_IDS minus dropped
    emitted_ids = set(_FILE_STATE_TRAIN_IDS) - set(result.get("dropped", []))
    overlap = emitted_ids & _HELDOUT_IDS
    assert not overlap, (
        f"FIREWALL BREACH: heldout IDs in emitted set: {overlap}"
    )

    # (b) Injecting a heldout ID must raise ValueError
    heldout_sample = sorted(_HELDOUT_IDS)[0]  # e.g. "h001"
    raised = False
    try:
        with tempfile.TemporaryDirectory() as tmpdir2:
            _M.run_pipeline(
                [heldout_sample],
                output_dir=tmpdir2,
                verbose=False,
            )
    except ValueError as e:
        raised = True
        assert "FIREWALL" in str(e) or "held-out" in str(e).lower(), (
            f"ValueError raised but message doesn't mention firewall: {e}"
        )
    assert raised, (
        f"Expected ValueError when running pipeline with heldout ID {heldout_sample!r}, "
        f"but no exception was raised"
    )

    print(f"PASS test_train_only_firewall: no heldout leakage, injection raises ValueError")


def test_tokenizer_consistent():
    """All emitted token IDs are < 32000 (vocab 32000)."""
    import numpy as np
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        result = _M.run_pipeline(
            _FILE_STATE_TRAIN_IDS,
            output_dir=tmpdir,
            verbose=False,
        )
        shard_path = result["shard_path"]
        arr = np.fromfile(shard_path, dtype="<u2")

    max_id = int(arr.max())
    assert max_id < 32000, (
        f"Token ID {max_id} >= 32000 found in shard — tokenizer vocab violated"
    )
    assert len(arr) > 0, "Shard is empty"
    print(f"PASS test_tokenizer_consistent: {len(arr)} tokens, max_id={max_id} < 32000")


def test_loads_back():
    """Written shards load via PackedShardLoader and windows decode correctly.

    Verifies:
    - PackedShardLoader can open the shard directory without error.
    - At least one window is produced (n_windows >= 1).
    - window_np(0) returns (x, y_primary, []) with correct shapes.
    - Concatenating all x windows reconstructs the stream prefix exactly
      (the round-trip claim from PackedShardLoader docstring).
    """
    import numpy as np
    import tempfile

    SEQ = 64
    N_MTP = 0

    with tempfile.TemporaryDirectory() as tmpdir:
        result = _M.run_pipeline(
            _FILE_STATE_TRAIN_IDS,
            output_dir=tmpdir,
            verbose=False,
        )
        shard_dir = str(pathlib.Path(result["shard_path"]).parent)

        # The shard must have enough tokens for at least one window
        arr = np.fromfile(result["shard_path"], dtype="<u2")
        total_tokens = len(arr)
        block_len = SEQ + 1 + N_MTP
        if total_tokens < block_len:
            # Use a smaller seq that fits
            SEQ = max(1, total_tokens - 1)
            block_len = SEQ + 1

        loader = PackedShardLoader(shard_dir, seq=SEQ, n_mtp=N_MTP)
        assert loader.n_windows >= 1, (
            f"Expected at least 1 window, got {loader.n_windows}"
        )

        # Check first window shape
        x, y0, ymtp = loader.window_np(0)
        assert x.shape == (SEQ,), f"x shape {x.shape} != ({SEQ},)"
        assert y0.shape == (SEQ,), f"y0 shape {y0.shape} != ({SEQ},)"
        assert ymtp == [], f"Expected empty mtp list, got {ymtp}"

        # Round-trip: concatenating x windows reconstructs stream prefix
        xs = np.concatenate([loader.window_np(i)[0] for i in range(loader.n_windows)])
        expected_prefix = loader.stream[:loader.n_windows * SEQ]
        assert np.array_equal(xs, expected_prefix.astype("int64")), (
            "Round-trip failed: concatenated x windows don't match stream prefix"
        )

        print(
            f"PASS test_loads_back: {loader.n_windows} windows, seq={SEQ}, "
            f"total_tokens={total_tokens}, round-trip verified"
        )


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

_TESTS = [
    test_executing_verified,
    test_train_only_firewall,
    test_tokenizer_consistent,
    test_loads_back,
]

if __name__ == "__main__":
    passed = 0
    failed = 0
    output_lines = []
    for test_fn in _TESTS:
        name = test_fn.__name__
        try:
            test_fn()
            passed += 1
        except Exception as exc:
            failed += 1
            line = f"FAIL {name}: {exc}"
            print(line)
            import traceback
            traceback.print_exc()
            output_lines.append(line)

    print(f"\n{passed}/{len(_TESTS)} tests passed")
    if failed:
        sys.exit(1)
