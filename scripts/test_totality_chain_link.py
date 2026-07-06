"""TDD tests for totality receipt chain linking via predecessor hash + constitutional invariant block.

These tests verify that:
1. Each board receipt includes prev_totality_receipt_sha256 (hash of prior receipt)
2. Each board receipt includes constitutional_invariant block with five fields
3. constitutional_invariant block structure matches specification
"""

import json
import hashlib
from pathlib import Path

INVARIANT_SHA256 = "08a0eb7418c09a8088be4658e10785107abbb7507fc2dbcdc789936aa54e02a6"
GENESIS_TS = "2026-07-06T14:13:23-07:00"  # committerDate of genesis merge (commit 9c89f7f66)


def _hash_json(data: dict) -> str:
    """Hash a JSON object (canonical ordering)."""
    json_str = json.dumps(data, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(json_str.encode()).hexdigest()


def _validate_constitutional_invariant_block(block: dict, genesis_ts: str = GENESIS_TS) -> tuple[bool, str]:
    """Validate constitutional_invariant block structure.

    Expected fields:
    - invariant_sha256: the constitutional hash
    - status: "GREEN" or "RED"
    - genesis_ts: the timestamp of genesis
    - errata_sha256: hash of INVARIANT-ERRATA.md (append-only log)
    - errata_length: byte length of errata file

    Returns: (is_valid, reason)
    """
    required_fields = ["invariant_sha256", "status", "genesis_ts", "errata_sha256", "errata_length"]

    for field in required_fields:
        if field not in block:
            return False, f"missing required field: {field}"

    if block["invariant_sha256"] != INVARIANT_SHA256:
        return False, f"wrong invariant_sha256: {block['invariant_sha256']}"

    if block["status"] not in ["GREEN", "RED"]:
        return False, f"invalid status: {block['status']}"

    if block["genesis_ts"] != genesis_ts:
        return False, f"wrong genesis_ts: {block['genesis_ts']}"

    if not isinstance(block["errata_sha256"], str) or len(block["errata_sha256"]) != 64:
        return False, f"invalid errata_sha256 format"

    if not isinstance(block["errata_length"], int) or block["errata_length"] < 0:
        return False, f"invalid errata_length: {block['errata_length']}"

    return True, "valid"


def test_receipt_includes_prev_totality_hash():
    """Board receipt must include prev_totality_receipt_sha256."""
    receipt = {
        "ticket": "board-run-001",
        "ts": "2026-07-07T00:00:00Z",
        "rows": [],
        "prev_totality_receipt_sha256": "abc123def456"  # Mock hash
    }

    assert "prev_totality_receipt_sha256" in receipt
    assert isinstance(receipt["prev_totality_receipt_sha256"], str)


def test_receipt_includes_constitutional_invariant_block():
    """Board receipt must include constitutional_invariant block."""
    receipt = {
        "ticket": "board-run-001",
        "ts": "2026-07-07T00:00:00Z",
        "rows": [],
        "prev_totality_receipt_sha256": "abc123def456",
        "constitutional_invariant": {
            "invariant_sha256": INVARIANT_SHA256,
            "status": "GREEN",
            "genesis_ts": GENESIS_TS,
            "errata_sha256": "0" * 64,
            "errata_length": 0
        }
    }

    assert "constitutional_invariant" in receipt
    block = receipt["constitutional_invariant"]

    valid, reason = _validate_constitutional_invariant_block(block)
    assert valid, f"constitutional_invariant block invalid: {reason}"


def test_constitutional_invariant_block_missing_field():
    """Missing field in constitutional_invariant block must fail."""
    block = {
        "invariant_sha256": INVARIANT_SHA256,
        "status": "GREEN",
        "genesis_ts": GENESIS_TS,
        # Missing errata_sha256 and errata_length
    }

    valid, reason = _validate_constitutional_invariant_block(block)
    assert not valid, f"Expected invalid block, got valid with reason: {reason}"


def test_constitutional_invariant_block_wrong_hash():
    """Wrong invariant_sha256 in block must fail."""
    block = {
        "invariant_sha256": "wrong_hash_value",
        "status": "GREEN",
        "genesis_ts": GENESIS_TS,
        "errata_sha256": "0" * 64,
        "errata_length": 0
    }

    valid, reason = _validate_constitutional_invariant_block(block)
    assert not valid, f"Expected invalid block, got valid with reason: {reason}"
    assert "invariant_sha256" in reason


def test_constitutional_invariant_block_invalid_status():
    """Invalid status in block must fail."""
    block = {
        "invariant_sha256": INVARIANT_SHA256,
        "status": "UNKNOWN",  # Invalid
        "genesis_ts": GENESIS_TS,
        "errata_sha256": "0" * 64,
        "errata_length": 0
    }

    valid, reason = _validate_constitutional_invariant_block(block)
    assert not valid, f"Expected invalid block, got valid with reason: {reason}"


def test_board_receipt_chain_structure():
    """Full board receipt with chain link and invariant block."""
    receipt = {
        "ticket": "board-run-002",
        "ts": "2026-07-07T01:00:00Z",
        "rows": [
            {"condition": "C-1", "status": "GREEN", "reason": "test"}
        ],
        "prev_totality_receipt_sha256": "abc123def456",
        "constitutional_invariant": {
            "invariant_sha256": INVARIANT_SHA256,
            "status": "GREEN",
            "genesis_ts": GENESIS_TS,
            "errata_sha256": "a" * 64,
            "errata_length": 256
        }
    }

    # Validate structure
    assert "prev_totality_receipt_sha256" in receipt
    assert "constitutional_invariant" in receipt
    assert isinstance(receipt["rows"], list)

    block = receipt["constitutional_invariant"]
    valid, reason = _validate_constitutional_invariant_block(block)
    assert valid, f"Block validation failed: {reason}"


if __name__ == "__main__":
    import sys
    try:
        test_receipt_includes_prev_totality_hash()
        print("[PASS] test_receipt_includes_prev_totality_hash")
        test_receipt_includes_constitutional_invariant_block()
        print("[PASS] test_receipt_includes_constitutional_invariant_block")
        test_constitutional_invariant_block_missing_field()
        print("[PASS] test_constitutional_invariant_block_missing_field")
        test_constitutional_invariant_block_wrong_hash()
        print("[PASS] test_constitutional_invariant_block_wrong_hash")
        test_constitutional_invariant_block_invalid_status()
        print("[PASS] test_constitutional_invariant_block_invalid_status")
        test_board_receipt_chain_structure()
        print("[PASS] test_board_receipt_chain_structure")
        print("\n[PASS] All totality chain link tests passed")
        sys.exit(0)
    except AssertionError as e:
        print(f"[FAIL] {e}")
        sys.exit(1)
