# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Resource-class mutex: at most one node of an exclusive resource_class
RUNNING at a time (default: gpu-exclusive -- the one-GPU-mutex gap item from
gap-matrix.md).

A lockfile per resource_class holds {node_id, owner_pid, acquired_at}. Stale
locks (owner_pid no longer alive) are detected and reclaimed automatically --
this is the gap-matrix.md ask, generalized past the compute-specific hooks
that exist today (pretouse-cpu-cap.sh) into something any resource_class
label can opt into.
"""

from __future__ import annotations

import ctypes
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ._atomic import atomic_write_json, read_json

# Resource classes that are serialized to at most one RUNNING node at a time.
# Everything else (cpu, gpu-shared, disk-heavy, none) is unconstrained by
# this module -- resource_class is a label, not an automatic lock, per the
# sketch's explicit design note.
EXCLUSIVE_CLASSES = {"gpu-exclusive"}


class MutexError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class MutexBusy(MutexError):
    def __init__(self, resource_class: str, holder_node_id: str, holder_pid: int):
        self.resource_class = resource_class
        self.holder_node_id = holder_node_id
        self.holder_pid = holder_pid
        super().__init__(
            "MUTEX_BUSY",
            f"resource_class {resource_class!r} already held by node {holder_node_id!r} (pid {holder_pid})",
        )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def lock_path(locks_dir: Path, resource_class: str) -> Path:
    return Path(locks_dir) / f"{resource_class}.lock.json"


def is_pid_alive(pid: int) -> bool:
    """Cross-platform liveness check without shelling out or new deps."""
    if pid <= 0:
        return False
    if sys.platform == "win32":
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            STILL_ACTIVE = 259
            if not ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return False
            return exit_code.value == STILL_ACTIVE
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # process exists, just owned by someone else
    return True


def acquire(locks_dir: Path, resource_class: str, node_id: str, owner_pid: int) -> bool:
    """Attempt to acquire the mutex for resource_class on behalf of node_id.

    Returns True if acquired (or the class isn't exclusive, or this node_id
    already holds it -- idempotent re-acquire). Raises MutexBusy if a
    different, still-live node holds it. A dead holder's lock is reclaimed
    automatically (stale-lock detection).
    """
    if resource_class not in EXCLUSIVE_CLASSES:
        return True

    path = lock_path(locks_dir, resource_class)
    current = read_json(path) if path.exists() else None

    if current is not None:
        if current.get("node_id") == node_id:
            return True  # idempotent re-acquire by the same node
        if is_pid_alive(int(current.get("owner_pid", -1))):
            raise MutexBusy(resource_class, current.get("node_id", "?"), int(current.get("owner_pid", -1)))
        # holder is dead: falls through and reclaims below (stale lock).

    record: dict[str, Any] = {
        "resource_class": resource_class,
        "node_id": node_id,
        "owner_pid": owner_pid,
        "acquired_at": _now(),
    }
    atomic_write_json(path, record)
    return True


def release(locks_dir: Path, resource_class: str, node_id: str) -> None:
    """Release the mutex if node_id currently holds it. No-op (idempotent) if
    the class isn't exclusive, the lock doesn't exist, or a different node
    holds it -- releasing is never destructive to someone else's lock."""
    if resource_class not in EXCLUSIVE_CLASSES:
        return

    path = lock_path(locks_dir, resource_class)
    if not path.exists():
        return
    current = read_json(path)
    if current.get("node_id") != node_id:
        return
    path.unlink(missing_ok=True)


def current_holder(locks_dir: Path, resource_class: str) -> dict[str, Any] | None:
    path = lock_path(locks_dir, resource_class)
    if not path.exists():
        return None
    return read_json(path)
