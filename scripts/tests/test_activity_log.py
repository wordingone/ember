#!/usr/bin/env python3
"""Tests for activity_log emit side."""

import json
import tempfile
import subprocess
import os
from pathlib import Path
from datetime import datetime, timezone

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from activity_log import emit


def test_writer_basic_emit():
    """Test: basic emit creates valid JSONL."""
    with tempfile.TemporaryDirectory() as tmpdir:
        orig_cwd = os.getcwd()
        try:
            os.chdir(tmpdir)
            Path("state/activity").mkdir(parents=True, exist_ok=True)

            emit("test-actor", "status", "Test event", body="Test body", run_id="run-123")

            date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
            log_file = Path(tmpdir) / "state" / "activity" / f"activity-{date_str}.jsonl"

            assert log_file.exists()
            lines = log_file.read_text().strip().split("\n")
            assert len(lines) == 1

            event = json.loads(lines[0])
            assert event["actor"] == "test-actor"
            assert event["kind"] == "status"
            assert event["title"] == "Test event"
            assert event["body"] == "Test body"
            assert event["run_id"] == "run-123"

            print("[PASS] Basic emit test passed")
        finally:
            os.chdir(orig_cwd)


def test_writer_body_truncation():
    """Test: body longer than 2KB is truncated."""
    with tempfile.TemporaryDirectory() as tmpdir:
        orig_cwd = os.getcwd()
        try:
            os.chdir(tmpdir)
            Path("state/activity").mkdir(parents=True, exist_ok=True)

            long_body = "x" * 3000
            emit("test", "status", "title", body=long_body)

            date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
            log_file = Path(tmpdir) / "state" / "activity" / f"activity-{date_str}.jsonl"

            event = json.loads(log_file.read_text().strip())
            assert len(event["body"]) == 2048, f"Body length is {len(event['body'])}, expected 2048"

            print("[PASS] Body truncation test passed")
        finally:
            os.chdir(orig_cwd)


def test_writer_concurrent_appends():
    """Test: concurrent appends from 2 processes produce no interleaved corruption."""
    with tempfile.TemporaryDirectory() as tmpdir:
        orig_cwd = os.getcwd()
        try:
            os.chdir(tmpdir)
            Path("state/activity").mkdir(parents=True, exist_ok=True)

            # Process 1: emit 5 events
            script1 = f"""
import sys
sys.path.insert(0, '{Path(__file__).parent.parent / "lib"}')
from activity_log import emit
for i in range(5):
    emit("proc1", "status", f"event {{i}}")
"""

            # Process 2: emit 5 events
            script2 = f"""
import sys
sys.path.insert(0, '{Path(__file__).parent.parent / "lib"}')
from activity_log import emit
for i in range(5):
    emit("proc2", "status", f"event {{i}}")
"""

            # Run both concurrently
            p1 = subprocess.Popen([sys.executable, "-c", script1], cwd=tmpdir)
            p2 = subprocess.Popen([sys.executable, "-c", script2], cwd=tmpdir)
            p1.wait()
            p2.wait()

            # Read the log and verify no corruption
            date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
            log_file = Path(tmpdir) / "state" / "activity" / f"activity-{date_str}.jsonl"

            assert log_file.exists(), "Activity log file was not created"

            lines = log_file.read_text().strip().split("\n")
            assert len(lines) == 10, f"Expected 10 events, got {len(lines)}"

            # Each line must be valid JSON
            events = []
            for line in lines:
                try:
                    event = json.loads(line)
                    events.append(event)
                except json.JSONDecodeError as e:
                    raise AssertionError(f"Malformed JSON in log: {line!r}") from e

            # Verify no partial writes or interleaving
            for i, event in enumerate(events):
                assert "ts" in event, f"Event {i} missing ts"
                assert "actor" in event, f"Event {i} missing actor"
                assert "kind" in event, f"Event {i} missing kind"
                assert "title" in event, f"Event {i} missing title"
                assert event["actor"] in ("proc1", "proc2"), f"Event {i} has unexpected actor"

            print(f"[PASS] Concurrent append test passed: {len(events)} events, no corruption")
        finally:
            os.chdir(orig_cwd)


if __name__ == "__main__":
    test_writer_basic_emit()
    test_writer_body_truncation()
    test_writer_concurrent_appends()
    print("\n[PASS] All writer tests passed")
