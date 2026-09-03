#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Static fail-closed policy for GitHub Actions workflow sources."""

from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path
from typing import Any

import yaml


PINNED_ACTION = re.compile(r"^[^./][^@]*@[0-9a-f]{40}$")
WRITE_KEYS = {
    "actions",
    "attestations",
    "checks",
    "contents",
    "deployments",
    "discussions",
    "id-token",
    "issues",
    "packages",
    "pages",
    "pull-requests",
    "repository-projects",
    "security-events",
    "statuses",
}
PR_EVENTS = {"pull_request", "pull_request_target"}
# Activity types that fire on pull-request metadata alone, with no new head
# commit. Under an unconditional `cancel-in-progress: true` each one starts a
# check suite that the next event cancels before any job exists, and branch
# protection binds the required context to that empty suite (#1375).
METADATA_ONLY_PR_TYPES = {
    "edited",
    "labeled",
    "unlabeled",
    "milestoned",
    "demilestoned",
}
# Activity types GitHub subscribes a pull-request event to when `types` is omitted.
DEFAULT_PR_TYPES = frozenset({"opened", "synchronize", "reopened"})
# A workflow that validates live pull-request state must be triggered by every
# activity that can change what it reads, or its verdict is bound to a stale
# snapshot with no path back to green short of manual rerun surgery. Each entry
# maps a token appearing in a run step to the activity types its inputs move on.
# Extend this table whenever a checker starts reading a new live PR field.
LIVE_PR_INPUT_READERS: dict[str, tuple[str, frozenset[str]]] = {
    # live_pr_policy reads title, body, labels and milestone off the live PR.
    "live_pr_policy": (
        "live PR title, body, labels and milestone",
        frozenset({"edited", "labeled", "unlabeled", "milestoned", "demilestoned"}),
    ),
    # check_pr_authority_binding reads the PR body only.
    "check_pr_authority_binding": ("live PR body", frozenset({"edited"})),
}
TRUSTED_CODEQL_PR_ACTIONS = (
    "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1",
    "github/codeql-action/init@3b0bd1d116c0bde30213346b22d4f634d96a2fb0",
    "github/codeql-action/analyze@3b0bd1d116c0bde30213346b22d4f634d96a2fb0",
)
SRC_SCRIPT_BY_PATH = re.compile(
    r"\bpython(?:\s+-B)?\s+(src/[A-Za-z0-9_./-]+\.py)\b"
)
EDITABLE_INSTALL = re.compile(
    r"\bpython(?:\s+-B)?\s+-m\s+pip\s+install\b[^\n]*(?:--editable\s+\.|-e\s+\.)"
)


def _load(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8", errors="strict"))
    if not isinstance(value, dict):
        raise ValueError("workflow must be a mapping")
    # PyYAML 1.1 may parse the key "on" as True.
    if True in value and "on" not in value:
        value["on"] = value.pop(True)
    return value


def _source_imports_src_package(path: Path) -> bool:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="strict"))
    except (OSError, SyntaxError, UnicodeError):
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == "src" or module.startswith("src."):
                return True
        elif isinstance(node, ast.Import):
            if any(alias.name == "src" or alias.name.startswith("src.") for alias in node.names):
                return True
    return False


def validate_src_script_execution(root: Path, path: Path) -> list[str]:
    """Reject by-path execution whose absolute ``src.*`` imports need packaging.

    Running ``python src/.../tool.py`` puts the tool's directory, not the
    repository root, on ``sys.path``. A module invocation or an editable
    install is therefore required for tools that import the ``src`` package.
    """
    try:
        workflow = _load(path)
    except Exception:
        return []  # validate_workflow already reports the parse failure.
    jobs = workflow.get("jobs")
    if not isinstance(jobs, dict):
        return []
    errors: list[str] = []
    for job_name, job in jobs.items():
        if not isinstance(job, dict) or not isinstance(job.get("steps"), list):
            continue
        runs = [
            str(step.get("run", ""))
            for step in job["steps"]
            if isinstance(step, dict)
        ]
        if any(EDITABLE_INSTALL.search(run) for run in runs):
            continue
        for run in runs:
            for relative in SRC_SCRIPT_BY_PATH.findall(run):
                source = root / Path(relative)
                if source.is_file() and _source_imports_src_package(source):
                    errors.append(
                        f"{path.name}:{job_name}: src-importing script by path "
                        f"without editable install: {relative}; invoke it with -m"
                    )
    return errors


def _permission_writes(value: Any) -> bool:
    if value == "write-all":
        return True
    return isinstance(value, dict) and any(
        key in WRITE_KEYS and access == "write" for key, access in value.items()
    )


def _event_names(events: Any) -> set[str]:
    if isinstance(events, str):
        return {events}
    if isinstance(events, dict):
        return {str(event) for event in events}
    if isinstance(events, list):
        return {str(event) for event in events}
    return set()


def _cancels_in_progress(value: Any) -> bool:
    """True only for an unconditional cancel-in-progress.

    An expression (``${{ ... }}``) is conditional by construction: it is how a
    workflow says "cancel only when a new head supersedes this run", which is
    exactly the shape that keeps metadata-driven runs alive.
    """
    return isinstance(value, dict) and value.get("cancel-in-progress") is True


def _subscribed_pr_types(events: Any) -> dict[str, frozenset[str]]:
    """Activity types each pull-request event is subscribed to.

    An omitted ``types`` key is GitHub's default set, not "everything", so a
    workflow that never declares types still fails coverage fail-closed.
    """
    if not isinstance(events, dict):
        return {}
    subscribed: dict[str, frozenset[str]] = {}
    for event in PR_EVENTS:
        if event not in events:
            continue
        config = events.get(event)
        types = config.get("types") if isinstance(config, dict) else None
        if isinstance(types, list):
            subscribed[event] = frozenset(str(item) for item in types)
        else:
            subscribed[event] = DEFAULT_PR_TYPES
    return subscribed


def _metadata_only_pr_types(events: Any) -> dict[str, list[str]]:
    """Metadata-only activity types subscribed per pull-request event."""
    return {
        event: sorted(types & METADATA_ONLY_PR_TYPES)
        for event, types in _subscribed_pr_types(events).items()
        if types & METADATA_ONLY_PR_TYPES
    }


def _live_pr_input_readers(jobs: Any) -> dict[str, tuple[str, frozenset[str]]]:
    """Live-PR checkers invoked by any run step, keyed by reader token."""
    if not isinstance(jobs, dict):
        return {}
    found: dict[str, tuple[str, frozenset[str]]] = {}
    for job in jobs.values():
        steps = job.get("steps") if isinstance(job, dict) else None
        if not isinstance(steps, list):
            continue
        for step in steps:
            if not isinstance(step, dict):
                continue
            run = str(step.get("run", ""))
            for token, requirement in LIVE_PR_INPUT_READERS.items():
                if token in run:
                    found[token] = requirement
    return found


def _effective_permissions(workflow: dict[str, Any], job: dict[str, Any]) -> Any:
    if "permissions" in job:
        return job["permissions"]
    return workflow.get("permissions")


def _checkout_uses_pr_subject(step: dict[str, Any]) -> bool:
    action = step.get("uses")
    if not isinstance(action, str) or not action.startswith("actions/checkout@"):
        return False
    with_values = step.get("with")
    if not isinstance(with_values, dict):
        with_values = {}
    repository = str(with_values.get("repository", "")).strip()
    trusted_repositories = {
        "",
        "${{ github.repository }}",
        "wordingone/ember",
    }
    ref = str(with_values.get("ref", "")).strip()
    if not ref:
        return True
    if "pull_request.head" in ref or "/merge" in ref:
        return True
    trusted_refs = {"master", "refs/heads/master"}
    if ref in trusted_refs:
        return repository not in trusted_repositories
    trusted_ref_expressions = {
        "${{ github.event.pull_request.base.sha }}",
        "${{ github.event.repository.default_branch }}",
    }
    if ref in trusted_ref_expressions:
        return repository not in trusted_repositories
    return True


def _job_executes_checked_out_repository_code(steps: list[Any]) -> bool:
    if not any(
        isinstance(step, dict) and _checkout_uses_pr_subject(step) for step in steps
    ):
        return False
    return any(
        isinstance(step, dict)
        and (
            bool(str(step.get("run", "")).strip())
            or str(step.get("uses", "")).startswith("./")
        )
        for step in steps
    )


def _job_executes_pr_controlled_workflow_code(steps: list[Any]) -> bool:
    return any(
        isinstance(step, dict)
        and (
            bool(str(step.get("run", "")).strip())
            or str(step.get("uses", "")).startswith("./")
        )
        for step in steps
    )


def _is_trusted_codeql_pr_write_job(
    path: Path,
    workflow: dict[str, Any],
    job_name: str,
    permissions: Any,
    job: dict[str, Any],
    steps: list[Any],
) -> bool:
    if path.name != "security-codeql.yml":
        return False
    if set(workflow) != {"name", "on", "permissions", "jobs"}:
        return False
    if workflow["name"] != "security-codeql":
        return False
    if workflow["on"] != {
        "push": {"branches": ["master"]},
        "pull_request": {"branches": ["master"]},
        "schedule": [{"cron": "47 10 * * 2"}],
    }:
        return False
    if set(workflow["jobs"]) != {"codeql"} or job_name != "codeql":
        return False
    if permissions != {"contents": "read", "security-events": "write"}:
        return False
    if set(job) != {"runs-on", "timeout-minutes", "strategy", "steps"}:
        return False
    if job["runs-on"] != "ubuntu-latest" or job["timeout-minutes"] != 45:
        return False
    if job["strategy"] != {
        "fail-fast": False,
        "matrix": {"language": ["python", "javascript-typescript"]},
    }:
        return False
    expected_steps = (
        {"uses": TRUSTED_CODEQL_PR_ACTIONS[0], "with": {"persist-credentials": False}},
        {"uses": TRUSTED_CODEQL_PR_ACTIONS[1], "with": {"languages": "${{ matrix.language }}"}},
        {"uses": TRUSTED_CODEQL_PR_ACTIONS[2]},
    )
    if tuple(steps) != expected_steps:
        return False
    actions = tuple(
        str(step.get("uses", ""))
        for step in steps
        if isinstance(step, dict)
    )
    if actions != TRUSTED_CODEQL_PR_ACTIONS:
        return False
    if _job_executes_pr_controlled_workflow_code(steps):
        return False
    checkout = steps[0]
    with_values = checkout.get("with")
    if not isinstance(with_values, dict):
        return False
    return (
        with_values.get("persist-credentials") is False
        and "repository" not in with_values
        and "ref" not in with_values
    )


def validate_workflow(path: Path) -> list[str]:
    errors: list[str] = []
    try:
        workflow = _load(path)
    except Exception as exc:
        return [f"{path.name}: unreadable: {exc}"]
    for key in ("name", "on", "permissions", "jobs"):
        if key not in workflow:
            errors.append(f"{path.name}: missing top-level {key}")
    jobs = workflow.get("jobs")
    if not isinstance(jobs, dict) or not jobs:
        return errors + [f"{path.name}: jobs must be a nonempty mapping"]
    events = workflow.get("on")
    event_names = _event_names(events)
    # Coverage: a workflow that validates live pull-request state must be
    # triggered by every activity that changes what it reads. Without this a
    # body fix cannot re-run the checker that rejected the body, and the only
    # way back to green is manual rerun surgery (#1375 review receipt: PR 1404).
    subscribed = _subscribed_pr_types(events)
    if subscribed:
        covered = frozenset().union(*subscribed.values())
        for token, (inputs, required) in sorted(_live_pr_input_readers(jobs).items()):
            missing = sorted(required - covered)
            if missing:
                errors.append(
                    f"{path.name}: runs {token}, which reads {inputs}, but is not "
                    f"triggered on {missing}; those edits could never re-validate"
                )
    # No husk: covering those activities is only safe if the resulting run can
    # reach a real conclusion. An unconditional cancel-in-progress cancels the
    # run before any job exists, and branch protection binds the required
    # context to that empty suite.
    if _cancels_in_progress(workflow.get("concurrency")) or any(
        isinstance(job, dict) and _cancels_in_progress(job.get("concurrency"))
        for job in jobs.values()
    ):
        for event, offenders in sorted(_metadata_only_pr_types(events).items()):
            errors.append(
                f"{path.name}: {event} subscribes to metadata-only activity "
                f"{offenders} under unconditional cancel-in-progress; these runs "
                "are cancelled before any job exists and strand required checks"
            )
    for job_name, job in jobs.items():
        context = f"{path.name}:{job_name}"
        if not isinstance(job, dict):
            errors.append(f"{context}: job must be a mapping")
            continue
        if "timeout-minutes" not in job:
            errors.append(f"{context}: timeout-minutes is required")
        steps = job.get("steps", [])
        if not isinstance(steps, list):
            errors.append(f"{context}: steps must be a list")
            continue
        effective_permissions = _effective_permissions(workflow, job)
        job_privileged = bool(PR_EVENTS & event_names) and _permission_writes(
            effective_permissions
        )
        if (
            job_privileged
            and "pull_request" in event_names
            and not _is_trusted_codeql_pr_write_job(
                path, workflow, str(job_name), effective_permissions, job, steps
            )
        ):
            errors.append(
                f"{context}: pull_request workflow source cannot hold write authority"
            )
        if job_privileged and _job_executes_checked_out_repository_code(steps):
            errors.append(
                f"{context}: write-capable PR job executes pull-request code"
            )
        for index, step in enumerate(steps):
            if not isinstance(step, dict):
                errors.append(f"{context}:step[{index}] must be a mapping")
                continue
            action = step.get("uses")
            if isinstance(action, str) and not action.startswith("./"):
                if not PINNED_ACTION.fullmatch(action):
                    errors.append(f"{context}: unpinned action {action}")
            if job_privileged:
                ref = str(step.get("with", {}).get("ref", ""))
                if (
                    "pull_request_target" in event_names
                    and _checkout_uses_pr_subject(step)
                ):
                    errors.append(
                        f"{context}: privileged job checks out pull-request subject"
                    )
                run = str(step.get("run", ""))
                if (
                    re.search(r"\b(bun|npm|pip|pytest|cargo|python)\b", run)
                    and "trusted-kernel/scripts/github/" not in run
                    and "trusted-kernel/src/ember/governance/scripts/github/" not in run
                    and "pull_request_target" in event_names
                ):
                    errors.append(
                        f"{context}: privileged job may execute repository-authored code"
                    )
    return errors


def validate_tree(root: Path) -> dict[str, Any]:
    paths = sorted((root / ".github" / "workflows").glob("*.y*ml"))
    errors: list[str] = []
    for path in paths:
        errors.extend(validate_workflow(path))
        errors.extend(validate_src_script_execution(root, path))
    return {
        "status": "PASS" if not errors else "FAIL",
        "workflow_count": len(paths),
        "errors": errors,
        "claim_boundary": "static workflow policy; not runtime execution proof",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    result = validate_tree(args.root.resolve())
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
