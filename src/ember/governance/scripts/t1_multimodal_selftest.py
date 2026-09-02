# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""t1_multimodal_selftest.py — CPU selftest for ember-multimodal-v0 Locks 2+3+VisionEmbedder.

AC for eng-36/#420 and eng-39/#423. Proves on CPU (<30s) that:
  Lock 2: splice_soft_tokens() correctly overwrites placeholder positions with
          VisionEmbedder soft tokens (input_embeds splice path).
  Lock 3: build_span_mask() produces correct causal + bidirectional structure.
  VisionEmbedder: forward pass returns correct shape and channels position signal.
  Integration: EmberModelV0Multimodal forward pass with text+image data exits cleanly.

Does NOT require GPU, real image data, B-MULTI-1 corpus, or EMBER_GATE_AUTHORIZED.

Exit 0 + T1_MULTIMODAL_SELFTEST_PASS in output = green.
"""

from __future__ import annotations

import math
import sys
import time

_start = time.monotonic()

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if not cond:
        failures.append(f"{name}: {detail}" if detail else name)


# ── imports ───────────────────────────────────────────────────────────────────
try:
    import torch
    check("torch_importable", True)
except ImportError as e:
    print(f"FAIL: torch_importable: {e}")
    sys.exit(1)

try:
    from ember_model_v0_multimodal import (
        splice_soft_tokens,
        build_span_mask,
        VisionEmbedder,
        EmberModelV0Multimodal,
    )
    check("module_importable", True)
except ImportError as e:
    print(f"FAIL: module_importable: {e}")
    sys.exit(1)

# ── 1. VisionEmbedder forward ─────────────────────────────────────────────────
try:
    ve = VisionEmbedder(in_dim=6912, out_dim=1024, max_pos=64)
    B, N = 1, 4
    patches = torch.zeros(B, N, 6912)
    x_pos = torch.zeros(B, N, dtype=torch.long)
    y_pos = torch.arange(N).unsqueeze(0)
    with torch.no_grad():
        out = ve.forward(patches, x_pos, y_pos)
    check("vision_embedder_shape", tuple(out.shape) == (B, N, 1024),
          f"got {tuple(out.shape)}, expected (1, 4, 1024)")
    # position signal: different y_pos rows should differ
    check("vision_embedder_pos_signal",
          not torch.allclose(out[0, 0], out[0, 1], atol=1e-5),
          "y=0 and y=1 embeddings identical — position not encoded")
except Exception as e:
    failures.append(f"vision_embedder: {e}")

# ── 2. splice_soft_tokens ─────────────────────────────────────────────────────
try:
    HIDDEN, VOCAB, SEQ = 32, 64, 16
    embed = torch.nn.Embedding(VOCAB, HIDDEN)
    ids = torch.randint(0, VOCAB, (1, SEQ))
    # Soft tokens to splice at positions 4..8 (4 tokens)
    soft = torch.ones(1, 4, HIDDEN) * 42.0
    spans = [(4, 8)]
    with torch.no_grad():
        h = splice_soft_tokens(embed, ids, soft, spans)
    check("splice_output_shape", tuple(h.shape) == (1, SEQ, HIDDEN),
          f"got {tuple(h.shape)}")
    # Span positions should carry the soft token value
    check("splice_soft_written", torch.allclose(h[0, 4:8], soft[0], atol=1e-5),
          "soft tokens not written at span [4, 8)")
    # Non-span positions should match embed(ids)
    with torch.no_grad():
        baseline = embed(ids)
    check("splice_text_unchanged",
          torch.allclose(h[0, 0:4], baseline[0, 0:4], atol=1e-5),
          "text positions [0, 4) changed after splice")
    check("splice_text_unchanged_after",
          torch.allclose(h[0, 8:], baseline[0, 8:], atol=1e-5),
          "text positions [8, SEQ) changed after splice")
except Exception as e:
    failures.append(f"splice_soft_tokens: {e}")

# ── 3. build_span_mask ────────────────────────────────────────────────────────
try:
    SEQ = 12
    spans = [(3, 7)]
    mask = build_span_mask(SEQ, spans)
    check("mask_shape", tuple(mask.shape) == (SEQ, SEQ),
          f"got {tuple(mask.shape)}")
    # Causal: upper triangle outside span must be -inf
    # Position (0, 1): row 0, col 1 — col > row, outside any span → -inf
    check("mask_causal_upper_tri",
          mask[0, 1].item() == float("-inf"),
          f"(0,1) expected -inf, got {mask[0, 1].item()}")
    # Inside span: all positions in [3, 7) attend to each other
    # (3, 6): row=3, col=6 — col > row but both in span → 0.0 (not masked)
    check("mask_span_bidirectional",
          mask[3, 6].item() == 0.0,
          f"(3,6) expected 0.0 (span), got {mask[3, 6].item()}")
    # (6, 3): row=6, col=3 — col < row, inside span → 0.0 (causal would also be 0)
    check("mask_span_lower_in_span",
          mask[6, 3].item() == 0.0,
          f"(6,3) expected 0.0, got {mask[6, 3].item()}")
    # Empty spans → pure causal (all upper-tri = -inf)
    mask_text = build_span_mask(8, [])
    triu_vals = mask_text[torch.triu(torch.ones(8, 8, dtype=torch.bool), diagonal=1)]
    check("mask_empty_spans_pure_causal",
          (triu_vals == float("-inf")).all().item(),
          "empty-span mask has non-(-inf) in upper triangle")
except Exception as e:
    failures.append(f"build_span_mask: {e}")

# ── 4. EmberModelV0Multimodal forward — text+image ────────────────────────────
try:
    HIDDEN, HEADS, HD, VOCAB = 32, 2, 16, 64
    SEQ = 12
    model = EmberModelV0Multimodal(hidden=HIDDEN, n_heads=HEADS, head_dim=HD, vocab=VOCAB)
    ids = torch.randint(0, VOCAB, (1, SEQ))
    soft = torch.randn(1, 4, HIDDEN)  # 4 image soft tokens
    spans = [(3, 7)]
    with torch.no_grad():
        out = model.forward(ids, inputs_embeds=soft, span_boundaries=spans)
    check("integration_shape", tuple(out.shape) == (1, SEQ, VOCAB),
          f"got {tuple(out.shape)}")
    check("integration_no_nan", not torch.isnan(out).any().item(),
          "output contains NaN")
    # Text-only path still works
    with torch.no_grad():
        out_text = model.forward(ids)
    check("text_only_shape", tuple(out_text.shape) == (1, SEQ, VOCAB),
          f"got {tuple(out_text.shape)}")
except Exception as e:
    failures.append(f"integration: {e}")

# ── 5. Timing gate ────────────────────────────────────────────────────────────
elapsed = time.monotonic() - _start
check("timing_under_30s", elapsed < 30.0,
      f"elapsed {elapsed:.1f}s >= 30s limit")

# ── Report ─────────────────────────────────────────────────────────────────────
if failures:
    for f in failures:
        print(f"FAIL: {f}")
    sys.exit(1)

print("T1_MULTIMODAL_SELFTEST_PASS")
print(f"lock2_pass=true lock3_pass=true vision_embedder_pass=true integration_pass=true")
print(f"elapsed_s={elapsed:.2f}")
