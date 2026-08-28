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
import fnmatch
import json
import re
import subprocess
import warnings
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
