"""build_decontam_batch.py -- W2 preregistration sec.4 decontamination precondition
(docs/spec/w2-scale-preregistration-v1.md, FROZEN 2026-07-04).

Rebuilds the held-out capability-point eval batch with window-level dedup applied
as a FILTER at construction time, not a post-hoc check: any held-out candidate
window with a corpus match is REPLACED, iterating until the batch is full and
clean (`contamination_recheck` must report 0 confirmed matches).

Reuse, never reimplement, per the dispatch rail:
  - `contamination_recheck`      (scripts/w1_collapse_control_run.py)  -- the
    exact 13-token polynomial rolling-hash matcher that found W1's 69,811
    matches, unmodified.
  - `held_out_window_start` / `assert_disjoint_from_training`  (same module)
    -- the disjointness-from-training convention, unmodified.
  - `compute_n_windows_from_manifest`  (same module) -- byte-size-only window
    count derivation, so this script never needs PackedShardLoader's
    RAM-heavy (~14-27GB) full-corpus concatenation just to pick indices.

New in this script (nothing upstream provides these):
  - a RAM-frugal per-shard window reader (`read_window_tokens`) that seeks
    into just the 1-2 shard files a candidate window's [start, start+block_len)
    range touches, instead of loading the whole packed stream;
  - self-match exclusion: a held-out candidate window is drawn FROM the real
    corpus, so contamination_recheck trivially reports a match at the
    window's own physical (shard, offset) -- excluding that one expected
    self-hit is required or the "iterate until clean" loop could never
    converge (every candidate would show >=1 trivial self-match). A match at
    ANY OTHER (shard, offset) is genuine duplication and disqualifies the
    candidate. This exclusion runs entirely in this script (candidate rows
    are small, no corpus rescan needed for the attribution step) --
    contamination_recheck's own matcher logic is never touched.

CPU-only. Read-only against the corpus and against every existing receipt --
this script writes exactly one new receipt file
(receipts/ember-c-scale/w2-heldout-decontam-<ts>.json) and touches nothing else.
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

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_ROOT = os.path.dirname(HERE)          # .../scripts
REPO_ROOT = os.path.dirname(SCRIPTS_ROOT)     # .../ember-goalforge
sys.path.insert(0, SCRIPTS_ROOT)

from w1_collapse_control_run import (  # noqa: E402  (reused, never reimplemented)
    contamination_recheck,
    held_out_window_start,
    assert_disjoint_from_training,
    compute_n_windows_from_manifest,
    CONTAMINATION_WINDOW_TOKENS,
    CONTAMINATION_ROLL_BASE,
)

# Defaults mirror W1's rung-1 REAL-LINEAGE convention (the only frozen
# precedent as of this dispatch -- W2's own real_arch is not yet frozen),
# read from receipts/ember-c-scale/w1-collapse-control-20260704T144548Z.json
# real_lineage_reference.derived_target_architecture: {vocab:32000, seq:1024,
# batch:16, n_mtp:2}. NOTE: seq=1024 here, NOT the seq=64 dry-run/demo
# convention scratch/corpus-wire/contamination_check.py's docstring uses
# (that script's SEQ_DRYRUN=64/VOCAB_DRYRUN=512 is a SEPARATE small synthetic
# corpus for its own self-contained demo, unrelated to the real held-out
# batch this module rebuilds -- an earlier draft of this module wrongly
# carried DEFAULT_SEQ=64 over from that docstring; fixed before the real run
# shipped a receipt, caught by cross-checking real_lineage_reference directly
# rather than trusting the dry-run constant by proximity).
# Every value is a CLI-overridable parameter, never hardcoded into the
# selection logic itself, so the eventual W2 runner can pass rung-2's real
# numbers without touching this module.
DEFAULT_SEQ = 1024
DEFAULT_N_MTP = 2
DEFAULT_BATCH_SIZE = 16
DEFAULT_CEILING_STEPS = 1533
DEFAULT_TRAIN_BATCH = 16
DEFAULT_SHARD_DIR = os.environ.get("EMBER_SHARD_DIR", "")
DEFAULT_POOL_OVERSAMPLE = 2   # candidates drawn per round = batch_size * this;
                              # kept modest because contamination_recheck's
                              # own np.isin call grows memory-expensive with
                              # needle-window count -- classify_candidates
                              # adaptively splits on MemoryError regardless
                              # (see classify_candidates docstring), so this
                              # is a wall-time tuning knob, not a correctness
                              # requirement: a smaller default means fewer
                              # rows need splitting on the first attempt
                              # under tight ambient memory (observed: a
                              # 128-row/seq=1024 batch MemoryError'd under
                              # ~10-14GB free with ~33GB held by unrelated
                              # processes on this shared machine).
DEFAULT_MAX_ROUNDS = 6

RECEIPT_DIR = os.path.join(REPO_ROOT, "receipts", "ember-c-scale")


def _utc_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


# ---------------------------------------------------------------------------
# Cheap (no-SHA) manifest: only what compute_n_windows_from_manifest needs,
# plus per-shard token counts in file order for window->(shard,offset) lookup.
# Deliberately does NOT call manifest_sha.compute_manifest (which SHA-256
# hashes every shard byte -- an unrelated, heavier concern than picking
# window indices; corpus-identity verification stays the runner's own job
# via verify_shard_corpus, not duplicated here).
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
# RAM-frugal window reader: seeks into just the shard file(s) a window's
# token range touches, instead of PackedShardLoader's eager full-stream
# concatenation (14GB+ resident). Produces IDENTICAL windows to
# PackedShardLoader.window_np by construction: both index the same sorted
# shard-file concatenation, stride=seq, block_len=seq+1+n_mtp.
# ---------------------------------------------------------------------------

def _cumulative_token_offsets(files: list[dict]) -> list[int]:
    """cumulative[i] = total tokens in files[0:i] (so file i covers the global
    token range [cumulative[i], cumulative[i+1]))."""
    cum = [0]
    for f in files:
        cum.append(cum[-1] + f["n_tokens"])
    return cum


def window_source_position(files: list[dict], cum: list[int], seq: int,
                            window_idx: int) -> dict:
    """Where window_idx's FIRST token lives: (shard name, offset within that
    shard, and the GLOBAL token-stream position). Kept for readability/
    receipts; self-match exclusion itself compares GLOBAL positions (see
    _match_global_start), not (shard, offset) pairs -- a window straddling a
    shard boundary is reported by contamination_recheck as a "boundary" match
    with a different dict shape ({boundary, offset_in_join} instead of
    {shard, offset}), and comparing shapes directly would silently misclassify
    every boundary-spanning candidate. Global-position comparison is correct
    for both match shapes."""
    start = window_idx * seq
    for i in range(len(files)):
        if cum[i] <= start < cum[i + 1]:
            return {"shard": files[i]["name"], "offset": start - cum[i], "global_start": start}
    raise SystemExit(
        f"W2_DECONTAM_WINDOW_OUT_OF_RANGE: window {window_idx} start {start} "
        f"exceeds corpus token range {cum[-1]}")


def _match_global_start(m: dict, name_to_index: dict[str, int], cum: list[int],
                         window: int) -> int:
    """Resolves a contamination_recheck confirmed_matches entry (either the
    per-shard {shard, offset} shape or the cross-boundary {boundary,
    offset_in_join} shape) to a single global token-stream start position,
    so both shapes can be compared against a candidate's known global_start
    (window_idx * seq) on equal footing."""
    if "shard" in m:
        return cum[name_to_index[m["shard"]]] + m["offset"]
    # Boundary shape: m["boundary"] = "shard_i_name|shard_j_name". The join
    # buffer contamination_recheck built is [last (window-1) tokens of
    # shard_i] + [first (window-1) tokens of shard_j] -- i.e. it starts
    # (window-1) tokens before shard_j's global start.
    name_i, name_j = m["boundary"].split("|")
    idx_j = name_to_index[name_j]
    join_global_start = cum[idx_j] - (window - 1)
    return join_global_start + m["offset_in_join"]


def read_window_tokens(shard_dir: str, files: list[dict], cum: list[int],
                        seq: int, block_len: int, window_idx: int) -> list[int]:
    """Read exactly block_len tokens starting at window_idx*seq, seeking into
    only the shard file(s) that range touches (never the full corpus)."""
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
# Candidate pool + disjointness (reuses held_out_window_start /
# assert_disjoint_from_training unmodified, generalized from "the last
# eval_batch_size windows" to "the last pool_size windows" -- a strict
# superset of the same reserved, training-disjoint tail region).
# ---------------------------------------------------------------------------

def reserve_pool(n_windows: int, pool_size: int, ceiling_steps: int,
                  train_batch: int) -> tuple[int, dict]:
    pool_start = held_out_window_start(n_windows, pool_size)
    disjoint_check = assert_disjoint_from_training(pool_start, ceiling_steps, train_batch)
    return pool_start, disjoint_check


# ---------------------------------------------------------------------------
# Self-match-aware contamination filter. ONE contamination_recheck call per
# round (its cost is dominated by the fixed full-corpus scan, not by needle
# count -- batching many candidates into one call is strictly cheaper than
# one call per candidate).
# ---------------------------------------------------------------------------

def _row_contains_window(row: list[int], window_tuple: tuple, window_len: int) -> bool:
    n = len(row)
    if n < window_len:
        return False
    for i in range(n - window_len + 1):
        if tuple(row[i:i + window_len]) == window_tuple:
            return True
    return False


def _classify_once(candidate_rows: list[list[int]],
                    candidate_positions: list[dict],
                    shard_dir: str,
                    *, window: int, roll_base: int,
                    files: list[dict] | None,
                    cum: list[int] | None) -> dict:
    """Runs contamination_recheck ONCE over all candidate_rows, then
    attributes every confirmed match back to the candidate row(s) whose
    content contains that exact window (cheap local check, no corpus
    rescan), excluding a match at the candidate's OWN known GLOBAL position
    as an expected self-hit (see _match_global_start for why this must be
    global-position comparison, not (shard, offset) equality -- boundary-
    spanning candidates need it). `files`/`cum` are required to resolve
    boundary-shaped matches; when omitted, boundary matches are treated as
    always non-self (safe default -- can only make the filter MORE strict,
    never hide a genuine duplicate, at the cost of possibly over-replacing a
    boundary-spanning candidate that was actually clean). May raise
    MemoryError -- propagated to the caller, not caught here (this is the
    single-attempt primitive; classify_candidates is the adaptive wrapper)."""
    t0 = time.perf_counter()
    raw = contamination_recheck(candidate_rows, shard_dir, window=window, roll_base=roll_base)
    wall_s = round(time.perf_counter() - t0, 3)

    name_to_index = {f["name"]: i for i, f in enumerate(files)} if files else None

    non_self_matches_by_candidate: list[list[dict]] = [[] for _ in candidate_rows]
    self_matches_excluded = 0

    for m in raw["confirmed_matches"]:
        window_tuple = tuple(m["window"])
        if name_to_index is not None and cum is not None:
            match_global_start = _match_global_start(m, name_to_index, cum, window)
        else:
            match_global_start = None  # boundary resolution unavailable -> never self
        for idx, row in enumerate(candidate_rows):
            if not _row_contains_window(row, window_tuple, window):
                continue
            pos = candidate_positions[idx]
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
    """Merges two classify_candidates results, where `right`'s per-candidate
    indices (clean_idx/contaminated_idx/non_self_matches_by_candidate) are
    relative to ITS OWN sublist and must be shifted by right_offset (=
    len(left's original candidate_rows)) to be relative to the combined
    list."""
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
                         cum: list[int] | None = None) -> dict:
    """Adaptive wrapper around _classify_once: contamination_recheck's own
    np.isin call switches to a memory-heavier algorithm once the needle-
    window count is large enough, and that strategy's memory need is not a
    fixed threshold -- it depends on however much RAM happens to be free
    right now (ambient pressure from unrelated processes on a shared
    machine, not this script's own footprint). A hardcoded "safe" batch size
    would either waste scans when memory is plentiful or still fail when
    memory is tighter than assumed. Instead: try the full candidate_rows in
    ONE contamination_recheck call; on MemoryError, split in half and retry
    each half independently (each half re-scans the full corpus -- more
    wall-clock cost, but correct and self-adjusting to whatever memory is
    actually available), merging results. Bottoms out at a single row --
    if even that raises MemoryError, it propagates (nothing smaller to try,
    and that is a genuine environment-exhaustion condition worth surfacing,
    not one to paper over)."""
    try:
        return _classify_once(candidate_rows, candidate_positions, shard_dir,
                               window=window, roll_base=roll_base, files=files, cum=cum)
    except MemoryError:
        if len(candidate_rows) <= 1:
            raise
        mid = len(candidate_rows) // 2
        left = classify_candidates(candidate_rows[:mid], candidate_positions[:mid], shard_dir,
                                    window=window, roll_base=roll_base, files=files, cum=cum)
        right = classify_candidates(candidate_rows[mid:], candidate_positions[mid:], shard_dir,
                                     window=window, roll_base=roll_base, files=files, cum=cum)
        return _merge_classify_results(left, right, right_offset=mid)


# ---------------------------------------------------------------------------
# sha256 convention -- mirrors sha256_tokens(torch.cat([x, y], dim=1)) exactly
# (scripts/w1_collapse_control_run.py:188), reimplemented in pure numpy so
# this module has no torch dependency: int64 bytes of [x || y] per row,
# stacked, row-major.
# ---------------------------------------------------------------------------

def batch_sha256(rows: list[list[int]], seq: int) -> str:
    xs = np.array([r[:seq] for r in rows], dtype=np.int64)
    ys = np.array([r[1:seq + 1] for r in rows], dtype=np.int64)
    combined = np.concatenate([xs, ys], axis=1)
    return hashlib.sha256(combined.tobytes()).hexdigest()


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def build_batch(*, shard_dir: str = DEFAULT_SHARD_DIR, seq: int = DEFAULT_SEQ,
                 n_mtp: int = DEFAULT_N_MTP, batch_size: int = DEFAULT_BATCH_SIZE,
                 ceiling_steps: int = DEFAULT_CEILING_STEPS,
                 train_batch: int = DEFAULT_TRAIN_BATCH,
                 pool_oversample: int = DEFAULT_POOL_OVERSAMPLE,
                 max_rounds: int = DEFAULT_MAX_ROUNDS) -> dict:
    t_start = time.perf_counter()
    block_len = seq + 1 + n_mtp

    files = cheap_shard_sizes(shard_dir)
    cum = _cumulative_token_offsets(files)
    manifest = shard_manifest_for_window_count(shard_dir)
    n_windows = compute_n_windows_from_manifest(manifest, seq, n_mtp=n_mtp)

    pool_size = batch_size * pool_oversample
    pool_start, disjoint_check = reserve_pool(n_windows, pool_size, ceiling_steps, train_batch)

    selected_rows: list[list[int]] = []
    selected_indices: list[int] = []
    rounds: list[dict] = []
    next_pool_start = pool_start
    replacements_made = 0
    total_candidates_checked = 0

    for round_no in range(1, max_rounds + 1):
        need = batch_size - len(selected_rows)
        if need <= 0:
            break
        this_pool_size = max(need * pool_oversample, need)
        pool_indices = list(range(next_pool_start, min(next_pool_start + this_pool_size, n_windows)))
        if not pool_indices:
            raise SystemExit(
                "W2_DECONTAM_POOL_EXHAUSTED: ran out of training-disjoint window "
                f"indices before assembling {batch_size} clean windows "
                f"(selected {len(selected_rows)}).")

        candidate_rows = [read_window_tokens(shard_dir, files, cum, seq, block_len, i)
                           for i in pool_indices]
        candidate_positions = [window_source_position(files, cum, seq, i) for i in pool_indices]

        result = classify_candidates(candidate_rows, candidate_positions, shard_dir,
                                      files=files, cum=cum)
        total_candidates_checked += len(pool_indices)

        newly_clean = result["clean_idx"][:need]
        for ci in newly_clean:
            selected_rows.append(candidate_rows[ci])
            selected_indices.append(pool_indices[ci])
        # A "replacement" is any candidate this round found CONTAMINATED --
        # each one had to be swapped out for another draw to keep the batch
        # full, regardless of whether that swap happened within this same
        # round's surplus or required a later round. Excess CLEAN candidates
        # beyond `need` are unused oversupply, not replacements.
        replacements_made += len(result["contaminated_idx"])

        rounds.append({
            "round": round_no,
            "pool_start": next_pool_start,
            "pool_size": len(pool_indices),
            "wall_s": result["wall_s"],
            "n_contamination_recheck_calls": result["n_calls"],
            "memory_split_occurred": result["split_occurred"],
            "clean_found": len(result["clean_idx"]),
            "contaminated_found": len(result["contaminated_idx"]),
            "self_matches_excluded": result["self_matches_excluded"],
        })

        next_pool_start = pool_indices[-1] + 1

    if len(selected_rows) < batch_size:
        raise SystemExit(
            f"W2_DECONTAM_INSUFFICIENT_CLEAN_WINDOWS: found {len(selected_rows)} clean "
            f"windows in {max_rounds} rounds ({total_candidates_checked} candidates "
            f"checked), needed {batch_size}. Corpus may be too repetitive at "
            f"window={CONTAMINATION_WINDOW_TOKENS} for a clean batch to exist under "
            "the strict any-match convention -- raise max_rounds/pool_oversample or "
            "escalate the finding, do not silently relax the match definition.")

    # Final verification pass: recheck the ASSEMBLED batch as one call, using
    # the same self-match exclusion, so the receipt's contamination_recheck
    # count is measured on the batch actually being shipped, not inferred
    # from per-round bookkeeping.
    final_positions = [window_source_position(files, cum, seq, i) for i in selected_indices]
    final_check = classify_candidates(selected_rows, final_positions, shard_dir,
                                       files=files, cum=cum)
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
                          "(same convention as scratch/corpus-wire/contamination_check.py) "
                          "-- unmodified, called as a construction-time FILTER here instead "
                          "of a post-hoc check",
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
            f"= {result['contamination_recheck']['confirmed_non_self_matches']} != 0 -- "
            "refusing to write a receipt claiming a clean batch that isn't. Not a code path "
            "reached by a correct build_batch() call (it raises "
            "W2_DECONTAM_INSUFFICIENT_CLEAN_WINDOWS first), kept as a belt-and-suspenders "
            "fail-closed floor.")
    path = os.path.join(receipt_dir, f"w2-heldout-decontam-{ts}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(receipt, fh, indent=2)
    return path


def write_batch_file(result: dict, *, out_path: str) -> str:
    """Writes the decontaminated batch's raw token rows as a flat int64 .npy
    array (shape [batch_size, block_len]) -- the artifact the launch gate's
    sha check runs against. Never touches shard_dir or any existing receipt."""
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
    args = ap.parse_args()

    if not args.shard_dir:
        raise SystemExit("W2_DECONTAM_SHARD_DIR_REQUIRED: shard directory must be specified via --shard-dir argument or EMBER_SHARD_DIR environment variable")

    result = build_batch(shard_dir=args.shard_dir, seq=args.seq, n_mtp=args.n_mtp,
                          batch_size=args.batch_size, ceiling_steps=args.ceiling_steps,
                          train_batch=args.train_batch, pool_oversample=args.pool_oversample,
                          max_rounds=args.max_rounds)
    write_batch_file(result, out_path=args.out_batch)
    receipt_path = write_receipt(result, receipt_dir=args.receipt_dir)

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
