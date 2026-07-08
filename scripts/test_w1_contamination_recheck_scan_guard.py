"""test_w1_contamination_recheck_scan_guard.py -- TDD for issue #445: fold
w2_heldout/build_decontam_batch_mp.py's adaptive chunk-halving MemoryError/
ArrayMemoryError guard directly into scripts/w1_collapse_control_run.py's
serial contamination_recheck(), so it is the ONLY entry point and every
caller (p1_envelope_sweep.py, w1_recheck_cache.py, w2_heldout/
build_decontam_batch.py, this module's own main()) inherits the guard with
zero signature changes.

Real code under test (imported, never reimplemented), synthetic-only corpus
(tempfile.TemporaryDirectory(), a tiny made-up uint16 token stream) -- same
convention as test_w1_live_gates.py / w2_heldout/test_build_decontam_batch.py.
No real corpus, no real memory pressure -- the MemoryError is SIMULATED by
monkeypatching the module-level scan primitive (_hash_chunk_for_hits), the
same style w2_heldout/test_build_decontam_batch.py already uses to simulate
memory pressure without needing gigabytes of real RAM.
"""
from __future__ import annotations

import os
import sys
import tempfile

import numpy as np
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import w1_collapse_control_run  # noqa: E402
from w1_collapse_control_run import contamination_recheck  # noqa: E402

WINDOW = 4  # small window for a fast, toy-scale fixture (production default is 13)
ROLL_BASE = w1_collapse_control_run.CONTAMINATION_ROLL_BASE


def _write_shard(shard_dir: str, name: str, tokens) -> None:
    np.array(list(tokens), dtype="<u2").tofile(os.path.join(shard_dir, name))


def _fake_hash_chunk_factory(real_fn, fail_above_tokens: int):
    """Wraps the REAL _hash_chunk_for_hits primitive but raises MemoryError
    when called on a span longer than fail_above_tokens tokens -- simulating
    "the full-size attempt cannot allocate" (issue #445's reported failure:
    a 268M-element/~2GiB uint64 buffer) without needing real memory
    pressure. A span at or below the threshold (i.e. a sufficiently-halved
    chunk) is passed straight through to the real computation, so results
    are only ever produced by real code, never faked."""
    def _fake(arr_u16, n_keep, window, roll_base, needle_arr):
        if arr_u16.shape[0] > fail_above_tokens:
            raise MemoryError(
                f"simulated: {arr_u16.shape[0]}-token span exceeds fake ceiling "
                f"{fail_above_tokens}")
        return real_fn(arr_u16, n_keep, window, roll_base, needle_arr)
    return _fake


def test_contamination_recheck_survives_simulated_full_size_memory_error(monkeypatch):
    """The exact class of issue #445 instance 2: the full-size scan attempt
    raises MemoryError (there, numpy's own ArrayMemoryError on a 268M-element
    uint64 buffer); the guarded serial contamination_recheck must recover by
    halving the chunk and retrying, returning the IDENTICAL result set an
    unguarded pass (no failure ever induced) produces on the same fixture."""
    with tempfile.TemporaryDirectory() as shard_dir:
        n_tokens = 60
        _write_shard(shard_dir, "shard-0000.bin", range(n_tokens))
        # eval_rows drawn from the corpus's own content -> guaranteed matches,
        # so the equivalence check below compares non-trivial results, not an
        # empty-vs-empty edge case.
        eval_rows = [[0, 1, 2, 3, 4], [10, 11, 12, 13, 14], [40, 41, 42, 43]]

        baseline = contamination_recheck(
            eval_rows, shard_dir, window=WINDOW, roll_base=ROLL_BASE,
            scan_chunk_tokens=n_tokens, min_scan_subchunk_tokens=8)

        real_fn = w1_collapse_control_run._hash_chunk_for_hits
        monkeypatch.setattr(
            w1_collapse_control_run, "_hash_chunk_for_hits",
            _fake_hash_chunk_factory(real_fn, fail_above_tokens=30))

        guarded = contamination_recheck(
            eval_rows, shard_dir, window=WINDOW, roll_base=ROLL_BASE,
            scan_chunk_tokens=n_tokens, min_scan_subchunk_tokens=8)

    assert baseline["confirmed_matches"], "fixture must produce real matches to be meaningful"
    assert guarded["verdict"] == baseline["verdict"]
    assert guarded["windows_hashed"] == baseline["windows_hashed"]
    assert guarded["hash_collisions_ruled_out"] == baseline["hash_collisions_ruled_out"]
    assert (sorted(guarded["confirmed_matches"], key=str)
            == sorted(baseline["confirmed_matches"], key=str))


def test_contamination_recheck_scan_guard_reraises_at_min_chunk_floor(monkeypatch):
    """When even the smallest sub-chunk (at min_scan_subchunk_tokens) still
    raises MemoryError, the guard must NOT retry forever -- it re-raises a
    NAMED MemoryError instead of masking a genuinely exhausted environment
    (or, worse, silently looping)."""
    with tempfile.TemporaryDirectory() as shard_dir:
        n_tokens = 60
        _write_shard(shard_dir, "shard-0000.bin", range(n_tokens))
        eval_rows = [[0, 1, 2, 3, 4]]

        real_fn = w1_collapse_control_run._hash_chunk_for_hits
        monkeypatch.setattr(
            w1_collapse_control_run, "_hash_chunk_for_hits",
            _fake_hash_chunk_factory(real_fn, fail_above_tokens=-1))  # always fails

        with pytest.raises(MemoryError, match="W1_LIVE_CONTAMINATION_SCAN_OOM"):
            contamination_recheck(
                eval_rows, shard_dir, window=WINDOW, roll_base=ROLL_BASE,
                scan_chunk_tokens=n_tokens, min_scan_subchunk_tokens=8)


def test_contamination_recheck_default_scan_params_match_build_decontam_batch_mp():
    """Issue #445's fold-in must reuse build_decontam_batch_mp.py's exact
    chunk/floor bounds, not invent new ones -- a silent divergence here would
    leave the serial path memory-safe at a DIFFERENT ceiling than its
    parallel sibling, reintroducing the exact "two paths, one hardened" class
    this issue closes."""
    sys.path.insert(0, os.path.join(HERE, "w2_heldout"))
    import build_decontam_batch_mp  # noqa: E402

    assert (w1_collapse_control_run.DEFAULT_SCAN_CHUNK_TOKENS
            == build_decontam_batch_mp.DEFAULT_SCAN_CHUNK_TOKENS)
    assert (w1_collapse_control_run.MIN_SCAN_SUBCHUNK_TOKENS
            == build_decontam_batch_mp.MIN_SCAN_SUBCHUNK_TOKENS)
