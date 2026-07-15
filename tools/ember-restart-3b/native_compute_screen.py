# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Current-native, non-admissible full-step throughput screen."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

import torch
import torch.nn.functional as F

from batch import decode_owned_batch
from model import RestartDecoderConfig, UnifiedDecoder
from parameter_counter import measure_parameter_counts
from run_vertical_slice import build_production_optimizer, load_optimizer_contract
from semantic_stream import ManifestBoundTokenStream

_SEQUENCE_LENGTH = 1024
_REQUIRED_BATCHES = (1, 2)
_MEMORY_GATE_BATCHES = (4, 8)


def screen_plan(*, total_vram_bytes: int) -> dict[str, object]:
    if not isinstance(total_vram_bytes, int) or total_vram_bytes <= 0:
        raise ValueError("total VRAM bytes must be positive")
    return {
        "sequence_length": _SEQUENCE_LENGTH,
        "required_batches": list(_REQUIRED_BATCHES),
        "memory_gate_only_batches": list(_MEMORY_GATE_BATCHES),
        "max_peak_allocated_bytes": int(total_vram_bytes * 0.8),
        "minimum_free_margin_bytes": int(1.5 * 1024**3),
    }


def screen_receipt(
    *,
    model_config_sha256: str,
    optimizer_contract_sha256: str,
    tokenizer_sha256: str,
    checkpoint_manifest_sha256: str,
    source_sha256: str,
    total_vram_bytes: int,
    available_vram_bytes: int | None = None,
    custody: dict[str, Any] | None = None,
    batch_measurements: list[dict[str, Any]],
) -> dict[str, object]:
    plan = screen_plan(total_vram_bytes=total_vram_bytes)
    required = list(plan["required_batches"])
    max_peak = int(plan["max_peak_allocated_bytes"])
    available = total_vram_bytes if available_vram_bytes is None else available_vram_bytes
    if not isinstance(available, int) or available <= 0 or available > total_vram_bytes:
        raise ValueError("available VRAM bytes must be a positive value no greater than total VRAM")
    minimum_margin = int(plan["minimum_free_margin_bytes"])
    for item in batch_measurements:
        if not isinstance(item.get("elapsed_seconds"), (int, float)) or item["elapsed_seconds"] <= 0:
            raise ValueError("screen step timing must be positive")
        if not isinstance(item.get("peak_allocated_bytes"), int) or item["peak_allocated_bytes"] > max_peak:
            raise MemoryError("0.8 VRAM governor rejects the measured allocation")
        if not isinstance(item.get("peak_reserved_bytes"), int) or item["peak_reserved_bytes"] < item["peak_allocated_bytes"]:
            raise ValueError("screen reserved peak must cover allocated peak")
        if available - item["peak_reserved_bytes"] < minimum_margin:
            raise MemoryError("1.5 GiB free-memory governor rejects the measured reservation")
    observed = [item.get("batch_size") for item in batch_measurements]
    if observed != required:
        raise ValueError("screen receipt requires exactly batch-1 then batch-2 full steps")
    required_custody = {"hardware_runtime", "source_closure_sha256", "emberd_schedule_receipt_sha256", "disk_budget_receipt_sha256"}
    if not isinstance(custody, dict) or set(custody) != required_custody:
        raise ValueError("screen receipt custody must bind runtime, source closure, emberd, and disk evidence")
    runtime = custody["hardware_runtime"]
    if not isinstance(runtime, dict) or not {"gpu_name", "compute_capability", "torch_version", "cuda_version", "cudnn_version", "optimizer_implementation", "optimizer_version"}.issubset(runtime):
        raise ValueError("screen receipt custody runtime identity is incomplete")
    closure = custody["source_closure_sha256"]
    needed_sources = {"model.py", "batch.py", "semantic_stream.py", "run_vertical_slice.py", "parameter_counter.py", "native_compute_screen.py"}
    if not isinstance(closure, dict) or set(closure) != needed_sources or any(not isinstance(value, str) or len(value) != 64 for value in closure.values()):
        raise ValueError("screen receipt custody source closure is incomplete")
    if any(not isinstance(custody[key], str) or len(custody[key]) != 64 for key in ("emberd_schedule_receipt_sha256", "disk_budget_receipt_sha256")):
        raise ValueError("screen receipt custody receipt hashes are invalid")
    return {
        "schema_version": "ember-native-compute-screen-v1",
        "result": "MEASURED",
        "admission": "NON_ADMISSIBLE_COMPUTE_PRIMITIVE",
        "operation": "CLEAN_GENESIS_FULL_FORWARD_BACKWARD_OPTIMIZER_STEP",
        "sequence_length": _SEQUENCE_LENGTH,
        "required_batches": required,
        "memory_gate_only_batches": list(plan["memory_gate_only_batches"]),
        "vram_governor": {"maximum_fraction": 0.8, "minimum_free_margin_bytes": plan["minimum_free_margin_bytes"]},
        "model_config_sha256": model_config_sha256,
        "optimizer_contract_sha256": optimizer_contract_sha256,
        "tokenizer_sha256": tokenizer_sha256,
        "checkpoint_manifest_sha256": checkpoint_manifest_sha256,
        "source_sha256": source_sha256,
        "total_vram_bytes": total_vram_bytes,
        "available_vram_bytes_at_dispatch": available,
        "custody": custody,
        "steps": batch_measurements,
    }

def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False) as handle:
        json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def _full_step(*, model: UnifiedDecoder, optimizer: torch.optim.Optimizer, record: dict[str, object], config: RestartDecoderConfig, batch_size: int, device: torch.device) -> dict[str, object]:
    batch = decode_owned_batch(record, config, device=device)
    input_ids = batch["input_ids"].repeat(batch_size, 1)
    target_ids = batch["target_ids"].repeat(batch_size, 1)
    torch.cuda.reset_peak_memory_stats(device)
    torch.cuda.synchronize(device)
    started = time.perf_counter()
    optimizer.zero_grad(set_to_none=True)
    logits = model(input_ids, active_expert="shared")
    loss = F.cross_entropy(logits.float().reshape(-1, config.vocab_size), target_ids.reshape(-1))
    if not torch.isfinite(loss):
        raise RuntimeError("native full-step screen produced a non-finite loss")
    loss.backward()
    optimizer.step()
    torch.cuda.synchronize(device)
    return {
        "batch_size": batch_size,
        "elapsed_seconds": time.perf_counter() - started,
        "loss": float(loss.detach().cpu()),
        "peak_allocated_bytes": int(torch.cuda.max_memory_allocated(device)),
        "peak_reserved_bytes": int(torch.cuda.max_memory_reserved(device)),
    }


def run_screen(*, receipt_path: Path, shards_root: Path, tokenizer_path: Path, reference_checkpoint_manifest: Path, emberd_schedule_receipt: Path, disk_budget_receipt: Path, output: Path, seed: int) -> dict[str, object]:
    """Run both required clean-genesis batch arms; call only through disk_budget_runner."""
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for the native full-step screen")
    if not isinstance(seed, int) or seed < 0:
        raise ValueError("screen seed must be a nonnegative integer")
    if output.exists():
        raise FileExistsError("native screen output must be a fresh path")
    if not reference_checkpoint_manifest.is_file() or not emberd_schedule_receipt.is_file() or not disk_budget_receipt.is_file():
        raise ValueError("reference checkpoint, emberd schedule, and disk-budget receipts must exist")
    # This is deliberately before model allocation: all 26 shard bytes and tokenizer bytes are rechecked first.
    stream = ManifestBoundTokenStream.from_receipt(receipt_path=receipt_path, shards_root=shards_root, tokenizer_path=tokenizer_path)
    root = Path(__file__).resolve().parents[2]
    config_path = root / "configs" / "ember-restart-3b.json"
    config = RestartDecoderConfig.from_contract(config_path)
    optimizer_contract = load_optimizer_contract(config_path)
    device = torch.device("cuda")
    available, total = torch.cuda.mem_get_info(device)
    plan = screen_plan(total_vram_bytes=int(total))
    if available < int(plan["minimum_free_margin_bytes"]):
        raise MemoryError("native screen dispatch lacks the 1.5 GiB GPU free-memory floor")
    record, _ = stream.next_episode(shard_index=0, token_offset=0, sequence_length=_SEQUENCE_LENGTH)
    steps: list[dict[str, object]] = []
    counts: dict[str, object] | None = None
    for batch_size in _REQUIRED_BATCHES:
        torch.manual_seed(seed)
        torch.cuda.manual_seed_all(seed)
        previous_dtype = torch.get_default_dtype()
        torch.set_default_dtype(torch.bfloat16)
        try:
            model = UnifiedDecoder(config, device=device, allow_production_allocation=True, genesis_seed=seed)
        finally:
            torch.set_default_dtype(previous_dtype)
        model.train()
        model._activate_expert("shared")
        counts = measure_parameter_counts(model)
        if int(counts["unique_parameters"]) < 3_000_000_000 or counts["active_expert_ids"] != ["shared"]:
            raise RuntimeError("native screen did not instantiate the required owned shared-active 3B path")
        optimizer = build_production_optimizer(model, optimizer_contract=optimizer_contract)
        steps.append(_full_step(model=model, optimizer=optimizer, record=record, config=config, batch_size=batch_size, device=device))
        del optimizer, model
        torch.cuda.empty_cache()
    result = screen_receipt(
        model_config_sha256=_sha256(config_path),
        optimizer_contract_sha256=hashlib.sha256(json.dumps(optimizer_contract, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest(),
        tokenizer_sha256=stream.tokenizer_sha256,
        checkpoint_manifest_sha256=_sha256(reference_checkpoint_manifest),
        source_sha256=_sha256(Path(__file__)),
        total_vram_bytes=int(total),
        available_vram_bytes=int(available),
        custody={"hardware_runtime": {"gpu_name": torch.cuda.get_device_name(device), "compute_capability": ".".join(map(str, torch.cuda.get_device_capability(device))), "torch_version": torch.__version__, "cuda_version": torch.version.cuda or "unavailable", "cudnn_version": str(torch.backends.cudnn.version()), "optimizer_implementation": str(optimizer_contract["implementation"]), "optimizer_version": __import__("bitsandbytes").__version__}, "source_closure_sha256": {name: _sha256(root / "tools" / "ember-restart-3b" / name) for name in ("model.py", "batch.py", "semantic_stream.py", "run_vertical_slice.py", "parameter_counter.py", "native_compute_screen.py")}, "emberd_schedule_receipt_sha256": _sha256(emberd_schedule_receipt), "disk_budget_receipt_sha256": _sha256(disk_budget_receipt)},
        batch_measurements=steps,
    )
    result.update({
        "genesis_seed": seed,
        "reference_checkpoint_role": "CUSTODY_REFERENCE_ONLY_NOT_LOADED",
        "stream_receipt_sha256": stream.receipt_sha256,
        "total_parameters": counts["unique_parameters"] if counts else None,
        "active_parameters": counts["active_parameters"] if counts else None,
    })
    _atomic_json(output, result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--shards-root", type=Path, required=True)
    parser.add_argument("--tokenizer", type=Path, required=True)
    parser.add_argument("--reference-checkpoint-manifest", type=Path, required=True)
    parser.add_argument("--emberd-schedule-receipt", type=Path, required=True)
    parser.add_argument("--disk-budget-receipt", type=Path, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(run_screen(receipt_path=args.receipt, shards_root=args.shards_root, tokenizer_path=args.tokenizer, reference_checkpoint_manifest=args.reference_checkpoint_manifest, emberd_schedule_receipt=args.emberd_schedule_receipt, disk_budget_receipt=args.disk_budget_receipt, output=args.output, seed=args.seed), sort_keys=True))
    except Exception as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())