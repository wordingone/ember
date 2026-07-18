# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
#!/usr/bin/env python3
"""TDD test suite for C-CUSTODY probe (issue #381).

Tests the three failure shapes:
  (a) untracked-in-canonical
  (b) unparseable JSON
  (c) cited-path-missing

Plus a clean GREEN case.
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def run_probe(root_dir):
    """Run test_c_custody.py with EMBER_TOTALITY_ROOT set to root_dir.
    Returns (stdout_line, returncode)."""
    probe_path = os.path.join(
        os.path.dirname(__file__), "..", "ember_totality", "test_c_custody.py"
    )
    try:
        result = subprocess.run(
            [sys.executable, probe_path],
            cwd=root_dir,
            capture_output=True,
            text=True,
            timeout=30,
            env={**os.environ, "EMBER_TOTALITY_ROOT": root_dir},
        )
        lines = result.stdout.strip().split("\n")
        first_line = lines[0] if lines else ""
        return first_line, result.returncode
    except Exception as e:
        return f"ERROR: {e}", 1


def test_shape_a_untracked():
    """Shape (a): untracked-in-canonical — untracked file in receipts/."""
    with tempfile.TemporaryDirectory() as tmpdir:
        receipts_dir = os.path.join(tmpdir, "receipts")
        os.makedirs(receipts_dir)

        # Create an untracked receipt file
        receipt_file = os.path.join(receipts_dir, "untracked-file.json")
        receipt_data = {
            "ticket": "TEST-UNTRACKED",
            "ts": "20260707T000000Z",
            "status": "test",
        }
        with open(receipt_file, "w", encoding="utf-8") as f:
            json.dump(receipt_data, f)

        # Initialize a git repo and DON'T track this file
        subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=tmpdir,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=tmpdir,
            capture_output=True,
        )

        # Create a tracked dummy file so we have something in the index
        dummy = os.path.join(tmpdir, ".gitkeep")
        Path(dummy).touch()
        subprocess.run(["git", "add", ".gitkeep"], cwd=tmpdir, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=tmpdir,
            capture_output=True,
        )

        output, _ = run_probe(tmpdir)
        assert "RED" in output, f"Expected RED for untracked file, got: {output}"
        assert "UNTRACKED" in output or "custody" in output.lower(), (
            f"Expected UNTRACKED/custody mention, got: {output}"
        )
        print("✓ Shape (a) untracked: PASS")


def test_post_landing_untracked_is_red():
    """A new untracked receipt after a receipt landing is still a RED violation."""
    with tempfile.TemporaryDirectory() as tmpdir:
        receipts_dir = os.path.join(tmpdir, "receipts")
        os.makedirs(receipts_dir)

        landed = os.path.join(receipts_dir, "landed-receipt.json")
        with open(landed, "w", encoding="utf-8") as f:
            json.dump({"ticket": "TEST-LANDED", "status": "success"}, f)

        subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmpdir, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=tmpdir, capture_output=True)
        subprocess.run(["git", "add", "receipts/"], cwd=tmpdir, capture_output=True)
        subprocess.run(["git", "commit", "-m", "land receipt"], cwd=tmpdir, capture_output=True)

        silent = os.path.join(receipts_dir, "silent-after-landing.json")
        with open(silent, "w", encoding="utf-8") as f:
            json.dump({"ticket": "TEST-SILENT", "status": "success"}, f)
        landing_ts = int(subprocess.run(
            ["git", "log", "-1", "--format=%ct"],
            cwd=tmpdir, capture_output=True, text=True, check=True,
        ).stdout.strip())
        os.utime(silent, (landing_ts + 60, landing_ts + 60))

        output, _ = run_probe(tmpdir)
        assert "RED" in output, (
            "A post-landing silent untracked receipt must be RED, got: "
            f"{output}"
        )
        assert "untracked=1" in output, f"Expected untracked=1 in output, got: {output}"


def test_shape_b_unparseable():
    """Shape (b): unparseable — file with invalid JSON."""
    with tempfile.TemporaryDirectory() as tmpdir:
        receipts_dir = os.path.join(tmpdir, "receipts")
        os.makedirs(receipts_dir)

        # Create a file with invalid JSON
        receipt_file = os.path.join(receipts_dir, "truncated-corpus.json")
        with open(receipt_file, "w", encoding="utf-8") as f:
            f.write('{"ticket": "TEST-TRUNC", "ts": "20260707')  # Missing closing

        # Initialize git and track this file (so shape (a) doesn't trigger)
        subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=tmpdir,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=tmpdir,
            capture_output=True,
        )
        subprocess.run(["git", "add", "receipts/"], cwd=tmpdir, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=tmpdir,
            capture_output=True,
        )

        output, _ = run_probe(tmpdir)
        assert "RED" in output, f"Expected RED for unparseable JSON, got: {output}"
        assert "UNPARSEABLE" in output or "custody" in output.lower(), (
            f"Expected UNPARSEABLE/custody mention, got: {output}"
        )
        print("✓ Shape (b) unparseable: PASS")


def test_shape_c_cited_missing():
    """Shape (c): cited-path-missing — receipt references a missing receipt."""
    with tempfile.TemporaryDirectory() as tmpdir:
        receipts_dir = os.path.join(tmpdir, "receipts")
        os.makedirs(receipts_dir)

        # Create a receipt that cites another receipts/ path that doesn't exist
        receipt_file = os.path.join(receipts_dir, "board-with-citation.json")
        receipt_data = {
            "ticket": "TEST-CITE",
            "ts": "20260707T000000Z",
            "cited_receipt": "receipts/missing-evidence-20260707T000000Z.json",
            "status": "test",
        }
        with open(receipt_file, "w", encoding="utf-8") as f:
            json.dump(receipt_data, f)

        # Initialize git and track this file
        subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=tmpdir,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=tmpdir,
            capture_output=True,
        )
        subprocess.run(["git", "add", "receipts/"], cwd=tmpdir, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=tmpdir,
            capture_output=True,
        )

        output, _ = run_probe(tmpdir)
        assert "RED" in output, f"Expected RED for cited-missing, got: {output}"
        assert "CITED-MISSING" in output or "custody" in output.lower(), (
            f"Expected CITED-MISSING/custody mention, got: {output}"
        )
        print("✓ Shape (c) cited-missing: PASS")


def test_clean_pass():
    """Clean pass: tracked, parseable, no broken citations."""
    with tempfile.TemporaryDirectory() as tmpdir:
        receipts_dir = os.path.join(tmpdir, "receipts")
        os.makedirs(receipts_dir)

        # Create a clean, tracked, parseable receipt
        receipt_file = os.path.join(receipts_dir, "clean-receipt.json")
        receipt_data = {
            "ticket": "TEST-CLEAN",
            "ts": "20260707T000000Z",
            "status": "success",
        }
        with open(receipt_file, "w", encoding="utf-8") as f:
            json.dump(receipt_data, f)

        # Initialize git and track
        subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=tmpdir,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=tmpdir,
            capture_output=True,
        )
        subprocess.run(["git", "add", "receipts/"], cwd=tmpdir, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=tmpdir,
            capture_output=True,
        )

        output, _ = run_probe(tmpdir)
        assert "GREEN" in output, f"Expected GREEN for clean pass, got: {output}"
        assert "0 violations" in output or "custody" in output.lower(), (
            f"Expected success message, got: {output}"
        )
        print("✓ Clean pass: PASS")


def test_empty_receipts():
    """Edge case: receipts/ directory is empty or missing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create an empty git repo with an empty receipts directory.
        receipts_dir = os.path.join(tmpdir, "receipts")
        os.makedirs(receipts_dir)
        subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=tmpdir,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=tmpdir,
            capture_output=True,
        )

        # Create and commit a dummy file
        dummy = os.path.join(tmpdir, ".gitkeep")
        Path(dummy).touch()
        subprocess.run(["git", "add", ".gitkeep"], cwd=tmpdir, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=tmpdir,
            capture_output=True,
        )

        output, _ = run_probe(tmpdir)
        # Could be GREEN (empty is fine) or UNEVALUABLE (no receipts/ to check)
        assert "GREEN" in output, f"Empty receipts should be GREEN, got: {output}"
        print("✓ Empty receipts: PASS")


def main():
    print("\nC-CUSTODY TDD Test Suite")
    print("=" * 50)

    try:
        test_shape_a_untracked()
        test_post_landing_untracked_is_red()
        test_shape_b_unparseable()
        test_shape_c_cited_missing()
        test_clean_pass()
        test_empty_receipts()

        print("\n" + "=" * 50)
        print("All tests PASSED ✓")
        return 0
    except AssertionError as e:
        print(f"\nTest FAILED ✗: {e}")
        return 1
    except Exception as e:
        print(f"\nUnexpected error ✗: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
