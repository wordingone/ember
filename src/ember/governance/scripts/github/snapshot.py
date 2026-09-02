#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Capture a canonical, content-addressed Ember GitHub control-plane snapshot."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


class SnapshotError(RuntimeError):
    pass


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


class Gh:
    def __init__(self, command_prefix: list[str], repository: str) -> None:
        if not command_prefix or not all(
            isinstance(value, str) and value for value in command_prefix
        ):
            raise SnapshotError("gh command prefix must be a nonempty string list")
        self.command_prefix = command_prefix
        self.repository = repository

    def _run(self, args: list[str], *, allow_missing: bool = False) -> Any:
        completed = subprocess.run(
            [*self.command_prefix, *args],
            check=False,
            text=True,
            encoding="utf-8",
            errors="strict",
            capture_output=True,
            shell=False,
        )
        if completed.returncode and not allow_missing:
            raise SnapshotError(
                f"gh {' '.join(args)} failed ({completed.returncode}): "
                f"{completed.stderr.strip()}"
            )
        if completed.returncode:
            return {
                "unavailable": True,
                "returncode": completed.returncode,
                "stderr": completed.stderr.strip(),
            }
        try:
            return json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise SnapshotError(f"gh returned non-JSON for {' '.join(args)}") from exc

    def api(self, suffix: str, *, allow_missing: bool = False) -> Any:
        endpoint = f"repos/{self.repository}"
        if suffix:
            endpoint += f"/{suffix}"
        return self._run(["api", endpoint], allow_missing=allow_missing)

    def paginate(self, suffix: str, *, envelope_key: str | None = None) -> list[Any]:
        value = self._run(
            [
                "api",
                "--paginate",
                "--slurp",
                f"repos/{self.repository}/{suffix}",
            ]
        )
        if not isinstance(value, list):
            raise SnapshotError(f"{suffix}: paginated response is not a list")
        flattened: list[Any] = []
        for page in value:
            if envelope_key is not None:
                if not isinstance(page, dict) or not isinstance(
                    page.get(envelope_key), list
                ):
                    raise SnapshotError(f"{suffix}: invalid paginated envelope")
                flattened.extend(page[envelope_key])
            else:
                if not isinstance(page, list):
                    raise SnapshotError(f"{suffix}: page is not a list")
                flattened.extend(page)
        return flattened


def _project_label(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": row["name"],
        "color": row["color"],
        "description": row.get("description") or "",
    }


def _project_issue(row: dict[str, Any], comments: list[Any]) -> dict[str, Any]:
    return {
        "number": row["number"],
        "node_id": row["node_id"],
        "item_type": "pull_request" if "pull_request" in row else "issue",
        "state": row["state"].upper(),
        "state_reason": row.get("state_reason"),
        "title": row["title"],
        "body": row.get("body") or "",
        "labels": sorted(label["name"] for label in row.get("labels", [])),
        "milestone": row.get("milestone", {}).get("title") if row.get("milestone") else None,
        "assignees": sorted(user["login"] for user in row.get("assignees", [])),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "closed_at": row.get("closed_at"),
        "author": row["user"]["login"],
        "comments": [
            {
                "id": comment["id"],
                "author": comment["user"]["login"],
                "created_at": comment["created_at"],
                "updated_at": comment["updated_at"],
                "body": comment.get("body") or "",
            }
            for comment in comments
        ],
    }


def capture(gh: Gh, *, include_comments: bool = True) -> dict[str, Any]:
    repository = gh.api("")
    labels = sorted(
        (_project_label(row) for row in gh.paginate("labels?per_page=100")),
        key=lambda row: row["name"],
    )
    all_open = gh.paginate("issues?state=open&per_page=100&sort=created&direction=asc")
    open_items: list[dict[str, Any]] = []
    for row in all_open:
        comments = (
            gh.paginate(f"issues/{row['number']}/comments?per_page=100")
            if include_comments and row.get("comments", 0)
            else []
        )
        open_items.append(_project_issue(row, comments))
    closed = gh.paginate(
        "issues?state=closed&per_page=25&sort=updated&direction=desc"
    )[:25]
    branches = gh.paginate("branches?per_page=100")
    milestones = gh.paginate("milestones?state=all&per_page=100")
    workflow_rows = gh.paginate(
        "actions/workflows?per_page=100", envelope_key="workflows"
    )
    snapshot = {
        "schema_version": "ember-github-control-plane-snapshot/v1",
        "repository": gh.repository,
        "captured_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "default_branch_head": gh.api("commits/master")["sha"],
        "repository_settings": repository,
        "master_protection": gh.api("branches/master/protection", allow_missing=True),
        "rulesets": gh.api("rulesets", allow_missing=True),
        "labels": labels,
        "milestones": [
            {
                "number": row["number"],
                "title": row["title"],
                "state": row["state"],
                "description": row.get("description") or "",
                "open_issues": row["open_issues"],
                "closed_issues": row["closed_issues"],
            }
            for row in milestones
        ],
        "open_items": open_items,
        "representative_closed_items": [
            _project_issue(row, []) for row in closed
        ],
        "branches": [
            {
                "name": row["name"],
                "sha": row["commit"]["sha"],
                "protected": bool(row["protected"]),
            }
            for row in branches
        ],
        "workflows": [
            {
                "id": row["id"],
                "name": row["name"],
                "path": row["path"],
                "state": row["state"],
            }
            for row in workflow_rows
        ],
        "secret_names": sorted(
            row["name"]
            for row in gh.api("actions/secrets").get("secrets", [])
        ),
        "variable_names": sorted(
            row["name"]
            for row in gh.api("actions/variables").get("variables", [])
        ),
    }
    snapshot["snapshot_sha256"] = canonical_sha256(snapshot)
    return snapshot


def to_label_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "ember-github-label-snapshot/v1",
        "repository": snapshot["repository"],
        "captured_at": snapshot["captured_at"],
        "labels": snapshot["labels"],
        "items": [
            {
                "number": row["number"],
                "node_id": row["node_id"],
                "item_type": row["item_type"],
                "state": row["state"],
                "title": row["title"],
                "labels": row["labels"],
            }
            for row in snapshot["open_items"]
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", default="wordingone/ember")
    parser.add_argument("--gh-wrapper", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--label-output", type=Path)
    parser.add_argument("--without-comments", action="store_true")
    args = parser.parse_args(argv)
    command_prefix = (
        ["powershell.exe", "-NoProfile", "-File", str(args.gh_wrapper.resolve())]
        if args.gh_wrapper
        else ["gh"]
    )
    snapshot = capture(
        Gh(command_prefix, args.repository),
        include_comments=not args.without_comments,
    )
    args.output.write_bytes(canonical_bytes(snapshot) + b"\n")
    if args.label_output:
        args.label_output.write_bytes(
            canonical_bytes(to_label_snapshot(snapshot)) + b"\n"
        )
    print(
        json.dumps(
            {
                "status": "PASS",
                "snapshot_sha256": snapshot["snapshot_sha256"],
                "open_item_count": len(snapshot["open_items"]),
                "branch_count": len(snapshot["branches"]),
                "workflow_count": len(snapshot["workflows"]),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
