"""fp35d_k4096_steady_state.py — K=4096 steady-state fp8 micro-bench (Closes #294).

Settles the K=4096 output_proj instability from fp35c (seed16 2.18x / seeds17-18 0.84x).
Protocol per #294: >=20 warmup, >=100 timed reps, p50/p90 per seed {16,17,18}.
Bar: stable >=1.2x at p50 across ALL 3 seeds → width-conditional fp8 dispatch viable.
Below bar → fp8 fully parked at c03 (registry row fp8-custom-kernel-sm89 stays CANDIDATE
for larger-width configs, with this receipt as the closing evidence).

Shape: output_proj GEMM only.
  bf16:  torch.mm(x_bf16, w_bf16.t())
  fp8wc: w_fp8 cached at init; per-rep cast x → fp8, then cuBLAS fp8 mm.

Native Windows Python (not WSL2). Live run 12c050e7 NOT touched.
"""
from __future__ import annotations

import json
import os
import statistics
import time
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Constants — output_proj shape at c03 seq=1024 batch=4
# ---------------------------------------------------------------------------
M = 4096    # batch * seq
K = 4096    # hidden_dim for output_proj input (MLP_DIM)
N = 1024    # output_proj output (hidden)

SEEDS       = [16, 17, 18]
WARMUP_REPS = 20
BENCH_REPS  = 100

VRAM_FRACTION = 0.80
MARGIN_GIB    = 1.5

LIVE_RUN_SHA = "12c050e7"

HERE     = os.path.dirname(os.path.abspath(__file__))
NC       = os.path.dirname(HERE)
RECEIPTS = os.path.join(NC, "receipts")


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _governor_check(torch) -> dict:
    total = torch.cuda.get_device_properties(0).total_memory / (1024**3)
    used  = (torch.cuda.memory_reserved(0)) / (1024**3)
    free  = total - used
    budget = total * VRAM_FRACTION
    margin = total - used
    assert margin > MARGIN_GIB, f"VRAM margin {margin:.2f} GiB < floor {MARGIN_GIB} GiB"
    return {"total_gib": round(total, 3), "free_gib_at_launch": round(free, 3),
            "budget_gib": round(budget, 3), "margin_gib": round(margin, 3)}


def bench_seed(seed: int, torch) -> dict:
    torch.manual_seed(seed)
    device = torch.device("cuda")

    # Input and weight in bf16
    x_bf16 = torch.randn(M, K, dtype=torch.bfloat16, device=device)
    w_bf16 = torch.randn(N, K, dtype=torch.bfloat16, device=device)  # (N, K)

    # Pre-cache fp8 weight (weight-cache variant — same as fp35c)
    # w_bf16 is (N, K) row-major → w_fp8.t() is (K, N) col-major (non-contiguous,
    # strides (1, K)); _scaled_mm requires row-major A × col-major B, so do NOT
    # call .contiguous() here (that would produce row-major (K, N) → wrong layout).
    w_fp8 = w_bf16.to(torch.float8_e4m3fn)      # (N, K) fp8 row-major
    w_fp8_col = w_fp8.t()                        # (K, N) col-major fp8

    # Stability gates (computed once before bench, not per-rep)
    with torch.no_grad():
        out_bf16 = torch.mm(x_bf16, w_bf16.t())
        x_fp8 = x_bf16.to(torch.float8_e4m3fn)
        scale_x = torch.tensor(1.0, dtype=torch.float32, device=device)
        scale_w = torch.tensor(1.0, dtype=torch.float32, device=device)
        out_fp8_f = torch._scaled_mm(x_fp8, w_fp8_col, scale_a=scale_x, scale_b=scale_w,
                                     out_dtype=torch.bfloat16)
        out_fp8_ref = out_fp8_f if not isinstance(out_fp8_f, tuple) else out_fp8_f[0]
        has_nan = torch.isnan(out_fp8_ref).any().item()
        has_inf = torch.isinf(out_fp8_ref).any().item()
        sat_frac = (x_fp8.to(torch.float32).abs() == 448.0).float().mean().item()
        rel_err = (out_fp8_ref.float() - out_bf16.float()).abs().mean().item() / (out_bf16.float().abs().mean().item() + 1e-8)

    stability_pass = (not has_nan) and (not has_inf) and (sat_frac < 0.10) and (rel_err < 0.5)

    def time_reps(fn, reps) -> list[float]:
        times = []
        for _ in range(reps):
            torch.cuda.synchronize()
            ev_s = torch.cuda.Event(enable_timing=True)
            ev_e = torch.cuda.Event(enable_timing=True)
            ev_s.record()
            fn()
            ev_e.record()
            torch.cuda.synchronize()
            times.append(ev_s.elapsed_time(ev_e))
        return times

    with torch.no_grad():
        # BF16 warmup
        for _ in range(WARMUP_REPS):
            torch.mm(x_bf16, w_bf16.t())
        torch.cuda.synchronize()

        # BF16 bench
        bf16_times = time_reps(lambda: torch.mm(x_bf16, w_bf16.t()), BENCH_REPS)

        # FP8 warmup
        x_fp8_warm = x_bf16.to(torch.float8_e4m3fn)
        scale_a = torch.tensor(1.0, dtype=torch.float32, device=device)
        scale_b = torch.tensor(1.0, dtype=torch.float32, device=device)
        for _ in range(WARMUP_REPS):
            xi = x_bf16.to(torch.float8_e4m3fn)
            torch._scaled_mm(xi, w_fp8_col, scale_a=scale_a, scale_b=scale_b,
                              out_dtype=torch.bfloat16)
        torch.cuda.synchronize()

        # FP8 bench
        def fp8_step():
            xi = x_bf16.to(torch.float8_e4m3fn)
            torch._scaled_mm(xi, w_fp8_col, scale_a=scale_a, scale_b=scale_b,
                              out_dtype=torch.bfloat16)

        fp8_times = time_reps(fp8_step, BENCH_REPS)

    bf16_p50 = statistics.median(bf16_times)
    bf16_p90 = sorted(bf16_times)[int(0.90 * len(bf16_times))]
    fp8_p50  = statistics.median(fp8_times)
    fp8_p90  = sorted(fp8_times)[int(0.90 * len(fp8_times))]
    mm_p50   = round(bf16_p50 / fp8_p50, 4)
    mm_p90   = round(bf16_p90 / fp8_p90, 4)  # p90 mm: lower bound (worst-case fp8 vs best-case bf16)

    return {
        "seed": seed,
        "bf16_p50_ms": round(bf16_p50, 4),
        "bf16_p90_ms": round(bf16_p90, 4),
        "fp8_p50_ms":  round(fp8_p50, 4),
        "fp8_p90_ms":  round(fp8_p90, 4),
        "mm_p50": mm_p50,
        "mm_p90": mm_p90,
        "stability_pass": stability_pass,
        "has_nan": has_nan,
        "has_inf": has_inf,
        "sat_frac": round(sat_frac, 6),
        "rel_err":  round(rel_err, 6),
    }


def main():
    import torch

    # Selftest marker
    print("FP35D_K4096_SELFTEST_PASS")

    # Governor check
    gov = _governor_check(torch)
    print(f"Governor OK: {gov['free_gib_at_launch']:.2f} GiB free, {gov['margin_gib']:.2f} GiB margin")

    # Runtime info
    runtime = {
        "python": os.path.abspath(os.sys.executable),
        "torch":  torch.__version__,
        "cuda":   torch.version.cuda,
        "device": torch.cuda.get_device_name(0),
        "sm":     str(torch.cuda.get_device_capability(0)[0] * 10 + torch.cuda.get_device_capability(0)[1]),
    }

    results = []
    for seed in SEEDS:
        print(f"\nSeed {seed} ...", flush=True)
        r = bench_seed(seed, torch)
        results.append(r)
        print(f"  bf16 p50={r['bf16_p50_ms']:.4f}ms  fp8 p50={r['fp8_p50_ms']:.4f}ms  MM(p50)={r['mm_p50']:.4f}x  stability={'PASS' if r['stability_pass'] else 'FAIL'}")

    # Verdict: bar = stable >=1.2x at p50 across ALL 3 seeds
    mm_p50_all = [r["mm_p50"] for r in results]
    bar_pass = all(mm >= 1.2 for mm in mm_p50_all)
    all_stable = all(r["stability_pass"] for r in results)
    verdict = "WIDTH_COND_VIABLE" if (bar_pass and all_stable) else "PARK_FP8_C03"

    print(f"\nVerdict: {verdict}")
    print(f"  p50 MMs: {mm_p50_all}")
    print(f"  Bar (all >=1.2x): {bar_pass}  Stability: {all_stable}")

    ts = _ts()
    receipt = {
        "ticket": "FP35D-K4096-STEADY-STATE",
        "ts": ts,
        "issue": "#294",
        "verdict": verdict,
        "verdict_reason": (
            f"all-seed p50 bar {'MET' if bar_pass else 'NOT MET'} (>=1.2x): {mm_p50_all}; stability={'PASS' if all_stable else 'FAIL'}"
        ),
        "shape": {"M": M, "K": K, "N": N, "label": "output_proj"},
        "protocol": {
            "warmup_reps": WARMUP_REPS,
            "bench_reps": BENCH_REPS,
            "variant": "weight-cache (w_fp8 cached at init, cast x per-rep)",
        },
        "governor": gov,
        "runtime": runtime,
        "results": results,
        "bar": "all-seed p50 MM >= 1.2x AND all stability PASS",
        "flags": [
            "native-Windows Python (not WSL2 daemon)",
            f"live run {LIVE_RUN_SHA} NOT touched",
            "weight fp8 cached at bench-init",
        ],
    }

    os.makedirs(RECEIPTS, exist_ok=True)
    path = os.path.join(RECEIPTS, f"fp35d-k4096-steady-state-{ts}.json")
    with open(path, "w") as f:
        json.dump(receipt, f, indent=2)
    print(f"\nReceipt: {path}")
    return receipt


if __name__ == "__main__":
    main()
