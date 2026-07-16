# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Current-native, non-admissible full-step throughput screen."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
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
    runtime_fields = {"gpu_name", "compute_capability", "torch_version", "cuda_version", "cudnn_version", "optimizer_implementation", "optimizer_version"}
    if not isinstance(runtime, dict) or not runtime_fields.issubset(runtime) or any(not isinstance(runtime[field], str) or not runtime[field].strip() for field in runtime_fields):
        raise ValueError("screen receipt custody runtime identity is incomplete")
    closure = custody["source_closure_sha256"]
    needed_sources = {"model.py", "batch.py", "semantic_stream.py", "run_vertical_slice.py", "parameter_counter.py", "native_compute_screen.py"}
    if not isinstance(closure, dict) or set(closure) != needed_sources or any(not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value) for value in closure.values()):
        raise ValueError("screen receipt custody source closure is incomplete")
    if any(not isinstance(custody[key], str) or not re.fullmatch(r"[0-9a-f]{64}", custody[key]) for key in ("emberd_schedule_receipt_sha256", "disk_budget_receipt_sha256")):
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

_SCREEN_JOB_ID = "ember-02b-native-clean-genesis-screen-b1-b2-seed83"
_SOURCE_NAMES = (
    "model.py",
    "batch.py",
    "semantic_stream.py",
    "run_vertical_slice.py",
    "parameter_counter.py",
    "native_compute_screen.py",
)
_OPERATING_FLOORS_GIB = {"B": 250.0, "C": 150.0}
_MAX_WRITE_GIB = {"B": 0.1, "C": 0.1}
_MAX_SCHEDULE_FUTURE_SKEW_MS = 60_000


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _validate_source_closure(closure: object) -> dict[str, str]:
    if not isinstance(closure, dict) or set(closure) != set(_SOURCE_NAMES):
        raise ValueError("source closure must bind every native screen source")
    if any(not _is_sha256(value) for value in closure.values()):
        raise ValueError("source closure must use lowercase SHA-256 digests")
    return dict(closure)


def _source_closure(root: Path) -> dict[str, str]:
    return {name: _sha256(root / "tools" / "ember-restart-3b" / name) for name in _SOURCE_NAMES}


def _assert_source_closure_stable(before: dict[str, str], after: dict[str, str]) -> None:
    if before != after:
        raise RuntimeError("native screen source closure changed before receipt publication")


def _read_json_receipt(path: Path, label: str) -> tuple[dict[str, object], str]:
    try:
        raw = path.read_bytes()
        payload = json.loads(raw)
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} must be readable JSON") from error
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be a JSON object")
    return payload, hashlib.sha256(raw).hexdigest()


def _dispatch_binding(*, output: Path, seed: int) -> dict[str, object]:
    if not isinstance(seed, int) or seed < 0:
        raise ValueError("screen dispatch seed must be a nonnegative integer")
    payload = {
        "job_id": _SCREEN_JOB_ID,
        "sequence_length": _SEQUENCE_LENGTH,
        "required_batches": list(_REQUIRED_BATCHES),
        "seed": seed,
        "output_path_sha256": hashlib.sha256(str(output.resolve()).encode("utf-8")).hexdigest(),
    }
    return {
        "payload": payload,
        "sha256": hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest(),
    }


def _dispatch_sha256(*, output: Path, seed: int) -> str:
    return str(_dispatch_binding(output=output, seed=seed)["sha256"])

def _validated_daemon_identity(value: object, label: str) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != {"binary_sha256", "source_sha256"} or any(not _is_sha256(digest) for digest in value.values()):
        raise ValueError(f"{label} must bind lowercase binary/source SHA-256 values")
    return dict(value)


def _validate_schedule_receipt(path: Path, *, now_ms: int | None = None) -> dict[str, object]:
    payload, digest = _read_json_receipt(path, "emberd schedule receipt")
    runs = payload.get("runs")
    if payload.get("schema_version") != "emberd-schedule-alarm-state-v1" or not isinstance(runs, list):
        raise ValueError("emberd schedule receipt has an invalid schema")
    if not isinstance(payload.get("generated_at_ms"), int) or payload["generated_at_ms"] <= 0:
        raise ValueError("emberd schedule receipt lacks an integer generation timestamp")
    top_identity = _validated_daemon_identity(payload.get("emberd_identity"), "emberd identity")
    matches = [run for run in runs if isinstance(run, dict) and run.get("job_id") == _SCREEN_JOB_ID]
    if len(matches) != 1:
        raise ValueError("emberd schedule receipt does not bind the native B1/B2 prediction")
    run = matches[0]
    if run.get("artifact_class") != "compute-primitive" or run.get("predicted_tokens") != 3072 or run.get("predicted_duration_ms") != 720000:
        raise ValueError("emberd schedule receipt does not bind the native B1/B2 prediction")
    timestamps = ("predicted_at_ms", "predicted_program_completion_ms", "absolute_deadline_ms")
    if any(not isinstance(run.get(field), int) or run[field] <= 0 for field in timestamps):
        raise ValueError("emberd schedule receipt lacks integer prediction timestamps and deadline")
    if not run["predicted_at_ms"] <= run["predicted_program_completion_ms"] <= run["absolute_deadline_ms"]:
        raise ValueError("emberd schedule prediction timestamps are not ordered")
    observed_now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    if not isinstance(observed_now_ms, int) or isinstance(observed_now_ms, bool) or observed_now_ms <= 0:
        raise ValueError("schedule validation requires a positive current timestamp")
    maximum_issued_timestamp_ms = observed_now_ms + _MAX_SCHEDULE_FUTURE_SKEW_MS
    if payload["generated_at_ms"] > maximum_issued_timestamp_ms or run["predicted_at_ms"] > maximum_issued_timestamp_ms:
        raise ValueError("emberd schedule exceeds bounded future clock skew")
    if observed_now_ms >= run["absolute_deadline_ms"]:
        raise ValueError("emberd schedule deadline has elapsed")
    prediction_identity = _validated_daemon_identity(run.get("prediction_daemon_identity"), "emberd prediction identity")
    if prediction_identity != top_identity:
        raise ValueError("emberd prediction identity does not match the schedule identity")
    return {
        "sha256": digest,
        "generated_at_ms": payload["generated_at_ms"],
        "predicted_at_ms": run["predicted_at_ms"],
        "predicted_program_completion_ms": run["predicted_program_completion_ms"],
        "absolute_deadline_ms": run["absolute_deadline_ms"],
        "predicted_duration_ms": run["predicted_duration_ms"],
        "predicted_tokens": run["predicted_tokens"],
        "prediction_daemon_identity": prediction_identity,
    }


def _validate_dispatch_payload(dispatch: object) -> dict[str, object]:
    required = {"job_id", "sequence_length", "required_batches", "seed", "output_path_sha256"}
    if not isinstance(dispatch, dict) or set(dispatch) != required:
        raise ValueError("disk preflight must bind the canonical screen dispatch")
    if dispatch.get("job_id") != _SCREEN_JOB_ID or dispatch.get("sequence_length") != _SEQUENCE_LENGTH or dispatch.get("required_batches") != list(_REQUIRED_BATCHES):
        raise ValueError("disk preflight must bind the canonical screen dispatch")
    if not isinstance(dispatch.get("seed"), int) or dispatch["seed"] < 0 or not _is_sha256(dispatch.get("output_path_sha256")):
        raise ValueError("disk preflight must bind the canonical screen dispatch")
    return dict(dispatch)


def _canonical_dispatch_sha256(dispatch: dict[str, object]) -> str:
    return hashlib.sha256(json.dumps(dispatch, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def disk_preflight_receipt(
    *,
    free_bytes_by_drive: dict[str, int],
    source_closure_sha256: dict[str, str],
    emberd_schedule_receipt_sha256: str,
    dispatch_sha256: str,
    dispatch: dict[str, object],
) -> dict[str, object]:
    closure = _validate_source_closure(source_closure_sha256)
    canonical_dispatch = _validate_dispatch_payload(dispatch)
    if not _is_sha256(emberd_schedule_receipt_sha256) or not _is_sha256(dispatch_sha256):
        raise ValueError("disk preflight must bind lowercase schedule and dispatch SHA-256 values")
    if dispatch_sha256 != _canonical_dispatch_sha256(canonical_dispatch):
        raise ValueError("disk preflight dispatch digest does not match its canonical dispatch")
    if set(free_bytes_by_drive) != set(_OPERATING_FLOORS_GIB) or any(not isinstance(value, int) or value < 0 for value in free_bytes_by_drive.values()):
        raise ValueError("disk preflight requires observed B and C free bytes")
    observed = {drive: round(free_bytes_by_drive[drive] / 1024**3, 6) for drive in _OPERATING_FLOORS_GIB}
    projected = {drive: round(observed[drive] - _MAX_WRITE_GIB[drive], 6) for drive in _OPERATING_FLOORS_GIB}
    if any(projected[drive] < _OPERATING_FLOORS_GIB[drive] for drive in _OPERATING_FLOORS_GIB):
        raise ValueError("disk preflight projected end crosses an operating floor")
    return {
        "schema_version": "ember-native-screen-disk-preflight-v1",
        "job_id": _SCREEN_JOB_ID,
        "result": "PASSED",
        "max_b_write_gib": _MAX_WRITE_GIB["B"],
        "max_c_write_gib": _MAX_WRITE_GIB["C"],
        "operating_floors_gib": dict(_OPERATING_FLOORS_GIB),
        "observed_free_gib": observed,
        "projected_end_free_gib": projected,
        "source_closure_sha256": closure,
        "emberd_schedule_receipt_sha256": emberd_schedule_receipt_sha256,
        "dispatch_sha256": dispatch_sha256,
        "dispatch": canonical_dispatch,
    }


def write_disk_preflight(
    *,
    path: Path,
    source_closure_sha256: dict[str, str],
    emberd_schedule_receipt_sha256: str,
    dispatch_sha256: str,
    dispatch: dict[str, object],
    free_bytes_by_drive: dict[str, int] | None = None,
) -> dict[str, object]:
    observed = free_bytes_by_drive
    if observed is None:
        observed = {drive: shutil.disk_usage(f"{drive}:\\").free for drive in _OPERATING_FLOORS_GIB}
    receipt = disk_preflight_receipt(
        free_bytes_by_drive=observed,
        source_closure_sha256=source_closure_sha256,
        emberd_schedule_receipt_sha256=emberd_schedule_receipt_sha256,
        dispatch_sha256=dispatch_sha256,
        dispatch=dispatch,
    )
    _atomic_json(path, receipt)
    return receipt


def _validate_disk_preflight(
    path: Path,
    *,
    expected_schedule_sha256: str | None = None,
    expected_source_closure_sha256: dict[str, str] | None = None,
    expected_dispatch_sha256: str | None = None,
) -> dict[str, object]:
    payload, digest = _read_json_receipt(path, "disk preflight receipt")
    if payload.get("schema_version") != "ember-native-screen-disk-preflight-v1" or payload.get("job_id") != _SCREEN_JOB_ID or payload.get("result") != "PASSED":
        raise ValueError("disk preflight receipt does not bind the native screen job")
    if payload.get("max_b_write_gib") != _MAX_WRITE_GIB["B"] or payload.get("max_c_write_gib") != _MAX_WRITE_GIB["C"] or payload.get("operating_floors_gib") != _OPERATING_FLOORS_GIB:
        raise ValueError("disk preflight receipt does not bind the approved B/C budget and floors")
    closure = _validate_source_closure(payload.get("source_closure_sha256"))
    if expected_source_closure_sha256 is not None and closure != _validate_source_closure(expected_source_closure_sha256):
        raise ValueError("disk preflight source closure does not match the executable screen")
    schedule_digest = payload.get("emberd_schedule_receipt_sha256")
    dispatch_digest = payload.get("dispatch_sha256")
    if not _is_sha256(schedule_digest) or not _is_sha256(dispatch_digest):
        raise ValueError("disk preflight receipt lacks canonical schedule and dispatch digests")
    canonical_dispatch = _validate_dispatch_payload(payload.get("dispatch"))
    if dispatch_digest != _canonical_dispatch_sha256(canonical_dispatch):
        raise ValueError("disk preflight dispatch digest does not match its canonical dispatch")
    if expected_schedule_sha256 is not None and schedule_digest != expected_schedule_sha256:
        raise ValueError("disk preflight does not match the validated emberd schedule")
    if expected_dispatch_sha256 is not None and dispatch_digest != expected_dispatch_sha256:
        raise ValueError("disk preflight does not match the exact screen dispatch")
    observed = payload.get("observed_free_gib")
    projected = payload.get("projected_end_free_gib")
    if not isinstance(observed, dict) or not isinstance(projected, dict) or set(observed) != set(_OPERATING_FLOORS_GIB) or set(projected) != set(_OPERATING_FLOORS_GIB):
        raise ValueError("disk preflight receipt lacks observed and projected B/C free space")
    for drive, floor in _OPERATING_FLOORS_GIB.items():
        if not isinstance(observed[drive], (int, float)) or not isinstance(projected[drive], (int, float)) or projected[drive] < floor:
            raise ValueError("disk preflight receipt crosses an operating floor")
        if round(float(observed[drive]) - _MAX_WRITE_GIB[drive], 6) != round(float(projected[drive]), 6):
            raise ValueError("disk preflight projected end does not match its write budget")
    return {
        "sha256": digest,
        "dispatch_sha256": dispatch_digest,
        "dispatch": canonical_dispatch,
        "max_write_gib": {"B": payload["max_b_write_gib"], "C": payload["max_c_write_gib"]},
        "operating_floors_gib": payload["operating_floors_gib"],
        "observed_free_gib": observed,
        "projected_end_free_gib": projected,
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
    root = Path(__file__).resolve().parents[2]
    schedule_binding = _validate_schedule_receipt(emberd_schedule_receipt)
    source_closure_before = _source_closure(root)
    dispatch_binding = _dispatch_binding(output=output, seed=seed)
    dispatch_sha256 = str(dispatch_binding["sha256"])
    disk_preflight_binding = _validate_disk_preflight(
        disk_budget_receipt,
        expected_schedule_sha256=str(schedule_binding["sha256"]),
        expected_source_closure_sha256=source_closure_before,
        expected_dispatch_sha256=dispatch_sha256,
    )
    # This is deliberately before model allocation: all 26 shard bytes and tokenizer bytes are rechecked first.
    stream = ManifestBoundTokenStream.from_receipt(receipt_path=receipt_path, shards_root=shards_root, tokenizer_path=tokenizer_path)
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
    if _source_closure(root) != source_closure_before:
        raise RuntimeError("native screen source closure changed before receipt publication")
    result = screen_receipt(
        model_config_sha256=_sha256(config_path),
        optimizer_contract_sha256=hashlib.sha256(json.dumps(optimizer_contract, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest(),
        tokenizer_sha256=stream.tokenizer_sha256,
        checkpoint_manifest_sha256=_sha256(reference_checkpoint_manifest),
        source_sha256=_sha256(Path(__file__)),
        total_vram_bytes=int(total),
        available_vram_bytes=int(available),
        custody={"hardware_runtime": {"gpu_name": torch.cuda.get_device_name(device), "compute_capability": ".".join(map(str, torch.cuda.get_device_capability(device))), "torch_version": torch.__version__, "cuda_version": torch.version.cuda or "unavailable", "cudnn_version": str(torch.backends.cudnn.version()), "optimizer_implementation": str(optimizer_contract["implementation"]), "optimizer_version": __import__("bitsandbytes").__version__}, "source_closure_sha256": source_closure_before, "emberd_schedule_receipt_sha256": str(schedule_binding["sha256"]), "disk_budget_receipt_sha256": str(disk_preflight_binding["sha256"])},
        batch_measurements=steps,
    )
    result.update({
        "genesis_seed": seed,
        "reference_checkpoint_role": "CUSTODY_REFERENCE_ONLY_NOT_LOADED",
        "stream_receipt_sha256": stream.receipt_sha256,
        "total_parameters": counts["unique_parameters"] if counts else None,
        "active_parameters": counts["active_parameters"] if counts else None,
        "validated_external": {
            "emberd_schedule": schedule_binding,
            "disk_preflight": disk_preflight_binding,
        },
    })
    _atomic_json(output, result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--shards-root", type=Path)
    parser.add_argument("--tokenizer", type=Path)
    parser.add_argument("--reference-checkpoint-manifest", type=Path)
    parser.add_argument("--emberd-schedule-receipt", type=Path)
    parser.add_argument("--disk-budget-receipt", type=Path)
    parser.add_argument("--emit-disk-preflight", type=Path)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.emit_disk_preflight is not None:
        if args.emberd_schedule_receipt is None or args.output is None or args.seed is None:
            parser.error("--emit-disk-preflight requires --emberd-schedule-receipt --output --seed")
        root = Path(__file__).resolve().parents[2]
        schedule_binding = _validate_schedule_receipt(args.emberd_schedule_receipt)
        result = write_disk_preflight(
            path=args.emit_disk_preflight,
            source_closure_sha256=_source_closure(root),
            emberd_schedule_receipt_sha256=str(schedule_binding["sha256"]),
            dispatch_sha256=_dispatch_sha256(output=args.output, seed=args.seed),
            dispatch=dict(_dispatch_binding(output=args.output, seed=args.seed)["payload"]),
        )
        print(json.dumps(result, sort_keys=True))
        return 0
    required = {
        "--receipt": args.receipt,
        "--shards-root": args.shards_root,
        "--tokenizer": args.tokenizer,
        "--reference-checkpoint-manifest": args.reference_checkpoint_manifest,
        "--emberd-schedule-receipt": args.emberd_schedule_receipt,
        "--disk-budget-receipt": args.disk_budget_receipt,
        "--seed": args.seed,
        "--output": args.output,
    }
    missing = [flag for flag, value in required.items() if value is None]
    if missing:
        parser.error(f"screen execution requires {' '.join(missing)}")
    try:
        print(json.dumps(run_screen(
            receipt_path=args.receipt,
            shards_root=args.shards_root,
            tokenizer_path=args.tokenizer,
            reference_checkpoint_manifest=args.reference_checkpoint_manifest,
            emberd_schedule_receipt=args.emberd_schedule_receipt,
            disk_budget_receipt=args.disk_budget_receipt,
            output=args.output,
            seed=args.seed,
        ), sort_keys=True))
    except Exception as error:
        parser.error(str(error))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())