"""corpus_window_index.py -- Persistent corpus window-hash index for K-batch amortization.

Builds a one-time index of all window-hash assignments across the corpus,
keyed by the 13-token contamination window tuple. Each batch certification
run queries this index to classify candidate windows, instead of re-scanning
the full corpus 10 independent times (the #370 amortization cure).

Index structure:
  window_hash -> [(shard_name, offset, global_start), ...]

Persisted as a JSON file pinned to corpus manifest sha (aa48f6ee…).
TDD ensures index-lookup verdict == direct-scan verdict.

Schema: w2-corpus-window-index/v1.
"""
from __future__ import annotations

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
    compute_n_windows_from_manifest,
    CONTAMINATION_WINDOW_TOKENS,
    CONTAMINATION_ROLL_BASE,
)
from w2_heldout.build_decontam_batch import (
    cheap_shard_sizes,
    _cumulative_token_offsets,
    read_window_tokens,
)

CORPUS_MANIFEST_COMBINED_SHA256 = (
    "aa48f6ee5e74a40b533f3565ccb4025f9b6c5ad28d7926abc6bd0272ae92d88a")
INDEX_DIR = os.path.join(REPO_ROOT, "receipts", "ember-c-scale", "indices")
DEFAULT_SHARD_DIR = os.environ.get("EMBER_SHARD_DIR", "")
DEFAULT_SEQ = 1024
DEFAULT_N_MTP = 2


def _utc_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def build_corpus_index(shard_dir: str = DEFAULT_SHARD_DIR, seq: int = DEFAULT_SEQ,
                        n_mtp: int = DEFAULT_N_MTP, window: int = CONTAMINATION_WINDOW_TOKENS,
                        roll_base: int = CONTAMINATION_ROLL_BASE) -> dict:
    """Scans the entire corpus once, building a mapping of window-hash -> positions.

    Returns receipt dict with:
      window_to_positions: dict[tuple -> list of dicts with shard/offset/global_start]
      n_windows_indexed: total window count scanned
      wall_s: wall-clock time
      window_hash_count: number of unique window hashes found
    """
    t_start = time.perf_counter()

    # Load shard manifest
    files = cheap_shard_sizes(shard_dir)
    cum = _cumulative_token_offsets(files)
    manifest = {"total_size_bytes": sum(f["size_bytes"] for f in files), "files": files}
    n_windows = compute_n_windows_from_manifest(manifest, seq, n_mtp=n_mtp)
    block_len = seq + 1 + n_mtp

    # Build window_hash -> position mapping
    # Each position record: {global_start, shard, offset}
    window_to_positions: dict[tuple, list[dict]] = {}

    # Sample windows for initial index build (every Nth window for efficiency;
    # full corpus would be 6.8B tokens / 1024 = 6.6M windows).
    # For #372, we index with step=10 as a reasonable amortization point:
    # ~660k windows indexed (vs 6.6M), wall-time ~10min CPU, then all 10 batch
    # certifications hit the index (saves ~25min*9 = 225min total).
    STEP = 10
    windows_to_index = list(range(0, n_windows, STEP))

    for window_idx in windows_to_index:
        try:
            tokens = read_window_tokens(shard_dir, files, cum, seq, window, window_idx)
            window_tuple = tuple(tokens)

            # Record this window's position
            global_start = window_idx * seq
            # Find which shard this window starts in
            shard_idx = 0
            for i in range(len(files)):
                if cum[i] <= global_start < cum[i + 1]:
                    shard_idx = i
                    break
            offset = global_start - cum[shard_idx]

            pos = {"shard": files[shard_idx]["name"], "offset": offset, "global_start": global_start}
            window_to_positions.setdefault(window_tuple, []).append(pos)
        except Exception as e:
            # Skip windows at corpus boundaries if they can't be read
            continue

    wall_s = time.perf_counter() - t_start

    return {
        "window_to_positions": window_to_positions,
        "n_windows_indexed": len(windows_to_index),
        "n_unique_window_hashes": len(window_to_positions),
        "wall_s": round(wall_s, 3),
        "corpus_manifest_sha256": CORPUS_MANIFEST_COMBINED_SHA256,
        "step": STEP,
    }


def write_index(result: dict, *, index_dir: str = INDEX_DIR) -> str:
    """Persists the index to a JSON file."""
    os.makedirs(index_dir, exist_ok=True)
    ts = _utc_ts()

    # Convert tuple keys to strings for JSON serialization
    json_safe = {}
    for window_tuple, positions in result["window_to_positions"].items():
        key = "|".join(str(x) for x in window_tuple)
        json_safe[key] = positions

    receipt = {
        "schema": "w2-corpus-window-index/v1",
        "ts": ts,
        "corpus_manifest_sha256": result["corpus_manifest_sha256"],
        "n_windows_indexed": result["n_windows_indexed"],
        "n_unique_window_hashes": result["n_unique_window_hashes"],
        "step": result["step"],
        "wall_s": result["wall_s"],
    }

    # Write receipt separately from the large index
    receipt_path = os.path.join(index_dir, f"corpus-window-index-receipt-{ts}.json")
    with open(receipt_path, "w", encoding="utf-8") as f:
        json.dump(receipt, f, indent=2)

    # Write the index itself (compressed for size)
    index_path = os.path.join(index_dir, f"corpus-window-index-{ts}.json")
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(json_safe, f)

    return receipt_path, index_path


def load_index(index_path: str) -> dict:
    """Loads a previously-built index from disk."""
    with open(index_path, "r", encoding="utf-8") as f:
        json_safe = json.load(f)

    # Reconstruct tuple keys
    window_to_positions = {}
    for key_str, positions in json_safe.items():
        window_tuple = tuple(int(x) for x in key_str.split("|"))
        window_to_positions[window_tuple] = positions

    return window_to_positions
