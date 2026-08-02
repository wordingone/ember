# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Shared atomic file primitives for the loop/graph substrate.

Same pattern as scripts/worktree_lifecycle.py's write_state: write to a
per-process temp file in the same directory, fsync, then os.replace onto
the target. os.replace is atomic on both POSIX and Windows (NTFS), so a
reader never observes a partially-written file, and a crash mid-write
leaves only an orphaned .tmp file behind -- never a corrupted target.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def atomic_write_json(path: Path, payload: Any) -> None:
    """Write JSON atomically via temp-file + os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    data = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_append_jsonl(path: Path, row: Any) -> None:
    """Append one JSON row to a JSONL file, atomically with respect to crashes.

    A plain open(..., "a").write() can leave a torn line if the process dies
    mid-write. This instead rewrites the whole file (existing lines + the new
    row) into a temp file and os.replace's it in -- more I/O per append, but
    the file is only ever seen whole or not-at-all, matching the atomic-write
    discipline used everywhere else in this substrate. Receipt volumes here
    (thousands of rows) make the extra I/O cheap relative to the correctness
    guarantee.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = read_jsonl(path)
    existing.append(row)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            for item in existing:
                handle.write(json.dumps(item, sort_keys=True))
                handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def read_jsonl(path: Path) -> list[Any]:
    if not path.exists():
        return []
    rows: list[Any] = []
    text = path.read_text(encoding="utf-8")
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))
