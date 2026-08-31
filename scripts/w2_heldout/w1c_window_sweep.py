# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""w1c_window_sweep.py -- window-size (W) sweep diagnostic for the #372 W1c
certification effort, plus optional per-row match/shard-distribution
histograms.

Origin: a standalone region-scout worker (built outside this repo, in an
isolated workspace, to certify 10 pre-registered corpus regions ahead of
issue #372's K-batch pregistration) independently discovered two memory
bugs during that mission -- an unchunked rolling-hash cast blowing up on
large shards, and an unbounded confirmed_matches list causing a 30GB
working-set incident on a near-empty box. Diffing that worker against this
repo's actual state (PR #302, merged 2026-07-07, one day before the sweep
ran) showed BOTH bugs were already fixed here, and more robustly:
_scan_for_hits/_hash_and_hit_offsets in build_decontam_batch_mp.py chunk
each shard adaptively (halving on MemoryError down to
MIN_SCAN_SUBCHUNK_TOKENS) instead of a single fixed chunk size, and
contamination_recheck_mp's workers stream every match straight to a JSONL
dump file rather than ever holding a match list in memory. Reimplementing
either fix here would have shipped a second, inferior, parallel
implementation next to the one already merged -- so this script calls the
EXISTING contamination_recheck_mp instead of re-scanning anything itself.

GOTCHA (worth knowing before pointing this at a big sweep): contamination_
recheck_mp falls back to the SERIAL contamination_recheck (the un-chunked,
un-capped one imported from w1_collapse_control_run.py) whenever
n_workers <= 1. The chunked/adaptive/streaming path only activates for
n_workers >= 2. This script always requests n_workers >= 2 (see
--n-workers, default DEFAULT_MP_WORKERS) for exactly that reason.

WINDOW-INDEX CONVENTION (the P1-lane mismatch this disclosure exists to
prevent): this script's --pool-start is a SIMPLE, NON-OVERLAPPING window
index -- token_start = pool_start_index * (seq_len + 1), stride ==
block length, no held-out-set semantics. This is DIFFERENT from this
repo's own held_out_window_start()/PackedShardLoader convention in
w1_collapse_control_run.py, where window i covers tokens
[i*seq, i*seq + seq+1+n_mtp) -- stride == seq, block length ==
seq+1+n_mtp, so consecutive windows OVERLAP by n_mtp+1 tokens. The two
conventions are NOT interchangeable: multiplying a held_out_window_start
value by this script's (seq+1) stride can land past the true corpus
length (this is exactly what happened trying to cross-reference a P1-lane
position during the #372 shard-19/shard-25 investigation -- the P1 value
uses the OTHER stride). Always state which convention a window index used
before doing arithmetic on it.

Usage:
    python w1c_window_sweep.py --shard-dir /path/to/shards \\
        --pool-start 5194351 --batch-size 16 --seq-len 1024 \\
        --window-sizes 13,21,34,55,89 --anchor-w 13 \\
        --anchor-target-per-window 1044 --anchor-tolerance 0.20 \\
        --output-dir ./w1c-certs
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# issue2015 exact-local-import:src/ember/governance/scripts/w2_heldout/build_decontam_batch_mp.py
import importlib.util as _ember_9c92008c8512cb00_importlib
import sys as _ember_9c92008c8512cb00_sys
from pathlib import Path as _ember_9c92008c8512cb00_Path
_ember_9c92008c8512cb00_path = _ember_9c92008c8512cb00_Path(__file__).resolve().parents[2].joinpath('src', 'ember', 'governance', 'scripts', 'w2_heldout', 'build_decontam_batch_mp.py')
if not _ember_9c92008c8512cb00_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/w2_heldout/build_decontam_batch_mp.py')
_ember_9c92008c8512cb00_aliases = ('_ember_issue2015_9c92008c8512cb00', 'build_decontam_batch_mp', 'scripts.w2_heldout.build_decontam_batch_mp')
_ember_9c92008c8512cb00_existing = []
for _ember_9c92008c8512cb00_alias in _ember_9c92008c8512cb00_aliases:
    _ember_9c92008c8512cb00_candidate = _ember_9c92008c8512cb00_sys.modules.get(_ember_9c92008c8512cb00_alias)
    if _ember_9c92008c8512cb00_candidate is not None and all(_ember_9c92008c8512cb00_candidate is not item for item in _ember_9c92008c8512cb00_existing):
        _ember_9c92008c8512cb00_existing.append(_ember_9c92008c8512cb00_candidate)
if len(_ember_9c92008c8512cb00_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/w2_heldout/build_decontam_batch_mp.py')
if _ember_9c92008c8512cb00_existing:
    _ember_9c92008c8512cb00_module = _ember_9c92008c8512cb00_existing[0]
    _ember_9c92008c8512cb00_observed = getattr(_ember_9c92008c8512cb00_module, '__file__', None)
    if _ember_9c92008c8512cb00_observed is None or _ember_9c92008c8512cb00_Path(_ember_9c92008c8512cb00_observed).resolve() != _ember_9c92008c8512cb00_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/w2_heldout/build_decontam_batch_mp.py')
else:
    _ember_9c92008c8512cb00_spec = _ember_9c92008c8512cb00_importlib.spec_from_file_location('_ember_issue2015_9c92008c8512cb00', _ember_9c92008c8512cb00_path)
    if _ember_9c92008c8512cb00_spec is None or _ember_9c92008c8512cb00_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/w2_heldout/build_decontam_batch_mp.py')
    _ember_9c92008c8512cb00_module = _ember_9c92008c8512cb00_importlib.module_from_spec(_ember_9c92008c8512cb00_spec)
    for _ember_9c92008c8512cb00_alias in _ember_9c92008c8512cb00_aliases:
        _ember_9c92008c8512cb00_prior = _ember_9c92008c8512cb00_sys.modules.get(_ember_9c92008c8512cb00_alias)
        if _ember_9c92008c8512cb00_prior is not None and _ember_9c92008c8512cb00_prior is not _ember_9c92008c8512cb00_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/w2_heldout/build_decontam_batch_mp.py')
        _ember_9c92008c8512cb00_sys.modules[_ember_9c92008c8512cb00_alias] = _ember_9c92008c8512cb00_module
    try:
        _ember_9c92008c8512cb00_spec.loader.exec_module(_ember_9c92008c8512cb00_module)
    except BaseException:
        for _ember_9c92008c8512cb00_alias in _ember_9c92008c8512cb00_aliases:
            if _ember_9c92008c8512cb00_sys.modules.get(_ember_9c92008c8512cb00_alias) is _ember_9c92008c8512cb00_module:
                _ember_9c92008c8512cb00_sys.modules.pop(_ember_9c92008c8512cb00_alias, None)
        raise
for _ember_9c92008c8512cb00_alias in _ember_9c92008c8512cb00_aliases:
    _ember_9c92008c8512cb00_prior = _ember_9c92008c8512cb00_sys.modules.get(_ember_9c92008c8512cb00_alias)
    if _ember_9c92008c8512cb00_prior is not None and _ember_9c92008c8512cb00_prior is not _ember_9c92008c8512cb00_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/w2_heldout/build_decontam_batch_mp.py')
    _ember_9c92008c8512cb00_sys.modules[_ember_9c92008c8512cb00_alias] = _ember_9c92008c8512cb00_module
contamination_recheck_mp = getattr(_ember_9c92008c8512cb00_module, 'contamination_recheck_mp')
CONTAMINATION_WINDOW_TOKENS = getattr(_ember_9c92008c8512cb00_module, 'CONTAMINATION_WINDOW_TOKENS')
CONTAMINATION_ROLL_BASE = getattr(_ember_9c92008c8512cb00_module, 'CONTAMINATION_ROLL_BASE')
DEFAULT_MP_WORKERS = getattr(_ember_9c92008c8512cb00_module, 'DEFAULT_MP_WORKERS')
# issue2015 exact-local-import-end:src/ember/governance/scripts/w2_heldout/build_decontam_batch_mp.py

# Gray-zone / dead-cure classification thresholds, carried over from the
# frozen knee-sweep spec (state/w1c-knee-sweep-spec-20260708.md in the
# coordinating workspace) -- the pregistered decision rule this sweep exists
# to evaluate: is there a window size small enough that matches/window drops
# below a "this is just short-window noise" floor?
THRESHOLD_PER_WINDOW = 10
GRAY_ZONE_CEILING = 100


def load_eval_rows(shard_dir: str, pool_start: int, batch_size: int, seq_len: int) -> list:
    """Load `batch_size` consecutive NON-OVERLAPPING windows of length
    seq_len+1, starting at global token index pool_start*(seq_len+1). See
    the module docstring's WINDOW-INDEX CONVENTION section -- this is a
    diagnostic-tool-specific convention, not this repo's production
    held_out_window_start/PackedShardLoader stride."""
    tokens_per_window = seq_len + 1
    shard_names = sorted(p for p in os.listdir(shard_dir) if p.endswith(".bin"))
    if not shard_names:
        raise SystemExit(f"W1C_SWEEP_NO_SHARDS: {shard_dir!r}")
    shard_lens = [os.path.getsize(os.path.join(shard_dir, n)) // 2 for n in shard_names]
    cumulative = [0]
    for L in shard_lens:
        cumulative.append(cumulative[-1] + L)

    def _locate(global_start: int, global_end: int):
        """Return (shard_name, local_start, local_end) if [global_start,
        global_end) sits entirely within one shard; raise otherwise (cross-
        shard windows are out of scope for this diagnostic -- pick a
        pool_start that doesn't straddle a shard boundary)."""
        for idx, name in enumerate(shard_names):
            s, e = cumulative[idx], cumulative[idx + 1]
            if s <= global_start and global_end <= e:
                return name, global_start - s, global_end - s
        raise SystemExit(
            f"W1C_SWEEP_CROSS_SHARD_WINDOW: [{global_start},{global_end}) does not "
            f"sit entirely inside one shard -- pick a different pool_start")

    eval_rows = []
    needed_shards: dict[str, np.ndarray] = {}
    for offset in range(batch_size):
        window_idx = pool_start + offset
        g_start = window_idx * tokens_per_window
        g_end = g_start + tokens_per_window
        name, local_start, local_end = _locate(g_start, g_end)
        if name not in needed_shards:
            needed_shards[name] = np.fromfile(os.path.join(shard_dir, name), dtype="<u2")
        eval_rows.append(needed_shards[name][local_start:local_end].tolist())
    return eval_rows


def run_sweep(*, shard_dir: str, pool_start: int, batch_size: int, seq_len: int,
              window_sizes: list, anchor_w: int, anchor_target_per_window: float,
              anchor_tolerance: float, roll_base: int, n_workers: int,
              output_dir: str) -> dict:
    eval_rows = load_eval_rows(shard_dir, pool_start, batch_size, seq_len)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    os.makedirs(output_dir, exist_ok=True)
    receipt_path = os.path.join(output_dir, f"w1c-window-sweep-{ts}.json")

    results = []
    anchor_check = None
    void = False

    def _write():
        payload = {
            "schema": "w1c-window-sweep/v1", "ts": ts,
            "pool_start": pool_start, "batch_size": batch_size, "seq_len": seq_len,
            "window_index_convention": "non-overlapping, stride=seq_len+1 "
                "(NOT this repo's held_out_window_start/PackedShardLoader stride)",
            "window_sizes_requested": window_sizes, "results": results,
            "anchor_check": anchor_check, "void": void,
        }
        tmp = receipt_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, receipt_path)
        return payload

    for w in window_sizes:
        t0 = time.perf_counter()
        result = contamination_recheck_mp(
            eval_rows, shard_dir, window=w, roll_base=roll_base, n_workers=max(2, n_workers))
        wall_s = round(time.perf_counter() - t0, 3)
        match_count = result.get("matches_found", len(result.get("confirmed_matches", [])))
        matches_per_window = match_count / batch_size
        results.append({
            "W": w, "match_count": match_count, "matches_per_window": matches_per_window,
            "windows_hashed": result.get("windows_hashed", 0), "wall_s": wall_s,
            "n_workers": result.get("n_workers", n_workers),
        })
        if w == anchor_w:
            lo = anchor_target_per_window * (1 - anchor_tolerance)
            hi = anchor_target_per_window * (1 + anchor_tolerance)
            anchor_pass = lo <= matches_per_window <= hi
            anchor_check = {
                "anchor_w": w, "measured_per_window": matches_per_window,
                "target_per_window": anchor_target_per_window, "band": [lo, hi],
                "pass": anchor_pass,
            }
            _write()
            if not anchor_pass:
                void = True
                break
        else:
            _write()

    verdict = None
    if void:
        verdict = "VOID_anchor_reproduction_failed"
    elif len(results) < len(window_sizes):
        verdict = "INCOMPLETE_SWEEP_STOPPED_EARLY"
    else:
        below_threshold = [r for r in results if r["matches_per_window"] < THRESHOLD_PER_WINDOW]
        if below_threshold:
            verdict = f"KNEE_FOUND_W_{below_threshold[0]['W']}"
        else:
            last = results[-1]
            if last["matches_per_window"] >= GRAY_ZONE_CEILING:
                verdict = f"DEAD_window_reparam_no_help_ge{GRAY_ZONE_CEILING}_at_W{last['W']}"
            else:
                verdict = (f"GRAY_ZONE_{THRESHOLD_PER_WINDOW}_{GRAY_ZONE_CEILING}"
                           f"_at_W{last['W']}_no_verdict")

    payload = {
        "schema": "w1c-window-sweep/v1", "ts": ts,
        "pool_start": pool_start, "batch_size": batch_size, "seq_len": seq_len,
        "window_index_convention": "non-overlapping, stride=seq_len+1 "
            "(NOT this repo's held_out_window_start/PackedShardLoader stride)",
        "window_sizes_requested": window_sizes, "results": results,
        "anchor_check": anchor_check, "void": void, "verdict": verdict,
    }
    tmp = receipt_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, receipt_path)
    print(json.dumps(payload, indent=2))
    print(f"receipt written: {receipt_path}")
    return payload


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--shard-dir", required=True)
    ap.add_argument("--pool-start", type=int, required=True,
                    help="Non-overlapping window index (see WINDOW-INDEX CONVENTION above); "
                         "NOT a held_out_window_start()-style value.")
    ap.add_argument("--batch-size", type=int, default=16)
    ap.add_argument("--seq-len", type=int, default=1024)
    ap.add_argument("--window-sizes", type=str, default="13,21,34,55,89")
    ap.add_argument("--anchor-w", type=int, default=13)
    ap.add_argument("--anchor-target-per-window", type=float, default=None,
                     help="If omitted, the anchor gate is skipped (no reproduction check).")
    ap.add_argument("--anchor-tolerance", type=float, default=0.20)
    ap.add_argument("--roll-base", type=int, default=CONTAMINATION_ROLL_BASE)
    ap.add_argument("--n-workers", type=int, default=DEFAULT_MP_WORKERS)
    ap.add_argument("--output-dir", type=str, default="./w1c-certs")
    args = ap.parse_args()

    window_sizes = [int(w.strip()) for w in args.window_sizes.split(",") if w.strip()]
    anchor_target = args.anchor_target_per_window
    if anchor_target is None:
        # No reproduction gate requested -- treat as always-pass so the sweep
        # runs the full requested W list.
        anchor_target = 0.0
        anchor_tol = 1e18
    else:
        anchor_tol = args.anchor_tolerance

    result = run_sweep(
        shard_dir=args.shard_dir, pool_start=args.pool_start, batch_size=args.batch_size,
        seq_len=args.seq_len, window_sizes=window_sizes, anchor_w=args.anchor_w,
        anchor_target_per_window=anchor_target, anchor_tolerance=anchor_tol,
        roll_base=args.roll_base, n_workers=args.n_workers, output_dir=args.output_dir)
    sys.exit(1 if result.get("void") else 0)


if __name__ == "__main__":
    main()
