# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""certify_heldout_batch.py -- Certification predicate using boilerplate Bloom filter.

RE-SCOPED #374: certification predicate is TWO-PART:
1. source-disjointness (metadata check, cheap)
2. not-in-boilerplate-Bloom (O(1) filter check); Bloom hit → exact recheck
   (false-positive absorption -- RE-SCOPE RULING point 2, "unchanged from
   the original design") EXCEPT for cap-saturated keys, which are an
   UNCONDITIONAL drop with no recheck escape hatch (RE-SCOPE RULING point 3
   states the conservative rule with no absorption clause).

Per-batch receipt tracks:
- candidates: input batch size
- dropped_disjointness: windows rejected for source contamination
- bloom_hits: Bloom filter positives (potential FPs)
- exact_confirmed: windows confirmed as contaminated by recheck
- cap_dropped: windows from cap-saturated doc-frequency values
- bloom_fp_absorbed: Bloom positives that exact recheck cleared (rework372)

For f=1e-03 per-source thresholds from heldout-v21-fcalib:
- code_github_clean: k=1868 (exceeds cap → ambiguous)
- fineweb_edu: k=1550 (exceeds cap → ambiguous)
- wikipedia_en: k=814 (exceeds cap → ambiguous)
- gutenberg_en: k=10 (exact)
- ledger_mit: k=10 (exact)

Conservative rule: cap-saturated keys are treated as boilerplate. As of
rework372, this is enforced TWO ways: (1) the Bloom filter itself contains
cap-saturated keys "by construction" (corpus_boilerplate_bloom.py fix --
correctness no longer depends on the side channel below being populated),
and (2) `cap_saturated_per_source`, when supplied (e.g. via
BoilerplateBloomIndex.build_from_fcalib_boilerplate_keys), gives a clean
"cap_saturated" reason label instead of the generic "bloom_positive_*"
reasons for receipt readability.

exact_recheck_fn (rework372 addition, AC2): an optional
Callable[[bytes, str], bool] -- True means the exact recheck CONFIRMS the
Bloom hit is a true boilerplate/contamination match; False means the recheck
is NEGATIVE, i.e. the Bloom hit was a false positive, which the predicate
ABSORBS (the window is still certified). With no exact_recheck_fn supplied,
a Bloom hit is conservatively treated as confirmed (no absorption) -- the
original, safe default.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

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
    exact_confirmed: int           # Exact recheck confirmations (true positive)
    bloom_fp_absorbed: int         # Exact recheck cleared (false positive, certified anyway)
    cap_dropped: int               # Cap-saturated key rejections
    certified_count: int           # Passed both checks
    results: list[dict]            # Detailed per-window results


class HeldoutCertifier:
    """Certification engine using boilerplate Bloom index."""

    def __init__(self, bloom_index: BoilerplateBloomIndex,
                 cap_saturated_per_source: dict[str, set[bytes]] | None = None,
                 exact_recheck_fn: Optional[Callable[[bytes, str], bool]] = None):
        """Initialize certifier with Bloom index.

        Parameters:
          bloom_index: BoilerplateBloomIndex loaded from disk. Cap-saturated
            keys are expected to already be folded into this index's Bloom
            filter (see BoilerplateBloomIndex.build_from_keys) -- correctness
            does NOT depend on cap_saturated_per_source being populated.
          cap_saturated_per_source: OPTIONAL diagnostic label set per source
            (drop decision is already covered by the Bloom; this only turns
            a generic "bloom_positive_*" reason into "cap_saturated" for
            receipt readability).
          exact_recheck_fn: OPTIONAL callable(window_key, source) -> bool.
            True = exact recheck CONFIRMS the Bloom hit (true positive,
            reject). False = recheck NEGATIVE (Bloom false positive,
            ABSORB -- window is still certified). With no fn supplied, a
            Bloom hit is conservatively treated as confirmed (matches the
            pre-rework372 default; no silent behavior change for callers
            that don't pass this).
        """
        self.bloom_index = bloom_index
        self.cap_saturated_per_source = cap_saturated_per_source or {}
        self.exact_recheck_fn = exact_recheck_fn

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

        Two-part predicate (AC2): certified =
          source_disjoint(window)
          AND (not bloom.contains(key) OR exact_recheck_negative(key))
        with cap-saturated keys an UNCONDITIONAL drop (no recheck escape
        hatch -- RE-SCOPE RULING point 3).

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

        # Check 2a: cap-saturation diagnostic label (UNCONDITIONAL drop, no
        # recheck absorption -- correctness here does not depend on this
        # side-channel: cap-saturated keys are also folded into the Bloom
        # itself, so a caller with no cap_saturated_per_source still gets
        # the correct drop via check 2b below, just with a generic reason).
        if self._is_cap_saturated(window_key, source):
            return CertificationResult(
                window_key=window_key,
                source=source,
                certified=False,
                reason="cap_saturated",
                bloom_hit=True
            )

        # Check 2b: boilerplate Bloom filter, with exact-recheck absorption
        bloom_hit = self._check_boilerplate(window_key)
        if bloom_hit:
            if self.exact_recheck_fn is not None:
                confirmed = self.exact_recheck_fn(window_key, source)
                if confirmed:
                    return CertificationResult(
                        window_key=window_key,
                        source=source,
                        certified=False,
                        reason="bloom_positive_confirmed",
                        bloom_hit=True,
                        exact_confirmed=True
                    )
                # Recheck negative: Bloom false positive, ABSORBED
                return CertificationResult(
                    window_key=window_key,
                    source=source,
                    certified=True,
                    reason="bloom_positive_fp_absorbed",
                    bloom_hit=True,
                    exact_confirmed=False
                )
            # No recheck oracle available: conservative default (unchanged
            # from the pre-rework372 behavior -- no silent behavior change
            # for callers that don't supply exact_recheck_fn)
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
        exact_confirmed = 0
        bloom_fp_absorbed = 0
        cap_dropped = 0
        certified = 0
        results = []

        for window_key, source in candidates:
            result = self.certify_window(window_key, source, sources_in_batch)

            if result.reason == "source_contamination":
                dropped_disjointness += 1
            elif result.reason == "cap_saturated":
                cap_dropped += 1
            elif result.reason in ("bloom_positive", "bloom_positive_confirmed",
                                    "bloom_positive_fp_absorbed"):
                bloom_hits += 1
                if result.reason == "bloom_positive_confirmed":
                    exact_confirmed += 1
                elif result.reason == "bloom_positive_fp_absorbed":
                    bloom_fp_absorbed += 1

            if result.certified:
                certified += 1

            results.append({
                "source": result.source,
                "certified": result.certified,
                "reason": result.reason,
                "bloom_hit": result.bloom_hit,
            })

        return CertificationBatchReceipt(
            ts=_utc_ts(),
            batch_size=batch_size,
            candidates=batch_size,
            dropped_disjointness=dropped_disjointness,
            bloom_hits=bloom_hits,
            exact_confirmed=exact_confirmed,
            bloom_fp_absorbed=bloom_fp_absorbed,
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
