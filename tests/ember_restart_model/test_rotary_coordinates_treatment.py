#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Exact semantics and gradient contract for the #1945 selected rotary treatment."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
import torch


MODEL_PATH = Path(__file__).parents[2] / "tools" / "ember-restart-3b" / "model.py"
SPEC = importlib.util.spec_from_file_location("issue1945_rotary_model", MODEL_PATH)
MODEL = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODEL
SPEC.loader.exec_module(MODEL)


def reference(values: torch.Tensor, coordinates: torch.Tensor) -> torch.Tensor:
    axis_dim = values.shape[-1] // 2
    chunks = values.split(axis_dim, dim=-1)
    rotated = []
    base = torch.arange(0, axis_dim, 2, device=values.device, dtype=torch.float32)
    frequencies = torch.pow(10000.0, -base / axis_dim)
    for axis, chunk in enumerate(chunks):
        angle = coordinates[..., axis].to(torch.float32).unsqueeze(-1) * frequencies
        cos = angle.cos().to(chunk.dtype).unsqueeze(1)
        sin = angle.sin().to(chunk.dtype).unsqueeze(1)
        even = chunk[..., 0::2]
        odd = chunk[..., 1::2]
        rotated_axis = torch.stack((even * cos - odd * sin, even * sin + odd * cos), dim=-1)
        rotated.append(rotated_axis.flatten(-2))
    return torch.cat(rotated, dim=-1)


@pytest.mark.parametrize("shape", [(2, 4, 7, 16), (1, 2, 1, 32)])
def test_vectorized_rotary_matches_frozen_reference_bytes_and_gradients(shape: tuple[int, ...]) -> None:
    torch.manual_seed(1945)
    head_dim = shape[-1]
    values_a = torch.randn(shape, dtype=torch.float32, requires_grad=True)
    values_b = values_a.detach().clone().requires_grad_(True)
    coordinates = torch.randint(0, 32, (shape[0], shape[2], 2), dtype=torch.int64)
    module = MODEL.RotaryCoordinates(head_dim)

    expected = reference(values_a, coordinates)
    actual = module.apply(values_b, coordinates)
    torch.testing.assert_close(actual, expected, rtol=0, atol=0)

    weights = torch.randn_like(expected)
    expected.mul(weights).sum().backward()
    actual.mul(weights).sum().backward()
    torch.testing.assert_close(values_b.grad, values_a.grad, rtol=0, atol=0)


def test_fixed_frequencies_are_nonpersistent_and_move_with_module() -> None:
    module = MODEL.RotaryCoordinates(16)
    assert "frequencies" not in module.state_dict()
    assert module.frequencies.dtype == torch.float32
    assert module.frequencies.shape == (4,)
    module = module.to(dtype=torch.float64)
    assert module.frequencies.dtype == torch.float32


def test_invalid_head_dimension_refuses_at_construction() -> None:
    with pytest.raises(ValueError, match="head_dim must be divisible by 4"):
        MODEL.RotaryCoordinates(14)


def test_lower_allocation_treatment_removes_frequency_build_and_stack_cat() -> None:
    values = torch.randn((2, 4, 64, 64), dtype=torch.float32)
    coordinates = torch.randint(0, 64, (2, 64, 2), dtype=torch.int64)
    module = MODEL.RotaryCoordinates(64)
    with torch.profiler.profile(activities=[torch.profiler.ProfilerActivity.CPU]) as profile:
        module.apply(values, coordinates)
    counts = {event.key: event.count for event in profile.key_averages()}
    assert counts.get("aten::arange", 0) == 0
    assert counts.get("aten::pow", 0) == 0
    assert counts.get("aten::stack", 0) == 0
    assert counts.get("aten::cat", 0) == 0
    assert counts.get("aten::cos", 0) == 2
    assert counts.get("aten::sin", 0) == 2
