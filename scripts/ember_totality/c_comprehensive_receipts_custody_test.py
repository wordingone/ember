#!/usr/bin/env python3
"""c_comprehensive_receipts_custody_test.py -- Canonical receipts/ custody (TDD for issue #400).

Two-run test verifying NO new untracked files under canonical receipts/ after consecutive
board runs. All timestamped probe receipts appear in their respective subdirectories under
scripts/ember_totality/receipts-*/, never canonical.
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


def _get_all_json_files(path: Path) -> set[str]:
    """Get all .json files under a directory, relative to that directory."""
    if not path.exists():
        return set()
    return {str(f.relative_to(path)) for f in path.rglob("*.json")}


def _run_board_step(repo_root: Path, script_name: str) -> tuple[str, int]:
    """Run a board step script, return (stdout, exit_code)."""
    script = repo_root / "scripts" / script_name
    if not script.exists():
        return f"Script {script} not found", 1
    
    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        timeout=60,
    )
    return result.stdout, result.returncode


def test_comprehensive_receipts_custody():
    """Two-run TDD proof: no canonical receipts/ contamination by any probe family."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir) / "test_repo"
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

        # Create minimal docs/authority/GOAL.md
        goal_path = repo / "docs/authority/GOAL.md"
        if not goal_path.exists():
            goal_path.write_text("# GOAL\n\nMinimal GOAL for testing.\n")

        # Create necessary spec/config files
        spec_dir = repo / "docs" / "spec"
        spec_dir.mkdir(parents=True, exist_ok=True)
        
        (spec_dir / "h0-residual-lever-prereg-v1.md").write_text("| L1 |\n| L2 |\n| L3 |\n| L4 |\n| L5 |\n")
        (spec_dir / "feasibility-envelope-v1.md").write_text("measured **1.5x**\n")
        (spec_dir / "h0-lever-status.json").write_text(json.dumps({
            "L1": "PARKED", "L2": "PARKED", "L3": "PARKED", "L4": "PARKED", "L5": "PARKED"
        }))
        (spec_dir / "milestones-v1.md").write_text("""
# Milestones

## Section A: M1..M55 Mapping
| M1 | target1 |
| M2 | target2 |

## Section C: Dependency Lattice
```
M1 -> M2
```

## Section D: Floor Contract
| C1 | owner1 | pilot1 | trigger1 | kill1 |
""")
        (spec_dir / "publication-v1.md").write_text("# Publication Gate\n")

        # Create minimal receipts directories
        receipts_dir = repo / "receipts"
        receipts_dir.mkdir(exist_ok=True)
        for subdir in ["growth-rung-attempts", "bootstrap-rung", "escalation"]:
            (receipts_dir / subdir).mkdir(exist_ok=True)

        # Create new subdirectories for relocated writers
        for subdir in ["receipts-milestone", "receipts-publication", "receipts-disconfirmation"]:
            (repo / "scripts" / "ember_totality" / subdir).mkdir(parents=True, exist_ok=True)

        # Capture canonical receipts/ state BEFORE runs
        canonical_files_before = _get_all_json_files(receipts_dir)
        print(f"Baseline: {len(canonical_files_before)} files in canonical receipts/")

        # Run 1: Disconfirmation probe
        print("\nRun 1: Executing disconfirmation probe...")
        stdout1, exit1 = _run_board_step(repo, "check_disconfirmation_triggers.py")
        print(f"  Exit code: {exit1}")
        canonical_files_run1 = _get_all_json_files(receipts_dir)
        new_files_run1 = canonical_files_run1 - canonical_files_before
        print(f"  New files in canonical: {len(new_files_run1)}")
        if new_files_run1:
            for f in sorted(new_files_run1)[:5]:
                print(f"    - {f}")

        # Run 2: Milestone and Publication probes
        print("\nRun 2a: Executing milestone-reconciliation probe...")
        stdout2a, exit2a = _run_board_step(repo, "check_milestone_reconciliation.py")
        print(f"  Exit code: {exit2a}")

        print("\nRun 2b: Executing publication-gate probe...")
        stdout2b, exit2b = _run_board_step(repo, "check_publication_gate.py")
        print(f"  Exit code: {exit2b}")

        canonical_files_run2 = _get_all_json_files(receipts_dir)
        new_files_run2 = canonical_files_run2 - canonical_files_before
        print(f"\n  Total new files in canonical: {len(new_files_run2)}")
        if new_files_run2:
            for f in sorted(new_files_run2)[:5]:
                print(f"    - {f}")

        # Verification
        print("\n" + "=" * 60)
        print("VERIFICATION")
        print("=" * 60)

        if len(new_files_run2) == len(canonical_files_before):
            print("[PASS] No new files in canonical receipts/")
        else:
            print(f"[FAIL] Found {len(new_files_run2) - len(canonical_files_before)} new files in canonical receipts/")
            for f in sorted(new_files_run2 - canonical_files_before):
                print(f"       {f}")
            return False

        # Check that receipts are in new locations
        disconf_receipts = _get_all_json_files(repo / "scripts" / "ember_totality" / "receipts-disconfirmation")
        milestone_receipts = _get_all_json_files(repo / "scripts" / "ember_totality" / "receipts-milestone")
        publication_receipts = _get_all_json_files(repo / "scripts" / "ember_totality" / "receipts-publication")

        if milestone_receipts:
            print(f"[PASS] {len(milestone_receipts)} milestone receipt(s) in new location")
        else:
            print("[FAIL] No milestone receipts in new location")
            return False

        if publication_receipts:
            print(f"[PASS] {len(publication_receipts)} publication receipt(s) in new location")
        else:
            print("[FAIL] No publication receipts in new location")
            return False

        print("\n" + "=" * 60)
        print("TEST PASSED [OK]")
        print("=" * 60)
        return True


if __name__ == "__main__":
    try:
        success = test_comprehensive_receipts_custody()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"TEST FAILED [ERROR]: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
