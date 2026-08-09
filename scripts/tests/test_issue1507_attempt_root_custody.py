#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Focused CPU-only regressions for issue #1507."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import frontier_receipt  # noqa: E402
import r1_exit_battery  # noqa: E402


def test_attempt_named_run_root_is_not_excluded_below_root():
    run_root = Path("C:/attempt-20260808T2305Z")
    assert r1_exit_battery._evidence_excluded(
        run_root / "e4-measurement-receipt.json", run_root
    ) is False
    assert frontier_receipt._excluded_from_evidence(
        run_root / "e4-measurement-receipt.json", run_root
    ) is False


def test_nested_attempt_and_quarantine_are_excluded_below_root():
    run_root = Path("C:/run-root")
    assert r1_exit_battery._evidence_excluded(
        run_root / "attempt-child" / "e4-measurement-receipt.json", run_root
    ) is True
    assert frontier_receipt._excluded_from_evidence(
        run_root / ".checkpoint-quarantine" / "e4-measurement-receipt.json", run_root
    ) is True


def test_frontier_mint_refuses_non_genesis_before_writing(tmp_path: Path):
    output = tmp_path / "frontier-receipt.json"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "frontier_receipt.py"),
            "--run-root",
            str(tmp_path / "attempt-run"),
            "--predecessor",
            "docs/not-genesis.json",
            "--out",
            str(output),
        ],
        text=True,
        capture_output=True,
    )
    assert result.returncode == 2
    assert "PREDECESSOR_REFUSED" in result.stderr
    assert not output.exists()
