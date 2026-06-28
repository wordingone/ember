"""ember_model_v0_multimodal.py — architecture extension for ember-multimodal-v0.

Implements NC2-own §8 architecture locks for the multimodal config
(config/ember-multimodal-v0-pretrain-config.json, #26, 2026-06-14).

Locks implemented here:
  Lock 2 — inputs_embeds splice path
  Lock 3 — per-span bidirectional attention in causal mask
  Lock 4 — 2D x/y RoPE split (factorized, head_dim=64)
  QK-norm — L2 normalization on Q and K before attention scores

Lock 1 (reserved vocab band) is in the tokenizer (TOKENIZER-FREEZE-V0). Done.

CPU-safe: all top-level imports are stdlib. torch-dependent paths are inside
functions/methods so the module can be imported for selftest on pure CPU.
"""

from __future__ import annotations

import math
from typing import Optional

# ---------------------------------------------------------------------------
# QK-norm (Lock + QK-norm requirement)
# ---------------------------------------------------------------------------

class QKNorm:
    """L2-normalise Q and K before computing attention scores.

    Unretrofittable: must be wired from step 0. Applied per head.

    Usage::
        qk_norm = QKNorm(dim=64)
        q, k = qk_norm(q, k)   # both normalized; v unchanged
    """

    def __init__(self, dim: int, eps: float = 1e-6) -> None:
        import torch.nn as nn
        self.q_norm = nn.LayerNorm(dim, elementwise_affine=True, eps=eps)
        self.k_norm = nn.LayerNorm(dim, elementwise_affine=True, eps=eps)

    def __call__(self, q, k):
        return self.q_norm(q), self.k_norm(k)


# ---------------------------------------------------------------------------
# 2D RoPE factorized (Lock 4)
# ---------------------------------------------------------------------------

def _rope_1d(seq_len: int, head_dim: int, base: float = 10000.0):
    """Standard 1D RoPE frequency table for seq_len positions.

    Returns cos, sin tensors of shape (seq_len, head_dim).
    """
    import torch
    theta = 1.0 / (base ** (torch.arange(0, head_dim, 2).float() / head_dim))
    pos = torch.arange(seq_len).float()
    freqs = torch.outer(pos, theta)          # (seq_len, head_dim//2)
    cos = freqs.cos()
    sin = freqs.sin()
    cos = torch.cat([cos, cos], dim=-1)      # (seq_len, head_dim)
    sin = torch.cat([sin, sin], dim=-1)      # (seq_len, head_dim)
    return cos, sin


def _rotate_half(x):
    """Rotate x by negating and interleaving halves."""
    import torch
    x1, x2 = x[..., : x.shape[-1] // 2], x[..., x.shape[-1] // 2 :]
    return torch.cat([-x2, x1], dim=-1)


def apply_rope_1d(q, k, cos, sin):
    """Apply 1D RoPE to Q and K vectors.

    q, k: (..., seq_len, head_dim)
    cos, sin: (seq_len, head_dim) — broadcasted
    """
    q = (q * cos) + (_rotate_half(q) * sin)
    k = (k * cos) + (_rotate_half(k) * sin)
    return q, k


def apply_rope_2d_factorized(q, k, x_pos, y_pos, head_dim: int, base: float = 10000.0):
    """2D factorized RoPE for image token positions (Lock 4).

    head_dim must be divisible by 4 (head_dim%4==0; 64%4==0 SATISFIED).

    x_pos: (batch, n_image_tokens) integer x-coordinates (column index)
    y_pos: (batch, n_image_tokens) integer y-coordinates (row index)
    q, k:  (batch, n_heads, n_image_tokens, head_dim)

    First head_dim//2 dims receive x-RoPE; last head_dim//2 dims receive y-RoPE.
    """
    import torch
    half = head_dim // 2
    theta = 1.0 / (base ** (torch.arange(0, half, 2, device=q.device).float() / half))

    def pos_to_cos_sin(pos):
        # pos: (batch, n_tokens)
        freqs = pos.float().unsqueeze(-1) * theta.unsqueeze(0).unsqueeze(0)  # (B, T, half//2)
        cos = freqs.cos()
        sin = freqs.sin()
        cos = torch.cat([cos, cos], dim=-1)  # (B, T, half)
        sin = torch.cat([sin, sin], dim=-1)
        return cos, sin

    cos_x, sin_x = pos_to_cos_sin(x_pos)   # (B, T, half)
    cos_y, sin_y = pos_to_cos_sin(y_pos)   # (B, T, half)

    q_x = q[..., :half]   # (B, H, T, half)
    q_y = q[..., half:]
    k_x = k[..., :half]
    k_y = k[..., half:]

    cos_x = cos_x.unsqueeze(1)  # (B, 1, T, half)
    sin_x = sin_x.unsqueeze(1)
    cos_y = cos_y.unsqueeze(1)
    sin_y = sin_y.unsqueeze(1)

    q_x = (q_x * cos_x) + (_rotate_half(q_x) * sin_x)
    q_y = (q_y * cos_y) + (_rotate_half(q_y) * sin_y)
    k_x = (k_x * cos_x) + (_rotate_half(k_x) * sin_x)
    k_y = (k_y * cos_y) + (_rotate_half(k_y) * sin_y)

    q = torch.cat([q_x, q_y], dim=-1)
    k = torch.cat([k_x, k_y], dim=-1)
    return q, k


# ---------------------------------------------------------------------------
# Bidirectional span mask (Lock 3)
# ---------------------------------------------------------------------------

def build_span_mask(
    seq_len: int,
    span_boundaries: list[tuple[int, int]],
    dtype=None,
    device=None,
):
    """Build causal attention mask with full bidirectionality within image spans (Lock 3).

    Standard causal mask = lower-triangular (token i can attend to tokens 0..i).
    Within each span (start, end): ALL positions attend to ALL positions in the span.
    Cross-span structure: image spans obey causal ordering with respect to each other
    and to text tokens (they can attend to all prior tokens but not future ones outside
    the span).

    Args:
        seq_len:          total sequence length
        span_boundaries:  list of (start, end) in [0, seq_len). end is exclusive.
                          Empty list → pure causal mask (text-only, identical to v0).
        dtype:            mask dtype (default float32; caller may use bfloat16)
        device:           torch device

    Returns:
        mask: (seq_len, seq_len) additive attention mask.
              0.0 = attend, -inf = masked.

    Design note:
        Additive mask: 0.0 means "this position is visible." -inf means "masked out."
        Standard usage: attn_scores = attn_scores + mask (before softmax).
    """
    import torch

    if dtype is None:
        dtype = torch.float32

    # masked_fill_ avoids 0.0 * inf = NaN (IEEE 754) from arithmetic construction.
    mask = torch.zeros(seq_len, seq_len, dtype=dtype, device=device)
    causal_upper = torch.triu(
        torch.ones(seq_len, seq_len, dtype=torch.bool, device=device), diagonal=1
    )
    mask.masked_fill_(causal_upper, float("-inf"))  # upper-tri = -inf, lower-tri = 0.0

    # For each span, open full bidirectional attention within the span.
    for start, end in span_boundaries:
        if end <= start:
            continue
        # Rows in [start, end): these positions can attend to all [start, end).
        mask[start:end, start:end] = 0.0

    return mask


# ---------------------------------------------------------------------------
# inputs_embeds splice (Lock 2)
# ---------------------------------------------------------------------------

def splice_soft_tokens(
    embed_tokens,
    input_ids,
    inputs_embeds: Optional["torch.Tensor"],
    span_boundaries: list[tuple[int, int]],
    placeholder_ids: Optional[set] = None,
):
    """Splice vision soft tokens into the embedding table output (Lock 2).

    Args:
        embed_tokens:     nn.Embedding — the model's text embedding table
        input_ids:        (batch, seq_len) integer token ids
        inputs_embeds:    (batch, n_image_tokens, hidden) vision embedder output,
                          or None for text-only forward
        span_boundaries:  list of (start, end) — where to overwrite in seq dim.
                          Must match the ordering/size of inputs_embeds patches.
        placeholder_ids:  optional set of token IDs that are placeholders
                          (for sanity-check; not enforced in production path)

    Returns:
        embeddings: (batch, seq_len, hidden) — text embeddings with image spans
                    overwritten by inputs_embeds.
    """
    # Start from text embeddings (always needed for non-image positions).
    embeddings = embed_tokens(input_ids)   # (batch, seq_len, hidden)

    if inputs_embeds is None or len(span_boundaries) == 0:
        return embeddings

    # Splice: overwrite embedding rows at image-span positions.
    offset = 0
    for start, end in span_boundaries:
        span_len = end - start
        if span_len <= 0:
            continue
        # inputs_embeds is indexed by the span in insertion order.
        soft = inputs_embeds[:, offset:offset + span_len, :]  # (batch, span_len, hidden)
        embeddings[:, start:end, :] = soft
        offset += span_len

    return embeddings


# ---------------------------------------------------------------------------
# EmberMultimodalAttention — attention layer with Locks 3+4+QK-norm
# ---------------------------------------------------------------------------

class EmberMultimodalAttention:
    """Attention layer implementing Locks 3 (span mask) + 4 (2D RoPE) + QK-norm.

    For integration: use this in place of the standard self-attention module in
    the decoder stack. The rest of the transformer (MLP, layernorm, residual)
    is unchanged from v0.

    CPU selftest: this class is used in selftest_multimodal_splice.py with small
    synthetic inputs to verify all three sub-mechanisms.
    """

    def __init__(self, hidden: int, n_heads: int, head_dim: int) -> None:
        import torch.nn as nn
        self.n_heads = n_heads
        self.head_dim = head_dim

        self.q_proj = nn.Linear(hidden, n_heads * head_dim, bias=False)
        self.k_proj = nn.Linear(hidden, n_heads * head_dim, bias=False)
        self.v_proj = nn.Linear(hidden, n_heads * head_dim, bias=False)
        self.out_proj = nn.Linear(n_heads * head_dim, hidden, bias=False)

        self.qk_norm = QKNorm(dim=head_dim)

    def parameters(self):
        return (
            list(self.q_proj.parameters())
            + list(self.k_proj.parameters())
            + list(self.v_proj.parameters())
            + list(self.out_proj.parameters())
            + list(self.qk_norm.q_norm.parameters())
            + list(self.qk_norm.k_norm.parameters())
        )

    def forward(
        self,
        x,
        span_boundaries=None,
        x_pos=None,
        y_pos=None,
        image_token_indices=None,
    ):
        """Forward pass with span mask, 2D RoPE, and QK-norm.

        Args:
            x:                   (batch, seq_len, hidden)
            span_boundaries:     list of (start, end) for image spans (Lock 3)
            x_pos:               (batch, n_image) column positions (Lock 4); None for text-only
            y_pos:               (batch, n_image) row positions (Lock 4); None for text-only
            image_token_indices: list of (start, end) image span positions for 2D RoPE
        """
        import torch
        import torch.nn.functional as F

        B, S, H = x.shape
        n_heads = self.n_heads
        d = self.head_dim

        q = self.q_proj(x).view(B, S, n_heads, d).transpose(1, 2)  # (B, H, S, d)
        k = self.k_proj(x).view(B, S, n_heads, d).transpose(1, 2)
        v = self.v_proj(x).view(B, S, n_heads, d).transpose(1, 2)

        # QK-norm (Lock / QK-norm requirement)
        q, k = self.qk_norm(q.reshape(B * n_heads * S, d), k.reshape(B * n_heads * S, d))
        q = q.view(B, n_heads, S, d)
        k = k.view(B, n_heads, S, d)

        # Lock 4: mutually exclusive RoPE — 1D for text, 2D for image (never composed).
        # Prior bug: 1D applied to ALL tokens, then 2D applied on top → double rotation
        # on image tokens. Fix: apply 1D to full sequence first, then overwrite image
        # spans with fresh 2D RoPE computed from un-rotated q, k.
        cos, sin = _rope_1d(S, d, device=x.device)
        cos4d = cos.unsqueeze(0).unsqueeze(0).to(dtype=q.dtype)
        sin4d = sin.unsqueeze(0).unsqueeze(0).to(dtype=q.dtype)

        if x_pos is not None and y_pos is not None and image_token_indices:
            # Text positions get 1D RoPE; image spans get 2D RoPE (mutually exclusive).
            # Save pre-rotation q/k so image spans use fresh input for 2D RoPE.
            q_pre, k_pre = q, k
            q, k = apply_rope_1d(q, k, cos4d, sin4d)
            # img_offset tracks how many image patches we've consumed from x_pos/y_pos.
            # Required for multi-image sequences — each span reads its own slice.
            img_offset = 0
            for (img_start, img_end) in image_token_indices:
                n_img = img_end - img_start
                ix_pos = x_pos[:, img_offset:img_offset + n_img]
                iy_pos = y_pos[:, img_offset:img_offset + n_img]
                img_offset += n_img
                q_img, k_img = apply_rope_2d_factorized(
                    q_pre[:, :, img_start:img_end, :],
                    k_pre[:, :, img_start:img_end, :],
                    ix_pos, iy_pos, d,
                )
                q[:, :, img_start:img_end, :] = q_img
                k[:, :, img_start:img_end, :] = k_img
        else:
            q, k = apply_rope_1d(q, k, cos4d, sin4d)

        # Span mask (Lock 3) — dtype matches q to avoid float32 upcast on bfloat16 paths
        mask = build_span_mask(S, span_boundaries or [], dtype=q.dtype,
                               device=x.device if hasattr(x, "device") else None)
        mask = mask.unsqueeze(0).unsqueeze(0)  # (1, 1, S, S)

        # Attention
        scale = d ** -0.5
        attn = torch.matmul(q, k.transpose(-2, -1)) * scale + mask
        attn = F.softmax(attn, dim=-1)
        out = torch.matmul(attn, v)   # (B, n_heads, S, d)
        out = out.transpose(1, 2).contiguous().view(B, S, n_heads * d)
        return self.out_proj(out)


# ---------------------------------------------------------------------------
# SwiGLU FFN + TransformerLayer (for §IV stacked 20-layer config)
# ---------------------------------------------------------------------------

class EmberSwiGLUFFN:
    """SwiGLU feed-forward block. 3 × hidden × intermediate params."""

    def __init__(self, hidden: int, intermediate: int) -> None:
        import torch.nn as nn
        self.gate_proj = nn.Linear(hidden, intermediate, bias=False)
        self.up_proj = nn.Linear(hidden, intermediate, bias=False)
        self.down_proj = nn.Linear(intermediate, hidden, bias=False)

    def parameters(self):
        return (
            list(self.gate_proj.parameters())
            + list(self.up_proj.parameters())
            + list(self.down_proj.parameters())
        )

    def forward(self, x):
        import torch.nn.functional as F
        return self.down_proj(F.silu(self.gate_proj(x)) * self.up_proj(x))


class EmberTransformerLayer:
    """Pre-norm layer: LN → attn + residual → LN → FFN + residual."""

    def __init__(self, hidden: int, n_heads: int, head_dim: int, intermediate: int) -> None:
        import torch.nn as nn
        self.pre_attn_norm = nn.LayerNorm(hidden)
        self.attention = EmberMultimodalAttention(hidden, n_heads, head_dim)
        self.pre_ffn_norm = nn.LayerNorm(hidden)
        self.ffn = EmberSwiGLUFFN(hidden, intermediate)

    def parameters(self):
        return (
            list(self.pre_attn_norm.parameters())
            + self.attention.parameters()
            + list(self.pre_ffn_norm.parameters())
            + self.ffn.parameters()
        )

    def nn_modules(self):
        return [
            self.pre_attn_norm,
            self.attention.q_proj,
            self.attention.k_proj,
            self.attention.v_proj,
            self.attention.out_proj,
            self.attention.qk_norm.q_norm,
            self.attention.qk_norm.k_norm,
            self.pre_ffn_norm,
            self.ffn.gate_proj,
            self.ffn.up_proj,
            self.ffn.down_proj,
        ]

    def forward(self, x, span_boundaries=None, x_pos=None, y_pos=None, image_token_indices=None):
        x = x + self.attention.forward(
            self.pre_attn_norm(x),
            span_boundaries=span_boundaries,
            x_pos=x_pos,
            y_pos=y_pos,
            image_token_indices=image_token_indices,
        )
        x = x + self.ffn.forward(self.pre_ffn_norm(x))
        return x


def _rope_1d(seq_len: int, head_dim: int, base: float = 10000.0, device=None):
    """RoPE helper with optional device."""
    import torch
    theta = 1.0 / (base ** (torch.arange(0, head_dim, 2, device=device).float() / head_dim))
    pos = torch.arange(seq_len, device=device).float()
    freqs = torch.outer(pos, theta)
    cos = torch.cat([freqs.cos(), freqs.cos()], dim=-1)
    sin = torch.cat([freqs.sin(), freqs.sin()], dim=-1)
    return cos, sin


# ---------------------------------------------------------------------------
# VisionEmbedder (Fuyu-style patch encoder; config: vision_embedder section)
# ---------------------------------------------------------------------------

class VisionEmbedder:
    """48×48px patch → 6912-float → Linear(6912, 1024) + LayerNorm + factorized XY pos.

    Spec: config/v0-multimodal-config.json vision_embedder:
      patch_px=48, in_dim=6912, out_dim=1024, pos_type=xy_factorized.

    Style: Fuyu-style continuous soft tokens (NOT discrete codes). Each 48×48 RGB
    patch is flattened to 6912 floats, projected, normed, then positionally encoded
    by adding learned x-position + y-position embeddings (factorized XY).

    Output is then used as inputs_embeds fed into splice_soft_tokens().
    """

    def __init__(
        self,
        in_dim: int = 6912,
        out_dim: int = 1024,
        max_pos: int = 1024,
        use_convstem: bool = False,
        latent_refine_steps: int = 0,
    ) -> None:
        import torch.nn as nn
        self.in_dim = in_dim
        self.out_dim = out_dim
        self.use_convstem = use_convstem
        self.latent_refine_steps = int(latent_refine_steps)
        if self.latent_refine_steps < 0:
            raise ValueError("latent_refine_steps must be >= 0")
        self.patch_px = int(math.sqrt(in_dim // 3))
        if self.patch_px * self.patch_px * 3 != in_dim:
            raise ValueError(f"VisionEmbedder in_dim={in_dim} is not a square RGB patch")
        if use_convstem:
            self.convstem = nn.Sequential(
                nn.Conv2d(3, 32, kernel_size=5, stride=2, padding=2, bias=False),
                nn.SiLU(),
                nn.Conv2d(32, 64, kernel_size=3, stride=2, padding=1, bias=False),
                nn.SiLU(),
                nn.AdaptiveAvgPool2d((1, 1)),
                nn.Flatten(),
            )
            self.proj = nn.Linear(64, out_dim, bias=False)
        else:
            self.convstem = None
            self.proj = nn.Linear(in_dim, out_dim, bias=False)
        self.norm = nn.LayerNorm(out_dim)
        self.x_embed = nn.Embedding(max_pos, out_dim)
        self.y_embed = nn.Embedding(max_pos, out_dim)
        if self.latent_refine_steps:
            self.refine_norm = nn.LayerNorm(out_dim)
            self.refine_gate = nn.Linear(out_dim, out_dim * 2, bias=False)
            self.refine_down = nn.Linear(out_dim * 2, out_dim, bias=False)
        else:
            self.refine_norm = None
            self.refine_gate = None
            self.refine_down = None

    def parameters(self):
        params = []
        if self.convstem is not None:
            params += list(self.convstem.parameters())
        params += list(self.proj.parameters())
        params += list(self.norm.parameters())
        params += list(self.x_embed.parameters())
        params += list(self.y_embed.parameters())
        if self.refine_norm is not None:
            params += list(self.refine_norm.parameters())
            params += list(self.refine_gate.parameters())
            params += list(self.refine_down.parameters())
        return params

    def nn_modules(self):
        mods = []
        if self.convstem is not None:
            mods.append(self.convstem)
        mods += [self.proj, self.norm, self.x_embed, self.y_embed]
        if self.refine_norm is not None:
            mods += [self.refine_norm, self.refine_gate, self.refine_down]
        return mods

    def forward(self, patches, x_pos, y_pos):
        """
        patches: (batch, n_patches, in_dim) — raw pixel vectors (float)
        x_pos:   (batch, n_patches) long  — column index (0-based)
        y_pos:   (batch, n_patches) long  — row index (0-based)
        Returns: (batch, n_patches, out_dim) soft token embeddings
        """
        if self.convstem is not None:
            B, N, D = patches.shape
            if D != self.in_dim:
                raise ValueError(f"patch dim {D} != expected {self.in_dim}")
            x = patches.reshape(B * N, self.patch_px, self.patch_px, 3).permute(0, 3, 1, 2)
            h = self.convstem(x).reshape(B, N, -1)
            h = self.norm(self.proj(h))
        else:
            h = self.norm(self.proj(patches))              # (B, N, out_dim)
        h = h + self.x_embed(x_pos) + self.y_embed(y_pos)
        for _ in range(self.latent_refine_steps):
            import torch.nn.functional as F
            r = self.refine_norm(h)
            r = self.refine_down(F.silu(self.refine_gate(r)))
            h = h + r
        return h


# ---------------------------------------------------------------------------
# EmberModelV0Multimodal — minimal wrapper exposing #26 deliverables
# ---------------------------------------------------------------------------

class EmberModelV0Multimodal:
    """Multimodal-extended decoder (Lock 2+3+4+QK-norm) — supports stacking.

    n_layers=1: single-block minimal mode (selftest / mechanism verification).
    n_layers=20: §IV launch config (368M params, hidden=1024, heads=16, head_dim=64).

    Use nn_modules() to collect all nn.Module leaves for manual .to() calls
    (this class is NOT nn.Module — move submodules individually).
    """

    def __init__(self, hidden: int, n_heads: int, head_dim: int, vocab: int, n_layers: int = 1, tie_embeddings: bool = True) -> None:
        import torch.nn as nn
        import torch
        intermediate = hidden * 4  # SwiGLU intermediate: 4096 for hidden=1024
        self.embed_tokens = nn.Embedding(vocab, hidden)
        self.layers = [
            EmberTransformerLayer(hidden, n_heads, head_dim, intermediate)
            for _ in range(n_layers)
        ]
        self.norm = nn.LayerNorm(hidden)
        self.lm_head = nn.Linear(hidden, vocab, bias=False)
        if tie_embeddings:
            # Tie lm_head weights to embed_tokens (config: tied_embeddings=true).
            self.lm_head.weight = self.embed_tokens.weight
        self.n_layers = n_layers
        self.tie_embeddings = tie_embeddings
        # Backward-compat alias so single-layer call-sites still work
        self.attention = self.layers[0].attention if n_layers == 1 else None

        # Standard LM initialization (GPT-2 style):
        # - Embed/linear weights: std=0.02
        # - Output projections (out_proj, down_proj) scaled by 1/sqrt(2L)
        #   to prevent residual stream blowup in deep stacks.
        std = 0.02
        nn.init.normal_(self.embed_tokens.weight, std=std)
        out_scale = std / math.sqrt(2 * max(n_layers, 1))
        for layer in self.layers:
            nn.init.normal_(layer.attention.q_proj.weight, std=std)
            nn.init.normal_(layer.attention.k_proj.weight, std=std)
            nn.init.normal_(layer.attention.v_proj.weight, std=std)
            nn.init.normal_(layer.attention.out_proj.weight, std=out_scale)
            nn.init.normal_(layer.ffn.gate_proj.weight, std=std)
            nn.init.normal_(layer.ffn.up_proj.weight, std=std)
            nn.init.normal_(layer.ffn.down_proj.weight, std=out_scale)

    def nn_modules(self):
        """All nn.Module leaves — for manual .to(device, dtype) calls."""
        mods = [self.embed_tokens, self.norm, self.lm_head]
        for layer in self.layers:
            mods += layer.nn_modules()
        return mods

    def parameters(self):
        seen = set()
        result = []
        for p in (
            list(self.embed_tokens.parameters())
            + [p for layer in self.layers for p in layer.parameters()]
            + list(self.norm.parameters())
            + list(self.lm_head.parameters())
        ):
            if id(p) not in seen:
                seen.add(id(p))
                result.append(p)
        return result

    def forward(
        self,
        input_ids,
        inputs_embeds=None,
        span_boundaries=None,
        x_pos=None,
        y_pos=None,
        image_token_indices=None,
    ):
        """Forward pass: splice → stacked transformer layers → lm_head."""
        # Lock 2: splice soft tokens at placeholder positions
        x = splice_soft_tokens(
            self.embed_tokens, input_ids, inputs_embeds,
            span_boundaries or [], placeholder_ids=None,
        )
        img_idx = image_token_indices or span_boundaries
        for layer in self.layers:
            x = layer.forward(
                x,
                span_boundaries=span_boundaries,
                x_pos=x_pos,
                y_pos=y_pos,
                image_token_indices=img_idx,
            )
        x = self.norm(x)
        return self.lm_head(x)
