# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Stale-node detection: flag, never kill.

A RUNNING node is STALE if its lock's owner (PID + creation-time identity,
see procid.py) is no longer alive, or its lock's acquired_at exceeds its
declared wall_budget_seconds. Either way this module only produces a report
-- gap-matrix.md's "Stale-node detection" generic case explicitly does not
exist anywhere in the audited surfaces, and the one thing every existing
narrow instance (ember-stale-tree-read-gate.sh, worktree_lifecycle.py's
audit_state) agrees on is fail-closed reporting, not auto-remediation.
Deciding what to do about a stale node is an operator/engine call, not this
module's.

Using procid.is_same_process_alive (PID + creation time) rather than a bare
PID check closes review-pr1310.md MEDIUM-2's false-negative: without it, a
dead RUNNING node's PID getting reused by an unrelated process would make
this scan report the node as healthy.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import procid
from ._atomic import read_json
from .lifecycle import RUNNING


@dataclass(frozen=True)
class StaleReport:
    node_id: str
    reason: str  # "DEAD_OWNER" | "WALL_BUDGET_EXCEEDED"
    detail: str

    def as_dict(self) -> dict[str, str]:
        return {"node_id": self.node_id, "reason": self.reason, "detail": self.detail}


def _parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value)


def check_node(node: dict[str, Any], *, now: datetime | None = None) -> StaleReport | None:
    if node.get("state") != RUNNING:
        return None

    lock = node.get("lock") or {}
    node_id = node.get("node_id", "?")
    owner_pid = lock.get("owner_pid")

    if owner_pid is not None:
        identity = {
            "pid": owner_pid,
            "creation_time": lock.get("owner_creation_time"),
            "mode": lock.get("owner_liveness_mode", procid.MODE_PID_ONLY),
        }
        if not procid.is_same_process_alive(identity):
            return StaleReport(
                node_id, "DEAD_OWNER", f"lock owner_pid {owner_pid} (mode={identity['mode']}) is not alive"
            )

    wall_budget = lock.get("wall_budget_seconds")
    acquired_at = lock.get("acquired_at")
    if wall_budget is not None and acquired_at:
        current = now or datetime.now(timezone.utc)
        started = _parse_ts(acquired_at)
        elapsed = (current - started).total_seconds()
        if elapsed > wall_budget:
            return StaleReport(
                node_id,
                "WALL_BUDGET_EXCEEDED",
                f"running {elapsed:.0f}s, wall_budget_seconds is {wall_budget}",
            )

    return None


def scan(store_dir: Path, *, now: datetime | None = None) -> list[StaleReport]:
    """Scan every node file in store_dir and return a StaleReport for each
    stale RUNNING node. Never mutates node state."""
    reports: list[StaleReport] = []
    for path in sorted(Path(store_dir).glob("*.json")):
        node = read_json(path)
        report = check_node(node, now=now)
        if report is not None:
            reports.append(report)
    return reports
