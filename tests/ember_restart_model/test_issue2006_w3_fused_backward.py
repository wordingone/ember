# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Source-level and CPU-semantic gates for #2006's selected custom backward."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
import torch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "ember-restart-3b"))

from model import W3_ACTIVE_EXPERT_FUSED_BACKWARD_TREATMENT_ID, RestartDecoderConfig, SwiGLUExpert, UnifiedDecoder  # noqa: E402


def gradients(function, hidden, upstream):
    hidden = hidden.detach().clone().requires_grad_(True)
    expert = SwiGLUExpert(hidden.shape[-1])
    torch.manual_seed(1945200)
    with torch.no_grad():
        expert.up_gate.weight.normal_(0, 0.02)
        expert.down.weight.normal_(0, 0.02)
    function(expert, hidden).backward(upstream)
    return function(expert, hidden.detach()), hidden.grad, expert.up_gate.weight.grad, expert.down.weight.grad


def assert_metrics(control, treatment):
    assert control.shape == treatment.shape and control.dtype == treatment.dtype
    assert torch.equal(torch.isfinite(control), torch.isfinite(treatment))
    assert torch.equal(control == 0, treatment == 0)
    left, right = control.float().reshape(-1), treatment.float().reshape(-1)
    assert torch.nn.functional.cosine_similarity(left, right, dim=0) >= 0.999999
    assert torch.linalg.vector_norm(left - right) / torch.linalg.vector_norm(left) <= 0.001
    torch.testing.assert_close(left, right, rtol=0.001, atol=0.00001)


def test_eager_forward_bytes_and_all_gradient_subjects_match_on_portable_cpu():
    hidden = torch.randn(2, 7, 16, generator=torch.Generator().manual_seed(1945001)) * 0.125
    hidden.reshape(-1)[::17] = 0
    upstream = torch.randn(2, 7, 16, generator=torch.Generator().manual_seed(1945101)) * 0.0625
    upstream.reshape(-1)[::19] = 0
    torch.manual_seed(1945200)
    control_expert = SwiGLUExpert(16)
    torch.manual_seed(1945200)
    treatment_expert = SwiGLUExpert(16)
    control_hidden = hidden.clone().requires_grad_(True)
    treatment_hidden = hidden.clone().requires_grad_(True)
    control_output = control_expert(control_hidden)
    treatment_output = treatment_expert.forward_with_fused_backward(treatment_hidden)
    assert torch.equal(control_output, treatment_output)
    control_output.backward(upstream)
    treatment_output.backward(upstream)
    for control, treatment in (
        (control_hidden.grad, treatment_hidden.grad),
        (control_expert.up_gate.weight.grad, treatment_expert.up_gate.weight.grad),
        (control_expert.down.weight.grad, treatment_expert.down.weight.grad),
    ):
        assert_metrics(control, treatment)


def test_selector_refuses_before_model_allocation_and_defaults_to_eager():
    config = RestartDecoderConfig.small_for_tests(hidden_size=16, layers=1, attention_heads=4, vocab_size=32)
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("EMBER_W3_ACTIVE_EXPERT_FUSED_BACKWARD", None)
        assert UnifiedDecoder(config).w3_active_expert_fused_backward is False
    with patch.dict(os.environ, {"EMBER_W3_ACTIVE_EXPERT_FUSED_BACKWARD": "invalid"}):
        with pytest.raises(ValueError, match="EMBER_W3_ACTIVE_EXPERT_FUSED_BACKWARD"):
            UnifiedDecoder(config)


def test_selector_reaches_only_the_reasoning_expert():
    config = RestartDecoderConfig.small_for_tests(hidden_size=16, layers=1, attention_heads=4, vocab_size=32, gradient_checkpointing=False)
    with patch.dict(os.environ, {"EMBER_W3_ACTIVE_EXPERT_FUSED_BACKWARD": W3_ACTIVE_EXPERT_FUSED_BACKWARD_TREATMENT_ID}):
        model = UnifiedDecoder(config).eval()
    layer = model.layers[0]
    ids = torch.tensor([[1, 2, 3]])
    with patch.object(layer.experts["reasoning"], "forward_with_fused_backward", wraps=layer.experts["reasoning"].forward_with_fused_backward) as fused:
        model(ids, active_expert="reasoning")
        fused.assert_called_once()
    with patch.object(layer.experts["audio"], "forward_with_fused_backward", side_effect=AssertionError("nonselected expert fused")):
        model(ids, active_expert="audio")
