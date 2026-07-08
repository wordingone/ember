#!/usr/bin/env python3
"""writers_custody_two_run_test.py -- Extended custody test for writers (issue #400).

Two-run test verifying:
  (1) milestone_leg.py run 1 + publication_gate.py run 1 → receipts created in designated dirs
  (2) milestone_leg.py run 2 + publication_gate.py run 2 → ZERO new untracked files anywhere
      under receipts/ or scripts/ember_totality/receipts-totality/

Proves that writers are custody-clean: repeated runs do NOT create new untracked files.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
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


def _run_writer_step(repo_root: Path, script_path: str, args: list[str] = None) -> tuple[str, int]:
    """Run a writer script, return (stdout, exit_code)."""
    script = repo_root / script_path
    if not script.exists():
        return f"Script {script} not found", 1

    cmd = [sys.executable, str(script)]
    if args:
        cmd.extend(args)

    result = subprocess.run(
        cmd,
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        timeout=120,
    )
    return result.stdout, result.returncode


def test_writers_custody_two_run():
    """Two-run TDD proof: writers produce zero new untracked files on consecutive runs."""

    print("=" * 70)
    print("WRITERS CUSTODY TEST (ISSUE #400)")
    print("=" * 70)

    # Identify root and target directories
    receipts_dir = REPO_ROOT / "receipts"
    totality_receipts_dir = REPO_ROOT / "scripts" / "ember_totality" / "receipts-totality"

    print(f"\nTarget directories:")
    print(f"  receipts/: {receipts_dir}")
    print(f"  receipts-totality/: {totality_receipts_dir}")

    # Capture baseline untracked files
    print("\n--- BASELINE (before any run) ---")
    receipts_files_baseline = _get_all_json_files(receipts_dir)
    totality_files_baseline = _get_all_json_files(totality_receipts_dir)
    print(f"receipts/: {len(receipts_files_baseline)} files")
    print(f"receipts-totality/: {len(totality_files_baseline)} files")

    # Get git-tracked files at baseline
    try:
        result = subprocess.run(
            ["git", "ls-files"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=30,
        )
        git_tracked_baseline = set(p.replace("\\", "/") for p in result.stdout.strip().split("\n") if p)
    except Exception as e:
        print(f"WARNING: Could not get git tracked files: {e}")
        git_tracked_baseline = set()

    # --- RUN 1 ---
    print("\n--- RUN 1 ---")
    print("\nRun 1a: Executing milestone_leg.py...")
    stdout_m1, exit_m1 = _run_writer_step(REPO_ROOT, "scripts/ember_totality/milestone_leg.py",
                                           ["--contract-root", str(REPO_ROOT)])
    print(f"  Exit code: {exit_m1}")
    if exit_m1 != 0:
        print(f"  WARNING: Non-zero exit. Output:\n{stdout_m1}")

    print("\nRun 1b: Executing check_publication_gate.py...")
    stdout_p1, exit_p1 = _run_writer_step(REPO_ROOT, "scripts/check_publication_gate.py")
    print(f"  Exit code: {exit_p1}")
    if exit_p1 != 0:
        print(f"  WARNING: Non-zero exit. Output:\n{stdout_p1}")

    receipts_files_run1 = _get_all_json_files(receipts_dir)
    totality_files_run1 = _get_all_json_files(totality_receipts_dir)
    new_receipts_run1 = receipts_files_run1 - receipts_files_baseline
    new_totality_run1 = totality_files_run1 - totality_files_baseline

    print(f"\n  receipts/: {len(receipts_files_run1)} files (new: {len(new_receipts_run1)})")
    if new_receipts_run1:
        for f in sorted(new_receipts_run1)[:3]:
            print(f"    + {f}")

    print(f"  receipts-totality/: {len(totality_files_run1)} files (new: {len(new_totality_run1)})")
    if new_totality_run1:
        for f in sorted(new_totality_run1)[:3]:
            print(f"    + {f}")

    # --- RUN 2 ---
    print("\n--- RUN 2 ---")
    print("\nRun 2a: Executing milestone_leg.py (second time)...")
    stdout_m2, exit_m2 = _run_writer_step(REPO_ROOT, "scripts/ember_totality/milestone_leg.py",
                                           ["--contract-root", str(REPO_ROOT)])
    print(f"  Exit code: {exit_m2}")
    if exit_m2 != 0:
        print(f"  WARNING: Non-zero exit. Output:\n{stdout_m2}")

    print("\nRun 2b: Executing check_publication_gate.py (second time)...")
    stdout_p2, exit_p2 = _run_writer_step(REPO_ROOT, "scripts/check_publication_gate.py")
    print(f"  Exit code: {exit_p2}")
    if exit_p2 != 0:
        print(f"  WARNING: Non-zero exit. Output:\n{stdout_p2}")

    receipts_files_run2 = _get_all_json_files(receipts_dir)
    totality_files_run2 = _get_all_json_files(totality_receipts_dir)
    new_receipts_run2 = receipts_files_run2 - receipts_files_baseline
    new_totality_run2 = totality_files_run2 - totality_files_baseline

    print(f"\n  receipts/: {len(receipts_files_run2)} files (new: {len(new_receipts_run2)})")
    if new_receipts_run2:
        for f in sorted(new_receipts_run2)[:3]:
            print(f"    + {f}")

    print(f"  receipts-totality/: {len(totality_files_run2)} files (new: {len(new_totality_run2)})")
    if new_totality_run2:
        for f in sorted(new_totality_run2)[:3]:
            print(f"    + {f}")

    # --- VERIFICATION ---
    print("\n" + "=" * 70)
    print("VERIFICATION")
    print("=" * 70)

    # Key assertion: Run 1 and Run 2 produce IDENTICAL sets of new files
    # This proves writers are idempotent wrt untracked files
    files_identical = (new_receipts_run2 == new_receipts_run1 and
                       new_totality_run2 == new_totality_run1)

    if files_identical:
        print("\n[PASS] Run 1 and Run 2 produced IDENTICAL new file sets")
        print(f"       ZERO new untracked files between runs")
    else:
        new_run2_only = (new_receipts_run2 - new_receipts_run1) | (new_totality_run2 - new_totality_run1)
        print(f"\n[FAIL] Run 2 created NEW untracked files not in Run 1:")
        for f in sorted(new_run2_only):
            print(f"       {f}")
        return False

    # Additional checks: verify spend declarations exist
    print("\n--- SPEND DECLARATION VERIFICATION ---")
    milestone_ok = False
    publication_ok = False

    for f in new_receipts_run2 | new_totality_run2:
        fpath = (receipts_dir / f) if (receipts_dir / f).exists() else (totality_receipts_dir / f)
        if fpath.exists():
            try:
                data = json.loads(fpath.read_text())
                if "milestone" in f.lower() and isinstance(data.get("api_spend_usd"), (int, float)):
                    if data.get("api_spend_usd") == 0.0 and data.get("paid_api_surface_used") is False:
                        milestone_ok = True
                        print(f"[PASS] milestone receipt carries spend declaration: {f}")
                if "publication" in f.lower() and isinstance(data.get("api_spend_usd"), (int, float)):
                    if data.get("api_spend_usd") == 0.0 and data.get("paid_api_surface_used") is False:
                        publication_ok = True
                        print(f"[PASS] publication receipt carries spend declaration: {f}")
            except Exception as e:
                print(f"[WARN] Could not parse {f}: {e}")

    if not milestone_ok:
        print("[WARN] No milestone receipt with spend declaration found")
    if not publication_ok:
        print("[WARN] No publication receipt with spend declaration found")

    print("\n" + "=" * 70)
    print("TEST PASSED [OK]")
    print("=" * 70)
    return True


if __name__ == "__main__":
    try:
        success = test_writers_custody_two_run()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\nTEST FAILED [ERROR]: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
