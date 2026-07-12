#!/usr/bin/env python3
# goal_id: EMBER-00
# next_executed_outcome: EMBER-01 clean 3B custody and identity spine
"""Fail closed unless a pull request binds the exact active Ember goal."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path


POLICY_RE = re.compile(
    r"<!--\s*EMBER_AUTHORITY_V1\s*\r?\n(.*?)\r?\n-->", re.DOTALL
)
GOAL_LINE_RE = re.compile(r"(?m)^goal_id:\s*(\S.*?)\s*$")
OUTCOME_LINE_RE = re.compile(r"(?m)^next_executed_outcome:\s*(\S.*?)\s*$")


def load_goal_binding(root: Path) -> tuple[str, str]:
    text = (root / "GOAL.md").read_text(encoding="utf-8")
    match = POLICY_RE.search(text)
    if not match:
        raise ValueError("GOAL.md EMBER_AUTHORITY_V1 block missing")
    policy = json.loads(match.group(1))
    goal = policy.get("active_goal_id")
    outcome = policy.get("next_executed_outcome")
    if not isinstance(goal, str) or not goal:
        raise ValueError("GOAL.md active_goal_id missing")
    if not isinstance(outcome, str) or not outcome:
        raise ValueError("GOAL.md next_executed_outcome missing")
    return goal, outcome


def validate_pr_body(body: str, active_goal: str, expected_outcome: str) -> list[str]:
    errors: list[str] = []
    goals = GOAL_LINE_RE.findall(body or "")
    outcomes = OUTCOME_LINE_RE.findall(body or "")
    if len(goals) != 1:
        errors.append("goal_id must appear exactly once")
    elif goals[0] != active_goal:
        errors.append("goal_id does not match GOAL.md")
    if len(outcomes) != 1:
        errors.append("next_executed_outcome must appear exactly once")
    elif outcomes[0] != expected_outcome:
        errors.append("next_executed_outcome does not match GOAL.md")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
    parser.add_argument("--body-file")
    parser.add_argument("--body-env", default="PR_BODY")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    try:
        active_goal, expected_outcome = load_goal_binding(root)
        if args.body_file:
            body = Path(args.body_file).read_text(encoding="utf-8")
        else:
            body = os.environ.get(args.body_env, "")
    except Exception as exc:
        print(f"PR_AUTHORITY_BINDING FAIL: {exc}")
        return 1
    errors = validate_pr_body(body, active_goal, expected_outcome)
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
