#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Fail-closed branch inventory; never deletes a ref."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def build(snapshot: dict[str, Any]) -> dict[str, Any]:
    rows = []
    for branch in sorted(snapshot["branches"], key=lambda row: row["name"]):
        rows.append(
            {
                "name": branch["name"],
                "sha": branch["sha"],
                "protected": bool(branch["protected"]),
                "disposition": (
                    "KEEP_PROTECTED"
                    if branch["protected"]
                    else "KEEP_UNRESOLVED_REQUIRES_REACHABILITY_REPLAY"
                ),
                "deletion_authority": "NOT_GRANTED",
            }
        )
    return {
        "schema_version": "ember-branch-hygiene-audit/v1",
        "repository": snapshot["repository"],
        "source_snapshot_sha256": snapshot["snapshot_sha256"],
        "branch_count": len(rows),
        "rows": rows,
        "verified_delete_count": 0,
        "deletion_authority": "NOT_GRANTED",
        "status": "ADVISORY",
    }


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
