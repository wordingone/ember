#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Selftest for loop_launch_guard precondition checks."""
from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import loop_launch_guard


def test_pass_exists_and_predates() -> bool:
    """Test: PASS exists and predates launch => runs (verdict PASS)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir)
        receipts_dir = repo / "receipts" / "ember-resident-training-gate"
        receipts_dir.mkdir(parents=True)

        # Create a PASS receipt 1 hour before launch
        pass_ts = datetime(2026, 7, 4, 6, 29, 51, tzinfo=timezone.utc)
        pass_receipt = {
            "ticket": "EMBER-RESIDENT-TRAINING-GATE",
            "ts": pass_ts.strftime("%Y%m%dT%H%M%SZ"),
            "verdict": "RESIDENT_TRAINING_GATE_PASS",
        }
        (receipts_dir / "resident-training-gate-20260704T062951Z.json").write_text(
            json.dumps(pass_receipt, indent=2)
        )

        # Launch 1 hour later
        launch_ts = pass_ts + timedelta(hours=1)
        allowed, receipt = loop_launch_guard.check_launch_precondition(repo, launch_ts)

        assert allowed is True, f"Expected allowed=True, got {allowed}"
        assert receipt["verdict"] == "LOOP_LAUNCH_PRECONDITION_PASS", f"Got {receipt['verdict']}"
        assert receipt["pass_ts"] == pass_ts.strftime("%Y%m%dT%H%M%SZ")
        return True


def test_pass_absent() -> bool:
    """Test: PASS absent => refuses naming C14."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir)
        receipts_dir = repo / "receipts" / "ember-resident-training-gate"
        receipts_dir.mkdir(parents=True)

        launch_ts = datetime(2026, 7, 4, 12, 0, 0, tzinfo=timezone.utc)
        allowed, receipt = loop_launch_guard.check_launch_precondition(repo, launch_ts)

        assert allowed is False, f"Expected allowed=False, got {allowed}"
        assert receipt["verdict"] == "LOOP_LAUNCH_PRECONDITION_MISSING"
        assert receipt["named_precondition"] == "C14_RESIDENT_TRAINING_GATE_PASS"
        assert receipt["status"] == "ABSENT"
        return True


def test_pass_postdates_launch() -> bool:
    """Test: PASS postdates launch => refuses quoting both ts."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir)
        receipts_dir = repo / "receipts" / "ember-resident-training-gate"
        receipts_dir.mkdir(parents=True)

        # Create a PASS receipt
        pass_ts = datetime(2026, 7, 4, 12, 0, 0, tzinfo=timezone.utc)
        pass_receipt = {
            "ticket": "EMBER-RESIDENT-TRAINING-GATE",
            "ts": pass_ts.strftime("%Y%m%dT%H%M%SZ"),
            "verdict": "RESIDENT_TRAINING_GATE_PASS",
        }
        (receipts_dir / f"resident-training-gate-{pass_ts.strftime('%Y%m%dT%H%M%SZ')}.json").write_text(
            json.dumps(pass_receipt, indent=2)
        )

        # Launch 1 hour BEFORE the PASS receipt
        launch_ts = pass_ts - timedelta(hours=1)
        allowed, receipt = loop_launch_guard.check_launch_precondition(repo, launch_ts)

        assert allowed is False, f"Expected allowed=False, got {allowed}"
        assert receipt["verdict"] == "LOOP_LAUNCH_PRECONDITION_POSTDATES"
        assert receipt["named_precondition"] == "C14_RESIDENT_TRAINING_GATE_PASS"
        assert receipt["pass_ts"] == pass_ts.strftime("%Y%m%dT%H%M%SZ"), "Pass ts should be quoted"
        assert receipt["launch_ts"] == launch_ts.strftime("%Y%m%dT%H%M%SZ"), "Launch ts should be quoted"
        return True


def test_unparseable_receipt_ts() -> bool:
    """Test: unparseable PASS receipt ts => refuses."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir)
        receipts_dir = repo / "receipts" / "ember-resident-training-gate"
        receipts_dir.mkdir(parents=True)

        # Create a PASS receipt with malformed ts
        pass_receipt = {
            "ticket": "EMBER-RESIDENT-TRAINING-GATE",
            "ts": "not-a-valid-timestamp",
            "verdict": "RESIDENT_TRAINING_GATE_PASS",
        }
        (receipts_dir / "resident-training-gate-bad.json").write_text(
            json.dumps(pass_receipt, indent=2)
        )

        launch_ts = datetime(2026, 7, 4, 12, 0, 0, tzinfo=timezone.utc)
        allowed, receipt = loop_launch_guard.check_launch_precondition(repo, launch_ts)

        try:
            assert allowed is False, f"Expected allowed=False, got {allowed}"
            assert receipt["verdict"] == "LOOP_LAUNCH_PRECONDITION_UNPARSEABLE"
            assert receipt["named_precondition"] == "C14_RESIDENT_TRAINING_GATE_PASS"
            assert receipt["status"] == "UNPARSEABLE_TS"
            return True
        except AssertionError as e:
            print(f"  Receipt was: {json.dumps(receipt, indent=2)}")
            raise e


def test_deliberately_misorder_launch() -> bool:
    """Test: deliberately mis-ordered launch attempt produces refusal receipt."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir)
        receipts_dir = repo / "receipts" / "ember-resident-training-gate"
        receipts_dir.mkdir(parents=True)

        # Create a PASS receipt
        pass_ts = datetime(2026, 7, 4, 10, 0, 0, tzinfo=timezone.utc)
        pass_receipt = {
            "ticket": "EMBER-RESIDENT-TRAINING-GATE",
            "ts": pass_ts.strftime("%Y%m%dT%H%M%SZ"),
            "verdict": "RESIDENT_TRAINING_GATE_PASS",
        }
        (receipts_dir / f"resident-training-gate-{pass_ts.strftime('%Y%m%dT%H%M%SZ')}.json").write_text(
            json.dumps(pass_receipt, indent=2)
        )

        # Attempt launch BEFORE the PASS receipt (deliberately misorder)
        bad_launch_ts = pass_ts - timedelta(hours=1)
        allowed, receipt = loop_launch_guard.check_launch_precondition(repo, bad_launch_ts)

        assert allowed is False, f"Expected allowed=False for deliberately mis-ordered launch"
        assert receipt["verdict"] == "LOOP_LAUNCH_PRECONDITION_POSTDATES"
        assert "pass_ts" in receipt, "Receipt should quote pass_ts"
        assert "launch_ts" in receipt, "Receipt should quote launch_ts"

        # Verify that the guard_loop_launch raises an error
        try:
            loop_launch_guard.guard_loop_launch(repo, bad_launch_ts)
            assert False, "Expected guard_loop_launch to raise RuntimeError"
        except RuntimeError as e:
            assert "precondition not met" in str(e).lower()
            return True


def main() -> int:
    """Run all tests and report results."""
    tests = [
        ("PASS-exists-and-predates => runs", test_pass_exists_and_predates),
        ("PASS-absent => refuses naming C14", test_pass_absent),
        ("PASS-postdates-launch => refuses quoting both ts", test_pass_postdates_launch),
        ("unparseable receipt => refuses", test_unparseable_receipt_ts),
        ("deliberately mis-ordered launch produces refusal", test_deliberately_misorder_launch),
    ]

    passed = 0
    failed = 0
    for test_name, test_func in tests:
        try:
            if test_func():
                print(f"[PASS] {test_name}")
                passed += 1
            else:
                print(f"[FAIL] {test_name}")
                failed += 1
        except Exception as e:
            print(f"[FAIL] {test_name}: {e}")
            failed += 1

    print(f"\nPassed: {passed}/{len(tests)}")
    print(f"Failed: {failed}/{len(tests)}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
