# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Dense-A1-only full-state checkpoint writer and inventory verifier."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
from typing import Any
import uuid

import torch

from a1_dense import DenseA1Decoder
from a1_optimizer import FullStateAdamWCPUOffload
from durable_io import atomic_create_durable


SCHEMA = "ember-a1-dense-checkpoint-v2"
SHARD_SCHEMA = "ember-a1-dense-checkpoint-shard-v1"
MAX_SHARD_BYTES = 1024**3
IDENTITY_FIELDS = {
    "comparison_id", "matched_identity", "config_sha256", "source_commit",
    "certified_launch_sha256", "tier", "mechanism", "predecessor",
}
MATCHED_IDENTITY_FIELDS = {
    "comparison_id", "corpus_authority_sha256", "shard_sequence_sha256",
    "tokenizer_sha256", "seed", "cursor_start", "schedule_sha256",
    "genesis_sha256",
}
OPTIMIZER_INVENTORY_FIELDS = {
    "schema_version", "state_format", "registered_parameters", "registered_numel",
    "initialized_parameters", "cpu_fp32_master_numel",
    "cpu_fp32_first_moment_numel", "cpu_fp32_second_moment_numel", "complete",
}


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dense_inventory(model: DenseA1Decoder) -> dict[str, Any]:
    named = list(model.named_parameters())
    if len({id(parameter) for _, parameter in named}) != len(named):
        raise ValueError("dense A1 named parameter inventory contains aliases")
    total = sum(parameter.numel() for _, parameter in named)
    if total != model.config.structural_parameter_count():
        raise ValueError("dense A1 live parameter inventory differs from structure")
    return {
        "parameter_tensors": len(named),
        "unique_trainable_parameters": total,
        "architecture_revision": "ember-dense-a1-3b-v1",
        "contains_router_or_experts": False,
    }


def _digest(value: object, label: str, *, width: int = 64) -> str:
    if (
        not isinstance(value, str)
        or len(value) != width
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"dense A1 checkpoint {label} is invalid")
    return value


def _validate_identity(identity: object) -> dict[str, Any]:
    if not isinstance(identity, dict) or set(identity) != IDENTITY_FIELDS:
        raise ValueError("dense A1 checkpoint identity is not closed and complete")
    matched = identity.get("matched_identity")
    if not isinstance(matched, dict) or set(matched) != MATCHED_IDENTITY_FIELDS:
        raise ValueError("dense A1 checkpoint matched identity is not closed and complete")
    if identity.get("comparison_id") != matched.get("comparison_id"):
        raise ValueError("dense A1 checkpoint comparison identity is inconsistent")
    for field in (
        "corpus_authority_sha256", "shard_sequence_sha256", "tokenizer_sha256",
        "schedule_sha256", "genesis_sha256",
    ):
        _digest(matched.get(field), field)
    _digest(identity.get("config_sha256"), "config_sha256")
    _digest(identity.get("source_commit"), "source_commit", width=40)
    _digest(identity.get("certified_launch_sha256"), "certified_launch_sha256")
    if identity.get("tier") != "TIER_1" or identity.get("mechanism") != "FULL_STATE_ADAMW_CPU_OFFLOAD":
        raise ValueError("dense A1 checkpoint tier/mechanism identity is invalid")
    if identity.get("predecessor") is not None:
        raise ValueError("dense A1 clean-genesis checkpoint cannot name a predecessor")
    cursor = matched.get("cursor_start")
    if cursor != {"global_step": 0, "record_index": 0, "tokens_seen": 0}:
        raise ValueError("dense A1 checkpoint cursor identity is invalid")
    if type(matched.get("seed")) is not int:
        raise ValueError("dense A1 checkpoint seed identity is invalid")
    return dict(identity)


def _tensor_metadata(tensor: torch.Tensor) -> dict[str, Any]:
    return {
        "dtype": str(tensor.dtype),
        "shape": list(tensor.shape),
        "numel": tensor.numel(),
        "bytes": tensor.numel() * tensor.element_size(),
    }


def _parameter_bundle(
    name: str,
    parameter: torch.nn.Parameter,
    state: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], int]:
    model_tensor = parameter.detach().to(device="cpu")
    optimizer_tensors = {
        field: state[field].detach().to(device="cpu")
        for field in ("master_copy", "exp_avg", "exp_avg_sq")
    }
    payload = {
        "name": name,
        "model": model_tensor,
        "optimizer": {"step": state["step"], **optimizer_tensors},
    }
    metadata = {
        "name": name,
        "model": _tensor_metadata(model_tensor),
        "optimizer": {
            "step": state["step"],
            **{field: _tensor_metadata(tensor) for field, tensor in optimizer_tensors.items()},
        },
    }
    payload_bytes = metadata["model"]["bytes"] + sum(
        metadata["optimizer"][field]["bytes"]
        for field in ("master_copy", "exp_avg", "exp_avg_sq")
    )
    return payload, metadata, payload_bytes


def write_dense_checkpoint(
    root: Path,
    *,
    model: DenseA1Decoder,
    optimizer: FullStateAdamWCPUOffload,
    global_step: int,
    tokens_seen: int,
    identity: dict[str, Any],
) -> tuple[Path, str]:
    if type(global_step) is not int or global_step <= 0:
        raise ValueError("dense A1 checkpoint global_step must be positive")
    if type(tokens_seen) is not int or tokens_seen <= 0:
        raise ValueError("dense A1 checkpoint tokens_seen must be positive")
    identity = _validate_identity(identity)
    inventory = dense_inventory(model)
    optimizer_inventory = optimizer.state_inventory()
    expected = inventory["unique_trainable_parameters"]
    if set(optimizer_inventory) != OPTIMIZER_INVENTORY_FIELDS or optimizer_inventory != {
        **optimizer_inventory,
        "registered_numel": expected,
        "cpu_fp32_master_numel": expected,
        "cpu_fp32_first_moment_numel": expected,
        "cpu_fp32_second_moment_numel": expected,
        "complete": True,
    }:
        raise ValueError("dense A1 optimizer inventory is not complete full state")
    named = list(model.named_parameters())
    optimizer_parameters = optimizer._parameters()
    if [id(parameter) for _, parameter in named] != [id(parameter) for parameter in optimizer_parameters]:
        raise ValueError("dense A1 checkpoint optimizer parameter order drifted")
    root = Path(root)
    if root.exists():
        raise FileExistsError(root)
    root.parent.mkdir(parents=True, exist_ok=True)
    staging = root.parent / f".{root.name}.{uuid.uuid4().hex}.staging"
    staging.mkdir(exist_ok=False)
    try:
        shards: list[dict[str, Any]] = []
        pending_payload: list[dict[str, Any]] = []
        pending_metadata: list[dict[str, Any]] = []
        pending_bytes = 0

        def flush() -> None:
            nonlocal pending_payload, pending_metadata, pending_bytes
            if not pending_payload:
                return
            index = len(shards)
            path = staging / f"a1-shard-{index:05d}.pt"
            torch.save(
                {
                    "schema_version": SHARD_SCHEMA,
                    "index": index,
                    "parameters": pending_payload,
                },
                path,
            )
            actual_bytes = path.stat().st_size
            if actual_bytes > MAX_SHARD_BYTES:
                raise ValueError("dense A1 checkpoint shard exceeds reviewed maximum")
            shards.append(
                {
                    "index": index,
                    "path": path.name,
                    "sha256": _sha(path),
                    "bytes": actual_bytes,
                    "tensor_payload_bytes": pending_bytes,
                    "parameters": pending_metadata,
                }
            )
            pending_payload = []
            pending_metadata = []
            pending_bytes = 0

        for name, parameter in named:
            payload, metadata, payload_bytes = _parameter_bundle(
                name, parameter, optimizer.state[parameter]
            )
            if payload_bytes > MAX_SHARD_BYTES:
                raise ValueError("dense A1 checkpoint parameter bundle exceeds reviewed maximum")
            if pending_payload and pending_bytes + payload_bytes > MAX_SHARD_BYTES:
                flush()
            pending_payload.append(payload)
            pending_metadata.append(metadata)
            pending_bytes += payload_bytes
        flush()
        manifest = {
            "schema_version": SCHEMA,
            "global_step": global_step,
            "tokens_seen": tokens_seen,
            "identity": identity,
            "dense_inventory": inventory,
            "optimizer_inventory": optimizer_inventory,
            "shard_max_bytes": MAX_SHARD_BYTES,
            "aggregate_payload_bytes": sum(row["bytes"] for row in shards),
            "aggregate_tensor_payload_bytes": sum(row["tensor_payload_bytes"] for row in shards),
            "payload_shards": shards,
        }
        manifest_path = staging / "checkpoint-manifest.json"
        atomic_create_durable(manifest_path, _canonical(manifest) + b"\n")
        verify_dense_checkpoint(manifest_path, expected_identity=identity)
        os.rename(staging, root)
    except BaseException:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    manifest_path = root / "checkpoint-manifest.json"
    return manifest_path, _sha(manifest_path)


def verify_dense_checkpoint(
    manifest_path: Path, *, expected_identity: dict[str, Any]
) -> dict[str, Any]:
    manifest_path = Path(manifest_path)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("dense A1 checkpoint manifest is unavailable or invalid") from error
    fields = {
        "schema_version", "global_step", "tokens_seen", "identity",
        "dense_inventory", "optimizer_inventory", "shard_max_bytes",
        "aggregate_payload_bytes", "aggregate_tensor_payload_bytes", "payload_shards",
    }
    if not isinstance(manifest, dict) or set(manifest) != fields or manifest.get("schema_version") != SCHEMA:
        raise ValueError("dense A1 checkpoint manifest schema is invalid")
    if _validate_identity(manifest.get("identity")) != _validate_identity(expected_identity):
        raise ValueError("dense A1 checkpoint identity mismatch")
    shards = manifest.get("payload_shards")
    if not isinstance(shards, list) or not shards:
        raise ValueError("dense A1 checkpoint shard inventory is empty")
    seen_names: list[str] = []
    aggregate_bytes = 0
    aggregate_tensor_bytes = 0
    for expected_index, row in enumerate(shards):
        if not isinstance(row, dict) or set(row) != {
            "index", "path", "sha256", "bytes", "tensor_payload_bytes", "parameters"
        }:
            raise ValueError("dense A1 checkpoint shard row schema is invalid")
        if row.get("index") != expected_index or row.get("path") != f"a1-shard-{expected_index:05d}.pt":
            raise ValueError("dense A1 checkpoint shard order or path is invalid")
        path = manifest_path.parent / row["path"]
        if not path.is_file() or _sha(path) != row.get("sha256") or path.stat().st_size != row.get("bytes"):
            raise ValueError("dense A1 checkpoint shard raw bytes mismatch")
        if row["bytes"] > manifest.get("shard_max_bytes"):
            raise ValueError("dense A1 checkpoint shard exceeds manifest maximum")
        try:
            payload = torch.load(path, map_location="cpu", weights_only=True)
        except Exception as error:
            raise ValueError("dense A1 checkpoint shard cannot be reopened") from error
        if not isinstance(payload, dict) or set(payload) != {"schema_version", "index", "parameters"} or payload.get("schema_version") != SHARD_SCHEMA or payload.get("index") != expected_index:
            raise ValueError("dense A1 checkpoint shard payload schema is invalid")
        payload_parameters = payload.get("parameters")
        metadata = row.get("parameters")
        if not isinstance(payload_parameters, list) or not isinstance(metadata, list) or len(payload_parameters) != len(metadata):
            raise ValueError("dense A1 checkpoint shard parameter inventory mismatch")
        for actual, declared in zip(payload_parameters, metadata):
            if not isinstance(actual, dict) or set(actual) != {"name", "model", "optimizer"} or actual.get("name") != declared.get("name"):
                raise ValueError("dense A1 checkpoint parameter mapping is swapped or invalid")
            if _tensor_metadata(actual["model"]) != declared.get("model"):
                raise ValueError("dense A1 checkpoint model tensor metadata mismatch")
            optimizer_state = actual.get("optimizer")
            declared_optimizer = declared.get("optimizer")
            if not isinstance(optimizer_state, dict) or not isinstance(declared_optimizer, dict) or optimizer_state.get("step") != declared_optimizer.get("step"):
                raise ValueError("dense A1 checkpoint optimizer step mismatch")
            for field in ("master_copy", "exp_avg", "exp_avg_sq"):
                if _tensor_metadata(optimizer_state[field]) != declared_optimizer.get(field):
                    raise ValueError("dense A1 checkpoint optimizer tensor metadata mismatch")
            seen_names.append(actual["name"])
        aggregate_bytes += row["bytes"]
        aggregate_tensor_bytes += row["tensor_payload_bytes"]
    if len(seen_names) != len(set(seen_names)) or len(seen_names) != manifest["dense_inventory"].get("parameter_tensors"):
        raise ValueError("dense A1 checkpoint parameter names are missing or duplicated")
    if aggregate_bytes != manifest.get("aggregate_payload_bytes") or aggregate_tensor_bytes != manifest.get("aggregate_tensor_payload_bytes"):
        raise ValueError("dense A1 checkpoint aggregate bytes mismatch")
    return manifest
