#!/usr/bin/env python3
"""Validate bounded C1 native/fused training-stack probe evidence."""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RECEIPT = "receipts/4090-native-training-stack-probe-pretraining-equivalent.json"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def positive(value: Any) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(float(value)) and float(value) > 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    receipt = read_json(root / RECEIPT) if (root / RECEIPT).exists() else {}
    failures: list[dict[str, Any]] = []

    if receipt.get("verdict") != "NATIVE_TRAINING_STACK_PROBE_NOT_COMPLETION":
        failures.append({"code": "native_training_stack_bad_verdict", "actual": receipt.get("verdict")})
    if receipt.get("active_trainable_parameters", 0) < 1_000_000_000:
        failures.append({"code": "below_1b_active_trainable_parameters", "actual": receipt.get("active_trainable_parameters")})
    if receipt.get("cuda_available") is not True:
        failures.append({"code": "cuda_not_available"})
    if receipt.get("device_name") != "NVIDIA GeForce RTX 4090":
        failures.append({"code": "unexpected_device", "actual": receipt.get("device_name")})
    surfaces = receipt.get("native_training_surfaces", {})
    attention = surfaces.get("sdpa_attention_forward_backward", {})
    if attention.get("bounded") is not True or attention.get("uses_torch_scaled_dot_product_attention") is not True:
        failures.append({"code": "attention_surface_not_bounded", "attention": attention})
    shape = attention.get("shape", {})
    if shape.get("heads") != 16 or shape.get("seq_len") != 2048 or shape.get("head_dim") != 128:
        failures.append({"code": "attention_shape_not_c1", "shape": shape})
    if not positive(attention.get("mean_forward_backward_seconds")) or not positive(attention.get("lower_bound_attention_tflops")):
        failures.append({"code": "attention_timing_invalid", "attention": attention})
    loss = surfaces.get("cross_entropy_forward_backward", {})
    if loss.get("bounded") is not True or loss.get("uses_torch_cuda_cross_entropy_path") is not True:
        failures.append({"code": "loss_surface_not_bounded", "loss": loss})
    if loss.get("shape", {}).get("vocab_size") != 32768 or not positive(loss.get("mean_forward_backward_seconds")):
        failures.append({"code": "loss_surface_shape_or_timing_invalid", "loss": loss})
    opt = surfaces.get("adamw_optimizer_step", {})
    if opt.get("bounded") is not True or opt.get("fused_adamw_requested") is not True or opt.get("optimizer_elements", 0) < 1_000_000:
        failures.append({"code": "optimizer_surface_not_bounded", "optimizer": opt})
    if not positive(opt.get("mean_step_seconds")):
        failures.append({"code": "optimizer_timing_invalid", "optimizer": opt})
    open_surfaces = receipt.get("open_native_surfaces", [])
    required_open = {
        "full CUDA C++ transformer block forward/backward implementation",
        "full 19-layer native forward/backward/optimizer long-run receipt",
    }
    if not required_open.issubset(set(open_surfaces)):
        failures.append({"code": "open_native_surfaces_not_preserved", "open": open_surfaces})
    guard = str(receipt.get("completion_limit", ""))
    for term in ("not a full native transformer implementation", "not a full 1B long-run training receipt", "not proof that native optimization is exhausted", "not family completion"):
        if term not in guard:
            failures.append({"code": "completion_limit_missing_guard", "term": term})

    result = {
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "verdict": "C1_NATIVE_TRAINING_STACK_PROBE_VALIDATED" if not failures else "C1_NATIVE_TRAINING_STACK_PROBE_INVALID",
        "failure_count": len(failures),
        "failures": failures,
        "receipt_path": RECEIPT,
        "bounded_surfaces": sorted(surfaces.keys()),
        "open_native_surface_count": len(open_surfaces) if isinstance(open_surfaces, list) else None,
        "completion_limit": "This validates bounded native/fused training-stack telemetry only. It is not a full native transformer implementation, not a long-run 1B training receipt, and not overall baseline completion.",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
