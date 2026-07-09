"""certify_heldout_batch.py -- Certification predicate using boilerplate Bloom filter.

RE-SCOPED #374: certification predicate is TWO-PART:
1. source-disjointness (metadata check, cheap)
2. not-in-boilerplate-Bloom (O(1) filter check); Bloom hit → exact recheck

Per-batch receipt tracks:
- candidates: input batch size
- dropped_disjointness: windows rejected for source contamination
- bloom_hits: Bloom filter positives (potential FPs)
- exact_confirmed: windows confirmed as contaminated by recheck
- cap_dropped: windows from cap-saturated doc-frequency values

For f=1e-03 per-source thresholds from heldout-v21-fcalib:
- code_github_clean: k=1868 (exceeds cap → ambiguous)
- fineweb_edu: k=1550 (exceeds cap → ambiguous)
- wikipedia_en: k=814 (exceeds cap → ambiguous)
- gutenberg_en: k=10 (exact)
- ledger_mit: k=10 (exact)

Conservative rule: cap-saturated keys are treated as boilerplate.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_ROOT = os.path.dirname(HERE)
REPO_ROOT = os.path.dirname(SCRIPTS_ROOT)
sys.path.insert(0, SCRIPTS_ROOT)

from w2_heldout.corpus_boilerplate_bloom import BoilerplateBloomIndex


def _utc_ts() -> str:
    """ISO8601 UTC timestamp."""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


@dataclass
class CertificationResult:
    """Result of certifying a single candidate window."""
    window_key: bytes
    source: str
    certified: bool  # True if passes both checks
    reason: str      # Why it was/wasn't certified
    bloom_hit: bool = False          # Did it hit the Bloom filter?
    exact_confirmed: bool = False    # Was it confirmed by exact recheck?


@dataclass
class CertificationBatchReceipt:
    """Receipt for a batch of certified candidates."""
    ts: str
    batch_size: int
    candidates: int
    dropped_disjointness: int      # Source contamination rejections
    bloom_hits: int                # Bloom filter positives
    exact_confirmed: int           # Exact recheck confirmations
    cap_dropped: int               # Cap-saturated key rejections
    certified_count: int           # Passed both checks
    results: list[dict]            # Detailed per-window results


class HeldoutCertifier:
    """Certification engine using boilerplate Bloom index."""

    def __init__(self, bloom_index: BoilerplateBloomIndex,
                 cap_saturated_per_source: dict[str, set[bytes]] | None = None):
        """Initialize certifier with Bloom index.

        Parameters:
          bloom_index: BoilerplateBloomIndex loaded from disk
          cap_saturated_per_source: conservative drop set per source
        """
        self.bloom_index = bloom_index
        self.cap_saturated_per_source = cap_saturated_per_source or {}

    def _check_source_disjointness(self, sources_in_batch: set[str]) -> bool:
        """Check if batch has documents from multiple sources.

        Returns True (disjoint) only if all sources in the batch are the SAME.
        """
        return len(sources_in_batch) == 1

    def _check_boilerplate(self, window_key: bytes) -> bool:
        """Check if window is in boilerplate Bloom filter.

        Returns True if the key is likely in boilerplate (Bloom hit).
        False negatives: impossible (Bloom property)
        False positives: possible (absorbed by exact recheck downstream)
        """
        return self.bloom_index.bloom_filter.contains((window_key,))

    def _is_cap_saturated(self, window_key: bytes, source: str) -> bool:
        """Check if window was marked as cap-saturated.

        Cap-saturated keys are conservatively treated as boilerplate.
        """
        if source not in self.cap_saturated_per_source:
            return False
        return window_key in self.cap_saturated_per_source[source]

    def certify_window(self, window_key: bytes, source: str,
                      sources_in_batch: set[str]) -> CertificationResult:
        """Certify a single candidate window.

        Two-part predicate:
        1. source-disjointness: all windows in batch from same source
        2. not-in-boilerplate-Bloom: O(1) check + conservative drop rule

        Parameters:
          window_key: the 50*2-byte window key
          source: source name (must match batch)
          sources_in_batch: set of all sources in batch

        Returns:
          CertificationResult with verdict
        """
        # Check 1: source-disjointness
        if not self._check_source_disjointness(sources_in_batch):
            return CertificationResult(
                window_key=window_key,
                source=source,
                certified=False,
                reason="source_contamination"
            )

        # Check 2a: cap-saturation (conservative drop)
        if self._is_cap_saturated(window_key, source):
            return CertificationResult(
                window_key=window_key,
                source=source,
                certified=False,
                reason="cap_saturated"
            )

        # Check 2b: boilerplate Bloom filter
        bloom_hit = self._check_boilerplate(window_key)
        if bloom_hit:
            # Bloom positive: potential FP, exact recheck would confirm/deny
            # For this module, we conservatively mark as non-certified pending recheck
            return CertificationResult(
                window_key=window_key,
                source=source,
                certified=False,
                reason="bloom_positive",
                bloom_hit=True
            )

        # Passed all checks
        return CertificationResult(
            window_key=window_key,
            source=source,
            certified=True,
            reason="certified"
        )

    def certify_batch(self, candidates: list[tuple[bytes, str]],
                      sources_in_batch: set[str]) -> CertificationBatchReceipt:
        """Certify a batch of candidate windows.

        Parameters:
          candidates: list of (window_key, source) tuples
          sources_in_batch: set of all sources in batch

        Returns:
          CertificationBatchReceipt with aggregated results
        """
        batch_size = len(candidates)
        dropped_disjointness = 0
        bloom_hits = 0
        cap_dropped = 0
        certified = 0
        results = []

        for window_key, source in candidates:
            result = self.certify_window(window_key, source, sources_in_batch)

            if result.reason == "source_contamination":
                dropped_disjointness += 1
            elif result.reason == "cap_saturated":
                cap_dropped += 1
            elif result.reason == "bloom_positive":
                bloom_hits += 1

            if result.certified:
                certified += 1

            results.append({
                "source": result.source,
                "certified": result.certified,
                "reason": result.reason,
                "bloom_hit": result.bloom_hit,
            })

        # Exact recheck would be run on bloom_hits in a downstream step
        # For now, we report them separately
        exact_confirmed = 0  # Would be populated by contamination_recheck

        return CertificationBatchReceipt(
            ts=_utc_ts(),
            batch_size=batch_size,
            candidates=batch_size,
            dropped_disjointness=dropped_disjointness,
            bloom_hits=bloom_hits,
            exact_confirmed=exact_confirmed,
            cap_dropped=cap_dropped,
            certified_count=certified,
            results=results
        )

    def write_receipt(self, receipt: CertificationBatchReceipt,
                      output_path: str) -> str:
        """Write certification receipt to JSON file.

        Parameters:
          receipt: CertificationBatchReceipt object
          output_path: path to write receipt

        Returns:
          output_path
        """
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

        receipt_dict = asdict(receipt)
        receipt_dict["schema"] = "w2-certification-batch/v1"

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(receipt_dict, f, indent=2)

        return output_path
