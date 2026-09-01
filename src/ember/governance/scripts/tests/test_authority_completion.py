# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import sys
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).resolve().parents[5] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import verify_ember00_completion as completion  # noqa: E402


def passing_authority() -> dict:
    return {
        "ok": True,
        "certificate_legs": {str(leg): True for leg in range(1, 8)},
        "errors": [],
    }


def test_completion_requires_every_authority_leg() -> None:
    authority = passing_authority()
    authority["certificate_legs"]["6"] = False
    assert not completion.completion_is_valid(
        authority=authority,
        checks=[{"ok": True}],
        checkout={"clean": True, "detached": True, "head_unchanged": True},
        invariant_matches=True,
        selection_integrity=True,
    )


def test_completion_rejects_any_failed_executable_check() -> None:
    assert not completion.completion_is_valid(
        authority=passing_authority(),
        checks=[{"ok": True}, {"ok": False}],
        checkout={"clean": True, "detached": True, "head_unchanged": True},
        invariant_matches=True,
        selection_integrity=True,
    )


def test_completion_requires_clean_detached_checkout() -> None:
    assert not completion.completion_is_valid(
        authority=passing_authority(),
        checks=[{"ok": True}],
        checkout={"clean": True, "detached": False, "head_unchanged": True},
        invariant_matches=True,
        selection_integrity=True,
    )
    assert not completion.completion_is_valid(
        authority=passing_authority(),
        checks=[{"ok": True}],
        checkout={"clean": False, "detached": True, "head_unchanged": True},
        invariant_matches=True,
        selection_integrity=True,
    )


def test_receipt_must_be_outside_verified_checkout(tmp_path: Path) -> None:
    root = tmp_path / "checkout"
    root.mkdir()
    with pytest.raises(ValueError, match="outside"):
        completion.validate_receipt_path(root, root / "receipt.json")
    outside = tmp_path / "receipt.json"
    assert completion.validate_receipt_path(root, outside) == outside.resolve()


def test_completion_requires_stable_selector_and_selected_goal() -> None:
    assert not completion.completion_is_valid(
        authority=passing_authority(),
        checks=[{"ok": True}],
        checkout={"clean": True, "detached": True, "head_unchanged": True},
        invariant_matches=True,
        selection_integrity=False,
    )


def test_red_board_probe_cannot_count_as_green_check() -> None:
    result = completion.require_stdout_prefix(
        {"ok": True, "returncode": 0, "stdout": "RED C-AUTHORITY: missing"},
        "GREEN C-AUTHORITY:",
    )
    assert result["ok"] is False
