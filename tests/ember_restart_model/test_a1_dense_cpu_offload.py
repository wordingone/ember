# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Packet B1 tests for the A1 dense comparator and Tier-1 optimizer."""

from __future__ import annotations

import importlib
import copy
import json
import sys
import tempfile
from pathlib import Path

import pytest
import torch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "ember-restart-3b"))


def test_tier_mechanism_mismatch_has_a_closed_typed_refusal() -> None:
    """A free-form tier/mechanism pair must never select an unintended route."""

    dense = importlib.import_module("a1_dense")
    with pytest.raises(dense.A1Refusal) as caught:
        dense.require_tier_mechanism(
            dense.A1Tier.TIER_1,
            dense.A1Mechanism.OWNED_Q_GALORE_PROJECTED_GRADIENT,
        )
    assert caught.value.code is dense.A1RefusalCode.A1_TIER_MECHANISM_MISMATCH


def test_production_dense_contract_is_over_three_billion_and_has_no_experts() -> None:
    dense = importlib.import_module("a1_dense")
    sparse_model = importlib.import_module("model")
    config = dense.DenseA1Config.from_contract()
    assert config.structural_parameter_count() == 3_839_344_640
    assert config.declared_total_unique_trainable_parameters == 3_839_344_640
    model = dense.DenseA1Decoder(config, device="meta")
    assert sum(parameter.numel() for parameter in model.parameters()) == 3_839_344_640
    assert all("expert" not in name for name, _module in model.named_modules())
    assert all("expert" not in name for name, _parameter in model.named_parameters())
    assert any(type(module) is dense.DenseSwiGLU for module in model.modules())
    assert all(type(module) is not sparse_model.SwiGLUExpert for module in model.modules())
    assert all(not isinstance(module, sparse_model.SwiGLUExpert) for module in model.modules())
    assert not issubclass(dense.DenseSwiGLU, sparse_model.SwiGLUExpert)
    assert all(not isinstance(module, torch.nn.ModuleDict) for module in model.modules())


def test_owned_dense_swiglu_is_forward_equivalent_with_identical_weights() -> None:
    dense = importlib.import_module("a1_dense")
    sparse_model = importlib.import_module("model")
    torch.manual_seed(24164)
    owned = dense.DenseSwiGLU(32)
    reference = sparse_model.SwiGLUExpert(32)
    reference.load_state_dict(copy.deepcopy(owned.state_dict()))
    hidden_states = torch.randn(2, 5, 32)
    owned_output = owned(hidden_states)
    reference_output = reference(hidden_states)
    assert torch.equal(owned_output, reference_output)
    assert owned_output.detach().numpy().tobytes() == reference_output.detach().numpy().tobytes()


def test_dense_contract_refuses_bool_parameter_count_with_typed_code() -> None:
    dense = importlib.import_module("a1_dense")
    contract_path = ROOT / "tools" / "ember-restart-3b" / "ember-restart-3b-a1.json"
    payload = json.loads(contract_path.read_text(encoding="utf-8"))
    payload["model"]["total_unique_trainable_parameters"] = True
    with tempfile.TemporaryDirectory() as directory:
        candidate = Path(directory) / "a1.json"
        candidate.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(dense.A1Refusal) as caught:
            dense.DenseA1Config.from_contract(candidate)
    assert caught.value.code is dense.A1RefusalCode.A1_PARAMETER_COUNT_TYPE_INVALID


@pytest.mark.parametrize("value", [False, "disabled"])
def test_dense_contract_refuses_non_true_gradient_checkpointing(value: object) -> None:
    dense = importlib.import_module("a1_dense")
    contract_path = ROOT / "tools" / "ember-restart-3b" / "ember-restart-3b-a1.json"
    payload = json.loads(contract_path.read_text(encoding="utf-8"))
    payload["model"]["gradient_checkpointing"] = value
    with tempfile.TemporaryDirectory() as directory:
        candidate = Path(directory) / "a1.json"
        candidate.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(dense.A1Refusal) as caught:
            dense.DenseA1Config.from_contract(candidate, repo_root=ROOT)
    assert caught.value.code is dense.A1RefusalCode.A1_PARAMETER_INVENTORY_MISMATCH


def test_dense_contract_reopens_and_hash_binds_canonical_thresholds() -> None:
    dense = importlib.import_module("a1_dense")
    config = dense.DenseA1Config.from_contract()
    assert config.t08_liveness_floor == "0.33"
    assert config.t09_matched_steps == 100
    assert config.t20_sigma_multiplier == "2"

    contract_path = ROOT / "tools" / "ember-restart-3b" / "ember-restart-3b-a1.json"
    payload = json.loads(contract_path.read_text(encoding="utf-8"))
    payload["thresholds"]["sha256"] = "0" * 64
    with tempfile.TemporaryDirectory() as directory:
        candidate = Path(directory) / "a1.json"
        candidate.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(dense.A1Refusal) as caught:
            dense.DenseA1Config.from_contract(candidate, repo_root=ROOT)
    assert caught.value.code is dense.A1RefusalCode.A1_THRESHOLD_DOC_SHA_MISMATCH


def test_dense_contract_refuses_divergent_nested_authority_binding() -> None:
    dense = importlib.import_module("a1_dense")
    contract_path = ROOT / "tools" / "ember-restart-3b" / "ember-restart-3b-a1.json"
    payload = json.loads(contract_path.read_text(encoding="utf-8"))
    payload["authority"]["next_executed_outcome"] = "different outcome"
    with tempfile.TemporaryDirectory() as directory:
        candidate = Path(directory) / "a1.json"
        candidate.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(dense.A1Refusal) as caught:
            dense.DenseA1Config.from_contract(candidate, repo_root=ROOT)
    assert caught.value.code is dense.A1RefusalCode.A1_PARAMETER_INVENTORY_MISMATCH


def test_dense_and_optimizer_contracts_refuse_borrowed_lineage() -> None:
    dense = importlib.import_module("a1_dense")
    optimizer_module = importlib.import_module("a1_optimizer")
    contract_path = ROOT / "tools" / "ember-restart-3b" / "ember-restart-3b-a1.json"
    payload = json.loads(contract_path.read_text(encoding="utf-8"))
    payload["lineage"]["borrowed_weights"] = True
    with tempfile.TemporaryDirectory() as directory:
        candidate = Path(directory) / "a1.json"
        candidate.write_text(json.dumps(payload), encoding="utf-8")
        for loader in (
            lambda: dense.DenseA1Config.from_contract(candidate, repo_root=ROOT),
            lambda: optimizer_module.load_a1_optimizer_contract(candidate),
        ):
            with pytest.raises(dense.A1Refusal) as caught:
                loader()
            assert caught.value.code is dense.A1RefusalCode.A1_PARAMETER_INVENTORY_MISMATCH


def test_both_consumers_refuse_well_formed_a1_config_byte_drift() -> None:
    dense = importlib.import_module("a1_dense")
    optimizer_module = importlib.import_module("a1_optimizer")
    contract_path = ROOT / "tools" / "ember-restart-3b" / "ember-restart-3b-a1.json"
    payload = json.loads(contract_path.read_text(encoding="utf-8"))
    payload["training_state"]["optimizer"]["hyperparameters"]["learning_rate"] = 0.00002
    with tempfile.TemporaryDirectory() as directory:
        candidate = Path(directory) / "a1.json"
        candidate.write_text(json.dumps(payload), encoding="utf-8")
        for loader in (
            lambda: dense.DenseA1Config.from_contract(candidate, repo_root=ROOT),
            lambda: optimizer_module.load_a1_optimizer_contract(candidate),
        ):
            with pytest.raises(dense.A1Refusal) as caught:
                loader()
            assert caught.value.code is dense.A1RefusalCode.A1_CONFIG_SHA_MISMATCH


def test_small_dense_forward_is_full_parameter_text_path() -> None:
    dense = importlib.import_module("a1_dense")
    config = dense.DenseA1Config.small_for_tests()
    model = dense.DenseA1Decoder(config)
    logits = model(torch.tensor([[1, 2, 3, 4]]))
    assert logits.shape == (1, 4, config.vocab_size)
    logits.square().mean().backward()
    layer_parameters = [
        parameter
        for name, parameter in model.named_parameters()
        if name.startswith("layers.")
    ]
    assert layer_parameters
    assert all(parameter.grad is not None for parameter in layer_parameters)


def test_cpu_offload_state_is_complete_fp32_and_covers_every_parameter() -> None:
    optimizer_module = importlib.import_module("a1_optimizer")
    first = torch.nn.Parameter(torch.tensor([1.0, -2.0], dtype=torch.bfloat16))
    second = torch.nn.Parameter(torch.tensor([[3.0]], dtype=torch.bfloat16))
    optimizer = optimizer_module.FullStateAdamWCPUOffload(
        [first, second],
        contract=optimizer_module.load_a1_optimizer_contract(),
    )
    optimizer.initialize_state()
    inventory = optimizer.state_inventory()
    assert inventory == {
        "schema_version": "ember-a1-adamw-state-inventory-v1",
        "state_format": "ember-a1-full-state-adamw-cpu-offload-v1",
        "registered_parameters": 2,
        "registered_numel": 3,
        "initialized_parameters": 2,
        "cpu_fp32_master_numel": 3,
        "cpu_fp32_first_moment_numel": 3,
        "cpu_fp32_second_moment_numel": 3,
        "complete": True,
    }
    for parameter in (first, second):
        state = optimizer.state[parameter]
        assert state["step"] == 0
        for field in ("master_copy", "exp_avg", "exp_avg_sq"):
            assert state[field].device.type == "cpu"
            assert state[field].dtype is torch.float32
            assert state[field].shape == parameter.shape


def test_cpu_offload_adamw_matches_float32_reference_math() -> None:
    optimizer_module = importlib.import_module("a1_optimizer")
    candidate = torch.nn.Parameter(torch.tensor([1.25, -0.75], dtype=torch.float32))
    reference = torch.nn.Parameter(candidate.detach().clone())
    contract = optimizer_module.load_a1_optimizer_contract()
    optimizer = optimizer_module.FullStateAdamWCPUOffload([candidate], contract=contract)
    optimizer.initialize_state()
    reference_optimizer = torch.optim.AdamW(
        [reference],
        lr=1e-5,
        betas=(0.9, 0.999),
        eps=1e-8,
        weight_decay=0.01,
        foreach=False,
    )
    for gradient in (
        torch.tensor([0.5, -0.25]),
        torch.tensor([-0.125, 0.75]),
    ):
        candidate.grad = gradient.clone()
        reference.grad = gradient.clone()
        optimizer.step()
        reference_optimizer.step()
    torch.testing.assert_close(candidate, reference, rtol=0, atol=1e-7)
    torch.testing.assert_close(
        optimizer.state[candidate]["exp_avg"],
        reference_optimizer.state[reference]["exp_avg"],
        rtol=0,
        atol=1e-7,
    )
    torch.testing.assert_close(
        optimizer.state[candidate]["exp_avg_sq"],
        reference_optimizer.state[reference]["exp_avg_sq"],
        rtol=0,
        atol=1e-7,
    )


def test_cpu_offload_step_refuses_partial_state_before_update() -> None:
    dense = importlib.import_module("a1_dense")
    optimizer_module = importlib.import_module("a1_optimizer")
    parameter = torch.nn.Parameter(torch.tensor([1.0]))
    parameter.grad = torch.tensor([0.5])
    optimizer = optimizer_module.FullStateAdamWCPUOffload(
        [parameter],
        contract=optimizer_module.load_a1_optimizer_contract(),
    )
    with pytest.raises(dense.A1Refusal) as caught:
        optimizer.step()
    assert caught.value.code is dense.A1RefusalCode.A1_OPTIMIZER_STATE_INCOMPLETE
    assert parameter.item() == 1.0


def test_optimizer_contract_refuses_non_numeric_bool_hyperparameter() -> None:
    dense = importlib.import_module("a1_dense")
    optimizer_module = importlib.import_module("a1_optimizer")
    contract_path = ROOT / "tools" / "ember-restart-3b" / "ember-restart-3b-a1.json"
    payload = json.loads(contract_path.read_text(encoding="utf-8"))
    payload["training_state"]["optimizer"]["hyperparameters"]["learning_rate"] = True
    with tempfile.TemporaryDirectory() as directory:
        candidate = Path(directory) / "a1.json"
        candidate.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(dense.A1Refusal) as caught:
            optimizer_module.load_a1_optimizer_contract(candidate)
    assert caught.value.code is dense.A1RefusalCode.A1_OPTIMIZER_CONTRACT_INVALID


def test_cpu_offload_state_load_is_atomic_and_refuses_missing_moment() -> None:
    dense = importlib.import_module("a1_dense")
    optimizer_module = importlib.import_module("a1_optimizer")
    source_parameter = torch.nn.Parameter(torch.tensor([1.0, 2.0]))
    source = optimizer_module.FullStateAdamWCPUOffload(
        [source_parameter],
        contract=optimizer_module.load_a1_optimizer_contract(),
    )
    source.initialize_state()
    source_parameter.grad = torch.tensor([0.25, -0.5])
    source.step()
    tampered = copy.deepcopy(source.state_dict())
    del next(iter(tampered["state"].values()))["exp_avg_sq"]

    target_parameter = torch.nn.Parameter(torch.tensor([9.0, 9.0]))
    target = optimizer_module.FullStateAdamWCPUOffload(
        [target_parameter],
        contract=optimizer_module.load_a1_optimizer_contract(),
    )
    with pytest.raises(dense.A1Refusal) as caught:
        target.load_state_dict(tampered)
    assert caught.value.code is dense.A1RefusalCode.A1_OPTIMIZER_STATE_INCOMPLETE
    assert target.state == {}


def test_cpu_offload_state_load_refuses_duplicate_serialized_parameter_ids() -> None:
    dense = importlib.import_module("a1_dense")
    optimizer_module = importlib.import_module("a1_optimizer")
    source_parameter = torch.nn.Parameter(torch.tensor([1.0]))
    source = optimizer_module.FullStateAdamWCPUOffload(
        [source_parameter],
        contract=optimizer_module.load_a1_optimizer_contract(),
    )
    source.initialize_state()
    forged = copy.deepcopy(source.state_dict())
    forged["param_groups"][0]["params"] = [0, 0]

    target = optimizer_module.FullStateAdamWCPUOffload(
        [
            torch.nn.Parameter(torch.tensor([2.0])),
            torch.nn.Parameter(torch.tensor([3.0])),
        ],
        contract=optimizer_module.load_a1_optimizer_contract(),
    )
    with pytest.raises(dense.A1Refusal) as caught:
        target.load_state_dict(forged)
    assert caught.value.code is dense.A1RefusalCode.A1_OPTIMIZER_STATE_INCOMPLETE
    assert target.state == {}


def test_cpu_offload_state_round_trip_preserves_cpu_fp32_master_and_moments() -> None:
    optimizer_module = importlib.import_module("a1_optimizer")
    source_parameter = torch.nn.Parameter(torch.tensor([1.0, 2.0]))
    source = optimizer_module.FullStateAdamWCPUOffload(
        [source_parameter],
        contract=optimizer_module.load_a1_optimizer_contract(),
    )
    source.initialize_state()
    source_parameter.grad = torch.tensor([0.25, -0.5])
    source.step()

    target_parameter = torch.nn.Parameter(torch.tensor([0.0, 0.0]))
    target = optimizer_module.FullStateAdamWCPUOffload(
        [target_parameter],
        contract=optimizer_module.load_a1_optimizer_contract(),
    )
    target.load_state_dict(copy.deepcopy(source.state_dict()))
    assert target.state_inventory()["complete"] is True
    for field in ("master_copy", "exp_avg", "exp_avg_sq"):
        tensor = target.state[target_parameter][field]
        assert tensor.device.type == "cpu"
        assert tensor.dtype is torch.float32
        torch.testing.assert_close(tensor, source.state[source_parameter][field])
