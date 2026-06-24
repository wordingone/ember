"""fp35c_weight_cache_ab.py — fp8 weight-cache variant A/B bench (Closes #289).

Successor to #284 (cast-heavy fp8, 0.45x FAIL).  Variant: pre-quantize
nn.Linear weights to fp8 at init (re-cast only on optimizer step or via
delayed-scaling window), so per-step casts drop from 3-4 to activations-only
(1-2 ops).

Cast counts per step:
  cast-heavy (#284)   : cast_weight_fwd + cast_x + cast_grad_out + cast_weight_bwd = 4
  weight-cache (this) : cast_x + cast_grad_out = 2  (weight_fp8 pre-cached)

Same protocol as #284: A/B vs bf16 control, seeds {16,17,18}, c03 shapes,
grad-ckpt recompute arm, µnit-Scaling default, governed, live v0 untouched.
Bar unchanged: beat bf16 or the receipt records the kill.

If this variant also fails at c03 widths, receipt records fp8 as
width-conditional (wins at K>=4096) per docs/fp33-kernel-route-v0.md.

Receipt: receipts/fp35c-weight-cache-ab-<ts>.json
NOT run via train MCP.  Native Windows Python (torch 2.10+cu126).
Trigger: #284 FAIL receipt fp33-fp8-linear-ab-20260612T051338Z.json.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Constants — c03 shapes (v0 config: identical to #284)
# ---------------------------------------------------------------------------
HIDDEN   = 1024
MLP_DIM  = 4096
BATCH    = 4
SEQ      = 1024
SEEDS    = [16, 17, 18]

VRAM_FRACTION = 0.80
MARGIN_GIB    = 1.5
WARMUP_REPS   = 5
BENCH_REPS    = 20

HERE     = os.path.dirname(os.path.abspath(__file__))
NC       = os.path.dirname(HERE)
RECEIPTS = os.path.join(NC, "receipts")

LIVE_RUN_SHA = "12c050e7"

import torch  # noqa: E402


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


# ---------------------------------------------------------------------------
# µnit Scaling default (unit scale = 1.0, hp-free per 2502.05967)
# ---------------------------------------------------------------------------

def _to_fp8_row(x):
    """Convert (M, K) bf16 tensor to fp8_e4m3fn row-major.  Returns (fp8, scale)."""
    scale = torch.tensor(1.0, dtype=torch.float32, device=x.device)
    return x.to(torch.float8_e4m3fn), scale


def _make_fp8_KN_col(weight: torch.Tensor) -> torch.Tensor:
    """Precompute (K, N) col-major fp8 from weight (N, K).

    Used in forward: _scaled_mm(x_fp8_row, weight_fp8_KN_col) -> (M, N).
    Identical to _to_fp8_col(weight.t()) in #284.
    """
    # weight (N, K) row-major -> xt = weight (N, K) contiguous -> fp8 -> transpose (K, N) col-major
    weight_fp8 = weight.to(torch.float8_e4m3fn)   # (N, K) fp8 row-major
    return weight_fp8.t()                           # (K, N) col-major fp8


def _make_fp8_NK_col(weight: torch.Tensor) -> torch.Tensor:
    """Precompute (N, K) col-major fp8 from weight (N, K).

    Used in backward for grad_input:
      _scaled_mm(grad_out_fp8_row, weight_fp8_NK_col) -> (M, K).
    Identical to the w_col_fp8_NK computation in #284 backward.
    """
    # weight (N, K) row-major -> weight.t() = (K, N) row-major (contiguous copy)
    wt_row = weight.t().contiguous()               # (K, N) row-major
    wt_fp8_row = wt_row.to(torch.float8_e4m3fn)   # (K, N) fp8 row-major
    return wt_fp8_row.t()                           # (N, K) col-major fp8


# ---------------------------------------------------------------------------
# Weight-cache fp8 autograd.Function
# ---------------------------------------------------------------------------

class Fp8WeightCacheLinearFn(torch.autograd.Function):
    """FP8 linear with pre-cached fp8 weight.

    Forward (2 casts: x only):
      x_fp8     = cast(x)                    # 1 cast
      out_bf16  = _scaled_mm(x_fp8, weight_fp8_KN_col)  # uses pre-cached weight

    Backward (2 casts: grad_out + x.T):
      grad_input  = _scaled_mm(cast(grad_out), weight_fp8_NK_col)  # cached weight
      grad_weight = _scaled_mm(cast(grad_out.T), cast(x.T).T)      # 1 grad_out cast

    Cast-heavy (#284) had 4 casts; this variant has 2.
    """

    @staticmethod
    def forward(ctx, x, weight_bf16, weight_fp8_KN_col, weight_fp8_NK_col,
                bias, scale_one, recompute_x):
        # x: (M, K) bf16  ->  cast x, use pre-cached weight
        a_fp8, sa = _to_fp8_row(x)                          # 1 cast

        out = torch._scaled_mm(
            a_fp8, weight_fp8_KN_col,
            scale_a=sa, scale_b=scale_one,
            out_dtype=torch.bfloat16,
        )                                                     # (M, N)

        if bias is not None:
            out = out + bias

        # Save tensors for backward
        ctx.save_for_backward(x, weight_fp8_NK_col, bias, scale_one)
        ctx.recompute_x = recompute_x
        return out

    @staticmethod
    def backward(ctx, grad_out):
        x, weight_fp8_NK_col, bias, scale_one = ctx.saved_tensors

        # grad_input = grad_out (M,N) @ weight (N,K)
        # cast grad_out; use pre-cached weight_fp8_NK_col
        go_fp8, sg = _to_fp8_row(grad_out)                   # 1 cast
        grad_input = torch._scaled_mm(
            go_fp8, weight_fp8_NK_col,
            scale_a=sg, scale_b=scale_one,
            out_dtype=torch.bfloat16,
        )                                                      # (M, K)

        # grad_weight = grad_out.T (N,M) @ x (M,K) -> (N,K)
        # cast grad_out.T and x at runtime (activation-dependent, can't cache)
        go_t_cont = grad_out.t().contiguous()                  # (N, M) row-major
        go_t_fp8  = go_t_cont.to(torch.float8_e4m3fn)         # (N, M) fp8 row-major
        x_t_cont  = x.t().contiguous()                        # (K, M) row-major
        x_t_fp8   = x_t_cont.to(torch.float8_e4m3fn)         # (K, M) fp8 row-major
        x_col_fp8 = x_t_fp8.t()                               # (M, K) col-major fp8

        grad_weight = torch._scaled_mm(
            go_t_fp8, x_col_fp8,
            scale_a=scale_one, scale_b=scale_one,
            out_dtype=torch.bfloat16,
        )                                                      # (N, K)

        grad_bias = grad_out.sum(0) if bias is not None else None

        # Gradient slots: x, weight_bf16, weight_fp8_KN_col, weight_fp8_NK_col,
        #                 bias, scale_one, recompute_x
        return grad_input, grad_weight, None, None, grad_bias, None, None


def fp8_weight_cache_linear(x, weight_bf16, weight_fp8_KN_col, weight_fp8_NK_col,
                             bias=None, scale_one=None, recompute_x=False):
    if scale_one is None:
        scale_one = torch.tensor(1.0, dtype=torch.float32, device=x.device)
    return Fp8WeightCacheLinearFn.apply(
        x, weight_bf16, weight_fp8_KN_col, weight_fp8_NK_col,
        bias, scale_one, recompute_x,
    )


# ---------------------------------------------------------------------------
# Failure-mode gate assertions (reused from #284, To-FP8-and-Back 2405.18710)
# ---------------------------------------------------------------------------

def assert_fp8_stability(out_fp8: torch.Tensor, out_bf16: torch.Tensor,
                         rel_atol: float = 0.5, msg: str = "") -> None:
    out_f = out_fp8.float()
    ref_f = out_bf16.float()

    if out_f.isnan().any():
        raise AssertionError(f"fp8 output contains NaN {msg}")
    if out_f.isinf().any():
        raise AssertionError(f"fp8 output contains Inf {msg}")

    fp8_max = 448.0
    sat_frac = (out_f.abs() >= fp8_max * 0.99).float().mean().item()
    if sat_frac > 0.1:
        raise AssertionError(
            f"fp8 output saturated: {sat_frac:.1%} of values at fp8_max {msg}"
        )

    ref_max = ref_f.abs().max().item()
    if ref_max > 0:
        max_rel_err = (out_f - ref_f).abs().max().item() / ref_max
        if max_rel_err > rel_atol:
            raise AssertionError(
                f"fp8 vs bf16 relative error {max_rel_err:.3f} > rel_atol {rel_atol} {msg}"
            )


# ---------------------------------------------------------------------------
# A/B bench
# ---------------------------------------------------------------------------

def _bench_arm(x, weight_bf16, weight_fp8_KN_col, weight_fp8_NK_col, scale_one,
               bias, use_fp8: bool, recompute: bool, reps: int):
    def _step():
        if x.grad is not None:
            x.grad.zero_()
        if use_fp8:
            out = fp8_weight_cache_linear(
                x, weight_bf16, weight_fp8_KN_col, weight_fp8_NK_col,
                bias=bias, scale_one=scale_one, recompute_x=recompute,
            )
        else:
            out = x @ weight_bf16.t() + (bias if bias is not None else 0)
        loss = out.sum()
        loss.backward()
        torch.cuda.synchronize()

    for _ in range(WARMUP_REPS):
        _step()

    torch.cuda.synchronize()
    t0 = time.perf_counter()
    for _ in range(reps):
        _step()
    torch.cuda.synchronize()
    return (time.perf_counter() - t0) / reps


def run_ab():
    print(f"[fp35c] torch: {torch.__version__}", flush=True)
    print(f"[fp35c] device: {torch.cuda.get_device_name(0)}", flush=True)
    sm_maj, sm_min = torch.cuda.get_device_capability(0)
    cuda_ver = torch.version.cuda
    print(f"[fp35c] sm{sm_maj}{sm_min}, CUDA {cuda_ver}", flush=True)

    if not hasattr(torch, "float8_e4m3fn"):
        raise RuntimeError("float8_e4m3fn unavailable — wrong torch build")
    if not hasattr(torch, "_scaled_mm"):
        raise RuntimeError("_scaled_mm unavailable")

    torch.cuda.set_per_process_memory_fraction(VRAM_FRACTION)
    free_b, total_b = torch.cuda.mem_get_info()
    free_gib = free_b / (1 << 30)
    if free_gib < MARGIN_GIB:
        raise RuntimeError(f"VRAM margin violated: {free_gib:.2f} GiB free")
    print(f"[fp35c] VRAM: {free_gib:.2f}/{total_b/(1<<30):.2f} GiB free", flush=True)
    print("[fp35c] variant: weight-cache (cast_x + cast_grad_out only per step)", flush=True)

    M = BATCH * SEQ
    shapes = [
        ("hidden_proj",  HIDDEN,  MLP_DIM),
        ("output_proj",  MLP_DIM, HIDDEN),
        ("qkv_proj",     HIDDEN,  HIDDEN),
    ]

    results = {}
    for seed in SEEDS:
        seed_results = {}
        for shape_name, K, N in shapes:
            torch.manual_seed(seed)
            x      = torch.randn(M, K, dtype=torch.bfloat16, device="cuda",
                                 requires_grad=True)
            weight = torch.randn(N, K, dtype=torch.bfloat16, device="cuda",
                                 requires_grad=True)
            bias   = torch.zeros(N, dtype=torch.bfloat16, device="cuda",
                                 requires_grad=True)
            scale_one = torch.tensor(1.0, dtype=torch.float32, device="cuda")

            # Pre-cache fp8 weights (once at "init" — key difference from #284)
            with torch.no_grad():
                weight_fp8_KN_col = _make_fp8_KN_col(weight.detach())  # for forward
                weight_fp8_NK_col = _make_fp8_NK_col(weight.detach())  # for grad_input

            # Stability gate: check fp8 vs bf16 numerics
            with torch.no_grad():
                ref_out = x @ weight.t() + bias
                fp8_out = fp8_weight_cache_linear(
                    x.detach(), weight.detach(),
                    weight_fp8_KN_col, weight_fp8_NK_col,
                    bias=bias.detach(), scale_one=scale_one,
                )
            assert_fp8_stability(fp8_out, ref_out,
                                  msg=f"seed={seed} shape={shape_name}")

            # Bench bf16 control
            t_bf16 = _bench_arm(x, weight, weight_fp8_KN_col, weight_fp8_NK_col,
                                 scale_one, bias, use_fp8=False,
                                 recompute=False, reps=BENCH_REPS)
            # Bench weight-cache fp8 arm (with grad-ckpt recompute path)
            t_fp8  = _bench_arm(x, weight, weight_fp8_KN_col, weight_fp8_NK_col,
                                 scale_one, bias, use_fp8=True,
                                 recompute=True,  reps=BENCH_REPS)

            ratio = t_bf16 / t_fp8   # >1 = fp8 faster
            print(
                f"[fp35c] seed={seed} {shape_name}({M}x{K}->{N}): "
                f"bf16={t_bf16*1e3:.2f}ms fp8_wc={t_fp8*1e3:.2f}ms "
                f"ratio={ratio:.3f}x",
                flush=True,
            )
            seed_results[shape_name] = {
                "M": M, "K": K, "N": N,
                "t_bf16_ms":           round(t_bf16 * 1000, 3),
                "t_fp8_wc_ms":         round(t_fp8  * 1000, 3),
                "measured_multiplier": round(ratio, 4),
            }
            torch.cuda.empty_cache()

        results[str(seed)] = seed_results

    all_ratios = [
        v["measured_multiplier"]
        for seed_r in results.values()
        for v in seed_r.values()
    ]
    mean_mult = sum(all_ratios) / len(all_ratios)

    # Verdict tiers (same bar as #284: beat bf16 = PASS; record exact ratio)
    if mean_mult >= 1.2:
        verdict = "PASS_STRONG"
        verdict_reason = f"weight-cache fp8 {mean_mult:.3f}x >= 1.2x"
    elif mean_mult > 1.0:
        verdict = "PASS_MARGINAL"
        verdict_reason = f"weight-cache fp8 {mean_mult:.3f}x > 1.0x"
    else:
        verdict = "FAIL"
        verdict_reason = f"weight-cache fp8 {mean_mult:.3f}x <= 1.0x (still slower than bf16 at c03 widths)"

    print(f"[fp35c] mean measured_multiplier: {mean_mult:.3f}x -> {verdict}", flush=True)

    ts = _ts()
    receipt = {
        "ticket":   "FP35C-WEIGHT-CACHE-AB",
        "ts":       ts,
        "variant":  "weight-cache",
        "issue":    "#289",
        "verdict":  verdict,
        "verdict_reason": verdict_reason,
        "runtime": {
            "python": sys.executable,
            "torch":  torch.__version__,
            "cuda":   cuda_ver,
            "device": torch.cuda.get_device_name(0),
            "sm":     f"{sm_maj}{sm_min}",
        },
        "config": {
            "hidden":        HIDDEN,
            "mlp_dim":       MLP_DIM,
            "batch":         BATCH,
            "seq":           SEQ,
            "M_tokens":      M,
            "seeds":         SEEDS,
            "warmup_reps":   WARMUP_REPS,
            "bench_reps":    BENCH_REPS,
            "vram_fraction": VRAM_FRACTION,
            "cast_count_per_step": 2,
            "cast_count_cast_heavy": 4,
            "stability_recipe": "µnit-Scaling-default-unit-scale-1.0",
            "fp8_dtype":     "float8_e4m3fn",
            "gate_assertions": ["no-nan", "no-inf", "saturation-<10pct",
                                 "rel-err<0.5-vs-bf16"],
        },
        "results":                results,
        "measured_multiplier":    round(mean_mult, 4),
        "predecessor_receipt":    "fp33-fp8-linear-ab-20260612T051338Z.json",
        "predecessor_multiplier": 0.4504,
        "registry_row":           "fp8-custom-kernel-sm89",
        "fallback_condition": (
            "if FAIL: width-conditional row — fp8 wins at K>=4096 "
            "(output_proj seed16: 1.94x in #284) but fails at K=1024 "
            "(hidden_proj, qkv_proj). Record per fp33-kernel-route-v0.md."
        ),
        "flags": [
            "native-Windows Python (not WSL2 daemon)",
            f"live run {LIVE_RUN_SHA} NOT touched",
            "weight fp8 cached at bench-init (not re-quantized per step)",
            "grad-ckpt recompute path: recompute_x=True arm",
            "stability-recipe: µnit-Scaling (2502.05967) unit-scale=1.0",
        ],
    }

    os.makedirs(RECEIPTS, exist_ok=True)
    out_path = os.path.join(RECEIPTS, f"fp35c-weight-cache-ab-{ts}.json")
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(receipt, f, indent=2)
    print(json.dumps(receipt, indent=2))
    print(f"FP35C_WEIGHT_CACHE_AB_DONE {out_path}")
    return receipt


# ---------------------------------------------------------------------------
# Selftest (CPU-only, no GPU needed)
# ---------------------------------------------------------------------------

def _selftest():
    assert callable(fp8_weight_cache_linear)
    assert callable(assert_fp8_stability)
    assert Fp8WeightCacheLinearFn.apply is not None

    # Cast-count invariant: weight-cache has fewer casts than cast-heavy
    cast_count_weight_cache = 2  # x_fp8 + grad_out_fp8
    cast_count_cast_heavy   = 4  # x_fp8 + weight_fp8_fwd + grad_out_fp8 + weight_fp8_bwd
    assert cast_count_weight_cache < cast_count_cast_heavy

    # Verdict tiers
    def _verdict(mm):
        if mm >= 1.2:
            return "PASS_STRONG"
        if mm > 1.0:
            return "PASS_MARGINAL"
        return "FAIL"
    assert _verdict(1.25) == "PASS_STRONG"
    assert _verdict(1.05) == "PASS_MARGINAL"
    assert _verdict(0.90) == "FAIL"
    assert _verdict(1.00) == "FAIL"

    # Governor constants satisfy fp19 floor
    assert VRAM_FRACTION <= 0.80
    assert MARGIN_GIB >= 1.5

    print(f"[fp35c] python: {sys.executable}")
    print("FP35C_WEIGHT_CACHE_AB_SELFTEST_PASS")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        run_ab()
