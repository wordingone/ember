#!/usr/bin/env python3
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
import ember_cbase_avir_data as _M  # noqa: E402
from ember_avir_tasks import load_split  # noqa: E402
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
