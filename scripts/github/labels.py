#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Live-safe label audit, plan, apply, and verify entry point."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.parse
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.github.labels_engine import (  # noqa: E402,F401
    MigrationError,
    RecordingClient,
    apply_plan,
    build_plan,
    canonical_bytes,
    canonical_sha256,
    load_data,
    receipt_metadata,
    write_canonical,
)
from scripts.github.snapshot import Gh  # noqa: E402


def _prefix(wrapper: Path | None) -> list[str]:
    return (
        ["powershell.exe", "-NoProfile", "-File", str(wrapper.resolve())]
        if wrapper
        else ["gh"]
    )


def capture_label_snapshot(gh: Gh) -> dict[str, Any]:
    labels = sorted(
        (
            {
                "name": row["name"],
                "color": row["color"],
                "description": row.get("description") or "",
            }
            for row in gh.paginate("labels?per_page=100")
        ),
        key=lambda row: row["name"],
    )
    items = []
    for row in gh.paginate(
        "issues?state=all&per_page=100&sort=created&direction=asc"
    ):
        items.append(
            {
                "number": row["number"],
                "node_id": row["node_id"],
                "item_type": "pull_request" if "pull_request" in row else "issue",
                "state": row["state"].upper(),
                "title": row["title"],
                "labels": sorted(label["name"] for label in row.get("labels", [])),
            }
        )
    return {
        "schema_version": "ember-github-label-snapshot/v1",
        "repository": gh.repository,
        "captured_at": gh.api("commits/master")["commit"]["committer"]["date"],
        "labels": labels,
        "items": items,
    }


class GhClient:
    def __init__(self, gh: Gh) -> None:
        self.gh = gh

    def _call(self, args: list[str]) -> None:
        completed = subprocess.run(
            [*self.gh.command_prefix, *args],
            check=False,
            text=True,
            encoding="utf-8",
            errors="strict",
            capture_output=True,
            shell=False,
        )
        if completed.returncode:
            raise MigrationError(
                f"gh {' '.join(args)} failed: {completed.stderr.strip()}"
            )

    def create_or_update_label(
        self, *, action: str, name: str, color: str, description: str
    ) -> None:
        if action == "create":
            endpoint = f"repos/{self.gh.repository}/labels"
            method = "POST"
        elif action == "update":
            encoded = urllib.parse.quote(name, safe="")
            endpoint = f"repos/{self.gh.repository}/labels/{encoded}"
            method = "PATCH"
        else:
            raise MigrationError(f"unknown label action {action}")
        self._call(
            [
                "api",
                "--method",
                method,
                endpoint,
                "-f",
                f"name={name}",
                "-f",
                f"color={color}",
                "-f",
                f"description={description}",
            ]
        )

    def edit_item_labels(
        self, *, item_type: str, number: int, add: list[str], remove: list[str]
    ) -> None:
        endpoint = f"repos/{self.gh.repository}/issues/{number}/labels"
        for name in add:
            self._call(
                [
                    "api",
                    "--method",
                    "POST",
                    endpoint,
                    "-f",
                    f"labels[]={name}",
                ]
            )
        for name in remove:
            encoded = urllib.parse.quote(name, safe="")
            self._call(["api", "--method", "DELETE", f"{endpoint}/{encoded}"])

    def delete_label(self, name: str) -> None:
        encoded = urllib.parse.quote(name, safe="")
        self._call(
            [
                "api",
                "--method",
                "DELETE",
                f"repos/{self.gh.repository}/labels/{encoded}",
            ]
        )


def verify_live(snapshot: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    desired = {row["name"]: row for row in manifest["labels"]}
    live = {row["name"]: row for row in snapshot["labels"]}
    errors: list[str] = []
    for name, row in desired.items():
        actual = live.get(name)
        if actual is None:
            errors.append(f"missing label {name}")
        elif actual["color"].upper() != row["color"].upper():
            errors.append(f"{name}: color mismatch")
        elif actual["description"] != row["description"]:
            errors.append(f"{name}: description mismatch")
    unknown = sorted(set(live) - set(desired))
    if unknown:
        errors.append("unknown live labels: " + ", ".join(unknown))
    deprecated = {
        row["name"] for row in manifest["labels"] if row.get("deprecated") is True
    }
    for item in snapshot["items"]:
        if item["state"] == "OPEN" and deprecated.intersection(item["labels"]):
            errors.append(
                f"{item['item_type']} #{item['number']}: deprecated label in use"
            )
    return {
        "schema_version": "ember-label-live-verification/v1",
        "repository": snapshot["repository"],
        "snapshot_sha256": canonical_sha256(snapshot),
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("audit", "plan", "apply", "verify"))
    parser.add_argument("--repository", default="wordingone/ember")
    parser.add_argument("--gh-wrapper", type=Path)
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--migrations", type=Path, required=True)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--confirm-apply", action="store_true")
    args = parser.parse_args(argv)

    gh = Gh(_prefix(args.gh_wrapper), args.repository)
    snapshot = (
        load_data(args.snapshot)
        if args.snapshot
        else capture_label_snapshot(gh)
    )
    if snapshot.get("schema_version") == "ember-label-audit/v1":
        snapshot = snapshot["snapshot"]
    manifest = load_data(args.manifest)
    migrations = load_data(args.migrations)

    if args.command == "audit":
        value: dict[str, Any] = {
            "schema_version": "ember-label-audit/v1",
            "repository": snapshot["repository"],
            "snapshot": snapshot,
            "snapshot_sha256": canonical_sha256(snapshot),
        }
    elif args.command == "plan":
        value = build_plan(snapshot, manifest, migrations)
    elif args.command == "apply":
        if not args.confirm_apply or args.plan is None:
            raise MigrationError("apply requires --plan and --confirm-apply")
        envelope = load_data(args.plan)
        fresh = capture_label_snapshot(gh)
        value = apply_plan(
            envelope,
            client=GhClient(gh),
            apply=True,
            current_snapshot=fresh,
        )
        post = capture_label_snapshot(gh)
        value["post_verification"] = verify_live(post, manifest)
        value["receipt_sha256"] = canonical_sha256(
            {k: v for k, v in value.items() if k != "receipt_sha256"}
        )
    else:
        value = verify_live(capture_label_snapshot(gh), manifest)
        value.update(receipt_metadata("EMBER-GITHUB-LABEL-VERIFICATION"))
        value["receipt_sha256"] = canonical_sha256(
            {k: v for k, v in value.items() if k != "receipt_sha256"}
        )
    write_canonical(args.output, value)
    print(json.dumps(value, sort_keys=True))
    return 0 if value.get("status", value.get("post_verification", {}).get("status")) != "FAIL" else 1


if __name__ == "__main__":
    raise SystemExit(main())
