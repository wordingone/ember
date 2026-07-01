#!/usr/bin/env python3
"""Bounded governed probe for the single-4090 >=1B engineering baseline.

This probe does not claim to train the 1B model. It uses the locked 1B config for
parameter/FLOP/memory accounting, then runs a bounded transformer step on the
same local GPU to produce measured telemetry under explicit stop rules.
"""

from __future__ import annotations

import argparse
import json
import math
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
        return {"verdict": "INVALID_RUN_CUDA_UNAVAILABLE", "torch_version": torch.__version__, "cuda_available": False}

    torch.backends.cuda.matmul.allow_tf32 = True
    torch.backends.cudnn.allow_tf32 = True
    device = "cuda"
    dtype = torch.bfloat16 if args.dtype == "bfloat16" and torch.cuda.is_bf16_supported() else torch.float16
    hidden = args.probe_hidden
    heads = args.probe_heads
    layers = args.probe_layers
    seq = args.probe_seq_len
    batch = args.probe_batch_size
    vocab = args.probe_vocab_size

    class Block(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.ln1 = nn.LayerNorm(hidden)
            self.attn = nn.MultiheadAttention(hidden, heads, batch_first=True)
            self.ln2 = nn.LayerNorm(hidden)
            self.mlp = nn.Sequential(nn.Linear(hidden, 4 * hidden), nn.GELU(), nn.Linear(4 * hidden, hidden))

        def forward(self, x):
            y = self.ln1(x)
            y, _ = self.attn(y, y, y, need_weights=False)
            x = x + y
            return x + self.mlp(self.ln2(x))

    class ProbeLM(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.emb = nn.Embedding(vocab, hidden)
            self.blocks = nn.ModuleList([Block() for _ in range(layers)])
            self.ln = nn.LayerNorm(hidden)
            self.head = nn.Linear(hidden, vocab, bias=False)

        def forward(self, idx):
            x = self.emb(idx)
            for block in self.blocks:
                x = block(x)
            return self.head(self.ln(x))

    torch.cuda.reset_peak_memory_stats()
    model = ProbeLM().to(device=device, dtype=dtype)
    opt = torch.optim.AdamW(model.parameters(), lr=1e-4)
    idx = torch.randint(0, vocab, (batch, seq), device=device)
    target = torch.randint(0, vocab, (batch, seq), device=device)
    probe_params = sum(p.numel() for p in model.parameters())
    tokens_per_iter = batch * seq

    stop_after_s = args.max_seconds
    started = time.perf_counter()
    losses = []
    completed = 0
    for step in range(args.steps):
        if time.perf_counter() - started > stop_after_s:
            break
        opt.zero_grad(set_to_none=True)
        logits = model(idx)
        loss = F.cross_entropy(logits.float().view(-1, vocab), target.view(-1))
        loss.backward()
        opt.step()
        torch.cuda.synchronize()
        losses.append(float(loss.detach().cpu()))
        completed += 1
    elapsed = time.perf_counter() - started
    estimated_flops = 6.0 * probe_params * tokens_per_iter * max(completed, 1)
    full_token_budget = int(raw["training"]["token_budget"])
    full_required_tflops = 6.0 * counts["active_trainable_parameters"] * full_token_budget / (float(raw["training"].get("days_scale_threshold", 14)) * 86400.0) / 1e12
    return {
        "verdict": "GOVERNED_PROBE_NOT_COMPLETION",
        "torch_version": torch.__version__,
        "cuda_available": True,
        "cuda_version": torch.version.cuda,
        "device_name": torch.cuda.get_device_name(0),
        "device_total_memory_bytes": torch.cuda.get_device_properties(0).total_memory,
        "dtype": str(dtype).replace("torch.", ""),
        "probe_shape": {
            "batch_size": batch,
            "seq_len": seq,
            "hidden": hidden,
            "heads": heads,
            "layers": layers,
            "vocab_size": vocab,
            "parameters": probe_params,
        },
        "steps_requested": args.steps,
        "steps_completed": completed,
        "elapsed_s": elapsed,
        "tokens_per_second": tokens_per_iter * completed / elapsed if elapsed > 0 else None,
        "estimated_probe_training_tflops": estimated_flops / elapsed / 1e12 if elapsed > 0 else None,
        "peak_memory_bytes": torch.cuda.max_memory_allocated(),
        "loss_first": losses[0] if losses else None,
        "loss_last": losses[-1] if losses else None,
        "full_config_required_sustained_tflops": full_required_tflops,
        "completion_limit": "Bounded probe telemetry is non-dry-run GPU evidence, but not representative full 1B long-run throughput and not family completion by itself.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--capability-target", required=True)
    parser.add_argument("--max-seconds", type=float, default=120.0)
    parser.add_argument("--steps", type=int, default=3)
    parser.add_argument("--dtype", choices=["float16", "bfloat16"], default="bfloat16")
    parser.add_argument("--probe-batch-size", type=int, default=1)
    parser.add_argument("--probe-seq-len", type=int, default=256)
    parser.add_argument("--probe-hidden", type=int, default=512)
    parser.add_argument("--probe-heads", type=int, default=8)
    parser.add_argument("--probe-layers", type=int, default=4)
    parser.add_argument("--probe-vocab-size", type=int, default=8192)
    args = parser.parse_args()

    raw = load_json(args.config)
    counts = analytical_parameter_count(raw["model"])
    receipt: dict[str, Any] = {
        "created_at_utc": now_utc(),
        "kind": "single_4090_governed_probe",
        "config_path": str(args.config),
        "config_id": raw.get("config_id"),
        "lane": raw.get("lane"),
        "capability_target": args.capability_target,
        "full_config_parameter_count": counts,
        "active_trainable_parameters": counts["active_trainable_parameters"],
        "token_budget": raw["training"]["token_budget"],
        "stop_rule": {"max_seconds": args.max_seconds, "steps": args.steps, "no_completion_claim": True},
        "platform": {"system": platform.system(), "release": platform.release(), "machine": platform.machine(), "python": platform.python_version()},
    }
    try:
        receipt.update(run_probe(args, raw, counts))
    except Exception as exc:
        receipt["verdict"] = "INVALID_RUN_EXCEPTION"
        receipt["error"] = {"type": type(exc).__name__, "message": str(exc)}

    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0 if receipt.get("verdict") == "GOVERNED_PROBE_NOT_COMPLETION" else 1


if __name__ == "__main__":
    raise SystemExit(main())
