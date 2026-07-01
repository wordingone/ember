#!/usr/bin/env python3
"""Bound native/fused training-stack surfaces for the single-4090 >=1B baseline.

This probe measures selected native PyTorch/CUDA training primitives at C1-like
shapes: SDPA attention forward/backward, CUDA cross-entropy, and fused AdamW API
availability. It is not a full fused transformer implementation and not proof
that native optimization is exhausted.
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


def timed_cuda(fn, warmup: int, iters: int) -> float:
    import torch

    for _ in range(warmup):
        fn()
    torch.cuda.synchronize(0)
    start = time.perf_counter()
    for _ in range(iters):
        fn()
    torch.cuda.synchronize(0)
    return (time.perf_counter() - start) / max(iters, 1)


def run_probe(args: argparse.Namespace, raw: dict[str, Any], params: int) -> dict[str, Any]:
    import torch
    import torch.nn.functional as F

    if not torch.cuda.is_available():
        return {"verdict": "INVALID_RUN_CUDA_UNAVAILABLE", "cuda_available": False, "torch_version": torch.__version__}

    torch.manual_seed(args.seed)
    torch.backends.cuda.matmul.allow_tf32 = True
    device = torch.device("cuda:0")
    model = raw["model"]
    seq = int(model["sequence_length"])
    hidden = int(model["n_embd"])
    heads = int(model.get("n_heads", model.get("n_head")))
    head_dim = hidden // heads
    vocab = int(model["vocab_size"])

    q = torch.randn((1, heads, seq, head_dim), device=device, dtype=torch.bfloat16, requires_grad=True)
    k = torch.randn((1, heads, seq, head_dim), device=device, dtype=torch.bfloat16, requires_grad=True)
    v = torch.randn((1, heads, seq, head_dim), device=device, dtype=torch.bfloat16, requires_grad=True)
    def attention_step() -> None:
        for tensor in (q, k, v):
            tensor.grad = None
        y = F.scaled_dot_product_attention(q, k, v, is_causal=True)
        y.float().square().mean().backward()

    attention_s = timed_cuda(attention_step, args.warmup, args.iters)
    attention_flops_lower = 4.0 * heads * seq * seq * head_dim

    tokens = min(seq, args.loss_tokens)
    logits = torch.randn((tokens, vocab), device=device, dtype=torch.bfloat16, requires_grad=True)
    targets = torch.randint(0, vocab, (tokens,), device=device, dtype=torch.long)
    def loss_step() -> None:
        logits.grad = None
        loss = F.cross_entropy(logits.float(), targets)
        loss.backward()

    loss_s = timed_cuda(loss_step, args.warmup, args.iters)

    optimizer_elements = int(args.optimizer_elements)
    p = torch.nn.Parameter(torch.randn((optimizer_elements,), device=device, dtype=torch.bfloat16))
    fused_adamw_supported = True
    fused_error = None
    try:
        opt = torch.optim.AdamW([p], lr=1e-4, fused=True)
    except Exception as exc:
        fused_adamw_supported = False
        fused_error = {"type": type(exc).__name__, "message": str(exc)}
        opt = torch.optim.AdamW([p], lr=1e-4, foreach=True)

    def optimizer_step() -> None:
        opt.zero_grad(set_to_none=True)
        p.grad = torch.randn_like(p)
        opt.step()

    optimizer_s = timed_cuda(optimizer_step, args.warmup, args.iters)

    return {
        "verdict": "NATIVE_TRAINING_STACK_PROBE_NOT_COMPLETION",
        "cuda_available": True,
        "torch_version": torch.__version__,
        "cuda_version": torch.version.cuda,
        "device_name": torch.cuda.get_device_name(0),
        "device_total_memory_bytes": torch.cuda.get_device_properties(0).total_memory,
        "toolchain": {
            "triton_available": shutil.which("triton") is not None,
            "nvcc_available": shutil.which("nvcc") is not None,
            "nvcc_path_recorded": shutil.which("nvcc") is not None,
            "cmake_available": shutil.which("cmake") is not None,
        },
        "native_training_surfaces": {
            "sdpa_attention_forward_backward": {
                "bounded": True,
                "shape": {"batch": 1, "heads": heads, "seq_len": seq, "head_dim": head_dim, "dtype": "bfloat16"},
                "uses_torch_scaled_dot_product_attention": True,
                "flash_sdp_enabled": bool(torch.backends.cuda.flash_sdp_enabled()),
                "math_sdp_enabled": bool(torch.backends.cuda.math_sdp_enabled()),
                "mem_efficient_sdp_enabled": bool(torch.backends.cuda.mem_efficient_sdp_enabled()),
                "mean_forward_backward_seconds": attention_s,
                "lower_bound_attention_tflops": attention_flops_lower / attention_s / 1e12 if attention_s > 0 else None,
            },
            "cross_entropy_forward_backward": {
                "bounded": True,
                "shape": {"tokens": tokens, "vocab_size": vocab, "logit_dtype": "bfloat16", "loss_dtype": "float32"},
                "uses_torch_cuda_cross_entropy_path": True,
                "mean_forward_backward_seconds": loss_s,
            },
            "adamw_optimizer_step": {
                "bounded": True,
                "optimizer_elements": optimizer_elements,
                "parameter_dtype": "bfloat16",
                "fused_adamw_requested": True,
                "fused_adamw_supported": fused_adamw_supported,
                "fallback_if_any": fused_error,
                "mean_step_seconds": optimizer_s,
            },
        },
        "open_native_surfaces": [
            "full CUDA C++ transformer block forward/backward implementation",
            "Triton fused attention backward replacement at full C1 stack",
            "fused bias/dropout/residual/layernorm training kernel stack",
            "full 19-layer native forward/backward/optimizer long-run receipt",
            "thermal/power stability over long-run native training",
        ],
        "completion_limit": "Native training-stack probe bounds selected PyTorch/CUDA fused surfaces only: SDPA attention forward/backward, CUDA cross-entropy, and fused AdamW API behavior. It is not a full native transformer implementation, not a full 1B long-run training receipt, not proof that native optimization is exhausted, and not family completion.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--capability-target", required=True)
    parser.add_argument("--warmup", type=int, default=2)
    parser.add_argument("--iters", type=int, default=5)
    parser.add_argument("--loss-tokens", type=int, default=1024)
    parser.add_argument("--optimizer-elements", type=int, default=8388608)
    parser.add_argument("--seed", type=int, default=1337)
    args = parser.parse_args()
    raw = load_json(args.config)
    params = analytical_parameter_count(raw["model"])
    receipt: dict[str, Any] = {
        "created_at_utc": now_utc(),
        "kind": "single_4090_native_training_stack_probe",
        "config_repo_path": "engineering/4090-1b/configs/" + args.config.name,
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
    return 0 if receipt.get("verdict") == "NATIVE_TRAINING_STACK_PROBE_NOT_COMPLETION" else 1


if __name__ == "__main__":
    raise SystemExit(main())
