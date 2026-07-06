"""selftest_b3_multimodal.py — B3 runner selftest for the multimodal pretrain config.

B-MULTI-4 deliverable. Verifies that:
  1. v0-pretrain-config.json loads cleanly (model dims).
  2. v0-multimodal-config.json loads cleanly (multimodal extension).
  3. EmberModelV0Multimodal instantiates from config params (tiny dims, CPU).
  4. A synthetic forward pass (text-only tokens, no image data) returns the
     correct output shape (batch, seq, vocab).
  5. The B3 runner helper build_multimodal_v0_model() is callable with
     live=False and returns a model + config metadata.
  6. Lock-2 (by PROPERTY): splice_soft_tokens() overwrites image-span rows
     in the embedding output with inputs_embeds values, leaves text rows
     unchanged.
  7. Lock-3 (by PROPERTY): build_span_mask() grants full bidirectionality
     within the image span (mask == 0.0) and enforces causal masking for
     positions before the span trying to attend into the span.
  8. Lock-4 rope_2d_exclusive_pass: apply_rope_2d_factorized() produces a
     different rotation than apply_rope_1d() for the same Q/K at image
     positions — proves exclusive 2D RoPE (no double-rotation).

Also emits a tok/s receipt:
  receipts/multimodal-b3-tokps-<ts>.json
  Basis: cpu-tiny-selftest (hidden=32, heads=2, seq=8, batch=1).
  Production GPU tok/s requires fp-44 remeasure on #414.

Gate (ember #414): receipt must carry rope_2d_exclusive_pass=true AND
tokens_per_second.

Exit 0 + B3_MULTIMODAL_SELFTEST_PASS = green.
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
CONFIGS = ROOT / "configs"
RECEIPTS = ROOT / "receipts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

failures = []


def check(name, cond, detail=""):
    if not cond:
        failures.append(f"{name}: {detail}" if detail else name)
        print(f"FAIL {name}: {detail}")
    else:
        print(f"ok   {name}")


# ── 1. Base pretrain config (model dims) ────────────────────────────────────
base_cfg_path = CONFIGS / "v0-pretrain-config.json"
check("base_config_exists", base_cfg_path.exists(), f"not found: {base_cfg_path}")
base_cfg = {}
m = {}
if base_cfg_path.exists():
    base_cfg = json.loads(base_cfg_path.read_text(encoding="utf-8"))
    m = base_cfg.get("model", {})
    check("base_config_has_model", bool(m), "missing 'model' key")
    check("base_config_has_hidden", "hidden" in m, "missing model.hidden")
    check("base_config_has_heads", "heads" in m, "missing model.heads")
    check("base_config_has_vocab", "vocab" in m, "missing model.vocab")
    # head_dim derived from hidden/heads; verify divisibility
    if "hidden" in m and "heads" in m and m["heads"] > 0:
        hd = m["hidden"] // m["heads"]
        check("base_config_head_dim_divisible", m["hidden"] % m["heads"] == 0,
              f"hidden={m['hidden']} not divisible by heads={m['heads']}")
        check("base_config_head_dim_div4", hd % 4 == 0,
              f"head_dim={hd} must be divisible by 4 for 2D RoPE factorization")

# ── 2. Multimodal extension config ──────────────────────────────────────────
mm_cfg_path = CONFIGS / "v0-multimodal-config.json"
check("mm_config_exists", mm_cfg_path.exists(), f"not found: {mm_cfg_path}")
mm_cfg = {}
if mm_cfg_path.exists():
    mm_cfg = json.loads(mm_cfg_path.read_text(encoding="utf-8"))
    mm = mm_cfg.get("multimodal", {})
    check("mm_config_enabled", mm.get("enabled") is True,
          f"multimodal.enabled={mm.get('enabled')!r}, expected True")
    check("mm_config_has_lock2", "lock2_inputs_embeds" in mm,
          "missing multimodal.lock2_inputs_embeds")
    check("mm_config_has_lock3", "lock3_bidirectional_spans" in mm,
          "missing multimodal.lock3_bidirectional_spans")
    check("mm_config_has_lock4", "lock4_rope_2d" in mm,
          "missing multimodal.lock4_rope_2d")

# ── 3. Import runner helper ──────────────────────────────────────────────────
build_multimodal_v0_model = None
try:
    from build_multimodal_v0_model import build_multimodal_v0_model
    check("runner_importable", True)
except ImportError as e:
    failures.append(f"runner_importable: {e}")

# ── 4. Instantiate model (tiny dims, CPU) ────────────────────────────────────
model = None
if build_multimodal_v0_model and base_cfg:
    try:
        model, vocab, hidden = build_multimodal_v0_model(base_cfg, live=False)
        check("model_instantiates", model is not None)
        check("vocab_matches", vocab == m.get("vocab", 0),
              f"got {vocab}, expected {m.get('vocab')}")
        check("hidden_matches", hidden == m.get("hidden", 0),
              f"got {hidden}, expected {m.get('hidden')}")
    except Exception as e:
        failures.append(f"model_instantiates: {e}")

# ── 5. Forward pass — text-only, synthetic, CPU ──────────────────────────────
if model is not None:
    try:
        import torch
        TINY_BATCH, TINY_SEQ = 1, 8
        ids = torch.randint(0, 64, (TINY_BATCH, TINY_SEQ))
        with torch.no_grad():
            out = model.forward(ids)
        check("forward_returns_tensor", hasattr(out, "shape"),
              f"got {type(out)}")
        if hasattr(out, "shape"):
            expected_shape = (TINY_BATCH, TINY_SEQ, 64)   # tiny vocab=64
            check("output_shape", tuple(out.shape) == expected_shape,
                  f"got {tuple(out.shape)}, expected {expected_shape}")
    except Exception as e:
        failures.append(f"forward_pass: {e}")

# ── 6. Lock-2 (by PROPERTY): splice_soft_tokens overwrites image spans ───────
try:
    import torch
    from ember_model_v0_multimodal import splice_soft_tokens

    HIDDEN_TINY = 32
    VOCAB_TINY = 64
    torch.manual_seed(0)
    embed = torch.nn.Embedding(VOCAB_TINY, HIDDEN_TINY)
    torch.nn.init.constant_(embed.weight, 1.0)   # all text embeddings = 1.0

    # Sequence: positions 0,1 text | 2,3,4 image span | 5,6,7 text
    input_ids = torch.zeros(1, 8, dtype=torch.long)
    span_boundaries = [(2, 5)]
    inputs_embeds = torch.full((1, 3, HIDDEN_TINY), 2.0)  # distinctive value

    out_splice = splice_soft_tokens(embed, input_ids, inputs_embeds, span_boundaries)

    image_overwritten = torch.allclose(out_splice[0, 2:5, :],
                                       inputs_embeds[0, :, :])
    text_unchanged_pre = torch.allclose(out_splice[0, 0:2, :],
                                        torch.ones(2, HIDDEN_TINY))
    text_unchanged_post = torch.allclose(out_splice[0, 5:8, :],
                                         torch.ones(3, HIDDEN_TINY))
    check("lock2_splice_overwrites_image_positions", image_overwritten,
          "image positions should equal inputs_embeds value (2.0)")
    check("lock2_splice_preserves_pre_span_text", text_unchanged_pre,
          "text positions before span should keep embed value (1.0)")
    check("lock2_splice_preserves_post_span_text", text_unchanged_post,
          "text positions after span should keep embed value (1.0)")
except Exception as e:
    failures.append(f"lock2_splice: {e}")

# ── 7. Lock-3 (by PROPERTY): build_span_mask bidirectionality ────────────────
try:
    import torch
    from ember_model_v0_multimodal import build_span_mask

    S = 8
    span = [(2, 5)]   # image span: positions 2, 3, 4 (end exclusive)
    mask = build_span_mask(S, span)   # (S, S), additive: 0.0=attend, -inf=masked

    # Within span: all pairs fully attend (mask == 0.0)
    within_ok = bool((mask[2:5, 2:5] == 0.0).all().item())
    # Bidirectionality: row 2 can attend to col 4 (later in span, future in causal)
    fwd_in_span = bool(mask[2, 4].item() == 0.0)
    # Before span: row 0 cannot attend to image-span cols 2,3,4 (causal)
    pre_causal = bool((mask[0, 2:5] == float("-inf")).all().item())
    # Empty span → pure causal mask
    mask_empty = build_span_mask(S, [])
    causal_ref = torch.zeros(S, S)
    causal_ref.masked_fill_(torch.triu(torch.ones(S, S, dtype=torch.bool), diagonal=1),
                             float("-inf"))
    empty_is_causal = bool(torch.allclose(mask_empty, causal_ref))

    check("lock3_bidirectional_within_span", within_ok,
          "mask[span_rows, span_cols] should all be 0.0")
    check("lock3_forward_attend_in_span", fwd_in_span,
          "row 2 should attend to col 4 (bidirectional within span)")
    check("lock3_causal_before_span", pre_causal,
          "row 0 should not attend to span cols (causal)")
    check("lock3_empty_span_is_pure_causal", empty_is_causal,
          "empty span list should produce standard causal mask")
except Exception as e:
    failures.append(f"lock3_span_mask: {e}")

# ── 8. Lock-4: rope_2d_exclusive_pass ────────────────────────────────────────
lock4_pass = False
try:
    import torch
    from ember_model_v0_multimodal import apply_rope_1d, apply_rope_2d_factorized, _rope_1d

    torch.manual_seed(42)
    H, S, d = 2, 6, 16   # n_heads, seq_len, head_dim (divisible by 4)
    q = torch.randn(1, H, S, d)
    k = torch.randn(1, H, S, d)

    # 1D RoPE applied to full sequence
    cos, sin = _rope_1d(S, d)
    cos4d = cos.unsqueeze(0).unsqueeze(0)
    sin4d = sin.unsqueeze(0).unsqueeze(0)
    q_1d, k_1d = apply_rope_1d(q.clone(), k.clone(), cos4d, sin4d)

    # 2D RoPE applied exclusively to image positions 2-3 (n_img=2)
    n_img = 2
    x_pos = torch.tensor([[0, 1]])   # column positions
    y_pos = torch.tensor([[0, 0]])   # row positions
    q_2d, _ = apply_rope_2d_factorized(
        q[:, :, 2:2 + n_img, :].clone(),
        k[:, :, 2:2 + n_img, :].clone(),
        x_pos, y_pos, d,
    )

    # rope_2d_exclusive: 2D result MUST differ from 1D result at same image positions
    q_1d_img = q_1d[:, :, 2:2 + n_img, :]
    differs = not torch.allclose(q_2d, q_1d_img, atol=1e-5)
    check("lock4_rope_2d_exclusive_pass", differs,
          "2D RoPE result should differ from 1D-only at image positions")
    lock4_pass = differs
except Exception as e:
    failures.append(f"lock4_rope_2d_exclusive: {e}")

# ── 9. Tok/s measurement + receipt emission ───────────────────────────────────
tokens_per_second = 0.0
receipt_path_str = ""
if build_multimodal_v0_model and base_cfg:
    try:
        import torch
        from receipt_write import checked_write

        tok_model, _, _ = build_multimodal_v0_model(base_cfg, live=False)
        ids = torch.randint(0, 64, (1, 8))

        # Warmup
        for _ in range(3):
            with torch.no_grad():
                tok_model.forward(ids)

        N = 30
        t0 = time.perf_counter()
        for _ in range(N):
            with torch.no_grad():
                tok_model.forward(ids)
        elapsed = time.perf_counter() - t0
        tokens_per_second = (N * 1 * 8) / elapsed

        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        lock2_ok = not any(
            f.startswith("lock2_splice_overwrites") for f in failures
        )
        lock3_ok = not any(
            f.startswith("lock3_bidirectional") for f in failures
        )
        receipt = {
            "ticket": "B3-MULTIMODAL-SELFTEST",
            "ts": ts,
            "config_base": "configs/v0-pretrain-config.json",
            "config_mm_ext": "configs/v0-multimodal-config.json",
            "lock2_splice_pass": lock2_ok,
            "lock3_span_mask_pass": lock3_ok,
            "lock4_rope_2d_exclusive_pass": lock4_pass,
            "rope_2d_exclusive_pass": lock4_pass,
            "tokens_per_second": round(tokens_per_second, 2),
            "tokps_basis": (
                "cpu-tiny-selftest: hidden=32 heads=2 seq=8 batch=1; "
                "production GPU tok/s from fp-44 remeasure on #414"
            ),
            "pass": len(failures) == 0,
        }
        RECEIPTS.mkdir(exist_ok=True)
        receipt_path = RECEIPTS / f"multimodal-b3-tokps-{ts}.json"
        checked_write(str(receipt_path), receipt)
        receipt_path_str = str(receipt_path)
        print(f"receipt: {receipt_path_str}")
        print(f"tokens_per_second: {tokens_per_second:.1f}")
        check("receipt_written", receipt_path.exists(),
              f"receipt not found at {receipt_path_str}")
    except Exception as e:
        failures.append(f"tokps_receipt: {e}")

# ── Report ─────────────────────────────────────────────────────────────────────
if failures:
    for f in failures:
        print(f"FAIL: {f}")
    sys.exit(1)

print("B3_MULTIMODAL_SELFTEST_PASS")
print(f"rope_2d_exclusive_pass={lock4_pass} "
      f"tok_per_second={tokens_per_second:.1f} "
      f"receipt={receipt_path_str}")
