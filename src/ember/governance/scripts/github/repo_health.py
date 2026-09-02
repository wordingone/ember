#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Outcome-oriented advisory repository health report."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def build(snapshot: dict[str, Any]) -> dict[str, Any]:
    missing: list[dict[str, Any]] = []
    unresolved_priority = Counter()
    blocked = []
    for item in snapshot["open_items"]:
        labels = set(item["labels"])
        absent = []
        if not any(x.startswith("kind:") for x in labels):
            absent.append("kind")
        if not any(x.startswith("area:") for x in labels):
            absent.append("area")
        if not any(x.startswith("state:") for x in labels):
            absent.append("state")
        if absent:
            missing.append({"number": item["number"], "missing": absent})
        for priority in ("priority:p0", "priority:p1"):
            if priority in labels:
                unresolved_priority[priority] += 1
        if "state:blocked" in labels:
            blocked.append(
                {
                    "number": item["number"],
                    "updated_at": item["updated_at"],
                    "needs": sorted(x for x in labels if x.startswith("needs:")),
                }
            )
    result = {
        "schema_version": "ember-repository-health/v1",
        "repository": snapshot["repository"],
        "source_snapshot_sha256": snapshot["snapshot_sha256"],
        "open_work_count": len(snapshot["open_items"]),
        "classification_gaps": missing,
        "unresolved_priority": dict(sorted(unresolved_priority.items())),
        "blocked_items": blocked,
        "branch_count": len(snapshot["branches"]),
        "workflow_count": len(snapshot["workflows"]),
        "status": "ADVISORY",
        "prohibited_progress_proxies": [
            "commits_per_day",
            "prs_per_day",
            "issues_closed_per_day",
            "files_or_lines_added",
            "trunk_movement",
            "repository_growth",
        ],
        "claim_boundary": "repository operability metadata, not project progress",
    }
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    snapshot = json.loads(args.snapshot.read_text(encoding="utf-8", errors="strict"))
    result = build(snapshot)
    args.output.write_text(
        json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
        errors="strict",
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
