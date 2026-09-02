#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Fail-closed verifier for Ember's legacy-to-current authority crosswalk."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
from pathlib import Path, PurePosixPath
from typing import Any


SCHEMA_VERSION = "ember-authority-supersession-crosswalk-v1"
REPOSITORY = "wordingone/ember"
HISTORICAL_TERMINAL = "HISTORICAL_ORPHANED"
DISPOSITIONS = {"SUPERSEDED", "HISTORICAL_ORPHANED", "CUSTODY_GAP"}
SOURCE_KINDS = {
    "obligation",
    "defect",
    "watcher",
    "doc_divergence",
    "legacy_milestone",
    "legacy_condition",
}
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
DISCREPANCY = re.compile(r"\|\s*(D-\d{3})\s*\|")
MILESTONE = re.compile(r"^EMBER-\d{2}$")

TOP_FIELDS = {
    "schema_version",
    "repository",
    "source_commit",
    "current_authority",
    "source_registries",
    "rows",
    "crosswalk_sha256",
}
AUTHORITY_FIELDS = {
    "matrix_path",
    "matrix_sha256",
    "discrepancy_ids",
    "milestone_ids",
    "historical_terminal",
}
REGISTRY_FIELDS = {"registry_id", "expected_source_ids", "evidence"}
ROW_FIELDS = {
    "source_registry",
    "source_id",
    "source_kind",
    "statement",
    "disposition",
    "targets",
    "evidence",
    "completion_credit",
}
EVIDENCE_FIELDS = {"path", "sha256"}


class CrosswalkError(ValueError):
    """The authority crosswalk is malformed, stale, or lossy."""


def _canonical_sha256(payload: dict[str, Any]) -> str:
    body = copy.deepcopy(payload)
    body.pop("crosswalk_sha256", None)
    encoded = json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _closed(value: Any, fields: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CrosswalkError(f"{label} must be an object")
    actual = set(value)
    if actual != fields:
        raise CrosswalkError(
            f"{label} fields must be exactly {sorted(fields)}; "
            f"missing={sorted(fields - actual)} extra={sorted(actual - fields)}"
        )
    return value


def _string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise CrosswalkError(f"{label} must be a nonempty trimmed string")
    return value


def _string_list(value: Any, label: str, *, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list) or (not value and not allow_empty):
        raise CrosswalkError(f"{label} must be a list of strings")
    result = [_string(item, f"{label} entry") for item in value]
    if len(result) != len(set(result)):
        raise CrosswalkError(f"{label} contains duplicate values")
    return result


def _repo_path(root: Path, raw: Any, label: str) -> Path:
    value = _string(raw, label)
    if "\\" in value:
        raise CrosswalkError(f"{label} must use repository-relative POSIX syntax")
    pure = PurePosixPath(value)
    if pure.is_absolute() or not pure.parts or ".." in pure.parts or "." in pure.parts:
        raise CrosswalkError(f"{label} escapes the repository")
    candidate = (root / Path(*pure.parts)).resolve()
    resolved_root = root.resolve()
    try:
        candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise CrosswalkError(f"{label} escapes the repository") from exc
    if not candidate.is_file():
        raise CrosswalkError(f"{label} does not resolve to a file: {value}")
    return candidate


def _verify_evidence(root: Path, value: Any, label: str) -> list[dict[str, str]]:
    if not isinstance(value, list) or not value:
        raise CrosswalkError(f"{label} evidence must be a nonempty list")
    seen: set[str] = set()
    result: list[dict[str, str]] = []
    for index, raw in enumerate(value):
        row = _closed(raw, EVIDENCE_FIELDS, f"{label} evidence[{index}]")
        path_text = _string(row["path"], f"{label} evidence path")
        if path_text in seen:
            raise CrosswalkError(f"{label} evidence contains duplicate paths")
        seen.add(path_text)
        expected = _string(row["sha256"], f"{label} evidence sha256")
        if not HEX64.fullmatch(expected):
            raise CrosswalkError(f"{label} evidence sha256 is malformed")
        path = _repo_path(root, path_text, f"{label} evidence path")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            raise CrosswalkError(
                f"{label} evidence hash mismatch for {path_text}: "
                f"expected {expected}, got {actual}"
            )
        result.append({"path": path_text, "sha256": expected})
    return result


def _live_discrepancy_ids(matrix_path: Path) -> list[str]:
    ids = DISCREPANCY.findall(matrix_path.read_text(encoding="utf-8"))
    unique = sorted(set(ids))
    if not unique:
        raise CrosswalkError("authority matrix contains no D identifiers")
    return unique


def _live_milestone_ids(root: Path) -> list[str]:
    candidates = (
        Path("docs") / "roadmap" / "milestones",
        Path("docs") / "domains" / "governance" / "roadmap" / "milestones",
    )
    present = [relative for relative in candidates if (root / relative).is_dir()]
    if len(present) > 1:
        raise CrosswalkError(
            "duplicate roadmap milestone layouts; expected exactly one, found: "
            + ", ".join(relative.as_posix() for relative in present)
        )
    if not present:
        raise CrosswalkError("roadmap contains no milestone contracts")
    milestone_root = root / present[0]
    ids = sorted(
        path.stem
        for path in milestone_root.glob("EMBER-*.md")
        if MILESTONE.fullmatch(path.stem)
    )
    if not ids:
        raise CrosswalkError("roadmap contains no milestone contracts")
    return ids


def validate_crosswalk(
    root: Path,
    payload: dict[str, Any],
    *,
    expected_source_commit: str | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    body = _closed(payload, TOP_FIELDS, "top-level")
    if body["schema_version"] != SCHEMA_VERSION:
        raise CrosswalkError("schema_version is not supported")
    if body["repository"] != REPOSITORY:
        raise CrosswalkError("repository is not wordingone/ember")
    source_commit = _string(body["source_commit"], "source commit")
    if not HEX40.fullmatch(source_commit):
        raise CrosswalkError("source commit must be lowercase 40-hex")
    if expected_source_commit is not None and source_commit != expected_source_commit:
        raise CrosswalkError(
            f"source commit mismatch: expected {expected_source_commit}, got {source_commit}"
        )

    recorded_crosswalk_sha = _string(
        body["crosswalk_sha256"], "crosswalk hash"
    )
    actual_crosswalk_sha = _canonical_sha256(body)
    if not HEX64.fullmatch(recorded_crosswalk_sha) or (
        recorded_crosswalk_sha != actual_crosswalk_sha
    ):
        raise CrosswalkError(
            f"crosswalk hash mismatch: expected {recorded_crosswalk_sha}, "
            f"got {actual_crosswalk_sha}"
        )

    authority = _closed(
        body["current_authority"], AUTHORITY_FIELDS, "current authority"
    )
    matrix_path_text = _string(authority["matrix_path"], "matrix path")
    matrix_path = _repo_path(root, matrix_path_text, "matrix path")
    matrix_sha = _string(authority["matrix_sha256"], "matrix hash")
    actual_matrix_sha = hashlib.sha256(matrix_path.read_bytes()).hexdigest()
    if not HEX64.fullmatch(matrix_sha) or matrix_sha != actual_matrix_sha:
        raise CrosswalkError(
            f"matrix hash mismatch: expected {matrix_sha}, got {actual_matrix_sha}"
        )

    discrepancy_ids = _string_list(
        authority["discrepancy_ids"], "discrepancy_ids"
    )
    live_discrepancies = _live_discrepancy_ids(matrix_path)
    if sorted(discrepancy_ids) != live_discrepancies:
        raise CrosswalkError(
            "discrepancy_ids do not equal the live authority matrix"
        )
    milestone_ids = _string_list(authority["milestone_ids"], "milestone_ids")
    live_milestones = _live_milestone_ids(root)
    if sorted(milestone_ids) != live_milestones:
        raise CrosswalkError("milestone_ids do not equal live roadmap contracts")
    if authority["historical_terminal"] != HISTORICAL_TERMINAL:
        raise CrosswalkError("historical terminal is not closed")
    current_targets = set(discrepancy_ids) | set(milestone_ids) | {
        HISTORICAL_TERMINAL
    }

    registries_raw = body["source_registries"]
    if not isinstance(registries_raw, list) or not registries_raw:
        raise CrosswalkError("source_registries must be a nonempty list")
    registries: dict[str, set[str]] = {}
    for index, raw in enumerate(registries_raw):
        registry = _closed(raw, REGISTRY_FIELDS, f"source registry[{index}]")
        registry_id = _string(registry["registry_id"], "registry_id")
        if registry_id in registries:
            raise CrosswalkError(f"duplicate source registry: {registry_id}")
        expected_ids = set(
            _string_list(
                registry["expected_source_ids"],
                f"{registry_id} expected_source_ids",
            )
        )
        _verify_evidence(root, registry["evidence"], registry_id)
        registries[registry_id] = expected_ids

    rows_raw = body["rows"]
    if not isinstance(rows_raw, list) or not rows_raw:
        raise CrosswalkError("rows must be a nonempty list")
    observed: dict[str, set[str]] = {key: set() for key in registries}
    seen_pairs: set[tuple[str, str]] = set()
    custody_gap_count = 0
    disposition_counts = {key: 0 for key in sorted(DISPOSITIONS)}
    for index, raw in enumerate(rows_raw):
        row = _closed(raw, ROW_FIELDS, f"row[{index}]")
        registry_id = _string(row["source_registry"], "row source_registry")
        source_id = _string(row["source_id"], "row source_id")
        pair = (registry_id, source_id)
        if pair in seen_pairs:
            raise CrosswalkError(
                f"duplicate source row: {registry_id}/{source_id}"
            )
        seen_pairs.add(pair)
        if registry_id not in registries:
            raise CrosswalkError(f"row references unknown registry: {registry_id}")
        if source_id not in registries[registry_id]:
            raise CrosswalkError(
                f"row source id is not declared: {registry_id}/{source_id}"
            )
        observed[registry_id].add(source_id)
        kind = _string(row["source_kind"], "row source_kind")
        if kind not in SOURCE_KINDS:
            raise CrosswalkError(f"unsupported source_kind: {kind}")
        _string(row["statement"], "row statement")
        disposition = _string(row["disposition"], "row disposition")
        if disposition not in DISPOSITIONS:
            raise CrosswalkError(f"unsupported disposition: {disposition}")
        targets = _string_list(
            row["targets"], "row targets", allow_empty=True
        )
        unknown_targets = sorted(set(targets) - current_targets)
        if unknown_targets:
            raise CrosswalkError(
                f"unknown current target(s): {','.join(unknown_targets)}"
            )
        if row["completion_credit"] is not False:
            raise CrosswalkError(
                "legacy rows and custody gaps may never grant completion credit"
            )
        if disposition == "CUSTODY_GAP":
            custody_gap_count += 1
            if targets:
                raise CrosswalkError("CUSTODY_GAP rows must not name targets")
        elif disposition == "HISTORICAL_ORPHANED":
            if targets != [HISTORICAL_TERMINAL]:
                raise CrosswalkError(
                    "HISTORICAL_ORPHANED rows must target only the historical terminal"
                )
        elif not targets or HISTORICAL_TERMINAL in targets:
            raise CrosswalkError(
                "SUPERSEDED rows require at least one live D or milestone target"
            )
        _verify_evidence(
            root, row["evidence"], f"{registry_id}/{source_id}"
        )
        disposition_counts[disposition] += 1

    for registry_id, expected_ids in registries.items():
        missing = sorted(expected_ids - observed[registry_id])
        extra = sorted(observed[registry_id] - expected_ids)
        if missing or extra:
            raise CrosswalkError(
                f"unaccounted source ids for {registry_id}: "
                f"missing={missing} extra={extra}"
            )

    return {
        "status": "PASS_WITH_CUSTODY_GAPS" if custody_gap_count else "PASS",
        "row_count": len(rows_raw),
        "custody_gap_count": custody_gap_count,
        "disposition_counts": disposition_counts,
        "crosswalk_sha256": recorded_crosswalk_sha,
        "source_commit": source_commit,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--crosswalk", type=Path, required=True)
    parser.add_argument("--expected-source-commit")
    args = parser.parse_args(argv)
    try:
        payload = json.loads(args.crosswalk.read_text(encoding="utf-8"))
        result = validate_crosswalk(
            args.repo,
            payload,
            expected_source_commit=args.expected_source_commit,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, CrosswalkError) as exc:
        print(
            json.dumps(
                {"status": "FAIL", "error": str(exc)},
                sort_keys=True,
                separators=(",", ":"),
            ),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
