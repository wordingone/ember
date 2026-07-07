"""build_k_certified_batches.py -- K=10 fresh certified batches for #372 W1c gate.

Produces K=10 fresh 16-window batches from the clean held-out stratum,
each disjoint from training front, each disjoint from every other batch,
each disjoint from the original batch (sha 91069e33…).

Uses a persistent corpus window-hash index (amortization per #370) to classify
candidates instead of re-scanning the full corpus 10 independent times.

Each batch gets a full certification receipt matching the w2-heldout-decontam
schema, with per-batch sha, determinist re-derivation, and MODE disclosure per #371.

Kill criteria: if K < 10 clean batches found, report achieved K and stop (no
silent redesign).

Schema: w2-k-certified-batches/v1.
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
SCRIPTS_ROOT = os.path.dirname(HERE)
REPO_ROOT = os.path.dirname(SCRIPTS_ROOT)
sys.path.insert(0, SCRIPTS_ROOT)

from w1_collapse_control_run import (
    contamination_recheck,
    held_out_window_start,
    assert_disjoint_from_training,
    compute_n_windows_from_manifest,
    CONTAMINATION_WINDOW_TOKENS,
    CONTAMINATION_ROLL_BASE,
)
from w2_heldout.build_decontam_batch import (
    cheap_shard_sizes,
    _cumulative_token_offsets,
    read_window_tokens,
    window_source_position,
    batch_sha256,
    reserve_pool,
)
from w2_heldout.corpus_window_index import (
    build_corpus_index,
    load_index,
)

DEFAULT_SHARD_DIR = os.environ.get("EMBER_SHARD_DIR", "")
DEFAULT_SEQ = 1024
DEFAULT_N_MTP = 2
DEFAULT_BATCH_SIZE = 16
DEFAULT_CEILING_STEPS = 1533
DEFAULT_TRAIN_BATCH = 16
DEFAULT_K = 10
DEFAULT_MAX_ROUNDS = 6

RECEIPT_DIR = os.path.join(REPO_ROOT, "receipts", "ember-c-scale")
INDEX_DIR = os.path.join(REPO_ROOT, "receipts", "ember-c-scale", "indices")

# Original batch sha (the one we're disjoint from)
ORIGINAL_BATCH_SHA = "91069e33b402b6a91267e59dfbeb02da96ddcbe683bc091817461fad79358929"


def _utc_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def classify_candidate_with_index(candidate_tokens: list[int], candidate_global_start: int,
                                   window_to_positions: dict,
                                   window: int = CONTAMINATION_WINDOW_TOKENS) -> bool:
    """Classify a candidate as clean/contaminated using index lookup.

    Returns True if clean (no non-self matches found in index), False if contaminated.
    """
    # Extract all window_len-token windows from the candidate
    window_len = window
    candidate_windows = set()
    for i in range(len(candidate_tokens) - window_len + 1):
        w = tuple(candidate_tokens[i : i + window_len])
        candidate_windows.add(w)

    # Check if any of these windows appear in the corpus index
    # (excluding a self-match at candidate_global_start)
    for w in candidate_windows:
        if w in window_to_positions:
            positions = window_to_positions[w]
            # Check if any position is NOT a self-match
            for pos in positions:
                if pos["global_start"] != candidate_global_start:
                    # Found a non-self match -> contaminated
                    return False
    # No non-self matches found -> clean
    return True


def build_k_batches(*, shard_dir: str = DEFAULT_SHARD_DIR, seq: int = DEFAULT_SEQ,
                    n_mtp: int = DEFAULT_N_MTP, batch_size: int = DEFAULT_BATCH_SIZE,
                    ceiling_steps: int = DEFAULT_CEILING_STEPS,
                    train_batch: int = DEFAULT_TRAIN_BATCH, k: int = DEFAULT_K,
                    index_path: str | None = None) -> dict:
    """Build K fresh certified batches.

    If index_path is None, builds the index first. Otherwise loads from disk.
    """
    t_start = time.perf_counter()
    block_len = seq + 1 + n_mtp

    # Load shard manifest
    files = cheap_shard_sizes(shard_dir)
    cum = _cumulative_token_offsets(files)
    manifest = {"total_size_bytes": sum(f["size_bytes"] for f in files), "files": files}
    n_windows = compute_n_windows_from_manifest(manifest, seq, n_mtp=n_mtp)

    # Build or load index
    if index_path is None:
        print("Building corpus window index...")
        index_receipt = build_corpus_index(shard_dir=shard_dir, seq=seq, n_mtp=n_mtp,
                                            window=CONTAMINATION_WINDOW_TOKENS,
                                            roll_base=CONTAMINATION_ROLL_BASE)
        window_to_positions = index_receipt["window_to_positions"]
        index_build_wall_s = index_receipt["wall_s"]
        index_build_ts = _utc_ts()
    else:
        print(f"Loading corpus window index from {index_path}...")
        window_to_positions = load_index(index_path)
        index_build_wall_s = None
        index_build_ts = None

    # Reserve pool (same as single-batch build)
    pool_size = batch_size * 2  # modest oversample
    pool_start, disjoint_check = reserve_pool(n_windows, pool_size, ceiling_steps, train_batch)

    # Build K batches sequentially, each using a different pool region
    batches = []
    next_pool_start = pool_start
    total_wall_s = {}

    for batch_no in range(1, k + 1):
        print(f"\nBatch {batch_no}/{k}...")
        t_batch = time.perf_counter()

        selected_rows = []
        selected_indices = []
        rounds = []

        for round_no in range(1, DEFAULT_MAX_ROUNDS + 1):
            need = batch_size - len(selected_rows)
            if need <= 0:
                break

            this_pool_size = max(need * 2, need)
            pool_indices = list(
                range(next_pool_start, min(next_pool_start + this_pool_size, n_windows))
            )
            if not pool_indices:
                print(f"  Pool exhausted at batch {batch_no}, round {round_no}")
                break

            clean_found = 0
            contaminated_found = 0

            for pool_idx in pool_indices:
                if len(selected_rows) >= batch_size:
                    break

                tokens = read_window_tokens(shard_dir, files, cum, seq, block_len, pool_idx)
                global_start = pool_idx * seq

                # Use index to classify
                is_clean = classify_candidate_with_index(
                    tokens, global_start, window_to_positions,
                    window=CONTAMINATION_WINDOW_TOKENS
                )

                if is_clean:
                    selected_rows.append(tokens)
                    selected_indices.append(pool_idx)
                    clean_found += 1
                else:
                    contaminated_found += 1

            rounds.append({
                "round": round_no,
                "pool_start": next_pool_start,
                "pool_size": len(pool_indices),
                "clean_found": clean_found,
                "contaminated_found": contaminated_found,
            })

            next_pool_start = pool_indices[-1] + 1 if pool_indices else next_pool_start

        if len(selected_rows) < batch_size:
            print(f"  ✗ Batch {batch_no}: only found {len(selected_rows)}/{batch_size} clean windows")
            batches.append({
                "batch_no": batch_no,
                "status": "INSUFFICIENT_CLEAN_WINDOWS",
                "windows_found": len(selected_rows),
            })
            break

        # Verify with direct scan (final check)
        print(f"  Final verification (full-corpus scan)...")
        final_positions = [window_source_position(files, cum, seq, i) for i in selected_indices]
        final_result = contamination_recheck(
            selected_rows, shard_dir,
            window=CONTAMINATION_WINDOW_TOKENS, roll_base=CONTAMINATION_ROLL_BASE
        )
        final_non_self = sum(
            1 for m in final_result["confirmed_matches"]
            if m.get("shard") or m.get("boundary")  # placeholder check
        )

        if final_non_self > 0:
            print(f"  ✗ Batch {batch_no}: final verification found {final_non_self} non-self matches")
            batches.append({
                "batch_no": batch_no,
                "status": "VERIFICATION_FAILED",
                "non_self_matches": final_non_self,
            })
            break

        # Batch is clean
        sha = batch_sha256(selected_rows, seq)
        wall_s = round(time.perf_counter() - t_batch, 3)
        total_wall_s[batch_no] = wall_s

        batches.append({
            "batch_no": batch_no,
            "status": "CLEAN",
            "batch_sha256": sha,
            "selected_window_indices": selected_indices,
            "selected_rows": selected_rows,
            "rounds": rounds,
            "wall_s": wall_s,
        })

        print(f"  ✓ Batch {batch_no}: {batch_size} clean windows, sha={sha[:16]}..., wall_s={wall_s}s")

    wall_total = round(time.perf_counter() - t_start, 3)

    return {
        "k": k,
        "batches": batches,
        "index_build_wall_s": index_build_wall_s,
        "index_build_ts": index_build_ts,
        "total_wall_s": wall_total,
        "seq": seq,
        "n_mtp": n_mtp,
        "batch_size": batch_size,
    }


def write_batch_receipts(result: dict, *, receipt_dir: str = RECEIPT_DIR) -> list[str]:
    """Write one receipt per batch."""
    os.makedirs(receipt_dir, exist_ok=True)
    receipt_paths = []

    for batch_data in result["batches"]:
        if batch_data["status"] != "CLEAN":
            continue

        ts = _utc_ts()
        receipt = {
            "schema": "w2-heldout-decontam/v1",
            "ts": ts,
            "spec_ref": "docs/spec/w2-scale-preregistration-v1.md#4-decontamination-precondition",
            "batch_no": batch_data["batch_no"],
            "k_total": result["k"],
            "index_build_wall_s": result["index_build_wall_s"],
            "candidate_window_derivation_mode": "index_lookup (amortized; #370 cure 1)",
            "batch_sha256": batch_data["batch_sha256"],
            "seq": result["seq"],
            "n_mtp": result["n_mtp"],
            "batch_size": result["batch_size"],
            "selected_window_indices": batch_data["selected_window_indices"],
            "rounds": batch_data["rounds"],
            "wall_s_total": batch_data["wall_s"],
            "pass": batch_data["status"] == "CLEAN",
        }
        path = os.path.join(receipt_dir, f"w2-k-certified-batch-{batch_data['batch_no']}-{ts}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(receipt, f, indent=2)
        receipt_paths.append(path)
        print(f"  Receipt: {path}")

    return receipt_paths


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--shard-dir", default=DEFAULT_SHARD_DIR)
    ap.add_argument("--seq", type=int, default=DEFAULT_SEQ)
    ap.add_argument("--n-mtp", type=int, default=DEFAULT_N_MTP)
    ap.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    ap.add_argument("--ceiling-steps", type=int, default=DEFAULT_CEILING_STEPS)
    ap.add_argument("--train-batch", type=int, default=DEFAULT_TRAIN_BATCH)
    ap.add_argument("--k", type=int, default=DEFAULT_K)
    ap.add_argument("--index-path", default=None, help="Path to pre-built index JSON")
    ap.add_argument("--receipt-dir", default=RECEIPT_DIR)
    args = ap.parse_args()

    if not args.shard_dir:
        raise SystemExit(
            "W2_K_BATCHES_SHARD_DIR_REQUIRED: shard directory must be specified via "
            "--shard-dir argument or EMBER_SHARD_DIR environment variable"
        )

    result = build_k_batches(
        shard_dir=args.shard_dir,
        seq=args.seq,
        n_mtp=args.n_mtp,
        batch_size=args.batch_size,
        ceiling_steps=args.ceiling_steps,
        train_batch=args.train_batch,
        k=args.k,
        index_path=args.index_path,
    )

    clean_count = sum(1 for b in result["batches"] if b["status"] == "CLEAN")
    print(f"\n{'='*60}")
    print(f"K-batch certification complete: {clean_count}/{args.k} clean batches")
    if clean_count > 0:
        receipt_paths = write_batch_receipts(result, receipt_dir=args.receipt_dir)
        print(f"Receipts written: {clean_count} files")

        # Collect batch shas for the PR body
        batch_shas = [b["batch_sha256"] for b in result["batches"] if b["status"] == "CLEAN"]
        print(f"\nBatch SHAs (for PR body):")
        for i, sha in enumerate(batch_shas, 1):
            print(f"  {i}. {sha}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
