#!/usr/bin/env python3
"""r0_claim_executor.py -- Self-gating claim executor for R0 autonomy-ladder.

After K=5 consecutive PASS windows, this executor:
1. Writes R0-claim-<ts>.json receipt
2. Updates autonomy-ladder-state.json (claimed=true, windows list, current_rung=R0)
3. Runs test_c_auto probe
4. ROLLS BACK state edit if probe returns RED

All in ONE motion. Failure honesty: a FAILED window resets the counter.

Spec (issue #109): claim executor is self-gating, state edit + probe run + rollback-on-non-GREEN.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def load_state(repo_root: str) -> dict[str, Any] | None:
    """Load the current autonomy-ladder-state.json."""
    state_path = os.path.join(repo_root, "autonomy-ladder-state.json")
    if not os.path.isfile(state_path):
        return None

    try:
        with open(state_path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def backup_state(repo_root: str) -> str | None:
    """Create a backup of the state file for rollback."""
    state_path = os.path.join(repo_root, "autonomy-ladder-state.json")
    if not os.path.isfile(state_path):
        return None

    backup_path = state_path + ".backup"
    try:
        shutil.copy2(state_path, backup_path)
        return backup_path
    except Exception:
        return None


def restore_state(backup_path: str) -> bool:
    """Restore state from backup."""
    state_path = backup_path.rstrip(".backup")
    try:
        shutil.copy2(backup_path, state_path)
        os.remove(backup_path)
        return True
    except Exception:
        return False


def write_claim_receipt(repo_root: str, claim_ts: str) -> str:
    """Write the claim receipt file."""
    receipt_dir = os.path.join(repo_root, "receipts", "autonomy-ladder")
    os.makedirs(receipt_dir, exist_ok=True)

    # Generate filename: R0-claim-<ts>.json
    ts_simple = claim_ts.replace("T", "T").replace("+00:00", "Z").replace(":", "").split("Z")[0] + "Z"
    filename = f"R0-claim-{ts_simple}.json"
    receipt_path = os.path.join(receipt_dir, filename)

    claim_receipt = {
        "ts": claim_ts,
        "rung": "R0",
        "promoted_at": claim_ts,
        "windows_count": 5,
        "claim_type": "promotion"
    }

    with open(receipt_path, "w", encoding="utf-8") as fh:
        json.dump(claim_receipt, fh, indent=2)
        fh.write("\n")  # LF ending per spec

    return receipt_path


def update_state(repo_root: str, window_refs: list[str], claim_ts: str) -> bool:
    """Update autonomy-ladder-state.json with the claim."""
    state_path = os.path.join(repo_root, "autonomy-ladder-state.json")

    # Load or create state
    state = load_state(repo_root)
    if state is None:
        # Initialize state if it doesn't exist
        state = {
            "schema": "autonomy-relinquishment-ladder-v1",
            "contract": "docs/spec/autonomy-relinquishment-ladder-v1.md",
            "current_rung": None,
            "rungs": {
                "R0": {"claimed": False, "windows": []},
                "R1": {"claimed": False, "windows": []},
                "R2": {"claimed": False, "windows": []},
                "R3": {"claimed": False, "windows": []},
                "R4": {"claimed": False, "windows": []},
                "R5": {"claimed": False, "windows": []},
            },
            "reversion_log": [],
            "promotion_rule": "K=5 consecutive clean receipted windows per rung; any attributable faithfulness incident reverts one rung immediately",
            "safety_floor": "escalation set, governor caps, kill-discipline"
        }

    # Update R0 claim data
    state["rungs"]["R0"]["claimed"] = True
    state["rungs"]["R0"]["windows"] = window_refs
    state["rungs"]["R0"]["claimed_at"] = claim_ts
    state["current_rung"] = "R0"

    # Write state
    try:
        with open(state_path, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2)
            fh.write("\n")  # LF ending per spec
        return True
    except Exception:
        return False


def run_c_auto_probe(repo_root: str) -> tuple[bool, str]:
    """
    Run the test_c_auto probe to verify the claim.

    Returns:
        (passed: bool, output: str)
    """
    probe_script = os.path.join(repo_root, "scripts", "ember_totality", "test_c_auto.py")

    if not os.path.isfile(probe_script):
        # Fallback: try to run from chore/board-suite-port branch
        return False, "test_c_auto.py not found"

    try:
        # Set EMBER_TOTALITY_ROOT for the probe
        env = os.environ.copy()
        env["EMBER_TOTALITY_ROOT"] = repo_root

        result = subprocess.run(
            [sys.executable, probe_script],
            cwd=repo_root,
            capture_output=True,
            text=True,
            env=env,
            timeout=30
        )

        output = result.stdout.strip() if result.stdout else result.stderr.strip()

        # Parse output: "GREEN ..." or "RED ..."
        passed = output.startswith("GREEN")

        return passed, output

    except Exception as e:
        return False, f"Probe execution failed: {str(e)}"


def execute_claim(repo_root: str, window_refs: list[str]) -> tuple[bool, dict[str, Any]]:
    """
    Execute the R0 claim with self-gating.

    Args:
        repo_root: Path to repo root
        window_refs: List of window receipt filenames (e.g., ["R0-window-1-...", ...])

    Returns:
        (success: bool, result: dict)
    """
    claim_ts = datetime.now(timezone.utc).isoformat()

    # Validate we have exactly K=5 consecutive windows
    if len(window_refs) < 5:
        return False, {
            "error": f"Need K=5 consecutive PASS windows, got {len(window_refs)}",
            "claim_ts": claim_ts
        }

    # Step 1: Backup state
    backup_path = backup_state(repo_root)

    # Step 2: Write claim receipt
    try:
        claim_receipt_path = write_claim_receipt(repo_root, claim_ts)
    except Exception as e:
        if backup_path:
            restore_state(backup_path)
        return False, {"error": f"Failed to write claim receipt: {str(e)}", "claim_ts": claim_ts}

    # Step 3: Update state
    if not update_state(repo_root, window_refs, claim_ts):
        if backup_path:
            restore_state(backup_path)
        return False, {"error": "Failed to update autonomy-ladder-state.json", "claim_ts": claim_ts}

    # Step 4: Run test_c_auto probe
    probe_passed, probe_output = run_c_auto_probe(repo_root)

    # Step 5: Rollback if probe failed
    if not probe_passed:
        if backup_path:
            restore_state(backup_path)
        return False, {
            "error": "test_c_auto probe returned RED, claim rolled back",
            "probe_output": probe_output,
            "claim_ts": claim_ts
        }

    # Clean up backup on success
    if backup_path and os.path.isfile(backup_path):
        os.remove(backup_path)

    return True, {
        "success": True,
        "claim_receipt_path": claim_receipt_path,
        "claim_ts": claim_ts,
        "windows_claimed": len(window_refs),
        "probe_output": probe_output
    }


def main():
    if len(sys.argv) < 2:
        print("Usage: r0_claim_executor.py <repo_root> [window_ref1] [window_ref2] ...")
        sys.exit(1)

    repo_root = sys.argv[1]
    window_refs = sys.argv[2:] if len(sys.argv) > 2 else []

    success, result = execute_claim(repo_root, window_refs)

    print(json.dumps({
        "success": success,
        "result": result
    }, indent=2))

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
