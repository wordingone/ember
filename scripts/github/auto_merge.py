#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Fail-closed auto-merge enrollment policy.

This tool only enrolls a deliberately authorized PR in GitHub auto-merge.
Branch protection and required checks still decide whether it lands.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from dataclasses import dataclass
from typing import Any, Mapping


PROTECTED = (
    re.compile(r"^(?:INVARIANT\.md|GOAL\.md)$"),
    re.compile(r"^\.github/workflows/"),
    re.compile(r"^\.githooks/"),
    re.compile(r"^scripts/github/"),
    re.compile(r"^tools/[^/]+$"),
    re.compile(r"^scripts/[^/]+$"),
    re.compile(r"^tools/ember-cli/src/build-tools/"),
    re.compile(r"^docs/authority/"),
    re.compile(r"^goals/"),
    re.compile(r"^constitution"),
)


@dataclass(frozen=True)
class Decision:
    eligible: bool
    reason: str


def decide(meta: Mapping[str, Any]) -> Decision:
    required = {
        "number",
        "isDraft",
        "autoMergeRequest",
        "baseRefName",
        "files",
        "changedFiles",
        "labels",
    }
    if set(meta) < required:
        return Decision(False, "metadata-incomplete")
    labels = meta["labels"]
    if not isinstance(labels, list) or not all(
        isinstance(row, dict) and isinstance(row.get("name"), str) for row in labels
    ):
        return Decision(False, "labels-unreadable")
    names = {row["name"] for row in labels}
    if "merge:manual-required" in names:
        return Decision(False, "manual-required")
    if "merge:auto-approved" not in names:
        return Decision(False, "authority-label-missing")
    if meta["isDraft"] is not False:
        return Decision(False, "draft-or-unknown")
    if meta["baseRefName"] != "master":
        return Decision(False, "noncanonical-base")
    if meta["autoMergeRequest"] is not None:
        return Decision(False, "already-enrolled")
    files = meta["files"]
    if not isinstance(files, list) or not all(
        isinstance(row, dict) and isinstance(row.get("path"), str) for row in files
    ):
        return Decision(False, "files-unreadable")
    if (
        not isinstance(meta["changedFiles"], int)
        or isinstance(meta["changedFiles"], bool)
        or len(files) != meta["changedFiles"]
    ):
        return Decision(False, "files-truncated")
    for row in files:
        if any(pattern.search(row["path"]) for pattern in PROTECTED):
            return Decision(False, f"protected-path:{row['path']}")
    return Decision(True, "authorized-and-bounded")


def _gh_json(args: list[str]) -> Any:
    completed = subprocess.run(
        ["gh", *args],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
        shell=False,
    )
    if completed.returncode:
        raise RuntimeError(completed.stderr.strip())
    return json.loads(completed.stdout)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", default="wordingone/ember")
    parser.add_argument("--pr", type=int, action="append")
    args = parser.parse_args(argv)
    numbers = args.pr or [
        row["number"]
        for row in _gh_json(
            [
                "pr",
                "list",
                "--repo",
                args.repository,
                "--state",
                "open",
                "--limit",
                "1000",
                "--json",
                "number",
            ]
        )
    ]
    output: list[dict[str, Any]] = []
    for number in numbers:
        meta = _gh_json(
            [
                "pr",
                "view",
                str(number),
                "--repo",
                args.repository,
                "--json",
                "number,isDraft,autoMergeRequest,baseRefName,files,changedFiles,labels",
            ]
        )
        decision = decide(meta)
        row = {"number": number, "eligible": decision.eligible, "reason": decision.reason}
        if decision.eligible:
            completed = subprocess.run(
                [
                    "gh",
                    "pr",
                    "merge",
                    str(number),
                    "--repo",
                    args.repository,
                    "--auto",
                    "--squash",
                ],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="strict",
                shell=False,
            )
            row["enrolled"] = completed.returncode == 0
            row["error"] = completed.stderr.strip() if completed.returncode else ""
        output.append(row)
    print(json.dumps(output, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
