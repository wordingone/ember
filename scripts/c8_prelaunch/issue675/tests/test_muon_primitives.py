# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import torch


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "q2_muon_primitives.py"


def _load():
    assert MODULE_PATH.exists(), "q2_muon_primitives.py is not implemented"
    spec = importlib.util.spec_from_file_location("q2_muon_primitives", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _reference(weight, grad, momentum_buffer, lr):
    a, b, c = 3.4445, -4.7750, 2.0315
    new_buf = momentum_buffer.clone()
    new_buf.mul_(0.95).add_(grad)
    update = grad.add(new_buf, alpha=0.95).to(torch.float32)
    transposed = False
    if update.shape[0] > update.shape[1]:
        update = update.T
        transposed = True
    update = update / (update.norm() + 1e-7)
    for _ in range(5):
        aa = update @ update.T
        bb = b * aa + c * (aa @ aa)
        update = a * update + bb @ update
    if transposed:
        update = update.T
    scale = max(1.0, weight.shape[0] / weight.shape[1]) ** 0.5
    result = weight.detach().clone()
    result.add_(update, alpha=-lr * scale)
    return result


def test_muon_step_matches_frozen_live_formula_without_mutating_inputs():
    module = _load()
    weight = torch.tensor([[0.5, -0.25], [0.125, 0.75]], dtype=torch.float32)
    grad = torch.tensor([[0.2, -0.3], [0.4, 0.1]], dtype=torch.float32)
    momentum = torch.tensor([[0.9, 0.2], [-0.1, 0.3]], dtype=torch.float32)
    originals = [value.clone() for value in (weight, grad, momentum)]

    actual = module.muon_step_in_copy(weight, grad, momentum, learning_rate=0.02)

    assert torch.equal(actual, _reference(weight, grad, momentum, 0.02))
    assert all(torch.equal(value, original) for value, original in zip((weight, grad, momentum), originals))


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("weight", torch.ones(2), "MUON_WEIGHT_INVALID"),
        ("gradient", torch.tensor([[float("nan")]]), "MUON_GRADIENT_INVALID"),
        ("momentum", torch.ones(3, 3), "MUON_SHAPE_MISMATCH"),
        ("learning_rate", 0.0, "MUON_LEARNING_RATE_INVALID"),
    ],
)
def test_muon_step_refuses_malformed_operands(field, value, code: str):
    module = _load()
    kwargs = {
        "weight": torch.ones(2, 2),
        "gradient": torch.ones(2, 2),
        "momentum": torch.ones(2, 2),
        "learning_rate": 0.02,
    }
    kwargs[field] = value
    with pytest.raises(module.MuonPrimitiveRefusal, match=code):
        module.muon_step_in_copy(**kwargs)
