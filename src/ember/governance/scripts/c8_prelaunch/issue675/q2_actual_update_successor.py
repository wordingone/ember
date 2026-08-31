#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Fail-closed Q2 actual-update successor evaluator for issue #675.

This CPU/file-only boundary evaluates already-persisted pre/post tensors.  It
does not launch training and cannot manufacture model, checkpoint, or result
credit.  Two scopes are deliberately distinct: a single target-tensor
counterfactual and a complete whole-step manifest.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from datetime import datetime
from typing import Callable, Mapping

import torch


TARGET_TENSOR_COUNTERFACTUAL = "TARGET_TENSOR_COUNTERFACTUAL"
WHOLE_STEP = "WHOLE_STEP"
ALPHA = 0.003
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_IDENTITY_KEYS = {
    "source_sha256", "config_sha256", "batch_sha256", "optimizer_sha256",
    "momentum_sha256", "b3_receipt_sha256", "replay_sha256", "learning_rate", "optimizer_scale",
    "optimizer_name", "capture_receipt_sha256", "event_authority",
}


class Refusal(ValueError):
    """A named, pre-evaluation contract refusal."""

    @property
    def code(self) -> str:
        return str(self)


def _orientation_verdict(p_upper: float) -> str:
    """Apply the frozen inclusive #675 orientation boundary."""
    return "NON_NULL_ORIENTATION" if p_upper <= ALPHA else "INCONCLUSIVE_ORIENTATION"


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("utf-8")


def artifact_sha256(artifact: Mapping[str, object]) -> str:
    payload = copy.deepcopy(dict(artifact))
    payload.pop("artifact_sha256", None)
    payload.pop("receipt_sha256", None)
    return hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def _seal(artifact: dict[str, object], field: str = "artifact_sha256") -> dict[str, object]:
    artifact[field] = artifact_sha256(artifact)
    return artifact


def build_threshold_artifact(*, mn: int, alpha: float = ALPHA) -> dict[str, object]:
    if not isinstance(mn, int) or mn <= 0 or alpha != ALPHA:
        raise Refusal("INVALID_THRESHOLD_CONTRACT")
    return _seal({
        "schema": "q2-two-sided-haar-threshold-v1",
        "mn": mn,
        "alpha": alpha,
        "p_upper_formula": "min(1, 1/(mn*rho_perp^2))",
        "observed_values_forbidden": True,
    })


def build_materiality_artifact(*, delta_min: float, frozen_at: str,
                               source_sha256: str) -> dict[str, object]:
    if not math.isfinite(delta_min) or delta_min <= 0:
        raise Refusal("INVALID_DELTA_MIN")
    _require_sha("source_sha256", source_sha256)
    _parse_ts(frozen_at)
    return _seal({
        "schema": "q2-pre-event-materiality-v1",
        "delta_min": float(delta_min),
        "frozen_at": frozen_at,
        "source_sha256": source_sha256,
    })


def _parse_ts(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise Refusal("INVALID_TIMESTAMP") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise Refusal("INVALID_TIMESTAMP")
    return parsed


def _require_sha(name: str, value: object) -> None:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise Refusal(f"INVALID_SHA256:{name}")


def _validate_identities(identities: Mapping[str, object]) -> dict[str, object]:
    if not isinstance(identities, Mapping):
        raise Refusal("IDENTITY_SCHEMA_MISMATCH")
    if set(identities) != _IDENTITY_KEYS:
        raise Refusal("IDENTITY_SCHEMA_MISMATCH")
    result = dict(identities)
    for key in ("source_sha256", "config_sha256", "batch_sha256",
                "optimizer_sha256", "momentum_sha256", "b3_receipt_sha256", "replay_sha256"):
        _require_sha(key, result[key])
    _require_sha("capture_receipt_sha256", result["capture_receipt_sha256"])
    for key in ("learning_rate", "optimizer_scale"):
        value = result[key]
        if not isinstance(value, (int, float)) or not math.isfinite(float(value)) or float(value) <= 0:
            raise Refusal(f"INVALID_EXECUTION_IDENTITY:{key}")
        result[key] = float(value)
    if not isinstance(result["optimizer_name"], str) or not result["optimizer_name"]:
        raise Refusal("INVALID_EXECUTION_IDENTITY:optimizer_name")
    if result["event_authority"] != "EMBER_LAB_TERMINAL_EXIT_ZERO":
        raise Refusal("UNADMITTED_EVENT_AUTHORITY")
    return result


def _tensor_sha(name: str, tensor: torch.Tensor) -> str:
    contiguous = tensor.detach().cpu().contiguous()
    frame = _canonical_bytes({
        "name": name,
        "dtype": str(contiguous.dtype),
        "shape": list(contiguous.shape),
    })
    raw = contiguous.view(torch.uint8).numpy().tobytes()
    return hashlib.sha256(frame + b"\0" + raw).hexdigest()


def _validate_state(label: str, state: Mapping[str, torch.Tensor]) -> dict[str, torch.Tensor]:
    if not isinstance(state, Mapping) or not state:
        raise Refusal(f"EMPTY_STATE:{label}")
    result: dict[str, torch.Tensor] = {}
    for name, tensor in state.items():
        if not isinstance(name, str) or not name or "/" in name or "\\" in name:
            raise Refusal(f"INVALID_TENSOR_NAME:{label}")
        if not isinstance(tensor, torch.Tensor) or tensor.layout != torch.strided:
            raise Refusal(f"INVALID_TENSOR:{label}:{name}")
        if tensor.numel() == 0 or not torch.isfinite(tensor).all().item():
            raise Refusal(f"INVALID_TENSOR:{label}:{name}")
        result[name] = tensor.detach().cpu().contiguous()
    return result


def _manifest(state: Mapping[str, torch.Tensor], names: list[str]) -> dict[str, object]:
    rows = [{
        "name": name,
        "shape": list(state[name].shape),
        "dtype": str(state[name].dtype),
        "sha256": _tensor_sha(name, state[name]),
    } for name in names]
    manifest = {"names": names, "rows": rows}
    manifest["sha256"] = hashlib.sha256(_canonical_bytes(manifest)).hexdigest()
    return manifest


def _same_tensor(left: torch.Tensor, right: torch.Tensor) -> bool:
    return (left.shape == right.shape and left.dtype == right.dtype
            and torch.equal(left, right))


def _flatten(state: Mapping[str, torch.Tensor], names: list[str]) -> torch.Tensor:
    return torch.cat([state[name].to(torch.float64).reshape(-1) for name in names])


def _validated_threshold(threshold: Mapping[str, object], mn: int) -> dict[str, object]:
    expected = build_threshold_artifact(mn=mn)
    if dict(threshold) != expected or artifact_sha256(threshold) != threshold.get("artifact_sha256"):
        raise Refusal("THRESHOLD_ARTIFACT_MISMATCH")
    return dict(threshold)


def _validated_materiality(materiality: Mapping[str, object] | None,
                           captured_at: str) -> dict[str, object] | None:
    if materiality is None:
        return None
    required = {"schema", "delta_min", "frozen_at", "source_sha256", "artifact_sha256"}
    if set(materiality) != required or materiality.get("schema") != "q2-pre-event-materiality-v1":
        raise Refusal("MATERIALITY_SCHEMA_MISMATCH")
    rebuilt = build_materiality_artifact(
        delta_min=float(materiality["delta_min"]), frozen_at=str(materiality["frozen_at"]),
        source_sha256=str(materiality["source_sha256"]))
    if rebuilt != dict(materiality):
        raise Refusal("MATERIALITY_ARTIFACT_MISMATCH")
    if _parse_ts(str(materiality["frozen_at"])) >= _parse_ts(captured_at):
        raise Refusal("DELTA_MIN_NOT_FROZEN_PRE_EVENT")
    return dict(materiality)


def evaluate_actual_update(
    *,
    pre_state: Mapping[str, torch.Tensor],
    reset_state: Mapping[str, torch.Tensor],
    transplant_state: Mapping[str, torch.Tensor],
    gradients: Mapping[str, torch.Tensor],
    scope: str,
    target_tensor: str | None,
    identities: Mapping[str, object],
    loss_fn: Callable[[dict[str, torch.Tensor]], float],
    threshold_artifact: Mapping[str, object],
    event_captured_at: str,
    materiality_artifact: Mapping[str, object] | None = None,
    requested_claim_scope: str | None = None,
) -> dict[str, object]:
    """Validate an actual-update event and return a path-free sealed receipt."""
    if scope not in {TARGET_TENSOR_COUNTERFACTUAL, WHOLE_STEP}:
        raise Refusal("UNKNOWN_SCOPE")
    if requested_claim_scope == WHOLE_STEP and scope == TARGET_TENSOR_COUNTERFACTUAL:
        raise Refusal("TARGET_RECEIPT_CANNOT_CLAIM_WHOLE_STEP")
    _parse_ts(event_captured_at)
    identity = _validate_identities(identities)
    pre = _validate_state("pre", pre_state)
    reset = _validate_state("reset", reset_state)
    transplant = _validate_state("transplant", transplant_state)
    grad = _validate_state("gradient", gradients)
    names = sorted(pre)
    if set(reset) != set(pre) or set(transplant) != set(pre):
        raise Refusal("STATE_MANIFEST_MISMATCH")
    for name in names:
        if reset[name].shape != pre[name].shape or transplant[name].shape != pre[name].shape:
            raise Refusal("STATE_SHAPE_MISMATCH")
        if reset[name].dtype != pre[name].dtype or transplant[name].dtype != pre[name].dtype:
            raise Refusal("STATE_DTYPE_MISMATCH")

    non_target_manifest = None
    if scope == TARGET_TENSOR_COUNTERFACTUAL:
        if target_tensor not in pre or set(grad) != {target_tensor}:
            raise Refusal("TARGET_OR_GRADIENT_MANIFEST_MISMATCH")
        math_names = [str(target_tensor)]
        non_target = [name for name in names if name != target_tensor]
        for name in non_target:
            if not (_same_tensor(pre[name], reset[name]) and
                    _same_tensor(pre[name], transplant[name])):
                raise Refusal("NON_TARGET_BYTES_CHANGED")
        non_target_manifest = _manifest(pre, non_target)
    else:
        if target_tensor is not None:
            raise Refusal("WHOLE_STEP_TARGET_FORBIDDEN")
        if set(grad) != set(pre):
            raise Refusal("GRADIENT_MANIFEST_MISMATCH")
        math_names = names

    for name in math_names:
        if grad[name].shape != pre[name].shape:
            raise Refusal("GRADIENT_SHAPE_MISMATCH")

    pre_vec = _flatten(pre, math_names)
    reset_vec = _flatten(reset, math_names)
    transplant_vec = _flatten(transplant, math_names)
    gradient_vec = _flatten(grad, math_names)
    v_reset = reset_vec - pre_vec
    v_transplant = transplant_vec - pre_vec
    difference = v_transplant - v_reset
    common = (v_transplant + v_reset) / 2.0
    if float(torch.linalg.vector_norm(difference)) == 0.0:
        raise Refusal("ZERO_UPDATE_DIFFERENCE")
    if float(torch.linalg.vector_norm(gradient_vec)) == 0.0:
        raise Refusal("ZERO_GRADIENT")
    common_norm_sq = float(torch.dot(common, common))
    if common_norm_sq == 0.0:
        d_perp = difference
    else:
        d_perp = difference - (torch.dot(difference, common) / common_norm_sq) * common
    perp_norm = float(torch.linalg.vector_norm(d_perp))
    grad_norm = float(torch.linalg.vector_norm(gradient_vec))
    rho_perp = 0.0 if perp_norm == 0.0 else float(torch.dot(gradient_vec, d_perp) / (grad_norm * perp_norm))
    mn = int(difference.numel())
    threshold = _validated_threshold(threshold_artifact, mn)
    p_upper = 1.0 if rho_perp == 0.0 else min(1.0, 1.0 / (mn * rho_perp * rho_perp))
    orientation = _orientation_verdict(p_upper)

    # All structural validation completes before either branch is evaluated.
    loss_reset = float(loss_fn({name: value.clone() for name, value in reset.items()}))
    loss_transplant = float(loss_fn({name: value.clone() for name, value in transplant.items()}))
    if not math.isfinite(loss_reset) or not math.isfinite(loss_transplant):
        raise Refusal("NONFINITE_PAIRED_LOSS")
    direct_gap = loss_transplant - loss_reset
    first_order_gap = float(torch.dot(gradient_vec, difference))
    remainder = direct_gap - first_order_gap
    same_nonzero_sign = direct_gap != 0.0 and first_order_gap != 0.0 and (
        math.copysign(1.0, direct_gap) == math.copysign(1.0, first_order_gap))
    dominant = same_nonzero_sign and abs(remainder) < abs(first_order_gap)
    materiality = _validated_materiality(materiality_artifact, event_captured_at)
    material = bool(dominant and materiality is not None
                    and abs(direct_gap) >= float(materiality["delta_min"]))
    if material:
        bridge_verdict = "MATERIAL_LOSS_BRIDGE"
    elif dominant:
        bridge_verdict = "FIRST_ORDER_DOMINANT"
    elif same_nonzero_sign:
        bridge_verdict = "SIGNED_FIRST_ORDER_DIRECTION"
    else:
        bridge_verdict = "INCONCLUSIVE_LOSS_BRIDGE"

    state_manifest = _manifest(pre, names)
    reset_manifest = _manifest(reset, names)
    transplant_manifest = _manifest(transplant, names)
    receipt: dict[str, object] = {
        "schema": "q2-actual-update-successor-receipt-v1",
        "issue": 675,
        "event_captured_at": event_captured_at,
        "scope": scope,
        "target_tensor": target_tensor,
        "tensor_manifest": state_manifest,
        "pre_state_manifest_sha256": state_manifest["sha256"],
        "reset_post_state_manifest_sha256": reset_manifest["sha256"],
        "transplant_post_state_manifest_sha256": transplant_manifest["sha256"],
        "non_target_manifest": non_target_manifest,
        "execution_identity": identity,
        "actual_gpu_applied_deltas": {
            "derivation": "post_state - exact_pre_state",
            "reset_sha256": hashlib.sha256(v_reset.numpy().tobytes()).hexdigest(),
            "transplant_sha256": hashlib.sha256(v_transplant.numpy().tobytes()).hexdigest(),
            "difference_sha256": hashlib.sha256(difference.numpy().tobytes()).hexdigest(),
            "gradient_sha256": hashlib.sha256(gradient_vec.numpy().tobytes()).hexdigest(),
            "dtype": str(difference.dtype),
            "shape": [mn],
        },
        "threshold_artifact_sha256": threshold["artifact_sha256"],
        "orientation": {
            "verdict": orientation,
            "rho_perp": rho_perp,
            "mn": mn,
            "p_upper": p_upper,
            "alpha": ALPHA,
            "raw_statistics_descriptive_only": True,
            "null_primary_forbidden": True,
        },
        "losses": {
            "reset": loss_reset,
            "transplant": loss_transplant,
            "direct_gap": direct_gap,
            "direct_gap_formula": "L_B(W+v_T)-L_B(W+v_R)",
            "direct_gap_sign": "TRANSPLANT_LOWER" if direct_gap < 0 else (
                "TRANSPLANT_HIGHER" if direct_gap > 0 else "TIED"),
            "first_order_gap": first_order_gap,
            "first_order_gap_formula": "<G,v_T-v_R>",
            "remainder": remainder,
            "same_nonzero_sign": same_nonzero_sign,
            "first_order_dominant": dominant,
        },
        "materiality_artifact_sha256": None if materiality is None else materiality["artifact_sha256"],
        "bridge_verdict": bridge_verdict,
        "credits": {
            "whole_step": False,
            "actual_update": False,
            "orientation": False,
            "signed_first_order": False,
            "first_order_dominant": False,
            "material_loss_bridge": False,
            "model_result": False,
            "checkpoint_result": False,
            "capability": False,
        },
        "historical_sibling_limit": "SIBLING_NON_NULL_ORIENTATION_ONLY",
        "no_new_parallel_authority": True,
    }
    return _seal(receipt, "receipt_sha256")


def evaluate_or_refuse(**kwargs: object) -> dict[str, object]:
    """Return a sealed FAILED_ENGAGEMENT receipt for every named refusal.

    The wrapper is the public admission boundary.  It intentionally exposes no
    exception text, host path, or partial statistic and grants no credit.
    """
    try:
        return evaluate_actual_update(**kwargs)  # type: ignore[arg-type]
    except Refusal as exc:
        receipt: dict[str, object] = {
            "schema": "q2-actual-update-successor-refusal-v1",
            "issue": 675,
            "verdict": "FAILED_ENGAGEMENT",
            "refusal_code": exc.code,
            "credits": {
                "whole_step": False,
                "actual_update": False,
                "orientation": False,
                "signed_first_order": False,
                "first_order_dominant": False,
                "material_loss_bridge": False,
                "model_result": False,
                "checkpoint_result": False,
                "capability": False,
            },
            "no_new_parallel_authority": True,
        }
        return _seal(receipt, "receipt_sha256")
