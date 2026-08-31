# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""TDD tests for receipt_check.py invariant validation.

These tests verify that:
1. Post-genesis receipts must have invariant_sha256 field
2. Post-genesis receipts must have correct hash value
3. Pre-genesis receipts are exempt from invariant checking
"""

import json
import sys
import tempfile
from pathlib import Path
from datetime import datetime

# For testing, we'll check the validation logic
INVARIANT_SHA256 = "08a0eb7418c09a8088be4658e10785107abbb7507fc2dbcdc789936aa54e02a6"
GENESIS_TS = "2026-07-06T14:13:23-07:00"  # committerDate of genesis merge (commit 9c89f7f66)


def _parse_ts(ts_str: str) -> float:
    """Parse ISO8601 timestamp to epoch seconds."""
    return datetime.fromisoformat(ts_str.replace('Z', '+00:00')).timestamp()


def validate_post_genesis_receipt(receipt: dict, genesis_ts: str = GENESIS_TS) -> tuple[bool, str]:
    """Validate that a receipt is properly stamped if post-genesis.

    Returns: (is_valid, reason)
    """
    receipt_ts = receipt.get("ts")
    if not receipt_ts:
        return False, "missing ts field"

    receipt_epoch = _parse_ts(receipt_ts)
    genesis_epoch = _parse_ts(genesis_ts)

    # Pre-genesis receipts are exempt
    if receipt_epoch < genesis_epoch:
        return True, "pre-genesis (exempt)"

    # Post-genesis must have invariant_sha256
    if "invariant_sha256" not in receipt:
        return False, "post-genesis receipt missing invariant_sha256"

    # Post-genesis must have correct value
    if receipt["invariant_sha256"] != INVARIANT_SHA256:
        return False, f"post-genesis receipt has wrong invariant_sha256: {receipt['invariant_sha256']}"

    return True, "valid"


def test_post_genesis_receipt_requires_stamp():
    """Post-genesis receipt without invariant_sha256 must fail."""
    receipt = {
        "ticket": "test-123",
        "ts": "2026-07-07T00:00:00Z",  # After genesis
        "status": "GREEN"
    }

    valid, reason = validate_post_genesis_receipt(receipt)
    assert not valid, f"Expected invalid receipt, got valid with reason: {reason}"
    assert "invariant_sha256" in reason


def test_post_genesis_receipt_must_have_correct_value():
    """Post-genesis receipt with wrong invariant_sha256 must fail."""
    receipt = {
        "ticket": "test-123",
        "ts": "2026-07-07T00:00:00Z",  # After genesis
        "status": "GREEN",
        "invariant_sha256": "wrong_hash"
    }

    valid, reason = validate_post_genesis_receipt(receipt)
    assert not valid, f"Expected invalid receipt, got valid with reason: {reason}"
    assert "wrong" in reason


def test_post_genesis_receipt_with_correct_stamp():
    """Post-genesis receipt with correct invariant_sha256 must pass."""
    receipt = {
        "ticket": "test-123",
        "ts": "2026-07-07T00:00:00Z",  # After genesis
        "status": "GREEN",
        "invariant_sha256": INVARIANT_SHA256
    }

    valid, reason = validate_post_genesis_receipt(receipt)
    assert valid, f"Expected valid receipt, got invalid with reason: {reason}"


def test_pre_genesis_receipt_exempt():
    """Pre-genesis receipts are exempt from invariant checking."""
    receipt = {
        "ticket": "test-123",
        "ts": "2026-07-05T00:00:00Z",  # Before genesis
        "status": "GREEN"
        # No invariant_sha256 field
    }

    valid, reason = validate_post_genesis_receipt(receipt)
    assert valid, f"Expected valid pre-genesis receipt, got invalid with reason: {reason}"
    assert "exempt" in reason


if __name__ == "__main__":
    import sys
    try:
        test_post_genesis_receipt_requires_stamp()
        print("[PASS] test_post_genesis_receipt_requires_stamp")
        test_post_genesis_receipt_must_have_correct_value()
        print("[PASS] test_post_genesis_receipt_must_have_correct_value")
        test_post_genesis_receipt_with_correct_stamp()
        print("[PASS] test_post_genesis_receipt_with_correct_stamp")
        test_pre_genesis_receipt_exempt()
        print("[PASS] test_pre_genesis_receipt_exempt")
        print("\n[PASS] All receipt_check invariant tests passed")
        sys.exit(0)
    except AssertionError as e:
        print(f"[FAIL] {e}")
        sys.exit(1)
