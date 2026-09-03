# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Regression for the real #1413 governed-run checkpoint refusal."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "src" / "ember" / "infrastructure" / "tools" / "ember-restart-3b"))

import checkpoint_artifacts


def test_real_quarantine_projects_shared_optimizer_storage_once() -> None:
    fixture = (
        REPO_ROOT
        / "tests"
        / "fixtures"
        / "domain-governance"
        / "issue1413-checkpoint-projection-d5b0dfd84e74b42e.json"
    )
    raw = fixture.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == (
        "d5b0dfd84e74b42e43a6be42d9142d8c5a61ff483069b6f29bd3c06b3b2a9cfe"
    )
    receipt = json.loads(raw)
    operands = receipt["comparison_operands"]["projected_storage_floor_inputs"]
    assert operands["projected_optimizer_state_tensor_storage_lower_bound_bytes"] == 14_009_073_664

    corrected = checkpoint_artifacts._projected_all_expert_optimizer_storage_bytes(
        routed_optimizer=operands[
            "optimizer_state_tensor_storage_by_route_bytes"
        ],
        active_expert=operands["active_expert"],
    )

    assert corrected == 7_796_359_168
    actual_checkpoint_floor = sum(
        operands["per_shard_tensor_storage_lower_bound_bytes"].values()
    )
    corrected_checkpoint_floor = (
        actual_checkpoint_floor
        - operands["optimizer_state_tensor_storage_lower_bound_bytes"]
        + corrected
    )
    assert corrected_checkpoint_floor == 15_474_687_952
    assert corrected_checkpoint_floor <= receipt["comparison_operands"][
        "derived_byte_bound_bytes"
    ]


def test_partial_routes_use_the_largest_populated_expert_for_missing_routes() -> None:
    routed = {
        "shared": 10,
        "vision": 3,
        "audio": 5,
        "reasoning": 0,
        "tool": 0,
    }
    assert checkpoint_artifacts._projected_all_expert_optimizer_storage_bytes(
        routed_optimizer=routed,
        active_expert="audio",
    ) == 28
    assert checkpoint_artifacts._projected_all_expert_optimizer_storage_bytes(
        routed_optimizer=routed,
        active_expert="shared",
    ) == 28
    assert checkpoint_artifacts._optimizer_projection_route_multiplier(
        routed_optimizer=routed,
        active_expert="shared",
    ) == 4


def test_legacy_failure_operands_without_route_map_do_not_crash(tmp_path: Path) -> None:
    operands = checkpoint_artifacts._failure_comparison_operands_from_receipt(
        {
            "storage_projection": {
                "active_expert": "vision",
                "optimizer_state_tensor_storage_lower_bound_bytes": 10,
                "projected_all_expert_optimizer_state_tensor_storage_lower_bound_bytes": 40,
            }
        },
        tmp_path,
    )
    assert operands["projected_storage_floor_inputs"]["route_multiplier"] is None
