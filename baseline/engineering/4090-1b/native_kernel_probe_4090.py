#!/usr/bin/env python3
"""Native/Triton kernel probe for the single-4090 >=1B baseline.

This bounded probe compares PyTorch matmul with a simple Triton matmul kernel at
C1 transformer-relevant shapes. It is a native-ceiling telemetry receipt, not a
full training run and not a claim that native optimization is exhausted.
"""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def analytical_parameter_count(model: dict[str, Any]) -> int:
    vocab = int(model["vocab_size"])
    seq = int(model["sequence_length"])
    layers = int(model["n_layers"])
    d = int(model["n_embd"])
    mlp = int(model.get("mlp_ratio", 4)) * d
    bias = 1 if model.get("bias", False) else 0
    token_embedding = vocab * d
    position_embedding = seq * d
    attention = layers * ((3 * d * d + 3 * d * bias) + (d * d + d * bias))
    mlp_params = layers * ((d * mlp + mlp * bias) + (mlp * d + d * bias))
    norms = layers * 4 * d + 2 * d
    lm_head = 0 if model.get("tie_embeddings", True) else vocab * d
    return token_embedding + position_embedding + attention + mlp_params + norms + lm_head


def run_probe(args: argparse.Namespace, raw: dict[str, Any], params: int) -> dict[str, Any]:
    import torch
    import triton
    import triton.language as tl

    if not torch.cuda.is_available():
        return {"verdict": "INVALID_RUN_CUDA_UNAVAILABLE", "cuda_available": False, "torch_version": torch.__version__}

    @triton.jit
    def matmul_kernel(a, b, c, M: tl.constexpr, N: tl.constexpr, K: tl.constexpr, BLOCK_M: tl.constexpr, BLOCK_N: tl.constexpr, BLOCK_K: tl.constexpr):
        pid_m = tl.program_id(0)
        pid_n = tl.program_id(1)
        offs_m = pid_m * BLOCK_M + tl.arange(0, BLOCK_M)
        offs_n = pid_n * BLOCK_N + tl.arange(0, BLOCK_N)
        offs_k = tl.arange(0, BLOCK_K)
        acc = tl.zeros((BLOCK_M, BLOCK_N), tl.float32)
        for k0 in range(0, K, BLOCK_K):
            a_ptrs = a + offs_m[:, None] * K + (k0 + offs_k[None, :])
            b_ptrs = b + (k0 + offs_k[:, None]) * N + offs_n[None, :]
            a_mask = (offs_m[:, None] < M) & ((k0 + offs_k[None, :]) < K)
            b_mask = ((k0 + offs_k[:, None]) < K) & (offs_n[None, :] < N)
            av = tl.load(a_ptrs, mask=a_mask, other=0.0)
            bv = tl.load(b_ptrs, mask=b_mask, other=0.0)
            acc += tl.dot(av, bv)
        c_ptrs = c + offs_m[:, None] * N + offs_n[None, :]
        tl.store(c_ptrs, acc, mask=(offs_m[:, None] < M) & (offs_n[None, :] < N))

    def triton_matmul(a, b):
        m = a.shape[0]
        k = a.shape[1]
        n = b.shape[1]
        c = torch.empty((m, n), device=a.device, dtype=torch.float32)
        block_m = 16
        block_n = 32
        block_k = 32
        grid = (triton.cdiv(m, block_m), triton.cdiv(n, block_n))
        matmul_kernel[grid](a, b, c, m, n, k, BLOCK_M=block_m, BLOCK_N=block_n, BLOCK_K=block_k)
        return c

    def timed(fn, warmup: int, iters: int) -> float:
        for _ in range(warmup):
            y = fn()
        torch.cuda.synchronize(0)
        start = time.perf_counter()
        for _ in range(iters):
            y = fn()
        torch.cuda.synchronize(0)
        return (time.perf_counter() - start) / max(iters, 1)

    torch.backends.cuda.matmul.allow_tf32 = True
    device = torch.device("cuda:0")
    model = raw["model"]
    seq = int(model["sequence_length"])
    hidden = int(model["n_embd"])
    mlp = int(model.get("mlp_ratio", 4)) * hidden
    shapes = [
        ("qkv_like", seq, 3 * hidden, hidden),
        ("proj_like", seq, hidden, hidden),
        ("mlp_up_like", seq, mlp, hidden),
        ("mlp_down_like", seq, hidden, mlp),
    ]
    results = []
    for name, m, n, k in shapes:
        a = torch.randn((m, k), device=device, dtype=torch.bfloat16)
        b = torch.randn((k, n), device=device, dtype=torch.bfloat16)
        torch_out = torch.matmul(a, b)
        triton_out = triton_matmul(a, b)
        torch.cuda.synchronize(0)
        diff = (torch_out.float() - triton_out.float()).abs()
        max_abs_error = float(diff.max().detach().cpu())
        max_ref_abs = float(torch_out.float().abs().max().detach().cpu())
        max_relative_error = max_abs_error / max(max_ref_abs, 1.0)
        torch_s = timed(lambda: torch.matmul(a, b), args.warmup, args.iters)
        triton_s = timed(lambda: triton_matmul(a, b), args.warmup, args.iters)
        flops = 2.0 * m * n * k
        results.append({
            "name": name,
            "m": m,
            "n": n,
            "k": k,
            "dtype": "bfloat16_inputs_float32_accum",
            "flops_per_matmul": flops,
            "torch_seconds": torch_s,
            "triton_seconds": triton_s,
            "torch_tflops": flops / torch_s / 1e12 if torch_s > 0 else None,
            "triton_tflops": flops / triton_s / 1e12 if triton_s > 0 else None,
            "triton_vs_torch_speed_ratio": torch_s / triton_s if triton_s > 0 else None,
            "max_abs_error": max_abs_error,
            "max_reference_abs": max_ref_abs,
            "max_relative_error": max_relative_error,
        })
    return {
        "verdict": "NATIVE_KERNEL_PROBE_NOT_COMPLETION",
        "cuda_available": True,
        "torch_version": torch.__version__,
        "cuda_version": torch.version.cuda,
        "device_name": torch.cuda.get_device_name(0),
        "device_total_memory_bytes": torch.cuda.get_device_properties(0).total_memory,
        "toolchain": {
            "triton_available": True,
            "triton_version": getattr(triton, "__version__", None),
            "nvcc_available": shutil.which("nvcc") is not None,
            "nvcc_path": shutil.which("nvcc"),
            "cl_available": shutil.which("cl") is not None,
            "cl_path": shutil.which("cl"),
            "cmake_path": shutil.which("cmake"),
        },
        "benchmarks": results,
        "benchmark_limits": {
            "kernel_family": "bf16 GEMM only",
            "not_measured": ["attention backward", "optimizer fusion", "loss fusion", "full CUDA C++ extension path", "long-run thermal/power stability"],
        },
        "completion_limit": "Native kernel probe measures bounded Triton GEMM shapes and records CUDA C++ toolchain availability. It is not family completion, not full forward/backward/optimizer training throughput, and not proof that native optimization is exhausted.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--capability-target", required=True)
    parser.add_argument("--warmup", type=int, default=5)
    parser.add_argument("--iters", type=int, default=20)
    args = parser.parse_args()
    raw = load_json(args.config)
    params = analytical_parameter_count(raw["model"])
    receipt: dict[str, Any] = {
        "created_at_utc": now_utc(),
        "kind": "single_4090_native_kernel_probe",
        "config_path": str(args.config),
        "config_id": raw.get("config_id"),
        "lane": raw.get("lane"),
        "capability_target": args.capability_target,
        "active_trainable_parameters": params,
        "platform": {"system": platform.system(), "release": platform.release(), "machine": platform.machine(), "python": platform.python_version()},
    }
    try:
        receipt.update(run_probe(args, raw, params))
    except Exception as exc:
        import traceback
        receipt["verdict"] = "INVALID_RUN_EXCEPTION"
        receipt["error"] = {"type": type(exc).__name__, "message": str(exc), "traceback": traceback.format_exc()}
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0 if receipt.get("verdict") == "NATIVE_KERNEL_PROBE_NOT_COMPLETION" else 1


if __name__ == "__main__":
    raise SystemExit(main())
