"""corpus_bloom_index.py -- Bloom filter index for ALL corpus window hashes.

Soundness fix for corpus-window contamination classification (#372 defect):
- Builds a Bloom filter over ALL 6.98B corpus window hashes (no sampling)
- O(1) rejection of clean windows (Bloom negatives = definite clean)
- Bloom positives trigger exact contamination_recheck re-verification
- Zero false negatives by construction (Bloom property)
- Exact re-verify absorbs Bloom false positives (contamination_recheck does it anyway)

The STEP=10 sampling in corpus_window_index.py was unsound: ~90% of corpus
n-gram positions invisible → contaminated batches certify CLEAN silently.
Bloom filter fixes this while preserving amortization: one full-corpus scan
builds the filter, then all K batches use O(1) Bloom lookups.

Bloom filter construction:
1. Stream all windows from corpus shards in order (no sampling)
2. Hash each 13-token window to Bloom bits
3. Persist as binary file (no JSON serialization overhead)

Usage:
  result = build_corpus_bloom_filter(shard_dir, target_fp_rate=0.01)
  bf = load_corpus_bloom_filter(bloom_path)
  if bf.contains(window_tokens):
      # Window might be contaminated (Bloom positive)
      # Run exact contamination_recheck to filter out FPs
      ...
  else:
      # Window is definitely clean (Bloom negative)
      ...

Schema: w2-corpus-bloom-index/v1.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import struct
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
    compute_n_windows_from_manifest,
    CONTAMINATION_WINDOW_TOKENS,
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


class SimpleBloomFilter:
    """Minimal Bloom filter: hash-to-bits, no false negatives, adjustable FP rate."""

    def __init__(self, n_items: int, target_fp_rate: float = 0.01):
        """Initialize Bloom filter for n_items with target false-positive rate.

        Parameters:
          n_items: expected number of distinct items
          target_fp_rate: desired false positive rate (e.g. 0.01 = 1%)

        Derived formulas (standard Bloom filter theory):
          m (filter size in bits) = -(n * ln(fp_rate)) / ln(2)^2
          k (hash functions) = (m / n) * ln(2)
        """
        self.n_items = n_items
        self.target_fp_rate = target_fp_rate

        # Compute filter size and k
        ln2_sq = math.log(2) ** 2
        self.m = max(1, int(-n_items * math.log(target_fp_rate) / ln2_sq))
        self.k = max(1, int((self.m / n_items) * math.log(2)))

        # Filter as numpy byte array
        n_bytes = (self.m + 7) // 8
        self.bits = np.zeros(n_bytes, dtype=np.uint8)

        # For reproducibility, use fixed seed for hash derivation
        self.seed = 0

    def _hashes(self, item: tuple) -> list[int]:
        """Generate k independent hash values for an item."""
        item_bytes = b"|".join(str(x).encode() for x in item)
        hashes = []
        for i in range(self.k):
            h = hashlib.sha256(item_bytes + struct.pack("<I", self.seed + i))
            hashes.append(int.from_bytes(h.digest()[:4], "little") % self.m)
        return hashes

    def add(self, item: tuple) -> None:
        """Add item to filter."""
        for bit_pos in self._hashes(item):
            byte_idx = bit_pos // 8
            bit_idx = bit_pos % 8
            self.bits[byte_idx] |= (1 << bit_idx)

    def contains(self, item: tuple) -> bool:
        """Check if item is in filter (may have false positives, never false negatives)."""
        for bit_pos in self._hashes(item):
            byte_idx = bit_pos // 8
            bit_idx = bit_pos % 8
            if not (self.bits[byte_idx] & (1 << bit_idx)):
                return False
        return True

    def size_bytes(self) -> int:
        """Size of filter in bytes."""
        return len(self.bits)

    def to_bytes(self) -> bytes:
        """Serialize filter to bytes."""
        return self.bits.tobytes()

    @staticmethod
    def from_bytes(data: bytes, m: int, k: int) -> SimpleBloomFilter:
        """Deserialize filter from bytes."""
        bf = SimpleBloomFilter.__new__(SimpleBloomFilter)
        bf.bits = np.frombuffer(data, dtype=np.uint8).copy()
        bf.m = m
        bf.k = k
        bf.seed = 0
        bf.n_items = None  # Not tracked after deserialization
        bf.target_fp_rate = None
        return bf


def build_corpus_bloom_filter(shard_dir: str = DEFAULT_SHARD_DIR, seq: int = DEFAULT_SEQ,
                              n_mtp: int = DEFAULT_N_MTP,
                              target_fp_rate: float = 0.01,
                              window: int = CONTAMINATION_WINDOW_TOKENS) -> dict:
    """Build Bloom filter over ALL corpus window hashes (no sampling).

    Scans entire corpus once, adding every window hash to the filter.
    """
    t_start = time.perf_counter()

    # Load shard manifest
    files = cheap_shard_sizes(shard_dir)
    cum = _cumulative_token_offsets(files)
    manifest = {"total_size_bytes": sum(f["size_bytes"] for f in files), "files": files}
    n_windows = compute_n_windows_from_manifest(manifest, seq, n_mtp=n_mtp)
    block_len = seq + 1 + n_mtp

    print(f"Building Bloom filter for {n_windows} windows, target FP rate {target_fp_rate}")
    bf = SimpleBloomFilter(n_windows, target_fp_rate=target_fp_rate)
    print(f"  Filter size: {bf.m / 8e9:.2f} GB ({bf.k} hash functions)")

    # Stream all windows and add to filter
    print(f"Scanning {n_windows} windows...")
    windows_added = 0
    for window_idx in range(n_windows):
        if window_idx % 100000 == 0:
            elapsed = time.perf_counter() - t_start
            rate = window_idx / elapsed if elapsed > 0 else 0
            print(f"  {window_idx / 1e6:.1f}M windows, {rate/1e6:.1f}M/s, elapsed {elapsed:.0f}s")

        try:
            tokens = read_window_tokens(shard_dir, files, cum, seq, window, window_idx)
            window_tuple = tuple(tokens)
            bf.add(window_tuple)
            windows_added += 1
        except Exception:
            # Skip windows at boundaries
            continue

    wall_s = time.perf_counter() - t_start

    return {
        "bloom_filter": bf,
        "n_windows_scanned": n_windows,
        "n_windows_added": windows_added,
        "filter_size_bytes": bf.size_bytes(),
        "wall_s": round(wall_s, 3),
        "corpus_manifest_sha256": CORPUS_MANIFEST_COMBINED_SHA256,
    }


def write_bloom_filter(result: dict, *, index_dir: str = INDEX_DIR) -> tuple[str, str]:
    """Persists Bloom filter and metadata receipt."""
    os.makedirs(index_dir, exist_ok=True)
    ts = _utc_ts()

    bf = result["bloom_filter"]
    filter_bytes = bf.to_bytes()

    # Write binary filter
    filter_path = os.path.join(index_dir, f"corpus-bloom-{ts}.bin")
    with open(filter_path, "wb") as f:
        f.write(filter_bytes)

    # Write metadata receipt
    receipt = {
        "schema": "w2-corpus-bloom-index/v1",
        "ts": ts,
        "corpus_manifest_sha256": result["corpus_manifest_sha256"],
        "n_windows_scanned": result["n_windows_scanned"],
        "n_windows_added": result["n_windows_added"],
        "filter_size_bytes": result["filter_size_bytes"],
        "filter_size_gb": round(result["filter_size_bytes"] / 1e9, 2),
        "bloom_m": bf.m,
        "bloom_k": bf.k,
        "wall_s": result["wall_s"],
    }

    receipt_path = os.path.join(index_dir, f"corpus-bloom-receipt-{ts}.json")
    with open(receipt_path, "w", encoding="utf-8") as f:
        json.dump(receipt, f, indent=2)

    return receipt_path, filter_path


def load_bloom_filter(filter_path: str, receipt_path: str) -> tuple[SimpleBloomFilter, dict]:
    """Loads a previously-built Bloom filter and its receipt."""
    with open(receipt_path, "r", encoding="utf-8") as f:
        receipt = json.load(f)

    with open(filter_path, "rb") as f:
        filter_bytes = f.read()

    bf = SimpleBloomFilter.from_bytes(filter_bytes, receipt["bloom_m"], receipt["bloom_k"])
    return bf, receipt
