#!/usr/bin/env python3
"""Compute the single-RTX-4090 >=1B training ceiling projection.

This is a deterministic calculator, not a benchmark. It turns the baseline's
FLOP, token-budget, and memory assumptions into a JSON receipt so the ceiling
math can be reviewed and rerun.
"""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_SUSTAINED_TFLOPS = [50, 75, 100, 150, 200, 250]
DEFAULT_TOKEN_BUDGETS_B = [5, 10, 20, 30, 50]


def try_nvidia_smi() -> dict:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return {"available": False, "reason": "nvidia-smi not found on PATH"}
    query = "name,memory.total,power.limit"
    try:
        completed = subprocess.run(
            [exe, f"--query-gpu={query}", "--format=csv,noheader,nounits"],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
        )
    except Exception as exc:  # pragma: no cover - environment dependent
        return {"available": False, "reason": str(exc)}
    rows = []
    for line in completed.stdout.splitlines():
        if not line.strip():
            continue
        parts = [part.strip() for part in line.split(",")]
        rows.append({"name": parts[0], "memory_total_mib": parts[1] if len(parts) > 1 else None, "power_limit_w": parts[2] if len(parts) > 2 else None})
    return {"available": True, "gpus": rows}


def training_flops(params_b: float, tokens_b: float) -> float:
    return 6.0 * params_b * 1e9 * tokens_b * 1e9


def days_for(flops: float, sustained_tflops: float) -> float:
    return flops / (sustained_tflops * 1e12) / 86400.0


def required_tflops(flops: float, target_days: float) -> float:
    return flops / (target_days * 86400.0) / 1e12


def memory_profiles(params_b: float) -> list[dict]:
    gb = params_b
    return [
        {
            "profile": "bf16_weights_bf16_grads_fp32_adamw_fp32_master",
            "weights_gb": 2 * gb,
            "gradients_gb": 2 * gb,
            "optimizer_master_gb": 12 * gb,
            "subtotal_before_activations_gb": 16 * gb,
            "fit_on_24gb_before_activations": 16 * gb < 24,
            "notes": "Mathematically fits before activations for 1B, but leaves too little practical headroom for useful sequence/batch without checkpointing or state reduction.",
        },
        {
            "profile": "bf16_weights_bf16_grads_8bit_optimizer_fp32_master_estimate",
            "weights_gb": 2 * gb,
            "gradients_gb": 2 * gb,
            "optimizer_master_gb_estimate": 5.5 * gb,
            "subtotal_before_activations_gb": 9.5 * gb,
            "fit_on_24gb_before_activations": 9.5 * gb < 24,
            "notes": "Plausible with activation checkpointing, small microbatching, fused kernels, and measured stability/throughput.",
        },
        {
            "profile": "compressed_or_offloaded_optimizer_state",
            "weights_gb": 2 * gb,
            "gradients_gb": 2 * gb,
            "optimizer_master_gb_estimate": "variable",
            "subtotal_before_activations_gb": "4GB + offload/compression state",
            "fit_on_24gb_before_activations": "conditional",
            "notes": "Only valid if offload bandwidth, recompute, and quality cost are included in wall-clock receipts.",
        },
    ]


def build_receipt(args: argparse.Namespace) -> dict:
    table = []
    requirements = []
    for tokens_b in args.token_budgets_b:
        flops = training_flops(args.params_b, tokens_b)
        row = {
            "token_budget_b": tokens_b,
            "training_flops": flops,
            "days_by_sustained_tflops": {str(t): days_for(flops, t) for t in args.sustained_tflops},
        }
        table.append(row)
        requirements.append({"token_budget_b": tokens_b, "required_sustained_tflops_for_target_days": required_tflops(flops, args.target_days)})
    return {
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "verdict": "CALCULATION_RECEIPT_NOT_COMPLETION",
        "params_b": args.params_b,
        "target_days": args.target_days,
        "flop_formula": "training_flops = 6 * active_parameters * trained_tokens",
        "token_budget_days_table": table,
        "required_sustained_tflops": requirements,
        "memory_profiles": memory_profiles(args.params_b),
        "local_hardware_probe": try_nvidia_smi(),
        "platform": {"system": platform.system(), "release": platform.release(), "machine": platform.machine(), "python": platform.python_version()},
        "completion_limits": [
            "This is deterministic math, not a representative local throughput benchmark.",
            "Completion still requires an exact model/config, measured sustained throughput, memory receipt, capability target, comparator table, and dual-repo verifier PASS.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--params-b", type=float, default=1.0)
    parser.add_argument("--target-days", type=float, default=14.0)
    parser.add_argument("--token-budgets-b", type=float, nargs="+", default=DEFAULT_TOKEN_BUDGETS_B)
    parser.add_argument("--sustained-tflops", type=float, nargs="+", default=DEFAULT_SUSTAINED_TFLOPS)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()
    receipt = build_receipt(args)
    text = json.dumps(receipt, indent=2 if args.pretty else None, sort_keys=True)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
