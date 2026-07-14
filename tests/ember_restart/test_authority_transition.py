# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Execution-authority regression tests for the owned 3B birth."""

from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _policy() -> dict:
    text = (ROOT / "GOAL.md").read_text(encoding="utf-8")
    match = re.search(
        r"<!--\s*EMBER_AUTHORITY_V1\s*\r?\n(.*?)\r?\n-->",
        text,
        re.DOTALL,
    )
    assert match is not None
    return json.loads(match.group(1))


def test_public_authority_selects_executable_ember02() -> None:
    policy = _policy()
    assert policy["active_goal_id"] == "EMBER-02"
    assert policy["allows_new_network"] is True
    assert policy["authority_only_goal"] is False
    assert policy["active_workstream_ids"] == ["EMBER-02A", "EMBER-02B", "EMBER-02C"]


def test_ember02_model_workstream_owns_3b_execution_paths() -> None:
    policy = _policy()
    scope = policy["workstream_path_scopes"]["EMBER-02B"]
    assert scope["mode"] == "only"
    prefixes = set(scope["prefixes"])
    assert {
        "configs/ember-restart-3b.json",
        "models/ember-restart-3b/",
        "tools/ember-restart-3b/",
        "receipts/ember-restart-3b/",
        "inference/ember-restart-3b/",
        "tests/ember_restart_model/",
    } <= prefixes


def test_ember02_eval_workstream_owns_all_published_evaluator_paths() -> None:
    policy = _policy()
    scope = policy["workstream_path_scopes"]["EMBER-02C"]
    assert scope["mode"] == "only"
    prefixes = set(scope["prefixes"])
    assert {
        "docs/ember-restart-sql-",
        "docs/ember-restart-structured-tools-",
        "docs/ember-restart-dynamics-",
        "scripts/ember_restart_measured_receipts",
        "tests/test_ember_restart_measured_receipts",
    } <= prefixes


def test_authority_verifier_binds_exact_ember02_goal() -> None:
    verifier = (ROOT / "scripts" / "verify_authority_conservation.py").read_text(
        encoding="utf-8"
    )
    assert 'ACTIVE_GOAL_ID = "EMBER-02"' in verifier
    assert '"goals/ember/ember-02-3b-foundation-birth/goal.md"' in verifier
