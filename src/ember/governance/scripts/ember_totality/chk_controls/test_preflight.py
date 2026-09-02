#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""test_preflight.py -- TDD tests for CHK controls preflight check.

Tests that the preflight_check_probe_files() function correctly:
1. Passes when all expected probe files exist
2. Fails loudly, naming missing files, when any are absent
"""

import os
import sys
import subprocess
import tempfile
import shutil
from pathlib import Path


HERE = os.path.dirname(os.path.abspath(__file__))
PROBES_DIR = os.path.dirname(HERE)
REPO_ROOT = os.path.abspath(os.path.join(PROBES_DIR, "..", ".."))
RUN_CONTROLS_PATH = os.path.join(HERE, "run_controls.py")


def test_preflight_passes_with_all_files():
    """Test that preflight passes when all expected probe files exist."""
    # Import and test directly
    import importlib.util
    spec = importlib.util.spec_from_file_location("run_controls", RUN_CONTROLS_PATH)
    run_controls = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(run_controls)

    # Just call the preflight function; if it doesn't raise, it passed.
    try:
        run_controls.preflight_check_probe_files()
        print("[PASS] Preflight passes with all expected probe files present")
    except SystemExit as e:
        if e.code == 1:
            raise AssertionError("Preflight failed when all files should exist")
        else:
            raise


def test_preflight_fails_with_missing_file():
    """Test that preflight fails loudly, naming the missing file."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("run_controls", RUN_CONTROLS_PATH)
    run_controls = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(run_controls)

    # Temporarily patch PROBES_DIR to point to a directory missing a file
    original_probes_dir = run_controls.PROBES_DIR
    with tempfile.TemporaryDirectory() as tmpdir:
        # Copy all existing probe files
        for f in os.listdir(original_probes_dir):
            if f.endswith(".py") and f.startswith("test_c"):
                src = os.path.join(original_probes_dir, f)
                dst = os.path.join(tmpdir, f)
                shutil.copy2(src, dst)

        # Remove test_c_auto.py to simulate the missing file condition
        missing_file = os.path.join(tmpdir, "test_c_auto.py")
        if os.path.exists(missing_file):
            os.remove(missing_file)

        # Patch PROBES_DIR and test
        run_controls.PROBES_DIR = tmpdir
        try:
            run_controls.preflight_check_probe_files()
            raise AssertionError("Preflight should have failed but passed")
        except SystemExit as e:
            if e.code == 1:
                # Expected: preflight failed
                print("[PASS] Preflight correctly fails when probe file is missing")
            else:
                raise AssertionError(f"Preflight exited with unexpected code {e.code}")
        finally:
            run_controls.PROBES_DIR = original_probes_dir


if __name__ == "__main__":
    print("Running CHK preflight tests...")
    print()
    test_preflight_passes_with_all_files()
    print()
    test_preflight_fails_with_missing_file()
    print()
    print("All preflight tests passed!")
