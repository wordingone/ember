#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Plan, apply, and verify Ember's native GitHub sub-issue relationships."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol


class RelationshipError(RuntimeError):
    pass


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _authority_binding() -> dict[str, str]:
    return {
        "goal_id": "EMBER-02",
        "workstream_id": "EMBER-02A",
        "next_executed_outcome": (
            "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember"
        ),
    }


def _receipt_metadata(ticket: str) -> dict[str, Any]:
    return {
        "authority": _authority_binding(),
        "ticket": ticket,
        "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "sha_convention": (
            "sha256 fields use lowercase hexadecimal SHA-256 over canonical "
            "UTF-8 JSON (sort_keys=True,separators=(',',':'),ensure_ascii=False); "
            "receipt_sha256 excludes its own field"
        ),
    }


class Client(Protocol):
    def children(self, parent: int) -> dict[int, str]: ...

    def add(self, parent_node_id: str, child_node_id: str) -> None: ...


class GhClient:
    def __init__(self, wrapper: Path, repository: str) -> None:
        self.prefix = [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(wrapper.resolve()),
        ]
        self.repository = repository
        self.owner, self.name = repository.split("/", 1)

    def _run(self, args: list[str]) -> dict[str, Any]:
        result = subprocess.run(
            [*self.prefix, *args],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="strict",
            shell=False,
        )
        if result.returncode:
            raise RelationshipError(result.stderr.strip() or result.stdout.strip())
        try:
            value = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise RelationshipError("GitHub returned non-JSON") from exc
        if not isinstance(value, dict):
            raise RelationshipError("GitHub returned an invalid GraphQL envelope")
        return value

    def children(self, parent: int) -> dict[int, str]:
        query = """
query($owner:String!,$name:String!,$number:Int!,$cursor:String) {
  repository(owner:$owner,name:$name) {
    issue(number:$number) {
      subIssues(first:100,after:$cursor) {
        nodes { id number }
        pageInfo { hasNextPage endCursor }
      }
    }
  }
}"""
        cursor: str | None = None
        rows: dict[int, str] = {}
        while True:
            args = [
                "api",
                "graphql",
                "-f",
                f"query={query}",
                "-F",
                f"owner={self.owner}",
                "-F",
                f"name={self.name}",
                "-F",
                f"number={parent}",
            ]
            if cursor is not None:
                args.extend(["-F", f"cursor={cursor}"])
            value = self._run(args)
            try:
                connection = value["data"]["repository"]["issue"]["subIssues"]
            except (KeyError, TypeError) as exc:
                raise RelationshipError(
                    f"parent #{parent}: sub-issue query unavailable"
                ) from exc
            for row in connection["nodes"]:
                rows[int(row["number"])] = str(row["id"])
            if not connection["pageInfo"]["hasNextPage"]:
                return rows
            cursor = connection["pageInfo"]["endCursor"]

    def add(self, parent_node_id: str, child_node_id: str) -> None:
        query = """
mutation($issueId:ID!,$subIssueId:ID!) {
  addSubIssue(input:{issueId:$issueId,subIssueId:$subIssueId}) {
    issue { id }
    subIssue { id }
  }
}"""
        value = self._run(
            [
                "api",
                "graphql",
                "-f",
                f"query={query}",
                "-F",
                f"issueId={parent_node_id}",
                "-F",
                f"subIssueId={child_node_id}",
            ]
        )
        try:
            result = value["data"]["addSubIssue"]
        except (KeyError, TypeError) as exc:
            raise RelationshipError("addSubIssue returned no result") from exc
        if (
            result["issue"]["id"] != parent_node_id
            or result["subIssue"]["id"] != child_node_id
        ):
            raise RelationshipError("addSubIssue returned mismatched identities")


def build_plan(review_plan: dict[str, Any]) -> dict[str, Any]:
    node_by_number = {row["number"]: row["node_id"] for row in review_plan["rows"]}
    edges = []
    for row in review_plan["rows"]:
        parent = row.get("native_parent_issue")
        if parent is None:
            continue
        if parent == row["number"] or parent not in node_by_number:
            raise RelationshipError(f"issue #{row['number']}: invalid parent")
        edges.append(
            {
                "parent": parent,
                "parent_node_id": node_by_number[parent],
                "child": row["number"],
                "child_node_id": row["node_id"],
            }
        )
    edges.sort(key=lambda row: (row["parent"], row["child"]))
    if len({row["child"] for row in edges}) != len(edges):
        raise RelationshipError("a child has multiple planned parents")
    result = {
        "authority": _authority_binding(),
        "schema_version": "ember-native-relationship-plan/v1",
        "repository": review_plan["repository"],
        "review_plan_sha256": review_plan["plan_sha256"],
        "edges": edges,
        "claim_boundary": (
            "native hierarchy only; no dependency, acceptance, closure, "
            "training, research, or capability claim"
        ),
    }
    result["plan_sha256"] = _sha({k: v for k, v in result.items() if k != "authority"})
    return result


def apply(plan: dict[str, Any], client: Client, *, confirm: bool) -> dict[str, Any]:
    if not confirm:
        raise RelationshipError("apply requires --confirm-apply")
    expected = _sha(
        {
            key: value
            for key, value in plan.items()
            if key not in {"authority", "plan_sha256"}
        }
    )
    if expected != plan.get("plan_sha256"):
        raise RelationshipError("relationship plan digest mismatch")
    by_parent: dict[int, list[dict[str, Any]]] = {}
    for edge in plan["edges"]:
        by_parent.setdefault(edge["parent"], []).append(edge)
    added = already_present = 0
    for parent, edges in sorted(by_parent.items()):
        present = client.children(parent)
        for edge in edges:
            if edge["child"] in present:
                if present[edge["child"]] != edge["child_node_id"]:
                    raise RelationshipError(
                        f"issue #{edge['child']}: live node identity drift"
                    )
                already_present += 1
                continue
            client.add(edge["parent_node_id"], edge["child_node_id"])
            added += 1
    verify(plan, client)
    receipt = {
        **_receipt_metadata("EMBER-GITHUB-NATIVE-RELATIONSHIP-APPLY"),
        "schema_version": "ember-native-relationship-apply/v1",
        "repository": plan["repository"],
        "plan_sha256": plan["plan_sha256"],
        "edge_count": len(plan["edges"]),
        "added_count": added,
        "already_present_count": already_present,
        "status": "VERIFIED",
    }
    receipt["receipt_sha256"] = _sha(receipt)
    return receipt


def verify(plan: dict[str, Any], client: Client) -> None:
    by_parent: dict[int, dict[int, str]] = {}
    for edge in plan["edges"]:
        by_parent.setdefault(edge["parent"], {})[edge["child"]] = edge["child_node_id"]
    for parent, expected in sorted(by_parent.items()):
        actual = client.children(parent)
        missing = sorted(set(expected) - set(actual))
        mismatched = sorted(
            number
            for number in set(expected) & set(actual)
            if expected[number] != actual[number]
        )
        if missing or mismatched:
            raise RelationshipError(
                f"parent #{parent}: missing={missing}, mismatched={mismatched}"
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("plan", "apply", "verify"))
    parser.add_argument("--review-plan", type=Path)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--gh-wrapper", type=Path)
    parser.add_argument("--confirm-apply", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "plan":
        if args.review_plan is None:
            raise RelationshipError("plan requires --review-plan")
        value = build_plan(json.loads(args.review_plan.read_text("utf-8")))
    else:
        if args.plan is None or args.gh_wrapper is None:
            raise RelationshipError(f"{args.command} requires --plan and --gh-wrapper")
        plan = json.loads(args.plan.read_text("utf-8"))
        client = GhClient(args.gh_wrapper, plan["repository"])
        if args.command == "apply":
            value = apply(plan, client, confirm=args.confirm_apply)
        else:
            verify(plan, client)
            value = {
                **_receipt_metadata("EMBER-GITHUB-NATIVE-RELATIONSHIP-VERIFY"),
                "schema_version": "ember-native-relationship-verify/v1",
                "repository": plan["repository"],
                "plan_sha256": plan["plan_sha256"],
                "edge_count": len(plan["edges"]),
                "status": "VERIFIED",
            }
            value["receipt_sha256"] = _sha(value)
    args.output.write_bytes(_canonical(value) + b"\n")
    print(json.dumps(value, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
