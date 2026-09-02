#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Semantic and routing contract for the #2062 native RMSNorm treatment."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
import torch


MODEL_PATH = Path(__file__).parents[2] / "tools" / "ember-restart-3b" / "model.py"
SPEC = importlib.util.spec_from_file_location("issue2062_rmsnorm_model", MODEL_PATH)
MODEL = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODEL
with patch.object(torch, "compile", lambda function, **_kwargs: function):
    SPEC.loader.exec_module(MODEL)

TOLERANCES = {
    torch.float32: {"atol": 2e-6, "rtol": 2e-6},
    torch.bfloat16: {"atol": 0.015625, "rtol": 0.015625},
}
WEIGHT_GRADIENT_RELATIVE_LIMITS = {
    torch.float32: 4.76837158203125e-7,
    torch.bfloat16: 0.03125,
}
WEIGHT_GRADIENT_EPSILON = {
    torch.float32: 1.1920928955078125e-7,
    torch.bfloat16: 0.0078125,
}


def reference(hidden: torch.Tensor, weight: torch.Tensor) -> torch.Tensor:
    scale = torch.rsqrt(hidden.pow(2).mean(dim=-1, keepdim=True) + 1e-6)
    return hidden * scale * weight


def assert_weight_gradient_reduction_equivalent(
    *, fp32_reference: torch.Tensor, control: torch.Tensor, treatment: torch.Tensor, dtype: torch.dtype
) -> None:
    scale = max(float(fp32_reference.abs().max().item()), 1.0)
    control_error = float((fp32_reference - control.float()).abs().max().item())
    treatment_error = float((fp32_reference - treatment.float()).abs().max().item())
    relative_limit = WEIGHT_GRADIENT_RELATIVE_LIMITS[dtype]
    ulp_slack = WEIGHT_GRADIENT_EPSILON[dtype] * scale
    assert control_error / scale <= relative_limit
    assert treatment_error / scale <= relative_limit
    assert treatment_error <= control_error + ulp_slack


def test_weight_gradient_reduction_bound_is_fp32_referenced_and_nonregressive() -> None:
    fp32_reference = torch.tensor([100.0, -50.0])
    assert_weight_gradient_reduction_equivalent(
        fp32_reference=fp32_reference,
        control=torch.tensor([100.5, -50.0]),
        treatment=torch.tensor([101.0, -50.0]),
        dtype=torch.bfloat16,
    )
    with pytest.raises(AssertionError):
        assert_weight_gradient_reduction_equivalent(
            fp32_reference=fp32_reference,
            control=torch.tensor([100.0, -50.0]),
            treatment=torch.tensor([102.0, -50.0]),
            dtype=torch.bfloat16,
        )


@pytest.mark.parametrize("dtype", [torch.float32])
def test_cpu_native_route_matches_frozen_output_and_both_gradients(dtype: torch.dtype) -> None:
    torch.manual_seed(2062)
    left = torch.randn((2, 3, 256), dtype=dtype, requires_grad=True)
    right = left.detach().clone().requires_grad_(True)
    weight_left = torch.randn((256,), dtype=dtype, requires_grad=True)
    weight_right = weight_left.detach().clone().requires_grad_(True)

    expected = reference(left, weight_left)
    actual = MODEL._rms_norm_for_device(right, weight_right)
    tolerance = TOLERANCES[dtype]
    torch.testing.assert_close(actual, expected, **tolerance)

    upstream = torch.randn_like(expected)
    expected.mul(upstream).sum().backward()
    actual.mul(upstream).sum().backward()
    torch.testing.assert_close(right.grad, left.grad, **tolerance)
    torch.testing.assert_close(weight_right.grad, weight_left.grad, **tolerance)


def test_meta_route_preserves_shape_dtype_and_device() -> None:
    hidden = torch.empty((2, 3, 16), device="meta")
    weight = torch.empty((16,), device="meta")
    result = MODEL._rms_norm_for_device(hidden, weight)
    assert result.shape == hidden.shape
    assert result.dtype == hidden.dtype
    assert result.device.type == "meta"


def test_mixed_device_refuses_before_native_dispatch() -> None:
    with pytest.raises(ValueError, match="RMSNorm hidden states and weight must share a device"):
        MODEL._rms_norm_for_device(
            torch.empty((2, 3, 16), device="cpu"),
            torch.empty((16,), device="meta"),
        )


def test_unsupported_device_refuses_explicitly() -> None:
    class Unsupported:
        device = torch.device("mps")

    with pytest.raises(ValueError, match="RMSNorm native route does not support device type: mps"):
        MODEL._rms_norm_for_device(Unsupported(), Unsupported())


def test_every_rmsnorm_forward_routes_through_native_helper() -> None:
    module = MODEL.RMSNorm(16)
    hidden = torch.randn((2, 3, 16))
    sentinel = torch.randn_like(hidden)
    with patch.object(MODEL, "_rms_norm_for_device", return_value=sentinel) as native:
        assert module(hidden) is sentinel
    native.assert_called_once_with(hidden, module.weight)


@pytest.mark.parametrize("dtype", [torch.float32, torch.bfloat16])
def test_cuda_production_shape_matches_frozen_output_and_gradients(dtype: torch.dtype) -> None:
    if not torch.cuda.is_available():
        pytest.skip("CUDA treatment contract requires CUDA")
    torch.manual_seed(2062)
    left = torch.randn((2, 15, 8192), device="cuda", dtype=dtype, requires_grad=True)
    right = left.detach().clone().requires_grad_(True)
    weight_left = torch.randn((8192,), device="cuda", dtype=dtype, requires_grad=True)
    weight_right = weight_left.detach().clone().requires_grad_(True)
    expected = reference(left, weight_left)
    actual = MODEL._rms_norm_for_device(right, weight_right)
    tolerance = TOLERANCES[dtype]
    torch.testing.assert_close(actual, expected, **tolerance)
    upstream = torch.randn_like(expected)
    expected.mul(upstream).sum().backward()
    actual.mul(upstream).sum().backward()
    torch.testing.assert_close(right.grad, left.grad, **tolerance)
    fp32_input = left.detach().float().requires_grad_(True)
    fp32_weight = weight_left.detach().float().requires_grad_(True)
    fp32_output = reference(fp32_input, fp32_weight)
    fp32_weight_gradient = torch.autograd.grad(
        fp32_output, fp32_weight, upstream.float()
    )[0]
    assert_weight_gradient_reduction_equivalent(
        fp32_reference=fp32_weight_gradient,
        control=weight_left.grad,
        treatment=weight_right.grad,
        dtype=dtype,
    )
