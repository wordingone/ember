"""
c04_dynamo_patch.py -- Standalone patch for torch.compile(fullgraph=True) on c04 step.

Two blockers in torch 2.6.0+cu124 + transformers 5.2.0:

BLOCKER 1 — timeshare_pretrain.chunked_cross_entropy
  1. int(mask.sum()) in hot loop -- forces CPU sync + Python int, breaks dynamo trace
  2. if n_valid == 0: -- data-dependent Python branch -> UserError in dynamo
     "Could not guard on data-dependent expression Eq(u0, 0)"

BLOCKER 2 — LlamaModel.forward decorated with @merge_with_config_defaults
  Decorator at transformers/utils/generic.py:865 does:
    func.__code__.co_varnames.__contains__('use_cache')
  at each call — __code__ introspection is not dynamo-traceable:
    "call_method GetAttrVariable(GetSetDescriptorVariable(), co_varnames) __contains__"

Usage:
    import c04_dynamo_patch
    c04_dynamo_patch.apply()                  # patches chunked_cross_entropy
    c04_dynamo_patch.apply_compile_patch(backbone)  # strips co_varnames wrapper

    # fwd_bwd() can now be compiled with fullgraph=True.
    # NOTE: time.perf_counter() inside the full step() breaks fullgraph=True —
    # compile only the fwd+bwd portion; optimizer step + timing stay outside.

Call apply() once before any torch.compile call (patches ts module globally).
Call apply_compile_patch(backbone) once per backbone instance before torch.compile.
"""

import torch
import timeshare_pretrain as _ts


# ── BLOCKER 1 FIX ────────────────────────────────────────────────────────────

def _chunked_ce_dynamo(hidden, weight, targets, *, chunk_tokens=1024, ignore_index=-100):
    """Dynamo-safe chunked cross-entropy.

    Differences from original (timeshare_pretrain.py:927):
    - n_valid stays tensor throughout (no int() cast, no CPU sync per chunk)
    - zero-valid guard uses torch.where instead of data-dependent Python if
    Both changes are semantically identical for non-zero n_valid (the common case).
    """
    n = hidden.shape[0]
    total_nll = hidden.new_zeros(())
    total_valid = hidden.new_zeros((), dtype=torch.long)
    for s in range(0, n, chunk_tokens):
        e = min(s + chunk_tokens, n)
        logits = hidden[s:e] @ weight.T
        logp = torch.log_softmax(logits, dim=-1)
        t = targets[s:e]
        mask = t != ignore_index
        safe_t = t.clamp(min=0).unsqueeze(-1)
        nll = -logp.gather(-1, safe_t).squeeze(-1)
        total_nll = total_nll + (nll * mask).sum()
        total_valid = total_valid + mask.sum()
    loss = torch.where(
        total_valid > 0,
        total_nll / total_valid.clamp(min=1).to(total_nll.dtype),
        torch.zeros_like(total_nll),
    )
    return loss, total_valid


def apply():
    """Patch timeshare_pretrain.chunked_cross_entropy. Call once before torch.compile."""
    _ts.chunked_cross_entropy = _chunked_ce_dynamo
    return "c04_dynamo_patch applied: chunked_cross_entropy -> dynamo-safe (tensor n_valid + torch.where)"


# ── BLOCKER 2 FIX ────────────────────────────────────────────────────────────

def apply_compile_patch(backbone):
    """Strip the co_varnames-inspecting decorator from backbone.forward.

    @merge_with_config_defaults in transformers 5.2 wraps forward with a wrapper
    that calls func.__code__.co_varnames.__contains__('use_cache') at every call.
    dynamo cannot trace __code__ introspection under fullgraph=True.

    Fix: replace backbone.forward with the unwrapped original via inspect.unwrap().
    The decorator uses functools.wraps, so __wrapped__ points to the original fn.
    LlamaModel.forward handles use_cache=None internally via self.config.use_cache,
    so removing the decorator is semantically safe when use_cache=False is in config.

    Args:
        backbone: LlamaModel instance (or any transformers model with wrapped forward)

    Returns:
        backbone (same object, forward replaced in-place)
    """
    import types
    import inspect

    fwd = backbone.forward
    fn = getattr(fwd, '__func__', fwd)   # bound method → underlying function
    orig_fn = inspect.unwrap(fn)         # follow __wrapped__ chain to original

    if orig_fn is fn:
        print("[c04_dynamo_patch] apply_compile_patch: forward already unwrapped, no-op")
        return backbone

    backbone.forward = types.MethodType(orig_fn, backbone)
    return backbone
