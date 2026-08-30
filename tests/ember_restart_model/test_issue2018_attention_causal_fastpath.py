# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""CPU gates for #2018's signature-correct causal SDPA dispatch."""

from __future__ import annotations

import dataclasses
import sys
from pathlib import Path
from unittest.mock import patch

import torch
import torch.nn.functional as F
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "ember-restart-3b"))

from model import MultimodalSpan, RestartDecoderConfig, UnifiedDecoder  # noqa: E402


def test_span_free_forward_does_not_materialize_explicit_attention_mask() -> None:
    config = dataclasses.replace(
        RestartDecoderConfig.small_for_tests(
            hidden_size=32, layers=1, attention_heads=4, vocab_size=64
        ),
        gradient_checkpointing=False,
    )
    model = UnifiedDecoder(config)
    model.eval()
    ids = torch.tensor([[1, 2, 3, 4]])
    with patch.object(
        model,
        "build_attention_mask",
        side_effect=AssertionError("span-free route materialized an explicit mask"),
    ):
        output = model(ids, spans=None, active_expert="shared")
    assert torch.isfinite(output).all()


@pytest.mark.parametrize("attention_mode", ["causal", "bidirectional"])
def test_span_bearing_forward_stays_on_explicit_mask_control(attention_mode: str) -> None:
    config = dataclasses.replace(
        RestartDecoderConfig.small_for_tests(
            hidden_size=32, layers=1, attention_heads=4, vocab_size=64
        ),
        gradient_checkpointing=False,
    )
    model = UnifiedDecoder(config)
    model.eval()
    ids = torch.tensor([[1, 2, 3, 4]])
    span = MultimodalSpan(
        start=1, length=2, modality="text", attention_mode=attention_mode
    )
    with patch.object(model, "build_attention_mask", wraps=model.build_attention_mask) as build:
        output = model(ids, spans=[span], active_expert="shared")
    assert build.call_count == 1
    assert torch.isfinite(output).all()


def test_native_causal_dispatch_matches_explicit_causal_outputs_and_gradients() -> None:
    for shape in ((1, 2, 1, 8), (1, 2, 64, 8), (2, 2, 16, 8)):
        generator = torch.Generator(device="cpu").manual_seed(sum(shape) + 2018)
        base = [torch.randn(shape, generator=generator) for _ in range(3)]
        control_values = [value.clone().requires_grad_(True) for value in base]
        treatment_values = [value.clone().requires_grad_(True) for value in base]
        sequence = shape[-2]
        allowed = torch.arange(sequence).unsqueeze(0) <= torch.arange(sequence).unsqueeze(1)
        control = F.scaled_dot_product_attention(
            *control_values,
            attn_mask=allowed.unsqueeze(0).unsqueeze(0),
            is_causal=False,
        )
        treatment = F.scaled_dot_product_attention(
            *treatment_values,
            attn_mask=None,
            is_causal=True,
        )
        torch.testing.assert_close(treatment, control, rtol=1e-6, atol=1e-7)
        upstream = torch.randn(control.shape, generator=generator)
        control.backward(upstream)
        treatment.backward(upstream)
        for observed, expected in zip(treatment_values, control_values):
            torch.testing.assert_close(observed.grad, expected.grad, rtol=1e-6, atol=1e-7)
    assert not torch.cuda.is_initialized()
