#!/usr/bin/env python3
"""test_r0_claim_machinery_v2.py -- Fixed TDD selftests for R0 claim machinery.

Tests the window minter and claim executor with 4 sandbox fixtures:
1. 5 PASS windows -> claim succeeds, probe GREEN
2. 4 PASS + 1 FAIL -> no claim possible (executor should refuse invalid window sequence)
3. Fabricated window ref -> executor refuses (probe RED)
4. Rollback case (probe non-GREEN -> state restored)
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def create_sandbox_repo() -> str:
    """Create a temporary sandbox repo for testing."""
    sandbox = tempfile.mkdtemp(prefix="r0_test_v2_")
    os.makedirs(os.path.join(sandbox, "receipts", "autonomy-ladder"), exist_ok=True)
    os.makedirs(os.path.join(sandbox, "docs", "spec"), exist_ok=True)
    os.makedirs(os.path.join(sandbox, "scripts", "ember_totality"), exist_ok=True)
    return sandbox


def create_smart_test_c_auto(sandbox: str):
    """Create test_c_auto that actually validates window receipt references."""
    probe_script = os.path.join(sandbox, "scripts", "ember_totality", "test_c_auto.py")

    script_content = '''#!/usr/bin/env python3
import json
import os
import sys

repo_root = os.environ.get("EMBER_TOTALITY_ROOT", os.getcwd())
state_path = os.path.join(repo_root, "autonomy-ladder-state.json")

if not os.path.isfile(state_path):
    print("RED C-AUTO: state file absent")
    sys.exit(0)

try:
    with open(state_path, "r") as fh:
        state = json.load(fh)
except:
    print("RED C-AUTO: state unparseable")
    sys.exit(0)

claimed_rungs = {r: d for r, d in state.get("rungs", {}).items() if d.get("claimed")}

if not claimed_rungs:
    print("GREEN C-AUTO: no rung claimed (honest)")
    sys.exit(0)

# Validate claimed rungs
offenders = []
receipts_dir = os.path.join(repo_root, "receipts", "autonomy-ladder")

for rung, rung_data in claimed_rungs.items():
    windows = rung_data.get("windows", [])

    # Check K>=5
    if len(windows) < 5:
        offenders.append(f"only {len(windows)} windows for {rung}")
        continue

    # Check each window receipt exists
    for window_ref in windows:
        receipt_path = os.path.join(receipts_dir, window_ref)
        if not os.path.isfile(receipt_path):
            offenders.append(f"window {window_ref} does not resolve")
            continue

        # Check it's valid JSON
        try:
            with open(receipt_path) as f:
                wr = json.load(f)
            if wr.get("verdict") != "PASS":
                offenders.append(f"window {window_ref} is not PASS")
        except:
            offenders.append(f"window {window_ref} unparseable")

if offenders:
    print(f"RED C-AUTO: {len(offenders)} issues - {offenders[:2]}")
    sys.exit(0)

print("GREEN C-AUTO: ladder state validated")
sys.exit(0)
'''

    with open(probe_script, "w", encoding="utf-8") as fh:
        fh.write(script_content)
    os.chmod(probe_script, 0o755)


def write_dummy_contract(sandbox: str):
    """Write a dummy autonomy relinquishment ladder contract."""
    contract_path = os.path.join(sandbox, "docs", "spec", "autonomy-relinquishment-ladder-v1.md")
    with open(contract_path, "w", encoding="utf-8") as fh:
        fh.write("# Autonomy Relinquishment Ladder v1\n\nTest contract.\n")


def write_window_receipt(sandbox: str, window_num: int, verdict: str = "PASS") -> str:
    """Write a window receipt."""
    receipt_dir = os.path.join(sandbox, "receipts", "autonomy-ladder")
    ts = datetime.now(timezone.utc).isoformat()
    ts_simple = ts.replace("T", "T").replace("+00:00", "Z").replace(":", "").split("Z")[0] + "Z"

    filename = f"R0-window-{window_num}-{ts_simple}.json"
    receipt_path = os.path.join(receipt_dir, filename)

    receipt = {
        "ts": ts,
        "window_number": window_num,
        "rows_checked": 10,
        "matched_rows": 10 if verdict == "PASS" else 8,
        "unmatched_rows": 0 if verdict == "PASS" else 2,
        "verdict": verdict,
        "r0_provenance_binding": {
            "source_registry": "receipts/",
            "window_span": f"window-{window_num}",
            "shas": []
        }
    }

    with open(receipt_path, "w", encoding="utf-8") as fh:
        json.dump(receipt, fh, indent=2)
        fh.write("\n")

    return filename


def write_selftest_receipt(sandbox: str, test_name: str, passed: bool, details: dict[str, Any]):
    """Write a selftest receipt."""
    receipt_dir = os.path.join(sandbox, "receipts")
    os.makedirs(receipt_dir, exist_ok=True)

    ts = datetime.now(timezone.utc).isoformat()
    ts_simple = ts.replace("T", "T").replace("+00:00", "Z").replace(":", "").split("Z")[0] + "Z"

    filename = f"r0-machinery-test-{test_name}-{ts_simple}.json"
    receipt_path = os.path.join(receipt_dir, filename)

    receipt = {
        "ts": ts,
        "test_name": test_name,
        "status": "PASS" if passed else "FAIL",
        "details": details,
        "api_spend_usd": 0.0,
        "paid_api_surface_used": False
    }

    with open(receipt_path, "w", encoding="utf-8") as fh:
        json.dump(receipt, fh, indent=2)
        fh.write("\n")

    return receipt_path


def test_5_pass_windows(sandbox: str) -> tuple[bool, str]:
    """Test 1: 5 PASS windows -> claim succeeds, probe GREEN."""
    print("\n=== TEST 1: 5 PASS windows -> claim succeeds ===")

    # Create 5 PASS window receipts
    window_refs = []
    for i in range(1, 6):
        ref = write_window_receipt(sandbox, i, "PASS")
        window_refs.append(ref)
        print(f"  Created window {i}: {ref}")

    # Execute claim with these windows
    from r0_claim_executor import execute_claim

    success, result = execute_claim(sandbox, window_refs)
    test_passed = success and result.get("success")

    details = {
        "windows": window_refs,
        "claim_success": success,
        "result": result
    }

    receipt_path = write_selftest_receipt(sandbox, "5pass", test_passed, details)
    print(f"  Result: {'PASS' if test_passed else 'FAIL'}")

    return test_passed, receipt_path


def test_4pass_1fail(sandbox: str) -> tuple[bool, str]:
    """Test 2: 4 PASS + 1 FAIL -> claim should fail on RED probe."""
    print("\n=== TEST 2: 4 PASS + 1 FAIL -> claim fails ===")

    # Create 4 PASS + 1 FAIL window receipts
    window_refs = []
    for i in range(1, 5):
        ref = write_window_receipt(sandbox, i, "PASS")
        window_refs.append(ref)
        print(f"  Created window {i} (PASS): {ref}")

    fail_ref = write_window_receipt(sandbox, 5, "FAIL")
    window_refs.append(fail_ref)
    print(f"  Created window 5 (FAIL): {fail_ref}")

    # Claim should fail because test_c_auto sees a FAIL window
    from r0_claim_executor import execute_claim

    success, result = execute_claim(sandbox, window_refs)
    # We expect success=False because the probe should RED on the FAIL window
    test_passed = not success and "RED" in result.get("probe_output", "")

    details = {
        "windows": window_refs,
        "claim_attempt_succeeded": success,
        "probe_output": result.get("probe_output"),
        "expected": "claim should fail due to FAIL window"
    }

    receipt_path = write_selftest_receipt(sandbox, "4pass1fail", test_passed, details)
    print(f"  Result: {'PASS (claim failed as expected)' if test_passed else 'FAIL'}")

    return test_passed, receipt_path


def test_fabricated_window_ref(sandbox: str) -> tuple[bool, str]:
    """Test 3: Fabricated window ref -> executor refuses (probe RED)."""
    print("\n=== TEST 3: Fabricated window ref -> executor refuses ===")

    # Create 4 real PASS windows
    window_refs = []
    for i in range(1, 5):
        ref = write_window_receipt(sandbox, i, "PASS")
        window_refs.append(ref)
        print(f"  Created window {i}: {ref}")

    # Add a fabricated window ref
    window_refs.append("R0-window-99-20260705T999999Z.json")
    print(f"  Added fabricated window: R0-window-99-20260705T999999Z.json")

    # Claim should fail because test_c_auto can't resolve the fabricated ref
    from r0_claim_executor import execute_claim

    success, result = execute_claim(sandbox, window_refs)
    test_passed = not success and ("does not resolve" in str(result.get("probe_output", "")) or "RED" in str(result))

    details = {
        "windows": window_refs,
        "claim_attempt_succeeded": success,
        "executor_refused": not success,
        "result": result
    }

    receipt_path = write_selftest_receipt(sandbox, "fabricated", test_passed, details)
    print(f"  Result: {'PASS (executor refused)' if test_passed else 'FAIL'}")

    return test_passed, receipt_path


def test_rollback_on_probe_red(sandbox: str) -> tuple[bool, str]:
    """Test 4: Rollback case - probe RED -> state restored."""
    print("\n=== TEST 4: Rollback case - probe RED -> state restored ===")

    # Create 5 PASS window receipts
    window_refs = []
    for i in range(1, 6):
        ref = write_window_receipt(sandbox, i, "PASS")
        window_refs.append(ref)
    print(f"  Created 5 PASS windows")

    # Create a probe that returns RED
    probe_script = os.path.join(sandbox, "scripts", "ember_totality", "test_c_auto.py")
    red_probe_content = '''#!/usr/bin/env python3
print("RED C-AUTO: test fixture validation failed")
'''

    with open(probe_script, "w", encoding="utf-8") as fh:
        fh.write(red_probe_content)
    os.chmod(probe_script, 0o755)

    # Backup current state
    state_path = os.path.join(sandbox, "autonomy-ladder-state.json")
    initial_state = None
    if os.path.isfile(state_path):
        with open(state_path, "r") as fh:
            initial_state = json.load(fh)

    # Try to execute claim with RED probe
    from r0_claim_executor import execute_claim

    success, result = execute_claim(sandbox, window_refs)

    # Claim should have failed due to RED probe
    claim_failed = not success

    # Check if state was rolled back to initial
    if os.path.isfile(state_path):
        with open(state_path, "r") as fh:
            final_state = json.load(fh)
        state_rolled_back = final_state == initial_state or initial_state is None
    else:
        state_rolled_back = initial_state is None

    test_passed = claim_failed and state_rolled_back

    details = {
        "windows": window_refs,
        "probe_returned_red": True,
        "claim_failed_as_expected": claim_failed,
        "state_rolled_back": state_rolled_back
    }

    receipt_path = write_selftest_receipt(sandbox, "rollback", test_passed, details)
    print(f"  Result: {'PASS (claim failed & state rolled back)' if test_passed else 'FAIL'}")

    return test_passed, receipt_path


def test_probe_absent(sandbox: str) -> tuple[bool, str]:
    """Test 5: Probe-absent scenario - executor refuses (fail-CLOSED)."""
    print("\n=== TEST 5: Probe-absent -> executor refuses (fail-CLOSED) ===")

    # Create 5 real PASS windows
    window_refs = []
    for i in range(1, 6):
        ref = write_window_receipt(sandbox, i, "PASS")
        window_refs.append(ref)
    print(f"  Created 5 PASS windows")

    # Remove the probe (simulate probe not available at runtime)
    probe_dir = os.path.join(sandbox, "scripts", "ember_totality")
    probe_script = os.path.join(probe_dir, "test_c_auto.py")
    if os.path.isfile(probe_script):
        os.remove(probe_script)
    print(f"  Removed probe: test_c_auto.py")

    # Try to execute claim without probe
    from r0_claim_executor import execute_claim

    success, result = execute_claim(sandbox, window_refs)

    # Claim should fail because probe is unavailable (fail-CLOSED)
    test_passed = not success and "probe not found" in result.get("probe_output", "").lower()

    details = {
        "windows": window_refs,
        "probe_available": False,
        "claim_attempt_succeeded": success,
        "probe_output": result.get("probe_output"),
        "expected": "claim should fail (refuse) because probe unavailable"
    }

    receipt_path = write_selftest_receipt(sandbox, "probe_absent", test_passed, details)
    print(f"  Result: {'PASS (executor refused without probe)' if test_passed else 'FAIL'}")

    return test_passed, receipt_path


def run_all_tests() -> tuple[bool, list[str]]:
    """Run all 5 selftests."""
    print("=" * 70)
    print("R0 CLAIM MACHINERY SELFTESTS v2")
    print("=" * 70)

    sandbox = create_sandbox_repo()
    print(f"Sandbox: {sandbox}")

    # Create required fixtures
    create_smart_test_c_auto(sandbox)
    write_dummy_contract(sandbox)

    results = []
    tests = [
        ("Test 1: 5 PASS windows", lambda: test_5_pass_windows(sandbox)),
        ("Test 2: 4 PASS + 1 FAIL", lambda: test_4pass_1fail(sandbox)),
        ("Test 3: Fabricated window ref", lambda: test_fabricated_window_ref(sandbox)),
        ("Test 4: Rollback on RED probe", lambda: test_rollback_on_probe_red(sandbox)),
        ("Test 5: Probe-absent (fail-CLOSED)", lambda: test_probe_absent(sandbox)),
    ]

    all_passed = True
    for test_name, test_fn in tests:
        try:
            passed, receipt_path = test_fn()
            results.append(f"{test_name}: {'PASS' if passed else 'FAIL'}")
            if not passed:
                all_passed = False
        except Exception as e:
            results.append(f"{test_name}: FAIL - {str(e)}")
            all_passed = False

    print("\n" + "=" * 70)
    print("TEST SUMMARY (5 tests):")
    for result in results:
        print(f"  {result}")
    print("=" * 70)
    print(f"Overall: {'ALL PASS' if all_passed else 'SOME FAILED'}")

    return all_passed, results


if __name__ == "__main__":
    import sys
    script_dir = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, script_dir)

    all_passed, results = run_all_tests()
    sys.exit(0 if all_passed else 1)
