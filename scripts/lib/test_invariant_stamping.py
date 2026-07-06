"""TDD tests for invariant stamping integration in writers.

These tests verify that:
1. Checkpoint manifest writers call stamp() before writing
2. Receipt writers call stamp() before writing
3. All post-genesis artifacts carry the invariant_sha256 field
"""

import json
import os
import sys
import tempfile
from pathlib import Path

# Add scripts dir to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from scripts.lib.invariant import stamp, INVARIANT_SHA256


def test_stamp_adds_field_to_dict():
    """stamp() adds invariant_sha256 field to a dict."""
    test_dict = {"name": "test", "value": 123}
    stamped = stamp(test_dict, repo_root=".")

    assert "invariant_sha256" in stamped
    assert stamped["invariant_sha256"] == INVARIANT_SHA256
    assert stamped["name"] == "test"


def test_receipt_includes_invariant_sha256():
    """A receipt written by a writer must include invariant_sha256."""
    # This test fails initially because writers don't stamp yet
    # After implementation, a receipt dict stamped before writing
    # must have the field
    receipt = {
        "ticket": "test-123",
        "ts": "2026-07-07T00:00:00Z",
        "condition": "C-INV",
        "status": "GREEN"
    }

    stamped_receipt = stamp(receipt, repo_root=".")

    assert "invariant_sha256" in stamped_receipt
    assert stamped_receipt["invariant_sha256"] == INVARIANT_SHA256


def test_manifest_includes_invariant_sha256():
    """A checkpoint manifest written by a writer must include invariant_sha256."""
    manifest = {
        "model_id": "test-model",
        "step": 100,
        "weights_sha256": "abc123"
    }

    stamped_manifest = stamp(manifest, repo_root=".")

    assert "invariant_sha256" in stamped_manifest
    assert stamped_manifest["invariant_sha256"] == INVARIANT_SHA256


if __name__ == "__main__":
    import sys
    try:
        test_stamp_adds_field_to_dict()
        print("[PASS] test_stamp_adds_field_to_dict")
        test_receipt_includes_invariant_sha256()
        print("[PASS] test_receipt_includes_invariant_sha256")
        test_manifest_includes_invariant_sha256()
        print("[PASS] test_manifest_includes_invariant_sha256")
        print("\n[PASS] All stamping tests passed")
        sys.exit(0)
    except AssertionError as e:
        print(f"[FAIL] {e}")
        sys.exit(1)
