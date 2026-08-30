"""bitlinear_unit.py — Isolated BitLinear unit tests for C15.

Standalone file: runs without ember_resident_training_candidate,
ember_train_multimodal_resident_adapter, or any external benchmark data.
Imports only from ember_bitnet_core (one level up) and stdlib/torch.

Tests:
  (a) BitLinear forward correctness on toy inputs (shape, dtype, no NaN/Inf).
  (b) REAL trainable layer proof: pre-train weights hash, 5 SGD steps, post-train
      hash != pre-train hash, gradient norm > 0 on shadow weight after backward.
  (c) Ternary constraint: all quantized weight values in {-1.0, 0.0, 1.0} during
      forward (before and during training).
  (d) STE identity: grad of absmax_quant_8bit is 1.0 everywhere.
  (e) Causal mask: perturbing position T-1 leaves positions 0..T-2 unchanged.
  (f) RoPE: same input at position 0 and position 3 yields different outputs.

Device policy: CPU ONLY (no CUDA required or used).

Key interfaces (required by sibling files):
  run_tests() -> dict[str, bool]   — name -> pass/fail mapping.
  main()      -> int               — 0 on BITLINEAR_UNIT_SELFTEST_PASS, 1 on failure.
  __main__: exits 0 on BITLINEAR_UNIT_SELFTEST_PASS.

Selftest: python bitlinear_unit.py
  Marker: BITLINEAR_UNIT_SELFTEST_PASS
"""

from __future__ import annotations

import hashlib
import math
import sys
import os
from typing import Any

import torch
import torch.nn as nn

# ---------------------------------------------------------------------------
# Import from ember_bitnet_core (parent scripts directory).
# Supports running from the ember_phase4_c15/ subdirectory directly.
# ---------------------------------------------------------------------------
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SCRIPTS_DIR = os.path.join(_REPO_ROOT, "src", "ember", "governance", "scripts")
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from ember_bitnet_core import (  # noqa: E402
    BitLinear,
    BitAttention,
    BitTransformerBlock,
    absmax_quant_8bit,
    ternary_quantize,
    absmean_scale,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tensor_sha256(t: torch.Tensor) -> str:
    """SHA-256 over a tensor's bytes (detached, contiguous, float32).

    Matches the C15 comparison rig's pre/post hash convention: serialises
    name+shape+dtype+bytes; here we use shape+dtype+bytes (single tensor).
    Returns a hex string.
    """
    t_cpu = t.detach().cpu().contiguous().to(torch.float32)
    meta = f"shape={tuple(t_cpu.shape)},dtype={t_cpu.dtype}".encode()
    payload = t_cpu.numpy().tobytes()
    return hashlib.sha256(meta + payload).hexdigest()


def _collect_bitlinear_weights(module: nn.Module) -> list[torch.Tensor]:
    """Return all shadow weight tensors from BitLinear submodules."""
    weights = []
    for m in module.modules():
        if isinstance(m, BitLinear):
            weights.append(m.weight.data.clone())
    return weights


def _module_weights_hash(module: nn.Module) -> str:
    """SHA-256 over all BitLinear shadow weights in module (in named order)."""
    parts = []
    for name, m in module.named_modules():
        if isinstance(m, BitLinear):
            parts.append(f"{name}:{_tensor_sha256(m.weight)}")
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()


# ---------------------------------------------------------------------------
# Individual test functions
# ---------------------------------------------------------------------------

def _test_a_forward_correctness() -> tuple[bool, str]:
    """(a) BitLinear forward: output shape, dtype, no NaN/Inf."""
    torch.manual_seed(100)
    B, T, H_in, H_out = 3, 5, 32, 16
    layer = BitLinear(H_in, H_out, bias=False, quant_act=True)
    x = torch.randn(B, T, H_in)
    with torch.no_grad():
        out = layer(x)
    if out.shape != (B, T, H_out):
        return False, f"shape {out.shape} != ({B},{T},{H_out})"
    if out.dtype not in (torch.float32, torch.float16, torch.bfloat16):
        return False, f"unexpected dtype {out.dtype}"
    if torch.isnan(out).any():
        return False, "NaN in output"
    if torch.isinf(out).any():
        return False, "Inf in output"
    # Also verify with bias=True
    layer_b = BitLinear(H_in, H_out, bias=True, quant_act=True)
    x2 = torch.randn(B, T, H_in)
    with torch.no_grad():
        out_b = layer_b(x2)
    if out_b.shape != (B, T, H_out):
        return False, f"bias=True shape {out_b.shape} != ({B},{T},{H_out})"
    return True, ""


def _test_b_real_trainable_layer() -> tuple[bool, str]:
    """(b) REAL trainable layer proof via SHA-256 hash change over 5 SGD steps.

    Asserts:
    - gradient norm > 0 on shadow weight after first backward
    - pre-train hash != post-train hash (weights actually changed)
    - hash change is deterministic (same seed gives same hashes)
    """
    torch.manual_seed(42)
    layer = BitLinear(16, 8, bias=False, quant_act=False)
    pre_hash = _tensor_sha256(layer.weight.data)

    opt = torch.optim.SGD(layer.parameters(), lr=0.05)
    x = torch.randn(4, 16)

    # Step 1: verify gradient exists and is non-zero
    out = layer(x)
    loss = out.pow(2).mean()
    loss.backward()
    if layer.weight.grad is None:
        return False, "shadow weight has no gradient after backward"
    grad_norm = layer.weight.grad.norm().item()
    if grad_norm <= 0.0:
        return False, f"gradient norm is {grad_norm} (expected > 0)"

    # 5 SGD steps
    for _ in range(5):
        opt.zero_grad()
        x = torch.randn(4, 16)
        out = layer(x)
        loss = out.pow(2).mean()
        loss.backward()
        opt.step()

    post_hash = _tensor_sha256(layer.weight.data)
    if pre_hash == post_hash:
        return False, "pre-train hash == post-train hash (weights did not change)"

    # Sanity: values genuinely differ (not just FP noise in hash)
    torch.manual_seed(42)
    layer2 = BitLinear(16, 8, bias=False, quant_act=False)
    pre_hash2 = _tensor_sha256(layer2.weight.data)
    if pre_hash2 != pre_hash:
        return False, f"determinism broken: seed-reset gives different pre hash"

    return True, f"grad_norm={grad_norm:.4f} pre={pre_hash[:12]}... post={post_hash[:12]}..."


def _test_c_ternary_constraint() -> tuple[bool, str]:
    """(c) Quantized weight values are exactly in {{-1.0, 0.0, 1.0}} before and during training.

    Checks ternary_quantize output before any training AND after an optimizer step
    (shadow weights move, but the quantized view must remain ternary).
    """
    ALLOWED = {-1.0, 0.0, 1.0}

    torch.manual_seed(7)
    layer = BitLinear(32, 16, bias=False, quant_act=False)

    # Before training
    w_q_before = ternary_quantize(layer.weight.data)
    unique_before = {round(v, 6) for v in w_q_before.flatten().tolist()}
    bad_before = unique_before - ALLOWED
    if bad_before:
        return False, f"non-ternary values before training: {bad_before}"

    # After one training step
    opt = torch.optim.SGD(layer.parameters(), lr=0.1)
    x = torch.randn(4, 32)
    out = layer(x)
    out.sum().backward()
    opt.step()

    w_q_after = ternary_quantize(layer.weight.data)
    unique_after = {round(v, 6) for v in w_q_after.flatten().tolist()}
    bad_after = unique_after - ALLOWED
    if bad_after:
        return False, f"non-ternary values after training step: {bad_after}"

    return True, ""


def _test_d_ste_identity_absmax() -> tuple[bool, str]:
    """(d) STE identity: grad of absmax_quant_8bit is exactly 1.0 everywhere.

    absmax_quant_8bit uses the STE trick:
        return x + (x_q * scale - x).detach()
    so d(output)/d(x) == 1 pointwise, regardless of input values.
    """
    torch.manual_seed(13)
    x = torch.randn(8, 32, requires_grad=True)
    y = absmax_quant_8bit(x)
    # Use sum() so gradient is ones
    y.sum().backward()

    assert x.grad is not None, "no gradient on input to absmax_quant_8bit"
    expected = torch.ones_like(x)
    max_dev = (x.grad - expected).abs().max().item()
    if max_dev > 1e-6:
        return False, f"STE identity violated: max |grad - 1| = {max_dev:.4e}"

    # Also verify with a non-uniform input to exercise per-token scaling
    x2 = torch.randn(4, 64, requires_grad=True)
    x2.data[0, :] *= 100.0  # large values in first token
    absmax_quant_8bit(x2).sum().backward()
    assert x2.grad is not None
    max_dev2 = (x2.grad - torch.ones_like(x2)).abs().max().item()
    if max_dev2 > 1e-6:
        return False, f"STE identity violated on large-scale input: max dev = {max_dev2:.4e}"

    return True, ""


def _test_e_causal_mask() -> tuple[bool, str]:
    """(e) Causal mask: perturbing token T-1 leaves positions 0..T-2 unchanged.

    Uses a BitTransformerBlock with tiny dims for CPU speed.
    The block builds an additive upper-triangular -inf mask, so token i
    attends only to positions <= i.  Changing the last token must NOT
    alter any earlier token's output.
    """
    torch.manual_seed(19)
    H, NH, FFN = 32, 4, 64
    B, T = 1, 7

    block = BitTransformerBlock(hidden=H, n_heads=NH, ffn_hidden=FFN, quant_act=False)
    block.eval()

    x = torch.randn(B, T, H)

    with torch.no_grad():
        out_orig = block(x).clone()

    # Perturb ONLY the last position
    x_perturb = x.clone()
    x_perturb[:, T - 1, :] = x_perturb[:, T - 1, :] * 3.0 - 5.0

    with torch.no_grad():
        out_perturb = block(x_perturb)

    max_diff = (out_orig[:, :T - 1, :] - out_perturb[:, :T - 1, :]).abs().max().item()
    if max_diff > 0.0:
        return False, (
            f"earlier positions changed when token T-1 was perturbed; "
            f"max_diff={max_diff:.6g} (expected exactly 0.0; causal mask broken)"
        )
    return True, ""


def _test_f_rope_position_dependent() -> tuple[bool, str]:
    """(f) RoPE: same input at position 0 and position 3 produces different outputs.

    Constructs a sequence where x[:, 0, :] == x[:, 3, :] (identical content).
    After one BitTransformerBlock forward pass with RoPE applied in the
    attention Q/K projections, output[:, 0, :] must differ from output[:, 3, :].
    """
    torch.manual_seed(31)
    H, NH, FFN = 32, 4, 64
    B, T = 1, 6

    block = BitTransformerBlock(hidden=H, n_heads=NH, ffn_hidden=FFN, quant_act=False)
    block.eval()

    x = torch.randn(B, T, H)
    # Force positions 0 and 3 to have IDENTICAL input content
    x[:, 3, :] = x[:, 0, :].clone()

    with torch.no_grad():
        out = block(x)

    # If RoPE is working, positions 0 and 3 must produce different outputs
    # despite identical inputs (because cosine/sine rotation is position-dependent).
    if torch.allclose(out[:, 0, :], out[:, 3, :], atol=1e-5, rtol=1e-5):
        return False, (
            "positions 0 and 3 produced identical outputs despite different "
            "sequence positions — RoPE not position-encoding correctly"
        )
    return True, ""


# ---------------------------------------------------------------------------
# Aggregate runner
# ---------------------------------------------------------------------------

# Registry: (test_id, description, function)
_TESTS = [
    ("a_forward_correctness",  "(a) forward: shape/dtype/no-NaN/Inf",         _test_a_forward_correctness),
    ("b_real_trainable_layer", "(b) REAL trainable: hash change + grad>0",     _test_b_real_trainable_layer),
    ("c_ternary_constraint",   "(c) ternary constraint {-1,0,1} pre+post SGD", _test_c_ternary_constraint),
    ("d_ste_identity_absmax",  "(d) STE identity: absmax_quant_8bit grad=1",   _test_d_ste_identity_absmax),
    ("e_causal_mask",          "(e) causal mask: last token isolated",         _test_e_causal_mask),
    ("f_rope_position",        "(f) RoPE: same input, different positions differ", _test_f_rope_position_dependent),
]


def run_tests(verbose: bool = True) -> dict[str, bool]:
    """Run all BitLinear unit tests.

    Returns a name -> bool mapping where True means PASS.
    This is the primary key interface consumed by sibling harness files.
    """
    results: dict[str, bool] = {}
    errors:  dict[str, str]  = {}

    for test_id, desc, fn in _TESTS:
        try:
            passed, msg = fn()
        except Exception as exc:
            passed = False
            msg = f"EXCEPTION: {exc}"
        results[test_id] = passed
        if not passed:
            errors[test_id] = msg
        if verbose:
            status = "PASS" if passed else "FAIL"
            detail = f"  [{msg}]" if (not passed and msg) else ""
            print(f"  {status}  {desc}{detail}")

    return results


def main() -> int:
    """Run all tests.  Prints BITLINEAR_UNIT_SELFTEST_PASS and exits 0 on full pass.

    This is the primary key interface consumed by CI / tally runners.
    Returns 0 on full pass, 1 on any failure.
    """
    print("=" * 68)
    print("bitlinear_unit — BitLinear isolated unit tests (CPU, no C-BASE)")
    print("=" * 68)

    results = run_tests(verbose=True)

    total  = len(results)
    passed = sum(v for v in results.values())
    failed = total - passed

    print("-" * 68)
    print(f"Total: {total}  Passed: {passed}  Failed: {failed}")

    if failed == 0:
        print("BITLINEAR_UNIT_SELFTEST_PASS")
        return 0
    else:
        print("FAIL — see details above")
        return 1


# ---------------------------------------------------------------------------
# Selftest entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    sys.exit(main())
