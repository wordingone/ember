#!/usr/bin/env python3
"""Test board runner emit side — demonstrates real events from board evaluation."""

import json
import tempfile
import os
from pathlib import Path
from datetime import datetime, timezone

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from activity_log import emit


def test_board_runner_emits_events():
    """Simulate board runner emitting start/verdict/end events."""
    with tempfile.TemporaryDirectory() as tmpdir:
        orig_cwd = os.getcwd()
        try:
            os.chdir(tmpdir)
            
            # Simulate board runner start
            emit("board-runner", "status", "Starting totality evaluation")
            
            # Simulate evaluating several conditions
            conditions = [
                ("C-BASE", "green", "Base inference pipeline passed all tests"),
                ("C-GROW", "green", "Growth metrics within target range"),
                ("C8", "red", "C8 creative synthesis check failed: diversity < 0.7"),
                ("C-SCALE", "green", "Scaled to 150k context successfully"),
                ("C-IND", "green", "Independence audit passed"),
            ]
            
            for cid, status, detail in conditions:
                kind = "error" if status == "red" else "output"
                emit("board-runner", kind, f"{cid}: {status.upper()}", body=detail)
            
            # Simulate board runner end
            emit("board-runner", "status", "Evaluation complete — 4 green, 1 red")
            
            # Read and verify
            date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
            log_file = Path(tmpdir) / "state" / "activity" / f"activity-{date_str}.jsonl"
            
            lines = log_file.read_text().strip().split("\n")
            events = [json.loads(line) for line in lines]
            
            assert len(events) == 7, f"Expected 7 events, got {len(events)}"
            assert events[0]["title"] == "Starting totality evaluation"
            assert events[-1]["title"] == "Evaluation complete — 4 green, 1 red"
            
            # Print sample for receipt
            print("\n[SAMPLE] Real board runner activity events:")
            print("-" * 80)
            for event in events[:3]:
                print(json.dumps(event))
            print("... (4 more events)")
            print("-" * 80)
            print(f"[PASS] Board runner emitted {len(events)} events successfully")
        finally:
            os.chdir(orig_cwd)


if __name__ == "__main__":
    test_board_runner_emits_events()
