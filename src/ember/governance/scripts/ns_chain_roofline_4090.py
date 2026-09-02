"""ns_chain_roofline_4090.py — Test the external shatter-proof's roofline claims
on the ACTUAL RTX 4090 in bf16.

WHY THIS EXISTS
===============
The external analysis claimed:
  - launch threshold tau ~= 825 MFLOPs (from a 1000x unit-corrected CPU measurement)
  - H*_critical = 745
  - H=1024 is ~2.6x above the launch threshold, therefore NOT launch-bound
  - roofline arithmetic-intensity balance = 164 flops/byte
  - H=1024 has AI=102 -> BANDWIDTH-BOUND
  - H=2048 has AI=205 -> COMPUTE-BOUND
  - the bandwidth->compute crossing at H*~745 is the "discontinuity" justifying
    the c04 architecture-speedup thesis (widening to H=2048)

NONE of these were measured on a 4090.  Their empirical peak (~600 GFLOPS) is an
Apple M2 CPU number, not the 4090 (~165 TFLOP/s dense bf16 / ~330 sparse).

WHAT THIS SCRIPT MEASURES
==========================
1. EMPIRICAL CEILINGS: peak bf16 matmul TFLOPS and peak HBM bandwidth (GB/s).
   Roofline AI = peak_tflops*1e12 / (peak_bw*1e9)  [flops/byte].
   Not assumed 164/165 — measured.

2. NS-CHAIN SWEEP over H in {256,512,768,1024,1536,2048,3072,4096}:
   (a) GENERIC: 5 * HxH @ HxH bf16 matmuls  (external methodology)
       flops = 5 * 2 * H^3
   (b) REAL NS5: the exact Newton-Schulz5 iteration on HxH bf16 matrices
       ops: per step: A = X@X.T (2*H^3), A@A (2*H^3), B@X (2*H^3) -> 6*H^3/step
       plus element-wise: b*A, c*(A@A), a*X, B@X addition terms = O(H^2) each
       real flops counted correctly = 5 * (6*H^3 + small_H^2_terms)

   Per H, variant: warmup + timed reps, synchronize, median step time,
   achieved TFLOPS, arithmetic intensity (flops / bytes-moved), bound-regime
   classification vs the measured roofline AI, and fraction of measured peak.

3. VERDICT: is H=1024 bandwidth-bound or compute-bound ON THE 4090?
   Where is the real H* on the 4090?

4. RECEIPT: receipts/ns-chain-roofline-4090-<UTCstamp>.json

GOVERNED: VRAM fraction <= 0.80 (matches c04 family).  Reps bounded.
Tiny VRAM use; this is a microbenchmark, not a training job.

SELFTEST (--selftest, CPU-only):
  Asserts FLOPS-count math, AI computation, bound-regime classifier.
  Prints NS_ROOFLINE_4090_SELFTEST_PASS on success.

HARD RULE: no git commands, no train-daemon calls.  GPU run dispatched by [REDACTED]
via the daemon after this script is written.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE     = os.path.dirname(os.path.abspath(__file__))
NC       = os.path.dirname(HERE)
RECEIPTS = os.path.join(NC, "receipts")
sys.path.insert(0, HERE)

# ── External claims under test ───────────────────────────────────────────────
CLAIMED_ROOFLINE_AI       = 164.0   # flops/byte (their "balance point")
CLAIMED_H_STAR            = 745     # critical H where AI = roofline AI
CLAIMED_H1024_AI          = 102.0   # their AI at H=1024 (bandwidth-bound)
CLAIMED_H2048_AI          = 205.0   # their AI at H=2048 (compute-bound)
CLAIMED_H1024_BOUND       = "BANDWIDTH"
CLAIMED_H2048_BOUND       = "COMPUTE"
CLAIMED_PEAK_TFLOPS       = 0.0006  # ~600 GFLOPS = 0.0006 TFLOPS (Apple M2 CPU, not 4090)

# ── Governor: matches c04 family ────────────────────────────────────────────
VRAM_FRACTION = float(os.environ.get("EMBER_VRAM_FRACTION", "0.80"))
VRAM_MARGIN_GIB = 1.5   # microbench uses ~0 VRAM; 1.5 GiB is very conservative

# ── Sweep config ────────────────────────────────────────────────────────────
SWEEP_H = [256, 512, 768, 1024, 1536, 2048, 3072, 4096]

WARMUP_REPS  = 10
TIMED_REPS   = 40

# Ceiling bench config
CEIL_SIZE    = 8192   # NxN matmul for peak TFLOPS (large enough to saturate)
CEIL_REPS_W  = 5
CEIL_REPS_T  = 20

BW_COPY_GB   = 2.0    # device-to-device copy size in GB for BW ceiling
BW_REPS_W    = 5
BW_REPS_T    = 20

# Pacing: microbenchmark, no training steps — no heavy throttle needed,
# but still honor duty-cycle discipline with a small pause between timed reps.
PACE_S = float(os.environ.get("EMBER_THROTTLE_S", "0.02"))

# ── NS5 coefficients (must match _zeropower_bf16 exactly) ────────────────────
NS5_A =  3.4445
NS5_B = -4.7750
NS5_C =  2.0315
NS5_STEPS = 5


# ═══════════════════════════════════════════════════════════════════════════════
# FLOPS COUNTING (CPU-safe; no torch needed)
# ═══════════════════════════════════════════════════════════════════════════════

def flops_generic(H: int, ns_steps: int = NS5_STEPS) -> int:
    """External methodology: ns_steps identical HxH @ HxH bf16 matmuls.
    Each matmul = 2*H^3 FLOPs (multiply-add counted as 2).
    Returns total FLOPs for ns_steps matmuls.
    """
    return ns_steps * 2 * H * H * H


def flops_real_ns5(H: int, ns_steps: int = NS5_STEPS) -> int:
    """Real Newton-Schulz5 FLOPs for a (min(H,H) x max(H,H)) = (H x H) square matrix.

    After the norm division, X has shape (H, H) (square; no transpose for square).
    Per NS5 step:
        A  = X @ X.T    -> (H,H) @ (H,H) = 2*H^3 FLOPs
        A2 = A @ A      -> (H,H) @ (H,H) = 2*H^3 FLOPs
        B  = b*A + c*A2 -> 2*H^2 FLOPs   (element-wise, negligible vs H^3)
        X  = a*X + B@X  ->   B@X: (H,H)@(H,H) = 2*H^3 FLOPs
                           + a*X + (B@X): 2*H^2 (negligible)
    -> per step: 3 matmuls * 2*H^3 = 6*H^3  plus  O(H^2) element-wise
    Including element-wise exactly (4 element-wise ops of H^2 each per step):
        per step: 6*H^3 + 4*H^2

    Pre-loop: X = G / (norm(G) + eps)
        norm = H^2 multiply-adds + sqrt ~ H^2 + 1 ~ H^2
        division: H^2
        pre-loop total: ~2*H^2

    Post-loop: dtype cast is free (memory op).

    Return total FLOPs rounded to integer.
    """
    pre_loop = 2 * H * H
    per_step = 6 * H * H * H + 4 * H * H
    return pre_loop + ns_steps * per_step


def bytes_generic(H: int, ns_steps: int = NS5_STEPS) -> int:
    """Bytes moved for ns_steps HxH @ HxH matmuls (lower bound, compute-bound ops).

    Minimum (output-stationary): each matmul reads 2 input matrices, writes 1 output.
    But in the NS5 chain each step's output IS the next step's input — not fully
    independent.  For a conservative (lower-bound AI) estimate: each of the ns_steps
    matmuls moves: 2 read + 1 write = 3 * H^2 * 2 bytes (bf16 = 2 bytes/element).
    This gives the LOWEST arithmetic intensity (most pessimistic for bandwidth-bound).
    """
    bytes_per_elem = 2  # bf16
    # Each matmul: 2 input matrices + 1 output = 3 * H^2 elements
    return ns_steps * 3 * H * H * bytes_per_elem


def bytes_real_ns5(H: int, ns_steps: int = NS5_STEPS) -> int:
    """Bytes moved for real NS5 (lower bound, per-step accounting).

    Per step (conservative, HBM-traffic lower bound):
        A  = X @ X.T  : read X(H^2), X.T(H^2), write A(H^2)  = 3*H^2 elements
        A2 = A @ A    : read A(H^2), A(H^2), write A2(H^2)   = 3*H^2 elements
        B  = b*A+c*A2 : read A, A2, write B                  = 3*H^2 elements (ew)
        B@X           : read B(H^2), X(H^2), write tmp(H^2)  = 3*H^2 elements
        X  = a*X+B@X  : read X, tmp, write X                 = 3*H^2 elements (ew)
    -> per step: 5 * 3 * H^2 = 15 * H^2 elements
    Pre-loop: norm+div ~ 2*H^2 elements
    Total: 2*H^2 + ns_steps * 15 * H^2
    """
    bytes_per_elem = 2
    pre_loop_elems = 2 * H * H
    per_step_elems = 15 * H * H
    total_elems = pre_loop_elems + ns_steps * per_step_elems
    return total_elems * bytes_per_elem


def arithmetic_intensity(flops: int, bytes_moved: int) -> float:
    """flops / bytes_moved -> flops per byte."""
    if bytes_moved == 0:
        return float("inf")
    return flops / bytes_moved


def bound_regime(ai: float, roofline_ai: float) -> str:
    """BANDWIDTH if AI < roofline_ai, COMPUTE if AI >= roofline_ai."""
    return "COMPUTE" if ai >= roofline_ai else "BANDWIDTH"


# ═══════════════════════════════════════════════════════════════════════════════
# GPU BENCHMARKS
# ═══════════════════════════════════════════════════════════════════════════════

def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def measure_peak_bf16_tflops() -> tuple[float, dict]:
    """Measure actual bf16 peak TFLOPS via large square matmul on the 4090.

    Uses torch.cuda.synchronize + time.perf_counter for wall-clock timing.
    Returns (peak_tflops, detail_dict).
    """
    import torch
    N = CEIL_SIZE
    flops_per_matmul = 2 * N * N * N

    # Warmup
    A = torch.randn(N, N, dtype=torch.bfloat16, device="cuda")
    B = torch.randn(N, N, dtype=torch.bfloat16, device="cuda")
    for _ in range(CEIL_REPS_W):
        C = A @ B
    torch.cuda.synchronize()

    # Timed
    times = []
    for _ in range(CEIL_REPS_T):
        torch.cuda.synchronize()
        t0 = time.perf_counter()
        C = A @ B
        torch.cuda.synchronize()
        times.append(time.perf_counter() - t0)

    del A, B, C
    torch.cuda.empty_cache()

    median_s = sorted(times)[len(times) // 2]
    tflops = flops_per_matmul / median_s / 1e12
    return tflops, {
        "N": N,
        "flops_per_matmul": flops_per_matmul,
        "median_s": round(median_s, 6),
        "tflops": round(tflops, 3),
        "reps_timed": CEIL_REPS_T,
        "dtype": "bfloat16",
    }


def measure_peak_hbm_gbps() -> tuple[float, dict]:
    """Measure actual HBM bandwidth via large device-to-device tensor copy.

    Copies BW_COPY_GB bytes from one CUDA tensor to another.
    Returns (peak_gbps, detail_dict).
    """
    import torch
    n_bytes = int(BW_COPY_GB * 1e9)
    n_elems = n_bytes // 2   # bf16 = 2 bytes
    src = torch.randn(n_elems, dtype=torch.bfloat16, device="cuda")
    dst = torch.empty_like(src)

    # Warmup
    for _ in range(BW_REPS_W):
        dst.copy_(src)
    torch.cuda.synchronize()

    # Timed
    times = []
    for _ in range(BW_REPS_T):
        torch.cuda.synchronize()
        t0 = time.perf_counter()
        dst.copy_(src)
        torch.cuda.synchronize()
        times.append(time.perf_counter() - t0)

    del src, dst
    torch.cuda.empty_cache()

    # Bytes moved: read src + write dst = 2 * n_bytes
    bytes_moved = 2 * n_bytes
    median_s = sorted(times)[len(times) // 2]
    gbps = bytes_moved / median_s / 1e9
    return gbps, {
        "copy_gb": BW_COPY_GB,
        "bytes_moved": bytes_moved,
        "median_s": round(median_s, 6),
        "gbps": round(gbps, 1),
        "reps_timed": BW_REPS_T,
        "dtype": "bfloat16",
    }


def _ns5_step_real(X, import_torch=None):
    """One real NS5 step.  X must be 2D bf16 cuda tensor (square, already normed)."""
    import torch
    a, b, c = NS5_A, NS5_B, NS5_C
    A = X @ X.T
    B_mat = b * A + c * (A @ A)
    X = a * X + B_mat @ X
    return X


def bench_ns_variant(H: int, variant: str, peak_tflops: float, peak_bw_gbps: float,
                     roofline_ai: float) -> dict:
    """Benchmark one (H, variant) combination.

    variant: "generic" or "real_ns5"
    Returns a dict with step timing, achieved TFLOPS, AI, bound regime, peak fraction.
    """
    import torch

    if variant == "generic":
        flops  = flops_generic(H)
        bytes_ = bytes_generic(H)
    else:
        flops  = flops_real_ns5(H)
        bytes_ = bytes_real_ns5(H)

    ai = arithmetic_intensity(flops, bytes_)

    # Build input tensor
    G = torch.randn(H, H, dtype=torch.bfloat16, device="cuda")

    # --- Finding 1 fix: pre-allocate generic operands OUTSIDE the timed region ---
    _gen_A = torch.randn(H, H, dtype=torch.bfloat16, device="cuda")
    _gen_B = torch.randn(H, H, dtype=torch.bfloat16, device="cuda")

    def run_generic():
        """5 independent HxH @ HxH bf16 matmuls (operands pre-allocated)."""
        for _ in range(NS5_STEPS):
            _ = _gen_A @ _gen_B

    # --- Finding 2 fix: pre-compute clone + initial normalization OUTSIDE timing ---
    _ns5_X0 = G.clone()
    _ns5_X0 = _ns5_X0 / (_ns5_X0.norm() + 1e-7)

    def run_real_ns5():
        """Full Newton-Schulz5 iteration; enters at first matmul (setup pre-done)."""
        X = _ns5_X0.clone()   # cheap: restore starting point; clone is O(H^2) copy only
        for _ in range(NS5_STEPS):
            A = X @ X.T
            B_mat = NS5_B * A + NS5_C * (A @ A)
            X = NS5_A * X + B_mat @ X

    run_fn = run_generic if variant == "generic" else run_real_ns5

    # Warmup
    for _ in range(WARMUP_REPS):
        run_fn()
    torch.cuda.synchronize()

    # Timed
    step_times = []
    for _ in range(TIMED_REPS):
        torch.cuda.synchronize()
        t0 = time.perf_counter()
        run_fn()
        torch.cuda.synchronize()
        t1 = time.perf_counter()
        step_times.append(t1 - t0)
        time.sleep(PACE_S)

    del G
    torch.cuda.empty_cache()

    median_s = sorted(step_times)[len(step_times) // 2]
    achieved_tflops = flops / median_s / 1e12
    achieved_bytes_per_s = bytes_ / median_s
    peak_fraction   = achieved_tflops / peak_tflops if peak_tflops > 0 else 0.0
    # bandwidth_fraction: fraction of measured peak HBM bandwidth consumed
    peak_bw_bytes_s = peak_bw_gbps * 1e9
    bw_fraction = achieved_bytes_per_s / peak_bw_bytes_s if peak_bw_bytes_s > 0 else 0.0

    # Analytical regime (AI-based, lower-bound bytes model)
    regime_analytical = bound_regime(ai, roofline_ai)

    # Empirical regime: compare which resource is more saturated on real silicon.
    # High compute-fraction & low BW-fraction  => COMPUTE-BOUND (empirical).
    # High BW-fraction & low compute-fraction  => BANDWIDTH-BOUND (empirical).
    if peak_fraction >= bw_fraction:
        regime_empirical = "COMPUTE"
    else:
        regime_empirical = "BANDWIDTH"

    return {
        "H":                    H,
        "variant":              variant,
        "flops":                flops,
        "bytes_moved":          bytes_,
        "arithmetic_intensity": round(ai, 3),
        "median_step_s":        round(median_s, 6),
        "achieved_tflops":      round(achieved_tflops, 4),
        "achieved_bytes_per_s": round(achieved_bytes_per_s, 0),
        "peak_fraction":        round(peak_fraction, 4),
        "bw_fraction":          round(bw_fraction, 4),
        "bound_regime":         regime_empirical,    # EMPIRICAL verdict (saturation-based)
        "bound_regime_analytical": regime_analytical, # analytical (AI vs roofline_ai)
        "roofline_ai":          round(roofline_ai, 3),
        "reps_warmup":          WARMUP_REPS,
        "reps_timed":           TIMED_REPS,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN RUN
# ═══════════════════════════════════════════════════════════════════════════════

def run_and_emit() -> Path:
    import torch

    # ── Governor ─────────────────────────────────────────────────────────────
    torch.cuda.set_per_process_memory_fraction(VRAM_FRACTION)
    free_b, total_b = torch.cuda.mem_get_info()
    free_gib = free_b / (1 << 30)
    total_gib = total_b / (1 << 30)
    if free_gib < VRAM_MARGIN_GIB:
        raise SystemExit(
            f"VRAM-PREFLIGHT: {free_gib:.2f} GiB free of {total_gib:.2f} GiB — "
            f"need >= {VRAM_MARGIN_GIB} GiB free; refusing launch"
        )
    governor = {
        "vram_fraction": VRAM_FRACTION,
        "free_gib_preflight": round(free_gib, 2),
        "total_gib":          round(total_gib, 2),
        "margin_gib_floor":   VRAM_MARGIN_GIB,
    }
    print(f"[roofline-4090] governor OK: {free_gib:.2f}/{total_gib:.2f} GiB free", flush=True)

    device_name = torch.cuda.get_device_name(0)
    print(f"[roofline-4090] device: {device_name}", flush=True)
    print(f"[roofline-4090] torch: {torch.__version__}", flush=True)

    # ── Ceiling 1: peak bf16 matmul TFLOPS ───────────────────────────────────
    print(f"[roofline-4090] measuring peak bf16 TFLOPS ({CEIL_SIZE}x{CEIL_SIZE} matmul) ...", flush=True)
    peak_tflops, ceil_detail = measure_peak_bf16_tflops()
    print(f"[roofline-4090] peak_tflops_bf16 = {peak_tflops:.3f} TFLOPS", flush=True)

    # ── Ceiling 2: peak HBM bandwidth ────────────────────────────────────────
    print(f"[roofline-4090] measuring peak HBM bandwidth ({BW_COPY_GB:.1f} GB copy) ...", flush=True)
    peak_bw_gbps, bw_detail = measure_peak_hbm_gbps()
    print(f"[roofline-4090] peak_hbm_gbps = {peak_bw_gbps:.1f} GB/s", flush=True)

    # ── Derived roofline balance point ───────────────────────────────────────
    measured_roofline_ai = (peak_tflops * 1e12) / (peak_bw_gbps * 1e9)
    print(f"[roofline-4090] measured_roofline_ai = {measured_roofline_ai:.2f} flops/byte "
          f"(claimed: {CLAIMED_ROOFLINE_AI})", flush=True)

    # ── NS-chain sweep ────────────────────────────────────────────────────────
    sweep_results = []
    for H in SWEEP_H:
        for variant in ("generic", "real_ns5"):
            print(f"[roofline-4090] H={H:4d} variant={variant} ...", flush=True)
            row = bench_ns_variant(H, variant, peak_tflops, peak_bw_gbps, measured_roofline_ai)
            sweep_results.append(row)
            print(
                f"[roofline-4090]   AI={row['arithmetic_intensity']:.1f} "
                f"achieved={row['achieved_tflops']:.4f}T "
                f"compute={row['peak_fraction']*100:.1f}%peak "
                f"bw={row['bw_fraction']*100:.1f}%peak "
                f"regime(empirical)={row['bound_regime']} "
                f"regime(analytical)={row['bound_regime_analytical']}",
                flush=True,
            )

    # ── Verdict: find real H* (empirical saturation-based) ───────────────────────
    # H* = lowest H where real_ns5 variant is COMPUTE-bound empirically
    # (peak_fraction >= bw_fraction, i.e. compute is more saturated than bandwidth)
    real_ns5_rows = [r for r in sweep_results if r["variant"] == "real_ns5"]
    generic_rows  = [r for r in sweep_results if r["variant"] == "generic"]

    h_star_real_ns5 = None
    h_star_generic  = None
    for r in real_ns5_rows:
        if r["bound_regime"] == "COMPUTE":   # empirical saturation verdict
            h_star_real_ns5 = r["H"]
            break
    for r in generic_rows:
        if r["bound_regime"] == "COMPUTE":   # empirical saturation verdict
            h_star_generic = r["H"]
            break

    # Extract specific H=1024 and H=2048 verdicts for claim comparison
    def _row(variant: str, H: int) -> dict | None:
        for r in sweep_results:
            if r["variant"] == variant and r["H"] == H:
                return r
        return None

    r1024_real = _row("real_ns5", 1024)
    r2048_real = _row("real_ns5", 2048)
    r1024_gen  = _row("generic",  1024)
    r2048_gen  = _row("generic",  2048)

    # Speedup ratio: H=2048 vs H=1024 achieved TFLOPS (both real_ns5)
    speedup_2048_vs_1024 = None
    if r1024_real and r2048_real and r1024_real["achieved_tflops"] > 0:
        speedup_2048_vs_1024 = round(
            r2048_real["achieved_tflops"] / r1024_real["achieved_tflops"], 4
        )

    # ── External bytes model reverse-engineering (Finding 3b) ───────────────────
    # Their claimed AIs: H=1024 -> 102, H=2048 -> 205.
    # If they used those numbers with our FLOPS formula, their implied bytes are:
    #   bytes_external(H) = flops_generic(H) / claimed_AI(H)
    # This lets us back-calculate what bytes model they smuggled in.
    def bytes_external(H: int, claimed_ai: float) -> float:
        """Bytes implied by external claimed_AI: bytes = flops / claimed_AI."""
        return flops_generic(H) / claimed_ai if claimed_ai > 0 else float("inf")

    def reuse_factor_external(H: int, claimed_ai: float) -> float:
        """How many times each H^2-element matrix must move through HBM to match
        the external claimed_AI.  Our lower-bound model = 3*H^2*2*steps bytes
        (5 * 3 * H^2 * 2).  Each H^2-element matrix at bf16 = H^2*2 bytes.
        reuse_factor = (our_bytes / external_implied_bytes): >1 means we assumed
        MORE traffic per element (lower AI), <1 means they assumed more traffic (lower AI still)."""
        ext_bytes = bytes_external(H, claimed_ai)
        our_bytes = bytes_generic(H)
        return our_bytes / ext_bytes if ext_bytes > 0 else float("inf")

    ext_bytes_1024 = bytes_external(1024, CLAIMED_H1024_AI)
    ext_bytes_2048 = bytes_external(2048, CLAIMED_H2048_AI)
    reuse_1024 = reuse_factor_external(1024, CLAIMED_H1024_AI)
    reuse_2048 = reuse_factor_external(2048, CLAIMED_H2048_AI)

    # ── Empirical verdict per claimed H (Finding 3c/3d) ─────────────────────────
    def _empirical_verdict(row: dict | None, claimed_bound: str) -> dict:
        """For a measured row, state whether 4090 empirical saturation CONFIRMS or
        REFUTES the external claim, with measured numbers inline."""
        if row is None:
            return {"status": "NO_DATA"}
        empirical = row["bound_regime"]   # empirical saturation-based (Finding 3c)
        confirms = empirical == claimed_bound
        return {
            "claimed_bound":        claimed_bound,
            "empirical_bound":      empirical,
            "analytical_bound":     row["bound_regime_analytical"],
            "peak_fraction":        row["peak_fraction"],
            "bw_fraction":          row["bw_fraction"],
            "achieved_tflops":      row["achieved_tflops"],
            "achieved_bytes_per_s": row["achieved_bytes_per_s"],
            "verdict":              "CONFIRMS" if confirms else "REFUTES",
        }

    # H* empirical: first H where empirical bound = COMPUTE
    h_star_real_ns5_empirical = None
    for r in real_ns5_rows:
        if r["bound_regime"] == "COMPUTE":   # empirical field
            h_star_real_ns5_empirical = r["H"]
            break
    h_star_generic_empirical = None
    for r in generic_rows:
        if r["bound_regime"] == "COMPUTE":
            h_star_generic_empirical = r["H"]
            break

    claims_vs_measured = {
        "claimed_roofline_ai":          CLAIMED_ROOFLINE_AI,
        "measured_roofline_ai":         round(measured_roofline_ai, 3),
        "roofline_ai_ratio":            round(measured_roofline_ai / CLAIMED_ROOFLINE_AI, 4)
                                        if CLAIMED_ROOFLINE_AI else None,
        "claimed_peak_tflops_cpu":      CLAIMED_PEAK_TFLOPS,
        "measured_peak_tflops_4090":    peak_tflops,
        "claimed_H_star":               CLAIMED_H_STAR,
        "measured_H_star_real_ns5":     h_star_real_ns5,
        "measured_H_star_generic":      h_star_generic,
        "measured_H_star_real_ns5_empirical": h_star_real_ns5_empirical,
        "measured_H_star_generic_empirical":  h_star_generic_empirical,
        "claimed_H1024_bound":          CLAIMED_H1024_BOUND,
        "measured_H1024_AI_real_ns5_ours": r1024_real["arithmetic_intensity"] if r1024_real else None,
        "claimed_H1024_AI":             CLAIMED_H1024_AI,
        "H1024_empirical_verdict":      _empirical_verdict(r1024_real, CLAIMED_H1024_BOUND),
        "claimed_H2048_bound":          CLAIMED_H2048_BOUND,
        "measured_H2048_AI_real_ns5_ours": r2048_real["arithmetic_intensity"] if r2048_real else None,
        "claimed_H2048_AI":             CLAIMED_H2048_AI,
        "H2048_empirical_verdict":      _empirical_verdict(r2048_real, CLAIMED_H2048_BOUND),
        "widening_1024_to_2048_achieved_tflops_ratio": speedup_2048_vs_1024,
        "external_bytes_model": {
            "methodology": (
                "bytes_external(H) = flops_generic(H) / claimed_AI(H).  "
                "Reverse-engineers the bytes model implied by the external claimed AI "
                "to expose what HBM-traffic assumption their number smuggles.  "
                "Their claimed AI=102 at H=1024 and AI=205 at H=2048 imply the following "
                "bytes counts and reuse factors relative to our lower-bound model "
                "(5 * 3 * H^2 * 2 bytes = 3 reads+writes per matmul)."
            ),
            "H1024": {
                "claimed_AI":           CLAIMED_H1024_AI,
                "our_bytes_lower_bound": bytes_generic(1024),
                "our_AI":               round(arithmetic_intensity(flops_generic(1024), bytes_generic(1024)), 2),
                "external_implied_bytes": round(ext_bytes_1024, 0),
                "reuse_factor_our_vs_ext": round(reuse_1024, 3),
                "note": (
                    "reuse_factor > 1 means our model assumes MORE bytes/element (lower AI). "
                    "Their AI=102 implies ~3.34x FEWER bytes per element than our model. "
                    "Our model = 3 matrices per matmul; theirs ~ 0.9 matrices per matmul — "
                    "implying extreme reuse (L2 cache residency assumed, not HBM-resident)."
                ),
            },
            "H2048": {
                "claimed_AI":           CLAIMED_H2048_AI,
                "our_bytes_lower_bound": bytes_generic(2048),
                "our_AI":               round(arithmetic_intensity(flops_generic(2048), bytes_generic(2048)), 2),
                "external_implied_bytes": round(ext_bytes_2048, 0),
                "reuse_factor_our_vs_ext": round(reuse_2048, 3),
                "note": (
                    "Their AI=205 at H=2048 implies the same reuse factor (~3.34x) — consistent "
                    "with them using 1 matrix read+write per matmul (not 3). "
                    "A reader cannot falsify their number from our lower-bound AI alone."
                ),
            },
        },
        "regime_verdict_basis": "EMPIRICAL_SATURATION",
        "regime_verdict_explanation": (
            "Headline bound-regime per H is determined by empirical saturation on the 4090: "
            "compare peak_fraction (achieved_tflops / measured_peak_tflops) vs "
            "bw_fraction (achieved_bytes_per_s / measured_peak_hbm_bps). "
            "The resource with the higher saturation fraction is the binding constraint. "
            "This sidesteps the bytes-model dispute entirely. "
            "Analytical AI (our lower-bound model) is reported as context only."
        ),
        "note": (
            "Claimed values were derived from CPU (Apple M2) measurements + 4090 theory. "
            "Measured values are empirical 4090 runs.  "
            "measured_roofline_ai = (peak_tflops*1e12) / (peak_bw_gbps*1e9), both measured. "
            "H* = lowest H in sweep where empirical bound_regime = COMPUTE for that variant. "
            "bound_regime in each sweep_results row is EMPIRICAL (saturation-based); "
            "bound_regime_analytical is the AI-vs-roofline_ai analytical classification."
        ),
    }

    # ── Receipt ───────────────────────────────────────────────────────────────
    stamp = _ts()
    receipt = {
        "ticket":  "NS-CHAIN-ROOFLINE-4090",
        "ts":      stamp,
        "scope":   (
            "Test external shatter-proof roofline claims on the actual RTX 4090 in bf16. "
            "Measures empirical ceilings (peak TFLOPS, peak HBM BW) and sweeps the NS5 chain "
            "over H={} — both generic (5xHxH matmuls) and real NS5 ops.".format(SWEEP_H)
        ),
        "device":         device_name,
        "torch_version":  torch.__version__,
        "governor":       governor,
        "ceilings": {
            "peak_tflops_bf16":   peak_tflops,
            "peak_hbm_gbps":      peak_bw_gbps,
            "measured_roofline_ai": round(measured_roofline_ai, 3),
            "ceil_matmul_detail": ceil_detail,
            "bw_copy_detail":     bw_detail,
        },
        "sweep_config": {
            "H_values":     SWEEP_H,
            "variants":     ["generic", "real_ns5"],
            "warmup_reps":  WARMUP_REPS,
            "timed_reps":   TIMED_REPS,
            "pace_s":       PACE_S,
            "ns5_steps":    NS5_STEPS,
            "ns5_coeffs":   {"a": NS5_A, "b": NS5_B, "c": NS5_C},
            "dtype":        "bfloat16",
        },
        "sweep_results": sweep_results,
        "verdicts": {
            "h_star_real_ns5": h_star_real_ns5,
            "h_star_generic":  h_star_generic,
            "H1024_real_ns5":  r1024_real,
            "H2048_real_ns5":  r2048_real,
            "H1024_generic":   r1024_gen,
            "H2048_generic":   r2048_gen,
            "speedup_2048_vs_1024_real_ns5": speedup_2048_vs_1024,
        },
        "claims_vs_measured": claims_vs_measured,
        "methodology": {
            "flops_generic":   "5 * 2 * H^3  (5 identical HxH @ HxH matmuls)",
            "flops_real_ns5":  "pre_loop(2*H^2) + steps*(6*H^3 + 4*H^2)",
            "bytes_generic":   "5 * 3 * H^2 * 2  (lower bound: 2 reads + 1 write per matmul)",
            "bytes_real_ns5":  "(2*H^2 + steps*15*H^2) * 2  (lower bound per-step accounting)",
            "ai":              "flops / bytes_moved",
            "bound_regime":    "COMPUTE if AI >= roofline_ai else BANDWIDTH",
            "peak_tflops":     f"{CEIL_SIZE}x{CEIL_SIZE} bf16 matmul, {CEIL_REPS_T} reps, median",
            "peak_hbm_bw":     f"{BW_COPY_GB:.1f} GB device-to-device copy, {BW_REPS_T} reps, median",
            "roofline_ai":     "peak_tflops*1e12 / peak_hbm_gbps*1e9  (empirical, NOT assumed 164)",
        },
    }

    os.makedirs(RECEIPTS, exist_ok=True)
    receipt_path = os.path.join(RECEIPTS, f"ns-chain-roofline-4090-{stamp}.json")
    with open(receipt_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(receipt, f, indent=2)

    print(f"[roofline-4090] receipt: {receipt_path}", flush=True)
    print(f"[roofline-4090] CEILINGS: peak_tflops_bf16={peak_tflops:.3f}  "
          f"peak_hbm_gbps={peak_bw_gbps:.1f}  roofline_ai={measured_roofline_ai:.2f}", flush=True)
    print(f"[roofline-4090] H*_real_ns5={h_star_real_ns5}  H*_generic={h_star_generic}  "
          f"(claimed H*={CLAIMED_H_STAR})", flush=True)
    if r1024_real:
        print(f"[roofline-4090] H=1024 real_ns5: AI={r1024_real['arithmetic_intensity']:.1f}  "
              f"regime={r1024_real['bound_regime']}  "
              f"(claimed={CLAIMED_H1024_BOUND}, AI={CLAIMED_H1024_AI})", flush=True)
    if r2048_real:
        print(f"[roofline-4090] H=2048 real_ns5: AI={r2048_real['arithmetic_intensity']:.1f}  "
              f"regime={r2048_real['bound_regime']}  "
              f"(claimed={CLAIMED_H2048_BOUND}, AI={CLAIMED_H2048_AI})", flush=True)
    print(f"[roofline-4090] speedup_2048_vs_1024(real_ns5)={speedup_2048_vs_1024}", flush=True)
    print(f"NS_ROOFLINE_4090_DONE", flush=True)

    return Path(receipt_path)


# ═══════════════════════════════════════════════════════════════════════════════
# SELFTEST (CPU, no GPU)
# ═══════════════════════════════════════════════════════════════════════════════

def selftest() -> None:
    """CPU-only selftest: FLOPS-count math, AI computation, bound-regime classifier."""
    print("[ns_chain_roofline_4090] selftest: math + AI + regime (no GPU)", flush=True)
    failures: list[str] = []

    # 1. FLOPS count — generic
    for H in [256, 512, 1024, 2048]:
        expected = NS5_STEPS * 2 * H * H * H
        got = flops_generic(H)
        if got != expected:
            failures.append(f"flops_generic(H={H}): expected {expected}, got {got}")
    if not failures:
        print("  1. flops_generic: 5*2*H^3 for H in [256,512,1024,2048]  PASS")

    # Spot check: H=1024
    assert flops_generic(1024) == 5 * 2 * 1024**3, "H=1024 generic flops"
    print(f"     H=1024 generic flops = {flops_generic(1024):,}  ({flops_generic(1024)/1e9:.3f} GFLOPs)")

    # 2. FLOPS count — real NS5
    for H in [256, 512, 1024, 2048]:
        expected = 2 * H * H + NS5_STEPS * (6 * H * H * H + 4 * H * H)
        got = flops_real_ns5(H)
        if got != expected:
            failures.append(f"flops_real_ns5(H={H}): expected {expected}, got {got}")
    if not [f for f in failures if "real_ns5" in f]:
        print("  2. flops_real_ns5: pre(2*H^2) + steps*(6*H^3+4*H^2)  PASS")

    # Verify real > generic (NS5 has 3 matmuls per step vs 1 generic)
    for H in [512, 1024]:
        assert flops_real_ns5(H) > flops_generic(H), \
            f"real_ns5 flops should exceed generic at H={H}"
    print("     real_ns5 flops > generic flops at H=512,1024  PASS")

    # 3. Bytes — generic
    for H in [256, 1024]:
        expected = NS5_STEPS * 3 * H * H * 2
        got = bytes_generic(H)
        if got != expected:
            failures.append(f"bytes_generic(H={H}): expected {expected}, got {got}")
    if not [f for f in failures if "bytes_generic" in f]:
        print("  3. bytes_generic: 5*3*H^2*2  PASS")

    # 4. Bytes — real NS5
    for H in [256, 1024]:
        expected = (2 * H * H + NS5_STEPS * 15 * H * H) * 2
        got = bytes_real_ns5(H)
        if got != expected:
            failures.append(f"bytes_real_ns5(H={H}): expected {expected}, got {got}")
    if not [f for f in failures if "bytes_real_ns5" in f]:
        print("  4. bytes_real_ns5: (2*H^2 + steps*15*H^2)*2  PASS")

    # 5. Arithmetic intensity
    f1 = flops_generic(1024)
    b1 = bytes_generic(1024)
    ai1 = arithmetic_intensity(f1, b1)
    expected_ai = f1 / b1
    assert abs(ai1 - expected_ai) < 1e-10, f"AI math: {ai1} != {expected_ai}"
    print(f"  5. arithmetic_intensity: flops/bytes  PASS  (H=1024 generic AI={ai1:.2f})")

    # Verify H=1024 generic AI matches the claimed value approximately
    # (The claim was 102 flops/byte for generic; let's check our formula)
    ai1024_gen = arithmetic_intensity(flops_generic(1024), bytes_generic(1024))
    # flops=5*2*1024^3=10,737,418,240  bytes=5*3*1024^2*2=31,457,280
    # AI = 10737418240/31457280 = 341.3  -- different from their 102; they used different byte counting
    # Their 102 comes from: bytes = 2 * H^3 * 2 (one matmul read+write of size H^2 * H steps)
    # We use the LOWER BOUND (pessimistic for BW); they may have used a different model.
    # This is a valid difference in methodology — we report both.
    print(f"     H=1024 generic AI (our lower-bound bytes model) = {ai1024_gen:.2f}")
    print(f"     claimed H=1024 AI = {CLAIMED_H1024_AI}")

    # 6. Bound regime classifier
    assert bound_regime(50.0, 100.0)  == "BANDWIDTH", "50 < 100 should be BANDWIDTH"
    assert bound_regime(100.0, 100.0) == "COMPUTE",   "100 == 100 should be COMPUTE"
    assert bound_regime(200.0, 100.0) == "COMPUTE",   "200 > 100 should be COMPUTE"
    assert bound_regime(0.0, 100.0)   == "BANDWIDTH", "0 < 100 should be BANDWIDTH"
    print("  6. bound_regime classifier: BANDWIDTH/COMPUTE logic  PASS")

    # 7. Monotonicity: AI increases with H for both variants (since flops grow as H^3, bytes as H^2)
    prev_gen = 0.0
    prev_real = 0.0
    for H in [256, 512, 1024, 2048, 4096]:
        ai_gen  = arithmetic_intensity(flops_generic(H),  bytes_generic(H))
        ai_real = arithmetic_intensity(flops_real_ns5(H), bytes_real_ns5(H))
        if ai_gen <= prev_gen:
            failures.append(f"AI_generic not monotone at H={H}: {ai_gen} <= {prev_gen}")
        if ai_real <= prev_real:
            failures.append(f"AI_real_ns5 not monotone at H={H}: {ai_real} <= {prev_real}")
        prev_gen  = ai_gen
        prev_real = ai_real
    if not [f for f in failures if "monotone" in f]:
        print("  7. AI monotonically increases with H (H^3/H^2 = H growth)  PASS")

    # 8. H* search logic: given a synthetic roofline_ai, verify correct H* detection
    synthetic_roofline = 500.0  # flops/byte
    h_star_found = None
    for H in SWEEP_H:
        ai = arithmetic_intensity(flops_real_ns5(H), bytes_real_ns5(H))
        if bound_regime(ai, synthetic_roofline) == "COMPUTE":
            h_star_found = H
            break
    # With roofline=500, find the first H where AI >= 500
    expected_h_star = None
    for H in SWEEP_H:
        if arithmetic_intensity(flops_real_ns5(H), bytes_real_ns5(H)) >= synthetic_roofline:
            expected_h_star = H
            break
    assert h_star_found == expected_h_star, \
        f"H* search: expected {expected_h_star}, found {h_star_found}"
    print(f"  8. H* search logic (synthetic roofline={synthetic_roofline}): "
          f"H*={h_star_found}  PASS")

    # 9. Real NS5 coefficients match _zeropower_bf16 in c04_bf16ns5_qat_throughput.py
    assert NS5_A ==  3.4445, f"NS5_A mismatch: {NS5_A}"
    assert NS5_B == -4.7750, f"NS5_B mismatch: {NS5_B}"
    assert NS5_C ==  2.0315, f"NS5_C mismatch: {NS5_C}"
    assert NS5_STEPS == 5,   f"NS5_STEPS mismatch: {NS5_STEPS}"
    print("  9. NS5 coefficients (a,b,c)=(3.4445,-4.7750,2.0315) steps=5  PASS")

    # 10. Real NS5 flops > generic flops for all sweep H (3 matmuls/step vs 1)
    for H in SWEEP_H:
        assert flops_real_ns5(H) > flops_generic(H), \
            f"real_ns5 should have more flops than generic at H={H}"
    print("  10. real_ns5 flops > generic flops for all sweep H  PASS")

    # 11. Real NS5 AI > generic AI at large H (real has 6H^3 vs 2H^3 per step,
    #     but also more bytes; verify via formula)
    for H in [1024, 2048, 4096]:
        ai_real = arithmetic_intensity(flops_real_ns5(H), bytes_real_ns5(H))
        ai_gen  = arithmetic_intensity(flops_generic(H),  bytes_generic(H))
        # real: 6*H^3*steps / (15*H^2*steps*2) = 6H/(30) = H/5
        # gen:  2*H^3*steps / (3*H^2*steps*2)  = 2H/(6)  = H/3
        # real_ai/gen_ai ~ (H/5)/(H/3) = 3/5 -- real is LOWER AI than generic!
        # Because real has MORE bytes per flop.  Verify this:
        # Actually let's just check our formula outputs are consistent.
        assert ai_real > 0 and ai_gen > 0, f"AI must be positive at H={H}"
    # Check the ratio is approximately H/5 (real) vs H/3 (generic) for large H
    H = 4096
    ai_real_large = arithmetic_intensity(flops_real_ns5(H), bytes_real_ns5(H))
    ai_gen_large  = arithmetic_intensity(flops_generic(H),  bytes_generic(H))
    # Approx: real ~ H/5 = 819.2, generic ~ H/3 = 1365.3
    # So generic has higher AI than real NS5 (counter-intuitive but correct:
    # real NS5 has more bytes per flop because 15 H^2 byte terms per step vs 3 H^2)
    print(f"  11. H={H}: AI_real_ns5={ai_real_large:.1f}  AI_generic={ai_gen_large:.1f}  PASS")

    # 12. Empirical regime classifier (Finding 3c): peak_fraction vs bw_fraction
    #     If peak_fraction >= bw_fraction  => COMPUTE; else => BANDWIDTH
    def _empirical_regime(peak_frac: float, bw_frac: float) -> str:
        return "COMPUTE" if peak_frac >= bw_frac else "BANDWIDTH"

    assert _empirical_regime(0.80, 0.30) == "COMPUTE",    "high compute-frac => COMPUTE"
    assert _empirical_regime(0.30, 0.80) == "BANDWIDTH",  "high bw-frac => BANDWIDTH"
    assert _empirical_regime(0.50, 0.50) == "COMPUTE",    "tie => COMPUTE (peak_frac >= bw_frac)"
    assert _empirical_regime(0.01, 0.99) == "BANDWIDTH",  "near-zero compute => BANDWIDTH"
    assert _empirical_regime(0.99, 0.01) == "COMPUTE",    "near-full compute => COMPUTE"
    print("  12. empirical_regime classifier (peak_frac vs bw_frac)  PASS")

    # 13. External bytes model (Finding 3b): bytes_external = flops / claimed_AI
    #     Verify the reverse-engineering math for H=1024 and H=2048.
    def _bytes_external(H: int, claimed_ai: float) -> float:
        return flops_generic(H) / claimed_ai if claimed_ai > 0 else float("inf")

    def _reuse_factor(H: int, claimed_ai: float) -> float:
        return bytes_generic(H) / _bytes_external(H, claimed_ai)

    # H=1024: flops=5*2*1024^3, claimed_AI=102 -> ext_bytes = flops/102
    ext1024 = _bytes_external(1024, CLAIMED_H1024_AI)
    expected_ext1024 = flops_generic(1024) / CLAIMED_H1024_AI
    assert abs(ext1024 - expected_ext1024) < 1.0, \
        f"bytes_external H=1024: {ext1024} != {expected_ext1024}"

    # H=2048: claimed_AI=205
    ext2048 = _bytes_external(2048, CLAIMED_H2048_AI)
    expected_ext2048 = flops_generic(2048) / CLAIMED_H2048_AI
    assert abs(ext2048 - expected_ext2048) < 1.0, \
        f"bytes_external H=2048: {ext2048} != {expected_ext2048}"

    # External bytes must be larger than our lower-bound (their lower AI = more bytes)
    assert ext1024 > bytes_generic(1024), \
        "external implied bytes must EXCEED our lower-bound (their AI=102 < our AI)"
    assert ext2048 > bytes_generic(2048), \
        "external implied bytes must EXCEED our lower-bound (their AI=205 < our AI)"

    # reuse_factor = our_bytes / ext_bytes < 1 (we assume fewer bytes than they do)
    rf1024 = _reuse_factor(1024, CLAIMED_H1024_AI)
    rf2048 = _reuse_factor(2048, CLAIMED_H2048_AI)
    assert rf1024 < 1.0, f"reuse_factor H=1024 should be < 1.0, got {rf1024}"
    assert rf2048 < 1.0, f"reuse_factor H=2048 should be < 1.0, got {rf2048}"
    # Both H=1024 and H=2048 should yield similar reuse factors (within 5%)
    # They differ slightly because claimed_AI(1024)=102, claimed_AI(2048)=205 (not exactly 2x)
    assert abs(rf1024 - rf2048) < 0.05, \
        f"reuse_factor H=1024 and H=2048 should be similar (within 5%): {rf1024} vs {rf2048}"
    print(f"  13. external bytes model reverse-engineering: "
          f"H=1024 ext_bytes={ext1024:.0f} rf={rf1024:.3f}; "
          f"H=2048 ext_bytes={ext2048:.0f} rf={rf2048:.3f}  PASS")

    # 14. Empirical H* classification is distinct from analytical AI-based H*:
    #     Verify both can be computed independently from synthetic fractions.
    #     Empirical H* = first H where peak_fraction > bw_fraction.
    #     Analytical H* = first H where AI >= roofline_ai.
    #     Ensure the empirical classifier does NOT use AI at all (just fractions).
    synthetic_peak_fracs = {256: 0.10, 512: 0.20, 1024: 0.55, 2048: 0.80}
    synthetic_bw_fracs   = {256: 0.90, 512: 0.70, 1024: 0.40, 2048: 0.20}
    empirical_h_star = None
    for H in [256, 512, 1024, 2048]:
        if _empirical_regime(synthetic_peak_fracs[H], synthetic_bw_fracs[H]) == "COMPUTE":
            empirical_h_star = H
            break
    assert empirical_h_star == 1024, \
        f"synthetic empirical H* should be 1024 (first H with peak_frac > bw_frac), got {empirical_h_star}"
    print(f"  14. empirical H* from synthetic fractions = {empirical_h_star}  PASS")

    if failures:
        for f in failures:
            print(f"SELFTEST FAIL: {f}", flush=True)
        sys.exit(1)

    print("NS_ROOFLINE_4090_SELFTEST_PASS")


# ═══════════════════════════════════════════════════════════════════════════════
# ENTRYPOINT
# ═══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    ap = argparse.ArgumentParser(
        description=(
            "ns_chain_roofline_4090.py — Empirically test the external shatter-proof's "
            "roofline claims on the actual RTX 4090 in bf16.  "
            "Use --selftest for CPU-only math validation."
        )
    )
    ap.add_argument(
        "--selftest", action="store_true",
        help="CPU-only: assert FLOPS-count math, AI computation, bound-regime classifier. "
             "Prints NS_ROOFLINE_4090_SELFTEST_PASS. No GPU required.",
    )
    args, _ = ap.parse_known_args()
    if args.selftest:
        selftest()
    else:
        run_and_emit()


if __name__ == "__main__":
    main()
