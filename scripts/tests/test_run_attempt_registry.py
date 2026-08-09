#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Focused authority regressions for issue #1497 carrier A."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import run_attempt_registry as registry  # noqa: E402


def _valid_row(tmp_path: Path) -> dict:
    return registry.build_row(
        run_root=tmp_path / "run-A",
        outcome="failed",
        run_id="run-A",
        attempt_id="attempt-1",
        start_utc="2026-08-08T00:00:00Z",
        end_utc="2026-08-08T00:01:00Z",
        checkpoint_manifest_sha256=None,
        launch_receipt_ref="receipts/launch.json",
        source_receipt="receipts/launch.json",
        outcome_basis="child exit 1",
        backfill=False,
    )


def test_row_schema_rejects_unknown_fields_and_missing_launch_receipt(tmp_path: Path):
    row = _valid_row(tmp_path)
    assert registry.validate_row(row) == []

    extra = dict(row, foreign_claim="accepted")
    assert any("unknown fields" in defect for defect in registry.validate_row(extra))

    missing = dict(row, launch_receipt_ref=None)
    assert any("launch_receipt_ref" in defect for defect in registry.validate_row(missing))


def test_existing_invalid_row_refuses_before_append(tmp_path: Path):
    path = tmp_path / "receipts" / "run-attempts.jsonl"
    path.parent.mkdir(parents=True)
    invalid = dict(_valid_row(tmp_path), foreign_claim="accepted")
    original = json.dumps(invalid, sort_keys=True).encode("utf-8") + b"\n"
    path.write_bytes(original)

    args = argparse.Namespace(
        registry=str(path),
        run_root=str(tmp_path / "run-B"),
        outcome="running",
        run_id="run-B",
        attempt_id="attempt-1",
        start_utc="2026-08-08T00:02:00Z",
        end_utc=None,
        checkpoint_manifest_sha=None,
        launch_receipt_ref="receipts/launch.json",
        source_receipt="receipts/launch.json",
        outcome_basis="spawn",
    )
    assert registry.cmd_append(args) != 0
    assert path.read_bytes() == original


def test_run_root_ref_must_bind_exact_root_name(tmp_path: Path):
    row = _valid_row(tmp_path)
    row["run_root_ref"] = "custody:some-other-run"
    assert any("run_root_ref" in defect for defect in registry.validate_row(row))


def test_duplicate_attempt_identity_refuses_before_append(tmp_path: Path):
    path = tmp_path / "receipts" / "run-attempts.jsonl"
    row = _valid_row(tmp_path)

    assert registry.append_rows(path, [row]) == []
    original = path.read_bytes()

    defects = registry.append_rows(path, [dict(row)])
    assert any("duplicate attempt identity" in defect for defect in defects)
    assert path.read_bytes() == original

    within_call = tmp_path / "receipts" / "same-call.jsonl"
    defects = registry.append_rows(within_call, [row, dict(row)])
    assert any("duplicate attempt identity" in defect for defect in defects)
    assert not within_call.exists()


def test_preexisting_duplicate_attempt_identity_refuses_cmd_append(tmp_path: Path):
    path = tmp_path / "receipts" / "run-attempts.jsonl"
    path.parent.mkdir(parents=True)
    row = _valid_row(tmp_path)
    line = json.dumps(row, sort_keys=True).encode("utf-8") + b"\n"
    original = line + line
    path.write_bytes(original)

    args = argparse.Namespace(
        registry=str(path),
        run_root=str(tmp_path / "run-B"),
        outcome="running",
        run_id="run-B",
        attempt_id="attempt-1",
        start_utc="2026-08-08T00:02:00Z",
        end_utc=None,
        checkpoint_manifest_sha=None,
        launch_receipt_ref="receipts/launch.json",
        source_receipt="receipts/launch.json",
        outcome_basis="spawn",
    )
    assert registry.cmd_append(args) != 0
    assert path.read_bytes() == original
