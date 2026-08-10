# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Import-safe exact Muon target update for the issue #675 actual event.

The numerical update is copied from the live historical B3/P5 implementation,
but this module has no trainer imports, launch path, model mutation, or I/O.
"""

from __future__ import annotations

import math

import torch


class MuonPrimitiveRefusal(ValueError):
    """Named refusal before an update operand can enter capture custody."""


def _refuse(code: str) -> None:
    raise MuonPrimitiveRefusal(code)


def _operand(value: object, code: str) -> torch.Tensor:
    if (
        not isinstance(value, torch.Tensor)
        or value.dtype != torch.float32
        or value.ndim != 2
        or value.numel() == 0
        or not bool(torch.isfinite(value).all())
    ):
        _refuse(code)
    return value


def muon_step_in_copy(
    weight: torch.Tensor,
    gradient: torch.Tensor,
    momentum: torch.Tensor,
    *,
    learning_rate: float,
) -> torch.Tensor:
    """Return the exact five-step, Nesterov Muon update without mutation."""

    weight = _operand(weight, "MUON_WEIGHT_INVALID")
    gradient = _operand(gradient, "MUON_GRADIENT_INVALID")
    momentum = _operand(momentum, "MUON_MOMENTUM_INVALID")
    if (
        weight.shape != gradient.shape
        or weight.shape != momentum.shape
        or weight.device != gradient.device
        or weight.device != momentum.device
    ):
        _refuse("MUON_SHAPE_MISMATCH")
    if (
        not isinstance(learning_rate, (int, float))
        or isinstance(learning_rate, bool)
        or not math.isfinite(float(learning_rate))
        or learning_rate <= 0
    ):
        _refuse("MUON_LEARNING_RATE_INVALID")

    a, b, c = 3.4445, -4.7750, 2.0315
    new_buffer = momentum.clone()
    new_buffer.mul_(0.95).add_(gradient)
    update = gradient.add(new_buffer, alpha=0.95).to(torch.float32)
    transposed = False
    if update.shape[0] > update.shape[1]:
        update = update.T
        transposed = True
    update = update / (update.norm() + 1e-7)
    for _ in range(5):
        gram = update @ update.T
        polynomial = b * gram + c * (gram @ gram)
        update = a * update + polynomial @ update
    if transposed:
        update = update.T
    scale = max(1.0, weight.shape[0] / weight.shape[1]) ** 0.5
    result = weight.detach().clone()
    result.add_(update, alpha=-float(learning_rate) * scale)
    if not bool(torch.isfinite(result).all()):
        _refuse("MUON_RESULT_NONFINITE")
    return result
