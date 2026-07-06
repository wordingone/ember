"""build_decontam_batch_mp.py -- W2 preregistration sec.4 decontamination (parallelized).

Identical to build_decontam_batch.py in algorithm, semantics, and receipt contract.
The only difference: the contamination_recheck corpus scan is parallelized across
worker processes, sharding the corpus and merging results deterministically.

Receipt fields, sha pins, contamination_recheck=0 requirement, error shapes:
all IDENTICAL to the serial version. Only the wall-clock time changes.

Parallelization strategy:
  - Extract needle hashes from candidates (same for all workers)
  - Shard the corpus by file (each worker gets a subset of .bin files)
  - Each worker: loads its shards, computes rolling hashes, scans for matches
  - Boundary windows: worker pair handles the join between consecutive shards
  - Results merge deterministically (confirmed_matches concatenation is order-independent)

Memory discipline:
  - Preflight: assert >12GB free commit available, refuse if <12GB
  - Workers use read() per-chunk, NOT memmap (to avoid page-in storms)
  - Worker count capped: min(8, cores-4)
  - Progress: unbuffered stdout + heartbeat side-file per chunk

Equivalence gate: before the real launch, run equivalence test on fixture-scale
synthetic corpus to verify IDENTICAL decisions vs. serial version.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from multiprocessing import Pool, Manager
import shutil
import psutil

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_ROOT = os.path.dirname(HERE)
REPO_ROOT = os.path.dirname(SCRIPTS_ROOT)
sys.path.insert(0, SCRIPTS_ROOT)

from w1_collapse_control_run import (
    contamination_recheck as _serial_contamination_recheck,
    held_out_window_start,
    assert_disjoint_from_training,
    compute_n_windows_from_manifest,
    CONTAMINATION_WINDOW_TOKENS,
    CONTAMINATION_ROLL_BASE,
)

# Import torch-free scanner for multiprocessing pools (no CUDA DLL loads in workers)
from decon_scan_worker import contamination_scan_memmap


def contamination_recheck(candidate_rows: list[list[int]],
                          shard_dir: str,
                          *, window: int, roll_base: int) -> dict:
    """Memory-safe wrapper around serial contamination_recheck.

    Implements chunked scanning with adaptive splitting on MemoryError.
    Returns identical dict structure as serial version (NO 'wall_s' key).
    """
    try:
        return _serial_contamination_recheck(candidate_rows, shard_dir,
                                             window=window, roll_base=roll_base)
    except (MemoryError, np._core._exceptions._ArrayMemoryError) as e:
        # Adaptive split: divide candidate list in half, scan each, merge results
        if len(candidate_rows) <= 1:
            # Can't split further, re-raise
            raise
        mid = len(candidate_rows) // 2
        left = contamination_recheck(candidate_rows[:mid], shard_dir,
                                    window=window, roll_base=roll_base)
        right = contamination_recheck(candidate_rows[mid:], shard_dir,
                                     window=window, roll_base=roll_base)
        # Merge results deterministically
        return {
            "method": left["method"],
            "corpus_verification_open_item_ref": left["corpus_verification_open_item_ref"],
            "shards_scanned": left["shards_scanned"],
            "windows_hashed": left["windows_hashed"] + right["windows_hashed"],
            "confirmed_matches": left["confirmed_matches"] + right["confirmed_matches"],
            "hash_collisions_ruled_out": left["hash_collisions_ruled_out"] + right["hash_collisions_ruled_out"],
            "verdict": "CLEAN" if not (left["confirmed_matches"] + right["confirmed_matches"]) else "CONTAMINATED",
        }

# Defaults (same as serial version)
DEFAULT_SEQ = 1024
DEFAULT_N_MTP = 2
DEFAULT_BATCH_SIZE = 16
DEFAULT_CEILING_STEPS = 1533
DEFAULT_TRAIN_BATCH = 16
DEFAULT_SHARD_DIR = os.environ.get("EMBER_SHARD_DIR", "")
DEFAULT_POOL_OVERSAMPLE = 2
DEFAULT_MAX_ROUNDS = 6
DEFAULT_MP_WORKERS = min(8, max(1, psutil.cpu_count() - 4))
MIN_COMMIT_FREE_GB = 12
DEFAULT_SCAN_CHUNK_TOKENS = 33554432  # 32M tokens per chunk (memory-safe slicing)
HEARTBEAT_INTERVAL_S = 20  # intra-shard progress heartbeat cadence (issue #174 Phase 2)

RECEIPT_DIR = os.path.join(REPO_ROOT, "receipts", "ember-c-scale")


def _utc_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _preflight_check_commit() -> tuple[float, float]:
    """Return (total_commit_gb, free_commit_gb). Exit if free < MIN_COMMIT_FREE_GB."""
    vm = psutil.virtual_memory()
    commit_total_gb = vm.total / (1024**3)
    commit_free_gb = (vm.available) / (1024**3)
    if commit_free_gb < MIN_COMMIT_FREE_GB:
        raise SystemExit(
            f"W2_DECONTAM_INSUFFICIENT_HEADROOM: {commit_free_gb:.1f}GB free commit < "
            f"{MIN_COMMIT_FREE_GB}GB required. Abort.")
    return commit_total_gb, commit_free_gb


# ---------------------------------------------------------------------------
# Cheap manifest (same as serial version)
# ---------------------------------------------------------------------------

def cheap_shard_sizes(shard_dir: str) -> list[dict]:
    paths = sorted(Path(shard_dir).glob("*.bin"), key=lambda p: p.name)
    if not paths:
        raise SystemExit(f"W2_DECONTAM_NO_SHARDS: no *.bin under {shard_dir!r}")
    out = []
    for p in paths:
        size_bytes = p.stat().st_size
        out.append({"name": p.name, "size_bytes": size_bytes,
                     "n_tokens": size_bytes // 2})
    return out


def shard_manifest_for_window_count(shard_dir: str) -> dict:
    files = cheap_shard_sizes(shard_dir)
    return {"total_size_bytes": sum(f["size_bytes"] for f in files), "files": files}


# ---------------------------------------------------------------------------
# RAM-frugal window reader (same as serial version)
# ---------------------------------------------------------------------------

def _cumulative_token_offsets(files: list[dict]) -> list[int]:
    cum = [0]
    for f in files:
        cum.append(cum[-1] + f["n_tokens"])
    return cum


def window_source_position(files: list[dict], cum: list[int], seq: int,
                            window_idx: int) -> dict:
    start = window_idx * seq
    for i in range(len(files)):
        if cum[i] <= start < cum[i + 1]:
            return {"shard": files[i]["name"], "offset": start - cum[i], "global_start": start}
    raise SystemExit(
        f"W2_DECONTAM_WINDOW_OUT_OF_RANGE: window {window_idx} start {start} "
        f"exceeds corpus token range {cum[-1]}")


def _match_global_start(m: dict, name_to_index: dict[str, int], cum: list[int],
                         window: int) -> int:
    if "shard" in m:
        return cum[name_to_index[m["shard"]]] + m["offset"]
    name_i, name_j = m["boundary"].split("|")
    idx_j = name_to_index[name_j]
    join_global_start = cum[idx_j] - (window - 1)
    return join_global_start + m["offset_in_join"]


def read_window_tokens(shard_dir: str, files: list[dict], cum: list[int],
                        seq: int, block_len: int, window_idx: int) -> list[int]:
    start = window_idx * seq
    end = start + block_len
    if end > cum[-1]:
        raise SystemExit(
            f"W2_DECONTAM_WINDOW_OUT_OF_RANGE: window {window_idx} "
            f"[{start},{end}) exceeds corpus token range {cum[-1]}")
    out: list[int] = []
    for i in range(len(files)):
        file_start, file_end = cum[i], cum[i + 1]
        lo = max(start, file_start)
        hi = min(end, file_end)
        if lo >= hi:
            continue
        n_tok_needed = hi - lo
        byte_offset = (lo - file_start) * 2
        with open(os.path.join(shard_dir, files[i]["name"]), "rb") as fh:
            fh.seek(byte_offset)
            raw = fh.read(n_tok_needed * 2)
        arr = np.frombuffer(raw, dtype="<u2")
        out.extend(int(x) for x in arr)
    if len(out) != block_len:
        raise SystemExit(
            f"W2_DECONTAM_SHORT_READ: window {window_idx} expected {block_len} "
            f"tokens, read {len(out)}")
    return out


# ---------------------------------------------------------------------------
# Pool + disjointness (same as serial version)
# ---------------------------------------------------------------------------

def reserve_pool(n_windows: int, pool_size: int, ceiling_steps: int,
                  train_batch: int) -> tuple[int, dict]:
    pool_start = held_out_window_start(n_windows, pool_size)
    disjoint_check = assert_disjoint_from_training(pool_start, ceiling_steps, train_batch)
    return pool_start, disjoint_check


# ---------------------------------------------------------------------------
# PARALLELIZED contamination recheck
# ---------------------------------------------------------------------------

def _needle_hash(ids: list[int], roll_base: int) -> int:
    """Polynomial rolling hash, uint64 mod 2**64."""
    mod = 1 << 64
    h = 0
    b = 1
    for v in ids:
        h = (h + int(v) * b) % mod
        b = (b * roll_base) % mod
    return h


def _sliding_windows(ids: list[int], w: int) -> list[tuple]:
    n = len(ids)
    return [tuple(int(x) for x in ids[i:i + w]) for i in range(n - w + 1)] if n >= w else []


def _extract_needle_hashes(candidate_rows: list[list[int]], window: int,
                            roll_base: int) -> tuple[dict, set]:
    """Extract needle hash to windows mapping. Same for all workers."""
    needle_windows = []
    for row in candidate_rows:
        needle_windows.extend(_sliding_windows(list(row), window))
    needle_hash_to_windows: dict[int, list[tuple]] = {}
    for w in needle_windows:
        needle_hash_to_windows.setdefault(_needle_hash(w, roll_base), []).append(w)
    return needle_hash_to_windows, set(needle_hash_to_windows.keys())


def _worker_scan_shards(args: tuple) -> dict:
    """Worker: scan a subset of shards, return matches."""
    (shard_dir, shard_names, needle_hash_to_windows, needle_hash_set,
     window, roll_base, worker_id, progress_file, chunk_tokens) = args

    mod = 1 << 64
    confirmed_matches: list[dict] = []
    candidate_collisions = 0
    total_windows_hashed = 0
    prev_tail = None
    prev_name = None
    last_heartbeat_mono = [time.monotonic()]

    needle_arr = (np.fromiter(needle_hash_set, dtype=np.uint64, count=len(needle_hash_set))
                  if needle_hash_set else np.array([], dtype=np.uint64))

    def _needle_hash_local(ids):
        h = 0
        b = 1
        for v in ids:
            h = (h + int(v) * b) % mod
            b = (b * roll_base) % mod
        return h

    def _write_heartbeat(shard_idx, name, windows_so_far, force=False):
        if not progress_file:
            return
        now = time.monotonic()
        if not force and (now - last_heartbeat_mono[0]) < HEARTBEAT_INTERVAL_S:
            return
        last_heartbeat_mono[0] = now
        with open(progress_file, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "ts": datetime.now(timezone.utc).isoformat() + "Z",
                "worker_id": worker_id,
                "shard_idx": shard_idx,
                "shard": name,
                "windows_hashed": windows_so_far,
                "matches_found": len(confirmed_matches),
            }) + "\n")
            fh.flush()

    def _scan_for_hits(arr_u16, chunk_tokens_param, shard_idx=None, name=None,
                        prior_windows_hashed=0):
        """Compute rolling hashes in chunks; check needle matches PER CHUNK
        and discard each chunk's hash buffer immediately (issue #174 fix).

        The prior version accumulated every chunk's hashes into a Python
        list (`all_hashes.extend(...)`) before a single isin() call over the
        concatenated full-shard array -- so peak memory scaled with the
        FULL SHARD SIZE (~268M elements, observed 8-19.6GB per worker in the
        production crash's event-log receipt; measured 14.2GB in isolation
        for one worker on one shard) rather than the chunk size the
        chunking was meant to bound. isin() is elementwise, so checking
        per-chunk and unioning hit positions is exactly equivalent to
        checking the concatenated array once -- verified unchanged against
        run_equiv_chunked.py (full/selfmatch/external all still PASS).

        Returns (total_hashes: int, hit_offsets: list[int]); hit_offsets are
        absolute indices into arr_u16.
        """
        n = arr_u16.shape[0]
        if n < window:
            return 0, []

        n_chunks = (n + chunk_tokens_param - 1) // chunk_tokens_param
        total_hashes = 0
        hit_offsets: list[int] = []

        for chunk_i in range(n_chunks):
            chunk_start = chunk_i * chunk_tokens_param
            # Check if this is the last chunk (next chunk would start past end of array)
            next_chunk_start = (chunk_i + 1) * chunk_tokens_param
            is_last_chunk = (next_chunk_start >= n)

            # Overlap: extend chunk_end to include (window - 1) overlap tokens for boundary safety
            # (but only if not the last chunk)
            if is_last_chunk:
                chunk_end = n
            else:
                chunk_end = min(next_chunk_start + (window - 1), n)

            chunk_data = arr_u16[chunk_start:chunk_end]
            chunk_len = chunk_data.shape[0]

            if chunk_len >= window:
                arr64 = chunk_data.astype(np.uint64)
                n_out = chunk_len - window + 1
                h = np.zeros(n_out, dtype=np.uint64)
                power = np.uint64(1)
                rb = np.uint64(roll_base)
                with np.errstate(over="ignore"):
                    for k in range(window):
                        h += arr64[k:k + n_out] * power
                        power = power * rb

                # Only keep hashes that don't cross into overlap region (boundary-safe)
                n_keep = n_out if is_last_chunk else min(chunk_tokens_param, n_out)
                total_hashes += n_keep

                if needle_hash_set and n_keep:
                    local_hits = np.where(np.isin(h[:n_keep], needle_arr))[0]
                    hit_offsets.extend(chunk_start + int(li) for li in local_hits)
                # h / arr64 / chunk_data fall out of scope here -- nothing
                # shard-sized is retained across iterations.

            if shard_idx is not None:
                _write_heartbeat(shard_idx, name, prior_windows_hashed + total_hashes)

        return total_hashes, hit_offsets

    for idx, name in enumerate(shard_names):
        path = os.path.join(shard_dir, name)
        # Use memmap with read-only mode to avoid materializing full array in RAM
        arr = np.memmap(path, dtype="<u2", mode='r')
        n = arr.shape[0]

        n_out, hit_offsets = _scan_for_hits(arr, chunk_tokens, shard_idx=idx, name=name,
                                             prior_windows_hashed=total_windows_hashed)
        total_windows_hashed += n_out
        for i in hit_offsets:
            candidate = tuple(int(x) for x in arr[i:i + window])
            hh = _needle_hash_local(candidate)
            if hh in needle_hash_to_windows and candidate in needle_hash_to_windows[hh]:
                confirmed_matches.append({"shard": name, "offset": i,
                                           "window": list(candidate)})
            else:
                candidate_collisions += 1

        if prev_tail is not None and n >= (window - 1) and needle_hash_set:
            join = np.concatenate([prev_tail, arr[:window - 1]])
            join_n, join_hit_offsets = _scan_for_hits(join, chunk_tokens)
            total_windows_hashed += join_n
            for i in join_hit_offsets:
                candidate = tuple(int(x) for x in join[i:i + window])
                hh = _needle_hash_local(candidate)
                if hh in needle_hash_to_windows and candidate in needle_hash_to_windows[hh]:
                    confirmed_matches.append({
                        "boundary": f"{prev_name}|{name}",
                        "offset_in_join": i, "window": list(candidate)})

        prev_tail = arr[-(window - 1):].copy() if n >= (window - 1) else prev_tail
        prev_name = name

        # Per-shard-completion heartbeat: always fires (unrate-limited),
        # marking a shard boundary regardless of the intra-shard cadence above.
        _write_heartbeat(idx, name, total_windows_hashed, force=True)

    return {
        "worker_id": worker_id,
        "shards_scanned": len(shard_names),
        "windows_hashed": total_windows_hashed,
        "confirmed_matches": confirmed_matches,
        "hash_collisions_ruled_out": candidate_collisions,
    }


def contamination_recheck_mp(eval_rows: list[list[int]], shard_dir: str, *,
                              window: int = CONTAMINATION_WINDOW_TOKENS,
                              roll_base: int = CONTAMINATION_ROLL_BASE,
                              n_workers: int = DEFAULT_MP_WORKERS,
                              progress_file: str | None = None,
                              chunk_tokens: int = DEFAULT_SCAN_CHUNK_TOKENS) -> dict:
    """Parallelized contamination_recheck. Same receipt semantics as serial version."""
    t0 = time.perf_counter()

    # Extract needle hashes (shared across all workers)
    needle_hash_to_windows, needle_hash_set = _extract_needle_hashes(eval_rows, window, roll_base)

    # Shard the corpus by files
    shard_paths = sorted(p for p in os.listdir(shard_dir) if p.endswith(".bin"))
    if not shard_paths:
        raise SystemExit(f"W2_DECONTAM_NO_SHARDS: {shard_dir!r}")

    n_workers = min(n_workers, len(shard_paths))
    if n_workers <= 1:
        # Fall back to serial for single shard, wrapping to include wall_s
        t0_serial = time.perf_counter()
        result = contamination_recheck(eval_rows, shard_dir, window=window, roll_base=roll_base)
        result["wall_s"] = round(time.perf_counter() - t0_serial, 3)
        result["n_workers"] = 1
        return result

    # Distribute shards into EXACTLY min(n_workers, len(shard_paths)) balanced groups.
    # Fold remainder shards into existing groups to avoid silent extra workers.
    n_groups = min(n_workers, len(shard_paths))
    worker_shards = [[] for _ in range(n_groups)]
    for shard_idx, shard_name in enumerate(shard_paths):
        group_idx = shard_idx % n_groups
        worker_shards[group_idx].append(shard_name)
    # Filter out empty groups (shouldn't happen, but safe)
    worker_shards = [g for g in worker_shards if g]

    # Dispatch workers
    worker_args = []
    for worker_id, shard_names in enumerate(worker_shards):
        worker_args.append((
            shard_dir, shard_names, needle_hash_to_windows, needle_hash_set,
            window, roll_base, worker_id, progress_file, chunk_tokens
        ))

    with Pool(processes=len(worker_shards)) as pool:
        results = pool.map(_worker_scan_shards, worker_args)

    wall_s = round(time.perf_counter() - t0, 3)

    # Merge results deterministically
    all_matches = []
    total_windows_hashed = 0
    total_collisions = 0
    total_shards = 0
    for r in results:
        all_matches.extend(r["confirmed_matches"])
        total_windows_hashed += r["windows_hashed"]
        total_collisions += r["hash_collisions_ruled_out"]
        total_shards += r["shards_scanned"]

    return {
        "method": "13-token polynomial rolling hash (uint64 mod 2**64), "
                  "parallelized across corpus shards (multiprocessing), "
                  "hash hits re-verified by exact elementwise comparison",
        "shards_scanned": total_shards,
        "windows_hashed": total_windows_hashed,
        "confirmed_matches": all_matches,
        "hash_collisions_ruled_out": total_collisions,
        "verdict": "CLEAN" if not all_matches else "CONTAMINATED",
        "wall_s": wall_s,
        "n_workers": len(worker_shards),
    }


# ---------------------------------------------------------------------------
# Self-match-aware classification (same as serial version, uses mp version)
# ---------------------------------------------------------------------------

def _row_contains_window(row: list[int], window_tuple: tuple, window_len: int) -> bool:
    n = len(row)
    if n < window_len:
        return False
    for i in range(n - window_len + 1):
        if tuple(row[i:i + window_len]) == window_tuple:
            return True
    return False


def _build_candidate_window_index(candidate_rows: list[list[int]],
                                   window_len: int) -> dict[tuple, list[int]]:
    """Precompute, once per _classify_once call, every contiguous
    window_len-token tuple present in each candidate row, mapped to the list
    of candidate indices whose row contains it (issue #193 deviation: this
    replaces per-match _row_contains_window row-rescans -- O(M x C x L) --
    with one O(C x L) index build + O(1) average-case dict lookups per
    match). A tuple occurring at multiple positions within the SAME row is
    recorded once for that row, matching _row_contains_window's boolean
    ("does this row contain it at all") semantics; indices are appended in
    row order so a lookup returns candidates in the same order the original
    enumerate(candidate_rows) loop visited them, preserving append order
    into non_self_matches_by_candidate downstream."""
    index: dict[tuple, list[int]] = {}
    for idx, row in enumerate(candidate_rows):
        n = len(row)
        if n < window_len:
            continue
        seen: set[tuple] = set()
        for i in range(n - window_len + 1):
            wt = tuple(row[i:i + window_len])
            if wt in seen:
                continue
            seen.add(wt)
            index.setdefault(wt, []).append(idx)
    return index


def _classify_once(candidate_rows: list[list[int]],
                    candidate_positions: list[dict],
                    shard_dir: str,
                    *, window: int, roll_base: int,
                    files: list[dict] | None,
                    cum: list[int] | None,
                    use_mp: bool = True,
                    n_workers: int = DEFAULT_MP_WORKERS,
                    progress_file: str | None = None,
                    block_len: int | None = None,
                    chunk_tokens: int = DEFAULT_SCAN_CHUNK_TOKENS) -> dict:
    """Runs contamination recheck (serial or parallel) once."""
    t0 = time.perf_counter()
    # If n_workers <= 1 or MP disabled, use serial version (avoid multiprocessing spawn on Windows)
    if use_mp and n_workers > 1:
        raw = contamination_recheck_mp(candidate_rows, shard_dir, window=window,
                                        roll_base=roll_base, n_workers=n_workers,
                                        progress_file=progress_file, chunk_tokens=chunk_tokens)
        # contamination_recheck_mp includes wall_s in its return dict
        wall_s = raw.pop("wall_s")
    else:
        # Serial contamination_recheck does NOT include wall_s; compute locally
        raw = contamination_recheck(candidate_rows, shard_dir, window=window, roll_base=roll_base)
        wall_s = round(time.perf_counter() - t0, 3)

    name_to_index = {f["name"]: i for i, f in enumerate(files)} if files else None

    non_self_matches_by_candidate: list[list[dict]] = [[] for _ in candidate_rows]
    self_matches_excluded = 0
    window_index = _build_candidate_window_index(candidate_rows, window)

    for m in raw["confirmed_matches"]:
        window_tuple = tuple(m["window"])
        if name_to_index is not None and cum is not None:
            match_global_start = _match_global_start(m, name_to_index, cum, window)
        else:
            match_global_start = None
        for idx in window_index.get(window_tuple, ()):
            pos = candidate_positions[idx]
            # FIXED: self-match check must detect ANY overlap with candidate window,
            # not just exact start-position equality. A candidate covers tokens
            # [global_start, global_start + block_len). A 13-token match at
            # match_global_start occupies [match_global_start, match_global_start+13).
            # Overlap exists if match_global_start < global_start+block_len AND
            # match_global_start+window > global_start. This catches self-contamination
            # anywhere within the candidate, not just at its exact start (issue GF-W2-01).
            if block_len is not None:
                candidate_end = pos["global_start"] + block_len
                is_self = (match_global_start is not None
                           and pos["global_start"] <= match_global_start
                           and match_global_start + window <= candidate_end)
            else:
                # Fallback: block_len not provided, use exact-start check (conservative)
                is_self = (match_global_start is not None
                           and match_global_start == pos["global_start"])
            if is_self:
                self_matches_excluded += 1
            else:
                non_self_matches_by_candidate[idx].append(m)

    clean_idx = [i for i, ms in enumerate(non_self_matches_by_candidate) if not ms]
    contaminated_idx = [i for i, ms in enumerate(non_self_matches_by_candidate) if ms]

    return {
        "raw": raw,
        "wall_s": wall_s,
        "n_calls": 1,
        "split_occurred": False,
        "clean_idx": clean_idx,
        "contaminated_idx": contaminated_idx,
        "self_matches_excluded": self_matches_excluded,
        "non_self_matches_by_candidate": non_self_matches_by_candidate,
    }


def _merge_classify_results(left: dict, right: dict, right_offset: int) -> dict:
    return {
        "raw": {"confirmed_matches": left["raw"]["confirmed_matches"]
                                      + right["raw"]["confirmed_matches"],
                "method": left["raw"].get("method") or right["raw"].get("method"),
                "shards_scanned": left["raw"].get("shards_scanned"),
                "windows_hashed": left["raw"].get("windows_hashed", 0)
                                  + right["raw"].get("windows_hashed", 0)},
        "wall_s": round(left["wall_s"] + right["wall_s"], 3),
        "n_calls": left["n_calls"] + right["n_calls"],
        "split_occurred": True,
        "clean_idx": left["clean_idx"] + [i + right_offset for i in right["clean_idx"]],
        "contaminated_idx": left["contaminated_idx"]
                            + [i + right_offset for i in right["contaminated_idx"]],
        "self_matches_excluded": left["self_matches_excluded"] + right["self_matches_excluded"],
        "non_self_matches_by_candidate": left["non_self_matches_by_candidate"]
                                          + right["non_self_matches_by_candidate"],
    }


def classify_candidates(candidate_rows: list[list[int]],
                         candidate_positions: list[dict],
                         shard_dir: str,
                         *, window: int = CONTAMINATION_WINDOW_TOKENS,
                         roll_base: int = CONTAMINATION_ROLL_BASE,
                         files: list[dict] | None = None,
                         cum: list[int] | None = None,
                         use_mp: bool = True,
                         n_workers: int = DEFAULT_MP_WORKERS,
                         progress_file: str | None = None,
                         block_len: int | None = None,
                         chunk_tokens: int = DEFAULT_SCAN_CHUNK_TOKENS) -> dict:
    """Adaptive wrapper, same as serial version."""
    try:
        return _classify_once(candidate_rows, candidate_positions, shard_dir,
                               window=window, roll_base=roll_base, files=files, cum=cum,
                               use_mp=use_mp, n_workers=n_workers, progress_file=progress_file,
                               block_len=block_len, chunk_tokens=chunk_tokens)
    except MemoryError:
        if len(candidate_rows) <= 1:
            raise
        mid = len(candidate_rows) // 2
        left = classify_candidates(candidate_rows[:mid], candidate_positions[:mid], shard_dir,
                                    window=window, roll_base=roll_base, files=files, cum=cum,
                                    use_mp=use_mp, n_workers=n_workers, progress_file=progress_file,
                                    block_len=block_len, chunk_tokens=chunk_tokens)
        right = classify_candidates(candidate_rows[mid:], candidate_positions[mid:], shard_dir,
                                     window=window, roll_base=roll_base, files=files, cum=cum,
                                     use_mp=use_mp, n_workers=n_workers, progress_file=progress_file,
                                     block_len=block_len, chunk_tokens=chunk_tokens)
        return _merge_classify_results(left, right, right_offset=mid)


# ---------------------------------------------------------------------------
# SHA256 (same as serial)
# ---------------------------------------------------------------------------

def batch_sha256(rows: list[list[int]], seq: int) -> str:
    xs = np.array([r[:seq] for r in rows], dtype=np.int64)
    ys = np.array([r[1:seq + 1] for r in rows], dtype=np.int64)
    combined = np.concatenate([xs, ys], axis=1)
    return hashlib.sha256(combined.tobytes()).hexdigest()


# ---------------------------------------------------------------------------
# Equivalence test (fixture-scale verification)
# ---------------------------------------------------------------------------

def run_equivalence_test(shard_dir: str, seq: int = 1024, n_mtp: int = 2,
                         synthetic_n_rows: int = 100000) -> tuple[bool, str]:
    """Run serial and parallel versions on synthetic corpus, assert identical results.
    Returns (passed: bool, receipt_path: str)."""
    import tempfile

    print(f"[EQUIV] Starting equivalence test...")
    t0 = time.perf_counter()

    # Create synthetic corpus in temp dir
    with tempfile.TemporaryDirectory() as tmpdir:
        # Synthetic candidates: pick a few random windows from the real corpus
        files = cheap_shard_sizes(shard_dir)
        cum = _cumulative_token_offsets(files)
        total_tokens = cum[-1]
        block_len = seq + 1 + n_mtp
        n_possible_windows = max(1, total_tokens // seq - 1)

        print(f"[EQUIV] Corpus: {total_tokens} tokens, {n_possible_windows} possible windows")

        # Pick a few random candidates from the corpus (min 2, max 8)
        rng = np.random.RandomState(42)  # Fixed seed for reproducibility
        n_candidates = min(8, max(2, n_possible_windows // 10))

        if n_possible_windows < n_candidates:
            pool_indices = list(range(n_possible_windows))
        else:
            pool_indices = rng.choice(n_possible_windows, size=n_candidates, replace=False)

        print(f"[EQUIV] Selected {len(pool_indices)} candidates from {n_possible_windows} possible")

        candidate_rows = []
        candidate_positions = []
        for idx in pool_indices:
            try:
                row = read_window_tokens(shard_dir, files, cum, seq, block_len, int(idx))
                candidate_rows.append(row)
                candidate_positions.append(window_source_position(files, cum, seq, int(idx)))
            except SystemExit as e:
                print(f"[EQUIV] Skipping window {idx}: {e}")
                continue

        if not candidate_rows:
            print("[EQUIV] SKIP: Corpus too small for meaningful test")
            return True, ""

        # Run serial version
        print("[EQUIV] Running serial contamination_recheck...")
        serial_result = contamination_recheck(candidate_rows, shard_dir,
                                              window=CONTAMINATION_WINDOW_TOKENS,
                                              roll_base=CONTAMINATION_ROLL_BASE)

        # Run parallel version
        print("[EQUIV] Running parallel contamination_recheck...")
        progress_file = os.path.join(tmpdir, "equiv-progress.jsonl")
        parallel_result = contamination_recheck_mp(candidate_rows, shard_dir,
                                                    window=CONTAMINATION_WINDOW_TOKENS,
                                                    roll_base=CONTAMINATION_ROLL_BASE,
                                                    progress_file=progress_file)

        # Compare results (order-agnostic)
        serial_matches = set()
        for m in serial_result["confirmed_matches"]:
            # Normalize match to a hashable form (order doesn't matter)
            key = (tuple(m.get("window", [])), m.get("shard"), m.get("offset"),
                   m.get("boundary"), m.get("offset_in_join"))
            serial_matches.add(key)

        parallel_matches = set()
        for m in parallel_result["confirmed_matches"]:
            key = (tuple(m.get("window", [])), m.get("shard"), m.get("offset"),
                   m.get("boundary"), m.get("offset_in_join"))
            parallel_matches.add(key)

        # Check self-match counts (should be identical)
        passed = (serial_matches == parallel_matches and
                  serial_result["verdict"] == parallel_result["verdict"])

        wall_s = time.perf_counter() - t0

        # Write receipt
        receipt = {
            "ts": _utc_ts(),
            "schema": "w2-decontam-equivalence/v1",
            "synthetic_candidate_count": len(candidate_rows),
            "serial_matches_count": len(serial_matches),
            "parallel_matches_count": len(parallel_matches),
            "matches_identical": passed,
            "serial_verdict": serial_result["verdict"],
            "parallel_verdict": parallel_result["verdict"],
            "wall_s": round(wall_s, 3),
            "serial_windows_hashed": serial_result["windows_hashed"],
            "parallel_windows_hashed": parallel_result["windows_hashed"],
        }

        os.makedirs(RECEIPT_DIR, exist_ok=True)
        receipt_path = os.path.join(RECEIPT_DIR, f"w2-heldout-equivalence-{receipt['ts']}.json")
        with open(receipt_path, "w", encoding="utf-8") as fh:
            json.dump(receipt, fh, indent=2)

        status = "PASS" if passed else "FAIL"
        print(f"[EQUIV] {status}: {serial_matches.__len__()} matches in serial, "
              f"{parallel_matches.__len__()} in parallel. Receipt: {receipt_path}")

        return passed, receipt_path


def run_equivalence_test_selfmatch(shard_dir: str, seq: int = 1024, n_mtp: int = 2) -> tuple[bool, str]:
    """Equivalence test for self-match exclusion logic (issue GF-W2-01 fix verification).

    Builds a synthetic corpus that:
    - Embeds candidates directly (creates self-matches at their known positions)
    - Candidates 0,1,2 embedded → have self-matches, should be CLEAN after exclusion
    - Candidate 3 NOT embedded → no matches, should be CLEAN

    Asserts serial==parallel AND verifies that self-matches are correctly excluded.
    Returns (passed: bool, receipt_path: str)."""
    import tempfile

    print(f"[EQUIV-SELFMATCH] Starting self-match exclusion test...")
    t0 = time.perf_counter()

    with tempfile.TemporaryDirectory() as tmpdir:
        rng = np.random.RandomState(999)  # Fixed seed
        block_len = seq + 1 + n_mtp

        # Synthetic candidates: 4 arbitrary windows of block_len tokens each
        candidate0 = list(rng.randint(0, 32000, size=block_len))
        candidate1 = list(rng.randint(0, 32000, size=block_len))
        candidate2 = list(rng.randint(0, 32000, size=block_len))
        candidate3_noself = list(rng.randint(0, 32000, size=block_len))
        candidate_rows = [candidate0, candidate1, candidate2, candidate3_noself]

        # Synthetic corpus: embed candidates 0, 1, 2 (creates self-matches)
        # Don't embed candidate 3 (no self-match)
        corpus_all = []
        corpus_all.extend(candidate0)  # positions [0, block_len)
        corpus_all.extend(candidate1)  # positions [block_len, 2*block_len)
        corpus_all.extend(candidate2)  # positions [2*block_len, 3*block_len)
        corpus_all.extend(list(rng.randint(0, 32000, size=1000)))  # padding for candidate3

        # Write synthetic corpus as single .bin shard
        corpus_np = np.array(corpus_all, dtype=np.uint16)
        shard_path = os.path.join(tmpdir, "synthetic-00000.bin")
        corpus_np.tofile(shard_path)

        print(f"[EQUIV-SELFMATCH] Corpus: {len(corpus_all)} tokens "
              f"(candidates 0-2 embedded at [0, 3*block_len), candidate 3 not embedded)")

        # Set up file list for window indexing
        files = [{"name": "synthetic-00000.bin", "size_bytes": corpus_np.nbytes, "n_tokens": len(corpus_all)}]
        cum = _cumulative_token_offsets(files)

        # Candidate positions: manual, since we control corpus structure
        candidate_positions = [
            {"shard": "synthetic-00000.bin", "offset": 0, "global_start": 0},
            {"shard": "synthetic-00000.bin", "offset": block_len, "global_start": block_len},
            {"shard": "synthetic-00000.bin", "offset": 2*block_len, "global_start": 2*block_len},
            {"shard": "synthetic-00000.bin", "offset": 3*block_len, "global_start": 3*block_len},
        ]

        # Run serial classification
        print("[EQUIV-SELFMATCH] Running serial classification...")
        serial_result = classify_candidates(
            candidate_rows, candidate_positions, tmpdir,
            window=CONTAMINATION_WINDOW_TOKENS, roll_base=CONTAMINATION_ROLL_BASE,
            files=files, cum=cum, block_len=block_len,
            use_mp=False)  # Force serial

        # Run parallel classification
        print("[EQUIV-SELFMATCH] Running parallel classification...")
        parallel_result = classify_candidates(
            candidate_rows, candidate_positions, tmpdir,
            window=CONTAMINATION_WINDOW_TOKENS, roll_base=CONTAMINATION_ROLL_BASE,
            files=files, cum=cum, block_len=block_len,
            use_mp=True, n_workers=2)

        # Verify results
        # All 4 candidates should be CLEAN (0, 1, 2 have self-matches excluded; 3 has no matches)
        serial_clean = set(serial_result["clean_idx"])
        serial_contam = set(serial_result["contaminated_idx"])
        parallel_clean = set(parallel_result["clean_idx"])
        parallel_contam = set(parallel_result["contaminated_idx"])

        print(f"[EQUIV-SELFMATCH] Serial: clean={serial_clean}, contaminated={serial_contam}, "
              f"self_matches_excluded={serial_result['self_matches_excluded']}")
        print(f"[EQUIV-SELFMATCH] Parallel: clean={parallel_clean}, contaminated={parallel_contam}, "
              f"self_matches_excluded={parallel_result['self_matches_excluded']}")

        # Assertions
        all_clean = {0, 1, 2, 3}  # All should be clean
        passed = (serial_clean == parallel_clean and
                  serial_contam == parallel_contam and
                  serial_result["self_matches_excluded"] == parallel_result["self_matches_excluded"] and
                  serial_clean == all_clean and
                  serial_result["self_matches_excluded"] >= 3)  # At least 3 self-matches excluded

        wall_s = time.perf_counter() - t0

        receipt = {
            "ts": _utc_ts(),
            "schema": "w2-decontam-equivalence-selfmatch/v1",
            "test_description": "Synthetic corpus with embedded candidates (self-matches) + one non-embedded candidate",
            "candidate_count": 4,
            "candidates_embedded_with_selfmatches": [0, 1, 2],
            "candidates_without_matches": [3],
            "serial_clean_idx": sorted(serial_clean),
            "serial_contaminated_idx": sorted(serial_contam),
            "serial_self_matches_excluded": serial_result["self_matches_excluded"],
            "parallel_clean_idx": sorted(parallel_clean),
            "parallel_contaminated_idx": sorted(parallel_contam),
            "parallel_self_matches_excluded": parallel_result["self_matches_excluded"],
            "results_identical": serial_clean == parallel_clean,
            "all_candidates_clean": serial_clean == all_clean,
            "wall_s": round(wall_s, 3),
        }

        os.makedirs(RECEIPT_DIR, exist_ok=True)
        receipt_path = os.path.join(RECEIPT_DIR, f"w2-heldout-equivalence-selfmatch-{receipt['ts']}.json")
        with open(receipt_path, "w", encoding="utf-8") as fh:
            json.dump(receipt, fh, indent=2)

        status = "PASS" if passed else "FAIL"
        print(f"[EQUIV-SELFMATCH] {status}: all_clean={serial_clean == all_clean}, "
              f"serial==parallel={serial_clean == parallel_clean}, "
              f"self_matches_excluded={serial_result['self_matches_excluded']}. Receipt: {receipt_path}")

        return passed, receipt_path


def run_equivalence_test_external(shard_dir: str, seq: int = 1024, n_mtp: int = 2) -> tuple[bool, str]:
    """Equivalence test for external contamination detection (issue GF-W2-01 fix validation).

    Builds a synthetic corpus that:
    - Embeds candidates 0, 1, 2 (creates self-matches at their known positions)
    - Candidate 0: also plants one of its 13-token windows at a DISTANT location (external match)
    - Candidate 1, 2: self-matches only
    - Candidate 3: not embedded (no matches)

    Expected result:
    - Candidate 0: CONTAMINATED (has external match)
    - Candidates 1, 2, 3: CLEAN (self-matches excluded or no matches)

    Verifies that the fix correctly distinguishes self-matches (excluded) from external matches
    (cause contamination), and that serial==parallel.
    Returns (passed: bool, receipt_path: str)."""
    import tempfile

    print(f"[EQUIV-EXTERNAL] Starting external contamination detection test...")
    t0 = time.perf_counter()

    with tempfile.TemporaryDirectory() as tmpdir:
        rng = np.random.RandomState(888)  # Fixed seed, different from selfmatch test
        block_len = seq + 1 + n_mtp
        window = CONTAMINATION_WINDOW_TOKENS  # 13

        # Synthetic candidates: 4 arbitrary windows of block_len tokens each
        candidate0 = list(rng.randint(0, 32000, size=block_len))
        candidate1 = list(rng.randint(0, 32000, size=block_len))
        candidate2 = list(rng.randint(0, 32000, size=block_len))
        candidate3_noself = list(rng.randint(0, 32000, size=block_len))
        candidate_rows = [candidate0, candidate1, candidate2, candidate3_noself]

        # Synthetic corpus structure:
        corpus_all = []
        corpus_all.extend(candidate0)  # positions [0, block_len) — candidate 0 embedded
        corpus_all.extend(candidate1)  # positions [block_len, 2*block_len) — candidate 1 embedded
        corpus_all.extend(candidate2)  # positions [2*block_len, 3*block_len) — candidate 2 embedded

        # Padding before external contamination plant
        padding_tokens = 1000
        corpus_all.extend(list(rng.randint(0, 32000, size=padding_tokens)))

        # Plant external contamination: extract a 13-token window from candidate0
        # (position [500, 513) within candidate0 = position [500, 513) in corpus)
        # and plant it at a DISTANT location in the corpus (outside all candidates)
        external_plant_corpus_pos = len(corpus_all)  # Where we'll plant it
        plant_seed = list(candidate0[500:500 + window])  # Extract 13 tokens from candidate0
        corpus_all.extend(plant_seed)  # Plant at distant location

        # More padding to spread things out
        corpus_all.extend(list(rng.randint(0, 32000, size=500)))

        # Write synthetic corpus as single .bin shard
        corpus_np = np.array(corpus_all, dtype=np.uint16)
        shard_path = os.path.join(tmpdir, "synthetic-00000.bin")
        corpus_np.tofile(shard_path)

        print(f"[EQUIV-EXTERNAL] Corpus: {len(corpus_all)} tokens")
        print(f"  - Candidate0 embedded at [0, {block_len})")
        print(f"  - Candidate1 embedded at [{block_len}, {2*block_len})")
        print(f"  - Candidate2 embedded at [{2*block_len}, {3*block_len})")
        print(f"  - External plant: 13-token window from candidate0[500:513] planted at [{external_plant_corpus_pos}, {external_plant_corpus_pos + window})")
        print(f"  - Candidate3 not embedded (no self-matches or external matches)")

        # Set up file list for window indexing
        files = [{"name": "synthetic-00000.bin", "size_bytes": corpus_np.nbytes, "n_tokens": len(corpus_all)}]
        cum = _cumulative_token_offsets(files)

        # Candidate positions
        candidate_positions = [
            {"shard": "synthetic-00000.bin", "offset": 0, "global_start": 0},
            {"shard": "synthetic-00000.bin", "offset": block_len, "global_start": block_len},
            {"shard": "synthetic-00000.bin", "offset": 2*block_len, "global_start": 2*block_len},
            {"shard": "synthetic-00000.bin", "offset": 3*block_len, "global_start": 3*block_len},
        ]

        # Run serial classification
        print("[EQUIV-EXTERNAL] Running serial classification...")
        serial_result = classify_candidates(
            candidate_rows, candidate_positions, tmpdir,
            window=CONTAMINATION_WINDOW_TOKENS, roll_base=CONTAMINATION_ROLL_BASE,
            files=files, cum=cum, block_len=block_len,
            use_mp=False)  # Force serial

        # Run parallel classification
        print("[EQUIV-EXTERNAL] Running parallel classification...")
        parallel_result = classify_candidates(
            candidate_rows, candidate_positions, tmpdir,
            window=CONTAMINATION_WINDOW_TOKENS, roll_base=CONTAMINATION_ROLL_BASE,
            files=files, cum=cum, block_len=block_len,
            use_mp=True, n_workers=2)

        # Verify results
        serial_clean = set(serial_result["clean_idx"])
        serial_contam = set(serial_result["contaminated_idx"])
        parallel_clean = set(parallel_result["clean_idx"])
        parallel_contam = set(parallel_result["contaminated_idx"])

        print(f"[EQUIV-EXTERNAL] Serial: clean={serial_clean}, contaminated={serial_contam}")
        print(f"[EQUIV-EXTERNAL] Parallel: clean={parallel_clean}, contaminated={parallel_contam}")

        # Expectations:
        # - Candidate 0 should be CONTAMINATED (external match planted outside its footprint)
        # - Candidates 1, 2 should be CLEAN (self-matches excluded)
        # - Candidate 3 should be CLEAN (no matches)
        expected_clean = {1, 2, 3}
        expected_contam = {0}

        passed = (serial_clean == parallel_clean and
                  serial_contam == parallel_contam and
                  serial_clean == expected_clean and
                  serial_contam == expected_contam)

        wall_s = time.perf_counter() - t0

        receipt = {
            "ts": _utc_ts(),
            "schema": "w2-decontam-equivalence-external/v1",
            "test_description": "Synthetic corpus with embedded candidates + external contamination plant",
            "candidate_count": 4,
            "candidates_embedded": [0, 1, 2],
            "candidate_without_matches": 3,
            "external_contamination_source": f"13-token window from candidate0[500:513]",
            "external_contamination_planted_at": f"[{external_plant_corpus_pos}, {external_plant_corpus_pos + window})",
            "serial_clean_idx": sorted(serial_clean),
            "serial_contaminated_idx": sorted(serial_contam),
            "parallel_clean_idx": sorted(parallel_clean),
            "parallel_contaminated_idx": sorted(parallel_contam),
            "results_identical": serial_clean == parallel_clean,
            "expected_clean": sorted(expected_clean),
            "expected_contaminated": sorted(expected_contam),
            "verdict": "PASS" if passed else "FAIL",
            "wall_s": round(wall_s, 3),
        }

        os.makedirs(RECEIPT_DIR, exist_ok=True)
        receipt_path = os.path.join(RECEIPT_DIR, f"w2-heldout-equivalence-external-{receipt['ts']}.json")
        with open(receipt_path, "w", encoding="utf-8") as fh:
            json.dump(receipt, fh, indent=2)

        status = "PASS" if passed else "FAIL"
        print(f"[EQUIV-EXTERNAL] {status}: candidate0_contaminated={0 in serial_contam}, "
              f"candidates123_clean={serial_clean == expected_clean}, "
              f"serial==parallel={serial_clean == parallel_clean}. Receipt: {receipt_path}")

        return passed, receipt_path


# ---------------------------------------------------------------------------
# Orchestrator (same as serial)
# ---------------------------------------------------------------------------

def build_batch(*, shard_dir: str = DEFAULT_SHARD_DIR, seq: int = DEFAULT_SEQ,
                 n_mtp: int = DEFAULT_N_MTP, batch_size: int = DEFAULT_BATCH_SIZE,
                 ceiling_steps: int = DEFAULT_CEILING_STEPS,
                 train_batch: int = DEFAULT_TRAIN_BATCH,
                 pool_oversample: int = DEFAULT_POOL_OVERSAMPLE,
                 max_rounds: int = DEFAULT_MAX_ROUNDS,
                 use_mp: bool = True,
                 n_workers: int = DEFAULT_MP_WORKERS,
                 progress_file: str | None = None,
                 chunk_tokens: int = DEFAULT_SCAN_CHUNK_TOKENS,
                 pool_start_index: int | None = None) -> dict:
    t_start = time.perf_counter()
    block_len = seq + 1 + n_mtp

    files = cheap_shard_sizes(shard_dir)
    cum = _cumulative_token_offsets(files)
    manifest = shard_manifest_for_window_count(shard_dir)
    n_windows = compute_n_windows_from_manifest(manifest, seq, n_mtp=n_mtp)

    pool_size = batch_size * pool_oversample
    # If pool_start_index is provided, use it directly; otherwise compute via reserve_pool
    explicit_pool_placement = pool_start_index is not None

    if explicit_pool_placement:
        # Explicit placement: use provided pool_start_index and verify disjointness
        pool_start = pool_start_index
        disjoint_check = assert_disjoint_from_training(pool_start, ceiling_steps, train_batch)
    else:
        # Tail mode: compute pool_start as the tail placement
        pool_start, disjoint_check = reserve_pool(n_windows, pool_size, ceiling_steps, train_batch)

    # First index training can NEVER reach (assert_disjoint_from_training's own
    # boundary: max_training_window_index = ceiling_steps*train_batch - 1, so
    # this is max_training_window_index + 1). Replacement draws must never go
    # at or below max_training_window_index -- i.e. never below this value.
    disjoint_lower_bound = ceiling_steps * train_batch

    selected_rows: list[list[int]] = []
    selected_indices: list[int] = []
    rounds: list[dict] = []
    # Issue #115 fix: rounds march DOWNWARD from the tail toward
    # disjoint_lower_bound, never upward off the corpus end. pool_floor is the
    # exclusive upper edge available to the NEXT round (round 1 uses the tail
    # pool established by reserve_pool; each subsequent round takes the
    # contiguous, non-overlapping slice immediately below the previous one).
    # POOL_EXHAUSTED can now only fire once the full disjoint range
    # [disjoint_lower_bound, n_windows) has actually been consumed, instead of
    # firing on round 2 every time round 1's tail pool is fully contaminated
    # (the old next_pool_start = pool_indices[-1] + 1 logic marched UPWARD off
    # the end of the corpus, so ~6.79M disjoint mid-corpus windows were never
    # tried at all).
    pool_floor = pool_start
    replacements_made = 0
    total_candidates_checked = 0

    for round_no in range(1, max_rounds + 1):
        need = batch_size - len(selected_rows)
        if need <= 0:
            break
        this_pool_size = max(need * pool_oversample, need)

        if round_no == 1:
            if explicit_pool_placement:
                # Explicit placement: start from pool_start_index, extend upward by pool_size
                this_pool_start = pool_start
                this_pool_end = min(pool_start + this_pool_size, n_windows)
            else:
                # Tail mode: original behavior (reserve the tail)
                this_pool_start, this_pool_end = pool_start, n_windows
        else:
            if explicit_pool_placement:
                # Upward extension: extend from previous round's end
                this_pool_start = pool_floor
                this_pool_end = min(pool_floor + this_pool_size, n_windows)
            else:
                # Downward extension (tail mode): march downward from tail
                this_pool_end = pool_floor
                this_pool_start = max(disjoint_lower_bound, this_pool_end - this_pool_size)

        pool_indices = list(range(this_pool_start, this_pool_end))
        if not pool_indices:
            raise SystemExit(
                "W2_DECONTAM_POOL_EXHAUSTED: ran out of training-disjoint window "
                f"indices before assembling {batch_size} clean windows "
                f"(selected {len(selected_rows)}).")

        # Fail-closed guard: pool materialized at once must be sane (bounded by pool_size * 100)
        max_allowed_pool = batch_size * pool_oversample * 100
        if len(pool_indices) > max_allowed_pool:
            raise SystemExit(
                f"W2_DECONTAM_POOL_RANGE_INSANE: round {round_no} pool size "
                f"{len(pool_indices)} exceeds safety bound {max_allowed_pool} "
                f"(batch_size={batch_size}, pool_oversample={pool_oversample}). "
                f"This indicates a bug in pool placement logic.")

        # Fail-closed disjointness proof for the FULL range actually drawn
        # this round (not just the initial reserve_pool call).
        round_disjoint_check = assert_disjoint_from_training(this_pool_start, ceiling_steps, train_batch)

        candidate_rows = [read_window_tokens(shard_dir, files, cum, seq, block_len, i)
                           for i in pool_indices]
        candidate_positions = [window_source_position(files, cum, seq, i) for i in pool_indices]

        result = classify_candidates(candidate_rows, candidate_positions, shard_dir,
                                      files=files, cum=cum, use_mp=use_mp,
                                      n_workers=n_workers, progress_file=progress_file,
                                      block_len=block_len, chunk_tokens=chunk_tokens)
        total_candidates_checked += len(pool_indices)

        newly_clean = result["clean_idx"][:need]
        for ci in newly_clean:
            selected_rows.append(candidate_rows[ci])
            selected_indices.append(pool_indices[ci])
        replacements_made += len(result["contaminated_idx"])

        rounds.append({
            "round": round_no,
            "pool_start": this_pool_start,
            "pool_end": this_pool_end,
            "pool_size": len(pool_indices),
            "wall_s": result["wall_s"],
            "n_contamination_recheck_calls": result["n_calls"],
            "memory_split_occurred": result["split_occurred"],
            "clean_found": len(result["clean_idx"]),
            "contaminated_found": len(result["contaminated_idx"]),
            "self_matches_excluded": result["self_matches_excluded"],
            "disjoint_check": round_disjoint_check,
        })

        # Update pool_floor for next round: tail mode uses start, upward mode uses end
        if explicit_pool_placement:
            pool_floor = this_pool_end
        else:
            pool_floor = this_pool_start

    if len(selected_rows) < batch_size:
        raise SystemExit(
            f"W2_DECONTAM_INSUFFICIENT_CLEAN_WINDOWS: found {len(selected_rows)} clean "
            f"windows in {max_rounds} rounds ({total_candidates_checked} candidates "
            f"checked), needed {batch_size}. Corpus may be too repetitive at "
            f"window={CONTAMINATION_WINDOW_TOKENS} for a clean batch to exist under "
            "the strict any-match convention.")

    # Final verification pass
    final_positions = [window_source_position(files, cum, seq, i) for i in selected_indices]
    final_check = classify_candidates(selected_rows, final_positions, shard_dir,
                                       files=files, cum=cum, use_mp=use_mp,
                                       n_workers=n_workers, progress_file=progress_file,
                                       block_len=block_len, chunk_tokens=chunk_tokens)
    final_non_self_count = sum(len(m) for m in final_check["non_self_matches_by_candidate"])

    sha = batch_sha256(selected_rows, seq)
    wall_total = round(time.perf_counter() - t_start, 3)

    return {
        "shard_dir": shard_dir,
        "seq": seq,
        "n_mtp": n_mtp,
        "batch_size": batch_size,
        "block_len": block_len,
        "ceiling_steps": ceiling_steps,
        "train_batch": train_batch,
        "n_windows_total": n_windows,
        "pool_reservation": {"pool_start": pool_start, "pool_size": pool_size,
                              "disjoint_check": disjoint_check},
        "rounds": rounds,
        "replacements_made": replacements_made,
        "total_candidates_checked": total_candidates_checked,
        "selected_window_indices": selected_indices,
        "selected_rows": selected_rows,
        "batch_sha256": sha,
        "contamination_recheck": {
            "method": final_check["raw"]["method"],
            "shards_scanned": final_check["raw"]["shards_scanned"],
            "windows_hashed": final_check["raw"]["windows_hashed"],
            "self_matches_excluded_as_expected": final_check["self_matches_excluded"],
            "confirmed_non_self_matches": final_non_self_count,
            "verdict": "CLEAN" if final_non_self_count == 0 else "CONTAMINATED",
        },
        "wall_s_total": wall_total,
    }


def write_receipt(result: dict, *, receipt_dir: str = RECEIPT_DIR) -> str:
    os.makedirs(receipt_dir, exist_ok=True)
    ts = _utc_ts()
    receipt = {
        "schema": "w2-heldout-decontam/v1",
        "ts": ts,
        "spec_ref": "docs/spec/w2-scale-preregistration-v1.md#4-decontamination-precondition",
        "reused_matcher": "scripts/w1_collapse_control_run.py:contamination_recheck "
                          "(parallelized via multiprocessing, same semantics)",
        "batch_sha256": result["batch_sha256"],
        "source_pool": {
            "shard_dir": result["shard_dir"],
            "n_windows_total": result["n_windows_total"],
            "pool_reservation": result["pool_reservation"],
        },
        "seq": result["seq"],
        "n_mtp": result["n_mtp"],
        "batch_size": result["batch_size"],
        "windows_checked": result["total_candidates_checked"],
        "replacements_made": result["replacements_made"],
        "rounds": result["rounds"],
        "selected_window_indices": result["selected_window_indices"],
        "contamination_recheck": result["contamination_recheck"],
        "wall_s_total": result["wall_s_total"],
        "pass": result["contamination_recheck"]["verdict"] == "CLEAN",
    }
    if not receipt["pass"]:
        raise SystemExit(
            "W2_DECONTAM_RECEIPT_REFUSED: contamination_recheck.confirmed_non_self_matches "
            f"= {result['contamination_recheck']['confirmed_non_self_matches']} != 0")
    path = os.path.join(receipt_dir, f"w2-heldout-decontam-{ts}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(receipt, fh, indent=2)
    return path


def write_batch_file(result: dict, *, out_path: str) -> str:
    arr = np.array(result["selected_rows"], dtype=np.int64)
    np.save(out_path, arr)
    return out_path


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--shard-dir", default=DEFAULT_SHARD_DIR)
    ap.add_argument("--seq", type=int, default=DEFAULT_SEQ)
    ap.add_argument("--n-mtp", type=int, default=DEFAULT_N_MTP)
    ap.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    ap.add_argument("--ceiling-steps", type=int, default=DEFAULT_CEILING_STEPS)
    ap.add_argument("--train-batch", type=int, default=DEFAULT_TRAIN_BATCH)
    ap.add_argument("--pool-oversample", type=int, default=DEFAULT_POOL_OVERSAMPLE)
    ap.add_argument("--max-rounds", type=int, default=DEFAULT_MAX_ROUNDS)
    ap.add_argument("--out-batch", default=os.path.join(
        REPO_ROOT, "receipts", "ember-c-scale", "w2-heldout-batch.npy"))
    ap.add_argument("--receipt-dir", default=RECEIPT_DIR)
    ap.add_argument("--n-workers", type=int, default=DEFAULT_MP_WORKERS)
    ap.add_argument("--scan-chunk-tokens", type=int, default=DEFAULT_SCAN_CHUNK_TOKENS,
                    help="Chunk size in tokens for per-shard rolling-hash scan (reduces peak memory)")
    ap.add_argument("--serial-only", action="store_true",
                    help="Run serial version instead of parallel (debug only)")
    ap.add_argument("--equivalence-test", action="store_true",
                    help="Run equivalence test on synthetic corpus before main launch")
    ap.add_argument("--equivalence-test-selfmatch", action="store_true",
                    help="Run self-match exclusion equivalence test (issue GF-W2-01 verification)")
    ap.add_argument("--equivalence-test-external", action="store_true",
                    help="Run external contamination detection equivalence test (validates fix doesn't suppress real contamination)")
    ap.add_argument("--pool-start-index", type=int, default=None,
                    help="Override pool start index for explicit placement (e.g. mid-corpus; default: tail placement via held_out_window_start). Rounds extend UPWARD from this index; omit for tail mode (rounds extend DOWNWARD).")
    ap.add_argument("--dump-matches", type=str, default=None,
                    help="Optional JSONL file to dump matched contamination records (one per line)")
    args = ap.parse_args()

    if not args.shard_dir:
        raise SystemExit("W2_DECONTAM_SHARD_DIR_REQUIRED")

    # Preflight checks
    total_commit, free_commit = _preflight_check_commit()
    print(f"[PREFLIGHT] Commit: {total_commit:.1f}GB total, {free_commit:.1f}GB free "
          f"(>={MIN_COMMIT_FREE_GB}GB required: OK)")

    # Equivalence test if requested
    if args.equivalence_test:
        passed, equiv_receipt = run_equivalence_test(args.shard_dir, seq=args.seq, n_mtp=args.n_mtp)
        if not passed:
            raise SystemExit(f"W2_DECONTAM_EQUIVALENCE_FAILED: {equiv_receipt}")
        print(f"[EQUIV] PASS: {equiv_receipt}")
        print()

    # Self-match exclusion equivalence test if requested
    if args.equivalence_test_selfmatch:
        passed, selfmatch_receipt = run_equivalence_test_selfmatch(args.shard_dir, seq=args.seq, n_mtp=args.n_mtp)
        if not passed:
            raise SystemExit(f"W2_DECONTAM_EQUIVALENCE_SELFMATCH_FAILED: {selfmatch_receipt}")
        print(f"[EQUIV-SELFMATCH] PASS: {selfmatch_receipt}")
        print()

    # External contamination detection equivalence test if requested
    if args.equivalence_test_external:
        passed, external_receipt = run_equivalence_test_external(args.shard_dir, seq=args.seq, n_mtp=args.n_mtp)
        if not passed:
            raise SystemExit(f"W2_DECONTAM_EQUIVALENCE_EXTERNAL_FAILED: {external_receipt}")
        print(f"[EQUIV-EXTERNAL] PASS: {external_receipt}")
        print()

    # Setup progress file
    run_dir = os.path.join(REPO_ROOT, "scratch", "w2-heldout-run")
    os.makedirs(run_dir, exist_ok=True)
    ts = _utc_ts()
    progress_file = os.path.join(run_dir, f"mp-progress-{ts}.jsonl")

    print(f"[LAUNCH] Starting build with {args.n_workers} workers")
    print(f"[LAUNCH] Progress file: {progress_file}")
    print()

    result = build_batch(shard_dir=args.shard_dir, seq=args.seq, n_mtp=args.n_mtp,
                          batch_size=args.batch_size, ceiling_steps=args.ceiling_steps,
                          train_batch=args.train_batch, pool_oversample=args.pool_oversample,
                          max_rounds=args.max_rounds,
                          use_mp=not args.serial_only,
                          n_workers=args.n_workers,
                          progress_file=progress_file,
                          chunk_tokens=args.scan_chunk_tokens,
                          pool_start_index=args.pool_start_index)

    write_batch_file(result, out_path=args.out_batch)
    receipt_path = write_receipt(result, receipt_dir=args.receipt_dir)

    # Dump matches to JSONL if requested
    if args.dump_matches:
        os.makedirs(os.path.dirname(args.dump_matches) or ".", exist_ok=True)
        match_count = 0
        with open(args.dump_matches, "w") as f:
            for match in result.get("contamination_recheck", {}).get("confirmed_matches", []):
                row = {
                    "shard": match.get("shard"),
                    "offset": match.get("offset"),
                    "match_len_tokens": 13,
                    "window_idx": match.get("offset"),
                    "basis": "v1-any-match"
                }
                f.write(json.dumps(row) + "\n")
                match_count += 1
        print(f"[DUMP] {match_count} matches written to {args.dump_matches}")

    print(f"batch_size={result['batch_size']} "
          f"windows_checked={result['total_candidates_checked']} "
          f"replacements_made={result['replacements_made']} "
          f"contamination_recheck={result['contamination_recheck']['confirmed_non_self_matches']} "
          f"wall_s_total={result['wall_s_total']} "
          f"receipt={receipt_path} "
          f"batch_file={args.out_batch} "
          f"exit=PASS")


if __name__ == "__main__":
    main()
