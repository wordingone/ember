# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Regression tests for w1_recheck_cache.py (#351).

Red-first test cases:
  1. Modified batch => cache miss (full recheck fires)
  2. Modified classifier code => cache miss
  3. Cache hit => recheck skipped + disclosure in receipt
"""

import json
import os
import tempfile
import unittest
from unittest import mock

# Assuming test is run from scripts/ directory
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from w1_recheck_cache import (
    compute_batch_sha,
    compute_cache_key,
    cache_entry_path,
    check_recheck_cache,
    write_recheck_cache,
    disclose_cache_hit,
    sha256_bytes,
)


class TestRecheckCacheBasic(unittest.TestCase):
    """Basic cache functionality tests."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        # Simple test batch: one row with 10 tokens
        self.eval_rows_1 = [[1, 2, 3, 4, 5, 6, 7, 8, 9, 10]]
        # Modified batch: different tokens
        self.eval_rows_2 = [[1, 2, 3, 4, 5, 6, 7, 8, 9, 11]]
        # Same tokens, different order (should be different sha)
        self.eval_rows_3 = [[11, 9, 8, 7, 6, 5, 4, 3, 2, 1]]

        # Mock contamination result (CLEAN verdict, cached result)
        self.mock_clean_contamination = {
            "verdict": "CLEAN",
            "method": "13-token polynomial rolling hash",
            "confirmed_matches": [],
            "hash_collisions_ruled_out": 0,
        }

        # Mock contamination result (CONTAMINATED verdict, should NOT be cached)
        self.mock_contaminated = {
            "verdict": "CONTAMINATED",
            "method": "13-token polynomial rolling hash",
            "confirmed_matches": [{"shard": "test.bin", "offset": 100, "window": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13]}],
            "hash_collisions_ruled_out": 0,
        }

    def test_batch_sha_identical_content(self):
        """Same batch content yields same sha."""
        sha1 = compute_batch_sha(self.eval_rows_1)
        sha2 = compute_batch_sha(self.eval_rows_1)
        self.assertEqual(sha1, sha2)

    def test_batch_sha_different_content(self):
        """Different batch content yields different sha (test 1)."""
        sha1 = compute_batch_sha(self.eval_rows_1)
        sha2 = compute_batch_sha(self.eval_rows_2)
        self.assertNotEqual(sha1, sha2)

    def test_batch_sha_different_order(self):
        """Different token order yields different sha."""
        sha1 = compute_batch_sha(self.eval_rows_1)
        sha3 = compute_batch_sha(self.eval_rows_3)
        self.assertNotEqual(sha1, sha3)

    def test_cache_key_triple(self):
        """Cache key is a triple (batch, receipt, code)."""
        # Create dummy files for receipt and code
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', dir=self.temp_dir, delete=False) as rf:
            rf.write('{"test": "receipt"}')
            receipt_path = rf.name
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', dir=self.temp_dir, delete=False) as cf:
            cf.write('# test code')
            code_path = cf.name

        try:
            batch_sha, receipt_sha, code_sha = compute_cache_key(
                self.eval_rows_1, receipt_path, code_path
            )
            # All three should be non-empty hex strings
            self.assertEqual(len(batch_sha), 64)  # sha256 hex = 64 chars
            self.assertEqual(len(receipt_sha), 64)
            self.assertEqual(len(code_sha), 64)
            # All three should be different
            self.assertNotEqual(batch_sha, receipt_sha)
            self.assertNotEqual(batch_sha, code_sha)
            self.assertNotEqual(receipt_sha, code_sha)
        finally:
            os.unlink(receipt_path)
            os.unlink(code_path)

    def test_cache_key_no_receipt(self):
        """Cache key with missing receipt path uses empty receipt_sha."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', dir=self.temp_dir, delete=False) as cf:
            cf.write('# test code')
            code_path = cf.name

        try:
            batch_sha, receipt_sha, code_sha = compute_cache_key(
                self.eval_rows_1, None, code_path
            )
            self.assertEqual(len(batch_sha), 64)
            self.assertEqual(receipt_sha, "")  # No receipt = empty string
            self.assertEqual(len(code_sha), 64)
        finally:
            os.unlink(code_path)

    def test_cache_write_clean_verdict(self):
        """Writing a CLEAN verdict creates cache entry."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', dir=self.temp_dir, delete=False) as cf:
            cf.write('# test code')
            code_path = cf.name

        try:
            # Write cache with CLEAN verdict
            cache_path = write_recheck_cache(
                self.mock_clean_contamination,
                self.eval_rows_1,
                None,  # no receipt
                self.temp_dir,
                classifier_code_path=code_path
            )
            # Cache path should be returned
            self.assertTrue(cache_path)
            self.assertTrue(os.path.exists(cache_path))

            # Verify cache file format
            with open(cache_path, 'r') as f:
                cached = json.load(f)
            self.assertEqual(cached["verdict"], "CLEAN")
            self.assertIn("cache_write_ts", cached)
            self.assertIn("cache_key_batch_sha256", cached)
            self.assertIn("original_receipt_sha", cached)
        finally:
            os.unlink(code_path)

    def test_cache_write_contaminated_not_cached(self):
        """Writing a CONTAMINATED verdict does NOT create cache entry."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', dir=self.temp_dir, delete=False) as cf:
            cf.write('# test code')
            code_path = cf.name

        try:
            # Write cache with CONTAMINATED verdict
            cache_path = write_recheck_cache(
                self.mock_contaminated,
                self.eval_rows_1,
                None,
                self.temp_dir,
                classifier_code_path=code_path
            )
            # No cache path returned for non-PASS verdict
            self.assertEqual(cache_path, "")
        finally:
            os.unlink(code_path)

    def test_cache_hit_clean_verdict(self):
        """Cache hit returns cached CLEAN result."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', dir=self.temp_dir, delete=False) as cf:
            cf.write('# test code')
            code_path = cf.name

        try:
            # Write cache first
            write_recheck_cache(
                self.mock_clean_contamination,
                self.eval_rows_1,
                None,
                self.temp_dir,
                classifier_code_path=code_path
            )

            # Now check cache with same batch
            cached = check_recheck_cache(
                self.eval_rows_1,
                "/fake/shard/dir",
                None,
                self.temp_dir,
                classifier_code_path=code_path
            )
            self.assertIsNotNone(cached)
            self.assertEqual(cached["verdict"], "CLEAN")
            self.assertTrue("cache_write_ts" in cached)
        finally:
            os.unlink(code_path)

    def test_cache_miss_modified_batch(self):
        """Modified batch triggers cache miss (test case 1)."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', dir=self.temp_dir, delete=False) as cf:
            cf.write('# test code')
            code_path = cf.name

        try:
            # Write cache for eval_rows_1
            write_recheck_cache(
                self.mock_clean_contamination,
                self.eval_rows_1,
                None,
                self.temp_dir,
                classifier_code_path=code_path
            )

            # Check cache with different batch (eval_rows_2)
            cached = check_recheck_cache(
                self.eval_rows_2,
                "/fake/shard/dir",
                None,
                self.temp_dir,
                classifier_code_path=code_path
            )
            # Should miss because batch sha is different
            self.assertIsNone(cached)
        finally:
            os.unlink(code_path)

    def test_cache_miss_modified_code(self):
        """Modified classifier code triggers cache miss (test case 2)."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', dir=self.temp_dir, delete=False) as cf1:
            cf1.write('# test code v1')
            code_path_1 = cf1.name
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', dir=self.temp_dir, delete=False) as cf2:
            cf2.write('# test code v2 modified')
            code_path_2 = cf2.name

        try:
            # Write cache with code v1
            write_recheck_cache(
                self.mock_clean_contamination,
                self.eval_rows_1,
                None,
                self.temp_dir,
                classifier_code_path=code_path_1
            )

            # Check cache with code v2
            cached = check_recheck_cache(
                self.eval_rows_1,
                "/fake/shard/dir",
                None,
                self.temp_dir,
                classifier_code_path=code_path_2
            )
            # Should miss because code sha is different
            self.assertIsNone(cached)
        finally:
            os.unlink(code_path_1)
            os.unlink(code_path_2)

    def test_disclose_cache_hit_true(self):
        """Cache hit disclosure adds fields to receipt."""
        receipt = {"other": "field"}
        contamination = {
            "verdict": "CLEAN",
            "cache_write_ts": "2026-07-07T12:00:00+00:00",
            "cached_receipt_path": "/path/to/cache",
            "cache_key_batch_sha256": "abc123",
            "cache_key_receipt_sha256": "def456",
            "cache_key_code_sha256": "ghi789",
        }

        result = disclose_cache_hit(contamination, receipt)
        self.assertTrue(result["cache_hit"])
        self.assertEqual(result["cache_hit_path"], "/path/to/cache")
        self.assertIn("cache_hit_ts", result)
        self.assertEqual(result["cache_key_batch_sha256"], "abc123")

    def test_disclose_cache_hit_false(self):
        """Fresh recheck disclosure marks cache_hit as False."""
        receipt = {"other": "field"}
        contamination = {
            "verdict": "CLEAN",
            # No cache_write_ts = fresh recheck
        }

        result = disclose_cache_hit(contamination, receipt)
        self.assertFalse(result["cache_hit"])


class TestRecheckCacheIntegration(unittest.TestCase):
    """Integration tests with mocked contamination_recheck."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.eval_rows = [[1, 2, 3, 4, 5, 6, 7, 8, 9, 10]]

        # Create dummy code file
        self.code_file = os.path.join(self.temp_dir, "w1_collapse_control_run.py")
        with open(self.code_file, 'w') as f:
            f.write('# test code')

        # Create a stable cache root (not per-launch out_dir)
        self.cache_root = os.path.join(self.temp_dir, "stable-cache")

    def test_cache_skip_integration(self):
        """Integration test: cache hit skips recheck (test case 3)."""
        mock_result = {
            "verdict": "CLEAN",
            "method": "test",
            "confirmed_matches": [],
        }

        # Pre-populate cache
        write_recheck_cache(mock_result, self.eval_rows, None, self.cache_root, self.code_file)

        # Now simulate the runner's cache check
        cached = check_recheck_cache(
            self.eval_rows,
            "/fake/shard/dir",
            None,
            self.cache_root,
            classifier_code_path=self.code_file
        )

        # Should return cached result
        self.assertIsNotNone(cached)
        self.assertEqual(cached["verdict"], "CLEAN")

        # Verify cache disclosure fields are present
        self.assertIn("cache_write_ts", cached)
        self.assertIn("cache_key_batch_sha256", cached)

    def test_cross_launch_cache_hit(self):
        """Cross-launch cache hit: different out_dirs, same stable cache_root (test case 3a).

        This test verifies the core requirement: attempts 2/3/4 in #351 should hit
        the cache written by attempt 1 despite having different timestamped out_dirs.
        """
        mock_result = {
            "verdict": "CLEAN",
            "method": "test",
            "confirmed_matches": [],
        }

        # Simulate first launch: write cache with stable cache_root
        write_recheck_cache(mock_result, self.eval_rows, None, self.cache_root, self.code_file)

        # Simulate second launch: check cache with SAME stable cache_root.
        # In real runner, out_dir would be different (w1-live-<ts1> vs w1-live-<ts2>),
        # but cache_root is STABLE and shared across launches.
        cached = check_recheck_cache(
            self.eval_rows,
            "/fake/shard/dir",
            None,
            self.cache_root,
            classifier_code_path=self.code_file
        )

        # Cross-launch hit! Same batch/code/receipt triple → cache hit despite different out_dirs.
        self.assertIsNotNone(cached)
        self.assertEqual(cached["verdict"], "CLEAN")
        self.assertIn("cache_write_ts", cached)
        # Verify the cache disclosure carries the timestamp
        self.assertTrue(cached.get("cache_write_ts"))


if __name__ == "__main__":
    unittest.main()
