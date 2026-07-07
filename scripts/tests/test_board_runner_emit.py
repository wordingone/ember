#!/usr/bin/env python3
"""Test board runner emit side — demonstrates fixture events (unmistakably synthetic).

Fixture events use actor='fixture-runner' to distinguish from real board-runner output.
"""

import json
import tempfile
import os
from pathlib import Path
from datetime import datetime, timezone

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from activity_log import emit


def test_board_runner_emits_events():
    """Simulate board runner emitting start/verdict/end events (FIXTURE, not real)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        orig_cwd = os.getcwd()
        try:
            os.chdir(tmpdir)
            
            # Simulate board runner start (FIXTURE: actor='fixture-runner')
            emit("fixture-runner", "status", "Starting totality evaluation")
            
            # Simulate evaluating several conditions (FIXTURE: synthetic verdicts)
            # Using real condition names for demo, but actor='fixture-runner' marks as fixture
            conditions = [
                ("C-BASE", "green", "Base inference pipeline passed all tests"),
                ("C-GROW", "green", "Growth metrics within target range"),
                ("C8", "red", "C8 creative synthesis check failed: diversity < 0.7"),
                ("C-SCALE", "green", "Scaled to 150k context successfully"),
                ("C-IND", "green", "Independence audit passed"),
            ]
            
            for cid, status, detail in conditions:
                kind = "error" if status == "red" else "output"
                emit("fixture-runner", kind, f"{cid}: {status.upper()}", body=detail)
            
            # Simulate board runner end
            emit("fixture-runner", "status", "Evaluation complete — 4 green, 1 red")
            
            # Read and verify
            date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
            log_file = Path(tmpdir) / "state" / "activity" / f"activity-{date_str}.jsonl"
            
            lines = log_file.read_text().strip().split("\n")
            events = [json.loads(line) for line in lines]
            
            assert len(events) == 7, f"Expected 7 events, got {len(events)}"
            assert events[0]["title"] == "Starting totality evaluation"
            assert events[-1]["title"] == "Evaluation complete — 4 green, 1 red"
            
            # Verify all events marked as fixture (actor='fixture-runner')
            for event in events:
                assert event["actor"] == "fixture-runner", f"Event not marked as fixture: {event}"
            
            # Print sample for receipt
            print("\n[SAMPLE] Fixture board runner activity events (actor='fixture-runner'):")
            print("-" * 80)
            for event in events[:3]:
                print(json.dumps(event))
            print("... (4 more events)")
            print("-" * 80)
            print(f"[PASS] Fixture events emitted {len(events)} events (all marked fixture-runner)")
        finally:
            os.chdir(orig_cwd)


if __name__ == "__main__":
    test_board_runner_emits_events()
