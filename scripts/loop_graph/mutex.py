# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Resource-class mutex: at most one node of an exclusive resource_class
RUNNING at a time (default: gpu-exclusive -- the one-GPU-mutex gap item from
gap-matrix.md).

Acquisition (review-pr1310.md MAJOR-2): `os.open(path, O_CREAT | O_EXCL |
O_WRONLY)` is the primitive -- file *creation* is the atomic act of
acquisition, not a separate read-then-write. Two processes racing this call
can never both "win": the OS guarantees exactly one O_EXCL create succeeds
and every other one raises FileExistsError, so there is no window between
"lock looks free" and "I write myself as holder" for a second claimant to
land in.

Stale-reclaim (review-pr1310.md RE-REVIEW N1): a dead holder's lock is
reclaimed via `os.replace(path, tombstone)`, never a bare `path.unlink()`.
A bare unlink is read-then-unlink -- it deletes whatever currently sits at
`path` regardless of content, so two engines racing to reclaim the same
dead holder could see the faster one already win (unlink + recreate) with a
fresh, valid, live record, and the slower one's unlink then deletes THAT
valid record out from under it, with both ending up believing they hold
gpu-exclusive.

`os.replace` alone only fixes the case where the RENAME calls themselves
race (of N concurrent `os.replace(path, ...)` calls against the same
`path`, exactly one succeeds and every other one raises FileNotFoundError).
It does NOT fix a straggler: a reclaimer whose `read_json` observed the dead
holder, then paused (thread scheduling, GC, anything) while a DIFFERENT
racer fully reclaimed and recreated a live lock at `path`, then resumes and
calls `os.replace(path, tombstone)` -- at that point `path` holds the
winner's fresh live record, not the stale one the straggler read, and the
unconditional rename would remove it just as destructively as the original
bare unlink. Closing this requires content verification, not just an atomic
rename: `_reclaim_stale` is passed the exact dead record the caller
observed, and after the rename it reads the tombstone back and compares
identity (pid + creation_time) against that expected dead record. A match
means the rename really did remove the dead holder -- proceed. A mismatch
means the straggler just evicted someone else's live lock by accident; it is
restored via `os.replace(tombstone, path)` and the call reports a loss, not
a win, so the straggler falls through to re-check the (now-restored) live
holder like any other loser.

Liveness (review-pr1310.md MEDIUM-2): holder identity is PID + process
creation time (see procid.py), not a bare PID -- a bare PID is vulnerable to
reuse after the original holder dies, which would otherwise wedge the mutex
closed forever against a completely unrelated process.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import procid
from ._atomic import read_json
from .procid import is_pid_alive  # re-exported for backward compatibility

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


def _record_for(resource_class: str, node_id: str, owner_pid: int) -> dict[str, Any]:
    identity = procid.current_identity(owner_pid)
    return {
        "resource_class": resource_class,
        "node_id": node_id,
        "owner_pid": owner_pid,
        "owner_creation_time": identity["creation_time"],
        "owner_liveness_mode": identity["mode"],
        "acquired_at": _now(),
    }


def _holder_identity(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "pid": record.get("owner_pid"),
        "creation_time": record.get("owner_creation_time"),
        "mode": record.get("owner_liveness_mode", procid.MODE_PID_ONLY),
    }


def _create_exclusive(path: Path, record: dict[str, Any]) -> bool:
    """Attempt the atomic O_EXCL create. Returns True on success, False if
    something else already holds the path (FileExistsError)."""
    payload = (json.dumps(record, sort_keys=True) + "\n").encode("utf-8")
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    try:
        os.write(fd, payload)
    finally:
        os.close(fd)
    return True


def _reclaim_stale(path: Path, owner_pid: int, expected_dead: dict[str, Any]) -> bool:
    """Reclaim a dead holder's lock file via os.replace to a tombstone plus
    content verification, never a bare unlink (review-pr1310.md RE-REVIEW
    N1). `expected_dead` is the exact record the caller observed and judged
    dead -- the reclaim is only honored if that is still what actually got
    removed.

    Returns True only if THIS call both won the rename AND the content it
    moved out of the way matches `expected_dead` (the caller may now retry
    the O_EXCL create). Returns False in every other case, each of which is
    always safe to loop back on and re-check:

    - FileNotFoundError / PermissionError (WinError 32 sharing violation) on
      the rename: a concurrent reclaimer already won, or transient
      Windows handle contention -- `path` was not ours to move.
    - Content mismatch: the rename succeeded, but what it moved was NOT the
      dead record we expected -- a straggler case where a different racer
      already fully reclaimed and recreated a live lock at `path` between
      our read and our rename. The tombstoned file is restored to `path` via
      os.replace(tombstone, path) so the live holder is never lost, and this
      call reports a loss rather than a phantom win.
    """
    tombstone = path.with_name(f"{path.name}.stale.{owner_pid}.{os.getpid()}.{threading.get_ident()}")
    try:
        os.replace(path, tombstone)
    except (FileNotFoundError, PermissionError):
        return False

    try:
        moved = read_json(tombstone)
    except (OSError, ValueError):
        moved = None

    if (
        moved is not None
        and moved.get("owner_pid") == expected_dead.get("owner_pid")
        and moved.get("owner_creation_time") == expected_dead.get("owner_creation_time")
    ):
        try:
            tombstone.unlink()
        except OSError:
            pass  # best-effort cleanup only; the tombstone is never read back
        return True

    # Mismatch (or unreadable tombstone content): we evicted something other
    # than the dead record we meant to reclaim. Put it back rather than
    # silently dropping whatever it actually was -- this is exactly the
    # straggler-clobbers-a-live-winner window this function exists to close.
    try:
        os.replace(tombstone, path)
    except OSError:
        pass  # if this also fails, there is nothing more we can safely do
    return False


def acquire(locks_dir: Path, resource_class: str, node_id: str, owner_pid: int) -> bool:
    """Attempt to acquire the mutex for resource_class on behalf of node_id.

    Returns True if acquired (or the class isn't exclusive, or this node_id
    already holds it -- idempotent re-acquire). Raises MutexBusy if a
    different, still-live process holds it. A dead holder's lock is
    reclaimed automatically (PID + creation-time verified via
    procid.is_same_process_alive).
    """
    if resource_class not in EXCLUSIVE_CLASSES:
        return True

    path = lock_path(locks_dir, resource_class)
    path.parent.mkdir(parents=True, exist_ok=True)

    # Fast idempotent path: no O_EXCL race needed if we already hold it.
    if path.exists():
        try:
            current = read_json(path)
        except (OSError, ValueError):
            current = None
        if current is not None and current.get("node_id") == node_id:
            return True

    record = _record_for(resource_class, node_id, owner_pid)

    while True:
        if _create_exclusive(path, record):
            return True

        # Someone else's file exists. Read it and decide: idempotent
        # re-acquire, a live and different holder (busy), or a dead holder
        # (reclaim by unlinking and retrying the O_EXCL create).
        try:
            current = read_json(path)
        except (OSError, ValueError):
            # The holder is mid-write or the file vanished between the failed
            # create and this read -- benign transient, retry the loop.
            continue

        if current.get("node_id") == node_id:
            return True

        if procid.is_same_process_alive(_holder_identity(current)):
            raise MutexBusy(resource_class, current.get("node_id", "?"), int(current.get("owner_pid", -1)))

        # Stale holder: reclaim via os.replace to a tombstone WITH content
        # verification against `current` (RE-REVIEW N1 -- see
        # _reclaim_stale and module docstring). Whether we win or lose this
        # specific reclaim race, looping back is always safe: a win frees
        # the path for our own create; a loss (including a straggler
        # mismatch, which restores the live record) means we'll observe the
        # current true holder on the re-check.
        _reclaim_stale(path, owner_pid, current)


def release(locks_dir: Path, resource_class: str, node_id: str) -> None:
    """Release the mutex if node_id currently holds it. No-op (idempotent) if
    the class isn't exclusive, the lock doesn't exist, or a different node
    holds it -- releasing is never destructive to someone else's lock."""
    if resource_class not in EXCLUSIVE_CLASSES:
        return

    path = lock_path(locks_dir, resource_class)
    if not path.exists():
        return
    try:
        current = read_json(path)
    except (OSError, ValueError):
        return
    if current.get("node_id") != node_id:
        return
    path.unlink(missing_ok=True)


def current_holder(locks_dir: Path, resource_class: str) -> dict[str, Any] | None:
    path = lock_path(locks_dir, resource_class)
    if not path.exists():
        return None
    return read_json(path)
