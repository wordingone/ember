# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Fail-closed byte consumer for an issue #675 target-tensor capture.

This scratch implementation deliberately performs no GPU/model work.  It
reopens the producer bytes and Ember Lab preflight receipt, derives their
identities, and returns only a path-free authority block suitable for the
pure Q2 evaluator.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

import torch


_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_LOGICAL_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_BINDING_KEYS = {
    "source_sha256",
    "config_sha256",
    "checkpoint_sha256",
    "optimizer_sha256",
    "momentum_sha256",
    "batch_sha256",
    "replay_sha256",
    "threshold_sha256",
    "verifier_sha256",
}
_ARTIFACT_KEYS = {
    "pre",
    "reset_post",
    "transplant_post",
    "gradient",
    "reset_momentum",
    "transplant_momentum",
}
_CREDIT_KEYS = {
    "whole_step",
    "null_confirmed",
    "material_loss_bridge",
    "training",
    "checkpoint",
    "capability",
    "sufficient_pretraining",
}
_MANIFEST_KEYS = {
    "schema",
    "issue",
    "scope",
    "run_id",
    "event_captured_at",
    "source_commit",
    "dispatch",
    "bindings",
    "binding_files",
    "target",
    "artifacts",
    "non_target_manifest",
    "optimizer",
    "paired_losses",
    "credits",
    "no_new_parallel_authority",
    "verdict",
    "manifest_sha256",
}
_OPERATIONAL_KEYS = {
    "schema",
    "ember_lab_identity",
    "job_id",
    "identity_sha256",
    "resource_lease",
    "state",
    "pid",
    "executable_identity",
    "restart_policy",
    "exit_code",
    "logs",
    "events",
    "outage_events",
    "scientific_capability_evidence",
}


class CaptureRefusal(ValueError):
    """A named, path-free capture admission refusal."""


def _refuse(code: str) -> None:
    raise CaptureRefusal(code)


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _tensor_content_sha(name: str, tensor: torch.Tensor) -> str:
    dtype = str(tensor.dtype).removeprefix("torch.")
    identity = _canonical({"name": name, "dtype": dtype, "shape": list(tensor.shape)})
    raw = tensor.detach().cpu().contiguous().reshape(-1).view(torch.uint8).numpy().tobytes()
    return _sha_bytes(identity + b"\0" + raw)


def _require_sha(value: object, code: str) -> str:
    if not isinstance(value, str) or _SHA_RE.fullmatch(value) is None:
        _refuse(code)
    return value


def _logical_file(root: Path, value: object) -> Path:
    if not isinstance(value, str) or _LOGICAL_RE.fullmatch(value) is None:
        _refuse("CAPTURE_LOGICAL_NAME_INVALID")
    candidate = root / value
    try:
        canonical = candidate.resolve(strict=True)
    except OSError:
        _refuse("CAPTURE_ARTIFACT_UNAVAILABLE")
    if canonical.parent != root:
        _refuse("CAPTURE_LOGICAL_NAME_INVALID")
    return canonical


def _read_json(path: Path, code: str) -> tuple[dict[str, Any], bytes]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        _refuse(code)
    if not isinstance(value, dict):
        _refuse(code)
    return value, raw


def load_capture(
    manifest_path: Path,
    dispatch_receipt_path: Path,
    terminal_receipt_path: Path,
) -> dict[str, object]:
    """Reopen and validate a capture before any Q2 adjudication.

    All host paths are inputs only.  The returned mapping contains hashes,
    logical identities, and closed claim boundaries, never host paths.
    """

    manifest_path = Path(manifest_path).resolve(strict=True)
    root = manifest_path.parent
    manifest, _ = _read_json(manifest_path, "CAPTURE_MANIFEST_MALFORMED")
    if set(manifest) != _MANIFEST_KEYS:
        _refuse("CAPTURE_MANIFEST_SCHEMA_INVALID")

    claimed_manifest_sha = _require_sha(
        manifest.get("manifest_sha256"), "CAPTURE_MANIFEST_HASH_INVALID"
    )
    unhashed = dict(manifest)
    unhashed.pop("manifest_sha256")
    if _sha_bytes(_canonical(unhashed)) != claimed_manifest_sha:
        _refuse("CAPTURE_MANIFEST_HASH_MISMATCH")

    if (
        manifest.get("schema") != "q2-actual-update-capture-v1"
        or manifest.get("issue") != 675
        or manifest.get("scope") != "TARGET_TENSOR_COUNTERFACTUAL"
        or manifest.get("verdict") != "CAPTURED_NOT_ADJUDICATED"
        or manifest.get("no_new_parallel_authority") is not True
    ):
        _refuse("CAPTURE_MANIFEST_SCHEMA_INVALID")

    source_commit = manifest.get("source_commit")
    if not isinstance(source_commit, str) or re.fullmatch(r"[0-9a-f]{40}", source_commit) is None:
        _refuse("CAPTURE_SOURCE_COMMIT_INVALID")

    dispatch_receipt_path = Path(dispatch_receipt_path).resolve(strict=True)
    if dispatch_receipt_path.parent != root:
        _refuse("DISPATCH_PREFLIGHT_OUTSIDE_CUSTODY")
    dispatch_receipt, dispatch_raw = _read_json(
        dispatch_receipt_path, "DISPATCH_PREFLIGHT_MALFORMED"
    )
    dispatch = manifest.get("dispatch")
    if not isinstance(dispatch, dict) or set(dispatch) != {
        "job_id",
        "manifest_sha256",
        "preflight_receipt_sha256",
    }:
        _refuse("CAPTURE_DISPATCH_BINDING_INVALID")
    if _sha_bytes(dispatch_raw) != _require_sha(
        dispatch.get("preflight_receipt_sha256"), "DISPATCH_PREFLIGHT_HASH_INVALID"
    ):
        _refuse("DISPATCH_PREFLIGHT_HASH_MISMATCH")
    if (
        dispatch_receipt.get("schema_version") != "ember-lab-dispatch-preflight-v1"
        or dispatch_receipt.get("result") != "PREFLIGHT_PASSED"
    ):
        _refuse("DISPATCH_PREFLIGHT_NOT_GREEN")
    lab_identity = dispatch_receipt.get("ember_lab_identity")
    if (
        not isinstance(lab_identity, dict)
        or set(lab_identity) != {"binary_sha256", "source_sha256"}
        or any(
            _SHA_RE.fullmatch(str(lab_identity.get(key))) is None
            for key in ("binary_sha256", "source_sha256")
        )
    ):
        _refuse("DISPATCH_PREFLIGHT_LAB_IDENTITY_INVALID")
    if (
        dispatch_receipt.get("job_id") != dispatch.get("job_id")
        or dispatch_receipt.get("source_commit") != source_commit
        or dispatch_receipt.get("dispatch_manifest_sha256")
        != dispatch.get("manifest_sha256")
    ):
        _refuse("DISPATCH_PREFLIGHT_IDENTITY_MISMATCH")

    try:
        terminal_receipt_path = Path(terminal_receipt_path).resolve(strict=True)
    except OSError:
        _refuse("TERMINAL_RECEIPT_UNAVAILABLE")
    if terminal_receipt_path.parent != root:
        _refuse("TERMINAL_RECEIPT_OUTSIDE_CUSTODY")
    terminal_receipt, terminal_raw = _read_json(
        terminal_receipt_path, "TERMINAL_RECEIPT_MALFORMED"
    )
    terminal_sha = _sha_bytes(terminal_raw)
    if terminal_receipt_path.name != f"{terminal_sha}.json":
        _refuse("TERMINAL_RECEIPT_CONTENT_ADDRESS_MISMATCH")
    terminal_logs = terminal_receipt.get("logs")
    if (
        set(terminal_receipt) != _OPERATIONAL_KEYS
        or terminal_receipt.get("schema") != "ember-lab-operational-receipt-v1"
        or terminal_receipt.get("job_id") != dispatch.get("job_id")
        or terminal_receipt.get("identity_sha256") != dispatch.get("manifest_sha256")
        or terminal_receipt.get("state") != "exited"
        or terminal_receipt.get("exit_code") != 0
        or terminal_receipt.get("scientific_capability_evidence") is not False
        or terminal_receipt.get("ember_lab_identity")
        != dispatch_receipt.get("ember_lab_identity")
        or not isinstance(terminal_receipt.get("pid"), int)
        or isinstance(terminal_receipt.get("pid"), bool)
        or terminal_receipt["pid"] <= 0
        or not isinstance(terminal_logs, dict)
        or set(terminal_logs) != {"stdout", "stderr"}
        or any(
            not isinstance(terminal_logs[name], dict)
            or _SHA_RE.fullmatch(str(terminal_logs[name].get("sha256"))) is None
            for name in ("stdout", "stderr")
        )
    ):
        _refuse("TERMINAL_RECEIPT_NOT_SUCCESSFUL")

    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != _ARTIFACT_KEYS:
        _refuse("CAPTURE_ARTIFACT_SCHEMA_INVALID")
    artifact_hashes: dict[str, str] = {}
    artifact_tensors: dict[str, torch.Tensor] = {}
    for key in sorted(_ARTIFACT_KEYS):
        artifact = artifacts[key]
        if not isinstance(artifact, dict) or set(artifact) != {
            "logical_name",
            "sha256",
            "bytes",
            "dtype",
            "shape",
        }:
            _refuse("CAPTURE_ARTIFACT_SCHEMA_INVALID")
        path = _logical_file(root, artifact.get("logical_name"))
        raw = path.read_bytes()
        expected = _require_sha(artifact.get("sha256"), "CAPTURE_ARTIFACT_HASH_INVALID")
        if _sha_bytes(raw) != expected or len(raw) != artifact.get("bytes"):
            _refuse("CAPTURE_ARTIFACT_HASH_MISMATCH")
        if artifact.get("dtype") != "float32" or not _valid_shape(artifact.get("shape")):
            _refuse("CAPTURE_ARTIFACT_TENSOR_IDENTITY_INVALID")
        try:
            tensor = torch.load(path, map_location="cpu", weights_only=True)
        except Exception:
            _refuse("CAPTURE_ARTIFACT_TENSOR_MALFORMED")
        if (
            not isinstance(tensor, torch.Tensor)
            or tensor.dtype != torch.float32
            or list(tensor.shape) != artifact["shape"]
            or not bool(torch.isfinite(tensor).all())
        ):
            _refuse("CAPTURE_ARTIFACT_TENSOR_IDENTITY_MISMATCH")
        artifact_hashes[key] = expected
        artifact_tensors[key] = tensor

    bindings = manifest.get("bindings")
    binding_files = manifest.get("binding_files")
    if (
        not isinstance(bindings, dict)
        or set(bindings) != _BINDING_KEYS
        or not isinstance(binding_files, dict)
        or set(binding_files) != _BINDING_KEYS
    ):
        _refuse("CAPTURE_BINDING_SCHEMA_INVALID")
    derived_bindings: dict[str, str] = {}
    seen_binding_paths: set[Path] = set()
    for key in sorted(_BINDING_KEYS):
        path = _logical_file(root, binding_files[key])
        if path in seen_binding_paths:
            _refuse("CAPTURE_BINDING_DUPLICATE")
        seen_binding_paths.add(path)
        actual = _sha_bytes(path.read_bytes())
        if actual != _require_sha(bindings[key], "CAPTURE_BINDING_HASH_INVALID"):
            _refuse("CAPTURE_BINDING_HASH_MISMATCH")
        derived_bindings[key] = actual

    target = manifest.get("target")
    if (
        not isinstance(target, dict)
        or set(target) != {"name", "dtype", "shape", "mn"}
        or target.get("dtype") != "float32"
        or not _valid_shape(target.get("shape"))
        or target.get("mn") != _shape_product(target["shape"])
    ):
        _refuse("CAPTURE_TARGET_IDENTITY_INVALID")
    if any(list(tensor.shape) != target["shape"] for tensor in artifact_tensors.values()):
        _refuse("CAPTURE_TARGET_TENSOR_SHAPE_MISMATCH")
    if bool(torch.count_nonzero(artifact_tensors["reset_momentum"])):
        _refuse("RESET_MOMENTUM_NOT_ZERO")
    if not bool(torch.count_nonzero(artifact_tensors["transplant_momentum"])):
        _refuse("TRANSPLANT_MOMENTUM_ZERO")

    non_target = manifest.get("non_target_manifest")
    if (
        not isinstance(non_target, dict)
        or set(non_target)
        != {
            "logical_name",
            "bytes",
            "entry_count",
            "sha256",
            "state_logical_name",
            "state_bytes",
            "state_sha256",
            "byte_identical_reset",
            "byte_identical_transplant",
        }
        or not isinstance(non_target.get("entry_count"), int)
        or non_target["entry_count"] < 1
        or non_target.get("byte_identical_reset") is not True
        or non_target.get("byte_identical_transplant") is not True
    ):
        _refuse("NON_TARGET_IDENTITY_INVALID")
    non_target_path = _logical_file(root, non_target.get("logical_name"))
    non_target_raw = non_target_path.read_bytes()
    non_target_sha = _require_sha(
        non_target.get("sha256"), "NON_TARGET_MANIFEST_HASH_INVALID"
    )
    if (
        _sha_bytes(non_target_raw) != non_target_sha
        or len(non_target_raw) != non_target.get("bytes")
    ):
        _refuse("NON_TARGET_MANIFEST_HASH_MISMATCH")
    non_target_value, _ = _read_json(
        non_target_path, "NON_TARGET_MANIFEST_MALFORMED"
    )
    if set(non_target_value) != {"schema", "entries"} or non_target_value.get(
        "schema"
    ) != "q2-non-target-byte-manifest-v1":
        _refuse("NON_TARGET_MANIFEST_SCHEMA_INVALID")
    entries = non_target_value.get("entries")
    if not isinstance(entries, list) or len(entries) != non_target["entry_count"]:
        _refuse("NON_TARGET_MANIFEST_SCHEMA_INVALID")
    names: list[str] = []
    for entry in entries:
        if (
            not isinstance(entry, dict)
            or set(entry) != {"name", "dtype", "shape", "sha256"}
            or not isinstance(entry.get("name"), str)
            or _LOGICAL_RE.fullmatch(entry["name"]) is None
            or not isinstance(entry.get("dtype"), str)
            or re.fullmatch(r"[a-z0-9_]+", entry["dtype"]) is None
            or not _valid_state_shape(entry.get("shape"))
        ):
            _refuse("NON_TARGET_MANIFEST_SCHEMA_INVALID")
        _require_sha(entry.get("sha256"), "NON_TARGET_MANIFEST_HASH_INVALID")
        names.append(entry["name"])
    if names != sorted(set(names)):
        _refuse("NON_TARGET_MANIFEST_ORDER_INVALID")

    non_target_state_path = _logical_file(root, non_target.get("state_logical_name"))
    non_target_state_raw = non_target_state_path.read_bytes()
    if (
        len(non_target_state_raw) != non_target.get("state_bytes")
        or _sha_bytes(non_target_state_raw)
        != _require_sha(non_target.get("state_sha256"), "NON_TARGET_STATE_HASH_INVALID")
    ):
        _refuse("NON_TARGET_STATE_HASH_MISMATCH")
    try:
        non_target_state = torch.load(
            non_target_state_path, map_location="cpu", weights_only=True
        )
    except Exception:
        _refuse("NON_TARGET_STATE_MALFORMED")
    if not isinstance(non_target_state, dict) or set(non_target_state) != set(names):
        _refuse("NON_TARGET_STATE_SCHEMA_INVALID")
    entry_by_name = {entry["name"]: entry for entry in entries}
    for name in names:
        tensor = non_target_state[name]
        entry = entry_by_name[name]
        if (
            not isinstance(tensor, torch.Tensor)
            or tensor.layout != torch.strided
            or tensor.numel() == 0
            or not bool(torch.isfinite(tensor).all())
            or str(tensor.dtype).removeprefix("torch.") != entry["dtype"]
            or list(tensor.shape) != entry["shape"]
            or _tensor_content_sha(name, tensor) != entry["sha256"]
        ):
            _refuse("NON_TARGET_STATE_IDENTITY_MISMATCH")

    optimizer = manifest.get("optimizer")
    if (
        not isinstance(optimizer, dict)
        or optimizer.get("name") != "Muon"
        or not _positive_finite(optimizer.get("learning_rate"))
        or not _positive_finite(optimizer.get("scale"))
        or optimizer.get("reset_momentum_exact_zero") is not True
        or optimizer.get("transplant_momentum_nonzero") is not True
    ):
        _refuse("OPTIMIZER_CAPTURE_INVALID")

    losses = manifest.get("paired_losses")
    if (
        not isinstance(losses, dict)
        or set(losses)
        != {
            "reset",
            "transplant",
            "finite",
            "same_frozen_batch",
            "non_target_state_reused",
            "replay_count_per_arm",
            "deterministic",
            "replay_sha256",
        }
        or not _finite(losses.get("reset"))
        or not _finite(losses.get("transplant"))
        or losses.get("finite") is not True
        or losses.get("same_frozen_batch") is not True
        or losses.get("non_target_state_reused") is not True
        or losses.get("replay_count_per_arm") != 2
        or losses.get("deterministic") is not True
        or losses.get("replay_sha256") != derived_bindings["replay_sha256"]
    ):
        _refuse("PAIRED_LOSS_CAPTURE_INVALID")

    credits = manifest.get("credits")
    if not isinstance(credits, dict) or set(credits) != _CREDIT_KEYS:
        _refuse("CAPTURE_FALSE_CREDIT_SCHEMA_INVALID")
    if any(value is not False for value in credits.values()):
        _refuse("CAPTURE_FALSE_CREDIT")

    target_name = target["name"]
    pre_state = {target_name: artifact_tensors["pre"], **non_target_state}
    reset_state = {target_name: artifact_tensors["reset_post"], **non_target_state}
    transplant_state = {
        target_name: artifact_tensors["transplant_post"],
        **non_target_state,
    }
    return {
        "schema": "q2-actual-update-capture-admission-v1",
        "issue": 675,
        "scope": "TARGET_TENSOR_COUNTERFACTUAL",
        "run_id": manifest["run_id"],
        "source_commit": source_commit,
        "event_authority": "EMBER_LAB_TERMINAL_EXIT_ZERO",
        "capture_manifest_sha256": claimed_manifest_sha,
        "dispatch_manifest_sha256": dispatch["manifest_sha256"],
        "preflight_receipt_sha256": dispatch["preflight_receipt_sha256"],
        "terminal_receipt_sha256": terminal_sha,
        "ember_lab_identity": lab_identity,
        "bindings": derived_bindings,
        "artifact_hashes": artifact_hashes,
        "target": target,
        "non_target_manifest_sha256": non_target_sha,
        "non_target_state_sha256": non_target["state_sha256"],
        "non_target_state": non_target_state,
        "pre_state": pre_state,
        "reset_state": reset_state,
        "transplant_state": transplant_state,
        "gradients": {target_name: artifact_tensors["gradient"]},
        "paired_losses": losses,
        "optimizer": optimizer,
        "event_captured_at": manifest["event_captured_at"],
        "credits": credits,
        "no_new_parallel_authority": True,
    }


def _valid_shape(value: object) -> bool:
    return isinstance(value, list) and bool(value) and all(
        isinstance(item, int) and not isinstance(item, bool) and item > 0 for item in value
    )


def _valid_state_shape(value: object) -> bool:
    return isinstance(value, list) and all(
        isinstance(item, int) and not isinstance(item, bool) and item > 0
        for item in value
    )


def _shape_product(shape: list[int]) -> int:
    result = 1
    for item in shape:
        result *= item
    return result


def _finite(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _positive_finite(value: object) -> bool:
    return _finite(value) and float(value) > 0
