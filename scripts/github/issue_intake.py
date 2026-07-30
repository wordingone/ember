#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Deterministic, triage-aware issue-intake validation."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MARKERS = ("<!-- ember-template: issue/", "<!-- ember-work-item:")
LEGACY_MIGRATION_CUTOFF = datetime(
    2026, 7, 29, 18, 40, 52, tzinfo=timezone.utc
)


def _is_preserved_legacy_issue(issue: dict[str, Any]) -> bool:
    """Identify bodies that predate the immutable PR #1183 migration boundary."""
    created_at = issue.get("created_at")
    if not isinstance(created_at, str):
        return False
    try:
        created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    return created <= LEGACY_MIGRATION_CUTOFF


def validate(issue: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    body = issue.get("body") or ""
    labels = {
        row["name"] if isinstance(row, dict) else row
        for row in issue.get("labels", [])
    }
    if (
        not any(marker in body for marker in MARKERS)
        and not _is_preserved_legacy_issue(issue)
    ):
        errors.append("missing Ember issue-form marker")
    kinds = [name for name in labels if name.startswith("kind:")]
    states = [name for name in labels if name.startswith("state:")]
    areas = [name for name in labels if name.startswith("area:")]
    if len(kinds) != 1:
        errors.append(f"expected exactly one kind: label, got {len(kinds)}")
    if len(states) != 1:
        errors.append(f"expected exactly one state: label, got {len(states)}")
    triage = states == ["state:triage"]
    if (triage and len(areas) > 3) or (not triage and not 1 <= len(areas) <= 3):
        errors.append(f"invalid area cardinality {len(areas)} for current state")
    if not triage and sum(name.startswith("priority:") for name in labels) != 1:
        errors.append("non-triage work requires exactly one priority")
    if (
        not triage
        and kinds
        and kinds[0] in {"kind:defect", "kind:model-behavior"}
        and sum(name.startswith("severity:") for name in labels) != 1
    ):
        errors.append("non-triage defect/model-behavior requires exactly one severity")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event", type=Path, required=True)
    args = parser.parse_args(argv)
    event = json.loads(args.event.read_text(encoding="utf-8", errors="strict"))
    errors = validate(event["issue"])
    result = {"status": "PASS" if not errors else "FAIL", "errors": errors}
    print(json.dumps(result, sort_keys=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
