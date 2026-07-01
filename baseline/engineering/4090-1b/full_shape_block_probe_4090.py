#!/usr/bin/env python3
"""Full-shape block throughput probe for the 4090 >=1B baseline.

This probe runs a single decoder block at the locked 1B config shape
(sequence, hidden size, heads, precision path) and measures forward/backward
optimizer-step telemetry. It is closer to the final model shape than the tiny
probe, but still not a full 19-layer 1B training run.
"""

from __future__ import annotations

import argparse
import json
import platform
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def analytical_parameter_count(model: dict[str, Any]) -> dict[str, int]:
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
    total = token_embedding + position_embedding + attention + mlp_params + norms + lm_head
    return {
        "active_trainable_parameters": total,
        "token_embedding": token_embedding,
        "position_embedding": position_embedding,
        "attention": attention,
        "mlp": mlp_params,
        "norms": norms,
        "lm_head": lm_head,
    }


def run_probe(args: argparse.Namespace, raw: dict[str, Any], counts: dict[str, int]) -> dict[str, Any]:
    import torch
    import torch.nn as nn
    import torch.nn.functional as F

    if not torch.cuda.is_available():
        return {"verdict": "INVALID_RUN_CUDA_UNAVAILABLE", "cuda_available": False, "torch_version": torch.__version__}

    torch.backends.cuda.matmul.allow_tf32 = True
    torch.backends.cudnn.allow_tf32 = True
    device = torch.device("cuda:0")
    model = raw["model"]
    batch = int(args.batch_size)
    seq = int(args.seq_len or model["sequence_length"])
    hidden = int(model["n_embd"])
    heads = int(model["n_heads"])
    head_dim = hidden // heads
    mlp_hidden = int(model.get("mlp_ratio", 4)) * hidden
    dtype = torch.bfloat16 if args.dtype == "bfloat16" and torch.cuda.is_bf16_supported() else torch.float16

    class FullShapeBlock(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.ln1 = nn.LayerNorm(hidden)
            self.qkv = nn.Linear(hidden, 3 * hidden, bias=False)
            self.proj = nn.Linear(hidden, hidden, bias=False)
            self.ln2 = nn.LayerNorm(hidden)
            self.fc1 = nn.Linear(hidden, mlp_hidden, bias=False)
            self.fc2 = nn.Linear(mlp_hidden, hidden, bias=False)

        def forward(self, x):
            y = self.ln1(x)
            qkv = self.qkv(y).view(batch, seq, 3, heads, head_dim).permute(2, 0, 3, 1, 4)
            q, k, v = qkv[0], qkv[1], qkv[2]
            y = F.scaled_dot_product_attention(q, k, v, is_causal=True, dropout_p=0.0)
            y = y.transpose(1, 2).contiguous().view(batch, seq, hidden)
            x = x + self.proj(y)
            y = self.fc2(F.gelu(self.fc1(self.ln2(x))))
            return x + y

    torch.cuda.empty_cache()
    try:
        torch.cuda.reset_peak_memory_stats(0)
    except Exception:
        pass
    block = FullShapeBlock().to(device=device, dtype=dtype)
    opt = torch.optim.AdamW(block.parameters(), lr=1e-4)
    x = torch.randn((batch, seq, hidden), device=device, dtype=dtype)
    target = torch.randn((batch, seq, hidden), device=device, dtype=dtype)
    block_params = sum(p.numel() for p in block.parameters())
    tokens_per_step = batch * seq

    losses = []
    completed = 0
    start = time.perf_counter()
    for _ in range(args.steps):
        opt.zero_grad(set_to_none=True)
        out = block(x)
        loss = (out.float() - target.float()).square().mean()
        loss.backward()
        opt.step()
        torch.cuda.synchronize(0)
        losses.append(float(loss.detach().cpu()))
        completed += 1
        if time.perf_counter() - start > args.max_seconds:
            break
    elapsed = time.perf_counter() - start
    # Lower-bound block FLOPs using the same 6*N*tokens training approximation.
    block_flops = 6.0 * block_params * tokens_per_step * max(completed, 1)
    estimated_block_tflops = block_flops / elapsed / 1e12 if elapsed > 0 else None
    layers = int(model["n_layers"])
    token_budget = int(raw["training"]["token_budget"])
    days_threshold = float(raw["training"].get("days_scale_threshold", 14))
    required_full_tflops = 6.0 * counts["active_trainable_parameters"] * token_budget / (days_threshold * 86400.0) / 1e12
    return {
        "verdict": "FULL_SHAPE_BLOCK_PROBE_NOT_COMPLETION",
        "cuda_available": True,
        "torch_version": torch.__version__,
        "cuda_version": torch.version.cuda,
        "device_name": torch.cuda.get_device_name(0),
        "device_total_memory_bytes": torch.cuda.get_device_properties(0).total_memory,
        "dtype": str(dtype).replace("torch.", ""),
        "uses_scaled_dot_product_attention": True,
        "probe_shape": {
            "batch_size": batch,
            "seq_len": seq,
            "hidden": hidden,
            "heads": heads,
            "head_dim": head_dim,
            "mlp_hidden": mlp_hidden,
            "block_parameters": block_params,
            "model_layers": layers,
            "full_model_active_trainable_parameters": counts["active_trainable_parameters"],
        },
        "steps_requested": args.steps,
        "steps_completed": completed,
        "elapsed_s": elapsed,
        "tokens_per_second": tokens_per_step * completed / elapsed if elapsed > 0 else None,
        "estimated_block_training_tflops_lower_bound": estimated_block_tflops,
        "full_config_required_sustained_tflops": required_full_tflops,
        "peak_memory_bytes": torch.cuda.max_memory_allocated(0),
        "peak_reserved_bytes": torch.cuda.max_memory_reserved(0),
        "loss_first": losses[0] if losses else None,
        "loss_last": losses[-1] if losses else None,
        "completion_limit": "Full-shape block probe measures one representative block at locked 1B shape. It is not full 19-layer 1B long-run throughput and not family completion by itself.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--capability-target", required=True)
    parser.add_argument("--steps", type=int, default=2)
    parser.add_argument("--max-seconds", type=float, default=240.0)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--seq-len", type=int)
    parser.add_argument("--dtype", choices=["bfloat16", "float16"], default="bfloat16")
    args = parser.parse_args()

    raw = load_json(args.config)
    counts = analytical_parameter_count(raw["model"])
    receipt: dict[str, Any] = {
        "created_at_utc": now_utc(),
        "kind": "single_4090_full_shape_block_probe",
        "config_path": str(args.config),
        "config_id": raw.get("config_id"),
        "lane": raw.get("lane"),
        "capability_target": args.capability_target,
        "active_trainable_parameters": counts["active_trainable_parameters"],
        "parameter_count": counts,
        "stop_rule": {"max_seconds": args.max_seconds, "steps": args.steps, "no_completion_claim": True},
        "platform": {"system": platform.system(), "release": platform.release(), "machine": platform.machine(), "python": platform.python_version()},
    }
    try:
        receipt.update(run_probe(args, raw, counts))
    except Exception as exc:
        import traceback
        receipt["verdict"] = "INVALID_RUN_EXCEPTION"
        receipt["error"] = {"type": type(exc).__name__, "message": str(exc), "traceback": traceback.format_exc()}
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0 if receipt.get("verdict") == "FULL_SHAPE_BLOCK_PROBE_NOT_COMPLETION" else 1


if __name__ == "__main__":
    raise SystemExit(main())
