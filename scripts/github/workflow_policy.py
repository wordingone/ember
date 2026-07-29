#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Static fail-closed policy for GitHub Actions workflow sources."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import yaml


PINNED_ACTION = re.compile(r"^[^./][^@]*@[0-9a-f]{40}$")
WRITE_KEYS = {
    "actions",
    "attestations",
    "checks",
    "contents",
    "deployments",
    "discussions",
    "id-token",
    "issues",
    "packages",
    "pages",
    "pull-requests",
    "repository-projects",
    "security-events",
    "statuses",
}


def _load(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8", errors="strict"))
    if not isinstance(value, dict):
        raise ValueError("workflow must be a mapping")
    # PyYAML 1.1 may parse the key "on" as True.
    if True in value and "on" not in value:
        value["on"] = value.pop(True)
    return value


def _permission_writes(value: Any) -> bool:
    if value == "write-all":
        return True
    return isinstance(value, dict) and any(
        key in WRITE_KEYS and access == "write" for key, access in value.items()
    )


def validate_workflow(path: Path) -> list[str]:
    errors: list[str] = []
    try:
        workflow = _load(path)
    except Exception as exc:
        return [f"{path.name}: unreadable: {exc}"]
    for key in ("name", "on", "permissions", "jobs"):
        if key not in workflow:
            errors.append(f"{path.name}: missing top-level {key}")
    jobs = workflow.get("jobs")
    if not isinstance(jobs, dict) or not jobs:
        return errors + [f"{path.name}: jobs must be a nonempty mapping"]
    events = workflow.get("on")
    event_names = (
        {events}
        if isinstance(events, str)
        else set(events or ())
        if isinstance(events, (dict, list))
        else set()
    )
    privileged = "pull_request_target" in event_names and _permission_writes(
        workflow.get("permissions")
    )
    for job_name, job in jobs.items():
        context = f"{path.name}:{job_name}"
        if not isinstance(job, dict):
            errors.append(f"{context}: job must be a mapping")
            continue
        if "timeout-minutes" not in job:
            errors.append(f"{context}: timeout-minutes is required")
        steps = job.get("steps", [])
        if not isinstance(steps, list):
            errors.append(f"{context}: steps must be a list")
            continue
        job_privileged = privileged or (
            "pull_request_target" in event_names
            and _permission_writes(job.get("permissions"))
        )
        for index, step in enumerate(steps):
            if not isinstance(step, dict):
                errors.append(f"{context}:step[{index}] must be a mapping")
                continue
            action = step.get("uses")
            if isinstance(action, str) and not action.startswith("./"):
                if not PINNED_ACTION.fullmatch(action):
                    errors.append(f"{context}: unpinned action {action}")
            if job_privileged:
                ref = str(step.get("with", {}).get("ref", ""))
                if "pull_request.head" in ref or "/merge" in ref:
                    errors.append(
                        f"{context}: privileged job checks out pull-request subject"
                    )
                run = str(step.get("run", ""))
                if (
                    re.search(r"\b(bun|npm|pip|pytest|cargo|python)\b", run)
                    and "trusted-kernel/scripts/github/" not in run
                ):
                    errors.append(
                        f"{context}: privileged job may execute repository-authored code"
                    )
    return errors


def validate_tree(root: Path) -> dict[str, Any]:
    paths = sorted((root / ".github" / "workflows").glob("*.y*ml"))
    errors: list[str] = []
    for path in paths:
        errors.extend(validate_workflow(path))
    return {
        "status": "PASS" if not errors else "FAIL",
        "workflow_count": len(paths),
        "errors": errors,
        "claim_boundary": "static workflow policy; not runtime execution proof",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    result = validate_tree(args.root.resolve())
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
