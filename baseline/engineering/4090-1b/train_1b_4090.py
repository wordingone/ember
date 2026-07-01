#!/usr/bin/env python3
"""Engineering baseline harness for single-RTX-4090 >=1B training claims.

The default dry run builds the exact configured model on CPU/meta-safe paths,
counts active trainable parameters, emits memory/FLOP requirements, and writes a
receipt. Non-dry-run execution requires explicit data and target receipts.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class ModelConfig:
    vocab_size: int
    sequence_length: int
    n_layers: int
    n_embd: int
    n_heads: int
    mlp_ratio: int
    tie_embeddings: bool
    dropout: float
    bias: bool


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_config(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def model_config(raw: dict[str, Any]) -> ModelConfig:
    m = raw["model"]
    return ModelConfig(
        vocab_size=int(m["vocab_size"]),
        sequence_length=int(m["sequence_length"]),
        n_layers=int(m["n_layers"]),
        n_embd=int(m["n_embd"]),
        n_heads=int(m["n_heads"]),
        mlp_ratio=int(m["mlp_ratio"]),
        tie_embeddings=bool(m.get("tie_embeddings", True)),
        dropout=float(m.get("dropout", 0.0)),
        bias=bool(m.get("bias", False)),
    )


def analytical_parameter_count(cfg: ModelConfig) -> dict[str, int]:
    d = cfg.n_embd
    mlp = cfg.mlp_ratio * d
    bias = 1 if cfg.bias else 0
    token_embedding = cfg.vocab_size * d
    position_embedding = cfg.sequence_length * d
    attention = cfg.n_layers * ((3 * d * d + 3 * d * bias) + (d * d + d * bias))
    mlp_params = cfg.n_layers * ((d * mlp + mlp * bias) + (mlp * d + d * bias))
    norms = cfg.n_layers * 4 * d + 2 * d
    lm_head = 0 if cfg.tie_embeddings else cfg.vocab_size * d
    total = token_embedding + position_embedding + attention + mlp_params + norms + lm_head
    return {
        "token_embedding": token_embedding,
        "position_embedding": position_embedding,
        "attention": attention,
        "mlp": mlp_params,
        "norms": norms,
        "lm_head": lm_head,
        "active_trainable_parameters": total,
    }


def memory_plan(params: int, cfg: ModelConfig, raw: dict[str, Any]) -> dict[str, Any]:
    gb = 1024**3
    weights = params * 2 / gb
    gradients = params * 2 / gb
    adamw_fp32 = params * 12 / gb
    adamw_8bit_est = params * 5.5 / gb
    activation_checkpointed_est = cfg.n_layers * cfg.sequence_length * cfg.n_embd * 2 * 4 / gb
    temp_margin = 2.0
    estimated_8bit_total = weights + gradients + adamw_8bit_est + activation_checkpointed_est + temp_margin
    return {
        "weights_bf16_gb": weights,
        "gradients_bf16_gb": gradients,
        "adamw_fp32_master_gb": adamw_fp32,
        "adamw_8bit_master_estimate_gb": adamw_8bit_est,
        "activation_checkpointed_estimate_gb": activation_checkpointed_est,
        "temporary_and_fragmentation_margin_gb": temp_margin,
        "estimated_8bit_optimizer_total_gb": estimated_8bit_total,
        "fits_24gb_estimate": estimated_8bit_total < 24.0,
        "required_controls": [
            "activation_checkpointing",
            "micro_batch_size=1 until measured otherwise",
            "8-bit optimizer or equivalently measured state compression/offload",
            "bf16/fp16 weights and gradients",
            "representative long-run memory receipt before PASS"
        ],
    }


def flop_plan(params: int, token_budget: int, days_threshold: float) -> dict[str, Any]:
    flops = 6.0 * params * token_budget
    required_tflops = flops / (days_threshold * 86400.0) / 1e12
    return {
        "formula": "training_flops = 6 * active_trainable_parameters * trained_tokens",
        "token_budget": token_budget,
        "days_threshold": days_threshold,
        "training_flops": flops,
        "required_sustained_tflops": required_tflops,
    }


def maybe_torch_probe() -> dict[str, Any]:
    try:
        import torch
    except Exception as exc:
        return {"torch_available": False, "error": str(exc)}
    probe: dict[str, Any] = {
        "torch_available": True,
        "torch_version": torch.__version__,
        "cuda_available": torch.cuda.is_available(),
        "cuda_version": torch.version.cuda,
    }
    if torch.cuda.is_available():
        probe["device_name"] = torch.cuda.get_device_name(0)
        probe["device_total_memory_bytes"] = torch.cuda.get_device_properties(0).total_memory
    return probe


def validate_preconditions(raw: dict[str, Any], args: argparse.Namespace) -> list[str]:
    failures: list[str] = []
    if not args.dry_run:
        if not args.data:
            failures.append("--data is required for non-dry-run execution")
        if not args.capability_target:
            failures.append("--capability-target is required for non-dry-run execution")
        if not args.output_dir:
            failures.append("--output-dir is required for non-dry-run execution")
    if raw["training"].get("token_budget", 0) <= 0:
        failures.append("config training.token_budget must be positive")
    return failures


def build_receipt(raw: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    cfg = model_config(raw)
    counts = analytical_parameter_count(cfg)
    params = counts["active_trainable_parameters"]
    token_budget = int(raw["training"]["token_budget"])
    days_threshold = float(raw["training"].get("days_scale_threshold", 14))
    min_params = int(raw["model"].get("expected_active_trainable_parameters_min", 1_000_000_000))
    precondition_failures = validate_preconditions(raw, args)
    if params < min_params:
        precondition_failures.append(f"active_trainable_parameters {params} below required minimum {min_params}")
    receipt = {
        "created_at_utc": now_utc(),
        "verdict": "DRY_RUN_ENGINEERING_BASELINE_READY" if args.dry_run and not precondition_failures else "INVALID_RUN",
        "completion_limit": "This receipt proves the engineered baseline surface is runnable/configured; it is not a completed training run and not an Ember win.",
        "config_path": str(args.config),
        "config_id": raw.get("config_id"),
        "lane": raw.get("lane"),
        "dry_run": args.dry_run,
        "platform": {"system": platform.system(), "release": platform.release(), "machine": platform.machine(), "python": platform.python_version()},
        "torch_probe": maybe_torch_probe(),
        "parameter_count": counts,
        "active_trainable_parameters": params,
        "parameter_floor": min_params,
        "token_budget": token_budget,
        "capability_target": args.capability_target or raw.get("capability_target"),
        "memory_plan": memory_plan(params, cfg, raw),
        "throughput": flop_plan(params, token_budget, days_threshold),
        "stop_rule": raw.get("stop_rule"),
        "precondition_failures": precondition_failures,
    }
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true", help="Validate and emit the engineering receipt without training.")
    parser.add_argument("--data", type=Path, help="Memmap/streaming token source for non-dry-run execution.")
    parser.add_argument("--output-dir", type=Path, help="Checkpoint/output directory for non-dry-run execution.")
    parser.add_argument("--capability-target", type=str, help="Frozen target identifier for non-dry-run execution.")
    args = parser.parse_args()

    raw = load_config(args.config)
    receipt = build_receipt(raw, args)
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0 if receipt["verdict"] == "DRY_RUN_ENGINEERING_BASELINE_READY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
