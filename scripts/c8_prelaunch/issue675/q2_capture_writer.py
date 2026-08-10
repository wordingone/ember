# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Atomic issue #675 target-tensor capture writer.

The GPU producer supplies already-computed tensors and paired losses.  This
module validates the target-only counterfactual boundary, persists every raw
operand, and writes the self-hashed manifest last.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping

import torch


_BINDING_KEYS = {
    "source_sha256",
    "config_sha256",
    "checkpoint_sha256",
    "optimizer_sha256",
    "momentum_sha256",
    "batch_sha256",
    "b3_receipt_sha256",
    "replay_sha256",
    "threshold_sha256",
    "verifier_sha256",
}
_ARTIFACT_NAMES = {
    "pre": "pre",
    "reset_post": "reset-post",
    "transplant_post": "transplant-post",
    "gradient": "gradient",
    "reset_momentum": "reset-momentum",
    "transplant_momentum": "transplant-momentum",
}
_MAX_TEMP_BYTES = 4 * 1024**3


class CaptureWriteRefusal(ValueError):
    """Named refusal emitted before a selectable capture manifest exists."""


def _refuse(code: str) -> None:
    raise CaptureWriteRefusal(code)


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_dispatch(path: Path, root: Path) -> tuple[dict[str, object], bytes]:
    try:
        canonical = path.resolve(strict=True)
        if canonical.parent != root:
            _refuse("DISPATCH_PREFLIGHT_OUTSIDE_CUSTODY")
        raw = canonical.read_bytes()
        value = json.loads(raw)
    except CaptureWriteRefusal:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        _refuse("DISPATCH_PREFLIGHT_MALFORMED")
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != "ember-lab-dispatch-preflight-v1"
        or value.get("result") != "PREFLIGHT_PASSED"
        or not isinstance(value.get("job_id"), str)
        or not value["job_id"]
        or not isinstance(value.get("source_commit"), str)
        or re.fullmatch(r"[0-9a-f]{40}", value["source_commit"]) is None
        or not isinstance(value.get("dispatch_manifest_sha256"), str)
        or re.fullmatch(r"[0-9a-f]{64}", value["dispatch_manifest_sha256"]) is None
    ):
        _refuse("DISPATCH_PREFLIGHT_NOT_GREEN")
    return value, raw


def _tensor(value: object, name: str) -> torch.Tensor:
    if (
        not isinstance(value, torch.Tensor)
        or value.dtype != torch.float32
        or value.numel() == 0
        or not bool(torch.isfinite(value).all())
    ):
        _refuse(f"{name.upper()}_TENSOR_INVALID")
    return value.detach().to(device="cpu").contiguous()


def _target_tensor(value: object, name: str) -> torch.Tensor:
    if (
        not isinstance(value, torch.Tensor)
        or value.dtype not in {torch.float32, torch.bfloat16, torch.float16}
        or value.numel() == 0
        or not bool(torch.isfinite(value).all())
    ):
        _refuse(f"{name.upper()}_TENSOR_INVALID")
    return value.detach().to(device="cpu").contiguous()


def _state_tensor(value: object, name: str) -> torch.Tensor:
    if (
        not isinstance(value, torch.Tensor)
        or value.numel() == 0
        or value.layout != torch.strided
        or not bool(torch.isfinite(value).all())
    ):
        _refuse(f"{name.upper()}_TENSOR_INVALID")
    return value.detach().to(device="cpu").contiguous()


def _tensor_content_sha(name: str, tensor: torch.Tensor) -> str:
    dtype = str(tensor.dtype).removeprefix("torch.")
    identity = _canonical(
        {"name": name, "dtype": dtype, "shape": list(tensor.shape)}
    )
    raw = tensor.reshape(-1).view(torch.uint8).numpy().tobytes()
    return _sha(identity + b"\0" + raw)


def _same_tensor(left: torch.Tensor, right: torch.Tensor) -> bool:
    return (
        left.dtype == right.dtype
        and tuple(left.shape) == tuple(right.shape)
        and torch.equal(left, right)
    )


def _replay_loss_twice(
    loss_replay: Callable[[torch.Tensor, dict[str, torch.Tensor]], float],
    target: torch.Tensor,
    non_target: Mapping[str, torch.Tensor],
) -> float:
    results: list[float] = []
    for _ in range(2):
        target_input = target.clone()
        non_target_input = {name: value.clone() for name, value in non_target.items()}
        target_before = target_input.clone()
        non_target_before = {
            name: value.clone() for name, value in non_target_input.items()
        }
        try:
            result = loss_replay(target_input, non_target_input)
        except Exception:
            _refuse("PAIRED_LOSS_REPLAY_FAILED")
        if (
            not _same_tensor(target_input, target_before)
            or set(non_target_input) != set(non_target_before)
            or any(
                not isinstance(non_target_input[name], torch.Tensor)
                or not _same_tensor(non_target_input[name], non_target_before[name])
                for name in non_target_before
            )
        ):
            _refuse("PAIRED_LOSS_REPLAY_MUTATED_STATE")
        if (
            not isinstance(result, (int, float))
            or isinstance(result, bool)
            or not math.isfinite(float(result))
        ):
            _refuse("PAIRED_LOSS_NONFINITE")
        results.append(float(result))
    if results[0] != results[1]:
        _refuse("PAIRED_LOSS_REPLAY_NONDETERMINISTIC")
    return results[0]


def _atomic_bytes(path: Path, payload: bytes) -> None:
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _atomic_torch(path: Path, value: object) -> None:
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    os.close(fd)
    try:
        torch.save(value, temporary)
        if os.path.getsize(temporary) > _MAX_TEMP_BYTES:
            _refuse("CAPTURE_TEMP_EXCEEDS_4GIB")
        with open(temporary, "rb+") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def write_capture(
    *,
    custody_root: Path,
    run_id: str,
    dispatch_receipt_path: Path,
    binding_files: Mapping[str, Path],
    target_name: str,
    pre: torch.Tensor,
    reset_post: torch.Tensor,
    transplant_post: torch.Tensor,
    gradient: torch.Tensor,
    reset_momentum: torch.Tensor,
    transplant_momentum: torch.Tensor,
    non_target_pre: Mapping[str, torch.Tensor],
    non_target_reset: Mapping[str, torch.Tensor],
    non_target_transplant: Mapping[str, torch.Tensor],
    loss_replay: Callable[[torch.Tensor, dict[str, torch.Tensor]], float],
    learning_rate: float,
    optimizer_scale: float,
) -> Path:
    """Validate and atomically persist one target-only actual-update capture."""

    root = Path(custody_root).resolve(strict=True)
    if not root.is_dir() or re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", run_id) is None:
        _refuse("CAPTURE_CUSTODY_OR_RUN_ID_INVALID")
    manifest_path = root / "capture-manifest.json"
    if manifest_path.exists():
        _refuse("CAPTURE_RUN_ALREADY_EXISTS")

    dispatch, dispatch_raw = _read_dispatch(Path(dispatch_receipt_path), root)
    if dispatch["job_id"] != run_id:
        _refuse("CAPTURE_RUN_DISPATCH_MISMATCH")

    if set(binding_files) != _BINDING_KEYS:
        _refuse("CAPTURE_BINDING_SCHEMA_INVALID")
    bindings: dict[str, str] = {}
    logical_bindings: dict[str, str] = {}
    seen_paths: set[Path] = set()
    for key in sorted(_BINDING_KEYS):
        try:
            path = Path(binding_files[key]).resolve(strict=True)
        except OSError:
            _refuse("CAPTURE_BINDING_UNAVAILABLE")
        if path.parent != root or path in seen_paths:
            _refuse("CAPTURE_BINDING_OUTSIDE_OR_DUPLICATE")
        seen_paths.add(path)
        bindings[key] = _sha(path.read_bytes())
        logical_bindings[key] = path.name

    tensors = {
        "pre": _target_tensor(pre, "pre"),
        "reset_post": _target_tensor(reset_post, "reset_post"),
        "transplant_post": _target_tensor(transplant_post, "transplant_post"),
        "gradient": _tensor(gradient, "gradient"),
        "reset_momentum": _tensor(reset_momentum, "reset_momentum"),
        "transplant_momentum": _tensor(transplant_momentum, "transplant_momentum"),
    }
    target_shape = tuple(tensors["pre"].shape)
    if any(tuple(value.shape) != target_shape for value in tensors.values()):
        _refuse("CAPTURE_TARGET_TENSOR_SHAPE_MISMATCH")
    if any(
        tensors[key].dtype != tensors["pre"].dtype
        for key in ("reset_post", "transplant_post")
    ):
        _refuse("CAPTURE_TARGET_TENSOR_DTYPE_MISMATCH")
    if bool(torch.count_nonzero(tensors["reset_momentum"])):
        _refuse("RESET_MOMENTUM_NOT_ZERO")
    if not bool(torch.count_nonzero(tensors["transplant_momentum"])):
        _refuse("TRANSPLANT_MOMENTUM_ZERO")
    if torch.equal(tensors["reset_post"] - tensors["pre"], tensors["transplant_post"] - tensors["pre"]):
        _refuse("ZERO_UPDATE_DIFFERENCE")

    if not target_name or "\\" in target_name or "/" in target_name or ":" in target_name:
        _refuse("CAPTURE_TARGET_NAME_INVALID")
    if not callable(loss_replay):
        _refuse("PAIRED_LOSS_REPLAY_INVALID")
    if not math.isfinite(float(learning_rate)) or learning_rate <= 0:
        _refuse("LEARNING_RATE_INVALID")
    if not math.isfinite(float(optimizer_scale)) or optimizer_scale <= 0:
        _refuse("OPTIMIZER_SCALE_INVALID")

    if not non_target_pre or set(non_target_pre) != set(non_target_reset) or set(non_target_pre) != set(non_target_transplant):
        _refuse("NON_TARGET_MANIFEST_INCOMPLETE")
    non_target_entries = []
    replay_non_target: dict[str, torch.Tensor] = {}
    for name in sorted(non_target_pre):
        if not name or "\\" in name or "/" in name or ":" in name:
            _refuse("NON_TARGET_NAME_INVALID")
        before = _state_tensor(non_target_pre[name], "non_target_pre")
        reset = _state_tensor(non_target_reset[name], "non_target_reset")
        transplant = _state_tensor(non_target_transplant[name], "non_target_transplant")
        if not _same_tensor(before, reset):
            _refuse("NON_TARGET_DRIFT_RESET")
        if not _same_tensor(before, transplant):
            _refuse("NON_TARGET_DRIFT_TRANSPLANT")
        replay_non_target[name] = before
        non_target_entries.append(
            {
                "name": name,
                "dtype": str(before.dtype).removeprefix("torch."),
                "shape": list(before.shape),
                "sha256": _tensor_content_sha(name, before),
            }
        )

    loss_reset = _replay_loss_twice(
        loss_replay, tensors["reset_post"], replay_non_target
    )
    loss_transplant = _replay_loss_twice(
        loss_replay, tensors["transplant_post"], replay_non_target
    )

    final_tensor_paths = {
        key: root / f"{run_id}-{logical}.pt" for key, logical in _ARTIFACT_NAMES.items()
    }
    non_target_path = root / "non-target-manifest.json"
    non_target_state_path = root / f"{run_id}-non-target-state.pt"
    reserved = [*final_tensor_paths.values(), non_target_path, non_target_state_path]
    if any(path.exists() for path in reserved):
        _refuse("CAPTURE_RUN_ALREADY_EXISTS")

    non_target_payload = _canonical(
        {"schema": "q2-non-target-byte-manifest-v1", "entries": non_target_entries}
    )
    _atomic_bytes(non_target_path, non_target_payload)
    _atomic_torch(non_target_state_path, replay_non_target)
    for key in sorted(final_tensor_paths):
        _atomic_torch(final_tensor_paths[key], tensors[key])

    non_target_state_raw = non_target_state_path.read_bytes()

    artifacts = {}
    for key in sorted(final_tensor_paths):
        path = final_tensor_paths[key]
        raw = path.read_bytes()
        artifacts[key] = {
            "logical_name": path.name,
            "sha256": _sha(raw),
            "bytes": len(raw),
            "dtype": str(tensors[key].dtype).removeprefix("torch."),
            "shape": list(tensors[key].shape),
        }

    manifest: dict[str, object] = {
        "schema": "q2-actual-update-capture-v1",
        "issue": 675,
        "scope": "TARGET_TENSOR_COUNTERFACTUAL",
        "run_id": run_id,
        "event_captured_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source_commit": dispatch["source_commit"],
        "dispatch": {
            "job_id": dispatch["job_id"],
            "manifest_sha256": dispatch["dispatch_manifest_sha256"],
            "preflight_receipt_sha256": _sha(dispatch_raw),
        },
        "bindings": bindings,
        "binding_files": logical_bindings,
        "target": {
            "name": target_name,
            "dtype": str(tensors["pre"].dtype).removeprefix("torch."),
            "shape": list(target_shape),
            "mn": tensors["pre"].numel(),
        },
        "artifacts": artifacts,
        "non_target_manifest": {
            "logical_name": non_target_path.name,
            "bytes": len(non_target_payload),
            "entry_count": len(non_target_entries),
            "sha256": _sha(non_target_payload),
            "state_logical_name": non_target_state_path.name,
            "state_bytes": len(non_target_state_raw),
            "state_sha256": _sha(non_target_state_raw),
            "byte_identical_reset": True,
            "byte_identical_transplant": True,
        },
        "optimizer": {
            "name": "Muon",
            "learning_rate": float(learning_rate),
            "scale": float(optimizer_scale),
            "reset_momentum_exact_zero": True,
            "transplant_momentum_nonzero": True,
        },
        "paired_losses": {
            "reset": float(loss_reset),
            "transplant": float(loss_transplant),
            "finite": True,
            "same_frozen_batch": True,
            "non_target_state_reused": True,
            "replay_count_per_arm": 2,
            "deterministic": True,
            "replay_sha256": bindings["replay_sha256"],
        },
        "credits": {
            "whole_step": False,
            "null_confirmed": False,
            "material_loss_bridge": False,
            "training": False,
            "checkpoint": False,
            "capability": False,
            "sufficient_pretraining": False,
        },
        "no_new_parallel_authority": True,
        "verdict": "CAPTURED_NOT_ADJUDICATED",
    }
    manifest["manifest_sha256"] = _sha(_canonical(manifest))
    _atomic_bytes(manifest_path, _canonical(manifest))
    return manifest_path
