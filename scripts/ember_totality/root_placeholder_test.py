#!/usr/bin/env python3
"""Unit tests for issue #544: root path sanitization in receipts.

Tests the sanitize_receipt_paths function to ensure all forms of the run-root
path (raw, JSON-escaped, doubly-escaped) are replaced with <ROOT>.
"""

import json
import os
import sys
import unittest

# Add repo root to path
HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, REPO_ROOT)

from scripts.ember_totality.ember_totality_spec import sanitize_receipt_paths


class TestRootPlaceholderSanitization(unittest.TestCase):
    """Test root path replacement in receipt payloads."""

    def setUp(self):
        """Set up synthetic root path (never a real worktree path)."""
        # Use a synthetic path that mimics the pattern but is clearly artificial
        self.synthetic_root = r"Z:\synthetic\run-tree"
        self.synthetic_root_forward = self.synthetic_root.replace("\\", "/")

    def test_raw_path_in_reason(self):
        """Test raw path replacement in reason string."""
        receipt = {
            "rows": [
                {
                    "condition": "C1",
                    "status": "GREEN",
                    "reason": f"Probe ran successfully from {self.synthetic_root}",
                }
            ],
        }

        sanitized = sanitize_receipt_paths(receipt, self.synthetic_root)

        self.assertIn("<ROOT>", sanitized["rows"][0]["reason"])
        self.assertNotIn(self.synthetic_root, sanitized["rows"][0]["reason"])

    def test_single_escaped_path(self):
        """Test single-escaped path replacement (JSON string escaping)."""
        # Single-escaped form: one backslash becomes two
        escaped_once = self.synthetic_root.replace("\\", "\\\\")
        receipt = {
            "rows": [
                {
                    "condition": "C1",
                    "reason": f"Path was {escaped_once} in the output",
                }
            ],
        }

        sanitized = sanitize_receipt_paths(receipt, self.synthetic_root)

        self.assertIn("<ROOT>", sanitized["rows"][0]["reason"])
        self.assertNotIn(escaped_once, sanitized["rows"][0]["reason"])

    def test_double_escaped_path(self):
        """Test double-escaped path replacement (nested JSON strings)."""
        # Double-escaped form: one backslash becomes four
        escaped_twice = self.synthetic_root.replace("\\", "\\\\\\\\")
        receipt = {
            "rows": [
                {
                    "condition": "C1",
                    "reason": f"Nested JSON had {escaped_twice} embedded",
                }
            ],
        }

        sanitized = sanitize_receipt_paths(receipt, self.synthetic_root)

        self.assertIn("<ROOT>", sanitized["rows"][0]["reason"])
        self.assertNotIn(escaped_twice, sanitized["rows"][0]["reason"])

    def test_forward_slash_variant(self):
        """Test forward-slash path variant replacement."""
        receipt = {
            "rows": [
                {
                    "condition": "C1",
                    "reason": f"Path was {self.synthetic_root_forward} in logs",
                }
            ],
        }

        sanitized = sanitize_receipt_paths(receipt, self.synthetic_root)

        self.assertIn("<ROOT>", sanitized["rows"][0]["reason"])
        self.assertNotIn(self.synthetic_root_forward, sanitized["rows"][0]["reason"])

    def test_nested_dict_and_list(self):
        """Test sanitization of nested dicts and lists."""
        receipt = {
            "metadata": {
                "path": self.synthetic_root,
                "nested": {
                    "reason": f"Ran from {self.synthetic_root}",
                    "paths": [
                        f"{self.synthetic_root}/subdir1",
                        f"{self.synthetic_root}/subdir2",
                    ],
                },
            },
            "rows": [
                {
                    "reason": f"Started at {self.synthetic_root}",
                    "details": [f"Sub-path: {self.synthetic_root}/file.txt"],
                }
            ],
        }

        sanitized = sanitize_receipt_paths(receipt, self.synthetic_root)

        # Check that all string values containing the root are replaced
        def check_no_raw_root(obj):
            """Recursively check that no raw root paths remain."""
            if isinstance(obj, str):
                self.assertNotIn(self.synthetic_root, obj)
            elif isinstance(obj, dict):
                for v in obj.values():
                    check_no_raw_root(v)
            elif isinstance(obj, (list, tuple)):
                for v in obj:
                    check_no_raw_root(v)

        check_no_raw_root(sanitized)

    def test_numeric_and_bool_unchanged(self):
        """Test that numeric values and booleans are left unchanged."""
        receipt = {
            "count": 42,
            "percentage": 3.14159,
            "is_complete": True,
            "is_failed": False,
            "nothing": None,
            "reason": f"Found {self.synthetic_root}",
        }

        sanitized = sanitize_receipt_paths(receipt, self.synthetic_root)

        self.assertEqual(sanitized["count"], 42)
        self.assertEqual(sanitized["percentage"], 3.14159)
        self.assertTrue(sanitized["is_complete"])
        self.assertFalse(sanitized["is_failed"])
        self.assertIsNone(sanitized["nothing"])
        self.assertIn("<ROOT>", sanitized["reason"])

    def test_multiple_occurrences_in_single_string(self):
        """Test replacement of multiple occurrences in a single string."""
        receipt = {
            "reason": (
                f"Started at {self.synthetic_root}, "
                f"then moved to {self.synthetic_root}/subdir, "
                f"and finally ended at {self.synthetic_root}/result"
            ),
        }

        sanitized = sanitize_receipt_paths(receipt, self.synthetic_root)

        # Should have 3 <ROOT> occurrences
        self.assertEqual(sanitized["reason"].count("<ROOT>"), 3)
        self.assertNotIn(self.synthetic_root, sanitized["reason"])

    def test_empty_receipt(self):
        """Test that empty receipt is handled correctly."""
        receipt = {}
        sanitized = sanitize_receipt_paths(receipt, self.synthetic_root)
        self.assertEqual(sanitized, {})

    def test_none_root(self):
        """Test that None root returns receipt unchanged."""
        receipt = {
            "reason": f"Path at {self.synthetic_root}",
        }

        sanitized = sanitize_receipt_paths(receipt, None)

        # Receipt should be unchanged when root is None
        self.assertEqual(sanitized, receipt)

    def test_all_escaped_forms_together(self):
        """Test a realistic receipt with all escaped forms mixed."""
        escaped_once = self.synthetic_root.replace("\\", "\\\\")
        escaped_twice = self.synthetic_root.replace("\\", "\\\\\\\\")

        receipt = {
            "rows": [
                {
                    "condition": "C1",
                    "reason": (
                        f"Raw: {self.synthetic_root}; "
                        f"Single-escaped: {escaped_once}; "
                        f"Double-escaped: {escaped_twice}"
                    ),
                }
            ],
        }

        sanitized = sanitize_receipt_paths(receipt, self.synthetic_root)

        reason = sanitized["rows"][0]["reason"]
        # Should have 3 <ROOT> occurrences
        self.assertEqual(reason.count("<ROOT>"), 3)
        # Should have no raw root forms
        self.assertNotIn(self.synthetic_root, reason)
        self.assertNotIn(escaped_once, reason)
        self.assertNotIn(escaped_twice, reason)

    def test_whitespace_preserved(self):
        """Test that whitespace around replaced paths is preserved."""
        receipt = {
            "reason": f"  {self.synthetic_root}  \n\t{self.synthetic_root}  ",
        }

        sanitized = sanitize_receipt_paths(receipt, self.synthetic_root)

        # Whitespace should be preserved
        self.assertIn("  <ROOT>  \n\t<ROOT>  ", sanitized["reason"])


class TestSanitizationWithJSONRoundtrip(unittest.TestCase):
    """Test that sanitized receipts survive JSON serialization/deserialization."""

    def setUp(self):
        self.synthetic_root = r"Z:\synthetic\run-tree"

    def test_json_roundtrip_no_corruption(self):
        """Test that JSON roundtrip doesn't corrupt sanitized content."""
        receipt = {
            "condition": "C1",
            "reason": f"Probe ran at {self.synthetic_root}",
            "nested": {
                "detail": f"File at {self.synthetic_root}/output.json",
            },
        }

        sanitized = sanitize_receipt_paths(receipt, self.synthetic_root)

        # Serialize and deserialize
        json_str = json.dumps(sanitized)
        restored = json.loads(json_str)

        # Should be identical
        self.assertEqual(sanitized, restored)
        # And should contain no raw root
        self.assertNotIn(self.synthetic_root, json_str)


if __name__ == "__main__":
    unittest.main()
