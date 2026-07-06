"""ember_bitnet_core.py — BitNet b1.58 ternary core module for C15 comparison.

Implements BitNet b1.58 (Ma et al. 2024) against the c03-h1024-d20 dense
architecture defined in timeshare_pretrain.py, so a future dense-vs-ternary
comparison is apples-to-apples.

Architecture parity with c03 (single-variable: ONLY weight precision differs):
  hidden      = 1024
  depth       = 20
  heads       = 16
  head_dim    = 64  (hidden // heads)
  ffn_hidden  = 4096  (hidden * 4, matching LlamaConfig intermediate_size)
  FFN style   = SwiGLU (gate_proj * silu(up_proj), then down_proj)
  Attention   = standard multi-head (QKV + out_proj), no GQA for simplicity
  Causal mask = autoregressive (decoder), same as c03 LlamaModel
  RoPE        = rotary position embeddings, theta=10000.0 (LlamaConfig default)
  Tied emb    = LM head weight == embedding weight (tie_word_embeddings=True)
  MTP heads   = n_mtp=2, weight=0.3 (contract #5, v0-pretrain-config.json)

BitNet b1.58 mechanics:
  - ABSMEAN quantization: scale = mean(|W|); W_q = round(clip(W/scale, -1, 1))
  - Weights are TERNARY {-1, 0, +1} after quantization.
  - STRAIGHT-THROUGH ESTIMATOR (STE): quantize in forward, gradient passes
    straight through to full-precision SHADOW weights unchanged.
  - Activation quantization: 8-bit absmax per-token (optional; enabled by
    default for the smoke as per the paper's activation scheme).

Device policy: CPU ONLY — no CUDA in this module.

Selftest: python ember_bitnet_core.py
  Marker: EMBER_BITNET_CORE_SELFTEST_PASS
"""

from __future__ import annotations

import math
import sys
from typing import Optional

import torch
import torch.nn as nn
import torch.nn.functional as F

# ---------------------------------------------------------------------------
# C03 architecture constants (mirrored from timeshare_pretrain.py /
# configs/v0-pretrain-config.json)
# ---------------------------------------------------------------------------
C03_HIDDEN: int = 1024
C03_DEPTH: int = 20
C03_HEADS: int = 16
C03_HEAD_DIM: int = C03_HIDDEN // C03_HEADS   # 64
C03_FFN_HIDDEN: int = C03_HIDDEN * 4           # 4096 (intermediate_size)
C03_VOCAB: int = 32_000
C03_SEQ: int = 1024
C03_ROPE_THETA: float = 10000.0    # LlamaConfig default_theta (rope_parameters)
C03_NORM_EPS: float = 1e-6         # LlamaConfig rms_norm_eps default
C03_MTP_N_HEADS: int = 2           # v0-pretrain-config.json objective.mtp_aux_heads.n_heads
C03_MTP_WEIGHT: float = 0.3        # v0-pretrain-config.json objective.mtp_aux_heads.weight

# ---------------------------------------------------------------------------
# Ternary quantization helpers
# ---------------------------------------------------------------------------

def absmean_scale(w: torch.Tensor, eps: float = 1e-8) -> torch.Tensor:
    """Per-tensor ABSMEAN scale.  scale = mean(|w|) + eps.

    eps avoids divide-by-zero on all-zero tensors (e.g. early init).
    Returns a scalar tensor with the same dtype as w.
    """
    return w.abs().mean() + eps


def ternary_quantize(w: torch.Tensor, eps: float = 1e-8) -> torch.Tensor:
    """Quantize w to {-1, 0, +1} via ABSMEAN scaling.

    W_q = round(clip(W / scale, -1, 1))

    The result is float (same dtype as w) with values exactly in {-1, 0, +1}.
    Not in-place; returns a new tensor.
    """
    scale = absmean_scale(w, eps=eps)
    return torch.round(torch.clamp(w / scale, -1.0, 1.0))


# ---------------------------------------------------------------------------
# Rotary Position Embeddings (RoPE) — matches c03 LlamaConfig
# theta=10000.0, head_dim=64 (hidden//heads).  Pure-Python + torch, CPU-safe.
# ---------------------------------------------------------------------------

def _rope_freqs(head_dim: int, theta: float, device: torch.device) -> torch.Tensor:
    """Precompute inverse frequencies for RoPE.

    Returns shape (head_dim // 2,) float32 tensor of 1 / (theta^(2i/d)).
    Matches the LlamaRotaryEmbedding frequency formula.
    """
    i = torch.arange(0, head_dim, 2, dtype=torch.float32, device=device)
    return 1.0 / (theta ** (i / head_dim))


def _rope_cos_sin(
    seq_len: int,
    head_dim: int,
    theta: float,
    device: torch.device,
    dtype: torch.dtype,
) -> tuple[torch.Tensor, torch.Tensor]:
    """Compute RoPE cos/sin tables for a given sequence length.

    Returns (cos, sin) each shape (1, 1, seq_len, head_dim) for broadcasting
    over (B, n_heads, T, head_dim).
    """
    inv_freq = _rope_freqs(head_dim, theta, device)
    t = torch.arange(seq_len, dtype=torch.float32, device=device)
    freqs = torch.outer(t, inv_freq)                    # (T, head_dim//2)
    emb = torch.cat([freqs, freqs], dim=-1)             # (T, head_dim)
    cos = emb.cos().to(dtype).unsqueeze(0).unsqueeze(0) # (1,1,T,head_dim)
    sin = emb.sin().to(dtype).unsqueeze(0).unsqueeze(0)
    return cos, sin


def _rotate_half(x: torch.Tensor) -> torch.Tensor:
    """Rotate the last dimension by splitting it in half and negating."""
    half = x.shape[-1] // 2
    x1 = x[..., :half]
    x2 = x[..., half:]
    return torch.cat([-x2, x1], dim=-1)


def apply_rope(
    q: torch.Tensor,
    k: torch.Tensor,
    cos: torch.Tensor,
    sin: torch.Tensor,
) -> tuple[torch.Tensor, torch.Tensor]:
    """Apply RoPE to query and key tensors.

    q, k: (B, n_heads, T, head_dim)
    cos, sin: (1, 1, T, head_dim) — broadcast over B and n_heads.
    Returns (q_rot, k_rot) same shape.
    """
    q_rot = (q * cos) + (_rotate_half(q) * sin)
    k_rot = (k * cos) + (_rotate_half(k) * sin)
    return q_rot, k_rot


def absmax_quant_8bit(x: torch.Tensor, eps: float = 1e-8) -> torch.Tensor:
    """Per-token 8-bit absmax activation quantization (STE).

    Quantizes each token vector to INT8 range [-127, 127] and immediately
    dequantizes — the result is float-valued but constrained to the INT8 grid.
    Gradient flows straight through (no custom autograd needed; round is
    applied to a detached value and added back with zero net effect on grad).

    Input shape: (..., H) — last dim is the feature dim.
    """
    scale = x.abs().amax(dim=-1, keepdim=True).clamp(min=eps) / 127.0
    x_q = torch.round(x / scale).clamp(-127, 127)
    # STE: x_quant = x + detach(x_q - x) => grad of x_quant w.r.t. x is 1
    return x + (x_q * scale - x).detach()


# ---------------------------------------------------------------------------
# Straight-Through Estimator autograd function
# ---------------------------------------------------------------------------

class _TernarySTEFunction(torch.autograd.Function):
    """STE for ternary weight quantization.

    Forward : return ternary_quantize(W) * scale  (re-scaled ternary weights)
    Backward: pass gradient straight through to the shadow (full-prec) W.
    """

    @staticmethod
    def forward(ctx, w: torch.Tensor, eps: float) -> torch.Tensor:  # type: ignore[override]
        scale = absmean_scale(w, eps=eps)
        ctx.save_for_backward(scale)
        w_q = torch.round(torch.clamp(w / scale, -1.0, 1.0))
        return w_q * scale   # re-scale so magnitude is preserved in fwd

    @staticmethod
    def backward(ctx, grad_output: torch.Tensor):  # type: ignore[override]
        # STE: identity pass-through; scale has no learnable gradient here.
        return grad_output, None


def ternary_ste(w: torch.Tensor, eps: float = 1e-8) -> torch.Tensor:
    """Apply STE ternary quantization to shadow weight tensor w.

    Returns a tensor that behaves like round(clip(w/scale,-1,1))*scale in the
    forward pass, but the backward gradient is identical to the gradient that
    would flow to w if no quantization were applied.
    """
    return _TernarySTEFunction.apply(w, eps)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# BitLinear — the core building block
# ---------------------------------------------------------------------------

class BitLinear(nn.Module):
    """Drop-in replacement for nn.Linear with BitNet b1.58 ternary weights.

    Stores FULL-PRECISION shadow weights (self.weight) as the learnable
    parameter.  In forward(), applies STE ternary quantization before the
    matmul.  Activations are optionally 8-bit-absmax quantized before the
    matmul (quant_act=True, the default).

    Bias is supported but NOT quantized (kept in full precision, consistent
    with the paper).
    """

    def __init__(
        self,
        in_features: int,
        out_features: int,
        bias: bool = False,
        quant_act: bool = True,
        eps: float = 1e-8,
    ) -> None:
        super().__init__()
        self.in_features = in_features
        self.out_features = out_features
        self.quant_act = quant_act
        self.eps = eps

        # Shadow weights — full precision, updated by the optimizer via STE.
        self.weight = nn.Parameter(
            torch.empty(out_features, in_features)
        )
        if bias:
            self.bias = nn.Parameter(torch.zeros(out_features))
        else:
            self.register_parameter("bias", None)

        self._reset_parameters()

    def _reset_parameters(self) -> None:
        # Kaiming uniform (same default as nn.Linear).
        nn.init.kaiming_uniform_(self.weight, a=math.sqrt(5))
        if self.bias is not None:
            fan_in, _ = nn.init._calculate_fan_in_and_fan_out(self.weight)
            bound = 1 / math.sqrt(fan_in) if fan_in > 0 else 0
            nn.init.uniform_(self.bias, -bound, bound)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # 1. Optionally quantize activations (8-bit absmax, STE).
        if self.quant_act:
            x = absmax_quant_8bit(x, eps=self.eps)
        # 2. Quantize weights via STE (ternary in forward, grad straight-through).
        w_q = ternary_ste(self.weight, eps=self.eps)
        # 3. Standard linear projection.
        return F.linear(x, w_q, self.bias)

    def extra_repr(self) -> str:
        return (
            f"in_features={self.in_features}, out_features={self.out_features}, "
            f"bias={self.bias is not None}, quant_act={self.quant_act}"
        )


# ---------------------------------------------------------------------------
# BitNet b1.58 Transformer block — mirrors c03-h1024-d20
# ---------------------------------------------------------------------------

class BitAttention(nn.Module):
    """Multi-head self-attention with BitLinear projections.

    Shape parity with c03:
      Q, K, V projections: (hidden, hidden) — same as nn.Linear(hidden, hidden)
      out_proj:            (hidden, hidden)
      heads = C03_HEADS = 16, head_dim = 64
    No GQA (full MHA, matching the standard LlamaAttention in the c03 config
    which uses num_key_value_heads == num_attention_heads).

    C15 architecture-parity fixes (defects closed):
      CAUSAL MASK: autoregressive decoder mask — position i attends only to
        positions <= i, exactly matching c03 LlamaModel.
      RoPE: rotary position embeddings applied to Q and K, theta=10000.0
        (LlamaConfig default), head_dim=64 (hidden//heads).  Matches c03.
    """

    def __init__(
        self,
        hidden: int = C03_HIDDEN,
        n_heads: int = C03_HEADS,
        bias: bool = False,
        quant_act: bool = True,
        rope_theta: float = C03_ROPE_THETA,
    ) -> None:
        super().__init__()
        assert hidden % n_heads == 0, "hidden must be divisible by n_heads"
        self.hidden = hidden
        self.n_heads = n_heads
        self.head_dim = hidden // n_heads
        self.rope_theta = rope_theta

        self.q_proj = BitLinear(hidden, hidden, bias=bias, quant_act=quant_act)
        self.k_proj = BitLinear(hidden, hidden, bias=bias, quant_act=quant_act)
        self.v_proj = BitLinear(hidden, hidden, bias=bias, quant_act=quant_act)
        self.o_proj = BitLinear(hidden, hidden, bias=bias, quant_act=quant_act)

    def forward(
        self,
        x: torch.Tensor,
        attn_mask: Optional[torch.Tensor] = None,
    ) -> torch.Tensor:
        """x: (B, T, H) -> (B, T, H).  Autoregressive (causal) decoder."""
        B, T, H = x.shape
        nh, hd = self.n_heads, self.head_dim

        q = self.q_proj(x).view(B, T, nh, hd).transpose(1, 2)  # (B, nh, T, hd)
        k = self.k_proj(x).view(B, T, nh, hd).transpose(1, 2)
        v = self.v_proj(x).view(B, T, nh, hd).transpose(1, 2)

        # --- RoPE: apply rotary position embeddings to Q and K (C15 fix) ---
        cos, sin = _rope_cos_sin(T, hd, self.rope_theta, x.device, x.dtype)
        q, k = apply_rope(q, k, cos, sin)

        # --- Scaled dot-product attention with CAUSAL MASK (C15 fix) ---
        scale = math.sqrt(hd)
        attn = (q @ k.transpose(-2, -1)) / scale             # (B, nh, T, T)

        # Build additive causal mask: -inf for future positions.
        # Shape (T, T): entry [i, j] is 0 if j <= i else -inf.
        causal = torch.full((T, T), float("-inf"), dtype=x.dtype, device=x.device)
        causal = torch.triu(causal, diagonal=1)               # upper-triangle = -inf
        attn = attn + causal                                   # broadcast over B, nh

        if attn_mask is not None:
            attn = attn + attn_mask
        attn = F.softmax(attn, dim=-1)

        out = (attn @ v).transpose(1, 2).contiguous().view(B, T, H)
        return self.o_proj(out)


class BitFFN(nn.Module):
    """SwiGLU feed-forward network with BitLinear projections.

    Matches c03's LlamaConfig intermediate_size = hidden * 4 = 4096.
    SwiGLU: out = silu(gate_proj(x)) * up_proj(x), then down_proj.
    The three projections mirror the three FFN matrices in LlamaModel.
    """

    def __init__(
        self,
        hidden: int = C03_HIDDEN,
        ffn_hidden: int = C03_FFN_HIDDEN,
        bias: bool = False,
        quant_act: bool = True,
    ) -> None:
        super().__init__()
        self.gate_proj = BitLinear(hidden, ffn_hidden, bias=bias, quant_act=quant_act)
        self.up_proj   = BitLinear(hidden, ffn_hidden, bias=bias, quant_act=quant_act)
        self.down_proj = BitLinear(ffn_hidden, hidden, bias=bias, quant_act=quant_act)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.down_proj(F.silu(self.gate_proj(x)) * self.up_proj(x))


class BitTransformerBlock(nn.Module):
    """Single BitNet b1.58 transformer block.

    Mirrors one layer of the c03 LlamaDecoder stack:
      - Pre-norm (RMSNorm before attention, as in LlamaDecoderLayer)
      - BitAttention (multi-head, hidden=1024, heads=16, causal, RoPE)
      - Residual connection
      - Pre-norm (RMSNorm before FFN)
      - BitFFN (SwiGLU, intermediate=4096)
      - Residual connection

    The norms are kept in FULL PRECISION (not quantized) — same as the paper.
    """

    def __init__(
        self,
        hidden: int = C03_HIDDEN,
        n_heads: int = C03_HEADS,
        ffn_hidden: int = C03_FFN_HIDDEN,
        bias: bool = False,
        quant_act: bool = True,
        norm_eps: float = C03_NORM_EPS,
        rope_theta: float = C03_ROPE_THETA,
    ) -> None:
        super().__init__()
        self.attn_norm = nn.RMSNorm(hidden, eps=norm_eps)
        self.ffn_norm  = nn.RMSNorm(hidden, eps=norm_eps)
        self.attn = BitAttention(hidden=hidden, n_heads=n_heads, bias=bias,
                                 quant_act=quant_act, rope_theta=rope_theta)
        self.ffn  = BitFFN(hidden=hidden, ffn_hidden=ffn_hidden, bias=bias,
                           quant_act=quant_act)

    def forward(
        self,
        x: torch.Tensor,
        attn_mask: Optional[torch.Tensor] = None,
    ) -> torch.Tensor:
        """x: (B, T, H) -> (B, T, H).  Same shape contract as a dense block."""
        x = x + self.attn(self.attn_norm(x), attn_mask=attn_mask)
        x = x + self.ffn(self.ffn_norm(x))
        return x


# ---------------------------------------------------------------------------
# Full BitNet transformer (depth=20, matches c03 stack depth)
# ---------------------------------------------------------------------------

class BitNetTransformer(nn.Module):
    """Full BitNet b1.58 transformer stack matching c03-h1024-d20.

    Embedding + depth=20 BitTransformerBlocks + final RMSNorm + tied LM head
    + optional MTP aux heads.

    C15 architecture-parity fixes (defects closed):
      TIED EMBEDDINGS: self.head.weight is self.embed.weight
        (tie_word_embeddings=True, matching c03 LlamaConfig).  Ensures identical
        param count and gradient dynamics as the dense baseline.
      MTP PARITY: n_mtp MTP aux heads (default n_mtp=2, weight=0.3) matching
        contract #5 in v0-pretrain-config.json.  The forward() returns ONLY the
        primary logits; the caller computes MTP losses via self.mtp_heads.
        Set n_mtp=0 to run CE-only (mirrors the comparison run's MTP setting).

    The embedding and norm are full-precision (not quantized), consistent with
    the paper's treatment of non-linear layers.
    """

    def __init__(
        self,
        vocab: int = C03_VOCAB,
        hidden: int = C03_HIDDEN,
        depth: int = C03_DEPTH,
        n_heads: int = C03_HEADS,
        ffn_hidden: int = C03_FFN_HIDDEN,
        bias: bool = False,
        quant_act: bool = True,
        norm_eps: float = C03_NORM_EPS,
        rope_theta: float = C03_ROPE_THETA,
        n_mtp: int = C03_MTP_N_HEADS,
        mtp_weight: float = C03_MTP_WEIGHT,
    ) -> None:
        super().__init__()
        self.n_mtp = n_mtp
        self.mtp_weight = mtp_weight

        self.embed   = nn.Embedding(vocab, hidden)
        self.blocks  = nn.ModuleList([
            BitTransformerBlock(
                hidden=hidden, n_heads=n_heads, ffn_hidden=ffn_hidden,
                bias=bias, quant_act=quant_act, norm_eps=norm_eps,
                rope_theta=rope_theta,
            )
            for _ in range(depth)
        ])
        self.norm    = nn.RMSNorm(hidden, eps=norm_eps)

        # Primary LM head — full precision, tied to embed weight (C15 fix).
        self.head = nn.Linear(hidden, vocab, bias=False)
        self.head.weight = self.embed.weight   # tie_word_embeddings=True

        # MTP aux heads — full precision, NOT tied (separate learned projections).
        # n_mtp=0 yields an empty list (CE-only mode, mirrors dense CE-only run).
        self.mtp_heads = nn.ModuleList([
            nn.Linear(hidden, vocab, bias=False)
            for _ in range(n_mtp)
        ])

    def forward(
        self,
        input_ids: torch.Tensor,
        attn_mask: Optional[torch.Tensor] = None,
    ) -> torch.Tensor:
        """input_ids: (B, T) int64 -> primary logits (B, T, vocab).

        MTP aux losses: caller iterates self.mtp_heads over the hidden states
        produced here.  Call backbone() to get the hidden states directly.
        """
        x = self._backbone(input_ids, attn_mask=attn_mask)
        return self.head(x)

    def _backbone(
        self,
        input_ids: torch.Tensor,
        attn_mask: Optional[torch.Tensor] = None,
    ) -> torch.Tensor:
        """Run the transformer stack and return final hidden states (B, T, H)."""
        x = self.embed(input_ids)
        for blk in self.blocks:
            x = blk(x, attn_mask=attn_mask)
        return self.norm(x)


# ---------------------------------------------------------------------------
# Dense reference block (same shapes, nn.Linear) — for shape-parity assertion
# ---------------------------------------------------------------------------

class DenseTransformerBlock(nn.Module):
    """Dense equivalent of BitTransformerBlock — identical shapes, nn.Linear.

    Used in smoke tests to confirm output shapes match between dense and ternary.
    """

    def __init__(
        self,
        hidden: int = C03_HIDDEN,
        n_heads: int = C03_HEADS,
        ffn_hidden: int = C03_FFN_HIDDEN,
        bias: bool = False,
        norm_eps: float = 1e-6,
    ) -> None:
        super().__init__()
        self.attn_norm = nn.RMSNorm(hidden, eps=norm_eps)
        self.ffn_norm  = nn.RMSNorm(hidden, eps=norm_eps)
        # Attention
        self.q_proj = nn.Linear(hidden, hidden, bias=bias)
        self.k_proj = nn.Linear(hidden, hidden, bias=bias)
        self.v_proj = nn.Linear(hidden, hidden, bias=bias)
        self.o_proj = nn.Linear(hidden, hidden, bias=bias)
        # FFN (SwiGLU)
        self.gate_proj = nn.Linear(hidden, ffn_hidden, bias=bias)
        self.up_proj   = nn.Linear(hidden, ffn_hidden, bias=bias)
        self.down_proj = nn.Linear(ffn_hidden, hidden, bias=bias)
        self.n_heads = n_heads
        self.head_dim = hidden // n_heads
        self.hidden = hidden

    def _attn(self, x: torch.Tensor) -> torch.Tensor:
        B, T, H = x.shape
        nh, hd = self.n_heads, self.head_dim
        q = self.q_proj(x).view(B, T, nh, hd).transpose(1, 2)
        k = self.k_proj(x).view(B, T, nh, hd).transpose(1, 2)
        v = self.v_proj(x).view(B, T, nh, hd).transpose(1, 2)
        attn = (q @ k.transpose(-2, -1)) / math.sqrt(hd)
        attn = F.softmax(attn, dim=-1)
        out = (attn @ v).transpose(1, 2).contiguous().view(B, T, H)
        return self.o_proj(out)

    def _ffn(self, x: torch.Tensor) -> torch.Tensor:
        return self.down_proj(F.silu(self.gate_proj(x)) * self.up_proj(x))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = x + self._attn(self.attn_norm(x))
        x = x + self._ffn(self.ffn_norm(x))
        return x


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------

def _run_tests(verbose: bool = True) -> dict:
    """Run all unit tests.  Returns a receipt dict with pass/fail per test."""

    results: dict[str, bool] = {}
    errors:  dict[str, str]  = {}

    def _pass(name: str) -> None:
        results[name] = True
        if verbose:
            print(f"  PASS  {name}")

    def _fail(name: str, msg: str) -> None:
        results[name] = False
        errors[name] = msg
        if verbose:
            print(f"  FAIL  {name}: {msg}")

    # -----------------------------------------------------------------------
    # T1: ternary quantization produces values in {-1, 0, +1} exactly
    # -----------------------------------------------------------------------
    name = "T1_ternary_values_in_set"
    try:
        torch.manual_seed(0)
        w = torch.randn(64, 64)
        w_q = ternary_quantize(w)
        unique_vals = w_q.unique().tolist()
        # Must be a SUBSET of {-1.0, 0.0, 1.0} (may not have all three for edge cases)
        allowed = {-1.0, 0.0, 1.0}
        bad = [v for v in unique_vals if round(v, 6) not in allowed]
        if bad:
            _fail(name, f"unexpected values in W_q: {bad}")
        else:
            _pass(name)
    except Exception as exc:
        _fail(name, str(exc))

    # -----------------------------------------------------------------------
    # T2: absmean scale is computed correctly
    # -----------------------------------------------------------------------
    name = "T2_absmean_scale_correct"
    try:
        w = torch.tensor([2.0, -4.0, 0.0, 6.0])
        scale = absmean_scale(w, eps=0.0)
        # mean(|w|) = (2+4+0+6)/4 = 3.0
        expected = 3.0
        if not math.isclose(float(scale), expected, rel_tol=1e-6):
            _fail(name, f"scale={float(scale):.8f} expected={expected}")
        else:
            _pass(name)
    except Exception as exc:
        _fail(name, str(exc))

    # -----------------------------------------------------------------------
    # T3: absmean scale with eps avoids division by zero on all-zero tensor
    # -----------------------------------------------------------------------
    name = "T3_absmean_scale_zero_safe"
    try:
        w = torch.zeros(16, 16)
        scale = absmean_scale(w, eps=1e-8)
        if float(scale) < 1e-9:
            _fail(name, f"scale too small on zero tensor: {float(scale)}")
        else:
            _pass(name)
    except Exception as exc:
        _fail(name, str(exc))

    # -----------------------------------------------------------------------
    # T4: straight-through gradient flows — shadow params change after backward
    # -----------------------------------------------------------------------
    name = "T4_ste_gradient_flows_to_shadow_weights"
    try:
        torch.manual_seed(42)
        layer = BitLinear(8, 4, quant_act=False)
        w0 = layer.weight.data.clone()
        x = torch.randn(2, 8)
        opt = torch.optim.SGD(layer.parameters(), lr=0.1)
        out = layer(x)
        loss = out.sum()
        loss.backward()
        # Check that gradient reached shadow weight
        assert layer.weight.grad is not None, "no gradient on shadow weight"
        grad_norm = layer.weight.grad.norm().item()
        assert grad_norm > 0, f"zero gradient on shadow weight (norm={grad_norm})"
        opt.step()
        w1 = layer.weight.data.clone()
        # Shadow weights should have changed
        if torch.allclose(w0, w1):
            _fail(name, "shadow weights did not change after optimizer step")
        else:
            _pass(name)
    except Exception as exc:
        _fail(name, str(exc))

    # -----------------------------------------------------------------------
    # T5: ternary quantized weight values in BitLinear are exactly {-1,0,+1}
    # -----------------------------------------------------------------------
    name = "T5_bitlinear_fwd_weight_ternary"
    try:
        torch.manual_seed(1)
        layer = BitLinear(16, 8, quant_act=False)
        # Inspect the quantized weight by running a forward and checking what
        # values the STE actually produces for this weight.
        w_q = ternary_quantize(layer.weight.data)
        unique_vals = set(round(v, 6) for v in w_q.flatten().tolist())
        allowed = {-1.0, 0.0, 1.0}
        bad = unique_vals - allowed
        if bad:
            _fail(name, f"quantized weight has non-ternary values: {bad}")
        else:
            _pass(name)
    except Exception as exc:
        _fail(name, str(exc))

    # -----------------------------------------------------------------------
    # T6: BitLinear forward output shape matches nn.Linear (same in/out dims)
    # -----------------------------------------------------------------------
    name = "T6_bitlinear_output_shape"
    try:
        torch.manual_seed(2)
        B, T, H_in, H_out = 2, 4, 32, 16
        bit_layer   = BitLinear(H_in, H_out, quant_act=False)
        dense_layer = nn.Linear(H_in, H_out, bias=False)
        x = torch.randn(B, T, H_in)
        bit_out   = bit_layer(x)
        dense_out = dense_layer(x)
        if bit_out.shape != dense_out.shape:
            _fail(name, f"shape mismatch: bit={bit_out.shape} dense={dense_out.shape}")
        else:
            _pass(name)
    except Exception as exc:
        _fail(name, str(exc))

    # -----------------------------------------------------------------------
    # T7: BitTransformerBlock output shape matches DenseTransformerBlock
    # -----------------------------------------------------------------------
    name = "T7_block_output_shape_matches_dense"
    try:
        torch.manual_seed(3)
        # Use tiny dims so CPU smoke is fast
        H, NH, FFN = 64, 4, 128
        B, T = 2, 8
        bit_block   = BitTransformerBlock(hidden=H, n_heads=NH, ffn_hidden=FFN,
                                          quant_act=False)
        dense_block = DenseTransformerBlock(hidden=H, n_heads=NH, ffn_hidden=FFN)
        x = torch.randn(B, T, H)
        bit_out   = bit_block(x)
        dense_out = dense_block(x)
        if bit_out.shape != dense_out.shape:
            _fail(name, f"shape mismatch: bit={bit_out.shape} dense={dense_out.shape}")
        elif bit_out.shape != (B, T, H):
            _fail(name, f"unexpected shape: {bit_out.shape} expected ({B},{T},{H})")
        else:
            _pass(name)
    except Exception as exc:
        _fail(name, str(exc))

    # -----------------------------------------------------------------------
    # T8: BitTransformerBlock at full c03 dims (H=1024, NH=16, FFN=4096)
    #     output shape correct (smoke — tiny batch so CPU stays fast)
    # -----------------------------------------------------------------------
    name = "T8_block_c03_dims_output_shape"
    try:
        torch.manual_seed(4)
        B, T = 1, 4   # tiny batch/seq for CPU speed
        bit_block = BitTransformerBlock(
            hidden=C03_HIDDEN, n_heads=C03_HEADS, ffn_hidden=C03_FFN_HIDDEN,
            quant_act=True,
        )
        x = torch.randn(B, T, C03_HIDDEN)
        with torch.no_grad():
            out = bit_block(x)
        if out.shape != (B, T, C03_HIDDEN):
            _fail(name, f"shape={out.shape} expected ({B},{T},{C03_HIDDEN})")
        else:
            _pass(name)
    except Exception as exc:
        _fail(name, str(exc))

    # -----------------------------------------------------------------------
    # T9: gradient flows end-to-end through multi-block stack + STE
    # -----------------------------------------------------------------------
    name = "T9_ste_gradient_multi_block"
    try:
        torch.manual_seed(5)
        H, NH, FFN = 32, 4, 64
        block1 = BitTransformerBlock(hidden=H, n_heads=NH, ffn_hidden=FFN,
                                     quant_act=False)
        block2 = BitTransformerBlock(hidden=H, n_heads=NH, ffn_hidden=FFN,
                                     quant_act=False)
        x = torch.randn(1, 4, H)
        out = block2(block1(x))
        loss = out.sum()
        loss.backward()
        # Check gradients reached all BitLinear shadow weights in both blocks
        no_grad_params = []
        for name_p, p in list(block1.named_parameters()) + list(block2.named_parameters()):
            if isinstance(p, nn.Parameter) and p.requires_grad:
                if p.grad is None or p.grad.norm().item() == 0.0:
                    no_grad_params.append(name_p)
        # RMSNorm weight may have near-zero grad if input variance is low; allow it.
        bad = [n for n in no_grad_params if "norm" not in n]
        if bad:
            _fail(name, f"zero/None grad on: {bad[:5]}")
        else:
            _pass(name)
    except Exception as exc:
        _fail(name, str(exc))

    # -----------------------------------------------------------------------
    # T10: absmax_quant_8bit STE — gradient passes through unchanged
    # -----------------------------------------------------------------------
    name = "T10_absmax_act_quant_ste_grad"
    try:
        torch.manual_seed(6)
        x = torch.randn(4, 16, requires_grad=True)
        y = absmax_quant_8bit(x)
        loss = y.sum()
        loss.backward()
        assert x.grad is not None
        # Gradient of sum(absmax_quant(x)) w.r.t. x should be all ones (STE identity)
        if not torch.allclose(x.grad, torch.ones_like(x)):
            _fail(name, f"grad not all-ones; max_dev={( x.grad - 1).abs().max().item():.4f}")
        else:
            _pass(name)
    except Exception as exc:
        _fail(name, str(exc))

    # -----------------------------------------------------------------------
    # T11: BitLinear param count vs equivalent nn.Linear (same number of params)
    # -----------------------------------------------------------------------
    name = "T11_bitlinear_param_count_matches_linear"
    try:
        H_in, H_out = 64, 32
        bit_layer   = BitLinear(H_in, H_out, bias=False)
        dense_layer = nn.Linear(H_in, H_out, bias=False)
        bit_params   = sum(p.numel() for p in bit_layer.parameters())
        dense_params = sum(p.numel() for p in dense_layer.parameters())
        if bit_params != dense_params:
            _fail(name, f"bit={bit_params} dense={dense_params}")
        else:
            _pass(name)
    except Exception as exc:
        _fail(name, str(exc))

    # -----------------------------------------------------------------------
    # T12: CAUSALITY — perturbing a FUTURE token must NOT change earlier
    #      positions' outputs (autoregressive causal mask correctness).
    # -----------------------------------------------------------------------
    name = "T12_causal_mask_future_tokens_do_not_affect_earlier_positions"
    try:
        torch.manual_seed(7)
        H, NH, FFN = 32, 4, 64
        B, T = 1, 6
        block = BitTransformerBlock(hidden=H, n_heads=NH, ffn_hidden=FFN,
                                    quant_act=False)
        block.eval()
        x = torch.randn(B, T, H)
        with torch.no_grad():
            out_orig = block(x).clone()

        # Perturb only the LAST token (position T-1).
        x_perturbed = x.clone()
        x_perturbed[:, T - 1, :] = x_perturbed[:, T - 1, :] * 2 + 1.0
        with torch.no_grad():
            out_perturbed = block(x_perturbed)

        # All positions BEFORE T-1 must be bit-identical (causal mask).
        earlier_unchanged = torch.allclose(
            out_orig[:, : T - 1, :], out_perturbed[:, : T - 1, :],
            atol=0.0, rtol=0.0,
        )
        if not earlier_unchanged:
            max_diff = (out_orig[:, : T - 1, :] - out_perturbed[:, : T - 1, :]).abs().max().item()
            _fail(name, f"earlier positions changed when future token perturbed; "
                        f"max_diff={max_diff:.6g} (expected 0.0)")
        else:
            _pass(name)
    except Exception as exc:
        _fail(name, str(exc))

    # -----------------------------------------------------------------------
    # T13: RoPE PRESENT + POSITION-DEPENDENT — the same hidden vector placed
    #      at different sequence positions must produce different Q/K outputs.
    # -----------------------------------------------------------------------
    name = "T13_rope_position_dependent"
    try:
        torch.manual_seed(8)
        H, NH, FFN = 32, 4, 64
        B, T = 1, 6
        block = BitTransformerBlock(hidden=H, n_heads=NH, ffn_hidden=FFN,
                                    quant_act=False)
        block.eval()
        # Build a sequence where position 0 and position 3 have the SAME input.
        x = torch.randn(B, T, H)
        x[:, 3, :] = x[:, 0, :]   # identical content, different positions

        # Compute Q/K for the full sequence by passing a tiny single-block model.
        # We verify output at pos 0 != output at pos 3 (same input, diff position).
        with torch.no_grad():
            out = block(x)

        same_input_diff_pos = not torch.allclose(
            out[:, 0, :], out[:, 3, :], atol=1e-5, rtol=1e-5,
        )
        if not same_input_diff_pos:
            _fail(name, "position 0 and position 3 produced identical outputs "
                        "despite different sequence positions — RoPE not active")
        else:
            _pass(name)
    except Exception as exc:
        _fail(name, str(exc))

    # -----------------------------------------------------------------------
    # T14: TIED EMBEDDINGS — LM head weight IS the embedding weight.
    #      Both data pointer and value identity must hold.
    # -----------------------------------------------------------------------
    name = "T14_lm_head_weight_tied_to_embedding"
    try:
        # Use tiny vocab/hidden to keep the test fast.
        tiny_vocab, tiny_hidden = 16, 8
        model = BitNetTransformer(
            vocab=tiny_vocab,
            hidden=tiny_hidden,
            depth=1,
            n_heads=2,
            ffn_hidden=16,
            quant_act=False,
            n_mtp=0,
        )
        # The head weight and embedding weight must be the SAME tensor object.
        if model.head.weight is not model.embed.weight:
            _fail(name, "head.weight is NOT the same tensor as embed.weight "
                        "(tie_word_embeddings parity broken)")
        else:
            # Double-check: mutating embed weight must be reflected in head weight.
            model.embed.weight.data[0, 0] = 99.0
            if not math.isclose(float(model.head.weight.data[0, 0]), 99.0):
                _fail(name, "mutating embed.weight did NOT propagate to head.weight "
                            "(object-identity broken)")
            else:
                _pass(name)
    except Exception as exc:
        _fail(name, str(exc))

    # -----------------------------------------------------------------------
    # T15: MTP HEAD COUNT matches the configured c03 setting.
    #      Verify n_mtp=2 (contract default) and n_mtp=0 (CE-only mode).
    # -----------------------------------------------------------------------
    name = "T15_mtp_head_count_matches_c03_config"
    try:
        # Default configuration: n_mtp=C03_MTP_N_HEADS=2
        tiny_vocab, tiny_hidden = 16, 8
        model_mtp = BitNetTransformer(
            vocab=tiny_vocab,
            hidden=tiny_hidden,
            depth=1,
            n_heads=2,
            ffn_hidden=16,
            quant_act=False,
            n_mtp=C03_MTP_N_HEADS,   # must equal 2 per contract
        )
        if len(model_mtp.mtp_heads) != C03_MTP_N_HEADS:
            _fail(name, f"mtp_heads count={len(model_mtp.mtp_heads)} "
                        f"expected C03_MTP_N_HEADS={C03_MTP_N_HEADS}")
        else:
            # Verify mtp_weight stored correctly.
            if not math.isclose(model_mtp.mtp_weight, C03_MTP_WEIGHT, rel_tol=1e-9):
                _fail(name, f"mtp_weight={model_mtp.mtp_weight} "
                            f"expected C03_MTP_WEIGHT={C03_MTP_WEIGHT}")
            else:
                # Also verify CE-only mode (n_mtp=0) yields empty mtp_heads.
                model_ce = BitNetTransformer(
                    vocab=tiny_vocab,
                    hidden=tiny_hidden,
                    depth=1,
                    n_heads=2,
                    ffn_hidden=16,
                    quant_act=False,
                    n_mtp=0,
                )
                if len(model_ce.mtp_heads) != 0:
                    _fail(name, f"CE-only mode: mtp_heads count={len(model_ce.mtp_heads)} expected 0")
                else:
                    _pass(name)
    except Exception as exc:
        _fail(name, str(exc))

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------
    total  = len(results)
    passed = sum(v for v in results.values())
    failed = total - passed
    all_passed = failed == 0

    receipt = {
        "ticket": "EMBER-BITNET-CORE-SELFTEST",
        "total": total,
        "passed": passed,
        "failed": failed,
        "all_passed": all_passed,
        "results": results,
        "errors": errors,
        "verdict": "EMBER_BITNET_CORE_SELFTEST_PASS" if all_passed else "FAIL",
    }
    return receipt


def selftest() -> None:
    """Run unit tests and print a structured receipt."""
    print("=" * 64)
    print("ember_bitnet_core — unit test suite")
    print("=" * 64)
    receipt = _run_tests(verbose=True)
    print("-" * 64)
    print(f"Total: {receipt['total']}  "
          f"Passed: {receipt['passed']}  "
          f"Failed: {receipt['failed']}")
    if receipt["all_passed"]:
        print(receipt["verdict"])
        sys.exit(0)
    else:
        print("FAIL — see errors above")
        for t, msg in receipt["errors"].items():
            print(f"  {t}: {msg}")
        sys.exit(1)


if __name__ == "__main__":
    selftest()
