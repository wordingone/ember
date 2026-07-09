"""test_certify_heldout_batch.py -- TDD for certification predicate.

Tests the two-part certification check:
1. Source-disjointness (metadata)
2. Not-in-boilerplate-Bloom (O(1)) + cap-saturation conservative drop

Synthetic fixtures only (CI-runnable).
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_ROOT = os.path.dirname(HERE)
REPO_ROOT = os.path.dirname(SCRIPTS_ROOT)
sys.path.insert(0, SCRIPTS_ROOT)

from w2_heldout.corpus_boilerplate_bloom import BoilerplateBloomIndex
from w2_heldout.certify_heldout_batch import (
    HeldoutCertifier,
    CertificationResult,
    CertificationBatchReceipt,
)


class TestHeldoutCertifier:
    """HeldoutCertifier: certification engine with two-part predicate."""

    def _make_certifier(self, boilerplate_keys: dict | None = None):
        """Helper to create a certifier with fixture Bloom index."""
        if boilerplate_keys is None:
            boilerplate_keys = {
                "source_a": [b"key_1", b"key_2"],
                "source_b": [b"key_10"],
            }

        bloom_index = BoilerplateBloomIndex.build_from_keys(
            boilerplate_keys,
            target_fp_rate=0.01
        )

        return HeldoutCertifier(bloom_index)

    def test_source_disjointness_check_passes_single_source(self):
        """Batch with windows from one source passes disjointness check."""
        certifier = self._make_certifier()

        # Single source in batch
        sources = {"source_a"}
        assert certifier._check_source_disjointness(sources) is True

    def test_source_disjointness_check_fails_multiple_sources(self):
        """Batch with windows from multiple sources fails disjointness."""
        certifier = self._make_certifier()

        # Multiple sources in batch
        sources = {"source_a", "source_b"}
        assert certifier._check_source_disjointness(sources) is False

    def test_boilerplate_check_hits_boilerplate_keys(self):
        """Boilerplate keys hit the Bloom filter."""
        certifier = self._make_certifier({
            "source_a": [b"boilerplate_1"],
        })

        # Key that's in the boilerplate set should hit Bloom
        assert certifier._check_boilerplate(b"boilerplate_1") is True

    def test_boilerplate_check_misses_clean_keys(self):
        """Clean (non-boilerplate) keys don't hit Bloom filter."""
        certifier = self._make_certifier({
            "source_a": [b"boilerplate_1"],
        })

        # Key not in boilerplate set should miss Bloom (definite clean)
        assert certifier._check_boilerplate(b"clean_key_xyz") is False

    def test_certify_single_window_passes(self):
        """Window passes certification if not in boilerplate."""
        certifier = self._make_certifier({
            "source_a": [b"boilerplate_1"],
        })

        # Window with single source, not in boilerplate
        result = certifier.certify_window(
            window_key=b"clean_window",
            source="source_a",
            sources_in_batch={"source_a"}
        )

        assert result.certified is True
        assert result.reason == "certified"

    def test_certify_single_window_fails_boilerplate(self):
        """Window fails if it hits boilerplate Bloom filter."""
        certifier = self._make_certifier({
            "source_a": [b"boilerplate_1"],
        })

        result = certifier.certify_window(
            window_key=b"boilerplate_1",
            source="source_a",
            sources_in_batch={"source_a"}
        )

        assert result.certified is False
        assert result.reason == "bloom_positive"
        assert result.bloom_hit is True

    def test_certify_single_window_fails_source_contamination(self):
        """Window fails if batch has multiple sources."""
        certifier = self._make_certifier()

        result = certifier.certify_window(
            window_key=b"clean_key",
            source="source_a",
            sources_in_batch={"source_a", "source_b"}  # Multiple sources!
        )

        assert result.certified is False
        assert result.reason == "source_contamination"

    def test_certify_single_window_fails_cap_saturated(self):
        """Window fails if marked as cap-saturated (conservative drop)."""
        certifier = self._make_certifier({
            "source_a": [b"regular_key"],
        })

        # Mark a key as cap-saturated
        certifier.cap_saturated_per_source = {
            "source_a": {b"capped_key"}
        }

        result = certifier.certify_window(
            window_key=b"capped_key",
            source="source_a",
            sources_in_batch={"source_a"}
        )

        assert result.certified is False
        assert result.reason == "cap_saturated"

    def test_certify_batch_single_source_all_clean(self):
        """Batch certification with single source, all clean windows."""
        certifier = self._make_certifier({
            "source_a": [b"boilerplate_1"],
        })

        candidates = [
            (b"clean_1", "source_a"),
            (b"clean_2", "source_a"),
            (b"clean_3", "source_a"),
        ]

        receipt = certifier.certify_batch(candidates, {"source_a"})

        assert receipt.batch_size == 3
        assert receipt.certified_count == 3
        assert receipt.dropped_disjointness == 0
        assert receipt.bloom_hits == 0
        assert receipt.cap_dropped == 0

    def test_certify_batch_with_boilerplate_hits(self):
        """Batch with mix of clean and boilerplate windows."""
        certifier = self._make_certifier({
            "source_a": [b"boilerplate_1", b"boilerplate_2"],
        })

        candidates = [
            (b"clean_1", "source_a"),
            (b"boilerplate_1", "source_a"),
            (b"clean_2", "source_a"),
            (b"boilerplate_2", "source_a"),
        ]

        receipt = certifier.certify_batch(candidates, {"source_a"})

        assert receipt.batch_size == 4
        assert receipt.certified_count == 2
        assert receipt.bloom_hits == 2
        assert receipt.dropped_disjointness == 0

    def test_certify_batch_with_source_contamination(self):
        """Batch with multiple sources gets rejected."""
        certifier = self._make_certifier()

        candidates = [
            (b"key_a", "source_a"),
            (b"key_b", "source_b"),
        ]

        receipt = certifier.certify_batch(candidates, {"source_a", "source_b"})

        assert receipt.batch_size == 2
        assert receipt.certified_count == 0
        assert receipt.dropped_disjointness == 2

    def test_certify_batch_receipt_schema(self):
        """Batch receipt has correct schema."""
        certifier = self._make_certifier()

        candidates = [(b"clean_1", "source_a")]
        receipt = certifier.certify_batch(candidates, {"source_a"})

        # Check receipt fields
        assert receipt.ts is not None
        assert receipt.batch_size == 1
        # Schema is added during write(), not in batch result
        assert len(receipt.results) == 1

    def test_write_receipt_to_file(self):
        """Write certification receipt to JSON file."""
        certifier = self._make_certifier()

        candidates = [
            (b"clean_1", "source_a"),
            (b"clean_2", "source_a"),
        ]
        receipt = certifier.certify_batch(candidates, {"source_a"})

        with tempfile.TemporaryDirectory() as tmpdir:
            receipt_path = os.path.join(tmpdir, "cert-receipt.json")
            certifier.write_receipt(receipt, receipt_path)

            # Verify file exists and has correct schema
            assert Path(receipt_path).exists()

            with open(receipt_path) as f:
                data = json.load(f)

            assert data["schema"] == "w2-certification-batch/v1"
            assert data["batch_size"] == 2
            assert data["certified_count"] == 2

    def test_certification_result_fields(self):
        """CertificationResult has all required fields."""
        result = CertificationResult(
            window_key=b"test_key",
            source="source_a",
            certified=True,
            reason="certified",
            bloom_hit=False,
            exact_confirmed=False
        )

        assert result.window_key == b"test_key"
        assert result.source == "source_a"
        assert result.certified is True
        assert result.reason == "certified"

    def test_batch_receipt_aggregation_counts(self):
        """Batch receipt correctly aggregates all rejection categories."""
        certifier = self._make_certifier({
            "source_a": [b"boilerplate_key"],
        })

        # Add cap-saturated keys
        certifier.cap_saturated_per_source = {
            "source_a": {b"capped_key"}
        }

        # Test 1: batch with single source shows all rejection types
        candidates_single_source = [
            (b"clean_1", "source_a"),           # certified
            (b"boilerplate_key", "source_a"),   # bloom_hit
            (b"capped_key", "source_a"),        # cap_dropped
        ]

        receipt = certifier.certify_batch(
            candidates_single_source,
            {"source_a"}
        )

        assert receipt.batch_size == 3
        assert receipt.certified_count == 1
        assert receipt.bloom_hits == 1
        assert receipt.cap_dropped == 1
        assert receipt.dropped_disjointness == 0

        # Test 2: batch with multiple sources rejects ALL windows
        candidates_multi_source = [
            (b"clean_1", "source_a"),
            (b"clean_2", "source_b"),
        ]

        receipt2 = certifier.certify_batch(
            candidates_multi_source,
            {"source_a", "source_b"}
        )

        assert receipt2.batch_size == 2
        assert receipt2.certified_count == 0
        assert receipt2.dropped_disjointness == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
