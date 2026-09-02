# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import importlib
from pathlib import Path
import sys

import pytest
import torch

ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
sys.path.insert(0, str(ROOT / "tools" / "ember-restart-3b"))


def _module():
    return importlib.import_module("a1_tier2_optimizer")


def _legacy_quantize_blocks(module, value: torch.Tensor, format_name: str, block_size: int = 256):
    """Frozen pre-vectorization oracle for byte-identity regression coverage."""
    source = value.detach().to(dtype=torch.float32).contiguous().reshape(-1)
    quantized_parts: list[torch.Tensor] = []
    scales: list[torch.Tensor] = []
    for start in range(0, source.numel(), block_size):
        block = source[start:start + block_size]
        maximum = block.max() if format_name == module.UNSIGNED_UINT8 else block.abs().max()
        if maximum.item() == 0:
            scale = torch.ones((), device=source.device, dtype=torch.float32)
            quantized = torch.zeros_like(
                block,
                dtype=torch.uint8 if format_name == module.UNSIGNED_UINT8 else torch.int8,
            )
        else:
            divisor = (
                255.0
                if format_name == module.UNSIGNED_UINT8
                else (7.0 if format_name == module.SIGNED_INT4 else 127.0)
            )
            scale = maximum / divisor
            lower = 0 if format_name == module.UNSIGNED_UINT8 else (-7 if format_name == module.SIGNED_INT4 else -127)
            upper = 255 if format_name == module.UNSIGNED_UINT8 else (7 if format_name == module.SIGNED_INT4 else 127)
            dtype = torch.uint8 if format_name == module.UNSIGNED_UINT8 else torch.int8
            quantized = torch.round(block / scale).clamp(lower, upper).to(dtype=dtype)
        scales.append(scale)
        quantized_parts.append(quantized)
    unpacked = torch.cat(quantized_parts)
    if format_name == module.SIGNED_INT4:
        nibbles = torch.bitwise_and(unpacked.to(torch.int16), 15).to(torch.uint8)
        if nibbles.numel() % 2:
            nibbles = torch.cat((nibbles, torch.zeros(1, dtype=torch.uint8, device=nibbles.device)))
        payload = nibbles[0::2] | (nibbles[1::2] << 4)
    else:
        payload = unpacked
    return module.QuantizedTensor(
        format_name=format_name,
        block_size=block_size,
        shape=tuple(value.shape),
        numel=value.numel(),
        payload=payload.contiguous(),
        scales=torch.stack(scales).to(dtype=torch.float32),
    )


@pytest.mark.parametrize("device", ["cpu", "cuda"])
@pytest.mark.parametrize(
    "format_name",
    ["SIGNED_INT4_SYMMETRIC", "SIGNED_INT8_SYMMETRIC", "UNSIGNED_UINT8"],
)
def test_block_quantization_is_byte_identical_to_legacy_for_randomized_tails_and_zero_blocks(
    device: str,
    format_name: str,
) -> None:
    if device == "cuda" and not torch.cuda.is_available():
        pytest.skip("CUDA unavailable")
    module = _module()
    generator = torch.Generator(device="cpu").manual_seed(1464)
    for size in (1, 255, 257, 511, 513, 770):
        values = torch.randn(size, generator=generator, dtype=torch.float32)
        if format_name == module.UNSIGNED_UINT8:
            values = values.abs()
        if size >= 257:
            values[:256] = 0
        if size == 770:
            values[512:] = 0
        values = values.to(device)
        expected = _legacy_quantize_blocks(module, values, format_name)
        actual = module.quantize_blocks(values, format_name)
        assert actual.format_name == expected.format_name
        assert actual.block_size == expected.block_size
        assert actual.shape == expected.shape
        assert actual.numel == expected.numel
        assert torch.equal(actual.payload, expected.payload)
        assert torch.equal(actual.scales, expected.scales)


def test_block_quantization_host_sync_count_does_not_scale_with_block_count(monkeypatch) -> None:
    module = _module()
    original_item = torch.Tensor.item
    item_calls = 0

    def counted_item(tensor: torch.Tensor, *args):
        nonlocal item_calls
        item_calls += 1
        return original_item(tensor, *args)

    monkeypatch.setattr(torch.Tensor, "item", counted_item)
    module.quantize_blocks(torch.ones(1), module.SIGNED_INT8)
    one_block_calls = item_calls
    item_calls = 0
    module.quantize_blocks(torch.ones(1025), module.SIGNED_INT8)
    assert item_calls == one_block_calls


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
