#!/usr/bin/env python3
"""Full-config CUDA memory allocation probe for the 4090 >=1B baseline.

This is not a training run. It allocates the planned memory classes for the
locked >=1B config on the local GPU: bf16 weights, bf16 gradients, 8-bit
optimizer-state estimate, activation-checkpoint estimate, and temporary margin.
The receipt is a feasibility measurement for the memory plan used by C1.
"""

from __future__ import annotations

import argparse
import gc
import json
import platform
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


GB = 1024**3


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


def bytes_plan(raw: dict[str, Any], params: int) -> list[dict[str, Any]]:
    model = raw["model"]
    layers = int(model["n_layers"])
    seq = int(model["sequence_length"])
    hidden = int(model["n_embd"])
    return [
        {"name": "bf16_weights", "bytes": params * 2, "reason": "2 bytes per active trainable parameter"},
        {"name": "bf16_gradients", "bytes": params * 2, "reason": "2 bytes per active trainable parameter"},
        {"name": "optimizer_state_8bit_estimate", "bytes": int(params * 5.5), "reason": "8-bit optimizer plus master/state estimate used by C1 memory plan"},
        {"name": "activation_checkpoint_estimate", "bytes": layers * seq * hidden * 2 * 4, "reason": "checkpointed activation estimate from C1 plan"},
        {"name": "temporary_fragmentation_margin", "bytes": 2 * GB, "reason": "temporary buffers and fragmentation margin"},
    ]


def allocate_chunks(torch, device, total_bytes: int, chunk_bytes: int = 1 * 1024 * 1024):
    chunks = []
    remaining = int(total_bytes)
    index = 0
    while remaining > 0:
        size = min(remaining, chunk_bytes)
        try:
            tensor = torch.empty((size,), dtype=torch.uint8, device=device)
            if tensor.numel() > 0:
                tensor[0] = 1
                tensor[-1] = 1
        except Exception as exc:
            raise RuntimeError(f"allocation chunk failed index={index} size={size} remaining={remaining}: {type(exc).__name__}: {exc}") from exc
        chunks.append(tensor)
        remaining -= size
        index += 1
    return chunks


def allocate_probe(args: argparse.Namespace, raw: dict[str, Any], counts: dict[str, int]) -> dict[str, Any]:
    import torch

    if not torch.cuda.is_available():
        return {"verdict": "INVALID_RUN_CUDA_UNAVAILABLE", "cuda_available": False, "torch_version": torch.__version__}

    device = torch.device("cuda:0")
    device_index = 0
    torch.cuda.empty_cache()
    warnings = []
    try:
        torch.cuda.reset_peak_memory_stats(device_index)
    except Exception as exc:
        warnings.append({"stage": "reset_peak_memory_stats", "type": type(exc).__name__, "message": str(exc)})
    plan = bytes_plan(raw, counts["active_trainable_parameters"])
    allocations = []
    allocated_segments = []
    verdict = "FULL_CONFIG_MEMORY_PROBE_NOT_COMPLETION"
    failure = None
    try:
        for segment in plan:
            tensors = allocate_chunks(torch, device, int(segment["bytes"]))
            allocated_segments.extend(tensors)
            torch.cuda.synchronize(device_index)
            allocations.append({
                "name": segment["name"],
                "planned_bytes": segment["bytes"],
                "allocated_bytes_after_segment": torch.cuda.memory_allocated(device_index),
                "reserved_bytes_after_segment": torch.cuda.memory_reserved(device_index),
                "reason": segment["reason"],
                "chunk_count": len(tensors),
            })
    except Exception as exc:
        verdict = "INVALID_RUN_MEMORY_PROBE_EXCEPTION"
        failure = {"type": type(exc).__name__, "message": str(exc)}
    peak_allocated = torch.cuda.max_memory_allocated(device_index)
    peak_reserved = torch.cuda.max_memory_reserved(device_index)
    total_memory = torch.cuda.get_device_properties(device_index).total_memory
    fits = verdict == "FULL_CONFIG_MEMORY_PROBE_NOT_COMPLETION" and peak_reserved < total_memory
    allocated_segments.clear()
    gc.collect()
    torch.cuda.empty_cache()
    return {
        "verdict": verdict,
        "cuda_available": True,
        "torch_version": torch.__version__,
        "cuda_version": torch.version.cuda,
        "device_name": torch.cuda.get_device_name(device_index),
        "device_total_memory_bytes": total_memory,
        "warnings": warnings,
        "allocation_plan": plan,
        "allocations": allocations,
        "peak_allocated_bytes": peak_allocated,
        "peak_reserved_bytes": peak_reserved,
        "peak_reserved_gb": peak_reserved / GB,
        "device_total_memory_gb": total_memory / GB,
        "fits_memory_probe": fits,
        "failure": failure,
        "completion_limit": "Full-config allocation probe measures C1 memory-plan feasibility only. It is not full 1B forward/backward throughput and not family completion by itself.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--capability-target", required=True)
    args = parser.parse_args()

    raw = load_json(args.config)
    counts = analytical_parameter_count(raw["model"])
    receipt: dict[str, Any] = {
        "created_at_utc": now_utc(),
        "kind": "single_4090_full_config_memory_probe",
        "config_path": str(args.config),
        "config_id": raw.get("config_id"),
        "lane": raw.get("lane"),
        "capability_target": args.capability_target,
        "active_trainable_parameters": counts["active_trainable_parameters"],
        "parameter_count": counts,
        "platform": {"system": platform.system(), "release": platform.release(), "machine": platform.machine(), "python": platform.python_version()},
    }
    try:
        receipt.update(allocate_probe(args, raw, counts))
    except Exception as exc:
        receipt["verdict"] = "INVALID_RUN_EXCEPTION"
        receipt["error"] = {"type": type(exc).__name__, "message": str(exc), "traceback": traceback.format_exc()}
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0 if receipt.get("verdict") == "FULL_CONFIG_MEMORY_PROBE_NOT_COMPLETION" else 1


if __name__ == "__main__":
    raise SystemExit(main())
