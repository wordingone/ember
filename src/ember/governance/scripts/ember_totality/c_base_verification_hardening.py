# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Forward-only C-BASE verification receipt hardening (issue #320)."""
from __future__ import annotations

import math
from typing import Any


PASS_MARKERS = ("PASS", "VERIFIED", "TRAINABLE")
ACTIVATION_SLACK = 1.05


def _mapping(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _pass_class(value: Any) -> bool:
    return isinstance(value, str) and any(marker in value.upper() for marker in PASS_MARKERS)


def _loss_trace(obj: dict) -> list[float] | None:
    candidates = [
        _mapping(obj.get("verification")).get("loss_trace"),
        _mapping(obj.get("results")).get("batch_losses"),
        obj.get("per_batch_losses"),
    ]
    for candidate in candidates:
        if not isinstance(candidate, list) or not candidate:
            continue
        if all(
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(float(value))
            for value in candidate
        ):
            return [float(value) for value in candidate]
    return None


def _vocab_size(obj: dict) -> int | None:
    for value in (
        _mapping(obj.get("model")).get("vocab"),
        _mapping(obj.get("model")).get("vocab_size"),
        _mapping(obj.get("config")).get("vocab"),
        _mapping(obj.get("config")).get("vocab_size"),
    ):
        if (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(float(value))
            and int(value) == value
            and int(value) > 1
        ):
            return int(value)
    return None


def _params_m(obj: dict) -> float | None:
    model = _mapping(obj.get("model"))
    config = _mapping(obj.get("config"))
    for value in (model.get("estimated_params_m"), model.get("params_m"), obj.get("model_params_m")):
        if (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(float(value))
            and float(value) > 0
        ):
            return float(value)
    # Conservative Llama-like lower bound from the receipt's own architecture:
    # embedding + four attention projections + three SwiGLU projections/layer.
    source = config if config else model
    vocab, hidden, layers, intermediate = (
        source.get("vocab"), source.get("hidden"), source.get("layers"), source.get("intermediate")
    )
    if all(
        isinstance(value, int) and not isinstance(value, bool) and value > 0
        for value in (vocab, hidden, layers, intermediate)
    ):
        return (
            vocab * hidden + layers * (4 * hidden * hidden + 3 * hidden * intermediate)
        ) / 1_000_000
    return None

def _vram_peak_gib(obj: dict) -> float | None:
    for value in (
        _mapping(obj.get("cuda")).get("vram_peak_during_job_gib"),
        _mapping(obj.get("vram")).get("peak_gb"),
        obj.get("vram_peak_max_gb"),
    ):
        if (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(float(value))
            and float(value) >= 0
        ):
            return float(value)
    return None


def _claims_gpu(obj: dict) -> bool:
    values = [
        _mapping(obj.get("cuda")).get("device"),
        obj.get("device"),
        obj.get("cuda_device"),
    ]
    return any(
        isinstance(value, str)
        and ("gpu" in value.lower() or "cuda" in value.lower() or "nvidia" in value.lower())
        for value in values
    )


def _walk_pairs(value: Any):
    if isinstance(value, dict):
        for key, child in value.items():
            yield str(key).lower().replace("-", "_").replace(" ", "_"), child
            yield from _walk_pairs(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_pairs(child)


def has_verification_evidence(obj: dict) -> bool:
    return bool(
        _loss_trace(obj)
        or isinstance(obj.get("verification"), dict)
        or isinstance(obj.get("results"), dict)
        or "gpu_verify" in str(obj.get("mode", "")).lower()
        or "verify" in str(obj.get("ticket", "")).lower()
    )


def verification_receipt_disposition(obj: dict) -> str:
    """Return VERIFIED, NON_VERDICT, REJECTED, or NOT_APPLICABLE.

    NON_VERDICT preserves an honest failure artifact without allowing it to
    satisfy a positive C-BASE checkpoint clause. REJECTED means a PASS-class
    claim contradicts evidence carried by the same receipt.
    """
    if not isinstance(obj, dict) or not has_verification_evidence(obj):
        return "NOT_APPLICABLE"
    if not _pass_class(obj.get("verdict")):
        return "NON_VERDICT"

    loss_functions = [
        value
        for key, value in _walk_pairs(obj)
        if key == "loss_function" and isinstance(value, str)
    ]
    if any("random logits" in value.lower() for value in loss_functions):
        return "REJECTED"

    losses = _loss_trace(obj)
    vocab = _vocab_size(obj)
    if losses is None or vocab is None:
        return "REJECTED"
    if len(set(losses)) == 1 or all(value < 1e-3 for value in losses):
        return "REJECTED"
    mean_loss = sum(losses) / len(losses)
    if abs(mean_loss - math.log(vocab)) < 0.05:
        return "REJECTED"

    params_m = _params_m(obj)
    if _claims_gpu(obj):
        if params_m is None:
            return "REJECTED"
        peak_gib = _vram_peak_gib(obj)
        parameter_floor_gib = params_m * 2_000_000 * ACTIVATION_SLACK / (1024 ** 3)
        if peak_gib is None or peak_gib < parameter_floor_gib:
            return "REJECTED"

    diagnosis = str(obj.get("diagnosis", "")).lower()
    if any(
        marker in diagnosis
        for marker in ("incomplete", "random baseline", "load failure", "load failed")
    ):
        return "REJECTED"
    return "VERIFIED"
