#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Rate-bounded runner for the Ember roadmap projection executor."""

from __future__ import annotations

import argparse
import importlib.util
import json
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def load(path: Path):
    spec = importlib.util.spec_from_file_location("roadmap_executor", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load roadmap executor")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def coalesce(operations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Combine each issue's label and milestone changes into one PATCH."""

    prefix: list[dict[str, Any]] = []
    suffix: list[dict[str, Any]] = []
    updates: dict[int, dict[str, Any]] = {}
    for operation in operations:
        op = operation["op"]
        if op in {"add_issue_labels", "set_issue_milestone"}:
            number = int(operation["issue_number"])
            update = updates.setdefault(
                number,
                {
                    "op": "update_issue",
                    "issue_number": number,
                    "add_labels": [],
                    "set_milestone": None,
                },
            )
            if op == "add_issue_labels":
                update["add_labels"] = operation["labels"]
            else:
                update["set_milestone"] = operation["milestone_id"]
        elif op == "add_subissue":
            suffix.append(operation)
        else:
            prefix.append(operation)
    return prefix + [updates[number] for number in sorted(updates)] + suffix


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--executor", type=Path, required=True)
    parser.add_argument("--projection", type=Path, required=True)
    parser.add_argument("--planner", type=Path, required=True)
    parser.add_argument("--gh-wrapper", type=Path, required=True)
    parser.add_argument("--publication-master-sha", required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    base = load(args.executor)
    planner = base.load_planner(args.planner)
    projection = json.loads(args.projection.read_text(encoding="utf-8"))
    gh = base.SafeGitHub(args.gh_wrapper, projection["repository"])
    before = base.capture_live(gh, projection, args.publication_master_sha)
    logical = planner.build_mutation_plan(
        projection,
        before,
        publication_master_sha=args.publication_master_sha,
    )
    operations = coalesce(logical)
    summary = {
        "logical_operation_count": len(logical),
        "api_operation_count": len(operations),
        "operations": dict(Counter(row["op"] for row in operations)),
        "before_live_state_sha256": base.digest(before),
    }
    if not args.execute:
        print(json.dumps({"status": "ROADMAP_PROJECTION_PREFLIGHT", **summary}, sort_keys=True))
        return 0

    class RateBoundedClient(base.Client):
        def __init__(self, safe_gh, live):
            super().__init__(safe_gh, live)
            self.issues = live["issues"]

        def execute(self, operation):
            time.sleep(1.0)
            if operation["op"] != "update_issue":
                return super().execute(operation)
            number = int(operation["issue_number"])
            current = self.issues[number]
            labels = sorted(
                set(current["labels"]) | set(operation.get("add_labels", []))
            )
            payload: dict[str, Any] = {"labels": labels}
            milestone = operation.get("set_milestone")
            if milestone is not None:
                payload["milestone"] = self._milestone_number(str(milestone))
            self.gh.api(
                f"repos/{self.repo}/issues/{number}",
                method="PATCH",
                payload=payload,
            )
            current["labels"] = labels
            current["milestone_id"] = milestone or current["milestone_id"]
            return {
                "op": "update_issue",
                "number": number,
                "added_labels": operation.get("add_labels", []),
                "milestone_id": milestone,
            }

    started_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    client = RateBoundedClient(gh, before)
    try:
        completed = planner.apply_plan(operations, client)
    except planner.ProjectionApplyError as exc:
        completed = exc.completed
        status = "PARTIAL_STOPPED"
        error = str(exc)
    else:
        status = "APPLIED"
        error = None

    after = base.capture_live(gh, projection, args.publication_master_sha)
    remaining = planner.build_mutation_plan(
        projection,
        after,
        publication_master_sha=args.publication_master_sha,
    )
    if status == "APPLIED" and remaining:
        raise RuntimeError("nonempty idempotency plan after completed projection")
    receipt = {
        "schema_version": "ember-roadmap-projection-execution-v1",
        "repository": projection["repository"],
        "source_master_sha": projection["source_master_sha"],
        "publication_master_sha": args.publication_master_sha,
        "projection_sha256": base.digest(projection),
        "before_live_state_sha256": base.digest(before),
        "after_live_state_sha256": base.digest(after),
        "started_at": started_at,
        "finished_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "logical_operation_count": len(logical),
        "planned_api_operation_count": len(operations),
        "completed_api_operation_count": len(completed),
        "completed_operation_types": dict(
            Counter(row["operation"]["op"] for row in completed)
        ),
        "remaining_logical_operation_count": len(remaining),
        "issue_closure_count": 0,
        "status": status,
        "error": error,
        "completed": completed,
    }
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_bytes(base.canonical_bytes(receipt))
    print(
        json.dumps(
            {
                "status": status,
                "completed": len(completed),
                "remaining": len(remaining),
                "receipt_sha256": base.digest(receipt),
            },
            sort_keys=True,
        )
    )
    return 0 if status == "APPLIED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
