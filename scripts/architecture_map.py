#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Compile Ember's domain-authority policy against one exact Git tree.

This module produces architecture and migration evidence only. It does not move source,
mutate external roots, authorize execution, or establish model/capability credit.
"""

from __future__ import annotations

import fnmatch
import json
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = "ember-domain-authority-policy-v1"
GOAL_ID = "EMBER-02"
WORKSTREAM_ID = "EMBER-02A"
NEXT_EXECUTED_OUTCOME = "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember"
OWNERS = [
    "Model",
    "Data",
    "Training",
    "Evaluation",
    "Runtime",
    "Lab",
    "Infrastructure",
    "Governance",
]
DISPOSITIONS = [
    "MOVE",
    "RETAIN_STABLE",
    "MERGE",
    "ARCHIVE",
    "EXTERNALIZE",
    "DELETE_REDUNDANT",
    "DEFERRED_DEPENDENCY",
]
DEFERRAL_FIELDS = {
    "id",
    "owner",
    "issue",
    "predicate",
    "evidence_selector",
    "failure_state",
}


class ArchitectureMapError(RuntimeError):
    """A named fail-closed architecture-map refusal."""

    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def canonical_json(value: object) -> bytes:
    """Return the receipt convention's UTF-8 canonical JSON bytes."""

    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _require(condition: bool, code: str, detail: str) -> None:
    if not condition:
        raise ArchitectureMapError(code, detail)


def validate_policy(policy: Mapping[str, Any]) -> None:
    """Validate policy invariants required before inspecting any tree path."""

    _require(policy.get("schema_version") == SCHEMA_VERSION, "POLICY_SCHEMA_MISMATCH", str(policy.get("schema_version")))
    _require(policy.get("goal_id") == GOAL_ID, "POLICY_GOAL_MISMATCH", str(policy.get("goal_id")))
    _require(policy.get("workstream_id") == WORKSTREAM_ID, "POLICY_WORKSTREAM_MISMATCH", str(policy.get("workstream_id")))
    _require(
        policy.get("next_executed_outcome") == NEXT_EXECUTED_OUTCOME,
        "POLICY_OUTCOME_MISMATCH",
        str(policy.get("next_executed_outcome")),
    )
    _require(policy.get("owners") == OWNERS, "POLICY_OWNER_SET_MISMATCH", repr(policy.get("owners")))
    _require(
        policy.get("dispositions") == DISPOSITIONS,
        "POLICY_DISPOSITION_SET_MISMATCH",
        repr(policy.get("dispositions")),
    )

    deferrals = policy.get("deferrals")
    _require(isinstance(deferrals, list), "MALFORMED_DEFERRALS", "deferrals must be a list")
    deferral_ids: set[str] = set()
    for row in deferrals:
        _require(isinstance(row, dict), "MALFORMED_DEFERRAL", "non-object")
        row_id = str(row.get("id", ""))
        _require(DEFERRAL_FIELDS.issubset(row), "MALFORMED_DEFERRAL", row_id)
        _require(row_id not in deferral_ids, "DUPLICATE_DEFERRAL", row_id)
        _require(row.get("owner") in OWNERS, "MALFORMED_DEFERRAL", row_id)
        _require(isinstance(row.get("issue"), int) and row["issue"] > 0, "MALFORMED_DEFERRAL", row_id)
        for field in ("predicate", "evidence_selector", "failure_state"):
            _require(isinstance(row.get(field), str) and bool(row[field].strip()), "MALFORMED_DEFERRAL", row_id)
        deferral_ids.add(row_id)

    path_rules = policy.get("path_rules")
    _require(isinstance(path_rules, list), "MALFORMED_PATH_RULES", "path_rules must be a list")
    rule_ids: set[str] = set()
    for row in path_rules:
        _require(isinstance(row, dict), "MALFORMED_PATH_RULE", "non-object")
        rule_id = str(row.get("id", ""))
        _require(bool(rule_id), "MALFORMED_PATH_RULE", "missing id")
        _require(rule_id not in rule_ids, "DUPLICATE_PATH_RULE", rule_id)
        _require(isinstance(row.get("include"), list) and bool(row["include"]), "MALFORMED_PATH_RULE", rule_id)
        _require(isinstance(row.get("exclude"), list), "MALFORMED_PATH_RULE", rule_id)
        _require(row.get("owner") in OWNERS, "MALFORMED_PATH_RULE", rule_id)
        _require(row.get("disposition") in DISPOSITIONS, "MALFORMED_PATH_RULE", rule_id)
        _require(isinstance(row.get("touch_set_id"), str) and bool(row["touch_set_id"]), "MALFORMED_PATH_RULE", rule_id)
        if row.get("disposition") == "DEFERRED_DEPENDENCY":
            deferral_id = row.get("deferral_id")
            _require(isinstance(deferral_id, str) and bool(deferral_id), "UNDECLARED_DEFERRAL", str(deferral_id))
        elif "deferral_id" in row:
            raise ArchitectureMapError("DEFERRAL_ON_NONDEFERRED_RULE", rule_id)
        rule_ids.add(rule_id)

    backend = policy.get("backend_authority")
    _require(isinstance(backend, dict), "MALFORMED_BACKEND_AUTHORITY", "missing object")
    _require(backend.get("name") == "setuptools", "MALFORMED_BACKEND_AUTHORITY", "name")
    _require(backend.get("version") == "84.0.0", "MALFORMED_BACKEND_AUTHORITY", "version")
    _require(
        backend.get("artifact") == "setuptools-84.0.0-py3-none-any.whl",
        "MALFORMED_BACKEND_AUTHORITY",
        "artifact",
    )
    _require(
        backend.get("sha256") == "51a52592b3b99e102b609654876bd65f19f999935166d1352678931132b0c670",
        "MALFORMED_BACKEND_AUTHORITY",
        "sha256",
    )
    _require(
        backend.get("substitution_failures") == ["HASH_MISMATCH_REFUSED", "ONLY_BINARY_REFUSED"],
        "MALFORMED_BACKEND_AUTHORITY",
        "substitution_failures",
    )


def validate_backend_artifact(actual_sha256: str, policy: Mapping[str, Any]) -> None:
    """Admit only the policy's exact wheel identity."""

    validate_policy(policy)
    expected = str(policy["backend_authority"]["sha256"])
    if actual_sha256.lower() != expected:
        raise ArchitectureMapError(
            "BACKEND_ARTIFACT_REFUSED",
            f"expected {expected}, got {actual_sha256.lower()}",
        )


def _normalize_repo_path(value: str) -> str:
    normalized = PurePosixPath(value.replace("\\", "/")).as_posix()
    if normalized in {"", "."} or normalized.startswith("../") or normalized.startswith("/"):
        raise ArchitectureMapError("INVALID_REPOSITORY_PATH", value)
    return normalized


def _matches(rule: Mapping[str, Any], path: str) -> bool:
    included = any(fnmatch.fnmatchcase(path, pattern) for pattern in rule["include"])
    excluded = any(fnmatch.fnmatchcase(path, pattern) for pattern in rule["exclude"])
    return included and not excluded


def classify_paths(
    paths: Sequence[str],
    policy: Mapping[str, Any],
) -> list[dict[str, object]]:
    """Return one stable owner/disposition row per path; refuse gaps and overlap."""

    validate_policy(policy)
    deferral_ids = {str(row["id"]) for row in policy["deferrals"]}
    rows: list[dict[str, object]] = []
    seen: set[str] = set()
    for raw_path in sorted(paths, key=lambda item: item.replace("\\", "/")):
        path = _normalize_repo_path(raw_path)
        _require(path not in seen, "DUPLICATE_TRACKED_PATH", path)
        seen.add(path)
        matches = [row for row in policy["path_rules"] if _matches(row, path)]
        if not matches:
            raise ArchitectureMapError("UNCOVERED_PATH", path)
        if len(matches) > 1:
            rule_ids = ",".join(sorted(str(row["id"]) for row in matches))
            raise ArchitectureMapError("OVERLAPPING_PATH_RULES", f"{path}: {rule_ids}")
        rule = matches[0]
        deferral_id = rule.get("deferral_id")
        if rule["disposition"] == "DEFERRED_DEPENDENCY" and deferral_id not in deferral_ids:
            raise ArchitectureMapError("UNDECLARED_DEFERRAL", str(deferral_id))
        rows.append(
            {
                "path": path,
                "owner": rule["owner"],
                "disposition": rule["disposition"],
                "rule_id": rule["id"],
                "touch_set_id": rule["touch_set_id"],
                "deferral_id": deferral_id,
            }
        )
    return rows


def _git(repo: Path, *args: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise ArchitectureMapError("GIT_ERROR", detail or " ".join(args))
    return result.stdout


def git_identity(repo: Path) -> dict[str, str]:
    """Bind the exact commit and tree expanded by a receipt."""

    return {
        "commit_sha": _git(repo, "rev-parse", "HEAD").decode("ascii").strip(),
        "tree_sha": _git(repo, "rev-parse", "HEAD^{tree}").decode("ascii").strip(),
    }


def tracked_paths(repo: Path) -> list[str]:
    """Return the exact Git-index path denominator in stable POSIX order."""

    raw = _git(repo, "ls-files", "-z")
    paths = [item.decode("utf-8", errors="strict") for item in raw.split(b"\0") if item]
    return sorted(_normalize_repo_path(item) for item in paths)
