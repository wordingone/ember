#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""test_c_pin.py — Pin-freshness probe (issue #96).

Asserts that the exec-tree docs/domains/governance/authority/GOAL.md AUTHORITY header's pinned contract-sha
matches the contract tree's docs/domains/governance/authority/GOAL.md sha256 on disk.

Test scenarios:
1. Parse AUTHORITY comment: strict regex, fail RED on parse failure
2. Match check: GREEN iff shas equal, RED with both values named
3. Fixture pairs: stale pin → RED; matched pin → GREEN

Receipt fields: pinned_sha, actual_sha, exec_goal_path, verdict
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Optional, Tuple


def parse_authority_comment(goal_path: Path) -> Optional[str]:
    """Parse AUTHORITY comment in docs/domains/governance/authority/GOAL.md for pinned contract-sha.

    Expected format (regex):
        <!-- AUTHORITY: contract-sha256=<64-char hex> -->

    Args:
        goal_path: Path to docs/domains/governance/authority/GOAL.md file

    Returns:
        Pinned sha256 hex string, or None if parse fails

    Raises:
        ValueError: If AUTHORITY comment exists but is malformed
    """
    if not goal_path.exists():
        raise FileNotFoundError(f"docs/domains/governance/authority/GOAL.md not found: {goal_path}")

    content = goal_path.read_text(encoding='utf-8')

    # Strict regex: AUTHORITY comment with contract-sha256
    pattern = r'<!--\s*AUTHORITY:\s*contract-sha256=([a-f0-9]{64})\s*-->'
    match = re.search(pattern, content, re.IGNORECASE | re.MULTILINE)

    if match:
        return match.group(1).lower()

    # Check if AUTHORITY comment exists but is malformed
    if 'AUTHORITY' in content and 'contract-sha256' in content:
        raise ValueError(
            f"AUTHORITY comment found but malformed (not strict hex): {goal_path}"
        )

    # No AUTHORITY comment found
    return None


def compute_sha256(file_path: Path) -> str:
    """Compute sha256 hash of file.

    Args:
        file_path: Path to file

    Returns:
        Lowercase hex string of sha256
    """
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    sha = hashlib.sha256()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(4096), b''):
            sha.update(chunk)

    return sha.hexdigest().lower()


def probe_pin_freshness(
    exec_goal_path: Path,
    contract_goal_path: Path
) -> Tuple[bool, dict]:
    """Run pin-freshness probe.

    Args:
        exec_goal_path: Path to execution-tree docs/domains/governance/authority/GOAL.md
        contract_goal_path: Path to contract-tree docs/domains/governance/authority/GOAL.md

    Returns:
        (verdict: bool, receipt: dict)
        verdict=True means GREEN (shas match)
        verdict=False means RED (shas mismatch or parse error)
    """
    receipt = {
        "pinned_sha": None,
        "actual_sha": None,
        "exec_goal_path": str(exec_goal_path),
        "contract_goal_path": str(contract_goal_path),
        "verdict": False,
        "error": None,
    }

    try:
        # Step 1: Parse AUTHORITY comment from exec tree
        pinned_sha = parse_authority_comment(exec_goal_path)

        if pinned_sha is None:
            receipt["error"] = "No AUTHORITY comment with contract-sha256 found"
            return False, receipt

        receipt["pinned_sha"] = pinned_sha

        # Step 2: Compute actual sha256 of contract tree docs/domains/governance/authority/GOAL.md
        actual_sha = compute_sha256(contract_goal_path)
        receipt["actual_sha"] = actual_sha

        # Step 3: Compare
        if pinned_sha == actual_sha:
            receipt["verdict"] = True
            return True, receipt
        else:
            receipt["error"] = f"Pin mismatch: pinned={pinned_sha} vs actual={actual_sha}"
            return False, receipt

    except (FileNotFoundError, ValueError) as e:
        receipt["error"] = str(e)
        return False, receipt


# ---------------------------------------------------------------------------
# Test fixtures and test cases
# ---------------------------------------------------------------------------

def setup_fixture_stale() -> Tuple[Path, Path]:
    """Create fixture with stale pin (mismatch). Returns (exec_path, contract_path)."""
    fixture_dir = Path(__file__).resolve().parent / "fixtures" / "pin_freshness"
    fixture_dir.mkdir(parents=True, exist_ok=True)

    stale_dir = fixture_dir / "stale"
    stale_dir.mkdir(exist_ok=True)

    # Create a contract docs/domains/governance/authority/GOAL.md with known content
    contract_path = stale_dir / "contract_GOAL.md"
    contract_content = "# Contract Goal\n\nThis is the contract tree docs/domains/governance/authority/GOAL.md.\n"
    contract_path.write_text(contract_content, encoding='utf-8')
    actual_sha = compute_sha256(contract_path)

    # Create exec docs/domains/governance/authority/GOAL.md with STALE pin (different sha)
    exec_path = stale_dir / "exec_GOAL.md"
    stale_sha = "0" * 64  # Obviously stale
    exec_content = (
        f"# Exec Goal\n\n"
        f"<!-- AUTHORITY: contract-sha256={stale_sha} -->\n\n"
        f"Some exec tree content.\n"
    )
    exec_path.write_text(exec_content, encoding='utf-8')

    return exec_path, contract_path


def setup_fixture_matched() -> Tuple[Path, Path]:
    """Create fixture with matched pin. Returns (exec_path, contract_path)."""
    fixture_dir = Path(__file__).resolve().parent / "fixtures" / "pin_freshness"
    fixture_dir.mkdir(parents=True, exist_ok=True)

    matched_dir = fixture_dir / "matched"
    matched_dir.mkdir(exist_ok=True)

    # Create a contract docs/domains/governance/authority/GOAL.md with known content
    contract_path = matched_dir / "contract_GOAL.md"
    contract_content = "# Contract Goal (matched case)\n\nMatched contract content.\n"
    contract_path.write_text(contract_content, encoding='utf-8')
    actual_sha = compute_sha256(contract_path)

    # Create exec docs/domains/governance/authority/GOAL.md with MATCHING pin
    exec_path = matched_dir / "exec_GOAL.md"
    exec_content = (
        f"# Exec Goal\n\n"
        f"<!-- AUTHORITY: contract-sha256={actual_sha} -->\n\n"
        f"Some exec tree content.\n"
    )
    exec_path.write_text(exec_content, encoding='utf-8')

    return exec_path, contract_path


# ---------------------------------------------------------------------------
# Test cases (TDD: RED → GREEN)
# ---------------------------------------------------------------------------

def test_stale_pin_red() -> int:
    """Test: Stale pin fails (RED)."""
    print("\n[TEST] Stale pin -> RED")
    exec_path, contract_path = setup_fixture_stale()

    verdict, receipt = probe_pin_freshness(exec_path, contract_path)

    # Should be RED (False)
    assert verdict is False, f"Expected RED (False), got {verdict}"
    assert receipt["pinned_sha"] is not None, "pinned_sha not captured"
    assert receipt["actual_sha"] is not None, "actual_sha not captured"
    assert receipt["pinned_sha"] != receipt["actual_sha"], "Shas should mismatch"
    assert receipt["error"] is not None, "Error should be recorded"

    print(f"  pinned_sha:  {receipt['pinned_sha']}")
    print(f"  actual_sha:  {receipt['actual_sha']}")
    print(f"  error:       {receipt['error']}")
    print("  [PASS] Stale pin correctly detected as RED")

    return 0


def test_matched_pin_green() -> int:
    """Test: Matched pin succeeds (GREEN)."""
    print("\n[TEST] Matched pin -> GREEN")
    exec_path, contract_path = setup_fixture_matched()

    verdict, receipt = probe_pin_freshness(exec_path, contract_path)

    # Should be GREEN (True)
    assert verdict is True, f"Expected GREEN (True), got {verdict}"
    assert receipt["pinned_sha"] is not None, "pinned_sha not captured"
    assert receipt["actual_sha"] is not None, "actual_sha not captured"
    assert receipt["pinned_sha"] == receipt["actual_sha"], "Shas should match"
    assert receipt["error"] is None, f"Error should be None, got {receipt['error']}"

    print(f"  pinned_sha:  {receipt['pinned_sha']}")
    print(f"  actual_sha:  {receipt['actual_sha']}")
    print(f"  verdict:     GREEN")
    print("  [PASS] Matched pin correctly detected as GREEN")

    return 0


def test_parse_error_red() -> int:
    """Test: Malformed AUTHORITY comment fails RED."""
    print("\n[TEST] Malformed AUTHORITY comment -> RED")
    fixture_dir = Path(__file__).resolve().parent / "fixtures" / "pin_freshness"
    fixture_dir.mkdir(parents=True, exist_ok=True)

    error_dir = fixture_dir / "malformed"
    error_dir.mkdir(exist_ok=True)

    # Create a contract docs/domains/governance/authority/GOAL.md
    contract_path = error_dir / "contract_GOAL.md"
    contract_path.write_text("# Contract\n", encoding='utf-8')

    # Create exec docs/domains/governance/authority/GOAL.md with MALFORMED AUTHORITY (not strict hex)
    exec_path = error_dir / "exec_GOAL.md"
    exec_content = (
        "# Exec Goal\n\n"
        "<!-- AUTHORITY: contract-sha256=not-a-valid-hex -->\n\n"
        "Content.\n"
    )
    exec_path.write_text(exec_content, encoding='utf-8')

    verdict, receipt = probe_pin_freshness(exec_path, contract_path)

    # Should be RED (False) with error
    assert verdict is False, f"Expected RED (False), got {verdict}"
    assert receipt["error"] is not None, "Error should be captured"
    assert "malformed" in receipt["error"].lower(), f"Error should mention malform: {receipt['error']}"

    print(f"  error: {receipt['error']}")
    print("  [PASS] Malformed AUTHORITY correctly detected as RED")

    return 0


def test_missing_authority_red() -> int:
    """Test: Missing AUTHORITY comment fails RED."""
    print("\n[TEST] Missing AUTHORITY comment -> RED")
    fixture_dir = Path(__file__).resolve().parent / "fixtures" / "pin_freshness"
    fixture_dir.mkdir(parents=True, exist_ok=True)

    missing_dir = fixture_dir / "missing"
    missing_dir.mkdir(exist_ok=True)

    # Create a contract docs/domains/governance/authority/GOAL.md
    contract_path = missing_dir / "contract_GOAL.md"
    contract_path.write_text("# Contract\n", encoding='utf-8')

    # Create exec docs/domains/governance/authority/GOAL.md WITHOUT AUTHORITY comment
    exec_path = missing_dir / "exec_GOAL.md"
    exec_path.write_text("# Exec Goal\n\nNo AUTHORITY comment here.\n", encoding='utf-8')

    verdict, receipt = probe_pin_freshness(exec_path, contract_path)

    # Should be RED (False) with "no comment" error
    assert verdict is False, f"Expected RED (False), got {verdict}"
    assert receipt["pinned_sha"] is None, "pinned_sha should be None"
    assert receipt["error"] is not None, "Error should be captured"

    print(f"  error: {receipt['error']}")
    print("  [PASS] Missing AUTHORITY correctly detected as RED")

    return 0


def main() -> int:
    """Run all tests."""
    try:
        print("\n" + "="*70)
        print("PIN-FRESHNESS PROBE TESTS (TDD, issue #96)")
        print("="*70)

        ret = test_stale_pin_red()
        if ret != 0:
            return ret

        ret = test_matched_pin_green()
        if ret != 0:
            return ret

        ret = test_parse_error_red()
        if ret != 0:
            return ret

        ret = test_missing_authority_red()
        if ret != 0:
            return ret

        print("\n" + "="*70)
        print("ALL TESTS PASS [PASS]")
        print("="*70 + "\n")
        return 0

    except Exception as e:
        print(f"\n[FAIL] TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
