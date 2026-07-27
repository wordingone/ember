#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Plan and apply the validated GitHub roadmap projection.

The planner is deliberately transport-independent.  A caller captures live
GitHub state through the repository's safe wrapper, obtains an exact mutation
plan, and passes an injected client to ``apply_plan``.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Protocol


class ProjectionError(ValueError):
    pass


class ProjectionApplyError(RuntimeError):
    def __init__(self, message: str, completed: list[dict[str, Any]]) -> None:
        super().__init__(message)
        self.completed = completed


class ProjectionClient(Protocol):
    def execute(self, operation: dict[str, Any]) -> Any: ...


def _rows(rows: Any, key: str, noun: str) -> dict[Any, dict[str, Any]]:
    if not isinstance(rows, list):
        raise ProjectionError(f"{noun} rows must be a list")
    result: dict[Any, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or key not in row:
            raise ProjectionError(f"invalid {noun} row")
        value = row[key]
        if value in result:
            raise ProjectionError(f"duplicate {noun} {value}")
        result[value] = row
    return result


def _same_label(live: dict[str, Any], desired: dict[str, Any]) -> bool:
    return (
        str(live.get("color", "")).lower() == str(desired["color"]).lower()
        and (live.get("description") or "") == (desired.get("description") or "")
    )


def _same_milestone(live: dict[str, Any], desired: dict[str, Any]) -> bool:
    return all(
        live.get(key) == desired.get(key)
        for key in ("title", "description", "state", "due_on")
    )


def _operation(op: str, **payload: Any) -> dict[str, Any]:
    return {"op": op, **deepcopy(payload)}


def build_mutation_plan(
    projection: dict[str, Any],
    live: dict[str, Any],
    *,
    publication_master_sha: str | None = None,
) -> list[dict[str, Any]]:
    """Return a deterministic, closure-free mutation plan or refuse drift."""

    if projection.get("issue_closures") != [] or any(
        row.get("close") is not False
        for row in projection.get("issue_mutations", [])
    ):
        raise ProjectionError("issue closure mutation is forbidden")
    expected_master = publication_master_sha or projection.get("source_master_sha")
    if live.get("master_sha") != expected_master:
        raise ProjectionError("public master drift")
    if (
        publication_master_sha is not None
        and live.get("projection_source_is_ancestor") is not True
    ):
        raise ProjectionError("projection source is not a proven ancestor")

    desired_labels = _rows(projection.get("labels"), "name", "label")
    desired_milestones = _rows(
        projection.get("milestones"), "milestone_id", "milestone"
    )
    desired_parents = _rows(
        projection.get("parent_issues"), "tracking_key", "parent tracking key"
    )
    desired_issues = _rows(
        projection.get("issue_mutations"), "number", "issue mutation"
    )

    live_labels = live.get("labels", {})
    live_milestones = live.get("milestones", {})
    live_parents = live.get("parents", {})
    live_issues = live.get("issues", {})
    live_dependencies = live.get("dependencies", {})
    for key, value in live_parents.items():
        if isinstance(value, list):
            if len(value) != 1:
                raise ProjectionError(f"duplicate parent tracking key {key}")
            live_parents[key] = value[0]

    live_open_numbers = live.get("open_issue_numbers")
    if live_open_numbers is not None:
        expected_numbers = set(desired_issues)
        expected_numbers.update(
            int(parent["number"])
            for parent in live_parents.values()
            if isinstance(parent, dict) and "number" in parent
        )
        if set(live_open_numbers) != expected_numbers:
            raise ProjectionError("open issue population drift")

    for number, desired in desired_issues.items():
        current = live_issues.get(number)
        if current is None:
            raise ProjectionError(f"issue {number} is missing")
        if current.get("state") != "open" or current.get(
            "body_sha256"
        ) != desired.get("expected_body_sha256"):
            raise ProjectionError(f"issue {number} drift")
        baseline_labels = set(desired.get("expected_labels", []))
        allowed_labels = baseline_labels | set(desired.get("add_labels", []))
        current_labels = set(current.get("labels", []))
        if not baseline_labels <= current_labels <= allowed_labels:
            raise ProjectionError(f"issue {number} drift")
        allowed_milestones = {
            desired.get("expected_milestone_id"),
            desired.get("set_milestone"),
        }
        if current.get("milestone_id") not in allowed_milestones:
            raise ProjectionError(f"issue {number} drift")
        if current.get("parent_tracking_key") not in (
            None,
            desired.get("add_as_subissue_of"),
        ):
            raise ProjectionError(f"issue {number} drift")
        if current.get("updated_at") != desired.get(
            "expected_updated_at"
        ) and current_labels == baseline_labels and current.get(
            "milestone_id"
        ) == desired.get("expected_milestone_id") and current.get(
            "parent_tracking_key"
        ) is None:
            raise ProjectionError(f"issue {number} drift")

    plan: list[dict[str, Any]] = []
    for name in sorted(desired_labels):
        desired = desired_labels[name]
        current = live_labels.get(name)
        if current is None:
            plan.append(_operation("create_label", label=desired))
        elif not _same_label(current, desired):
            plan.append(_operation("update_label", label=desired))

    for milestone_id in sorted(desired_milestones):
        desired = desired_milestones[milestone_id]
        current = live_milestones.get(milestone_id)
        if current is None:
            plan.append(_operation("create_milestone", milestone=desired))
        elif not _same_milestone(current, desired):
            plan.append(
                _operation(
                    "update_milestone",
                    milestone=desired,
                    milestone_number=current["number"],
                )
            )

    for tracking_key in sorted(desired_parents):
        desired = desired_parents[tracking_key]
        current = live_parents.get(tracking_key)
        if current is None:
            plan.append(_operation("create_parent_issue", parent=desired))
            continue
        desired_labels_set = set(desired.get("labels", []))
        current_labels = set(current.get("labels", []))
        if (
            current.get("title") != desired.get("title")
            or current.get("body") != desired.get("body")
            or current.get("milestone_id") != desired.get("milestone_id")
        ):
            plan.append(
                _operation(
                    "update_parent_issue",
                    parent=desired,
                    issue_number=current["number"],
                )
            )
        missing = sorted(desired_labels_set - current_labels)
        if missing:
            plan.append(
                _operation(
                    "add_parent_labels",
                    tracking_key=tracking_key,
                    issue_number=current["number"],
                    labels=missing,
                )
            )

    for tracking_key in sorted(desired_parents):
        desired = desired_parents[tracking_key]
        current_dependencies = set(live_dependencies.get(tracking_key, []))
        for dependency in sorted(desired.get("depends_on", [])):
            if dependency not in desired_parents:
                raise ProjectionError(f"unknown parent dependency {dependency}")
            if dependency not in current_dependencies:
                plan.append(
                    _operation(
                        "add_parent_dependency",
                        tracking_key=tracking_key,
                        blocked_by=dependency,
                    )
                )

    for number in sorted(desired_issues):
        desired = desired_issues[number]
        current = live_issues[number]
        missing_labels = sorted(
            set(desired.get("add_labels", [])) - set(current.get("labels", []))
        )
        if missing_labels:
            plan.append(
                _operation("add_issue_labels", issue_number=number, labels=missing_labels)
            )
        milestone_id = desired.get("set_milestone")
        if milestone_id is not None and current.get("milestone_id") != milestone_id:
            plan.append(
                _operation(
                    "set_issue_milestone",
                    issue_number=number,
                    milestone_id=milestone_id,
                )
            )
        parent = desired.get("add_as_subissue_of")
        if parent is not None:
            current_parent = current.get("parent_tracking_key")
            if current_parent not in (None, parent):
                raise ProjectionError(f"issue {number} already has another parent")
            if current_parent is None:
                plan.append(
                    _operation(
                        "add_subissue",
                        issue_number=number,
                        parent_tracking_key=parent,
                        issue_id=current["id"],
                    )
                )
    return plan


def apply_plan(
    operations: list[dict[str, Any]], client: ProjectionClient
) -> list[dict[str, Any]]:
    """Apply in order; never continue after an uncertain or failed mutation."""

    completed: list[dict[str, Any]] = []
    for operation in operations:
        try:
            result = client.execute(deepcopy(operation))
        except Exception as exc:
            raise ProjectionApplyError(
                f"projection stopped at {operation['op']}: {exc}", completed
            ) from exc
        completed.append({"operation": deepcopy(operation), "result": result})
    return completed
