"""fp33_p1_native_fp8_probe.py — native-Windows torch._scaled_mm fp8 probe.

Tests whether CUTLASS fp8 GEMM initializes on native-Windows CUDA (sm89/4090).
E5 confirmed CUTLASS init fail on WSL2 (torch 2.6+cu124). This probe runs on
native Windows Python (torch 2.10+cu126) — different CUDA driver stack.

Routing spec: docs/fp33-kernel-route-v0.md
P1 PASS → fp8 training runs on native-Windows Python side (integration only)
P1 FAIL → P2 CUTLASS-direct kernel authoring in WSL2

NOT run via train MCP (WSL2-only). Native Windows Python, CC bash.
Receipt: receipts/fp33-p1-native-fp8-probe-<ts>.json
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
NC   = os.path.dirname(HERE)
RECEIPTS = os.path.join(NC, "receipts")

VRAM_FRACTION = 0.80
MARGIN_GIB    = 1.5
M, K, N       = 1024, 1024, 1024   # small matrix — probe only, not bench


def run_probe():
    import torch

    print(f"[P1] torch: {torch.__version__}", flush=True)
    print(f"[P1] device: {torch.cuda.get_device_name(0)}", flush=True)
    sm_maj, sm_min = torch.cuda.get_device_capability(0)
    print(f"[P1] sm: {sm_maj}{sm_min}", flush=True)
    cuda_ver = torch.version.cuda
    print(f"[P1] CUDA: {cuda_ver}", flush=True)

    torch.cuda.set_per_process_memory_fraction(VRAM_FRACTION)
    free_b, total_b = torch.cuda.mem_get_info()
    free_gib = free_b / (1 << 30)
    total_gib = total_b / (1 << 30)
    print(f"[P1] VRAM: {free_gib:.2f}/{total_gib:.2f} GiB free", flush=True)
    if free_gib < MARGIN_GIB:
        raise RuntimeError(f"[P1] VRAM margin violated: {free_gib:.2f} GiB")

    # Build float8 inputs
    # _scaled_mm requires: a row-major (M,K) stride=(K,1), b column-major (K,N) stride=(1,K)
    if not hasattr(torch, "float8_e4m3fn"):
        raise RuntimeError("[P1] torch.float8_e4m3fn not available on this build")

    a_bf16 = torch.randn(M, K, dtype=torch.bfloat16, device="cuda")
    a_fp8 = a_bf16.to(torch.float8_e4m3fn)          # (M,K) row-major fp8 ✓

    # Start from (N,K) row-major; .t() → (K,N) col-major with stride=(1,K)
    b_raw = torch.randn(N, K, dtype=torch.bfloat16, device="cuda")
    b_fp8 = b_raw.to(torch.float8_e4m3fn).t()        # (K,N) col-major fp8 ✓

    scale_a = torch.tensor(1.0, dtype=torch.float32, device="cuda")
    scale_b = torch.tensor(1.0, dtype=torch.float32, device="cuda")

    print(f"[P1] inputs: a={tuple(a_fp8.shape)} {a_fp8.dtype}, "
          f"b={tuple(b_fp8.shape)} {b_fp8.dtype}", flush=True)

    kernel_names: list[str] = []
    verdict = "UNKNOWN"
    error_msg = None
    elapsed_ms = None

    # Warmup run outside profiler to catch initialization failures early
    try:
        out_warm = torch._scaled_mm(a_fp8, b_fp8, scale_a=scale_a, scale_b=scale_b,
                                    out_dtype=torch.bfloat16)
        torch.cuda.synchronize()
        print("[P1] warmup _scaled_mm: OK", flush=True)
    except RuntimeError as exc:
        error_msg = str(exc)
        print(f"[P1] warmup FAILED: {exc}", flush=True)
        verdict = "FAIL"

    if verdict != "FAIL":
        # Timed + traced run
        try:
            with torch.profiler.profile(
                activities=[torch.profiler.ProfilerActivity.CUDA],
                record_shapes=False,
                with_stack=False,
            ) as prof:
                e0 = torch.cuda.Event(enable_timing=True)
                e1 = torch.cuda.Event(enable_timing=True)
                e0.record()
                out = torch._scaled_mm(a_fp8, b_fp8, scale_a=scale_a, scale_b=scale_b,
                                       out_dtype=torch.bfloat16)
                e1.record()
                torch.cuda.synchronize()

            elapsed_ms = round(e0.elapsed_time(e1), 3)
            print(f"[P1] elapsed: {elapsed_ms} ms", flush=True)
            print(f"[P1] output shape: {tuple(out.shape)} {out.dtype}", flush=True)

            # Extract kernel names from profiler trace (device_time > 0 = GPU event)
            for evt in prof.key_averages():
                if evt.key and evt.self_device_time_total > 0:
                    kernel_names.append(evt.key)
            print(f"[P1] CUDA kernels: {kernel_names}", flush=True)

            # Verify: at least one kernel dispatched and result is not NaN
            if not kernel_names:
                verdict = "FAIL"
                error_msg = "no CUDA kernels recorded — possible silent fallback"
            elif out.isnan().any():
                verdict = "FAIL"
                error_msg = "output contains NaN — fp8 numerical failure"
            else:
                verdict = "PASS"

        except RuntimeError as exc:
            error_msg = str(exc)
            verdict = "FAIL"
            print(f"[P1] traced run FAILED: {exc}", flush=True)

    torch.cuda.empty_cache()

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt = {
        "ticket": "FP33-P1-NATIVE-FP8-PROBE",
        "ts": ts,
        "verdict": verdict,
        "error": error_msg,
        "runtime": {
            "python": sys.executable,
            "torch": torch.__version__,
            "cuda": cuda_ver,
            "device": torch.cuda.get_device_name(0),
            "sm": f"{sm_maj}{sm_min}",
        },
        "probe": {
            "dtype": "float8_e4m3fn",
            "shape_a": [M, K],
            "shape_b_transposed": [K, N],
            "out_dtype": "bfloat16",
            "vram_fraction": VRAM_FRACTION,
            "margin_gib_floor": MARGIN_GIB,
        },
        "result": {
            "elapsed_ms": elapsed_ms,
            "kernel_names": kernel_names,
        },
        "routing": (
            "P1 PASS → fp8 training jobs on native-Windows Python; integration only"
            if verdict == "PASS" else
            "P1 FAIL → P2 CUTLASS-direct authoring in WSL2"
        ),
        "flags": [
            "native-Windows Python (not WSL2 daemon)",
            "E5 WSL2 result: KERNEL_ROUTE (cutlass cannot initialize)",
            "live run 12c050e7 NOT touched",
        ],
    }

    os.makedirs(RECEIPTS, exist_ok=True)
    out_path = os.path.join(RECEIPTS, f"fp33-p1-native-fp8-probe-{ts}.json")
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(receipt, f, indent=2)
    print(json.dumps(receipt, indent=2))
    print(f"FP33_P1_NATIVE_FP8_PROBE_DONE {out_path}")
    return receipt


def _selftest():
    # no GPU needed
    print(f"[P1] python: {sys.executable}")
    import torch
    assert hasattr(torch, "float8_e4m3fn"), "fp8 dtype missing"
    assert hasattr(torch, "_scaled_mm"), "_scaled_mm missing"
    print("FP33_P1_NATIVE_FP8_PROBE_SELFTEST_PASS")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        run_probe()
