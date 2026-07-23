#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Focused regressions for the unified EMBER-01 completion runner."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import verify_ember01_completion as completion  # noqa: E402


def test_run_reports_missing_executable_without_aborting_receipt(
    tmp_path: Path,
) -> None:
    result = completion.run(
        ["ember-command-that-does-not-exist"],
        root=tmp_path,
        name="missing",
    )

    assert result["returncode"] is None
    assert result["timed_out"] is False
    assert result["command"] == ["ember-command-that-does-not-exist"]
    assert result["stderr"]


def test_seat_leg_invokes_resolved_bun_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seat = tmp_path / completion.SEAT_TEST_REL
    seat.parent.mkdir(parents=True)
    seat.write_text("test('seat', () => {});\n", encoding="utf-8")
    resolved_bun = str(tmp_path / "bin" / "bun.cmd")
    captured: list[str] = []

    monkeypatch.setattr(completion.shutil, "which", lambda name: resolved_bun)

    def fake_run(args: list[str], **_: object) -> dict[str, object]:
        captured.extend(args)
        return {
            "returncode": 0,
            "timed_out": False,
            "stdout": "",
            "stderr": "",
        }

    monkeypatch.setattr(completion, "run", fake_run)

    result = completion.seat_leg(tmp_path, run_seat=True)

    assert captured == [
        resolved_bun,
        "test",
        "src/entrypoints/model-seat.test.ts",
    ]
    assert result["5"]["state"] == completion.RESOLVED_TRUE
