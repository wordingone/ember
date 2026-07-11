#!/usr/bin/env python3
"""test_c_disconfirmation_custody.py -- Disconfirmation probe receipts custody (TDD for issue #387).

Two-run test verifying no new untracked files under canonical receipts/ after consecutive
disconfirmation probe runs. Genesis file (receipts/disconfirmation-probe.json) stays frozen.
Timestamped receipts appear in scripts/ember_totality/receipts-disconfirmation/, not canonical.
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

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent

# Add scripts to path so we can import cbase_grow_rung for the emitter function
sys.path.insert(0, str(REPO_ROOT / "scripts"))


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
    """Fixture proving NOT_EARNED×2 fires EARNED_GROWTH hinge end-to-end (issue #729)."""
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

        # Create two NOT_EARNED growth attempt receipts
        ts1 = "20260710T100000Z"
        ts2 = "20260710T110000Z"

        attempt1 = {
            "receipt_type": "growth_rung_attempt",
            "ts": ts1,
            "verdict": "NOT_EARNED",
            "evaluable": True,
            "refs": ["receipts/cbase-grow-rung/dummy1.json"],
            "git_anchor": "abc1234",
            "rung": 1,
            "mode": "live",
        }
        attempt2 = {
            "receipt_type": "growth_rung_attempt",
            "ts": ts2,
            "verdict": "NOT_EARNED",
            "evaluable": True,
            "refs": ["receipts/cbase-grow-rung/dummy2.json"],
            "git_anchor": "abc1235",
            "rung": 2,
            "mode": "live",
        }

        (growth_dir / f"growth-rung-attempt-{ts1}.json").write_text(json.dumps(attempt1))
        (growth_dir / f"growth-rung-attempt-{ts2}.json").write_text(json.dumps(attempt2))

        print("Fixture setup: NOT_EARNED×2 in growth-rung-attempts/")
        print(f"  Attempt 1 (ts={ts1}): verdict=NOT_EARNED, evaluable=True")
        print(f"  Attempt 2 (ts={ts2}): verdict=NOT_EARNED, evaluable=True")

        # Run the disconfirmation checker
        print("\nRunning check_disconfirmation_triggers.py...")
        stdout, exit_code = _run_disconfirmation_probe(repo)
        print(f"  Checker output:")
        for line in stdout.strip().split('\n'):
            print(f"    {line}")
        print(f"  Exit code: {exit_code}")

        # Verify the EARNED_GROWTH hinge fired
        # Look for disconfirmation-eval receipts (the actual checker output, not the wrapper leg)
        eval_receipts = sorted(
            (repo / "scripts" / "ember_totality" / "receipts-disconfirmation").glob("disconfirmation-eval-*.json"),
            reverse=True  # Most recent first
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
            print(f"  threshold: {earned_growth.get('threshold')}")
            print(f"  firing_receipt_refs: {earned_growth.get('firing_receipt_refs')}")
            return True
        else:
            print(f"[FAIL] EARNED_GROWTH hinge did NOT fire (expected to fire on NOT_EARNED×2)")
            print(f"  attempts_seen: {earned_growth.get('attempts_seen')}")
            print(f"  consecutive_fail_streak: {earned_growth.get('consecutive_fail_streak')}")
            print(f"  threshold: {earned_growth.get('threshold')}")
            print(f"  State: {earned_growth}")
            return False


def test_kill_with_dryrun_between():
    """Fixture: KILL×2 with dry-run between -> EARNED_GROWTH fires (R2).

    Tests that a dry-run in between two KILL attempts doesn't break the streak
    (dry-run emits nothing, so it doesn't appear in tally at all).
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir) / "test_repo_kill_dryrun"
        repo.mkdir()

        # Minimal setup
        scripts_src = REPO_ROOT / "scripts"
        scripts_dst = repo / "scripts"
        shutil.copytree(scripts_src, scripts_dst, ignore=shutil.ignore_patterns("*.pyc", "__pycache__"))

        docs_src = REPO_ROOT / "docs"
        if docs_src.exists():
            docs_dst = repo / "docs"
            shutil.copytree(docs_src, docs_dst, ignore=shutil.ignore_patterns("*.pyc", "__pycache__"))

        spec_dir = repo / "docs" / "spec"
        spec_dir.mkdir(parents=True, exist_ok=True)
        (spec_dir / "h0-residual-lever-prereg-v1.md").write_text("| L1 |\n| L2 |\n| L3 |\n| L4 |\n| L5 |\n")
        (spec_dir / "feasibility-envelope-v1.md").write_text("measured **1.5x**\n")
        (spec_dir / "h0-lever-status.json").write_text(json.dumps({"L1": "PARKED", "L2": "PARKED", "L3": "PARKED", "L4": "PARKED", "L5": "PARKED"}))

        receipts_dir = repo / "receipts"
        receipts_dir.mkdir(exist_ok=True)
        growth_dir = receipts_dir / "growth-rung-attempts"
        growth_dir.mkdir(exist_ok=True)
        (receipts_dir / "bootstrap-rung").mkdir(exist_ok=True)
        (receipts_dir / "escalation").mkdir(exist_ok=True)

        # Create KILL, dry-run, KILL
        ts1 = "20260710T120000Z"
        ts_dryrun = "20260710T125000Z"
        ts2 = "20260710T130000Z"

        kill1 = {
            "receipt_type": "growth_rung_attempt",
            "ts": ts1,
            "verdict": "NOT_EARNED",
            "evaluable": True,
            "refs": ["receipts/cbase-grow-rung/kill1.json"],
            "git_anchor": "abc1",
            "rung": 1,
            "mode": "live",
            "run_verdict": "GROW_RUNG_KILL",
        }
        # dry-run: should NOT appear in tally
        dryrun = {
            "receipt_type": "growth_rung_attempt",
            "ts": ts_dryrun,
            "evaluable": True,  # (dry-run doesn't emit, but if it did...)
            "refs": ["receipts/cbase-grow-rung/dryrun.json"],
            "mode": "dry-run",  # Mode indicates it's not live
            "run_verdict": "GROW_RUNG_DRYRUN_PASS",
        }
        kill2 = {
            "receipt_type": "growth_rung_attempt",
            "ts": ts2,
            "verdict": "NOT_EARNED",
            "evaluable": True,
            "refs": ["receipts/cbase-grow-rung/kill2.json"],
            "git_anchor": "abc2",
            "rung": 2,
            "mode": "live",
            "run_verdict": "GROW_RUNG_KILL",
        }

        (growth_dir / f"growth-rung-attempt-{ts1}.json").write_text(json.dumps(kill1))
        # Deliberately don't emit the dry-run (it shouldn't appear in live tally anyway)
        (growth_dir / f"growth-rung-attempt-{ts2}.json").write_text(json.dumps(kill2))

        print("Fixture: KILL×2 with dry-run between (dry-run not emitted to tally)")
        stdout, _ = _run_disconfirmation_probe(repo)

        eval_receipts = sorted(
            (repo / "scripts" / "ember_totality" / "receipts-disconfirmation").glob("disconfirmation-eval-*.json"),
            reverse=True
        )
        if not eval_receipts:
            print("[FAIL] No eval receipt")
            return False

        eval_receipt = json.loads(eval_receipts[0].read_text(encoding="utf-8"))
        hinges = {h["hinge"]: h for h in eval_receipt.get("hinges", [])}
        earned_growth = hinges.get("EARNED_GROWTH", {})

        if earned_growth.get("trigger_fired"):
            print(f"[PASS] EARNED_GROWTH fired (streak={earned_growth.get('consecutive_fail_streak')})")
            return True
        else:
            print(f"[FAIL] Did not fire")
            print(f"  State: {earned_growth}")
            return False


def test_evaluable_false_between_kills():
    """Fixture: evaluable=false row between two KILLs -> still fires (R2).

    Tests that an unevaluable row (evaluable=false) doesn't break a KILL streak.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir) / "test_repo_eval_false"
        repo.mkdir()

        scripts_src = REPO_ROOT / "scripts"
        scripts_dst = repo / "scripts"
        shutil.copytree(scripts_src, scripts_dst, ignore=shutil.ignore_patterns("*.pyc", "__pycache__"))

        docs_src = REPO_ROOT / "docs"
        if docs_src.exists():
            docs_dst = repo / "docs"
            shutil.copytree(docs_src, docs_dst, ignore=shutil.ignore_patterns("*.pyc", "__pycache__"))

        spec_dir = repo / "docs" / "spec"
        spec_dir.mkdir(parents=True, exist_ok=True)
        (spec_dir / "h0-residual-lever-prereg-v1.md").write_text("| L1 |\n| L2 |\n| L3 |\n| L4 |\n| L5 |\n")
        (spec_dir / "feasibility-envelope-v1.md").write_text("measured **1.5x**\n")
        (spec_dir / "h0-lever-status.json").write_text(json.dumps({"L1": "PARKED", "L2": "PARKED", "L3": "PARKED", "L4": "PARKED", "L5": "PARKED"}))

        receipts_dir = repo / "receipts"
        receipts_dir.mkdir(exist_ok=True)
        growth_dir = receipts_dir / "growth-rung-attempts"
        growth_dir.mkdir(exist_ok=True)
        (receipts_dir / "bootstrap-rung").mkdir(exist_ok=True)
        (receipts_dir / "escalation").mkdir(exist_ok=True)

        ts1 = "20260710T140000Z"
        ts_unevaluable = "20260710T145000Z"
        ts2 = "20260710T150000Z"

        kill1 = {
            "receipt_type": "growth_rung_attempt",
            "ts": ts1,
            "verdict": "NOT_EARNED",
            "evaluable": True,
            "refs": ["receipts/cbase-grow-rung/k1.json"],
            "mode": "live",
        }
        # Unevaluable row (no verdict, evaluable=false)
        unevaluable = {
            "receipt_type": "growth_rung_attempt",
            "ts": ts_unevaluable,
            "evaluable": False,  # Unevaluable — per checker, doesn't break streak
            "refs": ["receipts/cbase-grow-rung/crashed.json"],
            "mode": "live",
        }
        kill2 = {
            "receipt_type": "growth_rung_attempt",
            "ts": ts2,
            "verdict": "NOT_EARNED",
            "evaluable": True,
            "refs": ["receipts/cbase-grow-rung/k2.json"],
            "mode": "live",
        }

        (growth_dir / f"growth-rung-attempt-{ts1}.json").write_text(json.dumps(kill1))
        (growth_dir / f"growth-rung-attempt-{ts_unevaluable}.json").write_text(json.dumps(unevaluable))
        (growth_dir / f"growth-rung-attempt-{ts2}.json").write_text(json.dumps(kill2))

        print("Fixture: evaluable=false between two KILLs (doesn't break streak)")
        stdout, _ = _run_disconfirmation_probe(repo)

        eval_receipts = sorted(
            (repo / "scripts" / "ember_totality" / "receipts-disconfirmation").glob("disconfirmation-eval-*.json"),
            reverse=True
        )
        if not eval_receipts:
            print("[FAIL] No eval receipt")
            return False

        eval_receipt = json.loads(eval_receipts[0].read_text(encoding="utf-8"))
        hinges = {h["hinge"]: h for h in eval_receipt.get("hinges", [])}
        earned_growth = hinges.get("EARNED_GROWTH", {})

        if earned_growth.get("trigger_fired"):
            print(f"[PASS] EARNED_GROWTH fired (attempts={earned_growth.get('attempts_seen')}, streak={earned_growth.get('consecutive_fail_streak')})")
            return True
        else:
            print(f"[FAIL] Did not fire")
            return False


def test_blocked_alone_does_not_fire():
    """Fixture: BLOCKED×2 alone -> does NOT fire (R2).

    BLOCKED verdict creates evaluable=false rows, which can't contribute to the
    NOT_EARNED streak. Two evaluable=false rows don't trigger.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir) / "test_repo_blocked"
        repo.mkdir()

        scripts_src = REPO_ROOT / "scripts"
        scripts_dst = repo / "scripts"
        shutil.copytree(scripts_src, scripts_dst, ignore=shutil.ignore_patterns("*.pyc", "__pycache__"))

        docs_src = REPO_ROOT / "docs"
        if docs_src.exists():
            docs_dst = repo / "docs"
            shutil.copytree(docs_src, docs_dst, ignore=shutil.ignore_patterns("*.pyc", "__pycache__"))

        spec_dir = repo / "docs" / "spec"
        spec_dir.mkdir(parents=True, exist_ok=True)
        (spec_dir / "h0-residual-lever-prereg-v1.md").write_text("| L1 |\n| L2 |\n| L3 |\n| L4 |\n| L5 |\n")
        (spec_dir / "feasibility-envelope-v1.md").write_text("measured **1.5x**\n")
        (spec_dir / "h0-lever-status.json").write_text(json.dumps({"L1": "PARKED", "L2": "PARKED", "L3": "PARKED", "L4": "PARKED", "L5": "PARKED"}))

        receipts_dir = repo / "receipts"
        receipts_dir.mkdir(exist_ok=True)
        growth_dir = receipts_dir / "growth-rung-attempts"
        growth_dir.mkdir(exist_ok=True)
        (receipts_dir / "bootstrap-rung").mkdir(exist_ok=True)
        (receipts_dir / "escalation").mkdir(exist_ok=True)

        ts1 = "20260710T160000Z"
        ts2 = "20260710T170000Z"

        blocked1 = {
            "receipt_type": "growth_rung_attempt",
            "ts": ts1,
            "evaluable": False,  # BLOCKED is unevaluable
            "refs": ["receipts/cbase-grow-rung/b1.json"],
            "mode": "live",
            "run_verdict": "GROW_RUNG_BLOCKED",
        }
        blocked2 = {
            "receipt_type": "growth_rung_attempt",
            "ts": ts2,
            "evaluable": False,  # BLOCKED is unevaluable
            "refs": ["receipts/cbase-grow-rung/b2.json"],
            "mode": "live",
            "run_verdict": "GROW_RUNG_BLOCKED",
        }

        (growth_dir / f"growth-rung-attempt-{ts1}.json").write_text(json.dumps(blocked1))
        (growth_dir / f"growth-rung-attempt-{ts2}.json").write_text(json.dumps(blocked2))

        print("Fixture: BLOCKED×2 alone (evaluable=false, should NOT fire)")
        stdout, _ = _run_disconfirmation_probe(repo)

        eval_receipts = sorted(
            (repo / "scripts" / "ember_totality" / "receipts-disconfirmation").glob("disconfirmation-eval-*.json"),
            reverse=True
        )
        if not eval_receipts:
            print("[FAIL] No eval receipt")
            return False

        eval_receipt = json.loads(eval_receipts[0].read_text(encoding="utf-8"))
        hinges = {h["hinge"]: h for h in eval_receipt.get("hinges", [])}
        earned_growth = hinges.get("EARNED_GROWTH", {})

        if not earned_growth.get("trigger_fired"):
            print(f"[PASS] EARNED_GROWTH did NOT fire (as expected)")
            return True
        else:
            print(f"[FAIL] Should not have fired")
            return False


def test_disconfirmation_custody():
    """Two-run TDD proof: no canonical receipts/ contamination, timestamped receipts in new location."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Seed a minimal repo structure with necessary files
        repo = Path(tmpdir) / "test_repo"
        repo.mkdir()

        # Copy scripts
        scripts_src = REPO_ROOT / "scripts"
        scripts_dst = repo / "scripts"
        shutil.copytree(scripts_src, scripts_dst, ignore=shutil.ignore_patterns("*.pyc", "__pycache__"))

        # Copy docs (for GOAL.md and spec files)
        docs_src = REPO_ROOT / "docs"
        if docs_src.exists():
            docs_dst = repo / "docs"
            shutil.copytree(docs_src, docs_dst, ignore=shutil.ignore_patterns("*.pyc", "__pycache__"))

        # Create minimal GOAL.md if missing
        goal_path = repo / "GOAL.md"
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
        for f in receipts_disconf_2:
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
            for f in receipts_disconf_2:
                ts = f.name.replace("disconfirmation-eval-", "").replace(".json", "")
                print(f"       {f.name}")
        else:
            print(f"[FAIL] Expected 1+ timestamped receipts in new location, got {len(receipts_disconf_2)}")
            return False

        print("\n" + "=" * 60)
        print("TEST PASSED [OK]")
        print("=" * 60)
        return True


if __name__ == "__main__":
    try:
        print("=" * 60)
        print("TEST 1: EARNED_GROWTH hinge fires on NOT_EARNED×2 (issue #729)")
        print("=" * 60)
        test1 = test_earned_growth_hinge_fires()

        print("\n" + "=" * 60)
        print("TEST 2: KILL×2 with dry-run between -> fires (R2)")
        print("=" * 60)
        test2 = test_kill_with_dryrun_between()

        print("\n" + "=" * 60)
        print("TEST 3: evaluable=false between KILLs -> still fires (R2)")
        print("=" * 60)
        test3 = test_evaluable_false_between_kills()

        print("\n" + "=" * 60)
        print("TEST 4: BLOCKED×2 alone -> does NOT fire (R2)")
        print("=" * 60)
        test4 = test_blocked_alone_does_not_fire()

        print("\n" + "=" * 60)
        print("TEST 5: Disconfirmation custody (no canonical contamination)")
        print("=" * 60)
        test5 = test_disconfirmation_custody()

        print("\n" + "=" * 60)
        print("SUMMARY")
        print("=" * 60)
        print(f"Test 1 (NOT_EARNED×2 fires): {'PASS' if test1 else 'FAIL'}")
        print(f"Test 2 (KILL×2 with dry-run fires): {'PASS' if test2 else 'FAIL'}")
        print(f"Test 3 (evaluable=false doesn't break): {'PASS' if test3 else 'FAIL'}")
        print(f"Test 4 (BLOCKED×2 doesn't fire): {'PASS' if test4 else 'FAIL'}")
        print(f"Test 5 (Custody): {'PASS' if test5 else 'FAIL'}")

        sys.exit(0 if all([test1, test2, test3, test4, test5]) else 1)
    except Exception as e:
        print(f"TEST FAILED [ERROR]: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
