# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import copy
import importlib
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools" / "ember-restart-3b"
sys.path.insert(0, str(TOOLS))


def _module():
    return importlib.import_module("a1_tier2_contract")


def test_canonical_tier2_contract_is_closed_and_exact() -> None:
    contract = _module().load_tier2_contract()
    assert contract.tier == "TIER_2"
    assert contract.mechanism == "OWNED_Q_GALORE_PROJECTED_GRADIENT"
    assert contract.persistent_state_device == "cuda"
    assert contract.cpu_offload is False
    assert contract.max_rank == 512
    assert contract.refresh_gap == 200
    assert contract.projection_scale == 0.25
    assert contract.moment_refresh_policy == "carry_quantized_moments_without_reset_or_reprojection"
    assert contract.projector_format == "SIGNED_INT4_SYMMETRIC"
    assert contract.first_moment_format == "SIGNED_INT8_SYMMETRIC"
    assert contract.second_moment_format == "UNSIGNED_UINT8"
    assert contract.block_size == 256
    assert contract.learning_rate == 0.00001
    assert contract.betas == (0.9, 0.999)
    assert contract.epsilon == 1e-8
    assert contract.weight_decay == 0.01
    assert contract.deterministic_svd is True
    assert contract.random_or_stale_fallback is False
    assert contract.b_custody_floor_bytes == 250 * 1024**3


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update({"extra": True}),
        lambda value: value["projection"].update({"rank": 511}),
        lambda value: value["quantization"].update({"block_size": 128}),
        lambda value: value["optimizer"]["hyperparameters"].update({"learning_rate": 2e-5}),
        lambda value: value["state"].update({"persistent_device": "cpu"}),
        lambda value: value["determinism"].update({"random_or_stale_fallback": True}),
    ],
)
def test_tier2_contract_refuses_schema_or_authority_drift(tmp_path: Path, mutation) -> None:
    payload = json.loads((TOOLS / "ember-restart-3b-a1-tier2.json").read_text(encoding="utf-8"))
    mutation(payload)
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError):
        _module().load_tier2_contract(path)


def test_resource_inventory_is_shape_derived_without_host_full_state() -> None:
    module = _module()
    contract = module.load_tier2_contract()
    shapes = {
        "tall": (1024, 1024),
        "wide": (513, 1025),
        "small": (64, 64),
        "bias": (1024,),
    }
    inventory = module.derive_tier2_resource_inventory(shapes, contract=contract)
    parameter_count = sum(module.numel(shape) for shape in shapes.values())
    assert inventory["parameter_count"] == parameter_count
    assert inventory["model_bf16_bytes"] == parameter_count * 2
    assert inventory["max_single_full_gradient_bytes"] == max(module.numel(shape) for shape in shapes.values()) * 4
    assert inventory["moment_payload_bytes"] > 0
    assert inventory["moment_scale_bytes"] > 0
    assert inventory["projector_payload_bytes"] > 0
    assert inventory["projector_scale_bytes"] > 0
    assert inventory["svd_workspace_reserve_bytes"] > 0
    assert inventory["checkpoint_payload_bytes"] > inventory["model_bf16_bytes"]
    assert inventory["cpu_persistent_state_bytes"] == 0
    assert inventory["host_full_gradient_bytes"] == 0
    assert inventory["host_master_weight_bytes"] == 0


def test_resource_inventory_is_seed_and_order_independent() -> None:
    module = _module()
    contract = module.load_tier2_contract()
    first = module.derive_tier2_resource_inventory(
        {"b": (1024,), "a": (1024, 1024)},
        contract=contract,
    )
    second = module.derive_tier2_resource_inventory(
        {"a": (1024, 1024), "b": (1024,)},
        contract=contract,
    )
    assert first == second


def test_resource_preflight_passes_only_with_cuda_margin_and_b_floor() -> None:
    module = _module()
    contract = module.load_tier2_contract()
    inventory = module.derive_tier2_resource_inventory({"matrix": (1024, 1024)}, contract=contract)
    required_device = inventory["required_device_bytes"]
    required_custody = inventory["required_custody_bytes"]
    receipt = module.admit_tier2_resources(
        inventory,
        available_device_bytes=required_device,
        custody_free_bytes=required_custody,
        contract=contract,
    )
    assert receipt["schema_version"] == "ember-a1-tier2-resource-preflight-v1"
    assert receipt["status"] == "PASS"
    assert receipt["cpu_persistent_state_bytes"] == 0

    with pytest.raises(MemoryError, match="CUDA"):
        module.admit_tier2_resources(
            inventory,
            available_device_bytes=required_device - 1,
            custody_free_bytes=required_custody,
            contract=contract,
        )
    with pytest.raises(MemoryError, match="custody"):
        module.admit_tier2_resources(
            inventory,
            available_device_bytes=required_device,
            custody_free_bytes=required_custody - 1,
            contract=contract,
        )
