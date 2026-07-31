#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Measure whether low-precision parameter storage preserves gradient-caused updates.

The treatment and explicit-zero-gradient branches start from identical parameter
and optimizer state. Decoupled weight decay is reported separately and cannot
mint a passing signal-survival result.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import inspect
import json
import math
import os
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import torch

SCHEMA = "ember-update-survival-preflight/v1"
VERDICTS = {"PREFLIGHT_PASS", "PREFLIGHT_FAIL", "PREFLIGHT_INVALID"}
TOP_LEVEL_KEYS = {
    "schema",
    "verdict",
    "invalid_code",
    "optimizer",
    "treatment_dtype",
    "gradient_source",
    "gradient_source_sha256",
    "reference_identity",
    "class_survival_floors",
    "steps",
    "receipt_sha256",
}
GRADIENT_SOURCE_KEYS = {"kind", "source_id"}
OPTIMIZER_REQUIRED_KEYS = {
    "sgd": {
        "lr",
        "momentum",
        "dampening",
        "weight_decay",
        "nesterov",
        "maximize",
        "foreach",
    },
    "adamw": {
        "lr",
        "betas",
        "eps",
        "weight_decay",
        "amsgrad",
        "maximize",
        "foreach",
        "capturable",
        "differentiable",
        "fused",
    },
    "adafactor": {
        "lr",
        "beta2_decay",
        "eps",
        "d",
        "weight_decay",
        "foreach",
        "maximize",
    },
}
OPTIMIZER_CLASSES = {
    "sgd": torch.optim.SGD,
    "adamw": torch.optim.AdamW,
    "adafactor": torch.optim.Adafactor,
}
LIVE_OPTIMIZER_FAMILIES = {value: key for key, value in OPTIMIZER_CLASSES.items()}
LIVE_GROUP_REQUIRED_KEYS = {
    "sgd": OPTIMIZER_REQUIRED_KEYS["sgd"] | {"differentiable", "fused"},
    "adamw": OPTIMIZER_REQUIRED_KEYS["adamw"] | {"decoupled_weight_decay"},
    "adafactor": OPTIMIZER_REQUIRED_KEYS["adafactor"],
}


@dataclass(frozen=True)
class TensorProbe:
    name: str
    tensor_class: str
    initial: torch.Tensor
    gradient: torch.Tensor
    required_survival: bool = False


@dataclass(frozen=True)
class LiveTensorBinding:
    name: str
    tensor_class: str
    parameter: torch.nn.Parameter
    required_survival: bool = False


@dataclass(frozen=True)
class OptimizerParamGroup:
    parameter_names: Sequence[str]
    options: Mapping[str, Any]


@dataclass(frozen=True)
class OptimizerSpec:
    family: str
    kwargs: Mapping[str, Any]
    param_groups: Sequence[OptimizerParamGroup] | None = None


class PreflightInputError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in sorted(value.items())}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if isinstance(value, torch.dtype):
        return str(value)
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise PreflightInputError(
                "PREFLIGHT_INVALID_INPUT", "non-finite numeric input"
            )
        return value
    raise PreflightInputError(
        "PREFLIGHT_INVALID_INPUT",
        f"value is not canonically serializable: {type(value).__name__}",
    )


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        _jsonable(value),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _state_projection(value: Any) -> Any:
    if isinstance(value, torch.Tensor):
        return {
            "kind": "tensor",
            "dtype": str(value.dtype),
            "shape": list(value.shape),
            "sha256": hashlib.sha256(_tensor_bytes(value)).hexdigest(),
        }
    if isinstance(value, Mapping):
        return {
            str(key): _state_projection(item)
            for key, item in sorted(value.items(), key=lambda row: str(row[0]))
        }
    if isinstance(value, (tuple, list)):
        return [_state_projection(item) for item in value]
    return _jsonable(value)


def _optimizer_state_sha256(value: Mapping[str, Any]) -> str:
    return _canonical_sha256(_state_projection(value))


def _tensor_bytes(tensor: torch.Tensor) -> bytes:
    cpu = tensor.detach().contiguous().cpu()
    return cpu.reshape(-1).view(torch.uint8).numpy().tobytes()


def _tensor_identity(probe: TensorProbe) -> dict[str, Any]:
    return {
        "name": probe.name,
        "tensor_class": probe.tensor_class,
        "shape": list(probe.gradient.shape),
        "dtype": str(probe.gradient.dtype),
        "gradient_sha256": hashlib.sha256(_tensor_bytes(probe.gradient)).hexdigest(),
        "required_survival": probe.required_survival,
    }


def _optimizer_source_identity(family: str) -> dict[str, str]:
    optimizer_class = OPTIMIZER_CLASSES[family]
    source = inspect.getsourcefile(optimizer_class)
    if source is None:
        raise PreflightInputError(
            "PREFLIGHT_INVALID_REFERENCE",
            "optimizer implementation source is unavailable",
        )
    path = Path(source)
    try:
        source_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise PreflightInputError(
            "PREFLIGHT_INVALID_REFERENCE",
            "optimizer implementation source is unreadable",
        ) from exc
    return {
        "qualified_name": f"{optimizer_class.__module__}.{optimizer_class.__qualname__}",
        "source_sha256": source_sha256,
    }


def _validate_explicit_optimizer_options(
    family: str,
    options: Mapping[str, Any],
    *,
    expected_keys: set[str],
) -> dict[str, Any]:
    realized = dict(options)
    if set(realized) != expected_keys:
        raise PreflightInputError(
            "PREFLIGHT_INVALID_REFERENCE",
            f"optimizer options are not closed missing={sorted(expected_keys - set(realized))} "
            f"extra={sorted(set(realized) - expected_keys)}",
        )
    canonical = _jsonable(realized)
    if family == "adafactor":
        eps = realized["eps"]
        if (
            not isinstance(eps, (tuple, list))
            or len(eps) != 2
            or eps[0] is None
            or any(
                not isinstance(item, (int, float))
                or not math.isfinite(float(item))
                or float(item) <= 0.0
                for item in eps
            )
        ):
            raise PreflightInputError(
                "PREFLIGHT_INVALID_REFERENCE",
                "Adafactor eps scalars must be explicit and positive before dtype cloning",
            )
    return canonical


def _validate_optimizer_spec(
    spec: OptimizerSpec,
    *,
    probe_names: Sequence[str],
) -> dict[str, Any]:
    family = spec.family.lower()
    if family not in OPTIMIZER_REQUIRED_KEYS:
        raise PreflightInputError(
            "PREFLIGHT_INVALID_REFERENCE",
            f"optimizer family has no validated causal-twin adapter: {family}",
        )
    kwargs = _validate_explicit_optimizer_options(
        family,
        spec.kwargs,
        expected_keys=OPTIMIZER_REQUIRED_KEYS[family],
    )
    result: dict[str, Any] = {"family": family, "kwargs": kwargs}
    if spec.param_groups is None:
        return result
    if not spec.param_groups:
        raise PreflightInputError(
            "PREFLIGHT_INVALID_REFERENCE", "optimizer parameter groups are empty"
        )
    seen: list[str] = []
    groups: list[dict[str, Any]] = []
    for group in spec.param_groups:
        names = list(group.parameter_names)
        if (
            not names
            or any(not isinstance(name, str) or not name.strip() for name in names)
            or len(set(names)) != len(names)
        ):
            raise PreflightInputError(
                "PREFLIGHT_INVALID_REFERENCE",
                "optimizer parameter-group names are empty or duplicated",
            )
        seen.extend(names)
        groups.append(
            {
                "parameter_names": names,
                "options": _validate_explicit_optimizer_options(
                    family,
                    group.options,
                    expected_keys=LIVE_GROUP_REQUIRED_KEYS[family],
                ),
            }
        )
    if len(set(seen)) != len(seen) or set(seen) != set(probe_names):
        raise PreflightInputError(
            "PREFLIGHT_INVALID_REFERENCE",
            "optimizer parameter groups do not exactly cover the deduplicated probes",
        )
    result["param_groups"] = groups
    return result


def _validate_inputs(
    probes: Sequence[TensorProbe],
    *,
    treatment_dtype: torch.dtype,
    step_counts: Sequence[int],
    class_survival_floors: Mapping[str, float],
    gradient_source: Mapping[str, str],
) -> None:
    if treatment_dtype not in {torch.bfloat16, torch.float16, torch.float32}:
        raise PreflightInputError(
            "PREFLIGHT_INVALID_INPUT", "unsupported treatment dtype"
        )
    if not probes:
        raise PreflightInputError(
            "PREFLIGHT_INVALID_INPUT", "at least one tensor probe is required"
        )
    names = [probe.name for probe in probes]
    if any(not isinstance(name, str) or not name.strip() for name in names):
        raise PreflightInputError(
            "PREFLIGHT_INVALID_INPUT", "tensor names must be nonempty"
        )
    if len(set(names)) != len(names):
        raise PreflightInputError(
            "PREFLIGHT_INVALID_INPUT", "tensor names must be unique"
        )
    classes = {probe.tensor_class for probe in probes}
    if (
        any(not isinstance(name, str) or not name.strip() for name in classes)
        or set(class_survival_floors) != classes
    ):
        raise PreflightInputError(
            "PREFLIGHT_INVALID_INPUT",
            "survival floors must exactly cover tensor classes",
        )
    for class_name, floor in class_survival_floors.items():
        if (
            not isinstance(floor, (int, float))
            or not math.isfinite(float(floor))
            or not 0.0 <= float(floor) <= 1.0
        ):
            raise PreflightInputError(
                "PREFLIGHT_INVALID_INPUT",
                f"invalid survival floor for {class_name}",
            )
    if (
        not step_counts
        or list(step_counts) != sorted(set(step_counts))
        or any(not isinstance(step, int) or step < 1 for step in step_counts)
    ):
        raise PreflightInputError(
            "PREFLIGHT_INVALID_INPUT",
            "step counts must be unique increasing positive integers",
        )
    if set(gradient_source) != GRADIENT_SOURCE_KEYS or any(
        not isinstance(gradient_source[key], str) or not gradient_source[key].strip()
        for key in GRADIENT_SOURCE_KEYS
    ):
        raise PreflightInputError(
            "PREFLIGHT_INVALID_INPUT", "gradient source schema is invalid"
        )
    for probe in probes:
        if (
            not isinstance(probe.initial, torch.Tensor)
            or not isinstance(probe.gradient, torch.Tensor)
            or probe.initial.shape != probe.gradient.shape
            or probe.initial.numel() == 0
            or not torch.isfinite(probe.initial.float()).all().item()
            or not torch.isfinite(probe.gradient.float()).all().item()
        ):
            raise PreflightInputError(
                "PREFLIGHT_INVALID_INPUT",
                f"tensor probe is malformed: {probe.name}",
            )


def _build_optimizer(
    parameters: Sequence[torch.nn.Parameter],
    optimizer: Mapping[str, Any],
    optimizer_state_dict: Mapping[str, Any] | None,
    *,
    parameter_names: Sequence[str],
) -> torch.optim.Optimizer:
    family = str(optimizer["family"])
    optimizer_class = OPTIMIZER_CLASSES[family]
    if "param_groups" in optimizer:
        by_name = dict(zip(parameter_names, parameters))
        group_inputs = [
            {
                **copy.deepcopy(dict(group["options"])),
                "params": [by_name[name] for name in group["parameter_names"]],
            }
            for group in optimizer["param_groups"]
        ]
        instance = optimizer_class(group_inputs)
    else:
        instance = optimizer_class(
            parameters,
            **copy.deepcopy(dict(optimizer["kwargs"])),
        )
    if optimizer_state_dict is not None:
        saved_groups = optimizer_state_dict.get("param_groups")
        if not isinstance(saved_groups, list) or len(saved_groups) != len(
            instance.param_groups
        ):
            raise PreflightInputError(
                "PREFLIGHT_INVALID_REFERENCE",
                "optimizer state parameter-group count does not match the declared optimizer",
            )
        for expected_group, saved_group in zip(instance.param_groups, saved_groups):
            if not isinstance(saved_group, Mapping):
                raise PreflightInputError(
                    "PREFLIGHT_INVALID_REFERENCE", "optimizer state group is malformed"
                )
            saved_parameters = saved_group.get("params")
            if (
                not isinstance(saved_parameters, list)
                or len(saved_parameters) != len(expected_group["params"])
                or _jsonable(
                    {
                        key: value
                        for key, value in saved_group.items()
                        if key != "params"
                    }
                )
                != _jsonable(
                    {
                        key: value
                        for key, value in expected_group.items()
                        if key != "params"
                    }
                )
            ):
                raise PreflightInputError(
                    "PREFLIGHT_INVALID_REFERENCE",
                    "optimizer state hyperparameters drift from the declared optimizer",
                )
        try:
            instance.load_state_dict(copy.deepcopy(dict(optimizer_state_dict)))
        except (KeyError, TypeError, ValueError, RuntimeError) as exc:
            raise PreflightInputError(
                "PREFLIGHT_INVALID_REFERENCE",
                "optimizer state cannot be cloned into the treatment/reference twins",
            ) from exc
    return instance


def _optimizer_state_dtypes(optimizer: torch.optim.Optimizer) -> list[str]:
    return sorted(
        {
            str(value.dtype)
            for state in optimizer.state.values()
            for value in state.values()
            if isinstance(value, torch.Tensor)
        }
    )


def _rms(tensor: torch.Tensor) -> float:
    if tensor.numel() == 0:
        return 0.0
    return float(torch.sqrt(torch.mean(tensor.float().square())).item())


def _cosine(left: torch.Tensor, right: torch.Tensor) -> float:
    left_flat = left.float().reshape(-1)
    right_flat = right.float().reshape(-1)
    denominator = float(left_flat.norm().item() * right_flat.norm().item())
    if denominator == 0.0:
        return 0.0
    result = float(torch.dot(left_flat, right_flat).item() / denominator)
    return result if math.isfinite(result) else 0.0


def _class_metrics(
    rows: Sequence[dict[str, Any]],
) -> dict[str, dict[str, float]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row["tensor_class"]), []).append(row)
    result: dict[str, dict[str, float]] = {}
    for class_name, class_rows in sorted(grouped.items()):
        causal = torch.cat([row["causal"].reshape(-1) for row in class_rows])
        total = torch.cat([row["total"].reshape(-1) for row in class_rows])
        decay = torch.cat([row["decay"].reshape(-1) for row in class_rows])
        fp32 = torch.cat([row["fp32_causal"].reshape(-1) for row in class_rows])
        storage = torch.cat(
            [row["storage_achievable"].reshape(-1) for row in class_rows]
        )
        causal_rms = _rms(causal)
        fp32_rms = _rms(fp32)
        result[class_name] = {
            "causal_changed_fraction": float(
                torch.count_nonzero(causal).item() / causal.numel()
            ),
            "total_changed_fraction": float(
                torch.count_nonzero(total).item() / total.numel()
            ),
            "causal_rms": causal_rms,
            "decay_rms": _rms(decay),
            "fp32_causal_rms": fp32_rms,
            "storage_achievable_rms": _rms(storage),
            "realized_to_fp32_rms_ratio": (
                float(causal_rms / fp32_rms) if fp32_rms > 0.0 else 0.0
            ),
            "causal_cosine_to_fp32": _cosine(causal, fp32),
        }
    return result


def _ordered_optimizer_state(
    optimizer: torch.optim.Optimizer,
) -> list[Mapping[str, Any]]:
    return [
        optimizer.state.get(parameter, {})
        for group in optimizer.param_groups
        for parameter in group["params"]
    ]


def _pre_step_optimizer_state_identity(
    treatment_actual: torch.optim.Optimizer,
    treatment_zero: torch.optim.Optimizer,
    reference_actual: torch.optim.Optimizer,
    reference_zero: torch.optim.Optimizer,
) -> dict[str, Any]:
    if _optimizer_state_sha256(
        treatment_actual.state_dict()
    ) != _optimizer_state_sha256(
        treatment_zero.state_dict()
    ) or _optimizer_state_sha256(
        reference_actual.state_dict()
    ) != _optimizer_state_sha256(reference_zero.state_dict()):
        raise PreflightInputError(
            "PREFLIGHT_INVALID_REFERENCE",
            "actual and explicit-zero twins do not start from identical optimizer state",
        )
    treatment_states = _ordered_optimizer_state(treatment_actual)
    reference_states = _ordered_optimizer_state(reference_actual)
    if len(treatment_states) != len(reference_states):
        raise PreflightInputError(
            "PREFLIGHT_INVALID_REFERENCE", "optimizer state slot counts differ"
        )
    projection: list[dict[str, Any]] = []
    tensor_state_count = 0
    for slot, (treatment_state, reference_state) in enumerate(
        zip(treatment_states, reference_states)
    ):
        if set(treatment_state) != set(reference_state):
            raise PreflightInputError(
                "PREFLIGHT_INVALID_REFERENCE", "optimizer state keys differ"
            )
        for key in sorted(treatment_state, key=str):
            treatment_value = treatment_state[key]
            reference_value = reference_state[key]
            if isinstance(treatment_value, torch.Tensor) != isinstance(
                reference_value, torch.Tensor
            ):
                raise PreflightInputError(
                    "PREFLIGHT_INVALID_REFERENCE", "optimizer state value kinds differ"
                )
            if isinstance(treatment_value, torch.Tensor):
                if treatment_value.shape != reference_value.shape:
                    raise PreflightInputError(
                        "PREFLIGHT_INVALID_REFERENCE", "optimizer state shapes differ"
                    )
                expected_treatment = reference_value.detach().to(
                    device=treatment_value.device,
                    dtype=treatment_value.dtype,
                )
                if not torch.equal(treatment_value.detach(), expected_treatment):
                    raise PreflightInputError(
                        "PREFLIGHT_INVALID_REFERENCE",
                        "optimizer state violates the receipted dtype mapping",
                    )
                tensor_state_count += 1
                projection.append(
                    {
                        "slot": slot,
                        "key": str(key),
                        "shape": list(treatment_value.shape),
                        "treatment_dtype": str(treatment_value.dtype),
                        "reference_dtype": str(reference_value.dtype),
                        "treatment_sha256": hashlib.sha256(
                            _tensor_bytes(treatment_value)
                        ).hexdigest(),
                        "reference_sha256": hashlib.sha256(
                            _tensor_bytes(reference_value)
                        ).hexdigest(),
                    }
                )
            elif _jsonable(treatment_value) != _jsonable(reference_value):
                raise PreflightInputError(
                    "PREFLIGHT_INVALID_REFERENCE", "optimizer scalar state differs"
                )
            else:
                projection.append(
                    {"slot": slot, "key": str(key), "value": _jsonable(treatment_value)}
                )
    return {
        "status": "CLEAR",
        "tensor_state_count": tensor_state_count,
        "mapping_sha256": _canonical_sha256(projection),
    }


def _run_step_count(
    probes: Sequence[TensorProbe],
    *,
    optimizer: Mapping[str, Any],
    optimizer_state_dict: Mapping[str, Any] | None,
    treatment_dtype: torch.dtype,
    step_count: int,
    class_survival_floors: Mapping[str, float],
) -> dict[str, Any]:
    treatment_actual = [
        torch.nn.Parameter(probe.initial.detach().to(dtype=treatment_dtype).clone())
        for probe in probes
    ]
    treatment_zero = [
        torch.nn.Parameter(probe.initial.detach().to(dtype=treatment_dtype).clone())
        for probe in probes
    ]
    reference_actual = [
        torch.nn.Parameter(probe.initial.detach().float().clone()) for probe in probes
    ]
    reference_zero = [
        torch.nn.Parameter(probe.initial.detach().float().clone()) for probe in probes
    ]
    initial_treatment = [parameter.detach().clone() for parameter in treatment_actual]

    treatment_actual_optimizer = _build_optimizer(
        treatment_actual,
        optimizer,
        optimizer_state_dict,
        parameter_names=[probe.name for probe in probes],
    )
    treatment_zero_optimizer = _build_optimizer(
        treatment_zero,
        optimizer,
        optimizer_state_dict,
        parameter_names=[probe.name for probe in probes],
    )
    reference_actual_optimizer = _build_optimizer(
        reference_actual,
        optimizer,
        optimizer_state_dict,
        parameter_names=[probe.name for probe in probes],
    )
    reference_zero_optimizer = _build_optimizer(
        reference_zero,
        optimizer,
        optimizer_state_dict,
        parameter_names=[probe.name for probe in probes],
    )
    pre_step_state_identity = _pre_step_optimizer_state_identity(
        treatment_actual_optimizer,
        treatment_zero_optimizer,
        reference_actual_optimizer,
        reference_zero_optimizer,
    )

    for _ in range(step_count):
        for index, probe in enumerate(probes):
            treatment_actual[index].grad = probe.gradient.detach().to(
                dtype=treatment_dtype
            )
            treatment_zero[index].grad = torch.zeros_like(treatment_zero[index])
            reference_actual[index].grad = probe.gradient.detach().float().clone()
            reference_zero[index].grad = torch.zeros_like(reference_zero[index])
        treatment_actual_optimizer.step()
        treatment_zero_optimizer.step()
        reference_actual_optimizer.step()
        reference_zero_optimizer.step()

    rows: list[dict[str, Any]] = []
    frozen_required: list[str] = []
    changed_tensor_count = 0
    for index, probe in enumerate(probes):
        actual = treatment_actual[index].detach()
        zero = treatment_zero[index].detach()
        reference = reference_actual[index].detach()
        reference_zero_value = reference_zero[index].detach()
        causal = actual.float() - zero.float()
        total = actual.float() - initial_treatment[index].float()
        decay = zero.float() - initial_treatment[index].float()
        fp32_causal = reference.float() - reference_zero_value.float()
        storage_achievable = (
            reference.to(dtype=treatment_dtype).float()
            - reference_zero_value.to(dtype=treatment_dtype).float()
        )
        changed = bool(torch.count_nonzero(causal).item())
        changed_tensor_count += int(changed)
        if probe.required_survival and not changed:
            frozen_required.append(probe.name)
        rows.append(
            {
                "name": probe.name,
                "tensor_class": probe.tensor_class,
                "causal": causal,
                "total": total,
                "decay": decay,
                "fp32_causal": fp32_causal,
                "storage_achievable": storage_achievable,
            }
        )
    metrics = _class_metrics(rows)
    failed_classes = sorted(
        class_name
        for class_name, floor in class_survival_floors.items()
        if metrics[class_name]["causal_changed_fraction"] < float(floor)
    )
    return {
        "step_count": step_count,
        "fresh_twin_from_initial_state": True,
        "pre_step_optimizer_state_identity": pre_step_state_identity,
        "tensor_count": len(probes),
        "changed_tensor_count": changed_tensor_count,
        "frozen_required_tensors": sorted(frozen_required),
        "failed_tensor_classes": failed_classes,
        "tensor_classes": metrics,
        "optimizer_state_dtypes": _optimizer_state_dtypes(treatment_actual_optimizer),
    }


def _safe_invalid_projection(value: Any) -> Any:
    try:
        return _jsonable(value)
    except (PreflightInputError, TypeError, ValueError):
        return {
            "status": "UNAVAILABLE_UNCANONICAL_INPUT",
            "type": type(value).__name__,
        }


def _invalid_receipt(
    *,
    code: str,
    optimizer_spec: OptimizerSpec,
    treatment_dtype: torch.dtype,
    gradient_source: Mapping[str, str],
    class_survival_floors: Mapping[str, float],
) -> dict[str, Any]:
    receipt: dict[str, Any] = {
        "schema": SCHEMA,
        "verdict": "PREFLIGHT_INVALID",
        "invalid_code": code,
        "optimizer": {
            "family": optimizer_spec.family
            if isinstance(optimizer_spec.family, str)
            else "<invalid>",
            "kwargs": _safe_invalid_projection(dict(optimizer_spec.kwargs)),
        },
        "treatment_dtype": str(treatment_dtype),
        "gradient_source": _safe_invalid_projection(dict(gradient_source)),
        "gradient_source_sha256": _canonical_sha256(
            _safe_invalid_projection(dict(gradient_source))
        ),
        "reference_identity": {"status": "INVALID", "source": None},
        "class_survival_floors": _safe_invalid_projection(dict(class_survival_floors)),
        "steps": [],
        "receipt_sha256": "",
    }
    receipt["receipt_sha256"] = _canonical_sha256(
        {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    )
    return receipt


def run_update_survival_preflight(
    *,
    probes: Sequence[TensorProbe],
    optimizer_spec: OptimizerSpec,
    treatment_dtype: torch.dtype,
    step_counts: Sequence[int] = (1, 5),
    class_survival_floors: Mapping[str, float],
    gradient_source: Mapping[str, str],
    optimizer_state_dict: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a canonical path-free receipt; invalid evidence never launches."""
    try:
        _validate_inputs(
            probes,
            treatment_dtype=treatment_dtype,
            step_counts=step_counts,
            class_survival_floors=class_survival_floors,
            gradient_source=gradient_source,
        )
        optimizer = _validate_optimizer_spec(
            optimizer_spec, probe_names=[probe.name for probe in probes]
        )
        source_identity = _optimizer_source_identity(str(optimizer["family"]))
        gradient_projection = {
            "source": dict(gradient_source),
            "tensors": [_tensor_identity(probe) for probe in probes],
        }
        gradient_sha256 = _canonical_sha256(gradient_projection)
        state_identity = (
            _optimizer_state_sha256(optimizer_state_dict)
            if optimizer_state_dict is not None
            else _canonical_sha256({"state": "fresh-empty"})
        )
        reference_identity = {
            "status": "CLEAR",
            "reference_dtype": "torch.float32",
            "explicit_optimizer_kwargs": optimizer["kwargs"],
            "optimizer_source": source_identity,
            "optimizer_state_sha256": state_identity,
        }
        steps = [
            _run_step_count(
                probes,
                optimizer=optimizer,
                optimizer_state_dict=optimizer_state_dict,
                treatment_dtype=treatment_dtype,
                step_count=step_count,
                class_survival_floors=class_survival_floors,
            )
            for step_count in step_counts
        ]
        verdict = (
            "PREFLIGHT_FAIL"
            if any(
                step["frozen_required_tensors"] or step["failed_tensor_classes"]
                for step in steps
            )
            else "PREFLIGHT_PASS"
        )
        receipt: dict[str, Any] = {
            "schema": SCHEMA,
            "verdict": verdict,
            "invalid_code": None,
            "optimizer": optimizer,
            "treatment_dtype": str(treatment_dtype),
            "gradient_source": _safe_invalid_projection(dict(gradient_source)),
            "gradient_source_sha256": gradient_sha256,
            "reference_identity": reference_identity,
            "class_survival_floors": _safe_invalid_projection(
                dict(class_survival_floors)
            ),
            "steps": steps,
            "receipt_sha256": "",
        }
        if set(receipt) != TOP_LEVEL_KEYS or receipt["verdict"] not in VERDICTS:
            raise AssertionError("internal receipt schema drift")
        receipt["receipt_sha256"] = _canonical_sha256(
            {key: value for key, value in receipt.items() if key != "receipt_sha256"}
        )
        return receipt
    except PreflightInputError as exc:
        return _invalid_receipt(
            code=exc.code,
            optimizer_spec=optimizer_spec,
            treatment_dtype=treatment_dtype,
            gradient_source=gradient_source,
            class_survival_floors=class_survival_floors,
        )


def _live_invalid_receipt(
    *,
    code: str,
    optimizer: torch.optim.Optimizer,
    treatment_dtype: torch.dtype,
    gradient_source: Mapping[str, str],
    class_survival_floors: Mapping[str, float],
) -> dict[str, Any]:
    family = LIVE_OPTIMIZER_FAMILIES.get(type(optimizer), type(optimizer).__qualname__)
    return _invalid_receipt(
        code=code,
        optimizer_spec=OptimizerSpec(family=str(family), kwargs={}),
        treatment_dtype=treatment_dtype,
        gradient_source=gradient_source,
        class_survival_floors=class_survival_floors,
    )


def run_live_optimizer_update_survival_preflight(
    *,
    bindings: Sequence[LiveTensorBinding],
    optimizer: torch.optim.Optimizer,
    treatment_dtype: torch.dtype,
    step_counts: Sequence[int] = (1, 5),
    class_survival_floors: Mapping[str, float],
    gradient_source: Mapping[str, str],
) -> dict[str, Any]:
    """Capture the realized optimizer groups/state and run causal twins.

    Only exact repository-validated built-in adapters are admitted. The live
    parameter binding must cover every optimizer slot exactly once and every
    captured gradient is an explicit tensor; missing gradients fail closed.
    """
    family = LIVE_OPTIMIZER_FAMILIES.get(type(optimizer))
    if family is None:
        return _live_invalid_receipt(
            code="PREFLIGHT_INVALID_REFERENCE",
            optimizer=optimizer,
            treatment_dtype=treatment_dtype,
            gradient_source=gradient_source,
            class_survival_floors=class_survival_floors,
        )
    names = [binding.name for binding in bindings]
    parameter_ids = [id(binding.parameter) for binding in bindings]
    if (
        not bindings
        or len(set(names)) != len(names)
        or len(set(parameter_ids)) != len(parameter_ids)
        or any(
            not isinstance(binding.parameter, torch.nn.Parameter)
            or binding.parameter.dtype != treatment_dtype
            for binding in bindings
        )
    ):
        return _live_invalid_receipt(
            code="PREFLIGHT_INVALID_REFERENCE",
            optimizer=optimizer,
            treatment_dtype=treatment_dtype,
            gradient_source=gradient_source,
            class_survival_floors=class_survival_floors,
        )
    name_by_parameter_id = {id(binding.parameter): binding.name for binding in bindings}
    optimizer_parameter_ids = [
        id(parameter)
        for group in optimizer.param_groups
        for parameter in group["params"]
    ]
    if len(set(optimizer_parameter_ids)) != len(optimizer_parameter_ids) or set(
        optimizer_parameter_ids
    ) != set(parameter_ids):
        return _live_invalid_receipt(
            code="PREFLIGHT_INVALID_REFERENCE",
            optimizer=optimizer,
            treatment_dtype=treatment_dtype,
            gradient_source=gradient_source,
            class_survival_floors=class_survival_floors,
        )
    param_groups: list[OptimizerParamGroup] = []
    for group in optimizer.param_groups:
        options = {key: value for key, value in group.items() if key != "params"}
        if set(options) != LIVE_GROUP_REQUIRED_KEYS[family]:
            return _live_invalid_receipt(
                code="PREFLIGHT_INVALID_REFERENCE",
                optimizer=optimizer,
                treatment_dtype=treatment_dtype,
                gradient_source=gradient_source,
                class_survival_floors=class_survival_floors,
            )
        param_groups.append(
            OptimizerParamGroup(
                parameter_names=[name_by_parameter_id[id(p)] for p in group["params"]],
                options=options,
            )
        )
    first_options = dict(param_groups[0].options)
    optimizer_spec = OptimizerSpec(
        family=family,
        kwargs={key: first_options[key] for key in OPTIMIZER_REQUIRED_KEYS[family]},
        param_groups=param_groups,
    )
    probes = [
        TensorProbe(
            name=binding.name,
            tensor_class=binding.tensor_class,
            initial=binding.parameter.detach().clone(),
            gradient=(
                binding.parameter.grad.detach().clone()
                if isinstance(binding.parameter.grad, torch.Tensor)
                else None  # type: ignore[arg-type]
            ),
            required_survival=binding.required_survival,
        )
        for binding in bindings
    ]
    return run_update_survival_preflight(
        probes=probes,
        optimizer_spec=optimizer_spec,
        optimizer_state_dict=optimizer.state_dict(),
        treatment_dtype=treatment_dtype,
        step_counts=step_counts,
        class_survival_floors=class_survival_floors,
        gradient_source=gradient_source,
    )


def _selftest_sgd_spec() -> OptimizerSpec:
    return OptimizerSpec(
        family="sgd",
        kwargs={
            "lr": 1.0,
            "momentum": 0.0,
            "dampening": 0.0,
            "weight_decay": 0.0,
            "nesterov": False,
            "maximize": False,
            "foreach": False,
        },
    )


def _selftest_bitnet_probes() -> list[TensorProbe]:
    return [
        TensorProbe(
            name=f"{'weight' if index < 15 else 'norm-scale'}.{index}",
            tensor_class="weight" if index < 15 else "norm_scale",
            initial=torch.ones(8, dtype=torch.bfloat16),
            gradient=torch.full(
                (8,),
                1.0e-2 if index < 15 else 1.0e-4,
                dtype=torch.float32,
            ),
            required_survival=index >= 15,
        )
        for index in range(24)
    ]


def _run_cpu_selftest() -> dict[str, Any]:
    adamw = OptimizerSpec(
        family="adamw",
        kwargs={
            "lr": 0.01,
            "betas": (0.9, 0.999),
            "eps": 1.0e-8,
            "weight_decay": 1.0,
            "amsgrad": False,
            "maximize": False,
            "foreach": False,
            "capturable": False,
            "differentiable": False,
            "fused": False,
        },
    )
    decay = run_update_survival_preflight(
        probes=[
            TensorProbe(
                name="weight",
                tensor_class="weight",
                initial=torch.ones(32, dtype=torch.bfloat16),
                gradient=torch.full((32,), 1.0e-12, dtype=torch.float32),
                required_survival=True,
            )
        ],
        optimizer_spec=adamw,
        treatment_dtype=torch.bfloat16,
        step_counts=(1,),
        class_survival_floors={"weight": 0.01},
        gradient_source={"kind": "synthetic", "source_id": "decay-confound-v1"},
    )
    bitnet = run_update_survival_preflight(
        probes=_selftest_bitnet_probes(),
        optimizer_spec=_selftest_sgd_spec(),
        treatment_dtype=torch.bfloat16,
        step_counts=(1,),
        class_survival_floors={"weight": 0.9, "norm_scale": 0.01},
        gradient_source={"kind": "synthetic", "source_id": "bitnet-15-of-24"},
    )
    fp32 = run_update_survival_preflight(
        probes=_selftest_bitnet_probes(),
        optimizer_spec=_selftest_sgd_spec(),
        treatment_dtype=torch.float32,
        step_counts=(1, 3),
        class_survival_floors={"weight": 0.9, "norm_scale": 0.9},
        gradient_source={"kind": "synthetic", "source_id": "bitnet-fp32-master"},
    )
    adafactor = run_update_survival_preflight(
        probes=[
            TensorProbe(
                name="gate_proj.weight",
                tensor_class="weight",
                initial=torch.ones((4, 4), dtype=torch.bfloat16),
                gradient=torch.full((4, 4), 1.0e-2, dtype=torch.float32),
                required_survival=True,
            )
        ],
        optimizer_spec=OptimizerSpec(
            family="adafactor",
            kwargs={
                "lr": 0.01,
                "beta2_decay": -0.8,
                "eps": (None, 0.001),
                "d": 1.0,
                "weight_decay": 0.0,
                "foreach": False,
                "maximize": False,
            },
        ),
        treatment_dtype=torch.bfloat16,
        step_counts=(1,),
        class_survival_floors={"weight": 0.0},
        gradient_source={"kind": "captured", "source_id": "adafactor-eps-none"},
    )
    observed = {
        "weight-decay-causal-confound": decay,
        "bitnet-15-of-24-bf16": bitnet,
        "bitnet-fp32-master": fp32,
        "adafactor-implicit-eps": adafactor,
    }
    expected = {
        "weight-decay-causal-confound": "PREFLIGHT_FAIL",
        "bitnet-15-of-24-bf16": "PREFLIGHT_FAIL",
        "bitnet-fp32-master": "PREFLIGHT_PASS",
        "adafactor-implicit-eps": "PREFLIGHT_INVALID",
    }
    cases = [
        {
            "case_id": case_id,
            "expected_verdict": expected[case_id],
            "observed_verdict": receipt["verdict"],
            "preflight_receipt_sha256": receipt["receipt_sha256"],
            "passed": receipt["verdict"] == expected[case_id],
        }
        for case_id, receipt in sorted(observed.items())
    ]
    receipt: dict[str, Any] = {
        "schema": "ember-update-survival-selftest/v1",
        "device": "cpu",
        "torch_version": torch.__version__,
        "cases": cases,
        "verdict": "SELFTEST_PASS"
        if all(case["passed"] for case in cases)
        else "SELFTEST_FAIL",
        "receipt_sha256": "",
    }
    receipt["receipt_sha256"] = _canonical_sha256(
        {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    )
    return receipt


def _write_json_atomic(path: Path, value: Mapping[str, Any]) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_name = handle.name
            json.dump(_jsonable(value), handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
        temporary_name = None
    finally:
        if temporary_name is not None:
            try:
                Path(temporary_name).unlink()
            except OSError:
                pass


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="CPU-safe gradient-causal update-survival preflight"
    )
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args(argv)
    if not args.selftest:
        parser.error("the CLI currently exposes only the governed CPU selftest")
    receipt = _run_cpu_selftest()
    _write_json_atomic(args.receipt, receipt)
    print(
        f"UPDATE_SURVIVAL_{receipt['verdict']} "
        f"receipt_sha256={receipt['receipt_sha256']}"
    )
    return 0 if receipt["verdict"] == "SELFTEST_PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
