#!/usr/bin/env python3
"""Run a bounded RTX 4090 throughput probe for the Ember baseline ceiling.

This is a short diagnostic, not a governed training run. It measures local CUDA
availability, matmul throughput, and a tiny transformer-like forward/backward
step so the 4090 ceiling has receipt-backed local evidence.
"""

from __future__ import annotations

import argparse
import json
import math
import platform
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path


def nvidia_smi() -> dict:
    try:
        out = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total,power.limit,driver_version",
                "--format=csv,noheader,nounits",
            ],
            text=True,
            timeout=10,
        )
        rows = []
        for line in out.splitlines():
            if not line.strip():
                continue
            name, memory, power, driver = [part.strip() for part in line.split(",")]
            rows.append({"name": name, "memory_total_mib": float(memory), "power_limit_w": float(power), "driver_version": driver})
        return {"available": True, "gpus": rows}
    except Exception as exc:  # pragma: no cover - environment dependent
        return {"available": False, "error": str(exc)}


def sync(torch) -> None:
    if torch.cuda.is_available():
        torch.cuda.synchronize()


def bench_matmul(torch, size: int, warmup: int, iters: int, dtype_name: str) -> dict:
    device = "cuda"
    dtype = getattr(torch, dtype_name)
    a = torch.randn((size, size), device=device, dtype=dtype)
    b = torch.randn((size, size), device=device, dtype=dtype)
    for _ in range(warmup):
        _ = a @ b
    sync(torch)
    start = time.perf_counter()
    for _ in range(iters):
        c = a @ b
    sync(torch)
    elapsed = time.perf_counter() - start
    # GEMM FLOPs: 2*n^3 per matmul.
    flops = 2.0 * size * size * size * iters
    return {
        "kind": "square_matmul",
        "dtype": dtype_name,
        "size": size,
        "warmup": warmup,
        "iters": iters,
        "elapsed_s": elapsed,
        "tflops": flops / elapsed / 1e12,
        "memory_allocated_bytes": torch.cuda.max_memory_allocated(),
    }


def bench_transformer_step(torch, args: argparse.Namespace) -> dict:
    import torch.nn as nn
    import torch.nn.functional as F

    torch.cuda.reset_peak_memory_stats()
    device = "cuda"
    dtype = torch.bfloat16 if args.dtype == "bfloat16" else torch.float16
    vocab = args.vocab_size
    batch = args.batch_size
    seq = args.seq_len
    hidden = args.hidden
    heads = args.heads
    layers = args.layers

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
            x = x + self.mlp(self.ln2(x))
            return x

    class TinyLM(nn.Module):
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

    model = TinyLM().to(device=device, dtype=dtype)
    opt = torch.optim.AdamW(model.parameters(), lr=1e-4)
    idx = torch.randint(0, vocab, (batch, seq), device=device)
    target = torch.randint(0, vocab, (batch, seq), device=device)
    param_count = sum(p.numel() for p in model.parameters())
    tokens_per_iter = batch * seq

    for _ in range(args.step_warmup):
        opt.zero_grad(set_to_none=True)
        logits = model(idx)
        loss = F.cross_entropy(logits.float().view(-1, vocab), target.view(-1))
        loss.backward()
        opt.step()
    sync(torch)
    start = time.perf_counter()
    losses = []
    for _ in range(args.step_iters):
        opt.zero_grad(set_to_none=True)
        logits = model(idx)
        loss = F.cross_entropy(logits.float().view(-1, vocab), target.view(-1))
        loss.backward()
        opt.step()
        losses.append(float(loss.detach().cpu()))
    sync(torch)
    elapsed = time.perf_counter() - start
    # Common training estimate, scaled to this tiny model: 6 * params * tokens.
    estimated_flops = 6.0 * param_count * tokens_per_iter * args.step_iters
    return {
        "kind": "tiny_transformer_forward_backward_step",
        "dtype": args.dtype,
        "batch_size": batch,
        "seq_len": seq,
        "hidden": hidden,
        "heads": heads,
        "layers": layers,
        "vocab_size": vocab,
        "parameter_count": param_count,
        "tokens_per_iter": tokens_per_iter,
        "warmup": args.step_warmup,
        "iters": args.step_iters,
        "elapsed_s": elapsed,
        "tokens_per_second": tokens_per_iter * args.step_iters / elapsed,
        "estimated_training_tflops": estimated_flops / elapsed / 1e12,
        "peak_memory_bytes": torch.cuda.max_memory_allocated(),
        "loss_first": losses[0] if losses else None,
        "loss_last": losses[-1] if losses else None,
        "limit": "Tiny model throughput does not transfer directly to 1B training; it is a local CUDA sanity/projection input only.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--matmul-size", type=int, default=4096)
    parser.add_argument("--matmul-iters", type=int, default=20)
    parser.add_argument("--matmul-warmup", type=int, default=5)
    parser.add_argument("--dtype", choices=["float16", "bfloat16"], default="bfloat16")
    parser.add_argument("--batch-size", type=int, default=2)
    parser.add_argument("--seq-len", type=int, default=256)
    parser.add_argument("--hidden", type=int, default=512)
    parser.add_argument("--heads", type=int, default=8)
    parser.add_argument("--layers", type=int, default=4)
    parser.add_argument("--vocab-size", type=int, default=8192)
    parser.add_argument("--step-iters", type=int, default=6)
    parser.add_argument("--step-warmup", type=int, default=2)
    args = parser.parse_args()

    receipt = {
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "verdict": "THROUGHPUT_PROBE_NOT_COMPLETION",
        "platform": {"system": platform.system(), "release": platform.release(), "machine": platform.machine()},
        "nvidia_smi": nvidia_smi(),
        "completion_limits": [
            "This is a short local probe, not a governed >=1B training run.",
            "The result cannot satisfy the single_4090_ge_1b_foundation_ceiling family without exact 1B config, memory fit, sustained long-run throughput, capability target, and comparator receipts.",
        ],
    }
    try:
        import torch
        receipt["torch"] = {"version": torch.__version__, "cuda_available": torch.cuda.is_available(), "cuda_version": torch.version.cuda}
        if not torch.cuda.is_available():
            receipt["verdict"] = "INVALID_RUN_CUDA_UNAVAILABLE"
        else:
            torch.backends.cuda.matmul.allow_tf32 = True
            torch.backends.cudnn.allow_tf32 = True
            receipt["device"] = {
                "name": torch.cuda.get_device_name(0),
                "capability": list(torch.cuda.get_device_capability(0)),
                "total_memory_bytes": torch.cuda.get_device_properties(0).total_memory,
            }
            receipt["matmul"] = bench_matmul(torch, args.matmul_size, args.matmul_warmup, args.matmul_iters, "float16")
            receipt["transformer_step"] = bench_transformer_step(torch, args)
    except Exception as exc:
        receipt["verdict"] = "INVALID_RUN_EXCEPTION"
        receipt["error"] = {"type": type(exc).__name__, "message": str(exc)}

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0 if receipt["verdict"] == "THROUGHPUT_PROBE_NOT_COMPLETION" else 1


if __name__ == "__main__":
    raise SystemExit(main())
