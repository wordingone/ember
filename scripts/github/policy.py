#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Deterministic, non-semantic GitHub policy validation for Ember.

The validator proves structure and consistency. It never treats section
presence, a label, or a green result as proof that a scientific or capability
claim is true.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml


LABEL_FIELDS = {
    "name",
    "description",
    "color",
    "family",
    "applicability",
    "minimum_cardinality",
    "maximum_cardinality",
    "mutual_exclusions",
    "required",
    "automation_may_add",
    "automation_may_remove",
    "deprecated",
}
MIGRATION_FIELDS = {
    "source_label",
    "disposition",
    "destination",
    "rationale",
    "applicability",
    "deterministic",
    "human_or_operator_judgment_required",
    "usage_count_before",
    "expected_usage_count_after",
}
DISPOSITIONS = {
    "KEEP",
    "RENAME",
    "MERGE_INTO",
    "REPLACE_WITH_NATIVE_RELATIONSHIP",
    "DEPRECATE_AFTER_MIGRATION",
    "DELETE_IF_UNUSED",
}
KINDS = {
    "kind:initiative",
    "kind:defect",
    "kind:feature",
    "kind:enhancement",
    "kind:engineering",
    "kind:research",
    "kind:experiment",
    "kind:model-behavior",
    "kind:maintenance",
    "kind:documentation",
    "kind:governance",
    "kind:release",
}
ISSUE_REQUIRED = {
    "template_marker",
    "kind",
    "outcome",
    "current_state",
    "desired_state",
    "scope",
    "out_of_scope",
    "areas",
    "milestone",
    "dependencies",
    "evidence_required",
    "claim_boundary",
    "terminal_disposition",
}
PR_REQUIRED = {
    "template_marker",
    "kind",
    "base_sha",
    "reviewed_head_sha",
    "outcome",
    "coherent_reason",
    "areas",
    "milestones",
    "implementation_summary",
    "acceptance_mapping",
    "local_reproduction",
    "automated_tests",
    "executed_evidence",
    "generated_artifacts",
    "known_failures",
    "unverified_areas",
    "claim_boundary",
    "review_provenance",
    "rollback",
    "follow_up_obligations",
}


@dataclass(frozen=True)
class ValidationResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors


def _load(path: Path) -> Any:
    raw = path.read_text(encoding="utf-8", errors="strict")
    value = yaml.safe_load(raw)
    if not isinstance(value, dict):
        raise ValueError(f"{path}: top-level object must be a mapping")
    return value


def _closed_keys(
    obj: Mapping[str, Any], allowed: set[str], context: str, errors: list[str]
) -> None:
    unknown = sorted(set(obj) - allowed)
    missing = sorted(allowed - set(obj))
    if unknown:
        errors.append(f"{context}: unknown fields: {', '.join(unknown)}")
    if missing:
        errors.append(f"{context}: missing fields: {', '.join(missing)}")


def validate_label_manifest(path: Path) -> ValidationResult:
    errors: list[str] = []
    try:
        data = _load(path)
    except Exception as exc:
        return ValidationResult(errors=[f"label manifest unreadable: {exc}"])
    if set(data) != {
        "schema_version",
        "repository",
        "namespace_separator",
        "generated_policy",
        "labels",
    }:
        errors.append("label manifest top-level schema is not closed")
    if data.get("schema_version") != "ember-label-manifest/v1":
        errors.append("label manifest schema_version mismatch")
    labels = data.get("labels")
    if not isinstance(labels, list):
        return ValidationResult(errors=errors + ["labels must be a list"])
    names: set[str] = set()
    for index, row in enumerate(labels):
        context = f"label[{index}]"
        if not isinstance(row, dict):
            errors.append(f"{context}: must be a mapping")
            continue
        _closed_keys(row, LABEL_FIELDS, context, errors)
        name = row.get("name")
        if not isinstance(name, str) or not name or " " in name:
            errors.append(f"{context}: invalid name")
        elif name in names:
            errors.append(f"{context}: duplicate name {name}")
        else:
            names.add(name)
        color = row.get("color")
        if not isinstance(color, str) or not re.fullmatch(r"[0-9A-Fa-f]{6}", color):
            errors.append(f"{context}: color must be six hex digits")
        family = row.get("family")
        if not isinstance(family, str) or not str(name).startswith(f"{family}:"):
            errors.append(f"{context}: name/family mismatch")
        if row.get("applicability") not in {"issue", "pull_request", "both"}:
            errors.append(f"{context}: invalid applicability")
        minimum = row.get("minimum_cardinality")
        maximum = row.get("maximum_cardinality")
        if (
            not isinstance(minimum, int)
            or isinstance(minimum, bool)
            or not isinstance(maximum, int)
            or isinstance(maximum, bool)
            or minimum < 0
            or maximum < minimum
        ):
            errors.append(f"{context}: invalid cardinality")
        exclusions = row.get("mutual_exclusions")
        if not isinstance(exclusions, list) or not all(
            isinstance(x, str) for x in exclusions
        ):
            errors.append(f"{context}: mutual_exclusions must be a string list")
        for boolean in (
            "required",
            "automation_may_add",
            "automation_may_remove",
            "deprecated",
        ):
            if not isinstance(row.get(boolean), bool):
                errors.append(f"{context}: {boolean} must be boolean")
    for index, row in enumerate(labels):
        if isinstance(row, dict):
            for exclusion in row.get("mutual_exclusions", []):
                if exclusion not in names:
                    errors.append(f"label[{index}]: unknown exclusion {exclusion}")
    return ValidationResult(errors=errors, details={"label_count": len(labels)})


def validate_label_migrations(path: Path, manifest_path: Path) -> ValidationResult:
    errors: list[str] = []
    try:
        data = _load(path)
        manifest = _load(manifest_path)
    except Exception as exc:
        return ValidationResult(errors=[f"migration manifest unreadable: {exc}"])
    if set(data) != {"schema_version", "repository", "captured_at", "rules"}:
        errors.append("migration manifest top-level schema is not closed")
    if data.get("schema_version") != "ember-label-migrations/v1":
        errors.append("migration manifest schema_version mismatch")
    destinations = {row["name"] for row in manifest.get("labels", [])}
    rules = data.get("rules")
    if not isinstance(rules, list):
        return ValidationResult(errors=errors + ["rules must be a list"])
    sources: set[str] = set()
    for index, row in enumerate(rules):
        context = f"migration[{index}]"
        if not isinstance(row, dict):
            errors.append(f"{context}: must be a mapping")
            continue
        _closed_keys(row, MIGRATION_FIELDS, context, errors)
        source = row.get("source_label")
        if not isinstance(source, str) or not source:
            errors.append(f"{context}: invalid source label")
        elif source in sources:
            errors.append(f"{context}: duplicate source {source}")
        else:
            sources.add(source)
        if row.get("disposition") not in DISPOSITIONS:
            errors.append(f"{context}: invalid disposition")
        destination = row.get("destination")
        values: Iterable[Any]
        if isinstance(destination, dict):
            if set(destination) != {"issue", "pull_request"}:
                errors.append(f"{context}: destination mapping must bind both item types")
            values = destination.values()
        else:
            values = (destination,)
        for value in values:
            if value is not None and value not in destinations:
                errors.append(f"{context}: unknown destination {value}")
        for counts_name in ("usage_count_before", "expected_usage_count_after"):
            counts = row.get(counts_name)
            if not isinstance(counts, dict) or set(counts) != {
                "issues",
                "pull_requests",
                "total",
            }:
                errors.append(f"{context}: invalid {counts_name}")
            elif counts["total"] != counts["issues"] + counts["pull_requests"]:
                errors.append(f"{context}: inconsistent {counts_name}")
    return ValidationResult(errors=errors, details={"migration_count": len(rules)})


def _blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def validate_issue(issue: Mapping[str, Any]) -> ValidationResult:
    errors: list[str] = []
    missing = sorted(key for key in ISSUE_REQUIRED if key not in issue or _blank(issue[key]))
    if missing:
        errors.append(f"issue:missing:{','.join(missing)}")
    kind = issue.get("kind")
    if kind not in KINDS - {"kind:release"}:
        errors.append("issue:invalid-kind")
    outcome = str(issue.get("outcome", "")).lower()
    scope = str(issue.get("scope", "")).lower()
    if (
        "counter" in outcome
        or "counter" in scope
        or re.search(r"\bclose issue #?\d+\b", outcome + " " + scope)
    ):
        errors.append("busywork:counter-decrement")
    type_required = {
        "kind:enhancement": {"baseline", "success_metric"},
        "kind:research": {"hypothesis", "falsification"},
        "kind:experiment": {
            "treatment",
            "control",
            "model_identity",
            "dataset_identity",
            "kill_criteria",
        },
    }.get(str(kind), set())
    missing_type = sorted(k for k in type_required if _blank(issue.get(k)))
    if missing_type:
        errors.append(f"issue:type-required:{','.join(missing_type)}")
    if kind == "kind:feature" and "existing" in outcome and issue.get("success_metric"):
        errors.append("issue:feature-enhancement-ambiguity")
    if kind == "kind:experiment":
        haystack = " ".join(str(issue.get(k, "")) for k in ("outcome", "treatment", "control"))
        if "rewrap" in haystack.lower() or (
            "no new treatment" in haystack.lower() and "no control" in haystack.lower()
        ):
            errors.append("busywork:receipt-only-experiment")
    areas = issue.get("areas")
    if not isinstance(areas, list) or not 1 <= len(areas) <= 3:
        errors.append("issue:area-cardinality")
    return ValidationResult(errors=errors)


def validate_pull_request(pr: Mapping[str, Any]) -> ValidationResult:
    errors: list[str] = []
    missing = sorted(key for key in PR_REQUIRED if key not in pr)
    if missing:
        errors.append(f"pr:missing:{','.join(missing)}")
    linked = str(pr.get("linked_issue", "")).strip()
    exception = str(pr.get("exception", "")).strip()
    if not linked and not exception:
        errors.append("pr:linked-outcome-required")
    closing = bool(re.search(r"\b(close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#\d+", linked, re.I))
    if closing and _blank(pr.get("acceptance_mapping")):
        errors.append("pr:closing-acceptance-mapping-required")
    if int(pr.get("homogeneous_repair_count", 0) or 0) > 1 and _blank(
        pr.get("coherent_reason")
    ):
        errors.append("batching:rationale-required")
    for sha_field in ("base_sha", "reviewed_head_sha"):
        value = pr.get(sha_field)
        if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{40}", value):
            errors.append(f"pr:{sha_field}-invalid")
    return ValidationResult(errors=errors)


def example_issue(
    *,
    kind: str,
    outcome: str,
    current_state: str = "The current repository state does not satisfy the outcome.",
    desired_state: str = "The stated outcome is satisfied with bounded evidence.",
    scope: str = "One durable repository outcome.",
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "template_marker": f"issue/{kind.removeprefix('kind:')}@v1",
        "kind": kind,
        "outcome": outcome,
        "current_state": current_state,
        "desired_state": desired_state,
        "scope": scope,
        "out_of_scope": "Unrelated repository behavior.",
        "areas": ["area:governance"],
        "milestone": "EMBER-01",
        "dependencies": "None.",
        "evidence_required": "A bounded test or exact receipt.",
        "claim_boundary": "No capability or scientific claim.",
        "terminal_disposition": "Close only when every acceptance clause is met.",
    }
    result.update(extra or {})
    return result


def example_pr(
    *,
    linked_issue: str = "#17",
    exception: str = "",
    outcome: str = "Deliver one coherent tested repository outcome.",
    coherent_reason: str = "All changes share one rollback and review boundary.",
    acceptance_mapping: str = "Clause 1 -> test_policy.py",
) -> dict[str, Any]:
    return {
        "template_marker": "pr/engineering@v1",
        "kind": "kind:engineering",
        "linked_issue": linked_issue,
        "exception": exception,
        "base_sha": "a" * 40,
        "reviewed_head_sha": "b" * 40,
        "outcome": outcome,
        "coherent_reason": coherent_reason,
        "areas": ["area:governance"],
        "milestones": ["EMBER-01"],
        "implementation_summary": "Implementation.",
        "acceptance_mapping": acceptance_mapping,
        "local_reproduction": "python -B -m unittest",
        "automated_tests": "Unit tests.",
        "executed_evidence": "Bounded local result.",
        "generated_artifacts": "None.",
        "known_failures": "None.",
        "unverified_areas": "None.",
        "claim_boundary": "No capability claim.",
        "review_provenance": "Self-review at exact head.",
        "rollback": "git revert <merge>",
        "follow_up_obligations": "None.",
    }


def evaluate_repository_health(metrics: Mapping[str, Any]) -> dict[str, Any]:
    """Keep correctness separate from activity measurements."""
    required = metrics.get("required_checks")
    status = "PASS" if required == "PASS" else "FAIL"
    return {"status": status, "measurements": dict(metrics)}


def _emit(result: ValidationResult) -> int:
    print(
        json.dumps(
            {
                "status": "PASS" if result.ok else "FAIL",
                "errors": result.errors,
                "warnings": result.warnings,
                "details": result.details,
                "claim_boundary": "structural validation only",
            },
            sort_keys=True,
        )
    )
    return 0 if result.ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    labels = sub.add_parser("labels")
    labels.add_argument("--manifest", type=Path, required=True)
    migrations = sub.add_parser("migrations")
    migrations.add_argument("--manifest", type=Path, required=True)
    migrations.add_argument("--migrations", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "labels":
        return _emit(validate_label_manifest(args.manifest))
    return _emit(validate_label_migrations(args.migrations, args.manifest))


if __name__ == "__main__":
    raise SystemExit(main())
