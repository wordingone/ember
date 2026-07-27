#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Fail-closed validator for the public Ember roadmap projection."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
MILESTONE_IDS = tuple(f"EMBER-{number:02d}" for number in range(12))
SHA256 = re.compile(r"^[0-9a-f]{64}$")
CLAUSE_MARKER = re.compile(r"^<!-- clause-id: ([A-Z0-9.-]+) -->$", re.MULTILINE)


class RoadmapValidationError(ValueError):
    pass


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RoadmapValidationError(f"cannot read valid JSON {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise RoadmapValidationError(f"JSON root must be an object: {path}")
    return payload


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _unique_rows(rows: Any, key: str, noun: str) -> dict[Any, dict[str, Any]]:
    if not isinstance(rows, list):
        raise RoadmapValidationError(f"{noun} rows must be a list")
    result: dict[Any, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or key not in row:
            raise RoadmapValidationError(f"invalid {noun} row")
        value = row[key]
        if value in result:
            raise RoadmapValidationError(f"duplicate {noun} {value}")
        result[value] = row
    return result


def _require_ids(actual: set[str], noun: str) -> None:
    expected = set(MILESTONE_IDS)
    if actual != expected:
        raise RoadmapValidationError(
            f"{noun} milestone IDs differ: missing={sorted(expected-actual)}, "
            f"extra={sorted(actual-expected)}"
        )


def _issue_milestone_id(issue: dict[str, Any]) -> str | None:
    milestone = issue.get("milestone")
    if milestone is None:
        return None
    if not isinstance(milestone, dict):
        raise RoadmapValidationError("issue milestone is not an object")
    match = re.match(r"^(EMBER-\d{2})(?::|\s|$)", str(milestone.get("title", "")))
    if match and match.group(1) in MILESTONE_IDS:
        return match.group(1)
    return None


def _acyclic(edges: dict[str, list[str]], noun: str) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> None:
        if node in visiting:
            raise RoadmapValidationError(f"{noun} cycle")
        if node in visited:
            return
        visiting.add(node)
        for dependency in edges.get(node, []):
            if dependency not in edges:
                raise RoadmapValidationError(f"unknown {noun} dependency {dependency}")
            visit(dependency)
        visiting.remove(node)
        visited.add(node)

    for node in edges:
        visit(node)


def _extract_clause(text: str, clause_id: str) -> bytes:
    marker = f"<!-- clause-id: {clause_id} -->"
    if text.count(marker) != 1:
        raise RoadmapValidationError(
            f"public clause marker count for {clause_id} is {text.count(marker)}"
        )
    tail = text.split(marker, 1)[1].lstrip("\r\n")
    boundaries = [
        index
        for token in ("\n<!-- clause-id:", "\n## ", "\n### ")
        if (index := tail.find(token)) >= 0
    ]
    block = tail[: min(boundaries) if boundaries else len(tail)].strip()
    return block.encode("utf-8")


def _validate_contracts(root: Path, crosswalk: dict[str, Any], source: dict[str, Any]) -> int:
    contracts = _unique_rows(crosswalk.get("contracts"), "goal_id", "contract")
    sources = _unique_rows(source.get("contracts"), "goal_id", "source contract")
    _require_ids(set(contracts), "contract")
    _require_ids(set(sources), "source contract")
    seen_clauses: set[str] = set()
    clause_count = 0
    for goal_id in MILESTONE_IDS:
        contract = contracts[goal_id]
        source_row = sources[goal_id]
        for field in ("source_sha256", "public_sha256"):
            if not SHA256.fullmatch(str(contract.get(field, ""))):
                raise RoadmapValidationError(f"invalid {field} for {goal_id}")
        if contract["source_sha256"] != source_row.get("source_sha256"):
            raise RoadmapValidationError(f"source hash mismatch for {goal_id}")
        public_path = root / str(contract.get("public_path", ""))
        try:
            public_bytes = public_path.read_bytes()
            public_text = public_bytes.decode("utf-8")
        except (OSError, UnicodeError) as exc:
            raise RoadmapValidationError(f"cannot read public contract {goal_id}") from exc
        if _sha256(public_bytes) != contract["public_sha256"]:
            raise RoadmapValidationError(f"public contract hash mismatch for {goal_id}")
        clauses = contract.get("clauses")
        if not isinstance(clauses, list):
            raise RoadmapValidationError(f"clauses must be a list for {goal_id}")
        if len(clauses) != source_row.get("normative_clause_count"):
            raise RoadmapValidationError(f"clause count mismatch for {goal_id}")
        for clause in clauses:
            clause_id = str(clause.get("clause_id", ""))
            if clause_id in seen_clauses:
                raise RoadmapValidationError(f"duplicate clause ID {clause_id}")
            seen_clauses.add(clause_id)
            block = _extract_clause(public_text, clause_id)
            if _sha256(block) != clause.get("public_sha256"):
                raise RoadmapValidationError(f"public clause hash mismatch for {clause_id}")
            relation = clause.get("relation")
            if relation not in {"verbatim", "translated_public_equivalent"}:
                raise RoadmapValidationError(f"invalid clause relation for {clause_id}")
            clause_count += 1
    return clause_count


def _validate_execution_graph(root: Path, graph: dict[str, Any]) -> None:
    nodes = _unique_rows(graph.get("nodes"), "id", "execution graph node")
    _require_ids(set(nodes), "execution graph")
    edges: dict[str, list[str]] = {}
    for milestone_id, node in nodes.items():
        expected = f"docs/roadmap/milestones/{milestone_id}.md"
        if node.get("contract") != expected or not (root / expected).is_file():
            raise RoadmapValidationError(f"invalid contract path for {milestone_id}")
        dependencies = node.get("depends_on")
        if not isinstance(dependencies, list):
            raise RoadmapValidationError(f"invalid dependencies for {milestone_id}")
        edges[milestone_id] = dependencies
    _acyclic(edges, "execution graph dependency")
    program = graph.get("program", {})
    for key in ("target_milestone", "active_certificate_gate"):
        if program.get(key) not in nodes:
            raise RoadmapValidationError(f"unknown {key}")


def _validate_issues(
    census: dict[str, Any],
    reconciliation: dict[str, Any],
    projection: dict[str, Any],
) -> int:
    master = census.get("public_master_sha")
    if master is None:
        master = census.get("source_master_sha")
    if not GIT_SHA.fullmatch(str(master or "")):
        raise RoadmapValidationError("invalid census source master")
    for payload in (reconciliation, projection):
        if payload.get("source_master_sha") != master:
            raise RoadmapValidationError("source master mismatch")
    census_rows = _unique_rows(census.get("issues"), "number", "census issue")
    reconciliation_rows = _unique_rows(
        reconciliation.get("issues"), "number", "reconciliation issue"
    )
    mutation_rows = _unique_rows(
        projection.get("issue_mutations"), "number", "issue mutation"
    )
    if set(census_rows) != set(reconciliation_rows):
        raise RoadmapValidationError("issue census and reconciliation differ")
    if set(census_rows) != set(mutation_rows):
        raise RoadmapValidationError("issue census and projection differ")
    count = len(census_rows)
    for payload in (reconciliation, projection):
        if payload.get("source_issue_count") != count:
            raise RoadmapValidationError("source issue count mismatch")
    if census.get("counts", {}).get("open_issues") != count:
        raise RoadmapValidationError("census open issue count mismatch")
    for number, issue in census_rows.items():
        if issue.get("state") != "open" or not SHA256.fullmatch(
            str(issue.get("body_sha256", ""))
        ):
            raise RoadmapValidationError(f"invalid census issue {number}")
        row = reconciliation_rows[number]
        if (
            row.get("title") != issue.get("title")
            or row.get("body_sha256") != issue.get("body_sha256")
            or row.get("snapshot_updated_at") != issue.get("updated_at")
        ):
            raise RoadmapValidationError(f"stale reconciliation issue {number}")
        affected = row.get("affected_milestones")
        if not isinstance(affected, list) or not affected:
            raise RoadmapValidationError(f"missing affected milestones for issue {number}")
        for milestone_id in affected:
            if milestone_id not in MILESTONE_IDS:
                raise RoadmapValidationError(
                    f"unknown affected milestone {milestone_id}"
                )
        disposition = row.get("disposition")
        if disposition not in {"single_milestone", "cross_cutting", "mixed_historical"}:
            raise RoadmapValidationError(f"invalid disposition for issue {number}")
        if row.get("intended_state") != "open":
            raise RoadmapValidationError(f"issue {number} is not preserved open")
        if disposition == "single_milestone":
            if len(affected) != 1 or not row.get("desired_parent_subissue"):
                raise RoadmapValidationError(f"invalid single milestone issue {number}")
        elif row.get("desired_parent_subissue") is not None:
            raise RoadmapValidationError(f"cross-cutting issue {number} has a parent")
        mutation = mutation_rows[number]
        if mutation.get("close") is not False:
            raise RoadmapValidationError("issue closure mutation is forbidden")
        if (
            mutation.get("expected_body_sha256") != issue.get("body_sha256")
            or mutation.get("expected_updated_at") != issue.get("updated_at")
            or mutation.get("expected_labels") != issue.get("labels")
            or mutation.get("expected_milestone_id") != _issue_milestone_id(issue)
            or mutation.get("add_labels") != row.get("desired_labels")
        ):
            raise RoadmapValidationError(f"stale issue mutation {number}")
    if projection.get("issue_closures") != []:
        raise RoadmapValidationError("issue closure mutation is forbidden")
    return count


def _validate_projection(projection: dict[str, Any]) -> None:
    milestones = _unique_rows(projection.get("milestones"), "milestone_id", "milestone")
    parents = _unique_rows(projection.get("parent_issues"), "milestone_id", "parent issue")
    _require_ids(set(milestones), "projection")
    _require_ids(set(parents), "parent issue")
    tracking_keys = {row.get("tracking_key") for row in parents.values()}
    if len(tracking_keys) != 12 or None in tracking_keys:
        raise RoadmapValidationError("invalid parent tracking keys")
    edges: dict[str, list[str]] = {}
    key_to_id = {row["tracking_key"]: milestone_id for milestone_id, row in parents.items()}
    for milestone_id, row in parents.items():
        dependencies = row.get("depends_on")
        if not isinstance(dependencies, list):
            raise RoadmapValidationError(f"invalid parent dependencies for {milestone_id}")
        try:
            edges[milestone_id] = [key_to_id[value] for value in dependencies]
        except KeyError as exc:
            raise RoadmapValidationError(f"unknown parent dependency {exc.args[0]}") from exc
    _acyclic(edges, "parent dependency")
    label_rows = _unique_rows(projection.get("labels"), "name", "label")
    for milestone_id in MILESTONE_IDS:
        if f"affects:{milestone_id}" not in label_rows:
            raise RoadmapValidationError(f"missing affects label for {milestone_id}")
    for mutation in projection.get("issue_mutations", []):
        for label in mutation.get("add_labels", []):
            if label not in label_rows:
                raise RoadmapValidationError(f"undefined issue label {label}")
        parent_key = mutation.get("add_as_subissue_of")
        if parent_key is not None and parent_key not in tracking_keys:
            raise RoadmapValidationError(f"unknown parent key {parent_key}")
        milestone_id = mutation.get("set_milestone")
        if milestone_id is not None and milestone_id not in milestones:
            raise RoadmapValidationError(f"unknown issue milestone {milestone_id}")


def validate_repository(root: Path) -> dict[str, Any]:
    root = root.resolve()
    manifests = root / "manifests" / "roadmap"
    crosswalk = _read_json(manifests / "clause-crosswalk-v1.json")
    source = _read_json(manifests / "source-contracts-v1.json")
    census = _read_json(manifests / "public-issue-census-v1.json")
    reconciliation = _read_json(manifests / "issue-reconciliation-v1.json")
    projection = _read_json(manifests / "github-projection-v1.json")
    graph = _read_json(root / "docs" / "roadmap" / "execution-graph.json")
    clause_count = _validate_contracts(root, crosswalk, source)
    _validate_execution_graph(root, graph)
    _validate_projection(projection)
    issue_count = _validate_issues(census, reconciliation, projection)
    return {
        "status": "ROADMAP_VALID",
        "contract_count": len(MILESTONE_IDS),
        "clause_count": clause_count,
        "issue_count": issue_count,
        "issue_closures": 0,
        "source_master_sha": projection["source_master_sha"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    try:
        print(json.dumps(validate_repository(args.root), sort_keys=True))
    except RoadmapValidationError as exc:
        print(f"ROADMAP_INVALID: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
