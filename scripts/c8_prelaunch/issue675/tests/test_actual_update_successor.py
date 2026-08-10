# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import torch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import q2_actual_update_successor as q2  # noqa: E402


IDENTITY = {
    "source_sha256": "1" * 64,
    "config_sha256": "2" * 64,
    "batch_sha256": "3" * 64,
    "optimizer_sha256": "4" * 64,
    "replay_sha256": "5" * 64,
    "momentum_sha256": "6" * 64,
    "learning_rate": 0.01,
    "optimizer_scale": 1.0,
    "optimizer_name": "synthetic-sgd",
    "capture_receipt_sha256": "7" * 64,
    "event_authority": "FUTURE_CAPTURED_GPU_EVENT",
}


def _loss(state: dict[str, torch.Tensor]) -> float:
    return float(sum((value.float() ** 2).sum() for value in state.values()))


def _threshold(mn: int) -> dict[str, object]:
    return q2.build_threshold_artifact(mn=mn, alpha=0.003)


def test_target_counterfactual_binds_actual_deltas_and_non_target_manifest():
    pre = {"target": torch.tensor([1.0, 0.0]), "other": torch.tensor([7.0])}
    reset = {"target": torch.tensor([0.8, 0.0]), "other": torch.tensor([7.0])}
    transplant = {"target": torch.tensor([0.5, 0.2]), "other": torch.tensor([7.0])}
    receipt = q2.evaluate_actual_update(
        pre_state=pre,
        reset_state=reset,
        transplant_state=transplant,
        gradients={"target": torch.tensor([1.0, -1.0])},
        scope=q2.TARGET_TENSOR_COUNTERFACTUAL,
        target_tensor="target",
        identities=IDENTITY,
        loss_fn=_loss,
        threshold_artifact=_threshold(2),
        event_captured_at="2026-08-09T22:00:00Z",
    )
    assert receipt["scope"] == q2.TARGET_TENSOR_COUNTERFACTUAL
    assert receipt["actual_gpu_applied_deltas"]["derivation"] == "post_state - exact_pre_state"
    assert receipt["non_target_manifest"]["names"] == ["other"]
    assert receipt["losses"]["direct_gap_sign"] == "TRANSPLANT_LOWER"
    assert receipt["credits"]["whole_step"] is False
    assert receipt["credits"]["material_loss_bridge"] is False
    assert receipt["no_new_parallel_authority"] is True


def test_target_counterfactual_refuses_non_target_drift_and_whole_step_claim():
    pre = {"target": torch.tensor([1.0]), "other": torch.tensor([7.0])}
    reset = {"target": torch.tensor([0.5]), "other": torch.tensor([7.0])}
    transplant = {"target": torch.tensor([0.25]), "other": torch.tensor([8.0])}
    with pytest.raises(q2.Refusal, match="NON_TARGET_BYTES_CHANGED"):
        q2.evaluate_actual_update(
            pre_state=pre, reset_state=reset, transplant_state=transplant,
            gradients={"target": torch.tensor([1.0])},
            scope=q2.TARGET_TENSOR_COUNTERFACTUAL, target_tensor="target",
            identities=IDENTITY, loss_fn=_loss, threshold_artifact=_threshold(1),
            event_captured_at="2026-08-09T22:00:00Z",
        )
    transplant["other"] = pre["other"].clone()
    with pytest.raises(q2.Refusal, match="TARGET_RECEIPT_CANNOT_CLAIM_WHOLE_STEP"):
        q2.evaluate_actual_update(
            pre_state=pre, reset_state=reset, transplant_state=transplant,
            gradients={"target": torch.tensor([1.0])},
            scope=q2.TARGET_TENSOR_COUNTERFACTUAL, target_tensor="target",
            requested_claim_scope=q2.WHOLE_STEP,
            identities=IDENTITY, loss_fn=_loss, threshold_artifact=_threshold(1),
            event_captured_at="2026-08-09T22:00:00Z",
        )


def test_whole_step_uses_full_manifest_and_catches_opposite_sign_interference():
    # target-only: <G,D> is negative; full-state: the second tensor reverses it.
    pre = {"target": torch.tensor([0.0]), "interferer": torch.tensor([0.0])}
    reset = {"target": torch.tensor([1.0]), "interferer": torch.tensor([0.0])}
    transplant = {"target": torch.tensor([0.0]), "interferer": torch.tensor([2.0])}
    gradients = {"target": torch.tensor([1.0]), "interferer": torch.tensor([2.0])}
    receipt = q2.evaluate_actual_update(
        pre_state=pre, reset_state=reset, transplant_state=transplant,
        gradients=gradients, scope=q2.WHOLE_STEP, target_tensor=None,
        identities=IDENTITY, loss_fn=_loss, threshold_artifact=_threshold(2),
        event_captured_at="2026-08-09T22:00:00Z",
    )
    assert receipt["tensor_manifest"]["names"] == ["interferer", "target"]
    assert receipt["losses"]["first_order_gap"] > 0
    assert float(torch.dot(gradients["target"], transplant["target"] - reset["target"])) < 0
    assert receipt["credits"]["whole_step"] is True


def test_whole_step_refuses_incomplete_gradient_manifest_before_loss_evaluation():
    calls = 0

    def counting_loss(state: dict[str, torch.Tensor]) -> float:
        nonlocal calls
        calls += 1
        return _loss(state)

    state = {"a": torch.tensor([0.0]), "b": torch.tensor([0.0])}
    with pytest.raises(q2.Refusal, match="GRADIENT_MANIFEST_MISMATCH"):
        q2.evaluate_actual_update(
            pre_state=state, reset_state={"a": torch.tensor([1.0]), "b": torch.tensor([0.0])},
            transplant_state={"a": torch.tensor([0.0]), "b": torch.tensor([1.0])},
            gradients={"a": torch.tensor([1.0])}, scope=q2.WHOLE_STEP,
            target_tensor=None, identities=IDENTITY, loss_fn=counting_loss,
            threshold_artifact=_threshold(2), event_captured_at="2026-08-09T22:00:00Z",
        )
    assert calls == 0


def test_threshold_is_separate_pre_event_and_contains_no_observed_statistic():
    threshold = _threshold(8)
    encoded = json.dumps(threshold, sort_keys=True)
    assert threshold["p_upper_formula"] == "min(1, 1/(mn*rho_perp^2))"
    assert "rho_perp\":" not in encoded
    assert "observed_tensor" not in encoded
    assert "observed_loss" not in encoded
    assert q2.artifact_sha256(threshold) == threshold["artifact_sha256"]


def test_material_bridge_requires_pre_event_delta_min_and_dominant_remainder():
    pre = {"w": torch.tensor([1.0, 2.0])}
    reset = {"w": torch.tensor([0.8, 1.8])}
    transplant = {"w": torch.tensor([0.5, 1.5])}
    common = dict(
        pre_state=pre, reset_state=reset, transplant_state=transplant,
        gradients={"w": torch.tensor([2.0, 4.0])}, scope=q2.WHOLE_STEP,
        target_tensor=None, identities=IDENTITY, loss_fn=_loss,
        threshold_artifact=_threshold(2), event_captured_at="2026-08-09T22:00:00Z",
    )
    no_floor = q2.evaluate_actual_update(**common)
    assert no_floor["bridge_verdict"] != "MATERIAL_LOSS_BRIDGE"
    assert no_floor["credits"]["material_loss_bridge"] is False
    floor = q2.build_materiality_artifact(
        delta_min=0.1, frozen_at="2026-08-09T21:00:00Z", source_sha256="6" * 64)
    with_floor = q2.evaluate_actual_update(**common, materiality_artifact=floor)
    assert with_floor["bridge_verdict"] == "MATERIAL_LOSS_BRIDGE"


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_refuses_nonfinite_state_before_loss(bad: float):
    with pytest.raises(q2.Refusal, match="INVALID_TENSOR"):
        q2.evaluate_actual_update(
            pre_state={"w": torch.tensor([bad])}, reset_state={"w": torch.tensor([0.0])},
            transplant_state={"w": torch.tensor([1.0])}, gradients={"w": torch.tensor([1.0])},
            scope=q2.WHOLE_STEP, target_tensor=None, identities=IDENTITY,
            loss_fn=_loss, threshold_artifact=_threshold(1),
            event_captured_at="2026-08-09T22:00:00Z",
        )


def test_receipt_is_path_free_and_self_hashing():
    receipt = q2.evaluate_actual_update(
        pre_state={"w": torch.tensor([1.0, 0.0])},
        reset_state={"w": torch.tensor([0.5, 0.0])},
        transplant_state={"w": torch.tensor([0.0, 0.5])},
        gradients={"w": torch.tensor([1.0, 0.0])}, scope=q2.WHOLE_STEP,
        target_tensor=None, identities=IDENTITY, loss_fn=_loss,
        threshold_artifact=_threshold(2), event_captured_at="2026-08-09T22:00:00Z",
    )
    encoded = json.dumps(receipt, sort_keys=True)
    assert ":\\" not in encoded and "B:/" not in encoded
    assert q2.artifact_sha256(receipt) == receipt["receipt_sha256"]


def test_public_boundary_emits_path_free_failed_engagement_without_credit():
    receipt = q2.evaluate_or_refuse(
        pre_state={"w": torch.tensor([1.0])}, reset_state={"w": torch.tensor([1.0])},
        transplant_state={"w": torch.tensor([1.0])}, gradients={"w": torch.tensor([1.0])},
        scope=q2.WHOLE_STEP, target_tensor=None, identities=IDENTITY,
        loss_fn=_loss, threshold_artifact=_threshold(1),
        event_captured_at="2026-08-09T22:00:00Z",
    )
    assert receipt["verdict"] == "FAILED_ENGAGEMENT"
    assert receipt["refusal_code"] == "ZERO_UPDATE_DIFFERENCE"
    assert not any(receipt["credits"].values())
    assert q2.artifact_sha256(receipt) == receipt["receipt_sha256"]
    assert ":\\" not in json.dumps(receipt, sort_keys=True)


def test_closed_schemas_refuse_unknown_identity_threshold_and_path_name():
    common = dict(
        pre_state={"w": torch.tensor([0.0])}, reset_state={"w": torch.tensor([1.0])},
        transplant_state={"w": torch.tensor([2.0])}, gradients={"w": torch.tensor([1.0])},
        scope=q2.WHOLE_STEP, target_tensor=None, loss_fn=_loss,
        threshold_artifact=_threshold(1), event_captured_at="2026-08-09T22:00:00Z",
    )
    with pytest.raises(q2.Refusal, match="IDENTITY_SCHEMA_MISMATCH"):
        q2.evaluate_actual_update(**common, identities={**IDENTITY, "foreign": "x"})
    with pytest.raises(q2.Refusal, match="HISTORICAL_OR_RECONSTRUCTED_EVENT_FORBIDDEN"):
        q2.evaluate_actual_update(
            **common, identities={**IDENTITY, "event_authority": "HISTORICAL_SIBLING"})
    tampered = _threshold(1)
    tampered["alpha"] = 0.05
    with pytest.raises(q2.Refusal, match="THRESHOLD_ARTIFACT_MISMATCH"):
        q2.evaluate_actual_update(**{**common, "threshold_artifact": tampered}, identities=IDENTITY)
    with pytest.raises(q2.Refusal, match="INVALID_TENSOR_NAME"):
        q2.evaluate_actual_update(
            **{**common, "pre_state": {"B:/host/path": torch.tensor([0.0])},
               "reset_state": {"B:/host/path": torch.tensor([1.0])},
               "transplant_state": {"B:/host/path": torch.tensor([2.0])},
               "gradients": {"B:/host/path": torch.tensor([1.0])}}, identities=IDENTITY)
