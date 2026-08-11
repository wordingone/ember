#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Fail closed unless a pull request binds the exact active Ember goal."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Sequence

if __package__:
    from .verify_authority_conservation import authority_path
else:
    from verify_authority_conservation import authority_path


POLICY_RE = re.compile(
    r"<!--\s*EMBER_AUTHORITY_V1\s*\r?\n(.*?)\r?\n-->", re.DOTALL
)
GOAL_LINE_RE = re.compile(r"(?m)^goal_id:\s*(\S.*?)\s*$")
OUTCOME_LINE_RE = re.compile(r"(?m)^next_executed_outcome:\s*(\S.*?)\s*$")
WORKSTREAM_LINE_RE = re.compile(r"(?m)^workstream_id:\s*(\S.*?)\s*$")


def load_goal_binding(root: Path) -> tuple[str, str, tuple[str, ...]]:
    text = authority_path(root, "GOAL.md").read_text(encoding="utf-8")
    match = POLICY_RE.search(text)
    if not match:
        raise ValueError("docs/authority/GOAL.md EMBER_AUTHORITY_V1 block missing")
    policy = json.loads(match.group(1))
    goal = policy.get("active_goal_id")
    outcome = policy.get("next_executed_outcome")
    workstreams = policy.get("active_workstream_ids")
    if not isinstance(goal, str) or not goal:
        raise ValueError("docs/authority/GOAL.md active_goal_id missing")
    if not isinstance(outcome, str) or not outcome:
        raise ValueError("docs/authority/GOAL.md next_executed_outcome missing")
    if (
        not isinstance(workstreams, list)
        or not workstreams
        or not all(isinstance(item, str) and item for item in workstreams)
        or len(set(workstreams)) != len(workstreams)
    ):
        raise ValueError("docs/authority/GOAL.md active_workstream_ids invalid")
    return goal, outcome, tuple(workstreams)


def validate_pr_body(
    body: str,
    active_goal: str,
    expected_outcome: str,
    allowed_workstreams: Sequence[str] = (),
) -> list[str]:
    errors: list[str] = []
    goals = GOAL_LINE_RE.findall(body or "")
    outcomes = OUTCOME_LINE_RE.findall(body or "")
    workstreams = WORKSTREAM_LINE_RE.findall(body or "")
    if len(goals) != 1:
        errors.append("goal_id must appear exactly once")
    elif goals[0] != active_goal:
        errors.append("goal_id does not match docs/authority/GOAL.md")
    if len(outcomes) != 1:
        errors.append("next_executed_outcome must appear exactly once")
    elif outcomes[0] != expected_outcome:
        errors.append("next_executed_outcome does not match docs/authority/GOAL.md")
    if len(workstreams) != 1:
        errors.append("workstream_id must appear exactly once")
    elif workstreams[0] not in set(allowed_workstreams):
        errors.append("workstream_id is not allowed by docs/authority/GOAL.md")
    return errors


def validate_changed_workstreams(
    artifact_workstreams: dict[str, set[str]],
    expected_workstream: str,
) -> list[str]:
    errors: list[str] = []
    for path, workstreams in sorted(artifact_workstreams.items()):
        if workstreams != {expected_workstream}:
            actual = ",".join(sorted(workstreams)) or "<missing>"
            errors.append(
                f"{path} is bound to {actual}, not PR workstream {expected_workstream}"
            )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
    parser.add_argument("--body-file")
    parser.add_argument("--body-env", default="PR_BODY")
    parser.add_argument("--changed-range")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    try:
        active_goal, expected_outcome, allowed_workstreams = load_goal_binding(root)
        if args.body_file:
            body = Path(args.body_file).read_text(encoding="utf-8")
        else:
            body = os.environ.get(args.body_env, "")
    except Exception as exc:
        print(f"PR_AUTHORITY_BINDING FAIL: {exc}")
        return 1
    errors = validate_pr_body(
        body, active_goal, expected_outcome, allowed_workstreams
    )
    declared_workstreams = WORKSTREAM_LINE_RE.findall(body or "")
    if args.changed_range and len(declared_workstreams) == 1:
        from verify_authority_conservation import (
            check_changed_artifact_bindings,
            parse_goal_policy,
        )

        policy_errors: list[dict[str, object]] = []
        policy = parse_goal_policy(root, policy_errors)
        binding_errors: list[dict[str, object]] = []
        check_changed_artifact_bindings(
            root,
            policy,
            binding_errors,
            changed_range=args.changed_range,
            expected_workstream=declared_workstreams[0],
        )
        errors.extend(
            f"{item.get('code')}: {item.get('detail')}"
            for item in [*policy_errors, *binding_errors]
        )
    if errors:
        print("PR_AUTHORITY_BINDING FAIL: " + "; ".join(errors))
        return 1
    print(
        "PR_AUTHORITY_BINDING PASS: "
        f"goal_id={active_goal}; next_executed_outcome={expected_outcome}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
