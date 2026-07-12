# goal_id: EMBER-00
# next_executed_outcome: EMBER-01 clean 3B custody and identity spine
from __future__ import annotations

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from check_pr_authority_binding import validate_pr_body  # noqa: E402


GOAL = "EMBER-00"
OUTCOME = "EMBER-01 clean 3B custody and identity spine"


def test_exact_binding_passes() -> None:
    body = f"goal_id: {GOAL}\nnext_executed_outcome: {OUTCOME}\n"
    assert validate_pr_body(body, GOAL, OUTCOME) == []


def test_missing_or_duplicate_fields_fail() -> None:
    assert "goal_id must appear exactly once" in validate_pr_body(
        f"next_executed_outcome: {OUTCOME}\n", GOAL, OUTCOME
    )
    duplicate = (
        f"goal_id: {GOAL}\ngoal_id: {GOAL}\n"
        f"next_executed_outcome: {OUTCOME}\n"
    )
    assert "goal_id must appear exactly once" in validate_pr_body(
        duplicate, GOAL, OUTCOME
    )


def test_wrong_goal_or_outcome_fails() -> None:
    body = f"goal_id: EMBER-01\nnext_executed_outcome: {OUTCOME}\n"
    assert "goal_id does not match GOAL.md" in validate_pr_body(body, GOAL, OUTCOME)
    body = f"goal_id: {GOAL}\nnext_executed_outcome: TBD\n"
    assert "next_executed_outcome does not match GOAL.md" in validate_pr_body(
        body, GOAL, OUTCOME
    )
