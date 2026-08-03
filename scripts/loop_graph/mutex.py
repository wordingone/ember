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
means the rename really did remove the dead holder -- proceed.

A mismatch means the straggler just evicted someone else's live lock by
accident, and it must be put back -- but the restore step is itself a
second window, symmetric to the first: a bare `os.replace(tombstone, path)`
restore is just as content-blind as the original bug, so if a THIRD process
legitimately creates a fresh valid lock at the now-empty `path` in the gap
between the straggler's rename-out and its restore, a content-blind restore
would silently overwrite that fresh, live lock with the stale content being
put back -- destroying it exactly as destructively as the original defect,
just relocated one step later. The restore therefore uses the SAME O_EXCL
primitive the module already trusts for every other write
(`_create_exclusive`, via its shared `_create_exclusive_bytes` helper): if
something now occupies `path`, the O_EXCL create fails cleanly with
FileExistsError and the straggler fails safe -- it destroys nothing, and
the new occupant's legitimate win stands. Only if `path` is genuinely still
empty does the restore succeed, and either way the straggler reports a
loss, not a win, so it falls through to re-check the current true holder
like any other loser.

Residual window (disclosed, not closed by this fix): a straggler's evicted
record ends up stranded in an orphaned tombstone file -- never lost, but
never automatically returned to `path` either -- in two distinct cases,
neither closed by this fix:

1. Lost the restore race: the O_EXCL restore hits FileExistsError because a
   third process legitimately created a fresh lock at `path` first (the
   case _reclaim_stale's mismatch branch is built to detect). The evicted
   record's ONLY surviving copy is the tombstone, and it is deliberately
   left on disk rather than unlinked (unlinking it here would destroy that
   only copy, merely relocating the original defect one file over -- see
   `_reclaim_stale`). No crash is required for this case; it is the direct,
   expected outcome of losing that race, every time it happens.
2. Crashed mid-restore: THIS process dies between the rename-out and the
   O_EXCL restore attempt, leaving the tombstone behind with no attempt
   ever made to put it back, while the original live process (whose record
   was evicted) still believes it holds the mutex and `path` sits empty in
   the meantime.

In both cases the orphaned `*.stale.<owner_pid>.<pid>.<ident>` tombstone
file at `locks_dir` is the recovery artifact: it holds the exact evicted
record, is never overwritten or reused (each reclaim attempt mints its own
uniquely-named tombstone), and is safe to restore to `path` by hand or by
an automated scan once nothing legitimately occupies `path`. Building that
scan is out of scope for this fix -- no rename-based primitive can make the
rename-out and the restore atomic with each other, so some window between
them, and some accumulation of orphaned tombstones on the losing side,
is inherent to this design.

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


def _create_exclusive_bytes(path: Path, payload: bytes) -> bool:
    """Attempt the atomic O_EXCL create with raw bytes. Returns True on
    success, False if something else already holds the path
    (FileExistsError) -- the shared primitive behind both a fresh acquire
    (_create_exclusive) and a content-safe stale-lock restore
    (_reclaim_stale), so a restore can never silently clobber a legitimate
    fresh occupant the same way a bare unlink/replace would."""
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    try:
        os.write(fd, payload)
    finally:
        os.close(fd)
    return True


def _create_exclusive(path: Path, record: dict[str, Any]) -> bool:
    """Attempt the atomic O_EXCL create. Returns True on success, False if
    something else already holds the path (FileExistsError)."""
    payload = (json.dumps(record, sort_keys=True) + "\n").encode("utf-8")
    return _create_exclusive_bytes(path, payload)


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
      our read and our rename. The evicted content is restored to `path` via
      an O_EXCL create (see module docstring for why -- a bare
      os.replace(tombstone, path) restore would itself be content-blind and
      could clobber a THIRD process's legitimate fresh lock). If the O_EXCL
      restore fails because something now occupies `path`, that occupant's
      win stands and we destroy nothing at `path` -- but the tombstone is
      the ONLY surviving copy of the record we evicted, so it is left on
      disk as a named orphan rather than unlinked; unlinking it here would
      just relocate the destruction one file over (see module docstring).
      Either way this call reports a loss, never a phantom win.
    """
    tombstone = path.with_name(f"{path.name}.stale.{owner_pid}.{os.getpid()}.{threading.get_ident()}")
    try:
        os.replace(path, tombstone)
    except (FileNotFoundError, PermissionError):
        return False

    try:
        raw = tombstone.read_bytes()
        moved = json.loads(raw)
    except (OSError, ValueError):
        raw = None
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
    # than the dead record we meant to reclaim. Put the exact original bytes
    # back via O_EXCL -- never a bare replace, which would silently clobber
    # a third process's legitimate fresh lock if one raced in during the
    # eviction. FileExistsError here means exactly that happened: someone
    # else already legitimately holds `path` now, so we must NOT overwrite
    # it -- fail safe, destroy nothing at `path`.
    #
    # Unlink the tombstone ONLY when the restore actually succeeded. The
    # tombstone is the sole surviving copy of whatever we evicted; if the
    # restore lost (raw was None -- unreadable -- or the O_EXCL create hit
    # FileExistsError), unconditionally unlinking it here would destroy
    # that only copy just as permanently as the original defect, merely
    # relocated to this file. Leave it on disk as a named orphan instead --
    # exactly the artifact the disclosed future orphan-scan recovery pass
    # is meant to find and restore.
    restored = raw is not None and _create_exclusive_bytes(path, raw)
    if restored:
        try:
            tombstone.unlink()
        except OSError:
            pass
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
