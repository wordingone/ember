# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from check_pr_authority_binding import (  # noqa: E402
    validate_changed_workstreams,
    validate_pr_body,
)


GOAL = "EMBER-01"
OUTCOME = "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember"
WORKSTREAMS = ("EMBER-01A", "EMBER-01B", "EMBER-01C")


def test_imports_as_scripts_namespace_package() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, "-B", "-c", "import scripts.check_pr_authority_binding"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        shell=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_exact_binding_passes() -> None:
    body = (
        f"goal_id: {GOAL}\n"
        "workstream_id: EMBER-01A\n"
        f"next_executed_outcome: {OUTCOME}\n"
    )
    assert validate_pr_body(body, GOAL, OUTCOME, WORKSTREAMS) == []


def test_goal_binding_loads_exact_active_workstreams(tmp_path: Path) -> None:
    from check_pr_authority_binding import load_goal_binding

    (tmp_path / "GOAL.md").write_text(
        "<!-- EMBER_AUTHORITY_V1\n"
        + json.dumps(
            {
                "active_goal_id": GOAL,
                "next_executed_outcome": OUTCOME,
                "active_workstream_ids": list(WORKSTREAMS),
            }
        )
        + "\n-->\n",
        encoding="utf-8",
    )
    assert load_goal_binding(tmp_path) == (GOAL, OUTCOME, WORKSTREAMS)


def test_goal_binding_accepts_migrated_authority_path(tmp_path: Path) -> None:
    from check_pr_authority_binding import load_goal_binding

    authority = tmp_path / "docs" / "authority"
    authority.mkdir(parents=True)
    (authority / "GOAL.md").write_text(
        "<!-- EMBER_AUTHORITY_V1\n"
        + json.dumps(
            {
                "active_goal_id": GOAL,
                "next_executed_outcome": OUTCOME,
                "active_workstream_ids": list(WORKSTREAMS),
            }
        )
        + "\n-->\n",
        encoding="utf-8",
    )

    assert load_goal_binding(tmp_path) == (GOAL, OUTCOME, WORKSTREAMS)


def test_goal_binding_accepts_domain_authority_path(tmp_path: Path) -> None:
    from check_pr_authority_binding import load_goal_binding

    authority = tmp_path / "docs" / "domains" / "governance" / "authority"
    authority.mkdir(parents=True)
    (authority / "GOAL.md").write_text(
        "<!-- EMBER_AUTHORITY_V1\n"
        + json.dumps(
            {
                "active_goal_id": GOAL,
                "next_executed_outcome": OUTCOME,
                "active_workstream_ids": list(WORKSTREAMS),
            }
        )
        + "\n-->\n",
        encoding="utf-8",
    )

    assert load_goal_binding(tmp_path) == (GOAL, OUTCOME, WORKSTREAMS)


def test_goal_binding_rejects_both_migrated_authority_paths(tmp_path: Path) -> None:
    from check_pr_authority_binding import load_goal_binding

    legacy = tmp_path / "docs" / "authority"
    domain = tmp_path / "docs" / "domains" / "governance" / "authority"
    legacy.mkdir(parents=True)
    domain.mkdir(parents=True)
    payload = (
        "<!-- EMBER_AUTHORITY_V1\n"
        + json.dumps(
            {
                "active_goal_id": GOAL,
                "next_executed_outcome": OUTCOME,
                "active_workstream_ids": list(WORKSTREAMS),
            }
        )
        + "\n-->\n"
    )
    (legacy / "GOAL.md").write_text(payload, encoding="utf-8")
    (domain / "GOAL.md").write_text(payload, encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate canonical authority document"):
        load_goal_binding(tmp_path)


def test_goal_binding_rejects_duplicate_authority_paths(tmp_path: Path) -> None:
    from check_pr_authority_binding import load_goal_binding

    authority = tmp_path / "docs" / "authority"
    authority.mkdir(parents=True)
    payload = (
        "<!-- EMBER_AUTHORITY_V1\n"
        + json.dumps(
            {
                "active_goal_id": GOAL,
                "next_executed_outcome": OUTCOME,
                "active_workstream_ids": list(WORKSTREAMS),
            }
        )
        + "\n-->\n"
    )
    (tmp_path / "GOAL.md").write_text(payload, encoding="utf-8")
    (authority / "GOAL.md").write_text(payload, encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate canonical authority document"):
        load_goal_binding(tmp_path)


def test_missing_or_duplicate_fields_fail() -> None:
    assert "workstream_id must appear exactly once" in validate_pr_body(
        f"goal_id: {GOAL}\nnext_executed_outcome: {OUTCOME}\n",
        GOAL,
        OUTCOME,
        WORKSTREAMS,
    )
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
    body = f"goal_id: EMBER-00\nnext_executed_outcome: {OUTCOME}\n"
    assert "goal_id does not match canonical GOAL.md" in validate_pr_body(body, GOAL, OUTCOME)
    body = f"goal_id: {GOAL}\nnext_executed_outcome: TBD\n"
    assert "next_executed_outcome does not match canonical GOAL.md" in validate_pr_body(
        body, GOAL, OUTCOME
    )


def test_allowed_child_workstream_passes_without_becoming_parent_goal() -> None:
    body = (
        f"goal_id: {GOAL}\n"
        "workstream_id: EMBER-01B\n"
        f"next_executed_outcome: {OUTCOME}\n"
    )
    assert validate_pr_body(body, GOAL, OUTCOME, WORKSTREAMS) == []


def test_unknown_or_duplicate_child_workstream_fails() -> None:
    unknown = (
        f"goal_id: {GOAL}\n"
        "workstream_id: EMBER-99Z\n"
        f"next_executed_outcome: {OUTCOME}\n"
    )
    assert "workstream_id is not allowed by canonical GOAL.md" in validate_pr_body(
        unknown, GOAL, OUTCOME, WORKSTREAMS
    )
    duplicate = (
        f"goal_id: {GOAL}\n"
        "workstream_id: EMBER-01B\n"
        "workstream_id: EMBER-01C\n"
        f"next_executed_outcome: {OUTCOME}\n"
    )
    assert "workstream_id must appear exactly once" in validate_pr_body(
        duplicate, GOAL, OUTCOME, WORKSTREAMS
    )


def test_pr_workstream_must_match_every_changed_control_artifact() -> None:
    assert validate_changed_workstreams(
        {
            "scripts/ember_01_custody/hash_roots.py": {"EMBER-01B"},
            "docs/ember-01-custody/census.md": {"EMBER-01B"},
        },
        "EMBER-01B",
    ) == []
    errors = validate_changed_workstreams(
        {"scripts/verify_authority_conservation.py": {"EMBER-01A"}},
        "EMBER-01B",
    )
    assert errors == [
        "scripts/verify_authority_conservation.py is bound to EMBER-01A, not PR workstream EMBER-01B"
    ]
