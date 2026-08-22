# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import importlib
from pathlib import Path
import sys

import pytest
import torch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "ember-restart-3b"))


def _module():
    return importlib.import_module("a1_tier2_optimizer")


@pytest.mark.parametrize(
    ("format_name", "values", "tolerance"),
    [
        ("SIGNED_INT4_SYMMETRIC", torch.linspace(-3.0, 3.0, 513), 0.22),
        ("SIGNED_INT8_SYMMETRIC", torch.linspace(-3.0, 3.0, 513), 0.013),
        ("UNSIGNED_UINT8", torch.linspace(0.0, 3.0, 513), 0.007),
    ],
)
def test_block_quantization_round_trip_and_partial_block(
    format_name: str,
    values: torch.Tensor,
    tolerance: float,
) -> None:
    module = _module()
    record = module.quantize_blocks(values.reshape(9, 57), format_name, block_size=256)
    restored = module.dequantize_blocks(record)
    assert restored.shape == (9, 57)
    assert restored.dtype is torch.float32
    assert torch.max(torch.abs(restored - values.reshape(9, 57))).item() <= tolerance
    assert record.scales.dtype is torch.float32
    assert record.scales.numel() == 3


@pytest.mark.parametrize(
    ("format_name", "payload_dtype"),
    [
        ("SIGNED_INT4_SYMMETRIC", torch.uint8),
        ("SIGNED_INT8_SYMMETRIC", torch.int8),
        ("UNSIGNED_UINT8", torch.uint8),
    ],
)
def test_zero_blocks_have_scale_one_and_zero_payload(
    format_name: str,
    payload_dtype: torch.dtype,
) -> None:
    module = _module()
    record = module.quantize_blocks(torch.zeros(257), format_name, block_size=256)
    assert torch.equal(record.scales, torch.ones(2, dtype=torch.float32))
    assert record.payload.dtype is payload_dtype
    assert not torch.count_nonzero(record.payload)
    assert torch.equal(module.dequantize_blocks(record), torch.zeros(257))


def test_signed_int4_packing_is_deterministic_for_odd_numel() -> None:
    module = _module()
    values = torch.tensor([-7.0, -1.0, 0.0, 1.0, 7.0])
    first = module.quantize_blocks(values, "SIGNED_INT4_SYMMETRIC", block_size=256)
    second = module.quantize_blocks(values.clone(), "SIGNED_INT4_SYMMETRIC", block_size=256)
    assert first.payload.tolist() == second.payload.tolist()
    assert first.payload.numel() == 3
    assert first.payload[-1].item() >> 4 == 0


@pytest.mark.parametrize(
    "values",
    [torch.tensor([float("nan")]), torch.tensor([float("inf")]), torch.tensor([-1.0])],
)
def test_quantization_refuses_nonfinite_or_negative_unsigned(values: torch.Tensor) -> None:
    module = _module()
    format_name = "UNSIGNED_UINT8" if values.item() == -1.0 else "SIGNED_INT8_SYMMETRIC"
    with pytest.raises(ValueError):
        module.quantize_blocks(values, format_name, block_size=256)


def _largest_magnitude_entries_are_nonnegative(basis: torch.Tensor, direction: str) -> bool:
    vectors = basis if direction == "RIGHT" else basis.transpose(0, 1)
    for vector in vectors:
        index = int(torch.argmax(torch.abs(vector)).item())
        if vector[index].item() < 0:
            return False
    return True


@pytest.mark.parametrize(
    ("shape", "direction", "basis_shape", "projected_shape"),
    [
        ((7, 5), "RIGHT", (2, 5), (7, 2)),
        ((5, 7), "LEFT", (5, 2), (2, 7)),
    ],
)
def test_deterministic_projection_direction_shape_and_canonical_sign(
    shape: tuple[int, int],
    direction: str,
    basis_shape: tuple[int, int],
    projected_shape: tuple[int, int],
) -> None:
    module = _module()
    gradient = torch.arange(1, shape[0] * shape[1] + 1, dtype=torch.float32).reshape(shape)
    first = module.build_projection(gradient, max_rank=2)
    second = module.build_projection(gradient.clone(), max_rank=2)
    assert first.direction == direction
    assert tuple(first.basis.shape) == basis_shape
    assert tuple(first.projected_gradient.shape) == projected_shape
    assert torch.equal(first.basis, second.basis)
    assert torch.equal(first.projected_gradient, second.projected_gradient)
    assert _largest_magnitude_entries_are_nonnegative(first.basis, direction)


@pytest.mark.parametrize("shape", [(7,), (2, 7), (7, 2), (2, 2)])
def test_unreduced_shapes_do_not_invent_a_projection(shape: tuple[int, ...]) -> None:
    module = _module()
    gradient = torch.ones(shape, dtype=torch.float32)
    projection = module.build_projection(gradient, max_rank=2)
    assert projection.direction == "UNPROJECTED"
    assert projection.basis is None
    assert torch.equal(projection.projected_gradient, gradient)


def test_reconstruction_uses_the_declared_projection_direction() -> None:
    module = _module()
    tall = torch.arange(1, 36, dtype=torch.float32).reshape(7, 5)
    wide = tall.transpose(0, 1).contiguous()
    for gradient in (tall, wide):
        projection = module.build_projection(gradient, max_rank=2)
        rebuilt = module.reconstruct_projection(
            projection.projected_gradient,
            projection.basis,
            projection.direction,
        )
        assert rebuilt.shape == gradient.shape
        assert torch.isfinite(rebuilt).all()


@pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA-only Tier-2 state")
def test_projected_optimizer_updates_all_used_parameters_on_cuda_and_frees_gradients() -> None:
    module = _module()
    previous = torch.are_deterministic_algorithms_enabled()
    torch.use_deterministic_algorithms(True)
    parameters = [
        ("matrix", torch.nn.Parameter(torch.arange(35, device="cuda", dtype=torch.float32).reshape(7, 5))),
        ("bias", torch.nn.Parameter(torch.ones(5, device="cuda", dtype=torch.float32))),
    ]
    contract = module.Tier2OptimizerContract.for_tests(max_rank=2, refresh_gap=2)
    optimizer = module.ProjectedQuantizedAdamWCUDA(parameters, contract=contract)
    optimizer.initialize_state()
    optimizer.enable_fused_backward()

    try:
        before = {name: parameter.detach().clone() for name, parameter in parameters}
        loss = sum(parameter.square().sum() for _, parameter in parameters)
        loss.backward()
        optimizer.step()
        norm = optimizer.finish_gradient_norm()

        assert norm > 0
        assert all(parameter.grad is None for _, parameter in parameters)
        assert all(not torch.equal(parameter, before[name]) for name, parameter in parameters)
        inventory = optimizer.state_inventory()
        assert inventory["complete"] is True
        assert inventory["persistent_state_device"] == "cuda"
        assert inventory["cpu_persistent_state_bytes"] == 0
        assert optimizer.state[parameters[0][1]]["refresh_ordinal"] == 1
    finally:
        torch.use_deterministic_algorithms(previous)


@pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA-only Tier-2 state")
def test_projected_optimizer_refreshes_at_step_one_and_exact_gap_only() -> None:
    module = _module()
    previous = torch.are_deterministic_algorithms_enabled()
    torch.use_deterministic_algorithms(True)
    parameter = torch.nn.Parameter(torch.randn(7, 5, device="cuda"))
    optimizer = module.ProjectedQuantizedAdamWCUDA(
        [("matrix", parameter)],
        contract=module.Tier2OptimizerContract.for_tests(max_rank=2, refresh_gap=2),
    )
    optimizer.initialize_state()
    try:
        for expected_ordinal in (1, 2, 2):
            parameter.grad = torch.ones_like(parameter)
            optimizer.step()
            optimizer.finish_gradient_norm()
            assert optimizer.state[parameter]["refresh_ordinal"] == expected_ordinal
    finally:
        torch.use_deterministic_algorithms(previous)


@pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA-only Tier-2 state")
def test_refresh_step_uses_the_persisted_int4_basis_coordinates() -> None:
    module = _module()
    previous = torch.are_deterministic_algorithms_enabled()
    torch.use_deterministic_algorithms(True)
    parameter = torch.nn.Parameter(torch.arange(35, device="cuda", dtype=torch.float32).reshape(7, 5))
    optimizer = module.ProjectedQuantizedAdamWCUDA(
        [("matrix", parameter)],
        contract=module.Tier2OptimizerContract.for_tests(max_rank=2, refresh_gap=2),
    )
    optimizer.initialize_state()
    gradient = torch.linspace(-2.0, 3.0, 35, device="cuda", dtype=torch.float32).reshape(7, 5)
    parameter.grad = gradient.clone()
    try:
        optimizer.step()
        optimizer.finish_gradient_norm()
        state = optimizer.state[parameter]
        persisted_basis = module.dequantize_blocks(state["basis"])
        projected = gradient @ persisted_basis.transpose(0, 1)
        expected = module.quantize_blocks(
            projected * (1.0 - optimizer.param_groups[0]["betas"][0]),
            module.SIGNED_INT8,
            block_size=optimizer.contract.block_size,
        )
        assert torch.equal(state["exp_avg"].payload, expected.payload)
        assert torch.equal(state["exp_avg"].scales, expected.scales)
    finally:
        torch.use_deterministic_algorithms(previous)
