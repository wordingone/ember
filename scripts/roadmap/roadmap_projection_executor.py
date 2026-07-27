#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Execute the validated Ember roadmap projection through the safe GitHub wrapper."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote


PARENT_MARKER = re.compile(r"<!-- ember-roadmap-parent: (EMBER-\d{2}) -->")
MILESTONE = re.compile(r"^(EMBER-\d{2})(?::|\s|$)")


class ExecutionError(RuntimeError):
    pass


def canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n"
    ).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def body_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def flatten(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ExecutionError("paginated GitHub response is not an array")
    if all(isinstance(row, dict) for row in value):
        return list(value)
    rows: list[dict[str, Any]] = []
    for page in value:
        if not isinstance(page, list) or not all(isinstance(row, dict) for row in page):
            raise ExecutionError("invalid paginated GitHub response")
        rows.extend(page)
    return rows


def milestone_id(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ExecutionError("issue milestone is not an object")
    match = MILESTONE.match(str(value.get("title", "")))
    if match and match.group(1) in {f"EMBER-{index:02d}" for index in range(12)}:
        return match.group(1)
    return None


class SafeGitHub:
    def __init__(self, wrapper: Path, repository: str) -> None:
        if not wrapper.is_file():
            raise ExecutionError("safe GitHub wrapper is unavailable")
        self.wrapper = wrapper.resolve()
        self.repository = repository

    def api(
        self,
        endpoint: str,
        *,
        method: str = "GET",
        payload: dict[str, Any] | None = None,
        paginate: bool = False,
    ) -> Any:
        command = [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(self.wrapper),
            "api",
            endpoint,
        ]
        if method != "GET":
            command.extend(["--method", method])
        if payload is not None:
            command.extend(["--input", "-"])
        if paginate:
            command.extend(["--paginate", "--slurp"])
        result = subprocess.run(
            command,
            input=(json.dumps(payload) if payload is not None else None),
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        if result.returncode != 0:
            raise ExecutionError(
                f"GitHub {method} refused for {endpoint}: {result.stderr.strip()}"
            )
        output = result.stdout.strip()
        if not output:
            return None
        try:
            return json.loads(output)
        except json.JSONDecodeError as exc:
            raise ExecutionError(f"GitHub response is not JSON for {endpoint}") from exc


def load_planner(path: Path):
    spec = importlib.util.spec_from_file_location("roadmap_projection", path)
    if spec is None or spec.loader is None:
        raise ExecutionError("cannot load projection planner")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def capture_live(
    gh: SafeGitHub,
    projection: dict[str, Any],
    publication_master_sha: str,
) -> dict[str, Any]:
    repo = gh.repository
    source_sha = str(projection["source_master_sha"])
    master = gh.api(f"repos/{repo}/commits/master")
    if master.get("sha") != publication_master_sha:
        raise ExecutionError("public master differs from the exact landed carrier")
    compare = gh.api(f"repos/{repo}/compare/{source_sha}...{publication_master_sha}")
    source_is_ancestor = bool(
        compare.get("status") in {"ahead", "identical"}
        and compare.get("merge_base_commit", {}).get("sha") == source_sha
    )

    labels = {
        str(row["name"]): {
            "color": str(row["color"]),
            "description": str(row.get("description") or ""),
        }
        for row in flatten(
            gh.api(f"repos/{repo}/labels?per_page=100", paginate=True)
        )
    }
    milestones: dict[str, dict[str, Any]] = {}
    for row in flatten(
        gh.api(f"repos/{repo}/milestones?state=all&per_page=100", paginate=True)
    ):
        mid = milestone_id(row)
        if mid is None:
            continue
        if mid in milestones:
            raise ExecutionError(f"duplicate canonical milestone {mid}")
        milestones[mid] = {
            "number": int(row["number"]),
            "title": str(row["title"]),
            "description": str(row.get("description") or ""),
            "state": str(row["state"]),
            "due_on": row.get("due_on"),
        }

    issue_rows = flatten(
        gh.api(
            f"repos/{repo}/issues?state=open&sort=created&direction=asc&per_page=100",
            paginate=True,
        )
    )
    issue_rows = [row for row in issue_rows if "pull_request" not in row]
    search = gh.api(
        f"search/issues?q=repo%3A{repo.replace('/', '%2F')}+is%3Aissue+is%3Aopen&per_page=1"
    )
    if int(search["total_count"]) != len(issue_rows):
        raise ExecutionError("open issue pagination is incomplete")

    parents: dict[str, dict[str, Any]] = {}
    issues: dict[int, dict[str, Any]] = {}
    open_issue_numbers: list[int] = []
    for row in issue_rows:
        number = int(row["number"])
        open_issue_numbers.append(number)
        body = str(row.get("body") or "")
        match = PARENT_MARKER.search(body)
        if match:
            key = f"roadmap-parent:{match.group(1)}"
            if key in parents:
                raise ExecutionError(f"duplicate roadmap parent {key}")
            parents[key] = {
                "id": int(row["id"]),
                "number": number,
                "title": str(row["title"]),
                "body": body,
                "labels": sorted(str(item["name"]) for item in row.get("labels", [])),
                "milestone_id": milestone_id(row.get("milestone")),
            }
            continue
        issues[number] = {
            "id": int(row["id"]),
            "state": str(row["state"]),
            "body_sha256": body_digest(body),
            "updated_at": str(row["updated_at"]),
            "labels": sorted(str(item["name"]) for item in row.get("labels", [])),
            "milestone_id": milestone_id(row.get("milestone")),
            "parent_tracking_key": None,
        }

    dependencies: dict[str, list[str]] = {}
    for key, parent in parents.items():
        blocked_by = flatten(
            gh.api(
                f"repos/{repo}/issues/{parent['number']}/dependencies/blocked_by?per_page=100",
                paginate=True,
            )
        )
        dependency_keys: list[str] = []
        for row in blocked_by:
            match = PARENT_MARKER.search(str(row.get("body") or ""))
            if match is None:
                raise ExecutionError(f"{key} has a non-roadmap dependency")
            dependency_keys.append(f"roadmap-parent:{match.group(1)}")
        dependencies[key] = sorted(dependency_keys)

        subissues = flatten(
            gh.api(
                f"repos/{repo}/issues/{parent['number']}/sub_issues?per_page=100",
                paginate=True,
            )
        )
        for row in subissues:
            number = int(row["number"])
            if number not in issues:
                raise ExecutionError(f"{key} contains an unaccounted subissue {number}")
            current = issues[number]["parent_tracking_key"]
            if current not in (None, key):
                raise ExecutionError(f"issue {number} has multiple roadmap parents")
            issues[number]["parent_tracking_key"] = key

    return {
        "master_sha": publication_master_sha,
        "projection_source_is_ancestor": source_is_ancestor,
        "open_issue_numbers": sorted(open_issue_numbers),
        "labels": labels,
        "milestones": milestones,
        "parents": parents,
        "issues": issues,
        "dependencies": dependencies,
    }


class Client:
    def __init__(self, gh: SafeGitHub, live: dict[str, Any]) -> None:
        self.gh = gh
        self.repo = gh.repository
        self.milestones = live["milestones"]
        self.parents = live["parents"]

    def _milestone_number(self, mid: str) -> int:
        row = self.milestones.get(mid)
        if row is None:
            raise ExecutionError(f"milestone {mid} has not been created")
        return int(row["number"])

    def _parent(self, key: str) -> dict[str, Any]:
        row = self.parents.get(key)
        if row is None:
            raise ExecutionError(f"parent {key} has not been created")
        return row

    def execute(self, operation: dict[str, Any]) -> dict[str, Any]:
        op = str(operation["op"])
        if op == "create_label":
            desired = operation["label"]
            row = self.gh.api(
                f"repos/{self.repo}/labels", method="POST", payload=desired
            )
            return {"op": op, "name": row["name"]}
        if op == "update_label":
            desired = operation["label"]
            name = quote(str(desired["name"]), safe="")
            row = self.gh.api(
                f"repos/{self.repo}/labels/{name}",
                method="PATCH",
                payload=desired,
            )
            return {"op": op, "name": row["name"]}
        if op in {"create_milestone", "update_milestone"}:
            desired = dict(operation["milestone"])
            mid = str(desired.pop("milestone_id"))
            desired.pop("existing_number", None)
            endpoint = f"repos/{self.repo}/milestones"
            method = "POST"
            if op == "update_milestone":
                endpoint += f"/{operation['milestone_number']}"
                method = "PATCH"
            row = self.gh.api(endpoint, method=method, payload=desired)
            self.milestones[mid] = {
                "number": int(row["number"]),
                "title": str(row["title"]),
                "description": str(row.get("description") or ""),
                "state": str(row["state"]),
                "due_on": row.get("due_on"),
            }
            return {"op": op, "milestone_id": mid, "number": int(row["number"])}
        if op in {"create_parent_issue", "update_parent_issue"}:
            desired = operation["parent"]
            payload = {
                "title": desired["title"],
                "body": desired["body"],
                "milestone": self._milestone_number(desired["milestone_id"]),
            }
            endpoint = f"repos/{self.repo}/issues"
            method = "POST"
            if op == "create_parent_issue":
                payload["labels"] = desired["labels"]
            else:
                endpoint += f"/{operation['issue_number']}"
                method = "PATCH"
            row = self.gh.api(endpoint, method=method, payload=payload)
            key = str(desired["tracking_key"])
            self.parents[key] = {
                "id": int(row["id"]),
                "number": int(row["number"]),
                "title": str(row["title"]),
                "body": str(row.get("body") or ""),
                "labels": sorted(str(item["name"]) for item in row.get("labels", [])),
                "milestone_id": desired["milestone_id"],
            }
            return {"op": op, "tracking_key": key, "number": int(row["number"])}
        if op in {"add_parent_labels", "add_issue_labels"}:
            number = int(operation["issue_number"])
            self.gh.api(
                f"repos/{self.repo}/issues/{number}/labels",
                method="POST",
                payload={"labels": operation["labels"]},
            )
            return {"op": op, "number": number, "labels": operation["labels"]}
        if op == "add_parent_dependency":
            blocked = self._parent(str(operation["tracking_key"]))
            blocker = self._parent(str(operation["blocked_by"]))
            self.gh.api(
                f"repos/{self.repo}/issues/{blocked['number']}/dependencies/blocked_by",
                method="POST",
                payload={"issue_id": int(blocker["id"])},
            )
            return {
                "op": op,
                "number": int(blocked["number"]),
                "blocked_by": int(blocker["number"]),
            }
        if op == "set_issue_milestone":
            number = int(operation["issue_number"])
            mid = str(operation["milestone_id"])
            self.gh.api(
                f"repos/{self.repo}/issues/{number}",
                method="PATCH",
                payload={"milestone": self._milestone_number(mid)},
            )
            return {"op": op, "number": number, "milestone_id": mid}
        if op == "add_subissue":
            parent = self._parent(str(operation["parent_tracking_key"]))
            self.gh.api(
                f"repos/{self.repo}/issues/{parent['number']}/sub_issues",
                method="POST",
                payload={"sub_issue_id": int(operation["issue_id"])},
            )
            return {
                "op": op,
                "number": int(operation["issue_number"]),
                "parent": int(parent["number"]),
            }
        raise ExecutionError(f"unsupported operation {op}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--projection", type=Path, required=True)
    parser.add_argument("--planner", type=Path, required=True)
    parser.add_argument("--gh-wrapper", type=Path, required=True)
    parser.add_argument("--publication-master-sha", required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    projection = json.loads(args.projection.read_text(encoding="utf-8"))
    repository = str(projection["repository"])
    planner = load_planner(args.planner)
    gh = SafeGitHub(args.gh_wrapper, repository)
    started = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    before = capture_live(gh, projection, args.publication_master_sha)
    operations = planner.build_mutation_plan(
        projection,
        before,
        publication_master_sha=args.publication_master_sha,
    )
    if not args.execute:
        print(
            json.dumps(
                {
                    "status": "ROADMAP_PROJECTION_PREFLIGHT",
                    "operation_count": len(operations),
                    "operations": dict(Counter(row["op"] for row in operations)),
                    "live_state_sha256": digest(before),
                },
                sort_keys=True,
            )
        )
        return 0

    client = Client(gh, before)
    try:
        completed = planner.apply_plan(operations, client)
    except planner.ProjectionApplyError as exc:
        completed = exc.completed
        status = "PARTIAL_STOPPED"
        error = str(exc)
    else:
        status = "APPLIED"
        error = None

    after = capture_live(gh, projection, args.publication_master_sha)
    remaining = planner.build_mutation_plan(
        projection,
        after,
        publication_master_sha=args.publication_master_sha,
    )
    if status == "APPLIED" and remaining:
        raise ExecutionError("projection completed but idempotency plan is not empty")
    finished = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    receipt = {
        "schema_version": "ember-roadmap-projection-execution-v1",
        "repository": repository,
        "source_master_sha": projection["source_master_sha"],
        "publication_master_sha": args.publication_master_sha,
        "projection_sha256": digest(projection),
        "before_live_state_sha256": digest(before),
        "after_live_state_sha256": digest(after),
        "started_at": started,
        "finished_at": finished,
        "planned_operation_count": len(operations),
        "completed_operation_count": len(completed),
        "completed_operation_types": dict(
            Counter(row["operation"]["op"] for row in completed)
        ),
        "remaining_operation_count": len(remaining),
        "issue_closure_count": 0,
        "status": status,
        "error": error,
        "completed": completed,
    }
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_bytes(canonical_bytes(receipt))
    print(
        json.dumps(
            {
                "status": status,
                "planned": len(operations),
                "completed": len(completed),
                "remaining": len(remaining),
                "receipt_sha256": digest(receipt),
            },
            sort_keys=True,
        )
    )
    return 0 if status == "APPLIED" else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ExecutionError, OSError, KeyError, TypeError, ValueError) as exc:
        print(f"ROADMAP_PROJECTION_REFUSED: {exc}", file=sys.stderr)
        raise SystemExit(2)
