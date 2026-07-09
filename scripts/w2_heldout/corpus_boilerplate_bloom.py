"""corpus_boilerplate_bloom.py -- Bloom filter index for boilerplate window keys.

RE-SCOPED #374: Bloom filter over ONLY the ≥f boilerplate window-key set
(f=1e-3 per-source thresholds from heldout-v21-fcalib receipt).

Differences from the original corpus_bloom_index.py (all 6.98B windows):
1. Index the ≥f set, not all windows (per-source k_f from receipt)
2. Boilerplate keys are extracted by --emit-boilerplate-keys flag in fcalib.py
3. Cap-saturated keys (count==cap) are CONSERVATIVELY DROPPED
4. Much smaller Bloom filter m (boilerplate ~1.5% of corpus positions)

Certification predicate per candidate window:
- source-disjointness (metadata) AND not-in-boilerplate-Bloom (O(1))
- Bloom hit → exact recheck (FP absorption)
- Zero false negatives by construction

Schema: w2-boilerplate-bloom-index/v1.
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
from typing import Optional

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_ROOT = os.path.dirname(HERE)
REPO_ROOT = os.path.dirname(SCRIPTS_ROOT)
sys.path.insert(0, SCRIPTS_ROOT)


def _utc_ts() -> str:
    """ISO8601 UTC timestamp."""
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
        parts = []
        for x in item:
            if isinstance(x, bytes):
                parts.append(x)
            elif isinstance(x, str):
                parts.append(x.encode())
            else:
                parts.append(str(x).encode())
        item_bytes = b"|".join(parts)
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


class BoilerplateBloomIndex:
    """Boilerplate Bloom filter index with per-source cap handling."""

    def __init__(self, bloom_filter: SimpleBloomFilter,
                 n_boilerplate_keys: int,
                 n_cap_saturated_keys: int = 0,
                 sources: list[str] | None = None):
        """Initialize index with built Bloom filter.

        Parameters:
          bloom_filter: SimpleBloomFilter instance
          n_boilerplate_keys: count of keys added to filter
          n_cap_saturated_keys: count of cap-saturated keys excluded (conservative drop)
          sources: list of source names indexed
        """
        self.bloom_filter = bloom_filter
        self.n_boilerplate_keys = n_boilerplate_keys
        self.n_cap_saturated_keys = n_cap_saturated_keys
        self.sources = sources or []
        self.n_sources = len(self.sources)

    @staticmethod
    def build_from_keys(boilerplate_keys: dict[str, list[bytes]],
                        cap_saturated_keys: dict[str, list[bytes]] | None = None,
                        target_fp_rate: float = 0.01) -> BoilerplateBloomIndex:
        """Build Bloom index from per-source boilerplate key sets.

        Parameters:
          boilerplate_keys: dict[source] -> list of window-key bytes
          cap_saturated_keys: dict[source] -> list of cap-saturated keys (excluded)
          target_fp_rate: target FP rate for Bloom filter

        Returns:
          BoilerplateBloomIndex instance with Bloom filter built
        """
        if cap_saturated_keys is None:
            cap_saturated_keys = {}

        # Count total boilerplate keys (excludes cap-saturated)
        n_boilerplate = sum(len(keys) for keys in boilerplate_keys.values())
        n_cap_saturated = sum(len(keys) for keys in cap_saturated_keys.values())

        # Build Bloom filter over boilerplate keys only
        bf = SimpleBloomFilter(
            n_items=max(1, n_boilerplate),
            target_fp_rate=target_fp_rate
        )

        # Add all boilerplate keys
        for keys in boilerplate_keys.values():
            for key in keys:
                bf.add((key,))

        sources = sorted(boilerplate_keys.keys())

        return BoilerplateBloomIndex(
            bloom_filter=bf,
            n_boilerplate_keys=n_boilerplate,
            n_cap_saturated_keys=n_cap_saturated,
            sources=sources
        )

    def write(self, output_dir: str, metadata: dict | None = None) -> tuple[str, str]:
        """Persist Bloom filter and metadata receipt.

        Parameters:
          output_dir: directory to write files
          metadata: optional metadata dict (f, cap, sources, etc.)

        Returns:
          (receipt_path, filter_path) tuple
        """
        os.makedirs(output_dir, exist_ok=True)
        ts = _utc_ts()

        # Write binary filter
        filter_bytes = self.bloom_filter.to_bytes()
        filter_path = os.path.join(output_dir, f"boilerplate-bloom-{ts}.bin")
        with open(filter_path, "wb") as f:
            f.write(filter_bytes)

        # Build receipt
        receipt = {
            "schema": "w2-boilerplate-bloom-index/v1",
            "ts": ts,
            "n_boilerplate_keys": self.n_boilerplate_keys,
            "n_cap_saturated_keys": self.n_cap_saturated_keys,
            "filter_size_bytes": self.bloom_filter.size_bytes(),
            "filter_size_mb": round(self.bloom_filter.size_bytes() / 1e6, 2),
            "bloom_m": self.bloom_filter.m,
            "bloom_k": self.bloom_filter.k,
            "n_sources": self.n_sources,
            "sources": self.sources,
        }

        # Merge metadata if provided
        if metadata:
            receipt.update(metadata)

        # Write receipt
        receipt_path = os.path.join(output_dir, f"boilerplate-bloom-receipt-{ts}.json")
        with open(receipt_path, "w", encoding="utf-8") as f:
            json.dump(receipt, f, indent=2)

        return receipt_path, filter_path

    @staticmethod
    def load(filter_path: str, receipt_path: str) -> BoilerplateBloomIndex:
        """Load previously-written index from disk.

        Parameters:
          filter_path: path to .bin filter file
          receipt_path: path to .json receipt file

        Returns:
          BoilerplateBloomIndex instance
        """
        with open(receipt_path, "r", encoding="utf-8") as f:
            receipt = json.load(f)

        with open(filter_path, "rb") as f:
            filter_bytes = f.read()

        bf = SimpleBloomFilter.from_bytes(
            filter_bytes,
            receipt["bloom_m"],
            receipt["bloom_k"]
        )

        return BoilerplateBloomIndex(
            bloom_filter=bf,
            n_boilerplate_keys=receipt["n_boilerplate_keys"],
            n_cap_saturated_keys=receipt.get("n_cap_saturated_keys", 0),
            sources=receipt.get("sources", [])
        )
