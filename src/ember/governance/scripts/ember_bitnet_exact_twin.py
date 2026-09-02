# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""ember_bitnet_exact_twin.py — frozen BitNet 102M matched-pilot exact GPU twin.

Implementation preflight for ember issue #676, against the FROZEN identity
canonically pinned in issue #674 (source claim #155, realized-count
conventions #667). This module is deliverables A + B + C + D of #676:

  A. exact twin architecture (both arms)
  B. arm difference isolated to quantization
  C. realized-count accounting (per #667: REALIZED, never advertised)
  D. manifest identity + load-time mismatch refusal — tracks WHICH ARM and
     its realized parameter count (2026-07-10 gate amendment), so an
     arm-mislabeled checkpoint is caught even though every other identity
     field (config/source hash, seed, token order, eval manifest) is
     arm-invariant and cannot by itself catch that confusion

Deliverable E (the 50M GPU exact-twin preflight pair) is explicitly OUT OF
SCOPE for this module — CPU-only, no GPU dispatch, no training run.

Both arms (dense, ternary) are built from ONE shared class hierarchy
(``ExactTwinTransformer`` / ``ExactTwinBlock`` / ``ExactTwinAttention`` /
``ExactTwinFFN``). The ONLY point of divergence between arms is which
``linear_cls`` factory is injected for the attention/FFN projections —
plain ``nn.Linear`` (dense) or ``TernaryLinear676`` (ternary, absmean
{-1,0,+1} forward quantization + STE). Embedding, tied LM head, and both
RMSNorm layers per block are non-quantized in BOTH arms, per prereg. This
construction makes "dense twin architecture-identical" a structural
guarantee rather than a claim — see ``assert_arms_isomorphic``.

Frozen identity (issue #674 — canonical; DO NOT EDIT without a re-freeze):
  decoder-only next-token LM
  vocab=32,000  seq=1,024
  hidden=768  depth=9  q_heads=12  kv_heads=4  head_dim=64
  SwiGLU ffn_hidden=3,072
  RoPE theta=10,000  RMSNorm eps=1e-6
  per-head QK RMSNorm: ONE 64-elem learned scale for Q and ONE for K,
    PER BLOCK — shared across every head in that block, not a separate
    scale per individual head (matches the frozen param derivation's
    "+2*64" per-layer term: exactly two 64-dim vectors per block).
  tied token embedding / LM head
  MTP heads = 0
  no bias anywhere (linear layers or norms)
  exact parameter count 102,448,512 — BOTH arms, asserted at build time

Device policy: CPU-only in this module.

Selftest: python src/ember/governance/scripts/ember_bitnet_exact_twin.py
  Marker: EMBER_BITNET_EXACT_TWIN_SELFTEST_PASS
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Callable, Optional

import torch
import torch.nn as nn
import torch.nn.functional as F

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class ParamCountMismatchError(RuntimeError):
    """Raised when a built model's realized parameter count != the frozen
    exact count. Fail-closed: this is never a warning."""


class ArmIdentityError(RuntimeError):
    """Raised when the dense/ternary arms are not architecture-identical
    (shape isomorphism broken, or a quantizer leaked into the dense arm)."""


class ManifestMismatchError(RuntimeError):
    """Raised at load-time when a candidate manifest does not match the
    expected manifest on any tracked identity field (prereg gate item 7).
    This is a REFUSAL, never a warning or a silent substitution."""


# ---------------------------------------------------------------------------
# Frozen identity config
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExactTwinConfig:
    vocab: int
    seq: int
    hidden: int
    depth: int
    q_heads: int
    kv_heads: int
    head_dim: int
    ffn_hidden: int
    rope_theta: float
    norm_eps: float

    def __post_init__(self) -> None:
        if self.hidden != self.q_heads * self.head_dim:
            raise ValueError(
                f"hidden={self.hidden} must equal q_heads*head_dim="
                f"{self.q_heads}*{self.head_dim}={self.q_heads * self.head_dim}"
            )
        if self.q_heads % self.kv_heads != 0:
            raise ValueError(
                f"q_heads={self.q_heads} must be an integer multiple of "
                f"kv_heads={self.kv_heads} (GQA requirement)"
            )
        for name in ("vocab", "seq", "hidden", "depth", "q_heads", "kv_heads",
                     "head_dim", "ffn_hidden"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")

    @property
    def kv_dim(self) -> int:
        return self.kv_heads * self.head_dim

    @property
    def n_rep(self) -> int:
        """GQA repeat factor: how many query heads share one KV head."""
        return self.q_heads // self.kv_heads


# The frozen identity, issue #674. Never mutate; build a new config for tests.
FROZEN_CONFIG = ExactTwinConfig(
    vocab=32_000,
    seq=1_024,
    hidden=768,
    depth=9,
    q_heads=12,
    kv_heads=4,
    head_dim=64,
    ffn_hidden=3_072,
    rope_theta=10_000.0,
    norm_eps=1e-6,
)

FROZEN_MTP_HEADS: int = 0
FROZEN_PARAM_COUNT: int = 102_448_512


def derive_param_count(cfg: ExactTwinConfig) -> int:
    """Pure formula for the exact parameter count, independent of building
    an actual nn.Module. Issue #674's derivation:

      vocab*hidden
      + depth*(hidden*hidden                    # q_proj
               + 2*(hidden*kv_dim)               # k_proj, v_proj
               + hidden*hidden                   # o_proj
               + 3*hidden*ffn_hidden             # SwiGLU gate/up/down
               + 2*hidden                        # attn_norm + ffn_norm
               + 2*head_dim)                     # QK-norm (Q scale + K scale)
      + hidden                                   # final norm

    Embedding and LM head share ONE weight tensor (tied), so the head
    contributes zero additional params.
    """
    embed = cfg.vocab * cfg.hidden
    per_layer = (
        cfg.hidden * cfg.hidden                     # q_proj
        + 2 * (cfg.hidden * cfg.kv_dim)              # k_proj, v_proj
        + cfg.hidden * cfg.hidden                    # o_proj
        + 3 * cfg.hidden * cfg.ffn_hidden            # SwiGLU
        + 2 * cfg.hidden                             # attn_norm, ffn_norm
        + 2 * cfg.head_dim                           # QK-norm scales
    )
    final_norm = cfg.hidden
    return embed + cfg.depth * per_layer + final_norm


# Self-check at import time: the formula must reproduce the frozen literal.
# A divergence here means either the formula or the frozen config drifted —
# fail closed immediately, never silently.
_derived = derive_param_count(FROZEN_CONFIG)
if _derived != FROZEN_PARAM_COUNT:
    raise ParamCountMismatchError(
        f"derive_param_count(FROZEN_CONFIG)={_derived} != "
        f"FROZEN_PARAM_COUNT={FROZEN_PARAM_COUNT} — the frozen identity in "
        f"this module has drifted from issue #674. Fix the config or the "
        f"formula; never relax this assertion."
    )


# ---------------------------------------------------------------------------
# Ternary STE quantization (weights only — no activation quantization; the
# prereg's arm-difference clause names weight quant + STE only)
# ---------------------------------------------------------------------------


def absmean_scale(w: torch.Tensor, eps: float = 1e-8) -> torch.Tensor:
    """Per-tensor ABSMEAN scale: scale = mean(|w|) + eps."""
    return w.abs().mean() + eps


def ternary_quantize(w: torch.Tensor, eps: float = 1e-8) -> torch.Tensor:
    """W_q = round(clip(W/scale, -1, 1)) — exact values in {-1, 0, +1}."""
    scale = absmean_scale(w, eps=eps)
    return torch.round(torch.clamp(w / scale, -1.0, 1.0))


class _TernarySTEFunction(torch.autograd.Function):
    """Forward: ternary-quantize then rescale. Backward: identity pass-through
    to the full-precision shadow weight (straight-through estimator)."""

    @staticmethod
    def forward(ctx, w: torch.Tensor, eps: float) -> torch.Tensor:  # type: ignore[override]
        scale = absmean_scale(w, eps=eps)
        w_q = torch.round(torch.clamp(w / scale, -1.0, 1.0))
        return w_q * scale

    @staticmethod
    def backward(ctx, grad_output: torch.Tensor):  # type: ignore[override]
        return grad_output, None


def ternary_ste(w: torch.Tensor, eps: float = 1e-8) -> torch.Tensor:
    return _TernarySTEFunction.apply(w, eps)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# RoPE
# ---------------------------------------------------------------------------


def _rope_freqs(head_dim: int, theta: float, device: torch.device) -> torch.Tensor:
    i = torch.arange(0, head_dim, 2, dtype=torch.float32, device=device)
    return 1.0 / (theta ** (i / head_dim))


def rope_cos_sin(
    seq_len: int, head_dim: int, theta: float, device: torch.device, dtype: torch.dtype,
) -> tuple[torch.Tensor, torch.Tensor]:
    inv_freq = _rope_freqs(head_dim, theta, device)
    t = torch.arange(seq_len, dtype=torch.float32, device=device)
    freqs = torch.outer(t, inv_freq)
    emb = torch.cat([freqs, freqs], dim=-1)
    cos = emb.cos().to(dtype).unsqueeze(0).unsqueeze(0)
    sin = emb.sin().to(dtype).unsqueeze(0).unsqueeze(0)
    return cos, sin


def _rotate_half(x: torch.Tensor) -> torch.Tensor:
    half = x.shape[-1] // 2
    return torch.cat([-x[..., half:], x[..., :half]], dim=-1)


def apply_rope(
    q: torch.Tensor, k: torch.Tensor, cos: torch.Tensor, sin: torch.Tensor,
) -> tuple[torch.Tensor, torch.Tensor]:
    q_rot = (q * cos) + (_rotate_half(q) * sin)
    k_rot = (k * cos) + (_rotate_half(k) * sin)
    return q_rot, k_rot


def repeat_kv(x: torch.Tensor, n_rep: int) -> torch.Tensor:
    """GQA repeat: (B, kv_heads, T, hd) -> (B, kv_heads*n_rep, T, hd).

    Each KV head is repeated n_rep times CONSECUTIVELY so that query heads
    [g*n_rep : (g+1)*n_rep] all attend to KV head g — the standard GQA
    grouping (Llama-style expand+reshape, equivalent to repeat_interleave).
    """
    if n_rep == 1:
        return x
    B, kvh, T, hd = x.shape
    x = x[:, :, None, :, :].expand(B, kvh, n_rep, T, hd)
    return x.reshape(B, kvh * n_rep, T, hd)


# ---------------------------------------------------------------------------
# Per-head QK RMSNorm — ONE learned scale shared across every head in the
# block (issue #674: "one 64-element learned scale for Q and one for K
# per block").
# ---------------------------------------------------------------------------


class HeadRMSNorm(nn.Module):
    def __init__(self, head_dim: int, eps: float) -> None:
        super().__init__()
        self.head_dim = head_dim
        self.eps = eps
        self.scale = nn.Parameter(torch.ones(head_dim))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: (B, heads, T, head_dim) — norm over the last (head_dim) axis,
        # scale broadcasts identically across every head (shared, not
        # per-head-indexed).
        var = x.pow(2).mean(dim=-1, keepdim=True)
        x = x * torch.rsqrt(var + self.eps)
        return x * self.scale


# ---------------------------------------------------------------------------
# Linear implementations — the ONLY arm-divergence point
# ---------------------------------------------------------------------------


def dense_linear(in_features: int, out_features: int) -> nn.Module:
    """Dense arm: plain nn.Linear, no bias. No quantizer attached anywhere
    in this call path — the structural proof of that is
    ``assert_dense_no_quantizer``, which walks the built model's module
    tree and asserts zero ``TernaryLinear676`` instances."""
    return nn.Linear(in_features, out_features, bias=False)


class TernaryLinear676(nn.Module):
    """Ternary arm building block: full-precision shadow weight, STE
    ternary-quantized in the forward pass. No bias (frozen identity)."""

    def __init__(self, in_features: int, out_features: int, eps: float = 1e-8) -> None:
        super().__init__()
        self.in_features = in_features
        self.out_features = out_features
        self.eps = eps
        self.weight = nn.Parameter(torch.empty(out_features, in_features))
        self.register_parameter("bias", None)
        nn.init.kaiming_uniform_(self.weight, a=math.sqrt(5))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        w_q = ternary_ste(self.weight, eps=self.eps)
        return F.linear(x, w_q, None)

    def extra_repr(self) -> str:
        return f"in_features={self.in_features}, out_features={self.out_features}, bias=False"


def ternary_linear(in_features: int, out_features: int) -> nn.Module:
    return TernaryLinear676(in_features, out_features)


LinearFactory = Callable[[int, int], nn.Module]


# ---------------------------------------------------------------------------
# Attention (GQA + QK-norm + RoPE)
# ---------------------------------------------------------------------------


class ExactTwinAttention(nn.Module):
    def __init__(self, cfg: ExactTwinConfig, linear_cls: LinearFactory) -> None:
        super().__init__()
        self.cfg = cfg
        self.head_dim = cfg.head_dim
        self.q_heads = cfg.q_heads
        self.kv_heads = cfg.kv_heads
        self.n_rep = cfg.n_rep

        self.q_proj = linear_cls(cfg.hidden, cfg.q_heads * cfg.head_dim)
        self.k_proj = linear_cls(cfg.hidden, cfg.kv_dim)
        self.v_proj = linear_cls(cfg.hidden, cfg.kv_dim)
        self.o_proj = linear_cls(cfg.q_heads * cfg.head_dim, cfg.hidden)

        self.q_norm = HeadRMSNorm(cfg.head_dim, cfg.norm_eps)
        self.k_norm = HeadRMSNorm(cfg.head_dim, cfg.norm_eps)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        B, T, H = x.shape
        qh, kvh, hd = self.q_heads, self.kv_heads, self.head_dim

        q = self.q_proj(x).view(B, T, qh, hd).transpose(1, 2)   # (B, qh, T, hd)
        k = self.k_proj(x).view(B, T, kvh, hd).transpose(1, 2)  # (B, kvh, T, hd)
        v = self.v_proj(x).view(B, T, kvh, hd).transpose(1, 2)

        q = self.q_norm(q)
        k = self.k_norm(k)

        cos, sin = rope_cos_sin(T, hd, self.cfg.rope_theta, x.device, x.dtype)
        q, k = apply_rope(q, k, cos, sin)

        k = repeat_kv(k, self.n_rep)   # (B, qh, T, hd)
        v = repeat_kv(v, self.n_rep)

        scale = math.sqrt(hd)
        attn = (q @ k.transpose(-2, -1)) / scale  # (B, qh, T, T)

        causal = torch.full((T, T), float("-inf"), dtype=x.dtype, device=x.device)
        causal = torch.triu(causal, diagonal=1)
        attn = attn + causal
        attn = F.softmax(attn, dim=-1)

        out = (attn @ v).transpose(1, 2).contiguous().view(B, T, qh * hd)
        return self.o_proj(out)


# ---------------------------------------------------------------------------
# SwiGLU FFN
# ---------------------------------------------------------------------------


class ExactTwinFFN(nn.Module):
    def __init__(self, cfg: ExactTwinConfig, linear_cls: LinearFactory) -> None:
        super().__init__()
        self.gate_proj = linear_cls(cfg.hidden, cfg.ffn_hidden)
        self.up_proj = linear_cls(cfg.hidden, cfg.ffn_hidden)
        self.down_proj = linear_cls(cfg.ffn_hidden, cfg.hidden)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.down_proj(F.silu(self.gate_proj(x)) * self.up_proj(x))


# ---------------------------------------------------------------------------
# Transformer block
# ---------------------------------------------------------------------------


class ExactTwinBlock(nn.Module):
    def __init__(self, cfg: ExactTwinConfig, linear_cls: LinearFactory) -> None:
        super().__init__()
        self.attn_norm = nn.RMSNorm(cfg.hidden, eps=cfg.norm_eps)
        self.ffn_norm = nn.RMSNorm(cfg.hidden, eps=cfg.norm_eps)
        self.attn = ExactTwinAttention(cfg, linear_cls)
        self.ffn = ExactTwinFFN(cfg, linear_cls)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = x + self.attn(self.attn_norm(x))
        x = x + self.ffn(self.ffn_norm(x))
        return x


# ---------------------------------------------------------------------------
# Full transformer — the exact twin
# ---------------------------------------------------------------------------


class ExactTwinTransformer(nn.Module):
    """The exact GPU twin. ``ternary=True`` builds the ternary arm
    (TernaryLinear676 projections); ``ternary=False`` builds the dense arm
    (plain nn.Linear). Every other line of code is IDENTICAL between arms —
    this is the structural guarantee behind "arm difference isolated to
    quantization" (prereg deliverable B)."""

    def __init__(self, cfg: ExactTwinConfig, ternary: bool) -> None:
        super().__init__()
        self.cfg = cfg
        self.ternary = ternary
        linear_cls: LinearFactory = ternary_linear if ternary else dense_linear

        self.embed = nn.Embedding(cfg.vocab, cfg.hidden)
        self.blocks = nn.ModuleList(
            [ExactTwinBlock(cfg, linear_cls) for _ in range(cfg.depth)]
        )
        self.norm = nn.RMSNorm(cfg.hidden, eps=cfg.norm_eps)

        # Tied LM head — frozen identity. No separate parameters.
        self.head = nn.Linear(cfg.hidden, cfg.vocab, bias=False)
        self.head.weight = self.embed.weight

        # MTP heads frozen at zero. Exposed as an empty ModuleList so
        # realized-count introspection (len(model.mtp_heads)) works the
        # same way regardless of arm.
        self.mtp_heads = nn.ModuleList()

    def _backbone(self, input_ids: torch.Tensor) -> torch.Tensor:
        x = self.embed(input_ids)
        for blk in self.blocks:
            x = blk(x)
        return self.norm(x)

    def forward(self, input_ids: torch.Tensor) -> torch.Tensor:
        return self.head(self._backbone(input_ids))


def build_exact_twin(ternary: bool, cfg: ExactTwinConfig = FROZEN_CONFIG) -> ExactTwinTransformer:
    """Build one arm and assert its exact parameter count before returning.
    Fail-closed: a mismatch raises, never a warning."""
    model = ExactTwinTransformer(cfg, ternary=ternary)
    assert_exact_param_count(model, derive_param_count(cfg))
    return model


# ---------------------------------------------------------------------------
# Realized-count accounting (deliverable C, per #667: REALIZED not
# ADVERTISED — every figure below is read off the actual built nn.Module,
# never copied from the config that requested it).
# ---------------------------------------------------------------------------


def realized_param_count(model: nn.Module) -> int:
    return sum(p.numel() for p in model.parameters())


def assert_exact_param_count(model: nn.Module, expected: int = FROZEN_PARAM_COUNT) -> int:
    realized = realized_param_count(model)
    if realized != expected:
        raise ParamCountMismatchError(f"realized={realized} expected={expected}")
    return realized


def realized_head_accounting(model: ExactTwinTransformer) -> dict:
    """Read Q/KV head counts, head_dim, QK-norm presence, tied-embedding
    status, and MTP head count off the ACTUAL built module — never off
    ``model.cfg``, so a bug that mis-wires the config from the built
    layers is still caught."""
    attn0 = model.blocks[0].attn
    realized_q_heads = attn0.q_proj.out_features // attn0.head_dim  # type: ignore[union-attr]
    realized_kv_heads = attn0.k_proj.out_features // attn0.head_dim  # type: ignore[union-attr]
    return {
        "realized_q_heads": realized_q_heads,
        "realized_kv_heads": realized_kv_heads,
        "realized_head_dim": attn0.head_dim,
        "realized_qk_norm_q_dim": attn0.q_norm.scale.shape[0],
        "realized_qk_norm_k_dim": attn0.k_norm.scale.shape[0],
        "realized_tied_embedding": model.head.weight is model.embed.weight,
        "realized_mtp_heads": len(model.mtp_heads),
        "realized_depth": len(model.blocks),
    }


def _iter_linear_like(model: nn.Module):
    for m in model.modules():
        if isinstance(m, (nn.Linear, TernaryLinear676)):
            yield m


def assert_no_bias_anywhere(model: nn.Module) -> None:
    for m in _iter_linear_like(model):
        if getattr(m, "bias", None) is not None:
            raise ArmIdentityError(f"bias found on {m!r} — frozen identity forbids linear bias")


def assert_dense_no_quantizer(model: ExactTwinTransformer) -> None:
    """PROOF (deliverable B) that the dense arm has no quantizer attached
    anywhere in its module tree."""
    ternary_modules = [m for m in model.modules() if isinstance(m, TernaryLinear676)]
    if ternary_modules:
        raise ArmIdentityError(
            f"dense arm contains {len(ternary_modules)} TernaryLinear676 "
            f"module(s) — quantizer leaked into the dense arm"
        )


def assert_ternary_quantizer_scope(model: ExactTwinTransformer) -> None:
    """PROOF that the ternary arm quantizes exactly attention+FFN linears
    (7 per block: q,k,v,o,gate,up,down) and nothing else — embedding,
    tied head, and both RMSNorm layers per block stay non-ternary."""
    expected = 7 * len(model.blocks)
    actual = sum(1 for m in model.modules() if isinstance(m, TernaryLinear676))
    if actual != expected:
        raise ArmIdentityError(f"ternary module count={actual} expected={expected}")
    if isinstance(model.embed, TernaryLinear676) or isinstance(model.head, TernaryLinear676):
        raise ArmIdentityError("embedding/head must never be quantized")


def assert_arms_isomorphic(dense: ExactTwinTransformer, ternary: ExactTwinTransformer) -> None:
    """The strongest proof that 'the dense twin is architecture-identical':
    every named parameter in one arm has an identically-named,
    identically-shaped counterpart in the other arm."""
    dense_shapes = {n: tuple(p.shape) for n, p in dense.named_parameters()}
    ternary_shapes = {n: tuple(p.shape) for n, p in ternary.named_parameters()}
    if dense_shapes.keys() != ternary_shapes.keys():
        missing = dense_shapes.keys() ^ ternary_shapes.keys()
        raise ArmIdentityError(f"parameter name sets differ: {sorted(missing)[:10]}")
    mismatched = [n for n in dense_shapes if dense_shapes[n] != ternary_shapes[n]]
    if mismatched:
        raise ArmIdentityError(f"shape mismatch on: {mismatched[:10]}")


def ternary_value_fractions(model: ExactTwinTransformer) -> dict:
    """Per-tensor ternary-value fraction receipt (deliverable C). Returns
    ``{}`` for the dense arm — there is nothing to quantize (which is
    itself part of the dense-arm proof)."""
    out: dict[str, dict] = {}
    for name, module in model.named_modules():
        if not isinstance(module, TernaryLinear676):
            continue
        with torch.no_grad():
            w_q = ternary_quantize(module.weight, eps=module.eps)
        n = w_q.numel()
        out[name] = {
            "count": n,
            "frac_neg1": float((w_q == -1.0).sum().item()) / n,
            "frac_zero": float((w_q == 0.0).sum().item()) / n,
            "frac_pos1": float((w_q == 1.0).sum().item()) / n,
        }
    return out


# ---------------------------------------------------------------------------
# Manifest identity + load-time mismatch refusal (deliverable D, prereg
# gate item 7).
# ---------------------------------------------------------------------------


def compute_source_hash(path: Optional[Path] = None) -> str:
    p = path or Path(__file__)
    return hashlib.sha256(p.read_bytes()).hexdigest()


def compute_config_hash(cfg: ExactTwinConfig) -> str:
    payload = json.dumps(asdict(cfg), sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


_VALID_ARMS = ("dense", "ternary")


@dataclass(frozen=True)
class TwinManifest:
    config_hash: str
    source_hash: str
    arm: str
    param_count: int
    seed: int
    token_order_hash: str
    eval_manifest_hash: str


def build_manifest(
    arm: str,
    param_count: int,
    seed: int,
    token_order_hash: str,
    eval_manifest_hash: str,
    cfg: ExactTwinConfig = FROZEN_CONFIG,
    source_path: Optional[Path] = None,
) -> TwinManifest:
    """``arm`` and ``param_count`` are REQUIRED (2026-07-10 gate amendment):
    without them every other field (config/source hash, seed, token order,
    eval manifest) is arm-invariant, so a ternary checkpoint mislabeled as
    dense passed ``verify_manifest`` silently — exactly the confusion
    surface the load-time refusal exists to catch (prereg gate items 1+7).
    ``verify_manifest`` iterates every declared field, so adding these two
    here is sufficient for the refusal to be automatic."""
    if arm not in _VALID_ARMS:
        raise ValueError(f"arm must be one of {_VALID_ARMS}, got {arm!r}")
    return TwinManifest(
        config_hash=compute_config_hash(cfg),
        source_hash=compute_source_hash(source_path),
        arm=arm,
        param_count=param_count,
        seed=seed,
        token_order_hash=token_order_hash,
        eval_manifest_hash=eval_manifest_hash,
    )


def build_manifest_for_model(
    model: ExactTwinTransformer,
    seed: int,
    token_order_hash: str,
    eval_manifest_hash: str,
    source_path: Optional[Path] = None,
) -> TwinManifest:
    """Convenience wrapper that reads ``arm`` and ``param_count`` off the
    ACTUAL built model (realized_param_count), never off a caller-supplied
    literal — keeps the manifest honoring the same #667 realized-not-
    advertised convention as the rest of deliverable C."""
    return build_manifest(
        arm="ternary" if model.ternary else "dense",
        param_count=realized_param_count(model),
        seed=seed,
        token_order_hash=token_order_hash,
        eval_manifest_hash=eval_manifest_hash,
        cfg=model.cfg,
        source_path=source_path,
    )


def verify_manifest(candidate: TwinManifest, expected: TwinManifest) -> None:
    """Load-time refusal: ANY tracked field mismatch raises. This is the
    negative-test surface for prereg gate item 7 — never a warning, never
    a silent substitution."""
    mismatches = [
        f.name for f in fields(TwinManifest)
        if getattr(candidate, f.name) != getattr(expected, f.name)
    ]
    if mismatches:
        raise ManifestMismatchError(
            f"manifest mismatch on field(s) {mismatches} — refusing to load. "
            f"candidate={candidate} expected={expected}"
        )


# ---------------------------------------------------------------------------
# Selftest
# ---------------------------------------------------------------------------


def _run_tests(verbose: bool = True) -> dict:
    results: dict[str, bool] = {}
    errors: dict[str, str] = {}

    def _pass(name: str) -> None:
        results[name] = True
        if verbose:
            print(f"  PASS  {name}")

    def _fail(name: str, msg: str) -> None:
        results[name] = False
        errors[name] = msg
        if verbose:
            print(f"  FAIL  {name}: {msg}")

    # T1: formula reproduces the frozen literal (also asserted at import time)
    name = "T1_formula_matches_frozen_literal"
    try:
        if derive_param_count(FROZEN_CONFIG) != FROZEN_PARAM_COUNT:
            _fail(name, "formula does not reproduce 102,448,512")
        else:
            _pass(name)
    except Exception as exc:
        _fail(name, str(exc))

    # Build both arms once; reused by several tests below.
    try:
        dense = build_exact_twin(ternary=False)
        ternary = build_exact_twin(ternary=True)
        build_ok = True
    except Exception as exc:
        dense = ternary = None  # type: ignore[assignment]
        build_ok = False
        _fail("T0_both_arms_build_at_exact_count", str(exc))
    if build_ok:
        _pass("T0_both_arms_build_at_exact_count")

    if build_ok:
        # T2/T3: exact param count both arms (build_exact_twin already
        # asserts this internally; re-check here as an independent proof).
        for label, model in (("dense", dense), ("ternary", ternary)):
            name = f"T2_{label}_exact_param_count"
            try:
                n = assert_exact_param_count(model, FROZEN_PARAM_COUNT)
                if n != FROZEN_PARAM_COUNT:
                    _fail(name, f"count={n}")
                else:
                    _pass(name)
            except Exception as exc:
                _fail(name, str(exc))

        # T4: realized head accounting
        name = "T4_realized_head_accounting"
        try:
            acct = realized_head_accounting(dense)
            expect = {
                "realized_q_heads": 12,
                "realized_kv_heads": 4,
                "realized_head_dim": 64,
                "realized_qk_norm_q_dim": 64,
                "realized_qk_norm_k_dim": 64,
                "realized_tied_embedding": True,
                "realized_mtp_heads": 0,
                "realized_depth": 9,
            }
            bad = {k: (acct[k], v) for k, v in expect.items() if acct[k] != v}
            if bad:
                _fail(name, f"mismatches={bad}")
            else:
                _pass(name)
        except Exception as exc:
            _fail(name, str(exc))

        # T5: same accounting holds for the ternary arm too
        name = "T5_realized_head_accounting_ternary_arm"
        try:
            acct_t = realized_head_accounting(ternary)
            acct_d = realized_head_accounting(dense)
            if acct_t != acct_d:
                _fail(name, f"ternary={acct_t} dense={acct_d}")
            else:
                _pass(name)
        except Exception as exc:
            _fail(name, str(exc))

        # T6: no bias anywhere, either arm
        name = "T6_no_bias_anywhere"
        try:
            assert_no_bias_anywhere(dense)
            assert_no_bias_anywhere(ternary)
            _pass(name)
        except Exception as exc:
            _fail(name, str(exc))

        # T7: dense arm has zero quantizers (deliverable B proof)
        name = "T7_dense_arm_no_quantizer_proof"
        try:
            assert_dense_no_quantizer(dense)
            _pass(name)
        except Exception as exc:
            _fail(name, str(exc))

        # T8: ternary arm quantizes exactly the attn+ffn linears (7/block)
        name = "T8_ternary_arm_quantizer_scope"
        try:
            assert_ternary_quantizer_scope(ternary)
            _pass(name)
        except Exception as exc:
            _fail(name, str(exc))

        # T9: arms are shape-isomorphic (architecture-identical proof)
        name = "T9_arms_shape_isomorphic"
        try:
            assert_arms_isomorphic(dense, ternary)
            _pass(name)
        except Exception as exc:
            _fail(name, str(exc))

        # T10: ternary_value_fractions sums to ~1.0 per tensor, dense arm empty
        name = "T10_ternary_value_fractions"
        try:
            fracs = ternary_value_fractions(ternary)
            expected_tensors = 7 * 9
            if len(fracs) != expected_tensors:
                _fail(name, f"tensor count={len(fracs)} expected={expected_tensors}")
            else:
                bad = [
                    k for k, v in fracs.items()
                    if not math.isclose(v["frac_neg1"] + v["frac_zero"] + v["frac_pos1"], 1.0, rel_tol=1e-6)
                ]
                dense_fracs = ternary_value_fractions(dense)
                if bad:
                    _fail(name, f"fractions don't sum to 1.0 on: {bad[:3]}")
                elif dense_fracs:
                    _fail(name, f"dense arm reported {len(dense_fracs)} ternary tensors, expected 0")
                else:
                    _pass(name)
        except Exception as exc:
            _fail(name, str(exc))

        # T11: STE forward values exactly in {-1, 0, +1} pre-rescale
        name = "T11_ste_ternary_values_exact"
        try:
            layer = list(ternary.modules())
            bitlin = next(m for m in layer if isinstance(m, TernaryLinear676))
            w_q = ternary_quantize(bitlin.weight.data, eps=bitlin.eps)
            bad = [v for v in w_q.unique().tolist() if round(v, 6) not in (-1.0, 0.0, 1.0)]
            if bad:
                _fail(name, f"unexpected values: {bad}")
            else:
                _pass(name)
        except Exception as exc:
            _fail(name, str(exc))

        # T12: STE gradient flows to the shadow weight
        name = "T12_ste_gradient_flows_to_shadow"
        try:
            torch.manual_seed(42)
            layer = TernaryLinear676(8, 4)
            w0 = layer.weight.data.clone()
            x = torch.randn(2, 8)
            opt = torch.optim.SGD(layer.parameters(), lr=0.1)
            out = layer(x)
            out.sum().backward()
            assert layer.weight.grad is not None
            assert layer.weight.grad.norm().item() > 0
            opt.step()
            if torch.allclose(w0, layer.weight.data):
                _fail(name, "shadow weight unchanged after optimizer step")
            else:
                _pass(name)
        except Exception as exc:
            _fail(name, str(exc))
    else:
        for t in ("T2_dense_exact_param_count", "T2_ternary_exact_param_count",
                  "T4_realized_head_accounting", "T5_realized_head_accounting_ternary_arm",
                  "T6_no_bias_anywhere", "T7_dense_arm_no_quantizer_proof",
                  "T8_ternary_arm_quantizer_scope", "T9_arms_shape_isomorphic",
                  "T10_ternary_value_fractions", "T11_ste_ternary_values_exact",
                  "T12_ste_gradient_flows_to_shadow"):
            _fail(t, "skipped: arms failed to build")

    # T13: GQA repeat_kv groups query heads onto the correct KV head
    name = "T13_gqa_repeat_kv_grouping"
    try:
        torch.manual_seed(9)
        B, kvh, T, hd, n_rep = 1, 4, 3, 8, 3
        k = torch.randn(B, kvh, T, hd)
        k_rep = repeat_kv(k, n_rep)
        if k_rep.shape != (B, kvh * n_rep, T, hd):
            _fail(name, f"shape={k_rep.shape}")
        else:
            bad = []
            for g in range(kvh):
                for r in range(n_rep):
                    qh_idx = g * n_rep + r
                    if not torch.equal(k_rep[:, qh_idx], k[:, g]):
                        bad.append((g, r))
            if bad:
                _fail(name, f"grouping wrong at {bad[:3]}")
            else:
                _pass(name)
    except Exception as exc:
        _fail(name, str(exc))

    # T14: causal mask — perturbing the last token never changes earlier positions
    name = "T14_causal_mask_correctness"
    try:
        torch.manual_seed(7)
        tiny_cfg = ExactTwinConfig(vocab=32, seq=8, hidden=32, depth=1, q_heads=4,
                                    kv_heads=2, head_dim=8, ffn_hidden=64,
                                    rope_theta=10_000.0, norm_eps=1e-6)
        block = ExactTwinBlock(tiny_cfg, dense_linear)
        block.eval()
        B, T = 1, 6
        x = torch.randn(B, T, tiny_cfg.hidden)
        with torch.no_grad():
            out_orig = block(x).clone()
        x_pert = x.clone()
        x_pert[:, T - 1, :] = x_pert[:, T - 1, :] * 2 + 1.0
        with torch.no_grad():
            out_pert = block(x_pert)
        if not torch.allclose(out_orig[:, :T - 1], out_pert[:, :T - 1], atol=0.0, rtol=0.0):
            diff = (out_orig[:, :T - 1] - out_pert[:, :T - 1]).abs().max().item()
            _fail(name, f"earlier positions changed, max_diff={diff:.6g}")
        else:
            _pass(name)
    except Exception as exc:
        _fail(name, str(exc))

    # T15: RoPE is position-dependent
    name = "T15_rope_position_dependent"
    try:
        torch.manual_seed(8)
        tiny_cfg = ExactTwinConfig(vocab=32, seq=8, hidden=32, depth=1, q_heads=4,
                                    kv_heads=2, head_dim=8, ffn_hidden=64,
                                    rope_theta=10_000.0, norm_eps=1e-6)
        block = ExactTwinBlock(tiny_cfg, dense_linear)
        block.eval()
        B, T = 1, 6
        x = torch.randn(B, T, tiny_cfg.hidden)
        x[:, 3, :] = x[:, 0, :]
        with torch.no_grad():
            out = block(x)
        if torch.allclose(out[:, 0], out[:, 3], atol=1e-5, rtol=1e-5):
            _fail(name, "identical content at different positions produced identical output")
        else:
            _pass(name)
    except Exception as exc:
        _fail(name, str(exc))

    # T16: manifest determinism + verify passes on identical manifests
    name = "T16_manifest_determinism_and_verify_pass"
    try:
        m1 = build_manifest(arm="dense", param_count=FROZEN_PARAM_COUNT, seed=0,
                             token_order_hash="abc123", eval_manifest_hash="def456")
        m2 = build_manifest(arm="dense", param_count=FROZEN_PARAM_COUNT, seed=0,
                             token_order_hash="abc123", eval_manifest_hash="def456")
        if m1 != m2:
            _fail(name, f"non-deterministic manifest: {m1} != {m2}")
        else:
            verify_manifest(m2, m1)  # must not raise
            _pass(name)
    except Exception as exc:
        _fail(name, str(exc))

    # T17: deliberate mismatch causes load-time refusal (prereg gate item 7)
    name = "T17_manifest_mismatch_refusal"
    try:
        expected = build_manifest(arm="dense", param_count=FROZEN_PARAM_COUNT, seed=0,
                                   token_order_hash="abc123", eval_manifest_hash="def456")
        candidate = build_manifest(arm="dense", param_count=FROZEN_PARAM_COUNT, seed=1,
                                    token_order_hash="abc123", eval_manifest_hash="def456")
        raised = False
        try:
            verify_manifest(candidate, expected)
        except ManifestMismatchError:
            raised = True
        if not raised:
            _fail(name, "verify_manifest did not raise on a deliberately mismatched seed")
        else:
            _pass(name)
    except Exception as exc:
        _fail(name, str(exc))

    # T18: arm mismatch alone (all other fields identical, including
    # param_count which is IDENTICAL across arms by construction) must
    # still cause refusal (2026-07-10 gate amendment — the exact confusion
    # a ternary checkpoint mislabeled as dense used to slip past).
    name = "T18_arm_mismatch_refusal_all_else_identical"
    try:
        as_dense = build_manifest(arm="dense", param_count=FROZEN_PARAM_COUNT, seed=0,
                                   token_order_hash="abc123", eval_manifest_hash="def456")
        as_ternary = build_manifest(arm="ternary", param_count=FROZEN_PARAM_COUNT, seed=0,
                                     token_order_hash="abc123", eval_manifest_hash="def456")
        raised = False
        try:
            verify_manifest(as_ternary, as_dense)
        except ManifestMismatchError:
            raised = True
        if not raised:
            _fail(name, "verify_manifest did not raise when only 'arm' differed")
        else:
            _pass(name)
    except Exception as exc:
        _fail(name, str(exc))

    # T19: build_manifest_for_model reads arm+param_count off the ACTUAL
    # built model (realized, per #667), never a caller-supplied literal,
    # and a dense-vs-ternary manifest built this way for the SAME config
    # still triggers the T18 refusal end-to-end.
    name = "T19_build_manifest_for_model_realized_arm_and_count"
    if build_ok:
        try:
            m_dense = build_manifest_for_model(dense, seed=0, token_order_hash="abc123",
                                                eval_manifest_hash="def456")
            m_ternary = build_manifest_for_model(ternary, seed=0, token_order_hash="abc123",
                                                  eval_manifest_hash="def456")
            bad = []
            if m_dense.arm != "dense":
                bad.append(f"dense arm labeled {m_dense.arm!r}")
            if m_ternary.arm != "ternary":
                bad.append(f"ternary arm labeled {m_ternary.arm!r}")
            if m_dense.param_count != FROZEN_PARAM_COUNT or m_ternary.param_count != FROZEN_PARAM_COUNT:
                bad.append(f"param_count dense={m_dense.param_count} ternary={m_ternary.param_count}")
            refused = False
            try:
                verify_manifest(m_ternary, m_dense)
            except ManifestMismatchError:
                refused = True
            if not refused:
                bad.append("verify_manifest did not refuse mismatched real-model manifests")
            if bad:
                _fail(name, "; ".join(bad))
            else:
                _pass(name)
        except Exception as exc:
            _fail(name, str(exc))
    else:
        _fail(name, "skipped: arms failed to build")

    # T20: build_manifest rejects an invalid arm label outright (fail-closed
    # at construction time, not merely at verify time).
    name = "T20_build_manifest_rejects_invalid_arm"
    try:
        raised = False
        try:
            build_manifest(arm="bf16", param_count=FROZEN_PARAM_COUNT, seed=0,
                            token_order_hash="abc123", eval_manifest_hash="def456")
        except ValueError:
            raised = True
        if not raised:
            _fail(name, "build_manifest accepted an invalid arm label")
        else:
            _pass(name)
    except Exception as exc:
        _fail(name, str(exc))

    total = len(results)
    passed = sum(v for v in results.values())
    failed = total - passed
    all_passed = failed == 0

    receipt = {
        "ticket": "EMBER-BITNET-EXACT-TWIN-SELFTEST",
        "issue": 676,
        "prereg": 674,
        "total": total,
        "passed": passed,
        "failed": failed,
        "all_passed": all_passed,
        "results": results,
        "errors": errors,
        "verdict": "EMBER_BITNET_EXACT_TWIN_SELFTEST_PASS" if all_passed else "FAIL",
    }
    return receipt


def selftest() -> None:
    print("=" * 64)
    print("ember_bitnet_exact_twin — unit test suite (#676 / #674)")
    print("=" * 64)
    receipt = _run_tests(verbose=True)
    print("-" * 64)
    print(f"Total: {receipt['total']}  Passed: {receipt['passed']}  Failed: {receipt['failed']}")
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
