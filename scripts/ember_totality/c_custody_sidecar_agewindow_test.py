#!/usr/bin/env python3
"""c_custody_sidecar_agewindow_test.py -- Tests for sidecar + age-window classification (issue #401).

Verifies:
  (a) Sidecar JSON file written with full offender enumeration on every run
  (b) Fresh-mtime untracked file (newer than last landing) classifies as pending_landing
  (c) Old untracked file (older than last landing) remains a violation
  (d) cited_missing violations remain regardless of age
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


def _run_custody_probe(repo_root: Path) -> tuple[str, int]:
    """Run test_c_custody.py, return (stdout, exit_code)."""
    script = repo_root / "scripts" / "ember_totality" / "test_c_custody.py"
    if not script.exists():
        return f"Script {script} not found", 1

    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, "EMBER_TOTALITY_ROOT": str(repo_root)},
    )
    return result.stdout.strip(), result.returncode


def _init_git_repo(repo_root: Path):
    """Initialize a minimal git repo."""
    subprocess.run(["git", "init"], cwd=str(repo_root), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(repo_root), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=str(repo_root), capture_output=True, check=True)


def _git_add_and_commit(repo_root: Path, message: str):
    """Stage all changes and commit."""
    subprocess.run(["git", "add", "-A"], cwd=str(repo_root), capture_output=True, check=True)
    result = subprocess.run(
        ["git", "commit", "-m", message],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def test_sidecar_written_on_red():
    """Verify sidecar JSON file is written when probe detects violations."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir) / "test_repo"
        repo.mkdir()

        # Initialize minimal git repo
        _init_git_repo(repo)

        # Create receipts/ directory and commit (empty initial state)
        receipts_dir = repo / "receipts"
        receipts_dir.mkdir()
        gitkeep = receipts_dir / ".gitkeep"
        gitkeep.write_text("")
        _git_add_and_commit(repo, "Initial commit with receipts/")

        # Create scripts/ember_totality/ structure and copy probe
        scripts_dir = repo / "scripts" / "ember_totality"
        scripts_dir.mkdir(parents=True, exist_ok=True)
        probe_src = REPO_ROOT / "scripts" / "ember_totality" / "test_c_custody.py"
        probe_dst = scripts_dir / "test_c_custody.py"
        shutil.copy(probe_src, probe_dst)

        # Get the last landing timestamp
        last_landing_output = subprocess.run(
            ["git", "log", "-1", "--format=%ct"],
            cwd=str(repo),
            capture_output=True,
            text=True,
        )
        last_landing_ts = int(last_landing_output.stdout.strip())

        # NOW create an untracked file with OLD mtime (older than last landing, causes RED)
        untracked_file = receipts_dir / "old_untracked.json"
        untracked_file.write_text(json.dumps({"untracked": "data"}))
        # Set mtime to be older than last_landing
        old_mtime = last_landing_ts - 100
        os.utime(untracked_file, (old_mtime, old_mtime))

        # Run probe
        output, exit_code = _run_custody_probe(repo)
        assert "RED" in output, f"Expected RED in output, got: {output}"

        # Verify sidecar directory created
        sidecar_dir = repo / "scripts" / "ember_totality" / "receipts-custody"
        assert sidecar_dir.exists(), f"Sidecar directory not created: {sidecar_dir}"

        # Verify at least one custody JSON file exists
        sidecar_files = list(sidecar_dir.glob("custody-*.json"))
        assert len(sidecar_files) > 0, f"No custody sidecar files found in {sidecar_dir}"

        # Verify sidecar contains offender lists
        sidecar_data = json.loads(sidecar_files[0].read_text())
        assert "offenders" in sidecar_data, "Sidecar missing 'offenders' key"
        assert "untracked" in sidecar_data["offenders"], "Sidecar missing 'untracked' in offenders"
        assert len(sidecar_data["offenders"]["untracked"]) > 0, "Expected untracked offenders in sidecar"

        print(f"PASS: Sidecar written on RED: {sidecar_files[0].name}")
        print(f"  Offenders: {sidecar_data['offenders']}")


def test_sidecar_written_on_green():
    """Verify sidecar JSON file is written even on GREEN (zero-violation case)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir) / "test_repo"
        repo.mkdir()

        # Initialize git repo
        _init_git_repo(repo)

        # Create receipts/ with a tracked file
        receipts_dir = repo / "receipts"
        receipts_dir.mkdir()
        tracked_file = receipts_dir / "test.json"
        tracked_file.write_text(json.dumps({"test": "data"}))

        # Commit the file (tracked)
        _git_add_and_commit(repo, "Add tracked receipt")

        # Create scripts/ember_totality/ and copy probe
        scripts_dir = repo / "scripts" / "ember_totality"
        scripts_dir.mkdir(parents=True, exist_ok=True)
        probe_src = REPO_ROOT / "scripts" / "ember_totality" / "test_c_custody.py"
        probe_dst = scripts_dir / "test_c_custody.py"
        shutil.copy(probe_src, probe_dst)

        # Run probe
        output, exit_code = _run_custody_probe(repo)
        assert "GREEN" in output, f"Expected GREEN in output, got: {output}"

        # Verify sidecar written even on GREEN
        sidecar_dir = repo / "scripts" / "ember_totality" / "receipts-custody"
        sidecar_files = list(sidecar_dir.glob("custody-*.json"))
        assert len(sidecar_files) > 0, f"No custody sidecar files found on GREEN: {sidecar_dir}"

        sidecar_data = json.loads(sidecar_files[0].read_text())
        assert sidecar_data["failure_count"] == 0, "Expected zero failures on GREEN"
        assert sidecar_data["pending_landing_count"] == 0, "Expected zero pending_landing on GREEN"

        print(f"PASS: Sidecar written on GREEN: {sidecar_files[0].name}")


def test_pending_landing_classification():
    """Verify untracked files newer than last landing are classified as pending_landing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir) / "test_repo"
        repo.mkdir()

        # Initialize git repo
        _init_git_repo(repo)

        # Create initial receipts/ with tracked file and commit
        receipts_dir = repo / "receipts"
        receipts_dir.mkdir()
        tracked_file = receipts_dir / "old.json"
        tracked_file.write_text(json.dumps({"old": "data"}))
        _git_add_and_commit(repo, "Initial tracked receipt")

        # Record this as our last_landing time
        last_landing_output = subprocess.run(
            ["git", "log", "-1", "--format=%ct"],
            cwd=str(repo),
            capture_output=True,
            text=True,
        )
        last_landing_ts = int(last_landing_output.stdout.strip())

        # Wait and create a fresh untracked file (newer than last_landing)
        time.sleep(2)
        fresh_untracked = receipts_dir / "fresh_untracked.json"
        fresh_untracked.write_text(json.dumps({"fresh": "untracked"}))

        # Create old untracked file with old mtime (older than last_landing)
        old_untracked = receipts_dir / "old_untracked.json"
        old_untracked.write_text(json.dumps({"old": "untracked"}))
        # Set mtime to before last_landing
        old_mtime = last_landing_ts - 100
        os.utime(old_untracked, (old_mtime, old_mtime))

        # Create scripts/ember_totality/ and copy probe
        scripts_dir = repo / "scripts" / "ember_totality"
        scripts_dir.mkdir(parents=True, exist_ok=True)
        probe_src = REPO_ROOT / "scripts" / "ember_totality" / "test_c_custody.py"
        probe_dst = scripts_dir / "test_c_custody.py"
        shutil.copy(probe_src, probe_dst)

        # Run probe
        output, exit_code = _run_custody_probe(repo)
        assert "RED" in output, f"Expected RED (old_untracked), got: {output}"

        # Verify sidecar
        sidecar_dir = repo / "scripts" / "ember_totality" / "receipts-custody"
        sidecar_files = list(sidecar_dir.glob("custody-*.json"))
        assert len(sidecar_files) > 0, f"No sidecar files found"

        sidecar_data = json.loads(sidecar_files[0].read_text())

        # old_untracked should be in failures (it's older than last_landing)
        untracked_failures = sidecar_data["offenders"]["untracked"]
        assert any("old_untracked" in f for f in untracked_failures), \
            f"Expected old_untracked in failures, got: {untracked_failures}"

        # fresh_untracked should be in pending_landing (it's newer than last_landing)
        pending = sidecar_data["pending_landing"]
        assert any("fresh_untracked" in p for p in pending), \
            f"Expected fresh_untracked in pending_landing, got: {pending}"

        assert sidecar_data["pending_landing_count"] > 0, "Expected pending_landing_count > 0"

        print(f"PASS: Pending-landing classification works:")
        print(f"  Old untracked (violation): {[f for f in untracked_failures if 'old_untracked' in f]}")
        print(f"  Fresh untracked (pending_landing): {[p for p in pending if 'fresh_untracked' in p]}")


def test_cited_missing_always_violation():
    """Verify cited_missing violations always cause RED regardless of age."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir) / "test_repo"
        repo.mkdir()

        # Initialize git repo
        _init_git_repo(repo)

        # Create receipts/ with a file that cites a missing path
        receipts_dir = repo / "receipts"
        receipts_dir.mkdir()
        citing_file = receipts_dir / "citing.json"
        citing_file.write_text(json.dumps({
            "citation": "receipts/missing.json"
        }))
        _git_add_and_commit(repo, "Add citing receipt")

        # Create scripts/ember_totality/ and copy probe
        scripts_dir = repo / "scripts" / "ember_totality"
        scripts_dir.mkdir(parents=True, exist_ok=True)
        probe_src = REPO_ROOT / "scripts" / "ember_totality" / "test_c_custody.py"
        probe_dst = scripts_dir / "test_c_custody.py"
        shutil.copy(probe_src, probe_dst)

        # Run probe
        output, exit_code = _run_custody_probe(repo)
        assert "RED" in output, f"Expected RED (cited_missing), got: {output}"
        assert "cited_missing" in output, f"Expected 'cited_missing' in output"

        # Verify sidecar contains the missing citation
        sidecar_dir = repo / "scripts" / "ember_totality" / "receipts-custody"
        sidecar_files = list(sidecar_dir.glob("custody-*.json"))
        sidecar_data = json.loads(sidecar_files[0].read_text())

        cited_missing = sidecar_data["offenders"]["cited_missing"]
        assert len(cited_missing) > 0, f"Expected cited_missing offenders"
        assert any("missing.json" in c for c in cited_missing), f"Expected missing.json in cited_missing"

        print(f"PASS: Cited-missing violations always cause RED: {cited_missing}")


if __name__ == "__main__":
    test_sidecar_written_on_red()
    test_sidecar_written_on_green()
    test_pending_landing_classification()
    test_cited_missing_always_violation()
    print("\nPASS: All tests passed")
