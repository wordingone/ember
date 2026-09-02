#!/usr/bin/env python3
"""Tests for activity pane renderer."""

import json
import tempfile
import os
from pathlib import Path
from datetime import datetime, timezone, timedelta


def format_activity_pane(events: list, cols: int = 80) -> str:
    """Format activity events for display (fixture test target).

    Args:
        events: List of activity event dicts
        cols: Terminal width in columns

    Returns:
        Formatted pane text
    """
    if not events:
        now = datetime.now(timezone.utc)
        return f"organism quiet -- no live activity"

    lines = []
    now = datetime.now(timezone.utc)

    for event in events:
        ts = datetime.fromisoformat(event["ts"])
        delta = now - ts
        if delta.total_seconds() < 60:
            rel_time = "now"
        elif delta.total_seconds() < 3600:
            rel_time = f"{int(delta.total_seconds() / 60)}m ago"
        else:
            rel_time = f"{int(delta.total_seconds() / 3600)}h ago"

        kind_glyph = {
            "tool_use": "[*]",
            "reasoning": "[R]",
            "output": "[O]",
            "status": "[S]",
            "error": "[E]",
        }.get(event["kind"], "[?]")

        actor = event["actor"]
        title = event["title"]

        # Truncate to fit cols
        max_width = cols - len(f"{rel_time} {kind_glyph} {actor}: ")
        if len(title) > max_width:
            title = title[:max_width - 3] + "..."

        line = f"{rel_time} {kind_glyph} {actor}: {title}"
        lines.append(line)

    return "\n".join(lines)


def test_render_empty_state():
    """Test: empty state renders 'organism quiet'."""
    output = format_activity_pane([])
    assert "organism quiet" in output
    print("[PASS] Empty state test passed")


def test_render_single_event():
    """Test: single event renders with relative time, glyph, actor, title."""
    now = datetime.now(timezone.utc)
    events = [
        {
            "ts": now.isoformat(),
            "actor": "board-runner",
            "kind": "status",
            "title": "Starting totality check",
        }
    ]
    output = format_activity_pane(events)
    assert "now" in output
    assert "[S]" in output  # status glyph
    assert "board-runner" in output
    assert "Starting totality check" in output
    print("[PASS] Single event test passed")


def test_render_relative_times():
    """Test: relative times format correctly."""
    now = datetime.now(timezone.utc)
    events = [
        {"ts": (now - timedelta(seconds=30)).isoformat(), "actor": "a", "kind": "status", "title": "30s"},
        {"ts": (now - timedelta(minutes=5)).isoformat(), "actor": "a", "kind": "status", "title": "5m"},
        {"ts": (now - timedelta(hours=2)).isoformat(), "actor": "a", "kind": "status", "title": "2h"},
    ]
    output = format_activity_pane(events)
    assert "now" in output
    assert "5m ago" in output
    assert "2h ago" in output
    print("[PASS] Relative times test passed")


def test_render_resize_safe():
    """Test: output truncates to column width."""
    now = datetime.now(timezone.utc)
    events = [
        {
            "ts": now.isoformat(),
            "actor": "board-runner",
            "kind": "status",
            "title": "This is a very long title that should be truncated when the terminal is narrow",
        }
    ]
    output = format_activity_pane(events, cols=40)
    assert len(output.split("\n")[0]) <= 40
    print("[PASS] Resize-safe test passed")


def test_render_fixture():
    """Test: planted JSONL renders expected output."""
    with tempfile.TemporaryDirectory() as tmpdir:
        log_file = Path(tmpdir) / "activity-20260707.jsonl"

        now = datetime.now(timezone.utc)
        events = [
            {
                "ts": now.isoformat(),
                "actor": "board-runner",
                "kind": "status",
                "title": "Starting condition evaluation",
            },
            {
                "ts": (now + timedelta(seconds=1)).isoformat(),
                "actor": "board-runner",
                "kind": "tool_use",
                "title": "Ran ember totality check",
                "body": "Evaluated 42 conditions",
            },
            {
                "ts": (now + timedelta(seconds=2)).isoformat(),
                "actor": "board-runner",
                "kind": "status",
                "title": "Evaluation complete - 41 green, 1 red",
            },
        ]

        # Write fixture
        log_file.write_text("\n".join(json.dumps(e) for e in events) + "\n")

        # Read and render
        lines = log_file.read_text().strip().split("\n")
        parsed_events = [json.loads(line) for line in lines]
        output = format_activity_pane(parsed_events, cols=100)

        # Verify
        assert "board-runner" in output
        assert "Starting condition evaluation" in output
        assert "Evaluation complete" in output
        assert output.count("\n") == 2  # 3 events = 2 newlines
        print("[PASS] Fixture test passed")


if __name__ == "__main__":
    test_render_empty_state()
    test_render_single_event()
    test_render_relative_times()
    test_render_resize_safe()
    test_render_fixture()
    print("\n[PASS] All renderer tests passed")
