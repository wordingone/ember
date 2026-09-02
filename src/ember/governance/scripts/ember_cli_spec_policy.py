#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Fail-closed policy for ember-cli spec nodes and their production consumers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence


SPEC_ROOT = PurePosixPath("tools/ember-cli/specs")
CURRENT_STATUSES = {"CURRENT", "SHIPPED"}
KNOWN_STATUSES = CURRENT_STATUSES | {"OPEN", "HISTORICAL", "SUPERSEDED"}
CHANGED_FILE_STATUSES = {
    "added",
    "changed",
    "copied",
    "modified",
    "removed",
    "renamed",
}
ADDED_COMPONENT_RE = re.compile(
    r"^src/ember/infrastructure/tools/ember-cli/src/(?:components|screens|services)/"
    r"(?!.*(?:\.test|\.spec|\.d)\.ts$).+\.ts$"
)
STATUS_RE = re.compile(
    r"(?m)^Status:\s*(CURRENT|SHIPPED|OPEN|HISTORICAL|SUPERSEDED)\b"
)
CONSUMER_RE = re.compile(r"(?m)^Consumer:\s*(.+?)\s*$")
BACKTICK_PATH_RE = re.compile(r"`([^`\r\n]+)`")


class SpecPolicyError(ValueError):
    """A terminal spec-node policy violation."""


@dataclass(frozen=True)
class SpecNode:
    path: str
    status: str
    consumers: tuple[str, ...]


def _relative_posix(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _normalize_consumer(root: Path, value: str, *, spec_path: str) -> str:
    if (
        not value
        or "\\" in value
        or value.startswith("/")
        or re.match(r"^[A-Za-z]:", value)
    ):
        raise SpecPolicyError(f"{spec_path}:consumer-path-invalid:{value}")
    candidate = PurePosixPath(value)
    if (
        candidate.is_absolute()
        or any(part in {"", ".", ".."} for part in candidate.parts)
        or not candidate.parts
        or not (
            candidate.parts[0] == "tools"
            or candidate.parts[:3] == ("runtime", "ember-lab", "src")
        )
    ):
        raise SpecPolicyError(f"{spec_path}:consumer-path-invalid:{value}")
    normalized = candidate.as_posix()
    resolved = (root / Path(*candidate.parts)).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise SpecPolicyError(
            f"{spec_path}:consumer-path-invalid:{value}"
        ) from exc
    if not resolved.is_file():
        raise SpecPolicyError(f"{spec_path}:consumer-missing:{normalized}")
    return normalized


def _load_spec_node(root: Path, path: Path) -> SpecNode:
    relative = _relative_posix(root, path)
    try:
        text = path.read_bytes().decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise SpecPolicyError(f"{relative}:invalid-utf8") from exc

    statuses = STATUS_RE.findall(text)
    if len(statuses) != 1:
        raise SpecPolicyError(f"{relative}:status-cardinality")
    status = statuses[0]
    if status not in KNOWN_STATUSES:
        raise SpecPolicyError(f"{relative}:status-invalid")

    consumer_lines = CONSUMER_RE.findall(text)
    consumers: list[str] = []
    for line in consumer_lines:
        paths = BACKTICK_PATH_RE.findall(line)
        if not paths:
            raise SpecPolicyError(f"{relative}:consumer-line-invalid")
        consumers.extend(
            _normalize_consumer(root, item, spec_path=relative)
            for item in paths
        )
    if status in CURRENT_STATUSES and not consumers:
        raise SpecPolicyError(f"{relative}:consumer-required")
    if len(consumers) != len(set(consumers)):
        raise SpecPolicyError(f"{relative}:consumer-duplicate")
    return SpecNode(relative, status, tuple(consumers))


def load_spec_nodes(repo_root: Path) -> list[SpecNode]:
    """Load every ember-cli Markdown spec under a closed fail-closed contract."""

    root = repo_root.resolve()
    spec_dir = root / Path(*SPEC_ROOT.parts)
    if not spec_dir.is_dir():
        raise SpecPolicyError(f"{SPEC_ROOT.as_posix()}:directory-missing")
    paths = sorted(spec_dir.glob("*.md"), key=lambda item: item.name)
    if not paths:
        raise SpecPolicyError(f"{SPEC_ROOT.as_posix()}:empty")
    return [_load_spec_node(root, path) for path in paths]


def _changed_file_rows(
    changed_files: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, str]], list[str]]:
    rows: list[dict[str, str]] = []
    for row in changed_files:
        if not isinstance(row, Mapping):
            return [], ["spec-floor:changed-file-row-invalid"]
        filename = row.get("filename")
        status = row.get("status")
        if (
            not isinstance(filename, str)
            or not filename
            or "\\" in filename
            or not isinstance(status, str)
            or status not in CHANGED_FILE_STATUSES
        ):
            return [], ["spec-floor:changed-file-row-invalid"]
        rows.append({"filename": filename, "status": status})
    return rows, []


def validate_added_component_coverage(
    repo_root: Path,
    changed_files: Sequence[Mapping[str, Any]],
) -> list[str]:
    """Require every added ember-cli component to be consumed by a changed spec."""

    rows, errors = _changed_file_rows(changed_files)
    if errors:
        return errors
    added = sorted(
        row["filename"]
        for row in rows
        if row["status"] == "added" and ADDED_COMPONENT_RE.fullmatch(row["filename"])
    )
    if not added:
        return []
    changed_specs = {
        row["filename"]
        for row in rows
        if row["status"] in {"added", "changed", "copied", "modified", "renamed"}
        and row["filename"].startswith(f"{SPEC_ROOT.as_posix()}/")
        and row["filename"].endswith(".md")
    }
    try:
        nodes = load_spec_nodes(repo_root)
    except SpecPolicyError as exc:
        return [f"spec-floor:{exc}"]
    covered = {
        consumer
        for node in nodes
        if node.path in changed_specs
        for consumer in node.consumers
    }
    return [
        f"spec-floor:added-component-unbound:{path}"
        for path in added
        if path not in covered
    ]


def validate_added_component_coverage_between_roots(
    base_root: Path,
    subject_root: Path,
    changed_files: Sequence[str],
) -> list[str]:
    """Bind newly added ember-cli components to changed subject spec nodes."""

    base = base_root.resolve()
    subject = subject_root.resolve()
    if not base.is_dir():
        return ["spec-floor:base-root-invalid"]
    if not subject.is_dir():
        return ["spec-floor:subject-root-invalid"]

    normalized: list[str] = []
    for value in changed_files:
        if (
            not isinstance(value, str)
            or not value
            or "\\" in value
            or value.startswith("/")
            or re.match(r"^[A-Za-z]:", value)
        ):
            return ["spec-floor:changed-file-path-invalid"]
        path = PurePosixPath(value)
        if path.is_absolute() or any(
            part in {"", ".", ".."} for part in path.parts
        ):
            return ["spec-floor:changed-file-path-invalid"]
        normalized.append(path.as_posix())

    added: list[str] = []
    for value in sorted(set(normalized)):
        if not ADDED_COMPONENT_RE.fullmatch(value):
            continue
        parts = PurePosixPath(value).parts
        base_path = base / Path(*parts)
        subject_path = subject / Path(*parts)
        if not base_path.exists() and subject_path.is_file():
            added.append(value)
        elif not base_path.exists() and not subject_path.exists():
            return [f"spec-floor:changed-path-missing:{value}"]
    if not added:
        return []

    changed_specs = {
        value
        for value in normalized
        if value.startswith(f"{SPEC_ROOT.as_posix()}/")
        and value.endswith(".md")
    }
    try:
        nodes = load_spec_nodes(subject)
    except SpecPolicyError as exc:
        return [f"spec-floor:{exc}"]
    covered = {
        consumer
        for node in nodes
        if node.path in changed_specs
        for consumer in node.consumers
    }
    return [
        f"spec-floor:added-component-unbound:{path}"
        for path in added
        if path not in covered
    ]
