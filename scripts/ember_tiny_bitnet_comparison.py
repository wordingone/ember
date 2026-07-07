#!/usr/bin/env python3
"""Immediate tiny BitNet/1.58-bit comparison after the resident gate."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
import tracemalloc
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from receipt_write import checked_write

TICKET = "EMBER-TINY-BITNET-COMPARISON"
SHA_CONVENTION = "bytes/tensors as-is; tensor hash includes name, shape, dtype, and CPU contiguous bytes"
DEFAULT_OUT_ROOT = Path(__file__).resolve().parent.parent / "scratch" / "tiny-bitnet-comparison"
DEFAULT_GATE_ROOT = Path(__file__).resolve().parent.parent / "scratch" / "resident-training-gate"


def ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json(path: Path, obj: dict[str, Any], *, receipt: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if receipt:
        checked_write(path, obj)
    else:
        path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def latest_resident_gate_receipt(gate_root: Path = DEFAULT_GATE_ROOT) -> tuple[Path | None, dict[str, Any] | None]:
    if not gate_root.exists():
        return None, None
    # Extract timestamp from filename (resident-training-gate-YYYYMMDDTHHMMSSZ.json)
    # instead of relying on filesystem mtime (which can be refreshed by git checkout).
    def extract_timestamp(path: Path) -> str:
        match = re.search(r"(\d{8}T\d{6}Z)", path.name)
        return match.group(1) if match else ""

    candidates = sorted(gate_root.glob("resident-training-gate-*.json"), key=extract_timestamp, reverse=True)
    for path in candidates:
        try:
            receipt = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        if receipt.get("resident_training_gate_status") == "PASS":
            return path, receipt
    return None, None


def tensor_hash(items: list[tuple[str, Any]]) -> str:
    h = hashlib.sha256()
    for name, param in sorted(items, key=lambda item: item[0]):
        data = param.detach().cpu().contiguous()
        h.update(name.encode("utf-8"))
        h.update(str(tuple(data.shape)).encode("utf-8"))
        h.update(str(data.dtype).encode("utf-8"))
        h.update(data.numpy().tobytes())
    return "sha256:" + h.hexdigest()


def trainable_count(model: Any) -> int:
    return int(sum(param.numel() for param in model.parameters() if param.requires_grad))


def ternary_ste(weight: Any) -> Any:
    import torch

    scale = weight.detach().abs().mean().clamp_min(torch.tensor(1e-6, dtype=weight.dtype, device=weight.device))
    threshold = 0.5 * scale
    q = torch.where(weight > threshold, torch.ones_like(weight), torch.where(weight < -threshold, -torch.ones_like(weight), torch.zeros_like(weight)))
    return weight + (q - weight).detach()


class TinyTernaryResidentPolicy:
    """Small BitNet-style resident policy: trainable params, ternary forward weights."""

    def __init__(self, in_features: int, out_features: int):
        import torch

        self.weight = torch.nn.Parameter(torch.zeros(out_features, in_features, dtype=torch.float16))
        self.bias = torch.nn.Parameter(torch.zeros(out_features, dtype=torch.float16))

    def parameters(self) -> list[Any]:
        return [self.weight, self.bias]

    def named_parameters(self) -> list[tuple[str, Any]]:
        return [("weight", self.weight), ("bias", self.bias)]

    def __call__(self, x: Any) -> Any:
        import torch

        return torch.nn.functional.linear(x, ternary_ste(self.weight), self.bias)


def make_fp16_policy(in_features: int, out_features: int) -> Any:
    import torch

    policy = torch.nn.Linear(in_features, out_features)
    torch.nn.init.zeros_(policy.weight)
    torch.nn.init.zeros_(policy.bias)
    return policy.to(dtype=torch.float16)


def train_policy(policy: Any, x: Any, y: Any, *, epochs: int, lr: float) -> dict[str, Any]:
    import torch

    opt = torch.optim.SGD(policy.parameters(), lr=lr)
    losses: list[float] = []
    process_start = time.process_time()
    wall_start = time.perf_counter()
    for _epoch in range(epochs):
        opt.zero_grad()
        logits = policy(x)
        loss = torch.nn.functional.cross_entropy(logits.float(), y)
        loss.backward()
        opt.step()
        losses.append(float(loss.item()))
    return {
        "epochs": epochs,
        "lr": lr,
        "initial_loss": losses[0],
        "final_loss": losses[-1],
        "wall_seconds": round(time.perf_counter() - wall_start, 6),
        "process_cpu_seconds": round(time.process_time() - process_start, 6),
    }


def choose(policy: Any, features: list[float]) -> int:
    import torch

    with torch.no_grad():
        x = torch.tensor([features], dtype=torch.float16)
        return int(policy(x).argmax(dim=1).item())


def score_rows(policy: Any, rows: list[dict[str, Any]], split: str) -> list[dict[str, Any]]:
    import ember_resident_training_candidate as symbolic
    import ember_train_multimodal_resident_adapter as adapter

    out: list[dict[str, Any]] = []
    b_idx = symbolic.TEMPLATES.index("instruction_only")
    for task in rows:
        idx = choose(policy, adapter.task_features(task))
        out.append(
            {
                "task_id": task.get("id"),
                "source_row_idx": task.get("source_row_idx"),
                "split": split,
                "fp_template": symbolic.TEMPLATES[idx],
                "score": adapter.template_score(task, idx),
                "instruction_only_score": adapter.template_score(task, b_idx),
            }
        )
    return out


def deletion_rows(bitnet_policy: Any, deleted_policy: Any, rows: list[dict[str, Any]], split: str) -> list[dict[str, Any]]:
    import ember_resident_training_candidate as symbolic
    import ember_train_multimodal_resident_adapter as adapter

    out: list[dict[str, Any]] = []
    for task in rows:
        features = adapter.task_features(task)
        bitnet_idx = choose(bitnet_policy, features)
        deleted_idx = choose(deleted_policy, features)
        out.append(
            {
                "task_id": task.get("id"),
                "source_row_idx": task.get("source_row_idx"),
                "split": split,
                "bitnet_template": symbolic.TEMPLATES[bitnet_idx],
                "deleted_template": symbolic.TEMPLATES[deleted_idx],
                "bitnet_score": adapter.template_score(task, bitnet_idx),
                "deleted_score": adapter.template_score(task, deleted_idx),
                "deleted_condition": "ternary_policy_parameters_reverted_to_zero_pre_update_state",
            }
        )
    return out


def mean_score(rows: list[dict[str, Any]], key: str = "score") -> float:
    return round(sum(float(row[key]) for row in rows) / max(len(rows), 1), 6)


def model_bytes_fp16(policy: Any) -> int:
    return int(sum(param.numel() * 2 for param in policy.parameters()))


def model_bytes_ternary(policy: Any) -> int:
    weight, bias = list(policy.parameters())
    return int((weight.numel() * 1.58 + bias.numel() * 16) / 8)


def latency(policy: Any, features: list[float], repeats: int = 512) -> dict[str, Any]:
    import torch

    x = torch.tensor([features], dtype=torch.float16)
    with torch.no_grad():
        for _ in range(8):
            policy(x)
        start = time.perf_counter()
        for _ in range(repeats):
            policy(x)
        elapsed = time.perf_counter() - start
    return {"repeats": repeats, "total_seconds": round(elapsed, 6), "mean_ms": round((elapsed / repeats) * 1000.0, 6)}


def run_comparison(out_dir: Path, *, gate_root: Path = DEFAULT_GATE_ROOT, resident_gate_receipt: Path | None = None) -> dict[str, Any]:
    import torch
    import ember_resident_training_candidate as symbolic
    import ember_train_multimodal_resident_adapter as adapter

    out_dir.mkdir(parents=True, exist_ok=True)
    if resident_gate_receipt is not None:
        gate_path = resident_gate_receipt
        gate_receipt = json.loads(resident_gate_receipt.read_text(encoding="utf-8-sig")) if resident_gate_receipt.exists() else None
    else:
        gate_path, gate_receipt = latest_resident_gate_receipt(gate_root)
    if gate_receipt is None:
        receipt = {
            "ticket": TICKET,
            "ts": ts(),
            "verdict": "BITNET_BLOCKED",
            "post_resident_gate_required": True,
            "resident_gate_receipt_status": "MISSING",
            "resident_gate_receipt_path": None,
            "missing_implementation_surface": "resident-training gate PASS receipt",
            "next_executable_command": "python scripts\\ember_resident_training_gate.py --candidate-manifest <manifest> --out <gate-receipt>",
        }
        write_json(out_dir / "tiny_bitnet_comparison_receipt.json", receipt, receipt=True)
        return receipt

    task_source, tasks = adapter.load_task_source(adapter.DEFAULT_TASKS)
    train_tasks, heldout_tasks, transfer_tasks = adapter.split_tasks(tasks)
    torch.manual_seed(20260621)
    x = torch.tensor([adapter.task_features(task) for task in train_tasks], dtype=torch.float16)
    y = torch.tensor([adapter.best_template_index(task) for task in train_tasks], dtype=torch.long)
    out_features = len(symbolic.TEMPLATES)
    fp16_policy = make_fp16_policy(7, out_features)
    bitnet_policy = TinyTernaryResidentPolicy(7, out_features)
    deleted_bitnet_policy = TinyTernaryResidentPolicy(7, out_features)
    fp16_pre = tensor_hash([(f"fp16.{name}", param) for name, param in fp16_policy.named_parameters()])
    bitnet_pre = tensor_hash([(f"bitnet.{name}", param) for name, param in bitnet_policy.named_parameters()])

    tracemalloc.start()
    fp16_train = train_policy(fp16_policy, x, y, epochs=40, lr=0.8)
    bitnet_train = train_policy(bitnet_policy, x, y, epochs=40, lr=0.8)
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    fp16_post = tensor_hash([(f"fp16.{name}", param) for name, param in fp16_policy.named_parameters()])
    bitnet_post = tensor_hash([(f"bitnet.{name}", param) for name, param in bitnet_policy.named_parameters()])
    fp16_heldout = score_rows(fp16_policy, heldout_tasks, "heldout")
    bitnet_heldout = score_rows(bitnet_policy, heldout_tasks, "heldout")
    fp16_transfer = score_rows(fp16_policy, transfer_tasks, "transfer")
    bitnet_transfer = score_rows(bitnet_policy, transfer_tasks, "transfer")
    deletion = deletion_rows(bitnet_policy, deleted_bitnet_policy, heldout_tasks + transfer_tasks, "heldout_or_transfer")
    quality_delta = {
        "fp16_heldout_mean": mean_score(fp16_heldout),
        "bitnet_heldout_mean": mean_score(bitnet_heldout),
        "bitnet_minus_fp16_heldout_mean": round(mean_score(bitnet_heldout) - mean_score(fp16_heldout), 6),
        "fp16_transfer_mean": mean_score(fp16_transfer),
        "bitnet_transfer_mean": mean_score(bitnet_transfer),
        "bitnet_minus_fp16_transfer_mean": round(mean_score(bitnet_transfer) - mean_score(fp16_transfer), 6),
    }
    receipt = {
        "ticket": TICKET,
        "ts": ts(),
        "sha_convention": SHA_CONVENTION,
        "verdict": "BITNET_COMPARISON_PASS",
        "post_resident_gate_required": True,
        "resident_gate_receipt_status": gate_receipt.get("resident_training_gate_status"),
        "resident_gate_receipt_path": str(gate_path),
        "resident_gate_receipt_sha256": sha256(gate_path) if gate_path else None,
        "task_source": task_source,
        "same_resident_harness": "ember_train_multimodal_resident_adapter task features, verifier reward templates, frozen D3-Gym slices",
        "fp16_baseline_identity": "tiny_fp16_resident_policy_linear_seed_20260621_same_as_post_gate_policy_shape",
        "bitnet_model_identity": "tiny_ste_ternary_resident_policy_b1_58_seed_20260621",
        "precision_quantization_scheme": {
            "fp16": "torch.float16 Linear policy weights and bias",
            "bitnet": "BitNet-style ternary forward weights {-1,0,+1} with straight-through estimator; fp16 trainable latent weights; bias fp16",
        },
        "fp16_trainable_parameter_count": trainable_count(fp16_policy),
        "bitnet_trainable_parameter_count": trainable_count(bitnet_policy),
        "fp16_pre_parameter_hash": fp16_pre,
        "fp16_post_parameter_hash": fp16_post,
        "bitnet_pre_parameter_hash": bitnet_pre,
        "bitnet_post_parameter_hash": bitnet_post,
        "verifier_conditioned_training_command": "python scripts\\ember_tiny_bitnet_comparison.py --out-dir <out>",
        "matched_budget_envelope": {
            "same_train_rows": True,
            "same_heldout_rows": True,
            "same_transfer_rows": True,
            "same_epochs": fp16_train["epochs"] == bitnet_train["epochs"],
            "same_lr": fp16_train["lr"] == bitnet_train["lr"],
            "same_seed": 20260621,
            "same_verifier": "ember_resident_training_candidate.score_plan over frozen task rows",
        },
        "training": {"fp16": fp16_train, "bitnet": bitnet_train},
        "heldout_rows": [
            {**fp, "fp16_score": fp["score"], "bitnet_score": bn["score"], "bitnet_template": bn["fp_template"]}
            for fp, bn in zip(fp16_heldout, bitnet_heldout)
        ],
        "transfer_rows": [
            {**fp, "fp16_score": fp["score"], "bitnet_score": bn["score"], "bitnet_template": bn["fp_template"]}
            for fp, bn in zip(fp16_transfer, bitnet_transfer)
        ],
        "quality_delta": quality_delta,
        "footprint": {
            "fp16_parameter_bytes": model_bytes_fp16(fp16_policy),
            "bitnet_effective_parameter_bytes": model_bytes_ternary(bitnet_policy),
            "bitnet_effective_weight_bits": 1.58,
            "bias_bits": 16,
        },
        "throughput_latency": {
            "fp16": latency(fp16_policy, adapter.task_features(heldout_tasks[0])),
            "bitnet": latency(bitnet_policy, adapter.task_features(heldout_tasks[0])),
        },
        "memory_cpu_measurements": {
            "torch_cuda_available": bool(torch.cuda.is_available()),
            "cuda_max_memory_allocated_bytes": int(torch.cuda.max_memory_allocated()) if torch.cuda.is_available() else 0,
            "python_tracemalloc_peak_bytes_during_training": int(peak),
            "device": "cpu",
        },
        "deletion_revert_evidence": deletion,
        "missing_implementation_surface": None,
        "next_executable_command": "python scripts\\ember_post_resident_discovery.py --after-bitnet-receipt <receipt>",
    }
    write_json(out_dir / "tiny_bitnet_comparison_receipt.json", receipt, receipt=True)
    return receipt


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-dir")
    ap.add_argument("--resident-gate-receipt")
    args = ap.parse_args()
    out_dir = Path(args.out_dir) if args.out_dir else DEFAULT_OUT_ROOT / ts()
    resident_gate_receipt = Path(args.resident_gate_receipt) if args.resident_gate_receipt else None
    receipt = run_comparison(out_dir, resident_gate_receipt=resident_gate_receipt)
    print(json.dumps({"receipt": str(out_dir / "tiny_bitnet_comparison_receipt.json"), "verdict": receipt["verdict"]}, indent=2))
    return 0 if receipt.get("verdict") in {"BITNET_COMPARISON_PASS", "BITNET_BLOCKED"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
