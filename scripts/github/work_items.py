#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Build and safely apply the human-reviewed open-work metadata plan."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.github import work_items_engine as engine  # noqa: E402
from scripts.github.labels_engine import canonical_bytes, load_data  # noqa: E402

WorkItemError = engine.WorkItemError
CONTROLLED_PREFIXES = ("kind:", "area:", "state:", "priority:", "severity:")


def build_review_plan(snapshot: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    source = copy.deepcopy(snapshot)
    parent_numbers = set(engine.PARENT_BY_MILESTONE.values())
    for item in source["open_items"]:
        item["labels"] = [
            name
            for name in item.get("labels", [])
            if not name.startswith(CONTROLLED_PREFIXES)
        ]
        if item["number"] in parent_numbers:
            item["labels"].append("roadmap:parent")
    result = engine.build_review_plan(source, manifest)
    canonical = {row["name"] for row in manifest["labels"]}
    live_by_number = {row["number"]: row for row in snapshot["open_items"]}
    for row in result["rows"]:
        labels = list(row["desired_labels"])
        kind = next(name for name in labels if name.startswith("kind:"))
        if kind in {"kind:defect", "kind:model-behavior"}:
            if not any(name.startswith("severity:") for name in labels):
                labels.append("severity:s2")
        else:
            labels = [name for name in labels if not name.startswith("severity:")]
        if not set(labels).issubset(canonical):
            raise WorkItemError(f"issue #{row['number']}: noncanonical normalized label")
        row["before_labels"] = sorted(
            live_by_number[row["number"]].get("labels", [])
        )
        row["desired_labels"] = sorted(set(labels))
    result["source_snapshot_sha256"] = snapshot["snapshot_sha256"]
    result.pop("plan_sha256", None)
    result["plan_sha256"] = engine._sha(result)
    return result


def _text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _comments_sha256(comments: list[dict[str, Any]]) -> str:
    return _text_sha256("\n".join(row.get("body") or "" for row in comments))


def _repository_name(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return value.get("nameWithOwner") or value.get("full_name")
    return None


def verify_live_snapshot(plan: dict[str, Any], live: dict[str, Any]) -> None:
    """Refuse mutation unless all reviewed work-object inputs are unchanged."""
    if _repository_name(live.get("repository")) != plan["repository"]:
        raise WorkItemError("live snapshot repository mismatch")
    by_number = {
        row["number"]: row
        for row in live.get("open_items", [])
        if row.get("item_type") == "issue"
    }
    planned = {row["number"] for row in plan["rows"]}
    if set(by_number) != planned:
        raise WorkItemError("live open-issue population drift")
    for row in plan["rows"]:
        current = by_number[row["number"]]
        checks = {
            "title": engine._sha(current["title"]) == row["title_sha256"],
            "body": _text_sha256(current.get("body") or "") == row["body_sha256"],
            "comments": _comments_sha256(current.get("comments", []))
            == row["comments_sha256"],
            "labels": sorted(current.get("labels", [])) == row["before_labels"],
            "milestone": current.get("milestone") == row["primary_milestone"],
            "node_id": current.get("node_id") == row["node_id"],
        }
        failed = sorted(name for name, ok in checks.items() if not ok)
        if failed:
            raise WorkItemError(
                f"issue #{row['number']}: live drift in {', '.join(failed)}"
            )


def apply_plan(
    plan: dict[str, Any],
    *,
    live_snapshot: dict[str, Any],
    wrapper: Path,
    confirm: bool,
) -> dict[str, Any]:
    verify_live_snapshot(plan, live_snapshot)
    return engine.apply_plan(plan, wrapper=wrapper, confirm=confirm)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("plan", "apply"))
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--live-snapshot", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--gh-wrapper", type=Path)
    parser.add_argument("--confirm-apply", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "plan":
        if args.snapshot is None or args.manifest is None:
            raise WorkItemError("plan requires --snapshot and --manifest")
        result = build_review_plan(load_data(args.snapshot), load_data(args.manifest))
    else:
        if (
            args.plan is None
            or args.live_snapshot is None
            or args.gh_wrapper is None
        ):
            raise WorkItemError(
                "apply requires --plan, --live-snapshot, and --gh-wrapper"
            )
        result = apply_plan(
            load_data(args.plan),
            live_snapshot=load_data(args.live_snapshot),
            wrapper=args.gh_wrapper,
            confirm=args.confirm_apply,
        )
    args.output.write_bytes(canonical_bytes(result) + b"\n")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
