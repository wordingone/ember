"""
Capacity expansion functions for the growth-refutation experiment.

net2net_grow  -- function-preserving MLP width expansion (Net2WiderNet).
random_grow   -- same shape additions, random init (no preservation; arm R).

Both follow the capacity_fn signature used by the accumulation_law hook:
    (model, tokenizer, round_idx: int, tier: int) -> (model, tokenizer)

Mandatory assertion in net2net_grow: logits on a fixed probe batch must match
pre-expansion logits within max abs diff < NET2NET_ASSERT_TOL.
Raises RuntimeError on failure -- never write a receipt claiming
function-preservation that did not hold.

Net2WiderNet reference:
  Chen et al., "Net2Net: Accelerating Learning via Knowledge Transfer", ICLR 2016.
  Applied here to SwiGLU FFN layers of a decoder transformer.

SwiGLU MLP forward: out = down_proj( silu(gate_proj(x)) * up_proj(x) )
  gate_proj : Linear(hidden, interm)   -- shape (interm, hidden) in PyTorch weight
  up_proj   : Linear(hidden, interm)   -- same
  down_proj : Linear(interm, hidden)   -- shape (hidden, interm)

Width expansion (widen interm by n_new):
  * gate_proj, up_proj: append n_new rows that are copies of selected source rows.
    No scaling on these (gating mechanism handles activation magnitudes).
  * down_proj: for each source row s duplicated k times, column s becomes
    orig_col / (1 + k) and each copy column is also orig_col / (1 + k),
    so the sum over all copies = orig_col (output preserved).

Usage (as a CLI hook):
    python run_growth_refutation.py --capacity_fn capacity:net2net_grow
"""

from __future__ import annotations

import random
from collections import Counter
from typing import Tuple

import torch
import torch.nn as nn

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
NET2NET_ASSERT_TOL: float = 1e-3   # max abs logit diff after vs before expansion
MLP_EXPAND_FRAC:   float = 0.25    # fraction of current interm to add per event (GPU)
MLP_EXPAND_FRAC_SMOKE: float = 0.05  # smaller expansion for CPU smoke

# Fixed probe for the function-preserving assertion (arbitrary small vocab ids)
_PROBE_TOKEN_IDS = [1, 2, 3, 5, 8, 13, 21, 34, 55, 89]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _probe_batch(tokenizer, device: str) -> dict:
    """Build a fixed probe input for the assertion."""
    ids = [min(t, tokenizer.vocab_size - 1) for t in _PROBE_TOKEN_IDS]
    t   = torch.tensor([ids], dtype=torch.long, device=device)
    return {"input_ids": t, "attention_mask": torch.ones_like(t)}


def _get_logits(model, probe: dict, dtype: torch.dtype | None = None) -> torch.Tensor:
    """
    Forward pass, no grad, return logits.
    If dtype is None, return float32. Otherwise return in the specified dtype.
    """
    model.eval()
    with torch.no_grad():
        logits = model(**probe).logits.detach()
        if dtype is None:
            return logits.float()
        return logits.to(dtype)


def _get_transformer_layers(model):
    """
    Return the list of transformer decoder layers from a PEFT or plain model.
    Tries the standard PEFT nesting first; falls back to plain .model.layers.
    Raises RuntimeError with a diagnostic if neither path finds layers.
    """
    try:
        return model.base_model.model.model.layers  # PeftModel -> LoraModel -> LM -> decoder
    except AttributeError:
        pass
    try:
        return model.model.layers  # plain AutoModelForCausalLM
    except AttributeError:
        pass
    raise RuntimeError(
        "capacity.py: cannot locate transformer layers. "
        "Expected model.base_model.model.model.layers (PEFT) "
        "or model.model.layers (plain LM). "
        f"Got type: {type(model)}"
    )


def _compute_bf16_metrics(logits_before: torch.Tensor, logits_after: torch.Tensor) -> dict:
    """
    Compute functional-equivalence metrics in bf16.

    Returns dict with:
      argmax_agree: fraction of positions where top-1 argmax agrees
      kl_mean: mean KL divergence from before to after distribution (softmax)
    """
    # Ensure both are in bf16
    before = logits_before.to(torch.bfloat16)
    after  = logits_after.to(torch.bfloat16)

    # Top-1 argmax agreement
    argmax_before = before.argmax(dim=-1)
    argmax_after  = after.argmax(dim=-1)
    agree = (argmax_before == argmax_after).float().mean().item()

    # KL divergence: softmax(before) -> softmax(after), per position, then mean
    probs_before = torch.nn.functional.softmax(before, dim=-1)
    probs_after  = torch.nn.functional.softmax(after, dim=-1)

    # KL(before || after) = sum(P(before) * log(P(before) / P(after)))
    # Numerically stable: add small epsilon to avoid log(0)
    eps = 1e-8
    log_ratio = torch.log(probs_before + eps) - torch.log(probs_after + eps)
    kl_per_pos = (probs_before * log_ratio).sum(dim=-1)
    kl_mean = kl_per_pos.mean().item()

    return {
        "argmax_agree": agree,
        "kl_mean": kl_mean,
    }


def _widen_mlp_layer(
    layer,
    src_indices: list[int],
    device: str,
    dtype: torch.dtype,
) -> None:
    """
    Net2WiderNet in-place expansion of one SwiGLU MLP block.

    src_indices: list of intermediate-dim indices to duplicate (may repeat).
    After this call, intermediate_size grows by len(src_indices).
    Output of the layer is mathematically preserved to floating-point precision.
    """
    mlp  = layer.mlp
    gate = mlp.gate_proj   # (interm, hidden)
    up   = mlp.up_proj     # (interm, hidden)
    down = mlp.down_proj   # (hidden, interm)
    n_new = len(src_indices)

    # How many copies each source index appears as (original + copies)
    copy_count = Counter(src_indices)  # idx -> n extra copies

    with torch.no_grad():
        # ---- gate_proj ----
        new_g_rows = gate.weight[src_indices, :].clone()  # (n_new, hidden)
        new_g_w    = torch.cat([gate.weight, new_g_rows], dim=0)
        new_gate   = nn.Linear(gate.in_features, gate.out_features + n_new,
                               bias=(gate.bias is not None), device=device, dtype=dtype)
        new_gate.weight.copy_(new_g_w)
        if gate.bias is not None:
            new_gate.bias.copy_(torch.cat([gate.bias,
                                           gate.bias[src_indices].clone()]))
        mlp.gate_proj = new_gate

        # ---- up_proj ----
        new_u_rows = up.weight[src_indices, :].clone()
        new_u_w    = torch.cat([up.weight, new_u_rows], dim=0)
        new_up     = nn.Linear(up.in_features, up.out_features + n_new,
                               bias=(up.bias is not None), device=device, dtype=dtype)
        new_up.weight.copy_(new_u_w)
        if up.bias is not None:
            new_up.bias.copy_(torch.cat([up.bias, up.bias[src_indices].clone()]))
        mlp.up_proj = new_up

        # ---- down_proj: scale original cols, append scaled-copy cols ----
        # For each src index with k extra copies, both the original column
        # and each copy column become orig_col / (1 + k).
        orig_cols = down.weight.clone()  # (hidden, interm)
        for idx, k in copy_count.items():
            orig_cols[:, idx].div_(1.0 + k)

        new_d_cols = torch.stack(
            [down.weight[:, i].clone().div_(1.0 + copy_count[i])
             for i in src_indices],
            dim=1,
        )  # (hidden, n_new)
        new_d_w = torch.cat([orig_cols, new_d_cols], dim=1)
        new_down = nn.Linear(down.in_features + n_new, down.out_features,
                             bias=(down.bias is not None), device=device, dtype=dtype)
        new_down.weight.copy_(new_d_w)
        if down.bias is not None:
            new_down.bias.copy_(down.bias.clone())
        mlp.down_proj = new_down


# ---------------------------------------------------------------------------
# Public capacity functions
# ---------------------------------------------------------------------------

def net2net_grow(
    model,
    tokenizer,
    round_idx: int,
    tier: int,
    expand_frac: float | None = None,
    assert_tol: float = NET2NET_ASSERT_TOL,
    seed: int | None = None,
) -> Tuple:
    """
    Function-preserving MLP width expansion (Net2WiderNet).

    Widens each transformer layer's SwiGLU intermediate_size by expand_frac
    of its current width.  New units are initialised so the layer output is
    unchanged (verified by TWO-PART instrumentation):

    GATE A (CORRECTNESS GATE, fail-closed): Upcast model weights and activations
    to float32, compute pre/post-expansion reference logits in genuine float32
    (not bf16 + output cast), assert max_abs_diff < assert_tol (~1e-4 expected).
    Raises RuntimeError on failure.

    GATE B (RUNTIME FUNCTIONAL-EQUIVALENCE METRIC, characterizing): In the model's
    deployed dtype (bf16), compute top-1 argmax agreement and mean KL divergence
    between pre-expansion and post-expansion logits. Log WARNING if argmax_agree < 0.99.
    Emit both metrics to receipt via returned dict.

    Returns (model, tokenizer, metrics_dict).  model is mutated in-place (MLP layers
    replaced; LoRA adapters on attention layers are untouched).
    metrics_dict contains:
      net2net_fp32_max_abs_diff: float32 correctness gate value
      net2net_bf16_argmax_agree: bf16 top-1 agreement rate
      net2net_bf16_kl_mean: bf16 mean KL divergence
    """
    rng    = random.Random(seed if seed is not None else round_idx * 31 + tier * 7)
    device = str(next(model.parameters()).device)
    dtype  = next(model.parameters()).dtype

    if expand_frac is None:
        expand_frac = MLP_EXPAND_FRAC_SMOKE if device == "cpu" else MLP_EXPAND_FRAC

    layers   = _get_transformer_layers(model)
    old_interm = layers[0].mlp.gate_proj.out_features
    n_new    = max(1, int(old_interm * expand_frac))

    # Sample source indices (without replacement when possible)
    pool = list(range(old_interm))
    if n_new <= old_interm:
        src_indices = rng.sample(pool, k=n_new)
    else:
        # More new than existing: use choices (with replacement)
        src_indices = rng.choices(pool, k=n_new)

    probe = _probe_batch(tokenizer, device)

    # ---- GATE B pre-capture: bf16 logits BEFORE any model changes ----
    # Must run first so we have a genuine pre-expansion baseline for the soft metric.
    logits_before_bf16 = _get_logits(model, probe, dtype=torch.bfloat16)

    # ---- GATE A: CORRECTNESS GATE (float64, fail-closed) ----
    # Upcast the entire model to float64 (double precision) for the gate check.
    # The expansion surgery is mathematically exact (function-preserving by design),
    # but the pre-expansion and post-expansion forward passes use matmuls of
    # different widths (old_interm vs old_interm+n_new columns).  cuBLAS selects
    # different tiling algorithms for different sizes, causing different float32
    # rounding even in deterministic mode.  After LoRA fine-tuning, the hidden
    # states feeding the MLP have larger dynamic range, amplifying the
    # algorithm-choice-induced rounding difference to ~3.5e-1 — well above 1e-3.
    # Float64 reduces the rounding error to ~1e-12 (empirically exact zero on this
    # hardware/model), making the gate pass iff the surgery is genuinely correct.
    model.to(torch.float64)
    logits_before_fp32 = _get_logits(model, probe)  # float64 compute

    # Expand every layer while the model is in float64
    for layer in layers:
        _widen_mlp_layer(layer, src_indices, device, torch.float64)

    logits_after_fp32 = _get_logits(model, probe)  # float64 compute, expanded

    # Cast the expanded model back to the deployed dtype (bf16).
    model.to(dtype)

    # Mandatory function-preserving assertion (fail-closed).
    fp32_max_diff = (logits_after_fp32 - logits_before_fp32).abs().max().item()
    if fp32_max_diff >= assert_tol:
        raise RuntimeError(
            f"net2net_grow: function-preserving assertion FAILED "
            f"(fp64 max_abs_diff={fp32_max_diff:.6e} >= tol={assert_tol}). "
            f"round_idx={round_idx} tier={tier} expand_frac={expand_frac:.3f} "
            f"intermediate_size was {old_interm}, attempted +{n_new}."
        )

    # ---- GATE B: RUNTIME FUNCTIONAL-EQUIVALENCE METRIC (bf16, characterizing) ----
    # logits_before_bf16 was captured BEFORE expansion (above).
    # Capture post-expansion bf16 logits from the now-deployed bf16 model.
    logits_after_bf16 = _get_logits(model, probe, dtype=torch.bfloat16)

    bf16_metrics = _compute_bf16_metrics(logits_before_bf16, logits_after_bf16)
    argmax_agree = bf16_metrics["argmax_agree"]
    kl_mean = bf16_metrics["kl_mean"]

    # Soft gate: log warning if argmax_agree < 0.99 (only case where bf16 drift matters)
    if argmax_agree < 0.99:
        print(
            f"  [net2net_grow] WARNING: bf16 argmax_agree={argmax_agree:.4f} < 0.99 "
            f"(function-preservation may be compromised by bf16 numerical drift)"
        )

    new_interm = old_interm + n_new
    print(
        f"  [net2net_grow] r{round_idx} T{tier}: "
        f"intermediate_size {old_interm} -> {new_interm} (+{n_new}, "
        f"expand_frac={expand_frac:.2f}). "
        f"GATE_A(fp64) PASSED (max_abs_diff={fp32_max_diff:.2e} < {assert_tol}); "
        f"GATE_B(bf16) argmax_agree={argmax_agree:.4f} kl_mean={kl_mean:.6f}"
    )

    metrics = {
        "net2net_fp32_max_abs_diff": round(fp32_max_diff, 8),
        "net2net_bf16_argmax_agree": round(argmax_agree, 6),
        "net2net_bf16_kl_mean": round(kl_mean, 6),
    }
    return model, tokenizer, metrics


def random_grow(
    model,
    tokenizer,
    round_idx: int,
    tier: int,
    expand_frac: float | None = None,
    seed: int | None = None,
) -> Tuple:
    """
    Same capacity additions as net2net_grow but with RANDOM initialisation.
    No function-preservation -- new units start at small random values.
    No assertion (would trivially fail by design).
    Used by arm R to isolate whether function-PRESERVATION matters.

    Returns (model, tokenizer).
    """
    g_seed = seed if seed is not None else round_idx * 31 + tier * 7
    rng        = random.Random(g_seed)

    device = str(next(model.parameters()).device)
    dtype  = next(model.parameters()).dtype

    # Generator must live on the same device as the randn target below:
    # torch.randn(generator=..., device=cuda) rejects a cpu generator
    # (the arm-R round-5 random_grow crash). cpu dry-run path is unchanged;
    # per-seed determinism is preserved on each device.
    torch_rng  = torch.Generator(device=device)
    torch_rng.manual_seed(rng.randint(0, 2 ** 31))

    if expand_frac is None:
        expand_frac = MLP_EXPAND_FRAC_SMOKE if device == "cpu" else MLP_EXPAND_FRAC

    layers     = _get_transformer_layers(model)
    old_interm = layers[0].mlp.gate_proj.out_features
    n_new      = max(1, int(old_interm * expand_frac))
    scale      = 0.02  # small random init std

    with torch.no_grad():
        for layer in layers:
            mlp  = layer.mlp
            gate = mlp.gate_proj
            up   = mlp.up_proj
            down = mlp.down_proj

            # gate_proj
            rand_g = torch.randn(n_new, gate.in_features, generator=torch_rng,
                                 device=device, dtype=dtype) * scale
            new_gate = nn.Linear(gate.in_features, old_interm + n_new,
                                 bias=(gate.bias is not None), device=device, dtype=dtype)
            new_gate.weight.copy_(torch.cat([gate.weight, rand_g], dim=0))
            if gate.bias is not None:
                new_gate.bias.copy_(torch.cat([
                    gate.bias, torch.zeros(n_new, device=device, dtype=dtype)]))
            mlp.gate_proj = new_gate

            # up_proj
            rand_u = torch.randn(n_new, up.in_features, generator=torch_rng,
                                 device=device, dtype=dtype) * scale
            new_up = nn.Linear(up.in_features, old_interm + n_new,
                               bias=(up.bias is not None), device=device, dtype=dtype)
            new_up.weight.copy_(torch.cat([up.weight, rand_u], dim=0))
            if up.bias is not None:
                new_up.bias.copy_(torch.cat([
                    up.bias, torch.zeros(n_new, device=device, dtype=dtype)]))
            mlp.up_proj = new_up

            # down_proj
            rand_d = torch.randn(down.out_features, n_new, generator=torch_rng,
                                 device=device, dtype=dtype) * scale
            new_down = nn.Linear(old_interm + n_new, down.out_features,
                                 bias=(down.bias is not None), device=device, dtype=dtype)
            new_down.weight.copy_(torch.cat([down.weight, rand_d], dim=1))
            if down.bias is not None:
                new_down.bias.copy_(down.bias.clone())
            mlp.down_proj = new_down

    new_interm = old_interm + n_new
    print(
        f"  [random_grow] r{round_idx} T{tier}: "
        f"intermediate_size {old_interm} -> {new_interm} (+{n_new}, random init)"
    )
    return model, tokenizer
