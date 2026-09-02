#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Capture the complete public GitHub inputs for roadmap reconciliation."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


class CaptureError(ValueError):
    pass


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _flatten_pages(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise CaptureError("paginated response is not an array")
    if not value:
        return []
    if all(isinstance(row, dict) for row in value):
        return list(value)
    rows: list[dict[str, Any]] = []
    for page in value:
        if not isinstance(page, list) or not all(
            isinstance(row, dict) for row in page
        ):
            raise CaptureError("paginated response has an invalid page")
        rows.extend(page)
    return rows


def _milestone(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise CaptureError("issue milestone is not an object")
    return {
        "number": int(value["number"]),
        "title": str(value["title"]),
        "state": str(value["state"]),
    }


def capture(
    *,
    run: Callable[..., Any],
    repository: str,
    captured_at: str,
) -> dict[str, Any]:
    master = run(f"repos/{repository}/commits/master")
    if not isinstance(master, dict) or not isinstance(master.get("sha"), str):
        raise CaptureError("master response has no sha")
    master_sha = master["sha"]
    if len(master_sha) != 40:
        raise CaptureError("master sha is not 40 hex characters")

    issue_pages = run(
        (
            f"repos/{repository}/issues?state=open&per_page=100"
            "&sort=created&direction=asc"
        ),
        paginate=True,
    )
    all_rows = _flatten_pages(issue_pages)
    issue_rows = [row for row in all_rows if "pull_request" not in row]
    pull_rows = [row for row in all_rows if "pull_request" in row]
    issue_search = run(
        f"search/issues?q=repo%3A{repository.replace('/', '%2F')}"
        "+is%3Aissue+is%3Aopen&per_page=1"
    )
    pr_search = run(
        f"search/issues?q=repo%3A{repository.replace('/', '%2F')}"
        "+is%3Apr+is%3Aopen&per_page=1"
    )
    expected_issue_count = int(issue_search["total_count"])
    expected_pr_count = int(pr_search["total_count"])
    if expected_issue_count != len(issue_rows):
        raise CaptureError(
            "open issue count mismatch: "
            f"pages={len(issue_rows)} search={expected_issue_count}"
        )
    if expected_pr_count != len(pull_rows):
        raise CaptureError(
            "open pull request count mismatch: "
            f"pages={len(pull_rows)} search={expected_pr_count}"
        )

    issues: list[dict[str, Any]] = []
    seen_numbers: set[int] = set()
    for row in sorted(issue_rows, key=lambda item: int(item["number"])):
        number = int(row["number"])
        if number in seen_numbers:
            raise CaptureError(f"duplicate issue number: {number}")
        seen_numbers.add(number)
        body = row.get("body") or ""
        labels = sorted(
            str(label["name"])
            for label in row.get("labels", [])
            if isinstance(label, dict) and isinstance(label.get("name"), str)
        )
        issues.append(
            {
                "number": number,
                "title": str(row["title"]),
                "url": str(row["html_url"]),
                "body_sha256": _sha256_text(str(body)),
                "labels": labels,
                "milestone": _milestone(row.get("milestone")),
                "created_at": str(row["created_at"]),
                "updated_at": str(row["updated_at"]),
                "comment_count": int(row.get("comments", 0)),
                "state": str(row["state"]),
            }
        )

    milestones_raw = run(
        f"repos/{repository}/milestones?state=all&per_page=100",
        paginate=True,
    )
    milestones = [
        {
            "number": int(row["number"]),
            "title": str(row["title"]),
            "state": str(row["state"]),
            "open_issues": int(row.get("open_issues", 0)),
            "closed_issues": int(row.get("closed_issues", 0)),
            "description_sha256": _sha256_text(str(row.get("description") or "")),
        }
        for row in sorted(
            _flatten_pages(milestones_raw),
            key=lambda item: int(item["number"]),
        )
    ]
    labels_raw = run(
        f"repos/{repository}/labels?per_page=100",
        paginate=True,
    )
    labels = [
        {
            "name": str(row["name"]),
            "color": str(row["color"]),
            "description": str(row.get("description") or ""),
        }
        for row in sorted(
            _flatten_pages(labels_raw),
            key=lambda item: str(item["name"]).casefold(),
        )
    ]

    return {
        "schema_version": "ember-roadmap-public-state-v1",
        "repository": repository,
        "public_master_sha": master_sha,
        "captured_at": captured_at,
        "counts": {
            "open_issues": len(issues),
            "open_pull_requests": len(pull_rows),
            "milestones_all": len(milestones),
            "labels": len(labels),
        },
        "issues": issues,
        "milestones": milestones,
        "labels": labels,
    }


def _runner(wrapper: Path, repository: str) -> Callable[..., Any]:
    if not wrapper.is_file():
        raise CaptureError(f"safe GitHub wrapper is not a file: {wrapper}")

    def run(endpoint: str, *, paginate: bool = False) -> Any:
        command = [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(wrapper),
            "api",
            endpoint,
        ]
        if paginate:
            command.extend(["--paginate", "--slurp"])
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        if result.returncode != 0:
            raise CaptureError(
                f"GitHub read failed for {endpoint}: {result.stderr.strip()}"
            )
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise CaptureError(
                f"GitHub response is not JSON for {endpoint}"
            ) from exc

    return run


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", default="wordingone/ember")
    parser.add_argument("--gh-wrapper", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    captured_at = (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
    try:
        payload = capture(
            run=_runner(args.gh_wrapper, args.repository),
            repository=args.repository,
            captured_at=captured_at,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)
            + "\n",
            encoding="utf-8",
            newline="\n",
        )
    except (CaptureError, OSError, KeyError, TypeError, ValueError) as exc:
        print(f"ROADMAP_CAPTURE_REFUSED: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "master": payload["public_master_sha"],
                "open_issues": payload["counts"]["open_issues"],
                "open_pull_requests": payload["counts"]["open_pull_requests"],
                "status": "PUBLIC_STATE_CAPTURED",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
