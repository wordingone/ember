#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Issue #158: trigger-gated native-engine floor row and board cadence."""

from __future__ import annotations

import ast
import copy
import hashlib
import unittest
from pathlib import Path

import pytest

from scripts.ember_phase3_c14 import floor_contract_manifest as floor


REPO_ROOT = Path(__file__).resolve().parents[2]
ROW_KEY = "floor_contract.ember-native-engine"


def _manifest():
    return floor.build_manifest(REPO_ROOT)


def test_native_engine_is_a_hashed_trigger_gated_floor_row():
    manifest = _manifest()
    row = manifest[ROW_KEY]
    source = REPO_ROOT / row["source_file"]

    assert row["disposition"] == floor.PRESERVED_TRIGGER_GATED
    assert row["source_file"] == "docs/spec/ember-native-engine-trigger-ladder-v1.md"
    assert source.is_file()
    assert row["source_hash"] == hashlib.sha256(source.read_bytes()).hexdigest()

    combined = " ".join(
        str(row[field])
        for field in (
            "launch_vehicle_impact",
            "trigger",
            "pilot",
            "kill_promote_condition",
            "evidence_path",
        )
    )
    for token in ("T1", "T2", "T3", "T4", "R0", "R1", "R2", "R3"):
        assert token in combined
    assert "#155" in combined
    assert "FP8" in combined
    assert "Muon" in combined


def test_native_engine_board_review_is_closed_and_carries_t2_t3_every_run():
    review = floor.build_native_engine_board_review(_manifest())

    assert review == {
        "floor_row_key": ROW_KEY,
        "disposition": floor.PRESERVED_TRIGGER_GATED,
        "source_file": "docs/spec/ember-native-engine-trigger-ladder-v1.md",
        "source_sha256": _manifest()[ROW_KEY]["source_hash"],
        "issue": 158,
        "coupled_issue": 155,
        "reviewed_triggers": [
            {
                "trigger_id": "T2",
                "status": "PARTIALLY_FIRED",
                "required_rung": "R0",
            },
            {
                "trigger_id": "T3",
                "status": "ON_BLOCKER_PATH",
                "required_rung": "R1",
            },
        ],
        "claim_boundary": "TRIGGER_REVIEW_ONLY_NO_NATIVE_ENGINE_CAPABILITY_CLAIM",
    }

    board_source = (
        REPO_ROOT / "src" / "ember" / "governance" / "scripts" / "ember_totality" / "ember_totality_spec.py"
    ).read_text(encoding="utf-8")
    ast.parse(board_source)
    assert '"native_engine_trigger_review"' in board_source
    assert "build_native_engine_board_review" in board_source
    assert board_source.count('"native_engine_trigger_review"') == 1


@pytest.mark.parametrize(
    "field,replacement,error_token",
    [
        ("disposition", floor.USED_NOW, "preserved_trigger_gated"),
        ("trigger", "T1 and T3 and T4 only", "T2"),
        ("trigger", "T1 and T2 and T4 only", "T3"),
        ("pilot", "uncoupled pilot", "#155"),
    ],
)
def test_native_engine_row_fails_closed_when_authority_is_weakened(
    field: str, replacement: str, error_token: str
):
    manifest = copy.deepcopy(_manifest())
    manifest[ROW_KEY][field] = replacement
    errors = floor.validate_manifest(manifest)
    assert errors
    assert any(error_token in error for error in errors)


class NativeEngineTriggerTests(unittest.TestCase):
    def test_floor_row(self):
        test_native_engine_is_a_hashed_trigger_gated_floor_row()

    def test_board_review(self):
        test_native_engine_board_review_is_closed_and_carries_t2_t3_every_run()

    def test_weakened_rows_fail_closed(self):
        cases = [
            ("disposition", floor.USED_NOW, "preserved_trigger_gated"),
            ("trigger", "T1 and T3 and T4 only", "T2"),
            ("trigger", "T1 and T2 and T4 only", "T3"),
            ("pilot", "uncoupled pilot", "#155"),
        ]
        for case in cases:
            with self.subTest(case=case):
                test_native_engine_row_fails_closed_when_authority_is_weakened(
                    *case
                )


if __name__ == "__main__":
    unittest.main()
