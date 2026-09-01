#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
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

# issue2015 exact-local-import:src/ember/governance/scripts/ember_totality/ember_totality_spec.py
import importlib.util as _ember_a8376424dcb1abdf_importlib
import sys as _ember_a8376424dcb1abdf_sys
from pathlib import Path as _ember_a8376424dcb1abdf_Path
_ember_a8376424dcb1abdf_path = _ember_a8376424dcb1abdf_Path(__file__).resolve().parents[2].joinpath('src', 'ember', 'governance', 'scripts', 'ember_totality', 'ember_totality_spec.py')
if not _ember_a8376424dcb1abdf_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/ember_totality/ember_totality_spec.py')
_ember_a8376424dcb1abdf_aliases = ('_ember_issue2015_a8376424dcb1abdf', 'ember_totality_spec', 'scripts.ember_totality.ember_totality_spec')
_ember_a8376424dcb1abdf_existing = []
for _ember_a8376424dcb1abdf_alias in _ember_a8376424dcb1abdf_aliases:
    _ember_a8376424dcb1abdf_candidate = _ember_a8376424dcb1abdf_sys.modules.get(_ember_a8376424dcb1abdf_alias)
    if _ember_a8376424dcb1abdf_candidate is not None and all(_ember_a8376424dcb1abdf_candidate is not item for item in _ember_a8376424dcb1abdf_existing):
        _ember_a8376424dcb1abdf_existing.append(_ember_a8376424dcb1abdf_candidate)
if len(_ember_a8376424dcb1abdf_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/ember_totality/ember_totality_spec.py')
if _ember_a8376424dcb1abdf_existing:
    _ember_a8376424dcb1abdf_module = _ember_a8376424dcb1abdf_existing[0]
    _ember_a8376424dcb1abdf_observed = getattr(_ember_a8376424dcb1abdf_module, '__file__', None)
    if _ember_a8376424dcb1abdf_observed is None or _ember_a8376424dcb1abdf_Path(_ember_a8376424dcb1abdf_observed).resolve() != _ember_a8376424dcb1abdf_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/ember_totality/ember_totality_spec.py')
else:
    _ember_a8376424dcb1abdf_spec = _ember_a8376424dcb1abdf_importlib.spec_from_file_location('_ember_issue2015_a8376424dcb1abdf', _ember_a8376424dcb1abdf_path)
    if _ember_a8376424dcb1abdf_spec is None or _ember_a8376424dcb1abdf_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/ember_totality/ember_totality_spec.py')
    _ember_a8376424dcb1abdf_module = _ember_a8376424dcb1abdf_importlib.module_from_spec(_ember_a8376424dcb1abdf_spec)
    for _ember_a8376424dcb1abdf_alias in _ember_a8376424dcb1abdf_aliases:
        _ember_a8376424dcb1abdf_prior = _ember_a8376424dcb1abdf_sys.modules.get(_ember_a8376424dcb1abdf_alias)
        if _ember_a8376424dcb1abdf_prior is not None and _ember_a8376424dcb1abdf_prior is not _ember_a8376424dcb1abdf_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/ember_totality/ember_totality_spec.py')
        _ember_a8376424dcb1abdf_sys.modules[_ember_a8376424dcb1abdf_alias] = _ember_a8376424dcb1abdf_module
    try:
        _ember_a8376424dcb1abdf_spec.loader.exec_module(_ember_a8376424dcb1abdf_module)
    except BaseException:
        for _ember_a8376424dcb1abdf_alias in _ember_a8376424dcb1abdf_aliases:
            if _ember_a8376424dcb1abdf_sys.modules.get(_ember_a8376424dcb1abdf_alias) is _ember_a8376424dcb1abdf_module:
                _ember_a8376424dcb1abdf_sys.modules.pop(_ember_a8376424dcb1abdf_alias, None)
        raise
for _ember_a8376424dcb1abdf_alias in _ember_a8376424dcb1abdf_aliases:
    _ember_a8376424dcb1abdf_prior = _ember_a8376424dcb1abdf_sys.modules.get(_ember_a8376424dcb1abdf_alias)
    if _ember_a8376424dcb1abdf_prior is not None and _ember_a8376424dcb1abdf_prior is not _ember_a8376424dcb1abdf_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/ember_totality/ember_totality_spec.py')
    _ember_a8376424dcb1abdf_sys.modules[_ember_a8376424dcb1abdf_alias] = _ember_a8376424dcb1abdf_module
sanitize_receipt_paths = getattr(_ember_a8376424dcb1abdf_module, 'sanitize_receipt_paths')
# issue2015 exact-local-import-end:src/ember/governance/scripts/ember_totality/ember_totality_spec.py


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
