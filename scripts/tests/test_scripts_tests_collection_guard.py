#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Tests for the ci-nightly scripts/tests collection guard."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts import check_scripts_tests_collection as guard


def test_parse_collection_count_requires_a_complete_summary() -> None:
    assert guard.parse_collection_count("387 tests collected") == 387
    assert guard.parse_collection_count("1 test collected") == 1
    with pytest.raises(guard.CollectionGuardError, match="count"):
        guard.parse_collection_count("INTERNALERROR during collection")


def test_validate_collection_is_fail_closed_on_nonzero_or_truncated() -> None:
    guard.validate_collection(returncode=0, output="386 tests collected", minimum=380)
    diagnostic = "ModuleNotFoundError: No module named 'torch'"
    with pytest.raises(guard.CollectionGuardError, match="collection command failed") as failure:
        guard.validate_collection(
            returncode=1,
            output=f"{'x' * 10_000}\n{diagnostic}",
            minimum=380,
        )
    assert diagnostic in str(failure.value)
    assert len(str(failure.value)) < 5_000
    with pytest.raises(guard.CollectionGuardError, match="below floor"):
        guard.validate_collection(returncode=0, output="12 tests collected", minimum=380)


def test_run_collection_uses_repo_scripts_tests_and_reports_count(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class Result:
        returncode = 0
        stdout = "386 tests collected"
        stderr = ""

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured.update(kwargs)
        return Result()

    monkeypatch.setattr(subprocess, "run", fake_run)
    report = guard.run_collection(Path("C:/repo"), minimum=380)
    assert report.collected == 386
    assert captured["command"][-2:] == ["-q", "scripts/tests"]
    assert captured["cwd"] == Path("C:/repo")
