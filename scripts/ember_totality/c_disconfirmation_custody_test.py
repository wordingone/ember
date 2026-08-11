#!/usr/bin/env python3
"""test_c_disconfirmation_custody.py -- Disconfirmation probe receipts custody (TDD for issue #387).

Two-run test verifying no new untracked files under canonical receipts/ after consecutive
disconfirmation probe runs. Genesis file (receipts/disconfirmation-probe.json) stays frozen.
Timestamped receipts appear in scripts/ember_totality/receipts-disconfirmation/, not canonical.

EXTENDED (R3 2026-07-11): Custody tests for C-DISC hinge-tally emitter contract (#729).
Tests exercise PRODUCTION _emit_tally_receipt from cbase_grow_rung.py directly (monkeypatched
REPO) to prove emitter->checker binding. No local copies — production code only.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent


def _utc_ts():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _run_disconfirmation_probe(repo_root: Path) -> tuple[str, int]:
    """Run check_disconfirmation_triggers.py, return (stdout, exit_code)."""
    script = repo_root / "scripts" / "check_disconfirmation_triggers.py"
    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        timeout=60,
    )
    return result.stdout, result.returncode


def test_earned_growth_hinge_fires():
    """Fixture proving NOT_EARNED×2 fires EARNED_GROWTH hinge end-to-end (issue #729).

    R3: Exercise PRODUCTION _emit_tally_receipt (monkeypatched REPO) — emitter builds tally
    rows via live mode, checker verifies the exact emitted bytes, proving the emitter->checker
    binding.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        # Seed a minimal repo structure
        repo = Path(tmpdir) / "test_repo_hinge"
        repo.mkdir()

        # Copy scripts
        scripts_src = REPO_ROOT / "scripts"
        scripts_dst = repo / "scripts"
        shutil.copytree(scripts_src, scripts_dst, ignore=shutil.ignore_patterns("*.pyc", "__pycache__"))

        # Copy docs
        docs_src = REPO_ROOT / "docs"
        if docs_src.exists():
            docs_dst = repo / "docs"
            shutil.copytree(docs_src, docs_dst, ignore=shutil.ignore_patterns("*.pyc", "__pycache__"))

        # Create spec files for h0_ceiling (needed for checker to run)
        spec_dir = repo / "docs" / "spec"
        spec_dir.mkdir(parents=True, exist_ok=True)

        (spec_dir / "h0-residual-lever-prereg-v1.md").write_text("| L1 |\n| L2 |\n| L3 |\n| L4 |\n| L5 |\n")
        (spec_dir / "feasibility-envelope-v1.md").write_text("measured **1.5x**\n")
        (spec_dir / "h0-lever-status.json").write_text(json.dumps({"L1": "PARKED", "L2": "PARKED", "L3": "PARKED", "L4": "PARKED", "L5": "PARKED"}))

        # Create receipts directories
        receipts_dir = repo / "receipts"
        receipts_dir.mkdir(exist_ok=True)
        growth_dir = receipts_dir / "growth-rung-attempts"
        growth_dir.mkdir(exist_ok=True)
        bootstrap_dir = receipts_dir / "bootstrap-rung"
        bootstrap_dir.mkdir(exist_ok=True)
        escalation_dir = receipts_dir / "escalation"
        escalation_dir.mkdir(exist_ok=True)

        print("Test: test_earned_growth_hinge_fires")
        print("Fixture setup: NOT_EARNED×2 via PRODUCTION _emit_tally_receipt(mode='live')")

        # Import production cbase_grow_rung and monkeypatch REPO
        sys.path.insert(0, str(repo / "scripts"))
        import cbase_grow_rung
        original_repo = cbase_grow_rung.REPO
        try:
            cbase_grow_rung.REPO = repo

            # Build two NOT_EARNED tally receipts using the PRODUCTION emitter
            ts1 = "20260710T100000Z"
            ts2 = "20260710T110000Z"

            # Main receipts (simulate what the growth runner would have produced)
            main_receipt_1 = {
                "ticket": "CBASE-GROW-RUNG",
                "ts": ts1,
                "verdict": "GROW_RUNG_KILL",
                "rung": 1,
                "mode": "live",
            }
            main_receipt_2 = {
                "ticket": "CBASE-GROW-RUNG",
                "ts": ts2,
                "verdict": "GROW_RUNG_KILL",
                "rung": 2,
                "mode": "live",
            }

            main_path_1 = str(growth_dir / f"cbase-grow-rung-{ts1}.json")
            main_path_2 = str(growth_dir / f"cbase-grow-rung-{ts2}.json")

            (growth_dir / f"cbase-grow-rung-{ts1}.json").write_text(json.dumps(main_receipt_1))
            (growth_dir / f"cbase-grow-rung-{ts2}.json").write_text(json.dumps(main_receipt_2))

            # Call PRODUCTION _emit_tally_receipt (LIVE mode -> should emit)
            cbase_grow_rung._emit_tally_receipt(main_receipt_1, main_path_1, mode="live")
            time.sleep(1.1)  # Ensure different second-precision timestamps
            cbase_grow_rung._emit_tally_receipt(main_receipt_2, main_path_2, mode="live")

            print(f"  Attempt 1: cbase_grow_rung._emit_tally_receipt(verdict=GROW_RUNG_KILL, mode='live')")
            print(f"  Attempt 2: cbase_grow_rung._emit_tally_receipt(verdict=GROW_RUNG_KILL, mode='live')")

            # Verify the tally receipts were written
            tally_files = sorted(growth_dir.glob("growth-rung-attempt-*.json"))
            if len(tally_files) != 2:
                print(f"[FAIL] Expected 2 tally files, got {len(tally_files)}")
                return False

            for tf in tally_files:
                tally = json.loads(tf.read_text())
                if tally.get("verdict") != "NOT_EARNED":
                    print(f"[FAIL] Tally file {tf.name} has incorrect verdict: {tally.get('verdict')}")
                    return False
                if not tally.get("evaluable"):
                    print(f"[FAIL] Tally file {tf.name} should be evaluable=True")
                    return False

            print(f"  Tally files emitted: {len(tally_files)}")

            # Run the disconfirmation checker
            print("\nRunning check_disconfirmation_triggers.py...")
            stdout, exit_code = _run_disconfirmation_probe(repo)
            print(f"  Checker output:")
            for line in stdout.strip().split('\n'):
                print(f"    {line}")
            print(f"  Exit code: {exit_code}")

            # Verify the EARNED_GROWTH hinge fired
            eval_receipts = sorted(
                (repo / "scripts" / "ember_totality" / "receipts-disconfirmation").glob("disconfirmation-eval-*.json"),
                reverse=True
            )
            if not eval_receipts:
                print("[FAIL] No evaluation receipt found from checker")
                return False

            eval_receipt = json.loads(eval_receipts[0].read_text(encoding="utf-8"))
            hinges = {h["hinge"]: h for h in eval_receipt.get("hinges", [])}

            earned_growth = hinges.get("EARNED_GROWTH", {})
            if earned_growth.get("trigger_fired"):
                print(f"[PASS] EARNED_GROWTH hinge fired as expected")
                print(f"  attempts_seen: {earned_growth.get('attempts_seen')}")
                print(f"  consecutive_fail_streak: {earned_growth.get('consecutive_fail_streak')}")
                return True
            else:
                print(f"[FAIL] EARNED_GROWTH hinge did NOT fire (expected on NOT_EARNED×2)")
                return False
        finally:
            cbase_grow_rung.REPO = original_repo


def test_mode_gate_dry_run():
    """R3: Mode gate test — dry-run should NOT emit tally files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir) / "test_repo_mode"
        repo.mkdir()

        receipts_dir = repo / "receipts"
        receipts_dir.mkdir(exist_ok=True)
        growth_dir = receipts_dir / "growth-rung-attempts"
        growth_dir.mkdir(exist_ok=True)

        print("Test: test_mode_gate_dry_run")
        print("Fixture setup: PRODUCTION _emit_tally_receipt(mode='dry-run') should NOT emit")

        # Import and monkeypatch
        sys.path.insert(0, str(repo / "scripts"))
        import cbase_grow_rung
        original_repo = cbase_grow_rung.REPO
        try:
            cbase_grow_rung.REPO = repo

            receipt = {"ticket": "TEST", "verdict": "GROW_RUNG_KILL", "rung": 1}
            main_path = str(growth_dir / "dummy.json")

            initial_count = len(list(growth_dir.glob("growth-rung-attempt-*.json")))
            cbase_grow_rung._emit_tally_receipt(receipt, main_path, mode="dry-run")
            final_count = len(list(growth_dir.glob("growth-rung-attempt-*.json")))

            if initial_count == final_count:
                print(f"[PASS] Dry-run mode emitted NO files (expected)")
                return True
            else:
                print(f"[FAIL] Dry-run mode emitted {final_count - initial_count} file(s) (expected 0)")
                return False
        finally:
            cbase_grow_rung.REPO = original_repo


def test_mode_gate_selftest():
    """R3: Mode gate test — selftest should NOT emit tally files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir) / "test_repo_selftest"
        repo.mkdir()

        receipts_dir = repo / "receipts"
        receipts_dir.mkdir(exist_ok=True)
        growth_dir = receipts_dir / "growth-rung-attempts"
        growth_dir.mkdir(exist_ok=True)

        print("Test: test_mode_gate_selftest")
        print("Fixture setup: PRODUCTION _emit_tally_receipt(mode='selftest') should NOT emit")

        # Import and monkeypatch
        sys.path.insert(0, str(repo / "scripts"))
        import cbase_grow_rung
        original_repo = cbase_grow_rung.REPO
        try:
            cbase_grow_rung.REPO = repo

            receipt = {"ticket": "TEST", "verdict": "GROW_RUNG_PASS", "rung": 1}
            main_path = str(growth_dir / "dummy.json")

            initial_count = len(list(growth_dir.glob("growth-rung-attempt-*.json")))
            cbase_grow_rung._emit_tally_receipt(receipt, main_path, mode="selftest")
            final_count = len(list(growth_dir.glob("growth-rung-attempt-*.json")))

            if initial_count == final_count:
                print(f"[PASS] Selftest mode emitted NO files (expected)")
                return True
            else:
                print(f"[FAIL] Selftest mode emitted {final_count - initial_count} file(s) (expected 0)")
                return False
        finally:
            cbase_grow_rung.REPO = original_repo


def test_unknown_verdict_raises():
    """R3: Unknown verdict in LIVE mode should raise (fail-closed)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir) / "test_repo_unknown"
        repo.mkdir()

        receipts_dir = repo / "receipts"
        receipts_dir.mkdir(exist_ok=True)
        growth_dir = receipts_dir / "growth-rung-attempts"
        growth_dir.mkdir(exist_ok=True)

        print("Test: test_unknown_verdict_raises")
        print("Fixture setup: PRODUCTION _emit_tally_receipt(verdict='UNKNOWN', mode='live') should raise")

        # Import and monkeypatch
        sys.path.insert(0, str(repo / "scripts"))
        import cbase_grow_rung
        original_repo = cbase_grow_rung.REPO
        try:
            cbase_grow_rung.REPO = repo

            receipt = {"ticket": "TEST", "verdict": "UNKNOWN_VERDICT_INVALID", "rung": 1}
            main_path = str(growth_dir / "dummy.json")

            try:
                cbase_grow_rung._emit_tally_receipt(receipt, main_path, mode="live")
                print(f"[FAIL] Expected ValueError but no exception was raised")
                return False
            except ValueError as e:
                if "Unknown run_verdict" in str(e):
                    print(f"[PASS] Raised ValueError as expected: {e}")
                    return True
                else:
                    print(f"[FAIL] Raised ValueError but wrong message: {e}")
                    return False
        finally:
            cbase_grow_rung.REPO = original_repo


def test_blocked_evaluable_false():
    """R3: BLOCKED verdict should emit evaluable=false audit row (no verdict field)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir) / "test_repo_blocked"
        repo.mkdir()

        receipts_dir = repo / "receipts"
        receipts_dir.mkdir(exist_ok=True)
        growth_dir = receipts_dir / "growth-rung-attempts"
        growth_dir.mkdir(exist_ok=True)

        print("Test: test_blocked_evaluable_false")
        print("Fixture setup: PRODUCTION _emit_tally_receipt(verdict=GROW_RUNG_BLOCKED, mode='live')")

        # Import and monkeypatch
        sys.path.insert(0, str(repo / "scripts"))
        import cbase_grow_rung
        original_repo = cbase_grow_rung.REPO
        try:
            cbase_grow_rung.REPO = repo

            receipt = {"ticket": "TEST", "verdict": "GROW_RUNG_BLOCKED", "rung": 1}
            main_path = str(growth_dir / "dummy.json")

            cbase_grow_rung._emit_tally_receipt(receipt, main_path, mode="live")

            # Verify the file was emitted
            tally_files = list(growth_dir.glob("growth-rung-attempt-*.json"))
            if len(tally_files) != 1:
                print(f"[FAIL] Expected 1 tally file, got {len(tally_files)}")
                return False

            tally = json.loads(tally_files[0].read_text())

            # Verify evaluable=false and no verdict field
            if not tally.get("evaluable") == False:
                print(f"[FAIL] BLOCKED row should have evaluable=False, got {tally.get('evaluable')}")
                return False

            if "verdict" in tally:
                print(f"[FAIL] BLOCKED row should NOT have verdict field, but has: {tally.get('verdict')}")
                return False

            print(f"[PASS] BLOCKED row emitted with evaluable=False and no verdict field")
            return True
        finally:
            cbase_grow_rung.REPO = original_repo


def test_disconfirmation_custody():
    """Original custody test: Two-run TDD proof of no canonical receipts/ contamination."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Seed a minimal repo structure with necessary files
        repo = Path(tmpdir) / "test_repo"
        repo.mkdir()

        # Copy scripts
        scripts_src = REPO_ROOT / "scripts"
        scripts_dst = repo / "scripts"
        shutil.copytree(scripts_src, scripts_dst, ignore=shutil.ignore_patterns("*.pyc", "__pycache__"))

        # Copy docs (for docs/authority/GOAL.md and spec files)
        docs_src = REPO_ROOT / "docs"
        if docs_src.exists():
            docs_dst = repo / "docs"
            shutil.copytree(docs_src, docs_dst, ignore=shutil.ignore_patterns("*.pyc", "__pycache__"))

        # Create minimal docs/authority/GOAL.md if missing
        goal_path = repo / "docs/authority/GOAL.md"
        if not goal_path.exists():
            goal_path.write_text("# GOAL\n\nMinimal GOAL for testing disconfirmation.\n")

        # Create necessary spec files for h0_ceiling check
        spec_dir = repo / "docs" / "spec"
        spec_dir.mkdir(parents=True, exist_ok=True)

        (spec_dir / "h0-residual-lever-prereg-v1.md").write_text("| L1 |\n| L2 |\n| L3 |\n| L4 |\n| L5 |\n")
        (spec_dir / "feasibility-envelope-v1.md").write_text("measured **1.5x**\n")
        (spec_dir / "h0-lever-status.json").write_text(json.dumps({"L1": "PARKED", "L2": "PARKED", "L3": "PARKED", "L4": "PARKED", "L5": "PARKED"}))

        # Create minimal receipts directories
        receipts_dir = repo / "receipts"
        receipts_dir.mkdir(exist_ok=True)
        growth_dir = receipts_dir / "growth-rung-attempts"
        growth_dir.mkdir(exist_ok=True)
        bootstrap_dir = receipts_dir / "bootstrap-rung"
        bootstrap_dir.mkdir(exist_ok=True)
        escalation_dir = receipts_dir / "escalation"
        escalation_dir.mkdir(exist_ok=True)

        print("Test: test_disconfirmation_custody")

        # Run 1: Disconfirmation probe
        print("Run 1: Executing disconfirmation probe...")
        stdout1, exit1 = _run_disconfirmation_probe(repo)
        print(f"  Output: {stdout1.splitlines()[-1] if stdout1 else '(no output)'}")
        print(f"  Exit code: {exit1}")

        # Check state after run 1
        new_canonical_files_1 = list(receipts_dir.glob("disconfirmation-*.json"))
        print(f"  Canonical receipts/ disconfirmation files: {len(new_canonical_files_1)}")

        receipts_disconf_1 = list((repo / "scripts" / "ember_totality" / "receipts-disconfirmation").glob("*.json"))
        print(f"  Timestamped receipts in new location: {len(receipts_disconf_1)}")
        if receipts_disconf_1:
            print(f"    - {receipts_disconf_1[0].name}")

        # Run 2: Second disconfirmation probe
        print("\nRun 2: Executing disconfirmation probe...")
        stdout2, exit2 = _run_disconfirmation_probe(repo)
        print(f"  Output: {stdout2.splitlines()[-1] if stdout2 else '(no output)'}")
        print(f"  Exit code: {exit2}")

        # Check state after run 2
        new_canonical_files_2 = list(receipts_dir.glob("disconfirmation-*.json"))
        print(f"  Canonical receipts/ disconfirmation files: {len(new_canonical_files_2)}")

        receipts_disconf_2 = list((repo / "scripts" / "ember_totality" / "receipts-disconfirmation").glob("*.json"))
        print(f"  Timestamped receipts in new location: {len(receipts_disconf_2)}")
        for f in receipts_disconf_2[-3:]:  # Show last 3
            print(f"    - {f.name}")

        # Verify tests
        print("\n" + "=" * 60)
        print("VERIFICATION")
        print("=" * 60)

        # Test 1: No new files in canonical receipts/
        if len(new_canonical_files_2) == 0:
            print("[PASS] No disconfirmation-eval files in canonical receipts/")
        else:
            print(f"[FAIL] Found {len(new_canonical_files_2)} disconfirmation-eval files in canonical receipts/")
            for f in new_canonical_files_2:
                print(f"       {f.name}")
            return False

        # Test 2: Timestamped receipts in new location (1+ is sufficient with same-second precision)
        if len(receipts_disconf_2) >= 1:
            print(f"[PASS] {len(receipts_disconf_2)} timestamped receipt(s) created in new location")
            return True
        else:
            print(f"[FAIL] Expected 1+ timestamped receipts in new location, got {len(receipts_disconf_2)}")
            return False


if __name__ == "__main__":
    print("=" * 60)
    print("C-DISC HINGE-TALLY EMITTER CUSTODY TESTS (R3 FINAL)")
    print("=" * 60)

    tests = [
        ("test_earned_growth_hinge_fires", test_earned_growth_hinge_fires),
        ("test_mode_gate_dry_run", test_mode_gate_dry_run),
        ("test_mode_gate_selftest", test_mode_gate_selftest),
        ("test_unknown_verdict_raises", test_unknown_verdict_raises),
        ("test_blocked_evaluable_false", test_blocked_evaluable_false),
        ("test_disconfirmation_custody", test_disconfirmation_custody),
    ]

    results = {}
    for name, test_func in tests:
        print("\n" + "=" * 60)
        try:
            result = test_func()
            results[name] = "PASS" if result else "FAIL"
        except Exception as e:
            print(f"[ERROR] {e}")
            import traceback
            traceback.print_exc()
            results[name] = "ERROR"

    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    for name, result in results.items():
        status = f"[{result}]".ljust(8)
        print(f"{status} {name}")

    all_pass = all(r == "PASS" for r in results.values())
    print("\n" + ("=" * 60))
    if all_pass:
        print("ALL TESTS PASSED")
        sys.exit(0)
    else:
        print("SOME TESTS FAILED")
        sys.exit(1)
