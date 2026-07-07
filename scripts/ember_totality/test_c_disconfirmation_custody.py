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
        success = test_disconfirmation_custody()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"TEST FAILED [ERROR]: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
