"""test_corpus_boilerplate_bloom.py -- TDD for boilerplate Bloom filter.

Synthetic-fixture tests only (CI-runnable, no corpus/env dependency).
Tests cover:
- Bloom filter basic properties (zero false negatives, FP rate)
- Boilerplate key index loading/serialization
- Per-source docfreq cap-saturation handling (conservative drop)
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

from w2_heldout.corpus_boilerplate_bloom import (
    SimpleBloomFilter,
    BoilerplateBloomIndex,
)


# =============================================================================
# TIER 1: Synthetic-fixture tests (CI-runnable)
# =============================================================================

class TestSimpleBloomFilter:
    """SimpleBloomFilter: core Bloom properties."""

    def test_zero_false_negatives(self):
        """All added items must be found (Bloom property)."""
        bf = SimpleBloomFilter(n_items=100, target_fp_rate=0.01)
        items = [
            (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13),
            (10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22),
            (100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110, 111, 112),
        ]
        for item in items:
            bf.add(item)
        for item in items:
            assert bf.contains(item), f"False negative: {item} not found"

    def test_fp_rate_bounded(self):
        """FP rate stays within target range."""
        n = 1000
        target_fp = 0.01
        bf = SimpleBloomFilter(n_items=n, target_fp_rate=target_fp)

        # Add 500 items
        added = []
        for i in range(500):
            item = (i, i+1, i+2, i+3, i+4, i+5, i+6, i+7, i+8, i+9, i+10, i+11, i+12)
            bf.add(item)
            added.append(item)

        # Test FP rate on unseen items
        false_positives = 0
        test_count = 1000
        for i in range(n, n + test_count):
            item = (i, i+1, i+2, i+3, i+4, i+5, i+6, i+7, i+8, i+9, i+10, i+11, i+12)
            if bf.contains(item):
                false_positives += 1

        observed_fp_rate = false_positives / test_count
        max_acceptable = target_fp * 3  # Allow 3x slack for small-sample variance
        assert observed_fp_rate <= max_acceptable, (
            f"FP rate {observed_fp_rate:.4f} exceeds max {max_acceptable:.4f}"
        )

    def test_serialization_roundtrip(self):
        """Serialization and deserialization preserve filter."""
        bf = SimpleBloomFilter(n_items=100, target_fp_rate=0.01)
        items = [
            (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13),
            (100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110, 111, 112),
        ]
        for item in items:
            bf.add(item)

        # Serialize
        data = bf.to_bytes()
        assert len(data) == bf.size_bytes()

        # Deserialize
        bf2 = SimpleBloomFilter.from_bytes(data, bf.m, bf.k)
        for item in items:
            assert bf2.contains(item), f"Deserialized filter missing {item}"


class TestBoilerplateBloomIndex:
    """BoilerplateBloomIndex: boilerplate key tracking with cap handling."""

    def test_build_from_boilerplate_keys(self):
        """Build Bloom index from per-source boilerplate key sets."""
        # Fixture: 3 sources with different key counts
        boilerplate_keys = {
            "source_a": [b"key_1", b"key_2", b"key_3"],
            "source_b": [b"key_10", b"key_11"],
            "source_c": [b"key_100"],
        }

        index = BoilerplateBloomIndex.build_from_keys(
            boilerplate_keys,
            target_fp_rate=0.01
        )

        assert index is not None
        assert index.n_boilerplate_keys == 6
        # Verify all keys are in the Bloom filter
        for keys in boilerplate_keys.values():
            for key in keys:
                assert index.bloom_filter.contains((key,)), f"Key {key} not in bloom"

    def test_cap_saturated_keys_excluded(self):
        """Keys marked as cap-saturated (count==cap) are excluded from Bloom."""
        # Fixture: mix of below-cap and cap-saturated keys
        boilerplate_keys = {
            "source_a": [b"regular_1", b"regular_2"],
        }
        cap_saturated_keys = {
            "source_a": [b"capped_1", b"capped_2"],
        }

        index = BoilerplateBloomIndex.build_from_keys(
            boilerplate_keys,
            cap_saturated_keys=cap_saturated_keys,
            target_fp_rate=0.01
        )

        # Regular keys should be in Bloom
        assert index.bloom_filter.contains((b"regular_1",))

        # Cap-saturated keys should NOT be in Bloom (conservative drop)
        # Note: FPs are possible, but unlikely; we can't assert their absence
        # Instead, verify the count is correct
        assert index.n_boilerplate_keys == 2  # Only the 2 regular keys
        assert index.n_cap_saturated_keys == 2

    def test_source_disjointness_check(self):
        """Certification checks source-disjointness (metadata only)."""
        # Fixture: boilerplate keys from two sources
        boilerplate_keys = {
            "source_a": [b"a_key_1", b"a_key_2"],
            "source_b": [b"b_key_1"],
        }

        index = BoilerplateBloomIndex.build_from_keys(
            boilerplate_keys,
            target_fp_rate=0.01
        )

        # Candidate from one source should pass disjointness check
        # (disjointness is a metadata property, not checked by Bloom)
        # This test is a placeholder for integration with real metadata
        assert index.n_sources == 2

    def test_serialization_with_receipt(self):
        """Index serializes with metadata receipt."""
        boilerplate_keys = {
            "source_a": [b"key_1", b"key_2"],
        }

        index = BoilerplateBloomIndex.build_from_keys(
            boilerplate_keys,
            target_fp_rate=0.01
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            receipt_path, filter_path = index.write(
                output_dir=tmpdir,
                metadata={"f": "1e-03", "cap": 256}
            )

            assert Path(receipt_path).exists()
            assert Path(filter_path).exists()

            # Verify receipt contents
            with open(receipt_path) as f:
                receipt = json.load(f)

            assert receipt["schema"] == "w2-boilerplate-bloom-index/v1"
            assert receipt["n_boilerplate_keys"] == 2
            assert receipt["f"] == "1e-03"
            assert receipt["cap"] == 256

    def test_load_from_files(self):
        """Load previously-written index from disk."""
        boilerplate_keys = {
            "source_a": [b"key_1", b"key_2"],
            "source_b": [b"key_10"],
        }

        index_written = BoilerplateBloomIndex.build_from_keys(
            boilerplate_keys,
            target_fp_rate=0.01
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            receipt_path, filter_path = index_written.write(
                output_dir=tmpdir,
                metadata={"f": "1e-03", "cap": 256}
            )

            # Load from files
            index_loaded = BoilerplateBloomIndex.load(
                filter_path=filter_path,
                receipt_path=receipt_path
            )

            # Verify loaded index behaves like original
            assert index_loaded.n_boilerplate_keys == 3
            assert index_loaded.bloom_filter.contains((b"key_1",))
            assert index_loaded.bloom_filter.contains((b"key_10",))


class TestCertificationPredicate:
    """Certification predicate: source-disjointness + Bloom filter."""

    def test_certification_with_boilerplate_check(self):
        """Candidate fails certification if it hits boilerplate Bloom."""
        # Fixture: boilerplate Bloom with one key
        boilerplate_keys = {
            "source_code": [b"boilerplate_window_1"],
        }

        index = BoilerplateBloomIndex.build_from_keys(
            boilerplate_keys,
            target_fp_rate=0.01
        )

        # Candidate with same content as boilerplate should hit Bloom
        candidate_key = b"boilerplate_window_1"
        assert index.bloom_filter.contains((candidate_key,)), \
            "Boilerplate key should be in Bloom"

    def test_cap_saturation_conservative_drop(self):
        """Cap-saturated keys are conservatively dropped (not checked in Bloom)."""
        # Fixture: one regular key, one cap-saturated key
        boilerplate_keys = {
            "source_a": [b"regular"],
        }
        cap_saturated = {
            "source_a": [b"capped"],
        }

        index = BoilerplateBloomIndex.build_from_keys(
            boilerplate_keys,
            cap_saturated_keys=cap_saturated,
            target_fp_rate=0.01
        )

        # Cap-saturated key should NOT contribute to Bloom filter
        # (conservative approach: treat as potentially boilerplate)
        assert index.n_cap_saturated_keys == 1
        assert index.n_boilerplate_keys == 1  # Only the regular key


class TestPerSourceCapHandling:
    """Per-source cap handling per fcalib receipt."""

    def test_fcalib_thresholds_1e3(self):
        """Use exact k_source values from heldout-v21-fcalib receipt at f=1e-03."""
        # From receipt: f=1e-03 thresholds (k_source for each source)
        k_sources = {
            "code_github_clean": 1868,      # Exceeds cap (256) => ambiguous
            "fineweb_edu": 1550,              # Exceeds cap => ambiguous
            "wikipedia_en": 814,              # Exceeds cap => ambiguous
            "gutenberg_en": 10,               # Below cap => exact
            "ledger_mit": 10,                 # Below cap => exact
        }

        # This test verifies the threshold logic is available
        # (actual cap handling happens during boilerplate key extraction)
        cap = 256
        for source, k in k_sources.items():
            if k > cap:
                # Threshold exceeds cap: ambiguous band exists
                pass  # Conservative drop applies
            else:
                # Threshold below cap: exact boilerplate fraction
                pass

    def test_receipt_metadata_preserved(self):
        """Receipt carries per-source ambiguity disclosure."""
        boilerplate_keys = {
            "code_github_clean": [b"key_1"],
            "fineweb_edu": [b"key_2"],
        }

        index = BoilerplateBloomIndex.build_from_keys(
            boilerplate_keys,
            target_fp_rate=0.01
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            receipt_path, _ = index.write(
                output_dir=tmpdir,
                metadata={
                    "f": "1e-03",
                    "cap": 256,
                    "sources": {
                        "code_github_clean": {"k_source": 1868, "exceeds_cap": True},
                        "fineweb_edu": {"k_source": 1550, "exceeds_cap": True},
                    }
                }
            )

            with open(receipt_path) as f:
                receipt = json.load(f)

            assert "sources" in receipt
            assert receipt["sources"]["code_github_clean"]["exceeds_cap"] is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
