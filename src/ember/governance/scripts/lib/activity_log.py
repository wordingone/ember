#!/usr/bin/env python3
"""Activity event logger — append-only, multi-process safe on Windows."""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def emit(
    actor: str,
    kind: str,
    title: str,
    body: str = "",
    run_id: str = "",
) -> None:
    """Emit a single activity event (append-only, crash-safe).

    Args:
        actor: Process name (e.g., "board-runner", "decontam-scan")
        kind: Event type — "tool_use", "reasoning", "output", "status", or "error"
        title: One-line summary
        body: Optional detail (capped 2KB)
        run_id: Optional reference to a larger operation

    Windows append mode + single-line writes <4KB are atomic.
    """
    if not actor or not kind or not title:
        raise ValueError("actor, kind, and title are required")

    if kind not in ("tool_use", "reasoning", "output", "status", "error"):
        raise ValueError(f"kind must be one of tool_use/reasoning/output/status/error, got {kind}")

    # Truncate body to 2KB
    if body and len(body) > 2048:
        body = body[:2048]

    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y%m%d")

    # Create state/activity/ if it doesn't exist
    log_dir = Path("state/activity")
    log_dir.mkdir(parents=True, exist_ok=True)

    log_file = log_dir / f"activity-{date_str}.jsonl"

    event = {
        "ts": now.isoformat(),
        "actor": actor,
        "kind": kind,
        "title": title,
    }

    if body:
        event["body"] = body

    if run_id:
        event["run_id"] = run_id

    # Open-append-close per call: crash-safe on Windows
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(event) + "\n")
