# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Execution-node state machine: create -> claim -> start -> (request_review) -> close.

States (from schemas/loop-graph/execution-graph-v1.schema.json):
    PENDING -> RUNNING -> AWAITING_REVIEW -> CLOSED_PASS | CLOSED_FLAT | CLOSED_REJECTED
    RUNNING may also close directly (no review stage required).

Crash/resume safety: every transition is written via _atomic.atomic_write_json
(temp-file + os.replace), so a node file is always either fully the old state
or fully the new state -- never torn. Resuming after a crash means: read the
node back, see which state actually landed, and re-issue whichever transition
call you were about to make. Each transition function is idempotent when the
node is already in its target (post-transition) state, so a blind retry after
a crash is always safe and never double-applies or corrupts.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ._atomic import atomic_write_json, read_json

PENDING = "PENDING"
RUNNING = "RUNNING"
AWAITING_REVIEW = "AWAITING_REVIEW"
CLOSED_PASS = "CLOSED_PASS"
CLOSED_FLAT = "CLOSED_FLAT"
CLOSED_REJECTED = "CLOSED_REJECTED"
CLOSED_STATES = {CLOSED_PASS, CLOSED_FLAT, CLOSED_REJECTED}


class LifecycleError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def node_path(store_dir: Path, node_id: str) -> Path:
    return Path(store_dir) / f"{node_id}.json"


def load_node(store_dir: Path, node_id: str) -> dict[str, Any]:
    path = node_path(store_dir, node_id)
    if not path.exists():
        raise LifecycleError("NODE_NOT_FOUND", f"no node file for {node_id!r} at {path}")
    return read_json(path)


def try_load_node(store_dir: Path, node_id: str) -> dict[str, Any] | None:
    path = node_path(store_dir, node_id)
    if not path.exists():
        return None
    return read_json(path)


def create(store_dir: Path, node: dict[str, Any]) -> dict[str, Any]:
    """Create a new execution node in PENDING state. Idempotent: creating a
    node_id that already exists returns the existing record unchanged rather
    than erroring or overwriting it (a re-run of the same "create" call after
    a crash must never clobber progress a prior run already made)."""
    node_id = node.get("node_id")
    if not node_id:
        raise LifecycleError("INVALID_NODE", "node is missing node_id")

    existing = try_load_node(store_dir, node_id)
    if existing is not None:
        return existing

    record = dict(node)
    record.setdefault("state", PENDING)
    record.setdefault("created_at", _now())
    if record["state"] != PENDING:
        raise LifecycleError("INVALID_NODE", "a newly created node must start PENDING")

    atomic_write_json(node_path(store_dir, node_id), record)
    return record


def claim(store_dir: Path, node_id: str, owner: str) -> dict[str, Any]:
    """Assign an owner to a PENDING node without starting it. Idempotent when
    the same owner re-claims; refuses (does not silently steal) a node
    already claimed by a different owner or already past PENDING."""
    record = load_node(store_dir, node_id)

    if record["state"] == PENDING and record.get("owner") in (None, owner):
        if record.get("owner") == owner:
            return record
        record = dict(record)
        record["owner"] = owner
        atomic_write_json(node_path(store_dir, node_id), record)
        return record

    if record["state"] != PENDING:
        raise LifecycleError("INVALID_TRANSITION", f"cannot claim {node_id!r}: state is {record['state']}, not PENDING")

    raise LifecycleError(
        "ALREADY_CLAIMED", f"{node_id!r} already claimed by {record.get('owner')!r}, not {owner!r}"
    )


def start(store_dir: Path, node_id: str, owner_pid: int, *, wall_budget_seconds: float | None = None) -> dict[str, Any]:
    """PENDING -> RUNNING, recording the lock (owner_pid + acquired_at) that
    mutex.py and stale.py key off. Idempotent: re-starting a node already
    RUNNING under the same owner_pid is a no-op and returns the existing
    record (this is the exact crash-mid-transition-resume case: the engine
    died after writing RUNNING but before doing any work, and calling start()
    again on restart must not error)."""
    record = load_node(store_dir, node_id)

    if record["state"] == RUNNING:
        lock = record.get("lock") or {}
        if lock.get("owner_pid") == owner_pid:
            return record
        raise LifecycleError(
            "ALREADY_RUNNING", f"{node_id!r} already RUNNING under pid {lock.get('owner_pid')}, not {owner_pid}"
        )

    if record["state"] != PENDING:
        raise LifecycleError("INVALID_TRANSITION", f"cannot start {node_id!r}: state is {record['state']}, not PENDING")

    record = dict(record)
    record["state"] = RUNNING
    lock: dict[str, Any] = {"owner_pid": owner_pid, "acquired_at": _now()}
    if wall_budget_seconds is not None:
        lock["wall_budget_seconds"] = wall_budget_seconds
    record["lock"] = lock
    atomic_write_json(node_path(store_dir, node_id), record)
    return record


def request_review(store_dir: Path, node_id: str) -> dict[str, Any]:
    """RUNNING -> AWAITING_REVIEW. Idempotent if already AWAITING_REVIEW."""
    record = load_node(store_dir, node_id)

    if record["state"] == AWAITING_REVIEW:
        return record
    if record["state"] != RUNNING:
        raise LifecycleError(
            "INVALID_TRANSITION", f"cannot request review for {node_id!r}: state is {record['state']}, not RUNNING"
        )

    record = dict(record)
    record["state"] = AWAITING_REVIEW
    atomic_write_json(node_path(store_dir, node_id), record)
    return record


def close(
    store_dir: Path,
    node_id: str,
    verdict: str,
    *,
    outputs: list[dict[str, Any]] | None = None,
    receipt_id: str | None = None,
) -> dict[str, Any]:
    """RUNNING or AWAITING_REVIEW -> CLOSED_PASS | CLOSED_FLAT | CLOSED_REJECTED.

    Idempotent when the node is already closed with the SAME verdict (a
    resumed engine re-issuing the close it made right before a crash). Raises
    if the node is already closed with a DIFFERENT verdict -- that is not a
    resume, it is two different outcomes racing for the same node, and this
    substrate never silently picks a winner.
    """
    if verdict not in CLOSED_STATES:
        raise LifecycleError("INVALID_VERDICT", f"{verdict!r} is not a closed state ({sorted(CLOSED_STATES)})")

    record = load_node(store_dir, node_id)

    if record["state"] in CLOSED_STATES:
        if record["state"] == verdict:
            return record
        raise LifecycleError(
            "VERDICT_CONFLICT", f"{node_id!r} already closed as {record['state']}, cannot re-close as {verdict}"
        )

    if record["state"] not in (RUNNING, AWAITING_REVIEW):
        raise LifecycleError(
            "INVALID_TRANSITION",
            f"cannot close {node_id!r}: state is {record['state']}, expected RUNNING or AWAITING_REVIEW",
        )

    record = dict(record)
    record["state"] = verdict
    record["closed_at"] = _now()
    record.pop("lock", None)
    if outputs is not None:
        record["outputs"] = outputs
    if receipt_id is not None:
        record["receipt_id"] = receipt_id
    atomic_write_json(node_path(store_dir, node_id), record)
    return record
