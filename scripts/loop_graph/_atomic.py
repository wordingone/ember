# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Shared atomic file primitives for the loop/graph substrate.

atomic_write_json: write to a per-process temp file in the same directory,
fsync, then os.replace onto the target. os.replace is atomic on both POSIX
and Windows (NTFS), so a reader never observes a partially-written file, and
a crash mid-write leaves only an orphaned .tmp file behind -- never a
corrupted target. Same pattern as scripts/worktree_lifecycle.py's write_state.

ExclusiveLock + atomic_append_jsonl: review-pr1310.md MAJOR-1. The prior
version of atomic_append_jsonl was read-modify-replace, which is crash-safe
but NOT append-safe under concurrency -- two processes appending at once both
read the same base file, and whichever os.replace lands second silently
drops the other's row. ExclusiveLock is a real cross-process/cross-thread
mutual-exclusion primitive (msvcrt.locking on Windows, fcntl.flock on POSIX
-- same lock mechanism as worktree_lifecycle.py's RepositoryLock, but
blocking instead of fail-fast, since appenders should queue rather than
error out). Appends are serialized under this lock and use a real `open(...,
"a")`, so concurrent appends from multiple processes are true appends: every
row from every writer survives, in some serialized order.
"""

from __future__ import annotations

import json
import os
import sys
import time
from contextlib import AbstractContextManager
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


class ExclusiveLock(AbstractContextManager["ExclusiveLock"]):
    """Blocking cross-process/cross-thread exclusive lock on a sidecar file.

    Unlike scripts/worktree_lifecycle.py's RepositoryLock (fail-fast, one
    repo-wide lock), this blocks until acquired -- callers here (concurrent
    appenders, concurrent claimants) are expected to queue, not fail.
    """

    def __init__(self, path: Path):
        self.path = Path(path)
        self.handle: Any = None

    def __enter__(self) -> "ExclusiveLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+b")
        self.handle.seek(0, os.SEEK_END)
        if self.handle.tell() == 0:
            self.handle.write(b"0")
            self.handle.flush()
        self.handle.seek(0)
        if sys.platform == "win32":
            import msvcrt

            while True:
                try:
                    msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    time.sleep(0.005)
        else:
            import fcntl

            fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX)  # blocking
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        if self.handle is None:
            return
        self.handle.seek(0)
        if sys.platform == "win32":
            import msvcrt

            msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        self.handle.close()
        self.handle = None


def lock_sidecar(path: Path) -> Path:
    return path.with_name(f"{path.name}.lock")


def atomic_append_jsonl(path: Path, row: Any) -> None:
    """Append one JSON row to a JSONL file. True append (open "a"), serialized
    across processes/threads by an ExclusiveLock held on a sidecar .lock
    file -- so concurrent appenders queue instead of racing a read-modify-
    replace. Each writer's line is flushed and fsynced before releasing the
    lock, so a crash mid-write can only ever leave the *last* line torn, and
    read_jsonl tolerates exactly that (see below) -- it never loses an
    already-committed row.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with ExclusiveLock(lock_sidecar(path)):
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(row, sort_keys=True))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())


def read_jsonl(path: Path) -> list[Any]:
    """Read every row of a JSONL file. Tolerates a torn FINAL line (the one
    possible artifact of a crash mid-append under atomic_append_jsonl) by
    skipping it rather than raising -- a torn line can only ever be the last
    one, since every completed append is a whole flushed+fsynced line
    written under an exclusive lock. A torn line anywhere else indicates
    real corruption and is raised."""
    if not path.exists():
        return []
    rows: list[Any] = []
    lines = path.read_text(encoding="utf-8").splitlines()
    last_index = len(lines) - 1
    for index, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            if index == last_index:
                continue  # tolerated: a torn final line from a crash mid-append
            raise
    return rows


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))
