# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Execute and seal the exact host-commit dry run for issue #675."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
import time
from pathlib import Path

import torch

from q2_event_inputs import admit_event_inputs
from q2_host_commit_probe import HostCommitProbe
from q2_host_commit_simulation import validate_host_commit_measurement
from q2_rung2_runtime import build_rung2_model


class MeasuredDryRunRefusal(ValueError):
    """Named refusal before a dispatch host-commit receipt exists."""


def _refuse(code: str) -> None:
    raise MeasuredDryRunRefusal(code)


_CUDA_CHUNK_BYTES = 64 * 1024**2


def _unique_model_storage_bytes(model: torch.nn.Module) -> int:
    seen: set[tuple[str, int | None, int]] = set()
    total = 0
    for value in model.state_dict().values():
        key = (value.device.type, value.device.index, value.data_ptr())
        if key not in seen:
            seen.add(key)
            total += value.numel() * value.element_size()
    if total <= 0:
        _refuse("DRY_RUN_ACTIVATION_BOUND_INVALID")
    return total


def _activation_offload_bounds(
    config: dict[str, object], *, intermediate_size: int, model_bytes: int
) -> tuple[int, int]:
    try:
        model = config["model"]
        if not isinstance(model, dict):
            raise TypeError
        seq, hidden, layers, heads = (
            int(model[key]) for key in ("seq", "hidden", "layers", "heads")
        )
    except (KeyError, TypeError, ValueError):
        _refuse("DRY_RUN_ACTIVATION_BOUND_INVALID")
    if any(
        value <= 0
        for value in (seq, hidden, layers, heads, intermediate_size, model_bytes)
    ):
        _refuse("DRY_RUN_ACTIVATION_BOUND_INVALID")
    per_layer = 2 * seq * (
        16 * hidden + 6 * intermediate_size + 2 * heads * seq
    )
    host_offload = model_bytes + layers * per_layer
    target_gradient = 4 * hidden * intermediate_size
    cuda_scratch = per_layer + target_gradient + 512 * 1024**2
    return host_offload, cuda_scratch


def _touched_cpu_reserve(byte_count: int) -> list[torch.Tensor]:
    held = []
    remaining = byte_count
    while remaining:
        size = min(remaining, 256 * 1024**2)
        held.append(torch.zeros(size, dtype=torch.uint8, device="cpu"))
        remaining -= size
    return held


def _cuda_allocability_probe(
    *, config: dict[str, object], intermediate_size: int, model_bytes: int,
    run_id: str, source_commit: str, config_sha256: str,
    measurement_tool_sha256: str, checkpoint_manifest_sha256: str,
) -> dict[str, object]:
    _host_bytes, required = _activation_offload_bounds(
        config, intermediate_size=intermediate_size, model_bytes=model_bytes
    )
    free_before, total = torch.cuda.mem_get_info()
    held = []
    try:
        remaining = required
        while remaining:
            size = min(remaining, _CUDA_CHUNK_BYTES)
            value = torch.empty(size, dtype=torch.uint8, device="cuda")
            value.zero_()
            held.append(value)
            remaining -= size
        torch.cuda.synchronize()
        free_after, _ = torch.cuda.mem_get_info()
    except (torch.OutOfMemoryError, RuntimeError):
        _refuse("DRY_RUN_CUDA_NOT_ALLOCATABLE")
    finally:
        held.clear()
        torch.cuda.empty_cache()
    observed_at_ms = time.time_ns() // 1_000_000
    device_index = torch.cuda.current_device()
    receipt: dict[str, object] = {
        "schema": "q2-cuda-allocability-receipt-v1",
        "job_id": run_id,
        "source_commit": source_commit,
        "config_sha256": config_sha256,
        "measurement_tool_sha256": measurement_tool_sha256,
        "checkpoint_manifest_sha256": checkpoint_manifest_sha256,
        "intermediate_size": intermediate_size,
        "observed_at_ms": observed_at_ms,
        "expires_at_ms": observed_at_ms + 300_000,
        "device_index": device_index,
        "device_name": torch.cuda.get_device_name(device_index),
        "model_bytes": model_bytes,
        "required_scratch_bytes": required,
        "chunk_bytes": _CUDA_CHUNK_BYTES,
        "free_before_bytes": free_before,
        "free_after_bytes": free_after,
        "total_bytes": total,
        "result": "ALLOCATABLE",
        "event_credit": False,
        "scientific_credit": False,
        "no_new_parallel_authority": True,
    }
    receipt["receipt_sha256"] = hashlib.sha256(
        json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return receipt


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path: Path, value: object) -> None:
    if path.exists(): _refuse("DRY_RUN_OUTPUT_ALREADY_EXISTS")
    raw=json.dumps(value,sort_keys=True,separators=(",", ":")).encode("utf-8")
    fd,temporary=tempfile.mkstemp(prefix=f".{path.name}.",suffix=".tmp",dir=path.parent)
    try:
        with os.fdopen(fd,"wb") as handle: handle.write(raw); handle.flush(); os.fsync(handle.fileno())
        os.replace(temporary,path)
    except Exception:
        try: os.unlink(temporary)
        except OSError: pass
        raise


def _stage_json(path: Path, value: object) -> Path:
    raw=json.dumps(value,sort_keys=True,separators=(",", ":")).encode("utf-8")
    fd,temporary=tempfile.mkstemp(prefix=f".{path.name}.",suffix=".tmp",dir=path.parent)
    with os.fdopen(fd,"wb") as handle:
        handle.write(raw); handle.flush(); os.fsync(handle.fileno())
    return Path(temporary)


def _publish_bundle(staged: list[tuple[Path, Path]]) -> None:
    created=[]
    try:
        for temporary,target in staged:
            os.link(temporary,target)
            created.append(target)
            temporary.unlink()
    except Exception:
        for target in reversed(created):
            try: target.unlink()
            except OSError: pass
        for temporary,_target in staged:
            try: temporary.unlink()
            except OSError: pass
        raise


def _runtime_host_snapshots(
    model: torch.nn.Module,
) -> tuple[dict[str, torch.Tensor], list[torch.Tensor]]:
    baseline = {
        key: value.detach().to(device="cpu").contiguous().clone()
        for key, value in model.state_dict().items()
    }
    qat = [
        module.weight.detach().to(device="cpu").contiguous().clone()
        for module in model.modules()
        if isinstance(module, torch.nn.Linear)
    ]
    return baseline, qat


def _bound_config_path(root: Path, checkpoint_manifest_path: Path) -> Path:
    try:
        manifest=json.loads(checkpoint_manifest_path.read_text(encoding="utf-8"))
        logical=manifest["files"]["config"]["logical_path"]
        if not isinstance(logical,str) or not logical or Path(logical).is_absolute() or ".." in Path(logical).parts:
            _refuse("DRY_RUN_CONFIG_BINDING_INVALID")
        path=(root/logical).resolve(strict=True)
        if not path.is_relative_to(root) or not path.is_file() or path.is_symlink(): _refuse("DRY_RUN_CONFIG_BINDING_INVALID")
        return path
    except MeasuredDryRunRefusal: raise
    except (OSError,UnicodeError,json.JSONDecodeError,KeyError,TypeError): _refuse("DRY_RUN_CONFIG_BINDING_INVALID")


def run_measured_dry_run(
    *, run_id: str, source_commit: str, custody_root: Path,
    checkpoint_manifest_path: Path, batch_manifest_path: Path,
    producer_path: Path, trace_path: Path, receipt_path: Path,
    cuda_receipt_path: Path,
) -> dict[str, object]:
    """Retain each real phase allocation and measure cumulative commit high-water."""

    root=Path(custody_root).resolve(strict=True)
    output_paths=[]
    for candidate in (trace_path,receipt_path,cuda_receipt_path):
        raw=Path(candidate)
        output_paths.append(raw.parent.resolve(strict=True)/raw.name)
    if len(set(output_paths)) != 3 or any(path.exists() for path in output_paths):
        _refuse("DRY_RUN_OUTPUT_ALREADY_EXISTS")
    trace_path,receipt_path,cuda_receipt_path=output_paths
    checkpoint_manifest_path=Path(checkpoint_manifest_path).resolve(strict=True)
    batch_manifest_path=Path(batch_manifest_path).resolve(strict=True)
    producer_path=Path(producer_path).resolve(strict=True)
    config_path=_bound_config_path(root,checkpoint_manifest_path)
    bindings={
        "measurement_tool_sha256":_sha(Path(__file__).resolve()),
        "config_sha256":_sha(config_path),
        "checkpoint_manifest_sha256":_sha(checkpoint_manifest_path),
        "batch_manifest_sha256":_sha(batch_manifest_path),
        "producer_sha256":_sha(producer_path),
    }
    probe=HostCommitProbe(job_id=run_id,source_commit=source_commit,bindings=bindings)
    held=[]
    try:
        probe.begin_phase("model_reconstruction")
        inputs=admit_event_inputs(custody_root=root,checkpoint_manifest_path=checkpoint_manifest_path,batch_manifest_path=batch_manifest_path,expected_source_commit=source_commit,expected_run_id=run_id)
        files=inputs["files"]
        config=json.loads(files["config"].read_text(encoding="utf-8"))
        model,_vocab,_hidden,_mtp=build_rung2_model(config,intermediate_size=inputs["intermediate_size"],device="cpu")
        grown=torch.load(files["grown_model"],map_location="cpu",weights_only=True)
        model.load_state_dict(grown,strict=True); held.extend([inputs,config,model,grown]); probe.sample(); probe.end_phase()

        probe.begin_phase("optimizer_momentum")
        optimizer=torch.load(files["seed_optimizer"],map_location="cpu",weights_only=True)
        momentum=torch.load(files["pre_momentum"],map_location="cpu",weights_only=True)
        held.extend([optimizer,momentum]); probe.sample(); probe.end_phase()

        probe.begin_phase("frozen_batch")
        frozen=[]
        for row in inputs["microsteps"]:
            frozen.extend([row["x"].clone(),row["y0"].clone(),*[value.clone() for value in row["y_mtp"]]])
        held.append(frozen); probe.sample(); probe.end_phase()

        probe.begin_phase("capture_staging")
        runtime_integrity_baseline,runtime_qat_saved_weights=_runtime_host_snapshots(model)
        held.extend([runtime_integrity_baseline,runtime_qat_saved_weights]); probe.sample()
        target=model.get_parameter(inputs["target_name"])
        capture_staging=[target.detach().cpu().float().clone() for _ in range(6)]
        non_target={name:value.detach().cpu().clone() for name,value in model.state_dict().items() if name!=inputs["target_name"]}
        held.extend([capture_staging,non_target]); probe.sample()
        model_bytes=_unique_model_storage_bytes(model)
        activation_bytes,_scratch_bytes=_activation_offload_bounds(
            config,
            intermediate_size=inputs["intermediate_size"],
            model_bytes=model_bytes,
        )
        held.append(_touched_cpu_reserve(activation_bytes)); probe.sample(); probe.end_phase()

        probe.begin_phase("python_cuda_host_overhead")
        if not torch.cuda.is_available(): _refuse("DRY_RUN_CUDA_UNAVAILABLE")
        model.to("cuda"); torch.cuda.synchronize(); probe.sample()
        cuda_receipt=_cuda_allocability_probe(
            config=config,
            intermediate_size=inputs["intermediate_size"],
            model_bytes=model_bytes,
            run_id=run_id,
            source_commit=source_commit,
            config_sha256=bindings["config_sha256"],
            measurement_tool_sha256=bindings["measurement_tool_sha256"],
            checkpoint_manifest_sha256=bindings["checkpoint_manifest_sha256"],
        )
        held.append(cuda_receipt)
        probe.sample(); probe.end_phase()
        trace=probe.finish(exit_code=0)
    except MeasuredDryRunRefusal: raise
    except Exception: _refuse("DRY_RUN_PHASE_FAILED")
    staged=[]
    try:
        staged_trace=_stage_json(trace_path,trace); staged.append((staged_trace,trace_path))
        receipt=validate_host_commit_measurement(staged_trace)
        staged_receipt=_stage_json(receipt_path,receipt); staged.append((staged_receipt,receipt_path))
        staged_cuda=_stage_json(cuda_receipt_path,cuda_receipt); staged.append((staged_cuda,cuda_receipt_path))
        _publish_bundle(staged)
    except MeasuredDryRunRefusal: raise
    except Exception: _refuse("DRY_RUN_PUBLICATION_FAILED")
    return receipt


def main() -> int:
    parser=argparse.ArgumentParser()
    for name in ("run-id","source-commit","custody-root","checkpoint-manifest","batch-manifest","producer","trace","receipt","cuda-receipt"):
        parser.add_argument(f"--{name}",required=True)
    args=parser.parse_args()
    receipt=run_measured_dry_run(run_id=args.run_id,source_commit=args.source_commit,custody_root=Path(args.custody_root),checkpoint_manifest_path=Path(args.checkpoint_manifest),batch_manifest_path=Path(args.batch_manifest),producer_path=Path(args.producer),trace_path=Path(args.trace),receipt_path=Path(args.receipt),cuda_receipt_path=Path(args.cuda_receipt))
    print(json.dumps({"schema":"q2-measured-dry-run-result-v1","receipt_sha256":receipt["receipt_sha256"],"event_credit":False},sort_keys=True))
    return 0


if __name__=="__main__": raise SystemExit(main())
