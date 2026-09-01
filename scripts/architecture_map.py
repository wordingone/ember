#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Compile Ember's domain-authority policy against one exact Git tree.

This module produces architecture and migration evidence only. It does not move source,
mutate external roots, authorize execution, or establish model/capability credit.
"""

from __future__ import annotations

import ast
import argparse
import fnmatch
import hashlib
import json
import re
import subprocess
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence


_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0


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
        strategy = row.get("rollback_unit_strategy")
        _require(
            strategy in {"PER_AUTHORITATIVE_SWITCH_TARGET", "EXPLICIT_KEY", "NOT_A_SWITCH"},
            "MALFORMED_PATH_RULE",
            f"{rule_id}: rollback_unit_strategy",
        )
        is_switch = row.get("disposition") not in {"RETAIN_STABLE", "DEFERRED_DEPENDENCY"}
        _require(
            strategy != "NOT_A_SWITCH" if is_switch else strategy == "NOT_A_SWITCH",
            "MALFORMED_PATH_RULE",
            f"{rule_id}: rollback strategy/disposition mismatch",
        )
        if strategy == "EXPLICIT_KEY":
            _require(
                isinstance(row.get("rollback_unit_key"), str) and bool(row["rollback_unit_key"]),
                "MALFORMED_PATH_RULE",
                f"{rule_id}: rollback_unit_key",
            )
        else:
            _require("rollback_unit_key" not in row, "MALFORMED_PATH_RULE", f"{rule_id}: unexpected rollback_unit_key")
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
                "rollback_unit_strategy": rule["rollback_unit_strategy"],
                "deferral_id": deferral_id,
                **({"rollback_unit_key": rule["rollback_unit_key"]} if "rollback_unit_key" in rule else {}),
            }
        )
    return rows


def _git(repo: Path, *args: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        creationflags=_NO_WINDOW,
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


def verify_consumer_completeness(
    discovered: Sequence[Mapping[str, object]],
    declared: Sequence[Mapping[str, object]],
) -> None:
    """Refuse when a discovered consumer is absent from the declared census."""

    def identity(row: Mapping[str, object]) -> tuple[str, str, str]:
        return (
            str(row.get("consumer_path", "")),
            str(row.get("target", "")),
            str(row.get("discovery_class", "")),
        )

    declared_ids = {identity(row) for row in declared}
    missing = sorted(identity(row) for row in discovered if identity(row) not in declared_ids)
    if missing:
        consumer_path, target, _ = missing[0]
        raise ArchitectureMapError("OMITTED_CONSUMER", f"{consumer_path} -> {target}")


def scan_python_source(path: str, source: str) -> dict[str, list[dict[str, object]]]:
    """Parse Python imports and active import-path surgery from real source text."""

    source = source.removeprefix("\ufeff")
    parse_warnings: list[warnings.WarningMessage]
    try:
        with warnings.catch_warnings(record=True) as parse_warnings:
            warnings.simplefilter("always", DeprecationWarning)
            tree = ast.parse(source, filename=path)
    except SyntaxError as exc:
        raise ArchitectureMapError(
            "UNSUPPORTED_CONSUMER_SYNTAX",
            f"{path}:{exc.lineno or 0}: {exc.msg}",
        ) from exc

    consumers: list[dict[str, object]] = []
    findings: list[dict[str, object]] = [
        {
            "path": path,
            "finding": "PYTHON_DEPRECATION_WARNING",
            "line": int(item.lineno or 0),
            "detail": str(item.message),
        }
        for item in parse_warnings
        if issubclass(item.category, DeprecationWarning)
    ]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                consumers.append(
                    {
                        "consumer_path": path,
                        "target": f"module:{alias.name}",
                        "discovery_class": "python-import",
                        "line": node.lineno,
                    }
                )
        elif isinstance(node, ast.ImportFrom):
            prefix = "." * node.level
            module = node.module or ""
            consumers.append(
                {
                    "consumer_path": path,
                    "target": f"module:{prefix}{module}",
                    "discovery_class": "python-import",
                    "line": node.lineno,
                }
            )
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            owner = node.func.value
            if (
                node.func.attr == "import_module"
                and isinstance(owner, ast.Name)
                and owner.id == "importlib"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                consumers.append(
                    {
                        "consumer_path": path,
                        "target": f"module:{node.args[0].value}",
                        "discovery_class": "python-dynamic-loader",
                        "line": node.lineno,
                    }
                )
            if (
                node.func.attr in {"append", "extend", "insert"}
                and isinstance(owner, ast.Attribute)
                and owner.attr == "path"
                and isinstance(owner.value, ast.Name)
                and owner.value.id == "sys"
            ):
                findings.append(
                    {
                        "path": path,
                        "finding": "SYS_PATH_SURGERY",
                        "line": node.lineno,
                    }
                )
    consumers.sort(key=lambda row: (str(row["target"]), int(row["line"])))
    findings.sort(key=lambda row: (int(row["line"]), str(row["finding"])))
    return {"consumers": consumers, "findings": findings}


_AMBIENT_CWD_RE = re.compile(r"(?:Path\.cwd\s*\(|os\.getcwd\s*\()")
_DRIVE_ROOT_RE = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/]")


def scan_root_signals(path: str, source: str) -> list[dict[str, object]]:
    """Return live ambient-CWD and implicit-drive root findings by source line."""

    findings: list[dict[str, object]] = []
    for line_number, line in enumerate(source.splitlines(), start=1):
        if _AMBIENT_CWD_RE.search(line):
            findings.append(
                {"path": path, "finding": "AMBIENT_CWD", "line": line_number}
            )
        if _DRIVE_ROOT_RE.search(line):
            findings.append(
                {
                    "path": path,
                    "finding": "IMPLICIT_DRIVE_ROOT",
                    "line": line_number,
                }
            )
    return findings


_RUST_USE_RE = re.compile(r"^\s*(?:pub\s+)?use\s+([^;]+);", re.MULTILINE)
_TYPESCRIPT_IMPORT_RE = re.compile(
    r"(?:\bfrom\s*|\bimport\s*\(|\brequire\s*\()\s*['\"]([^'\"]+)['\"]"
)


def scan_rust_source(path: str, source: str) -> list[dict[str, object]]:
    """Return stable Rust `use` consumers without interpreting macros."""

    rows = [
        {
            "consumer_path": path,
            "target": f"rust:{match.group(1).strip()}",
            "discovery_class": "rust-import",
            "line": source.count("\n", 0, match.start()) + 1,
        }
        for match in _RUST_USE_RE.finditer(source)
    ]
    return sorted(rows, key=lambda row: (int(row["line"]), str(row["target"])))


def scan_typescript_source(path: str, source: str) -> list[dict[str, object]]:
    """Return static/dynamic TypeScript and JavaScript module consumers."""

    rows = [
        {
            "consumer_path": path,
            "target": f"typescript:{match.group(1)}",
            "discovery_class": "typescript-import",
            "line": source.count("\n", 0, match.start()) + 1,
        }
        for match in _TYPESCRIPT_IMPORT_RE.finditer(source)
    ]
    return sorted(rows, key=lambda row: (int(row["line"]), str(row["target"])))


def _cycle_path(nodes: Sequence[str], edges: Sequence[tuple[str, str]]) -> list[str] | None:
    adjacency = {node: [] for node in nodes}
    for source, target in edges:
        adjacency.setdefault(source, []).append(target)
        adjacency.setdefault(target, [])
    for values in adjacency.values():
        values.sort()

    visiting: set[str] = set()
    visited: set[str] = set()
    stack: list[str] = []

    def visit(node: str) -> list[str] | None:
        if node in visiting:
            start = stack.index(node)
            return stack[start:] + [node]
        if node in visited:
            return None
        visiting.add(node)
        stack.append(node)
        for target in adjacency[node]:
            cycle = visit(target)
            if cycle is not None:
                return cycle
        stack.pop()
        visiting.remove(node)
        visited.add(node)
        return None

    for node in sorted(adjacency):
        cycle = visit(node)
        if cycle is not None:
            return cycle
    return None


def build_dependency_graph(
    consumers: Sequence[Mapping[str, object]],
    policy: Mapping[str, Any],
) -> dict[str, object]:
    """Build and validate the owner-level dependency DAG."""

    validate_policy(policy)
    executable_classes = {
        "python-import",
        "python-dynamic-loader",
        "rust-import",
        "typescript-import",
        "declared-dependency",
    }
    dependency_rows = [
        row
        for row in consumers
        if row.get("discovery_class") is None
        or row.get("discovery_class") in executable_classes
    ]
    edges = sorted(
        {
            (str(row["owner"]), str(row["target_owner"]))
            for row in dependency_rows
            if row.get("target_owner") and row.get("target_owner") != row.get("owner")
        }
    )
    allowed = {tuple(map(str, row)) for row in policy["allowed_dependencies"]}
    forbidden = [edge for edge in edges if edge not in allowed]
    if forbidden:
        source, target = forbidden[0]
        raise ArchitectureMapError("FORBIDDEN_DEPENDENCY", f"{source} -> {target}")
    cycle = _cycle_path(OWNERS, edges)
    if cycle is not None:
        raise ArchitectureMapError("DEPENDENCY_CYCLE", " -> ".join(cycle))
    return {
        "nodes": list(OWNERS),
        "edges": [list(edge) for edge in edges],
    }


def validate_typed_roots(policy: Mapping[str, Any]) -> list[dict[str, object]]:
    """Validate the exact seven typed root contracts without resolving host paths."""

    expected = {
        "source",
        "application_state",
        "data",
        "model_checkpoint",
        "cache",
        "evidence",
        "worktree",
    }
    rows = policy.get("typed_roots")
    _require(isinstance(rows, list), "MALFORMED_TYPED_ROOTS", "not a list")
    ids = [str(row.get("id", "")) for row in rows if isinstance(row, dict)]
    _require(set(ids) == expected and len(ids) == len(expected), "MALFORMED_TYPED_ROOTS", repr(ids))
    for row in rows:
        root_id = str(row["id"])
        _require(row.get("type") == "absolute-directory", "MALFORMED_TYPED_ROOT", root_id)
        _require(row.get("resolution") in {"explicit-argument", "explicit-profile"}, "MALFORMED_TYPED_ROOT", root_id)
        _require(isinstance(row.get("external_input_only"), bool), "MALFORMED_TYPED_ROOT", root_id)
    return sorted((dict(row) for row in rows), key=lambda row: str(row["id"]))


def validate_package_authorities(
    repo: Path,
    policy: Mapping[str, Any],
) -> list[dict[str, str]]:
    """Bind package/workspace/lock declarations to their exact Git blob OIDs."""

    validate_policy(policy)
    rows = policy.get("package_authorities")
    _require(isinstance(rows, list) and bool(rows), "MALFORMED_PACKAGE_AUTHORITIES", "missing rows")
    verified: list[dict[str, str]] = []
    for row in sorted(rows, key=lambda item: str(item["id"])):
        path = _normalize_repo_path(str(row["path"]))
        actual = _git(repo, "rev-parse", f"HEAD:{path}").decode("ascii").strip()
        if actual != row.get("expected_blob_oid"):
            raise ArchitectureMapError("PACKAGE_AUTHORITY_DRIFT", path)
        verified.append(
            {
                "id": str(row["id"]),
                "path": path,
                "blob_oid": actual,
                "ecosystem": str(row["ecosystem"]),
                "role": str(row["role"]),
            }
        )
    return verified


_REFERENCE_RE = re.compile(
    r"(?<![A-Za-z0-9_.-])"
    r"((?:scripts|tools|src|runtime|configs|manifests|receipts|schemas|docs|tests|"
    r"state|scratch|artifacts|baseline|data|tokenizer)/"
    r"[A-Za-z0-9_./-]+)"
)
_TEXT_SUFFIXES = {
    ".py",
    ".rs",
    ".ts",
    ".tsx",
    ".js",
    ".mjs",
    ".cjs",
    ".yml",
    ".yaml",
    ".sh",
    ".ps1",
    ".md",
    ".toml",
}


def _module_target_owner(target: str) -> str | None:
    if not target.startswith("module:ember."):
        return None
    segment = target.removeprefix("module:ember.").split(".", 1)[0]
    return {
        "model": "Model",
        "data": "Data",
        "training": "Training",
        "evaluation": "Evaluation",
        "runtime": "Runtime",
        "lab": "Lab",
        "infrastructure": "Infrastructure",
        "governance": "Governance",
    }.get(segment)


def discover_consumers(
    repo: Path,
    path_rows: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Discover active textual consumers and root findings from classified paths."""

    by_path = {str(row["path"]): row for row in path_rows}
    consumers: list[dict[str, object]] = []
    findings: list[dict[str, object]] = []
    class_counts: dict[str, int] = {}
    for path in sorted(by_path):
        suffix = Path(path).suffix.lower()
        if suffix not in _TEXT_SUFFIXES:
            continue
        source_path = repo / Path(*PurePosixPath(path).parts)
        try:
            text = source_path.read_text(encoding="utf-8", errors="strict")
        except (OSError, UnicodeError) as exc:
            raise ArchitectureMapError("UNREADABLE_CONSUMER_SOURCE", path) from exc
        classification = by_path[path]
        local_rows: list[dict[str, object]] = []
        if suffix == ".py":
            parsed = scan_python_source(path, text)
            local_rows.extend(parsed["consumers"])
            findings.extend(parsed["findings"])
        elif suffix == ".rs":
            local_rows.extend(scan_rust_source(path, text))
        elif suffix in {".ts", ".tsx", ".js", ".mjs", ".cjs"}:
            local_rows.extend(scan_typescript_source(path, text))
        findings.extend(scan_root_signals(path, text))
        discovery_class = (
            "documentation-reference"
            if suffix == ".md"
            else "workflow-hook-installer-reference"
            if suffix in {".yml", ".yaml", ".sh", ".ps1"}
            else "source-reference"
        )
        for line_number, line in enumerate(text.splitlines(), start=1):
            for match in _REFERENCE_RE.finditer(line):
                target = match.group(1).rstrip(".,:;)]}")
                reference_class = discovery_class
                if target.startswith(("receipts/", "manifests/", "schemas/", "configs/", "baseline/", "artifacts/")):
                    reference_class = "receipt-manifest-schema-config-consumer"
                elif target.startswith(("state/", "scratch/")):
                    reference_class = "mutable-state-reference"
                elif target.startswith(("data/", "tokenizer/")):
                    reference_class = "external-input-reference"
                local_rows.append(
                    {
                        "consumer_path": path,
                        "target": target,
                        "discovery_class": reference_class,
                        "line": line_number,
                    }
                )
        for row in local_rows:
            target = str(row["target"])
            target_classification = by_path.get(target)
            target_owner = (
                str(target_classification["owner"])
                if target_classification is not None
                else _module_target_owner(target)
            )
            expanded = {
                **row,
                "owner": classification["owner"],
                "disposition": classification["disposition"],
                "touch_set_id": classification["touch_set_id"],
                "target_owner": target_owner,
            }
            consumers.append(expanded)
            key = str(row["discovery_class"])
            class_counts[key] = class_counts.get(key, 0) + 1
    consumers.sort(
        key=lambda row: (
            str(row["consumer_path"]),
            int(row["line"]),
            str(row["target"]),
            str(row["discovery_class"]),
        )
    )
    findings.sort(
        key=lambda row: (str(row["path"]), int(row["line"]), str(row["finding"]))
    )
    return {
        "rows": consumers,
        "findings": findings,
        "class_counts": dict(sorted(class_counts.items())),
    }


def build_touch_sets(
    path_rows: Sequence[Mapping[str, object]],
    consumers: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    """Derive stable switch-target components; stable/deferred paths remain context."""

    switch_dispositions = {"MOVE", "MERGE", "ARCHIVE", "EXTERNALIZE", "DELETE_REDUNDANT"}
    grouped: dict[tuple[str, str], dict[str, object]] = {}
    path_to_group: dict[str, tuple[str, str]] = {}
    for row in path_rows:
        disposition = str(row.get("disposition", ""))
        if disposition not in switch_dispositions:
            continue
        touch_set_id = str(row.get("touch_set_id", ""))
        _require(bool(touch_set_id), "MALFORMED_TOUCH_SET", str(row.get("path", "")))
        path = str(row.get("path", ""))
        strategy = str(row.get("rollback_unit_strategy", ""))
        if strategy == "PER_AUTHORITATIVE_SWITCH_TARGET":
            rollback_key = path
        elif strategy == "EXPLICIT_KEY":
            rollback_key = str(row.get("rollback_unit_key", ""))
            _require(bool(rollback_key), "MALFORMED_TOUCH_SET", f"{path}: rollback_unit_key")
        else:
            raise ArchitectureMapError("MALFORMED_TOUCH_SET", f"{path}: {strategy}")
        grouping_key = (touch_set_id, rollback_key)
        path_to_group[path] = grouping_key
        item = grouped.setdefault(
            grouping_key,
            {
                "namespace": touch_set_id,
                "rollback_unit_key": rollback_key,
                "owner": str(row["owner"]),
                "disposition": disposition,
                "paths": [],
                "consumers": [],
            },
        )
        _require(item["owner"] == row["owner"], "TOUCH_SET_OWNER_MISMATCH", touch_set_id)
        _require(
            item["disposition"] == row["disposition"],
            "TOUCH_SET_DISPOSITION_MISMATCH",
            touch_set_id,
        )
        item["paths"].append(path)

    for row in consumers:
        grouping_key = path_to_group.get(str(row.get("target", "")))
        if grouping_key is not None:
            grouped[grouping_key]["consumers"].append(str(row["consumer_path"]))

    result: list[dict[str, object]] = []
    for grouping_key in sorted(grouped):
        item = grouped[grouping_key]
        paths = sorted(set(item["paths"]))
        result.append(
            {
                "id": f"{item['namespace']}::{paths[0]}",
                "namespace": item["namespace"],
                "rollback_unit_key": item["rollback_unit_key"],
                "owner": item["owner"],
                "disposition": item["disposition"],
                "paths": paths,
                "consumers": sorted(set(item["consumers"])),
            }
        )
    return sorted(result, key=lambda row: str(row["id"]))


def build_conflict_graph(
    touch_sets: Sequence[Mapping[str, object]],
    reviewability: Mapping[str, object],
) -> dict[str, object]:
    """Build the exact pairwise carrier-conflict graph from atomic touch sets."""

    max_paths = reviewability.get("max_paths_per_carrier")
    max_consumers = reviewability.get("max_consumers_per_carrier")
    _require(
        isinstance(max_paths, int) and not isinstance(max_paths, bool) and max_paths > 0,
        "MALFORMED_REVIEWABILITY",
        "max_paths_per_carrier",
    )
    _require(
        isinstance(max_consumers, int)
        and not isinstance(max_consumers, bool)
        and max_consumers > 0,
        "MALFORMED_REVIEWABILITY",
        "max_consumers_per_carrier",
    )
    by_id: dict[str, Mapping[str, object]] = {}
    for row in touch_sets:
        touch_set_id = str(row.get("id", ""))
        _require(bool(touch_set_id), "MALFORMED_TOUCH_SET", "missing id")
        _require(touch_set_id not in by_id, "DUPLICATE_TOUCH_SET", touch_set_id)
        path_count = len(set(map(str, row.get("paths", []))))
        consumer_count = len(set(map(str, row.get("consumers", []))))
        if path_count > max_paths or consumer_count > max_consumers:
            raise ArchitectureMapError(
                "OVERSIZED_ATOMIC_TOUCH_SET",
                f"{touch_set_id}: paths={path_count}/{max_paths} consumers={consumer_count}/{max_consumers}",
            )
        by_id[touch_set_id] = row

    reasons: list[dict[str, object]] = []
    edges: list[list[str]] = []
    ids = sorted(by_id)
    for index, left_id in enumerate(ids):
        left = by_id[left_id]
        left_paths = set(map(str, left.get("paths", [])))
        left_consumers = set(map(str, left.get("consumers", [])))
        for right_id in ids[index + 1 :]:
            right = by_id[right_id]
            right_paths = set(map(str, right.get("paths", [])))
            right_consumers = set(map(str, right.get("consumers", [])))
            shared_paths = sorted(left_paths & right_paths)
            shared_consumers = sorted(left_consumers & right_consumers)
            combined_paths = len(left_paths | right_paths)
            combined_consumers = len(left_consumers | right_consumers)
            pair_reasons: list[str] = []
            if shared_paths:
                pair_reasons.append("SHARED_PATH")
            if shared_consumers:
                pair_reasons.append("SHARED_CONSUMER")
            if pair_reasons:
                edges.append([left_id, right_id])
                reasons.append(
                    {
                        "edge": [left_id, right_id],
                        "reasons": pair_reasons,
                        "shared_paths": shared_paths,
                        "shared_consumers": shared_consumers,
                        "combined_path_count": combined_paths,
                        "combined_consumer_count": combined_consumers,
                    }
                )
    return {
        "nodes": ids,
        "edges": edges,
        "edge_reasons": reasons,
        "node_weights": {
            touch_set_id: {
                "path_count": len(set(map(str, by_id[touch_set_id].get("paths", [])))),
                "consumers": sorted(set(map(str, by_id[touch_set_id].get("consumers", [])))),
            }
            for touch_set_id in ids
        },
        "capacities": {
            "max_paths_per_carrier": max_paths,
            "max_consumers_per_carrier": max_consumers,
            "consumer_counting_rule": "UNIQUE_CONSUMER_PATHS_PER_CARRIER",
        },
    }


def build_touch_set_precedence(
    touch_sets: Sequence[Mapping[str, object]],
    dependency_graph: Mapping[str, object],
) -> list[list[str]]:
    """Order every dependency target touch set before its dependent touch sets."""

    by_owner: dict[str, list[str]] = {}
    known_ids: set[str] = set()
    for row in touch_sets:
        touch_set_id = str(row.get("id", ""))
        owner = str(row.get("owner", ""))
        _require(bool(touch_set_id) and bool(owner), "MALFORMED_TOUCH_SET", repr(row))
        _require(touch_set_id not in known_ids, "DUPLICATE_TOUCH_SET", touch_set_id)
        known_ids.add(touch_set_id)
        by_owner.setdefault(owner, []).append(touch_set_id)
    for ids in by_owner.values():
        ids.sort()

    raw_edges = dependency_graph.get("edges")
    _require(isinstance(raw_edges, list), "MALFORMED_DEPENDENCY_GRAPH", "edges")
    precedence: set[tuple[str, str]] = set()
    for raw_edge in raw_edges:
        _require(
            isinstance(raw_edge, list) and len(raw_edge) == 2,
            "MALFORMED_DEPENDENCY_GRAPH",
            repr(raw_edge),
        )
        source_owner, target_owner = map(str, raw_edge)
        for target_id in by_owner.get(target_owner, []):
            for source_id in by_owner.get(source_owner, []):
                if target_id != source_id:
                    precedence.add((target_id, source_id))
    result = [list(edge) for edge in sorted(precedence)]
    if _cycle_path(sorted(known_ids), [tuple(edge) for edge in result]) is not None:
        raise ArchitectureMapError("PRECEDENCE_CYCLE", repr(result))
    return result


def build_carrier_specs(
    touch_sets: Sequence[Mapping[str, object]],
    coloring: Mapping[str, object],
    capacities: Mapping[str, object] | None = None,
) -> list[dict[str, object]]:
    """Render one ordered, complete carrier membership row per used color."""

    assignment = coloring.get("assignment")
    k = coloring.get("k")
    _require(isinstance(assignment, dict), "MALFORMED_COLORING", "assignment")
    _require(isinstance(k, int) and not isinstance(k, bool) and k >= 0, "MALFORMED_COLORING", "k")
    max_paths = None
    max_consumers = None
    if capacities is not None:
        max_paths = capacities.get("max_paths_per_carrier")
        max_consumers = capacities.get("max_consumers_per_carrier")
        _require(
            isinstance(max_paths, int) and not isinstance(max_paths, bool) and max_paths > 0,
            "MALFORMED_CAPACITY_CONTRACT",
            "max paths",
        )
        _require(
            isinstance(max_consumers, int)
            and not isinstance(max_consumers, bool)
            and max_consumers > 0,
            "MALFORMED_CAPACITY_CONTRACT",
            "max consumers",
        )
    by_id = {str(row.get("id", "")): row for row in touch_sets}
    _require(set(assignment) == set(by_id), "INCOMPLETE_CARRIER_MEMBERSHIP", repr(sorted(set(by_id) ^ set(assignment))))
    carriers: list[dict[str, object]] = []
    for color in range(k):
        member_ids = sorted(
            touch_set_id
            for touch_set_id, assigned_color in assignment.items()
            if assigned_color == color
        )
        _require(bool(member_ids), "EMPTY_CARRIER_COLOR", str(color))
        paths = sorted(
            {
                str(path)
                for touch_set_id in member_ids
                for path in by_id[touch_set_id].get("paths", [])
            }
        )
        consumers = sorted(
            {
                str(path)
                for touch_set_id in member_ids
                for path in by_id[touch_set_id].get("consumers", [])
            }
        )
        within_capacity = (
            max_paths is None
            or (len(paths) <= max_paths and len(consumers) <= max_consumers)
        )
        if not within_capacity:
            raise ArchitectureMapError(
                "CARRIER_CAPACITY_EXCEEDED",
                f"color={color} paths={len(paths)}/{max_paths} consumers={len(consumers)}/{max_consumers}",
            )
        carriers.append(
            {
                "carrier_id": f"carrier-{color + 1:03d}",
                "color": color,
                "touch_set_ids": member_ids,
                "paths": paths,
                "consumers": consumers,
                "path_count": len(paths),
                "unique_consumer_count": len(consumers),
                "within_capacity": within_capacity,
            }
        )
    return carriers


def _normalized_coloring_graph(
    nodes: Sequence[str],
    edges: Sequence[tuple[str, str]],
    precedence: Sequence[tuple[str, str]],
) -> tuple[list[str], list[tuple[str, str]], list[tuple[str, str]]]:
    ordered_nodes = sorted(set(map(str, nodes)))
    _require(len(ordered_nodes) == len(nodes), "DUPLICATE_COLORING_NODE", repr(list(nodes)))
    known = set(ordered_nodes)

    def normalize_pairs(
        pairs: Sequence[tuple[str, str]], code: str
    ) -> list[tuple[str, str]]:
        result: set[tuple[str, str]] = set()
        for raw_left, raw_right in pairs:
            left, right = str(raw_left), str(raw_right)
            _require(left in known and right in known, code, f"{left} -> {right}")
            _require(left != right, code, f"self edge {left}")
            result.add((left, right))
        return sorted(result)

    normalized_edges = [tuple(sorted(pair)) for pair in normalize_pairs(edges, "MALFORMED_CONFLICT_EDGE")]
    normalized_edges = sorted(set(normalized_edges))
    normalized_precedence = normalize_pairs(precedence, "MALFORMED_PRECEDENCE_EDGE")
    if _cycle_path(ordered_nodes, normalized_precedence) is not None:
        raise ArchitectureMapError("PRECEDENCE_CYCLE", repr(normalized_precedence))
    return ordered_nodes, normalized_edges, normalized_precedence


def _color_search(
    nodes: Sequence[str],
    edges: Sequence[tuple[str, str]],
    precedence: Sequence[tuple[str, str]],
    k: int,
    budget: dict[str, int],
    node_weights: Mapping[str, Mapping[str, object]],
    capacities: Mapping[str, object] | None,
    seed_clique: Sequence[str] = (),
) -> dict[str, int] | None:
    required_recursion_limit = len(nodes) + 256
    if sys.getrecursionlimit() < required_recursion_limit:
        sys.setrecursionlimit(required_recursion_limit)
    adjacent = {node: set() for node in nodes}
    for left, right in edges:
        adjacent[left].add(right)
        adjacent[right].add(left)
    before = {node: set() for node in nodes}
    after = {node: set() for node in nodes}
    for left, right in precedence:
        after[left].add(right)
        before[right].add(left)
    indegree = {node: len(before[node]) for node in nodes}
    ready = sorted(node for node in nodes if indegree[node] == 0)
    topological: list[str] = []
    while ready:
        node = ready.pop(0)
        topological.append(node)
        for child in sorted(after[node]):
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child)
                ready.sort()
    _require(len(topological) == len(nodes), "PRECEDENCE_CYCLE", repr(list(precedence)))
    minimum_color = {node: 0 for node in nodes}
    for node in topological:
        for child in after[node]:
            minimum_color[child] = max(minimum_color[child], minimum_color[node] + 1)
    successor_depth = {node: 0 for node in nodes}
    for node in reversed(topological):
        for child in after[node]:
            successor_depth[node] = max(successor_depth[node], successor_depth[child] + 1)
    if any(minimum_color[node] + successor_depth[node] >= k for node in nodes):
        budget["explored"] += 1
        if budget["explored"] > budget["maximum"]:
            raise ArchitectureMapError(
                "EXACT_COLORING_BUDGET_EXCEEDED",
                f"maximum={budget['maximum']} explored={budget['explored']}",
            )
        return None
    assignment: dict[str, int] = {}
    color_path_counts = [0 for _ in range(k)]
    color_consumers: list[set[str]] = [set() for _ in range(k)]
    max_paths = int(capacities["max_paths_per_carrier"]) if capacities is not None else None
    max_consumers = int(capacities["max_consumers_per_carrier"]) if capacities is not None else None
    _require(len(seed_clique) <= k, "MALFORMED_CLIQUE_SEED", f"{len(seed_clique)} > {k}")
    for color, node in enumerate(seed_clique):
        _require(node in adjacent and node not in assignment, "MALFORMED_CLIQUE_SEED", node)
        _require(
            all(tuple(sorted((node, prior))) in set(edges) for prior in assignment),
            "MALFORMED_CLIQUE_SEED",
            f"not a clique: {node}",
        )
        weight = node_weights[node]
        path_count = int(weight["path_count"])
        consumers = set(map(str, weight["consumers"]))
        _require(max_paths is None or path_count <= max_paths, "MALFORMED_CLIQUE_SEED", node)
        _require(max_consumers is None or len(consumers) <= max_consumers, "MALFORMED_CLIQUE_SEED", node)
        assignment[node] = color
        color_path_counts[color] = path_count
        color_consumers[color] = consumers

    def visit(index: int) -> dict[str, int] | None:
        budget["explored"] += 1
        if budget["explored"] > budget["maximum"]:
            raise ArchitectureMapError(
                "EXACT_COLORING_BUDGET_EXCEEDED",
                f"maximum={budget['maximum']} explored={budget['explored']}",
            )
        if len(assignment) == len(nodes):
            return dict(assignment)
        if precedence:
            node = nodes[index]
        else:
            unassigned = (candidate for candidate in nodes if candidate not in assignment)
            node = min(
                unassigned,
                key=lambda candidate: (
                    -len(
                        {
                            assignment[neighbor]
                            for neighbor in adjacent[candidate]
                            if neighbor in assignment
                        }
                    ),
                    -len(adjacent[candidate]),
                    candidate,
                ),
            )
        maximum_color = k - 1 - successor_depth[node]
        if precedence:
            # Precedence gives colors an absolute order, so ordinary color-label
            # symmetry breaking is unsound: a lexically later predecessor may need
            # color zero while the first lexical node takes color one.
            candidate_colors = range(minimum_color[node], maximum_color + 1)
        else:
            # With no precedence, unused color labels are interchangeable. Admit
            # only the next unused label; this removes permutations but no coloring.
            used = set(assignment.values())
            symmetric_maximum = min(maximum_color, len(used))
            candidate_colors = range(minimum_color[node], symmetric_maximum + 1)
        for color in candidate_colors:
            if any(assignment.get(neighbor) == color for neighbor in adjacent[node]):
                continue
            if any(assignment.get(parent, -1) >= color for parent in before[node]):
                continue
            if any(
                child in assignment and color >= assignment[child]
                for child in after[node]
            ):
                continue
            weight = node_weights[node]
            path_count = int(weight["path_count"])
            consumers = set(map(str, weight["consumers"]))
            if max_paths is not None and color_path_counts[color] + path_count > max_paths:
                continue
            if max_consumers is not None and len(color_consumers[color] | consumers) > max_consumers:
                continue
            assignment[node] = color
            prior_consumers = color_consumers[color]
            color_path_counts[color] += path_count
            color_consumers[color] = prior_consumers | consumers
            witness = visit(index + 1)
            if witness is not None:
                return witness
            color_path_counts[color] -= path_count
            color_consumers[color] = prior_consumers
            assignment.pop(node)
        return None

    return visit(0)


def _coloring_hash(value: object) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def canonical_sha256(value: object) -> str:
    """Public canonical hash helper for graph/certificate consumers."""

    return _coloring_hash(value)


def _normalize_capacity_contract(
    nodes: Sequence[str],
    node_weights: Mapping[str, Mapping[str, object]] | None,
    capacities: Mapping[str, object] | None,
) -> tuple[dict[str, dict[str, object]], dict[str, object] | None]:
    if node_weights is None and capacities is None:
        return (
            {node: {"path_count": 0, "consumers": []} for node in nodes},
            None,
        )
    _require(node_weights is not None and capacities is not None, "MALFORMED_CAPACITY_CONTRACT", "weights/capacities pair")
    _require(set(node_weights) == set(nodes), "MALFORMED_CAPACITY_CONTRACT", "node weight coverage")
    max_paths = capacities.get("max_paths_per_carrier")
    max_consumers = capacities.get("max_consumers_per_carrier")
    _require(isinstance(max_paths, int) and not isinstance(max_paths, bool) and max_paths > 0, "MALFORMED_CAPACITY_CONTRACT", "max paths")
    _require(isinstance(max_consumers, int) and not isinstance(max_consumers, bool) and max_consumers > 0, "MALFORMED_CAPACITY_CONTRACT", "max consumers")
    normalized: dict[str, dict[str, object]] = {}
    for node in nodes:
        row = node_weights[node]
        path_count = row.get("path_count")
        consumers = row.get("consumers")
        _require(isinstance(path_count, int) and not isinstance(path_count, bool) and 0 <= path_count <= max_paths, "OVERSIZED_ATOMIC_TOUCH_SET", node)
        _require(isinstance(consumers, list), "MALFORMED_CAPACITY_CONTRACT", node)
        normalized_consumers = sorted(set(map(str, consumers)))
        _require(len(normalized_consumers) <= max_consumers, "OVERSIZED_ATOMIC_TOUCH_SET", node)
        normalized[node] = {"path_count": path_count, "consumers": normalized_consumers}
    normalized_capacities = {
        "max_paths_per_carrier": max_paths,
        "max_consumers_per_carrier": max_consumers,
        "consumer_counting_rule": str(
            capacities.get("consumer_counting_rule", "UNIQUE_CONSUMER_PATHS_PER_CARRIER")
        ),
    }
    _require(
        normalized_capacities["consumer_counting_rule"] == "UNIQUE_CONSUMER_PATHS_PER_CARRIER",
        "MALFORMED_CAPACITY_CONTRACT",
        "consumer_counting_rule",
    )
    return normalized, normalized_capacities


def _deterministic_dsatur_witness(
    nodes: Sequence[str],
    edges: Sequence[tuple[str, str]],
    node_weights: Mapping[str, Mapping[str, object]],
    capacities: Mapping[str, object] | None,
) -> dict[str, int]:
    """Construct a deterministic capacity-valid upper witness without claiming optimality."""

    adjacent = {node: set() for node in nodes}
    for left, right in edges:
        adjacent[left].add(right)
        adjacent[right].add(left)
    assignment: dict[str, int] = {}
    unassigned = set(nodes)
    color_path_counts: list[int] = []
    color_consumers: list[set[str]] = []
    max_paths = int(capacities["max_paths_per_carrier"]) if capacities is not None else None
    max_consumers = int(capacities["max_consumers_per_carrier"]) if capacities is not None else None
    while unassigned:
        node = min(
            unassigned,
            key=lambda candidate: (
                -len({assignment[n] for n in adjacent[candidate] if n in assignment}),
                -len(adjacent[candidate]),
                candidate,
            ),
        )
        forbidden = {assignment[neighbor] for neighbor in adjacent[node] if neighbor in assignment}
        path_count = int(node_weights[node]["path_count"])
        consumers = set(map(str, node_weights[node]["consumers"]))
        chosen: int | None = None
        for color in range(len(color_path_counts)):
            if color in forbidden:
                continue
            if max_paths is not None and color_path_counts[color] + path_count > max_paths:
                continue
            if max_consumers is not None and len(color_consumers[color] | consumers) > max_consumers:
                continue
            chosen = color
            break
        if chosen is None:
            chosen = len(color_path_counts)
            color_path_counts.append(0)
            color_consumers.append(set())
        assignment[node] = chosen
        color_path_counts[chosen] += path_count
        color_consumers[chosen] |= consumers
        unassigned.remove(node)
    return {node: assignment[node] for node in nodes}


COLORING_ALGORITHM = "stable-exact-branch-and-bound-v1"


def _solve_minimum_coloring_monolithic(
    nodes: Sequence[str],
    edges: Sequence[tuple[str, str]],
    precedence: Sequence[tuple[str, str]],
    max_states: int,
    node_weights: Mapping[str, Mapping[str, object]] | None = None,
    capacities: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Return the exact lexicographically stable minimum carrier coloring."""

    _require(
        isinstance(max_states, int) and not isinstance(max_states, bool) and max_states > 0,
        "MALFORMED_COLORING_BUDGET",
        repr(max_states),
    )
    ordered_nodes, normalized_edges, normalized_precedence = _normalized_coloring_graph(
        nodes, edges, precedence
    )
    normalized_weights, normalized_capacities = _normalize_capacity_contract(
        ordered_nodes, node_weights, capacities
    )
    graph_payload = {"nodes": ordered_nodes, "edges": [list(edge) for edge in normalized_edges]}
    precedence_payload = [list(edge) for edge in normalized_precedence]
    graph_sha256 = _coloring_hash(graph_payload)
    precedence_sha256 = _coloring_hash(precedence_payload)
    capacity_payload = {
        "node_weights": normalized_weights,
        "capacities": normalized_capacities,
    }
    capacity_sha256 = _coloring_hash(capacity_payload)
    if not ordered_nodes:
        return {
            "algorithm": COLORING_ALGORITHM,
            "k": 0,
            "assignment": {},
            "graph_sha256": graph_sha256,
            "precedence_sha256": precedence_sha256,
            "capacity_sha256": capacity_sha256,
            "explored_states": 0,
            "k_minus_one_unsat": {
                "k": -1,
                "complete_exhaustion": True,
                "explored_states": 0,
                "graph_sha256": graph_sha256,
                "precedence_sha256": precedence_sha256,
                "capacity_sha256": capacity_sha256,
                "algorithm": COLORING_ALGORITHM,
            },
        }

    minimum_k = 1
    previous_unsat: dict[str, object] | None = None
    edge_set = set(normalized_edges)
    consumer_nodes: dict[str, list[str]] = {}
    for node, weight in normalized_weights.items():
        for consumer in weight["consumers"]:
            consumer_nodes.setdefault(str(consumer), []).append(node)
    clique_witness: list[str] = []
    clique_consumer: str | None = None
    for consumer, raw_members in sorted(consumer_nodes.items()):
        members = sorted(raw_members)
        if len(members) <= len(clique_witness):
            continue
        if all(
            tuple(sorted((left, right))) in edge_set
            for index, left in enumerate(members)
            for right in members[index + 1 :]
        ):
            clique_witness = members
            clique_consumer = consumer
    conflict_clique_bound = max(1, len(clique_witness))
    if normalized_capacities is not None:
        total_paths = sum(int(row["path_count"]) for row in normalized_weights.values())
        total_consumer_slots = sum(len(row["consumers"]) for row in normalized_weights.values())
        path_bound = (total_paths + int(normalized_capacities["max_paths_per_carrier"]) - 1) // int(
            normalized_capacities["max_paths_per_carrier"]
        )
        consumer_bound = (
            total_consumer_slots + int(normalized_capacities["max_consumers_per_carrier"]) - 1
        ) // int(normalized_capacities["max_consumers_per_carrier"])
        minimum_k = max(1, path_bound, consumer_bound, conflict_clique_bound)
        if minimum_k > 1:
            previous_unsat = {
                "k": minimum_k - 1,
                "complete_exhaustion": True,
                "proof_kind": (
                    "CONFLICT_CLIQUE_ROOT_BOUND"
                    if conflict_clique_bound > max(path_bound, consumer_bound)
                    else "CAPACITY_ROOT_BOUND"
                ),
                "explored_states": 1,
                "path_lower_bound": path_bound,
                "consumer_lower_bound": consumer_bound,
                "conflict_clique_lower_bound": conflict_clique_bound,
                "conflict_clique_consumer": clique_consumer,
                "conflict_clique_nodes_sha256": _coloring_hash(clique_witness),
                "graph_sha256": graph_sha256,
                "precedence_sha256": precedence_sha256,
                "capacity_sha256": capacity_sha256,
                "algorithm": COLORING_ALGORITHM,
            }
    total_explored = 0
    if not normalized_precedence:
        upper_witness = _deterministic_dsatur_witness(
            ordered_nodes,
            normalized_edges,
            normalized_weights,
            normalized_capacities,
        )
        upper_k = max(upper_witness.values(), default=-1) + 1
        if upper_k == minimum_k:
            if previous_unsat is None:
                previous_unsat = {
                    "k": 0,
                    "complete_exhaustion": True,
                    "explored_states": 0,
                    "graph_sha256": graph_sha256,
                    "precedence_sha256": precedence_sha256,
                    "capacity_sha256": capacity_sha256,
                    "algorithm": COLORING_ALGORITHM,
                }
            return {
                "algorithm": COLORING_ALGORITHM,
                "k": upper_k,
                "assignment": upper_witness,
                "graph_sha256": graph_sha256,
                "precedence_sha256": precedence_sha256,
                "capacity_sha256": capacity_sha256,
                "explored_states": len(ordered_nodes) + 1,
                "k_minus_one_unsat": previous_unsat,
            }
    for k in range(minimum_k, len(ordered_nodes) + 1):
        budget = {"explored": 0, "maximum": max_states - total_explored}
        if budget["maximum"] <= 0:
            raise ArchitectureMapError(
                "EXACT_COLORING_BUDGET_EXCEEDED",
                f"maximum={max_states} explored={total_explored}",
            )
        witness = _color_search(
            ordered_nodes,
            normalized_edges,
            normalized_precedence,
            k,
            budget,
            normalized_weights,
            normalized_capacities,
            clique_witness if not normalized_precedence and len(clique_witness) <= k else (),
        )
        total_explored += budget["explored"]
        if witness is not None:
            if previous_unsat is None:
                previous_unsat = {
                    "k": 0,
                    "complete_exhaustion": True,
                    "explored_states": 0,
                    "graph_sha256": graph_sha256,
                    "precedence_sha256": precedence_sha256,
                    "capacity_sha256": capacity_sha256,
                    "algorithm": COLORING_ALGORITHM,
                }
            return {
                "algorithm": COLORING_ALGORITHM,
                "k": k,
                "assignment": {node: witness[node] for node in ordered_nodes},
                "graph_sha256": graph_sha256,
                "precedence_sha256": precedence_sha256,
                "capacity_sha256": capacity_sha256,
                "explored_states": total_explored,
                "k_minus_one_unsat": previous_unsat,
            }
        previous_unsat = {
            "k": k,
            "complete_exhaustion": True,
            "explored_states": budget["explored"],
            "graph_sha256": graph_sha256,
            "precedence_sha256": precedence_sha256,
            "capacity_sha256": capacity_sha256,
            "algorithm": COLORING_ALGORITHM,
        }
    raise ArchitectureMapError("COLORING_INTERNAL_ERROR", "finite graph has no coloring")


def _conflict_components(
    nodes: Sequence[str], edges: Sequence[tuple[str, str]]
) -> list[list[str]]:
    adjacent = {node: set() for node in nodes}
    for left, right in edges:
        adjacent[left].add(right)
        adjacent[right].add(left)
    unseen = set(nodes)
    components: list[list[str]] = []
    while unseen:
        root = min(unseen)
        stack = [root]
        unseen.remove(root)
        component: list[str] = []
        while stack:
            node = stack.pop()
            component.append(node)
            for neighbor in sorted(adjacent[node], reverse=True):
                if neighbor in unseen:
                    unseen.remove(neighbor)
                    stack.append(neighbor)
        components.append(sorted(component))
    return sorted(components, key=lambda rows: rows[0])


def solve_minimum_coloring(
    nodes: Sequence[str],
    edges: Sequence[tuple[str, str]],
    precedence: Sequence[tuple[str, str]],
    max_states: int,
    node_weights: Mapping[str, Mapping[str, object]] | None = None,
    capacities: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Exactly color conflict components, then exactly capacity-pack their classes."""

    _require(
        isinstance(max_states, int) and not isinstance(max_states, bool) and max_states > 0,
        "MALFORMED_COLORING_BUDGET",
        repr(max_states),
    )
    ordered_nodes, normalized_edges, normalized_precedence = _normalized_coloring_graph(
        nodes, edges, precedence
    )
    normalized_weights, normalized_capacities = _normalize_capacity_contract(
        ordered_nodes, node_weights, capacities
    )
    if not ordered_nodes:
        result = _solve_minimum_coloring_monolithic(
            ordered_nodes,
            normalized_edges,
            normalized_precedence,
            max_states,
            normalized_weights if normalized_capacities is not None else None,
            normalized_capacities,
        )
        result["decomposition"] = {
            "component_count": 0,
            "packing_item_count": 0,
            "precedence_edge_component_locality": True,
            "components": [],
        }
        return result

    graph_payload = {"nodes": ordered_nodes, "edges": [list(edge) for edge in normalized_edges]}
    precedence_payload = [list(edge) for edge in normalized_precedence]
    capacity_payload = {
        "node_weights": normalized_weights,
        "capacities": normalized_capacities,
    }
    graph_sha256 = _coloring_hash(graph_payload)
    precedence_sha256 = _coloring_hash(precedence_payload)
    capacity_sha256 = _coloring_hash(capacity_payload)

    components = _conflict_components(ordered_nodes, normalized_edges)
    component_index = {
        node: index for index, component in enumerate(components) for node in component
    }
    for left, right in normalized_precedence:
        if component_index[left] != component_index[right]:
            raise ArchitectureMapError(
                "CROSS_COMPONENT_PRECEDENCE",
                f"{left} -> {right}",
            )

    explored = 0
    component_results: list[dict[str, object]] = []
    node_to_item: dict[str, str] = {}
    item_component: dict[str, int] = {}
    item_weights: dict[str, dict[str, object]] = {}
    packing_edges: list[tuple[str, str]] = []
    packing_precedence: set[tuple[str, str]] = set()
    for index, component in enumerate(components):
        component_set = set(component)
        component_edges = [
            edge for edge in normalized_edges if edge[0] in component_set
        ]
        component_precedence = [
            edge for edge in normalized_precedence if edge[0] in component_set
        ]
        remaining = max_states - explored
        if remaining <= 0:
            raise ArchitectureMapError(
                "EXACT_COLORING_BUDGET_EXCEEDED",
                f"maximum={max_states} explored={explored}",
            )
        component_result = _solve_minimum_coloring_monolithic(
            component,
            component_edges,
            component_precedence,
            remaining,
            (
                {node: normalized_weights[node] for node in component}
                if normalized_capacities is not None
                else None
            ),
            normalized_capacities,
        )
        explored += int(component_result["explored_states"])
        component_id = component[0]
        class_ids: list[str] = []
        for color in range(int(component_result["k"])):
            class_id = f"{component_id}::component-{index + 1:04d}-class-{color + 1:04d}"
            class_ids.append(class_id)
            item_component[class_id] = index
            members = sorted(
                node
                for node in component
                if component_result["assignment"][node] == color
            )
            for node in members:
                node_to_item[node] = class_id
            item_weights[class_id] = {
                "path_count": sum(
                    int(normalized_weights[node]["path_count"]) for node in members
                ),
                "consumers": sorted(
                    {
                        consumer
                        for node in members
                        for consumer in normalized_weights[node]["consumers"]
                    }
                ),
            }
        for left_index, left in enumerate(class_ids):
            for right in class_ids[left_index + 1 :]:
                packing_edges.append((left, right))
        for left, right in component_precedence:
            left_item, right_item = node_to_item[left], node_to_item[right]
            if left_item != right_item:
                packing_precedence.add((left_item, right_item))
        component_results.append(
            {
                "component_id": component_id,
                "node_count": len(component),
                "nodes_sha256": _coloring_hash(component),
                "k": component_result["k"],
                "explored_states": component_result["explored_states"],
                "certificate_sha256": _coloring_hash(component_result),
                "k_minus_one_unsat": component_result["k_minus_one_unsat"],
            }
        )

    item_ids = sorted(item_weights)
    for left_index, left in enumerate(item_ids):
        left_consumers = set(map(str, item_weights[left]["consumers"]))
        for right in item_ids[left_index + 1 :]:
            if item_component[left] != item_component[right]:
                _require(
                    left_consumers.isdisjoint(set(map(str, item_weights[right]["consumers"]))),
                    "CROSS_COMPONENT_CONSUMER",
                    f"{left} <> {right}",
                )

    remaining = max_states - explored
    if remaining <= 0:
        raise ArchitectureMapError(
            "EXACT_COLORING_BUDGET_EXCEEDED",
            f"maximum={max_states} explored={explored}",
        )
    packing = _solve_minimum_coloring_monolithic(
        item_ids,
        sorted(packing_edges),
        sorted(packing_precedence),
        remaining,
        item_weights if normalized_capacities is not None else None,
        normalized_capacities,
    )
    explored += int(packing["explored_states"])
    assignment = {
        node: int(packing["assignment"][node_to_item[node]]) for node in ordered_nodes
    }
    component_lower_bound = max(int(row["k"]) for row in component_results)
    if int(packing["k"]) > component_lower_bound:
        global_unsat = {
            "k": int(packing["k"]) - 1,
            "complete_exhaustion": True,
            "proof_kind": "GLOBAL_PACKING_EXHAUSTION",
            "packing_certificate": packing["k_minus_one_unsat"],
        }
    else:
        binding = next(
            row for row in component_results if int(row["k"]) == component_lower_bound
        )
        global_unsat = {
            "k": int(packing["k"]) - 1,
            "complete_exhaustion": True,
            "proof_kind": "BINDING_COMPONENT_EXHAUSTION",
            "binding_component_id": binding["component_id"],
            "component_certificate": binding["k_minus_one_unsat"],
        }
    global_unsat.update(
        {
            "graph_sha256": graph_sha256,
            "precedence_sha256": precedence_sha256,
            "capacity_sha256": capacity_sha256,
            "algorithm": COLORING_ALGORITHM,
        }
    )
    return {
        "algorithm": COLORING_ALGORITHM,
        "k": packing["k"],
        "assignment": assignment,
        "graph_sha256": graph_sha256,
        "precedence_sha256": precedence_sha256,
        "capacity_sha256": capacity_sha256,
        "explored_states": explored,
        "k_minus_one_unsat": global_unsat,
        "decomposition": {
            "component_count": len(components),
            "packing_item_count": len(item_ids),
            "precedence_edge_component_locality": True,
            "components": component_results,
            "packing_certificate_sha256": _coloring_hash(packing),
        },
    }


def verify_coloring_certificate(
    graph: Mapping[str, object],
    supplied: Mapping[str, object],
    max_states: int,
) -> dict[str, object]:
    """Recompute both the witness and K-1 exhaustion certificate exactly."""

    unsat = supplied.get("k_minus_one_unsat")
    if not isinstance(unsat, dict) or unsat.get("complete_exhaustion") is not True:
        raise ArchitectureMapError("K_MINUS_ONE_NOT_PROVEN", "complete_exhaustion is not true")
    nodes = graph.get("nodes")
    edges = graph.get("edges")
    precedence = graph.get("precedence", [])
    node_weights = graph.get("node_weights")
    capacities = graph.get("capacities")
    _require(isinstance(nodes, list), "MALFORMED_CONFLICT_GRAPH", "nodes")
    _require(isinstance(edges, list), "MALFORMED_CONFLICT_GRAPH", "edges")
    _require(isinstance(precedence, list), "MALFORMED_CONFLICT_GRAPH", "precedence")
    recomputed = solve_minimum_coloring(
        nodes,
        edges,
        precedence,
        max_states,
        node_weights=node_weights if isinstance(node_weights, dict) else None,
        capacities=capacities if isinstance(capacities, dict) else None,
    )
    if canonical_json(recomputed) != canonical_json(dict(supplied)):
        if canonical_json(recomputed["k_minus_one_unsat"]) != canonical_json(unsat):
            raise ArchitectureMapError("K_MINUS_ONE_NOT_PROVEN", "certificate differs from recomputation")
        raise ArchitectureMapError("COLORING_CERTIFICATE_MISMATCH", "witness differs from recomputation")
    return recomputed


RECEIPT_SCHEMA_VERSION = "ember-issue1962-c3-a-map-and-k-v1"
RECEIPT_CLAIM_BOUNDARY = (
    "ARCHITECTURE_CENSUS_CONFLICT_GRAPH_AND_EXACT_MINIMUM_CARRIER_PROOF_ONLY; "
    "NO_SOURCE_CUTOVER_NO_RUNTIME_EXECUTION_NO_PARENT_CLOSURE_CREDIT"
)
DECLARED_HOST_ENVELOPE = {
    "contract_issue": "#1866",
    "language": "on the current declared host (specs recorded at the public host-envelope document)",
    "identity_rule": "EMBER_PROJECT_IDENTITY_IS_HARDWARE_INDEPENDENT",
    "revalidation_trigger": "CURRENT_HOST_HARDWARE_OR_SOFTWARE_ENVELOPE_CHANGE",
}
VERIFIER_COST_CONTRACT = {
    "gate_placement": "PR_WAVE",
    "recomputation_required": True,
    "task4_measured_basis": {
        "focused_exact_replay_seconds": 13.438,
        "full_suite_seconds": 24.512,
        "basis": "TASK4_CURRENT_HEAD_RUNS_BEFORE_TASK5",
    },
    "measured_seconds_recorded_by": "TASK6_EXECUTION_CUSTODY_RECEIPT",
}


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def red_row(
    leg_id: str,
    *,
    executed: bool,
    reason: str | None = None,
    command_argv: Sequence[str] = (),
    started_at: str | None = None,
    stopped_at: str | None = None,
    returncode: int | None = None,
    stdout: bytes = b"",
    stderr: bytes = b"",
    failure_class: str | None = None,
    claim_boundary: str = "S1_BASELINE_ONLY_NO_ARCHITECTURE_GREEN_CREDIT",
) -> dict[str, object]:
    """Build one honest S1 row; an unexecuted row is always SKIP."""

    _require(bool(leg_id), "MALFORMED_RED_LEG", "missing leg_id")
    argv = [str(item) for item in command_argv]
    if not executed:
        _require(bool(reason), "MALFORMED_RED_LEG", f"{leg_id}: SKIP requires reason")
        status = "SKIP"
        returncode = None
        failure_class = None
    else:
        _require(returncode is not None, "MALFORMED_RED_LEG", f"{leg_id}: missing returncode")
        status = "PASS" if returncode == 0 else "FAIL"
        if status == "FAIL":
            _require(bool(failure_class), "MALFORMED_RED_LEG", f"{leg_id}: FAIL requires class")
    row: dict[str, object] = {
        "leg_id": leg_id,
        "status": status,
        "executed": executed,
        "command_argv_sha256": _sha256_bytes(canonical_json(argv)),
        "started_at": started_at,
        "stopped_at": stopped_at,
        "returncode": returncode,
        "stdout_sha256": _sha256_bytes(stdout),
        "stderr_sha256": _sha256_bytes(stderr),
        "failure_class": failure_class,
        "claim_boundary": claim_boundary,
    }
    if reason is not None:
        row["reason"] = reason
    return row


def adjudicate_red_leg(
    leg_id: str,
    *,
    returncode: int,
    failure_class: str | None = None,
    command_argv: Sequence[str] = (),
    started_at: str | None = None,
    stopped_at: str | None = None,
    stdout: bytes = b"",
    stderr: bytes = b"",
) -> dict[str, object]:
    """Adjudicate an executed S1 command without converting failure to green."""

    return red_row(
        leg_id,
        executed=True,
        command_argv=command_argv,
        started_at=started_at,
        stopped_at=stopped_at,
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
        failure_class=failure_class,
    )


def run_red_matrix(
    profiles: Sequence[Mapping[str, object]],
    *,
    timeout_seconds: float = 120.0,
) -> dict[str, object]:
    """Execute a bounded caller-declared S1 matrix and preserve exact streams."""

    rows: list[dict[str, object]] = []
    streams: dict[str, dict[str, bytes]] = {}
    for profile in profiles:
        leg_id = str(profile.get("leg_id", ""))
        argv_value = profile.get("argv")
        if argv_value is None:
            rows.append(
                red_row(
                    leg_id,
                    executed=False,
                    reason=str(profile.get("reason") or "runner absent"),
                )
            )
            continue
        _require(isinstance(argv_value, list) and bool(argv_value), "MALFORMED_RED_LEG", leg_id)
        argv = [str(item) for item in argv_value]
        started_at = _utc_now()
        try:
            result = subprocess.run(
                argv,
                cwd=str(profile["cwd"]) if profile.get("cwd") else None,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout_seconds,
                check=False,
                creationflags=_NO_WINDOW,
            )
            returncode = result.returncode
            stdout = result.stdout
            stderr = result.stderr
            failure_class = None if returncode == 0 else str(profile.get("failure_class") or "COMMAND_FAILED")
        except subprocess.TimeoutExpired as exc:
            returncode = 124
            stdout = exc.stdout or b""
            stderr = exc.stderr or b""
            failure_class = "COMMAND_TIMEOUT"
        stopped_at = _utc_now()
        rows.append(
            adjudicate_red_leg(
                leg_id,
                returncode=returncode,
                failure_class=failure_class,
                command_argv=argv,
                started_at=started_at,
                stopped_at=stopped_at,
                stdout=stdout,
                stderr=stderr,
            )
        )
        streams[leg_id] = {"stdout": stdout, "stderr": stderr}
    return {"rows": rows, "streams": streams}


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def compile_receipt(
    repo: Path,
    policy: Mapping[str, Any],
    red_matrix: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Compile the full source-bound census, graph, exact K proof, and carriers."""

    repo = repo.resolve()
    validate_policy(policy)
    paths = tracked_paths(repo)
    path_rows = classify_paths(paths, policy)
    census = discover_consumers(repo, path_rows)
    dependencies = build_dependency_graph(census["rows"], policy)
    typed_roots = validate_typed_roots(policy)
    package_authorities = validate_package_authorities(repo, policy)
    touch_sets = build_touch_sets(path_rows, census["rows"])
    conflict_graph = build_conflict_graph(touch_sets, policy["reviewability"])
    precedence = build_touch_set_precedence(touch_sets, dependencies)
    graph = {**conflict_graph, "precedence": precedence}
    max_states = int(policy["reviewability"]["max_exact_search_states"])
    coloring = solve_minimum_coloring(
        graph["nodes"],
        [tuple(edge) for edge in graph["edges"]],
        [tuple(edge) for edge in precedence],
        max_states=max_states,
        node_weights=graph["node_weights"],
        capacities=graph["capacities"],
    )
    verify_coloring_certificate(graph, coloring, max_states)
    carriers = build_carrier_specs(touch_sets, coloring, graph["capacities"])
    policy_path = repo / "manifests" / "architecture" / "domain-authority-v1.json"
    schema_path = repo / "domains" / "governance" / "schemas" / "architecture" / "domain-authority-v1.schema.json"
    compiler_path = repo / "scripts" / "architecture_map.py"
    red_rows = [dict(row) for row in red_matrix]
    for row in red_rows:
        _require(row.get("status") in {"PASS", "FAIL", "SKIP"}, "MALFORMED_RED_LEG", str(row.get("leg_id")))
    return {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "goal_id": GOAL_ID,
        "workstream_id": WORKSTREAM_ID,
        "next_executed_outcome": NEXT_EXECUTED_OUTCOME,
        "claim_boundary": RECEIPT_CLAIM_BOUNDARY,
        "declared_host_envelope": DECLARED_HOST_ENVELOPE,
        "consumer_reference_bound": {
            "regex": _REFERENCE_RE.pattern,
            "regex_sha256": _sha256_bytes(_REFERENCE_RE.pattern.encode("utf-8")),
            "text_suffixes": sorted(_TEXT_SUFFIXES),
        },
        "verifier_cost_contract": VERIFIER_COST_CONTRACT,
        "source": {
            **git_identity(repo),
            "compiler_sha256": _file_sha256(compiler_path),
            "policy_sha256": _file_sha256(policy_path),
            "schema_sha256": _file_sha256(schema_path),
        },
        "census": {
            "tracked_path_count": len(paths),
            "classified_path_count": len(path_rows),
            "consumer_count": len(census["rows"]),
            "finding_count": len(census["findings"]),
            "class_counts": census["class_counts"],
            "paths_sha256": canonical_sha256(paths),
            "classification_sha256": canonical_sha256(path_rows),
            "consumers_sha256": canonical_sha256(census["rows"]),
            "findings_sha256": canonical_sha256(census["findings"]),
        },
        "typed_roots": typed_roots,
        "package_authorities": package_authorities,
        "dependency_graph": dependencies,
        "touch_sets": touch_sets,
        "conflict_graph": graph,
        "coloring": coloring,
        "k": coloring["k"],
        "carriers": carriers,
        "red_matrix": red_rows,
        "red_summary": {
            status: sum(1 for row in red_rows if row.get("status") == status)
            for status in ("PASS", "FAIL", "SKIP")
        },
        "max_states": max_states,
    }


def derive_self_sha256(receipt: Mapping[str, object]) -> str:
    payload = dict(receipt)
    payload.pop("self_sha256", None)
    return _sha256_bytes(canonical_json(payload))


def write_no_overwrite_receipt(
    path: Path,
    receipt: Mapping[str, object],
) -> tuple[str, str]:
    """Write canonical receipt bytes exactly once and return raw/self hashes."""

    if path.exists():
        raise ArchitectureMapError("OUTPUT_EXISTS", str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(receipt)
    payload["self_sha256"] = derive_self_sha256(payload)
    raw = canonical_json(payload) + b"\n"
    with path.open("xb") as handle:
        handle.write(raw)
    return _sha256_bytes(raw), str(payload["self_sha256"])


def _baseline_stream_paths(output: Path, leg_ids: Sequence[str]) -> dict[str, tuple[Path, Path]]:
    paths: dict[str, tuple[Path, Path]] = {}
    for leg_id in leg_ids:
        safe = re.sub(r"[^A-Za-z0-9_.-]", "-", leg_id)
        paths[leg_id] = (
            output.parent / f"{safe}.stdout",
            output.parent / f"{safe}.stderr",
        )
    return paths


def _refuse_existing_outputs(paths: Sequence[Path]) -> None:
    existing = [str(path) for path in paths if path.exists()]
    if existing:
        raise ArchitectureMapError("OUTPUT_EXISTS", existing[0])


def verify_receipt(
    repo: Path,
    policy_path: Path,
    receipt_path: Path,
) -> dict[str, object]:
    """Re-open exact bytes, verify self, and recompute every terminal field."""

    raw = receipt_path.read_bytes()
    try:
        supplied = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ArchitectureMapError("RECEIPT_UNREADABLE", str(receipt_path)) from exc
    _require(isinstance(supplied, dict), "RECEIPT_UNREADABLE", "root must be object")
    expected_self = derive_self_sha256(supplied)
    if supplied.get("self_sha256") != expected_self:
        raise ArchitectureMapError("RECEIPT_SELF_MISMATCH", str(receipt_path))
    expected_raw = canonical_json(supplied) + b"\n"
    if raw != expected_raw:
        raise ArchitectureMapError("RECEIPT_RAW_MISMATCH", str(receipt_path))
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    recomputed = compile_receipt(repo, policy, supplied.get("red_matrix", []))
    comparable = dict(supplied)
    comparable.pop("self_sha256", None)
    if canonical_json(comparable) != canonical_json(recomputed):
        raise ArchitectureMapError("RECEIPT_RECOMPUTE_MISMATCH", str(receipt_path))
    verify_coloring_certificate(
        supplied["conflict_graph"],
        supplied["coloring"],
        int(supplied["max_states"]),
    )
    return {
        "result": "PASS",
        "raw_sha256": _sha256_bytes(raw),
        "self_sha256": expected_self,
        "commit_sha": supplied["source"]["commit_sha"],
        "k": supplied["k"],
    }


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    baseline = subparsers.add_parser("baseline")
    baseline.add_argument("--profiles", type=Path, required=True)
    baseline.add_argument("--output", type=Path, required=True)
    baseline.add_argument("--timeout-seconds", type=float, default=120.0)
    compile_parser = subparsers.add_parser("compile")
    compile_parser.add_argument("--repo", type=Path, required=True)
    compile_parser.add_argument("--policy", type=Path, required=True)
    compile_parser.add_argument("--red-matrix", type=Path, required=True)
    compile_parser.add_argument("--output", type=Path, required=True)
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--repo", type=Path, required=True)
    verify_parser.add_argument("--policy", type=Path, required=True)
    verify_parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "baseline":
        profiles = _load_json(args.profiles)
        _require(isinstance(profiles, list), "MALFORMED_RED_MATRIX", "profiles root")
        leg_ids = [str(profile.get("leg_id", "")) for profile in profiles]
        stream_paths = _baseline_stream_paths(args.output, leg_ids)
        _refuse_existing_outputs(
            [args.output]
            + [path for pair in stream_paths.values() for path in pair]
        )
        result = run_red_matrix(profiles, timeout_seconds=args.timeout_seconds)
        rows = result["rows"]
        output = {"schema_version": "ember-issue1962-s1-red-matrix-v1", "rows": rows}
        for leg_id, streams in result["streams"].items():
            stdout_path, stderr_path = stream_paths[leg_id]
            stdout_path.parent.mkdir(parents=True, exist_ok=True)
            with stdout_path.open("xb") as handle:
                handle.write(streams["stdout"])
            with stderr_path.open("xb") as handle:
                handle.write(streams["stderr"])
        raw_sha, self_sha = write_no_overwrite_receipt(args.output, output)
        print(json.dumps({"result": "COMPLETE", "raw_sha256": raw_sha, "self_sha256": self_sha}, sort_keys=True))
        return 0
    if args.command == "compile":
        policy = _load_json(args.policy)
        red_payload = _load_json(args.red_matrix)
        red_rows = red_payload.get("rows", red_payload) if isinstance(red_payload, dict) else red_payload
        receipt = compile_receipt(args.repo, policy, red_rows)
        raw_sha, self_sha = write_no_overwrite_receipt(args.output, receipt)
        print(json.dumps({"result": "COMPLETE", "raw_sha256": raw_sha, "self_sha256": self_sha, "k": receipt["k"]}, sort_keys=True))
        return 0
    verdict = verify_receipt(args.repo, args.policy, args.receipt)
    print(json.dumps(verdict, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
