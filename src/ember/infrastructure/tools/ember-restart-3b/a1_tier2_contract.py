# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Closed Tier-2 mechanism contract and allocation-free resource admission."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
from typing import Mapping

from a1_dense import require_clean_a1_lineage


_TOP = {
    "goal_id", "workstream_id", "next_executed_outcome", "schema_version",
    "tier", "mechanism", "architecture_revision", "state", "projection",
    "quantization", "optimizer", "determinism", "lineage", "resource_policy",
}
_STATE = {"persistent_device", "cpu_offload", "full_model_gradient_residency", "master_weight_copy"}
_PROJECTION = {
    "max_rank_policy", "max_rank", "refresh_gap_steps", "scale",
    "direction_policy", "small_parameter_policy", "moment_refresh_policy",
}
_QUANTIZATION = {
    "projector_format", "first_moment_format", "second_moment_format",
    "block_size", "scale_dtype", "zero_block_scale",
}
_OPTIMIZER = {"implementation", "state_format", "hyperparameters"}
_HYPERPARAMETERS = {"learning_rate", "betas", "epsilon", "weight_decay"}
_DETERMINISM = {
    "svd_dtype", "algorithms_required", "sign_policy",
    "random_or_stale_fallback", "registration_order_bound",
}
_RESOURCE = {
    "gpu_free_margin_bytes", "b_custody_floor_bytes",
    "checkpoint_transient_reserve_bytes", "svd_workspace_multiplier",
}


def _closed(value: object, fields: set[str], label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ValueError(f"Tier-2 {label} has an invalid closed schema")
    return value


def _exact_number(value: object, expected: float, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ValueError(f"Tier-2 {label} is invalid")
    if float(value) != expected:
        raise ValueError(f"Tier-2 {label} drifted")
    return float(value)


@dataclass(frozen=True)
class Tier2Contract:
    tier: str
    mechanism: str
    architecture_revision: str
    persistent_state_device: str
    cpu_offload: bool
    max_rank: int
    refresh_gap: int
    projection_scale: float
    moment_refresh_policy: str
    projector_format: str
    first_moment_format: str
    second_moment_format: str
    block_size: int
    learning_rate: float
    betas: tuple[float, float]
    epsilon: float
    weight_decay: float
    state_format: str
    deterministic_svd: bool
    random_or_stale_fallback: bool
    gpu_free_margin_bytes: int
    b_custody_floor_bytes: int
    checkpoint_transient_reserve_bytes: int
    svd_workspace_multiplier: int


def load_tier2_contract(path: str | Path | None = None) -> Tier2Contract:
    contract_path = Path(path) if path is not None else Path(__file__).with_name("ember-restart-3b-a1-tier2.json")
    try:
        payload = json.loads(contract_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("Tier-2 contract is unavailable or invalid") from error
    top = _closed(payload, _TOP, "contract")
    if (
        top["goal_id"] != "EMBER-02"
        or top["workstream_id"] != "EMBER-02B"
        or top["next_executed_outcome"] != "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember"
        or top["schema_version"] != "ember-restart-3b-a1-tier2-v1"
        or top["tier"] != "TIER_2"
        or top["mechanism"] != "OWNED_Q_GALORE_PROJECTED_GRADIENT"
        or top["architecture_revision"] != "ember-dense-a1-3b-v1"
    ):
        raise ValueError("Tier-2 contract identity drifted")
    require_clean_a1_lineage(top["lineage"])
    state = _closed(top["state"], _STATE, "state")
    if state != {
        "persistent_device": "cuda",
        "cpu_offload": False,
        "full_model_gradient_residency": False,
        "master_weight_copy": False,
    }:
        raise ValueError("Tier-2 state placement drifted")
    projection = _closed(top["projection"], _PROJECTION, "projection")
    if (
        projection["max_rank_policy"] != "min(512,min(parameter.shape))"
        or projection["max_rank"] != 512
        or projection["refresh_gap_steps"] != 200
        or projection["scale"] != 0.25
        or projection["direction_policy"] != "smaller_dimension"
        or projection["small_parameter_policy"] != "unprojected_block_quantized"
        or projection["moment_refresh_policy"] != "carry_quantized_moments_without_reset_or_reprojection"
    ):
        raise ValueError("Tier-2 projection contract drifted")
    quantization = _closed(top["quantization"], _QUANTIZATION, "quantization")
    if quantization != {
        "projector_format": "SIGNED_INT4_SYMMETRIC",
        "first_moment_format": "SIGNED_INT8_SYMMETRIC",
        "second_moment_format": "UNSIGNED_UINT8",
        "block_size": 256,
        "scale_dtype": "FP32",
        "zero_block_scale": 1,
    }:
        raise ValueError("Tier-2 quantization contract drifted")
    optimizer = _closed(top["optimizer"], _OPTIMIZER, "optimizer")
    if (
        optimizer["implementation"] != "owned.ProjectedQuantizedAdamWCUDA"
        or optimizer["state_format"] != "ember-a1-tier2-q-galore-cuda-v1"
    ):
        raise ValueError("Tier-2 optimizer identity drifted")
    hyper = _closed(optimizer["hyperparameters"], _HYPERPARAMETERS, "hyperparameters")
    betas = hyper["betas"]
    if not isinstance(betas, list) or len(betas) != 2:
        raise ValueError("Tier-2 betas are invalid")
    learning_rate = _exact_number(hyper["learning_rate"], 0.00001, "learning rate")
    beta1 = _exact_number(betas[0], 0.9, "beta1")
    beta2 = _exact_number(betas[1], 0.999, "beta2")
    epsilon = _exact_number(hyper["epsilon"], 1e-8, "epsilon")
    weight_decay = _exact_number(hyper["weight_decay"], 0.01, "weight decay")
    determinism = _closed(top["determinism"], _DETERMINISM, "determinism")
    if determinism != {
        "svd_dtype": "FP32",
        "algorithms_required": True,
        "sign_policy": "largest_magnitude_element_positive",
        "random_or_stale_fallback": False,
        "registration_order_bound": True,
    }:
        raise ValueError("Tier-2 deterministic policy drifted")
    resource = _closed(top["resource_policy"], _RESOURCE, "resource policy")
    expected_resource = {
        "gpu_free_margin_bytes": 4 * 1024**3,
        "b_custody_floor_bytes": 250 * 1024**3,
        "checkpoint_transient_reserve_bytes": 8 * 1024**3,
        "svd_workspace_multiplier": 4,
    }
    if resource != expected_resource:
        raise ValueError("Tier-2 resource policy drifted")
    return Tier2Contract(
        tier="TIER_2",
        mechanism="OWNED_Q_GALORE_PROJECTED_GRADIENT",
        architecture_revision="ember-dense-a1-3b-v1",
        persistent_state_device="cuda",
        cpu_offload=False,
        max_rank=512,
        refresh_gap=200,
        projection_scale=0.25,
        moment_refresh_policy="carry_quantized_moments_without_reset_or_reprojection",
        projector_format="SIGNED_INT4_SYMMETRIC",
        first_moment_format="SIGNED_INT8_SYMMETRIC",
        second_moment_format="UNSIGNED_UINT8",
        block_size=256,
        learning_rate=learning_rate,
        betas=(beta1, beta2),
        epsilon=epsilon,
        weight_decay=weight_decay,
        state_format=optimizer["state_format"],
        deterministic_svd=True,
        random_or_stale_fallback=False,
        **expected_resource,
    )


def numel(shape: tuple[int, ...]) -> int:
    if not isinstance(shape, tuple) or not shape or any(type(value) is not int or value < 1 for value in shape):
        raise ValueError("Tier-2 parameter shape is invalid")
    return math.prod(shape)


def _blocks(elements: int, block_size: int) -> int:
    return (elements + block_size - 1) // block_size


def derive_tier2_resource_inventory(
    parameter_shapes: Mapping[str, tuple[int, ...]],
    *,
    contract: Tier2Contract,
) -> dict[str, int | str]:
    if not isinstance(parameter_shapes, Mapping) or not parameter_shapes:
        raise ValueError("Tier-2 parameter inventory is empty")
    if any(not isinstance(name, str) or not name for name in parameter_shapes):
        raise ValueError("Tier-2 parameter name is invalid")
    parameter_count = 0
    maximum_gradient = 0
    moment_payload = 0
    moment_scales = 0
    projector_payload = 0
    projector_scales = 0
    workspace = 0
    for name in sorted(parameter_shapes):
        shape = parameter_shapes[name]
        elements = numel(shape)
        parameter_count += elements
        maximum_gradient = max(maximum_gradient, elements * 4)
        basis_elements = 0
        if len(shape) == 2 and min(shape) > contract.max_rank:
            rank = min(contract.max_rank, min(shape))
            moment_elements = max(shape) * rank
            basis_elements = min(shape) * rank
        else:
            moment_elements = elements
        moment_payload += moment_elements * 2
        moment_scales += _blocks(moment_elements, contract.block_size) * 4 * 2
        projector_payload += (basis_elements + 1) // 2
        projector_scales += _blocks(basis_elements, contract.block_size) * 4 if basis_elements else 0
        workspace = max(
            workspace,
            (elements + 3 * moment_elements + basis_elements) * 4 * contract.svd_workspace_multiplier,
        )
    model_bytes = parameter_count * 2
    persistent_state = moment_payload + moment_scales + projector_payload + projector_scales
    checkpoint_payload = model_bytes + persistent_state
    required_device = (
        model_bytes
        + persistent_state
        + maximum_gradient
        + workspace
        + contract.gpu_free_margin_bytes
    )
    required_custody = (
        contract.b_custody_floor_bytes
        + checkpoint_payload
        + contract.checkpoint_transient_reserve_bytes
    )
    return {
        "schema_version": "ember-a1-tier2-resource-inventory-v1",
        "parameter_count": parameter_count,
        "model_bf16_bytes": model_bytes,
        "max_single_full_gradient_bytes": maximum_gradient,
        "moment_payload_bytes": moment_payload,
        "moment_scale_bytes": moment_scales,
        "projector_payload_bytes": projector_payload,
        "projector_scale_bytes": projector_scales,
        "svd_workspace_reserve_bytes": workspace,
        "checkpoint_payload_bytes": checkpoint_payload,
        "checkpoint_transient_reserve_bytes": contract.checkpoint_transient_reserve_bytes,
        "gpu_free_margin_bytes": contract.gpu_free_margin_bytes,
        "b_custody_floor_bytes": contract.b_custody_floor_bytes,
        "required_device_bytes": required_device,
        "required_custody_bytes": required_custody,
        "cpu_persistent_state_bytes": 0,
        "host_full_gradient_bytes": 0,
        "host_master_weight_bytes": 0,
    }


def admit_tier2_resources(
    inventory: Mapping[str, int | str],
    *,
    available_device_bytes: int,
    custody_free_bytes: int,
    contract: Tier2Contract,
) -> dict[str, int | str]:
    if (
        not isinstance(inventory, Mapping)
        or inventory.get("schema_version") != "ember-a1-tier2-resource-inventory-v1"
        or inventory.get("cpu_persistent_state_bytes") != 0
        or inventory.get("host_full_gradient_bytes") != 0
        or inventory.get("host_master_weight_bytes") != 0
    ):
        raise ValueError("Tier-2 resource inventory is invalid")
    if type(available_device_bytes) is not int or available_device_bytes < inventory["required_device_bytes"]:
        raise MemoryError("Tier-2 CUDA free bytes are below the certified requirement")
    if type(custody_free_bytes) is not int or custody_free_bytes < inventory["required_custody_bytes"]:
        raise MemoryError("Tier-2 custody free bytes would violate the B: floor")
    return {
        "schema_version": "ember-a1-tier2-resource-preflight-v1",
        "status": "PASS",
        **{key: value for key, value in inventory.items() if key != "schema_version"},
        "available_device_bytes": available_device_bytes,
        "custody_free_bytes": custody_free_bytes,
        "persistent_state_device": contract.persistent_state_device,
    }
