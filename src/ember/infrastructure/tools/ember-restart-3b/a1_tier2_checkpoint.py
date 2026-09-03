# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Separate no-overwrite Tier-2 checkpoint writer and CPU verifier."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
from typing import Any, Mapping
import uuid

import torch

from a1_tier2_optimizer import ProjectedQuantizedAdamWCUDA, QuantizedTensor
from durable_io import atomic_create_durable


SCHEMA = "ember-a1-tier2-checkpoint-v1"
SHARD_SCHEMA = "ember-a1-tier2-checkpoint-shard-v1"
MAX_SHARD_BYTES = 1024**3
IDENTITY_FIELDS = {
    "comparison_id", "matched_identity", "config_sha256",
    "tier2_contract_sha256", "liveness_sha256", "source_commit",
    "certified_launch_sha256", "tier", "mechanism", "predecessor",
}
MATCHED_FIELDS = {
    "comparison_id", "corpus_authority_sha256", "shard_sequence_sha256",
    "tokenizer_sha256", "seed", "cursor_start", "schedule_sha256",
    "genesis_sha256",
}


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _digest(value: object, label: str, *, width: int = 64) -> str:
    if (
        not isinstance(value, str)
        or len(value) != width
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"Tier-2 checkpoint {label} is invalid")
    return value


def _validate_identity(value: object) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != IDENTITY_FIELDS:
        raise ValueError("Tier-2 checkpoint identity is not closed")
    matched = value.get("matched_identity")
    if not isinstance(matched, dict) or set(matched) != MATCHED_FIELDS:
        raise ValueError("Tier-2 checkpoint matched identity is not closed")
    if value["comparison_id"] != matched["comparison_id"]:
        raise ValueError("Tier-2 checkpoint comparison identity drifted")
    for field in (
        "corpus_authority_sha256", "shard_sequence_sha256", "tokenizer_sha256",
        "schedule_sha256", "genesis_sha256",
    ):
        _digest(matched[field], field)
    for field in (
        "config_sha256", "tier2_contract_sha256", "liveness_sha256",
        "certified_launch_sha256",
    ):
        _digest(value[field], field)
    _digest(value["source_commit"], "source_commit", width=40)
    if (
        value["tier"] != "TIER_2"
        or value["mechanism"] != "OWNED_Q_GALORE_PROJECTED_GRADIENT"
    ):
        raise ValueError("Tier-2 checkpoint tier/mechanism identity is invalid")
    if value["predecessor"] is not None:
        raise ValueError("Tier-2 clean-genesis checkpoint cannot name a predecessor")
    if matched["cursor_start"] != {"global_step": 0, "record_index": 0, "tokens_seen": 0}:
        raise ValueError("Tier-2 checkpoint cursor identity is invalid")
    if type(matched["seed"]) is not int:
        raise ValueError("Tier-2 checkpoint seed is invalid")
    return dict(value)


def _metadata(tensor: torch.Tensor) -> dict[str, Any]:
    return {
        "dtype": str(tensor.dtype),
        "shape": list(tensor.shape),
        "numel": tensor.numel(),
        "bytes": tensor.numel() * tensor.element_size(),
    }


def _quantized_payload(record: QuantizedTensor) -> dict[str, Any]:
    return {
        "format_name": record.format_name,
        "block_size": record.block_size,
        "shape": list(record.shape),
        "numel": record.numel,
        "payload": record.payload.detach().to("cpu"),
        "scales": record.scales.detach().to("cpu"),
    }


def _quantized_metadata(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "format_name": value["format_name"],
        "block_size": value["block_size"],
        "shape": value["shape"],
        "numel": value["numel"],
        "payload": _metadata(value["payload"]),
        "scales": _metadata(value["scales"]),
    }


def _validate_quantized_payload(value: object, declared: object, label: str) -> int:
    fields = {"format_name", "block_size", "shape", "numel", "payload", "scales"}
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError(f"Tier-2 checkpoint {label} payload is invalid")
    if not isinstance(declared, dict) or set(declared) != fields:
        raise ValueError(f"Tier-2 checkpoint {label} metadata is invalid")
    if _quantized_metadata(value) != declared:
        raise ValueError(f"Tier-2 checkpoint {label} tensor metadata mismatch")
    if value["payload"].device.type != "cpu" or value["scales"].device.type != "cpu":
        raise ValueError(f"Tier-2 checkpoint {label} did not reopen on CPU")
    return value["payload"].numel() * value["payload"].element_size() + value["scales"].numel() * value["scales"].element_size()


def _bundle(
    name: str,
    parameter: torch.nn.Parameter,
    state: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], int]:
    model = parameter.detach().to("cpu")
    basis = None if state["basis"] is None else _quantized_payload(state["basis"])
    first = _quantized_payload(state["exp_avg"])
    second = _quantized_payload(state["exp_avg_sq"])
    optimizer = {
        "step": state["step"],
        "direction": state["direction"],
        "rank": state["rank"],
        "refresh_ordinal": state["refresh_ordinal"],
        "basis": basis,
        "exp_avg": first,
        "exp_avg_sq": second,
        "parameter_shape": list(parameter.shape),
    }
    metadata_optimizer = {
        **{key: optimizer[key] for key in ("step", "direction", "rank", "refresh_ordinal", "parameter_shape")},
        "basis": None if basis is None else _quantized_metadata(basis),
        "exp_avg": _quantized_metadata(first),
        "exp_avg_sq": _quantized_metadata(second),
    }
    metadata = {"name": name, "model": _metadata(model), "optimizer": metadata_optimizer}
    tensor_bytes = metadata["model"]["bytes"]
    for record in (basis, first, second):
        if record is not None:
            tensor_bytes += record["payload"].numel() * record["payload"].element_size()
            tensor_bytes += record["scales"].numel() * record["scales"].element_size()
    return {"name": name, "model": model, "optimizer": optimizer}, metadata, tensor_bytes


def write_tier2_checkpoint(
    root: Path,
    *,
    model: torch.nn.Module,
    optimizer: ProjectedQuantizedAdamWCUDA,
    global_step: int,
    tokens_seen: int,
    identity: dict[str, Any],
) -> tuple[Path, str]:
    if type(global_step) is not int or global_step < 1:
        raise ValueError("Tier-2 checkpoint global_step must be positive")
    if type(tokens_seen) is not int or tokens_seen < 1:
        raise ValueError("Tier-2 checkpoint tokens_seen must be positive")
    identity = _validate_identity(identity)
    named = list(model.named_parameters())
    if not named or len({id(parameter) for _, parameter in named}) != len(named):
        raise ValueError("Tier-2 model parameter inventory is invalid")
    if [(name, id(parameter)) for name, parameter in optimizer.ordered_named_parameters()] != [
        (name, id(parameter)) for name, parameter in named
    ]:
        raise ValueError("Tier-2 checkpoint optimizer parameter inventory drifted")
    inventory = optimizer.state_inventory()
    if inventory.get("complete") is not True or inventory.get("initialized_parameters") != len(named):
        raise ValueError("Tier-2 checkpoint optimizer inventory is incomplete")
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
            path = staging / f"a1-tier2-shard-{index:05d}.pt"
            torch.save({"schema_version": SHARD_SCHEMA, "index": index, "parameters": pending_payload}, path)
            actual = path.stat().st_size
            if actual > MAX_SHARD_BYTES:
                raise ValueError("Tier-2 checkpoint shard exceeds maximum")
            shards.append({
                "index": index,
                "path": path.name,
                "sha256": _sha(path),
                "bytes": actual,
                "tensor_payload_bytes": pending_bytes,
                "parameters": pending_metadata,
            })
            pending_payload = []
            pending_metadata = []
            pending_bytes = 0

        for name, parameter in named:
            payload, metadata, tensor_bytes = _bundle(name, parameter, optimizer.state[parameter])
            if tensor_bytes > MAX_SHARD_BYTES:
                raise ValueError("Tier-2 parameter bundle exceeds maximum")
            if pending_payload and pending_bytes + tensor_bytes > MAX_SHARD_BYTES:
                flush()
            pending_payload.append(payload)
            pending_metadata.append(metadata)
            pending_bytes += tensor_bytes
        flush()
        manifest = {
            "schema_version": SCHEMA,
            "global_step": global_step,
            "tokens_seen": tokens_seen,
            "identity": identity,
            "parameter_names": [name for name, _ in named],
            "parameter_count": sum(parameter.numel() for _, parameter in named),
            "optimizer_inventory": inventory,
            "shard_max_bytes": MAX_SHARD_BYTES,
            "aggregate_payload_bytes": sum(row["bytes"] for row in shards),
            "aggregate_tensor_payload_bytes": sum(row["tensor_payload_bytes"] for row in shards),
            "payload_shards": shards,
        }
        manifest_path = staging / "checkpoint-manifest.json"
        atomic_create_durable(manifest_path, _canonical(manifest) + b"\n")
        verify_tier2_checkpoint(manifest_path, expected_identity=identity)
        os.rename(staging, root)
    except BaseException:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    manifest_path = root / "checkpoint-manifest.json"
    return manifest_path, _sha(manifest_path)


def verify_tier2_checkpoint(
    manifest_path: Path,
    *,
    expected_identity: dict[str, Any],
) -> dict[str, Any]:
    manifest_path = Path(manifest_path)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("Tier-2 checkpoint manifest is unavailable or invalid") from error
    fields = {
        "schema_version", "global_step", "tokens_seen", "identity",
        "parameter_names", "parameter_count", "optimizer_inventory",
        "shard_max_bytes", "aggregate_payload_bytes",
        "aggregate_tensor_payload_bytes", "payload_shards",
    }
    if not isinstance(manifest, dict) or set(manifest) != fields or manifest["schema_version"] != SCHEMA:
        raise ValueError("Tier-2 checkpoint manifest schema is invalid")
    if _validate_identity(manifest["identity"]) != _validate_identity(expected_identity):
        raise ValueError("Tier-2 checkpoint identity mismatch")
    names = manifest["parameter_names"]
    if not isinstance(names, list) or not names or len(names) != len(set(names)):
        raise ValueError("Tier-2 checkpoint parameter inventory is invalid")
    shards = manifest["payload_shards"]
    if not isinstance(shards, list) or not shards:
        raise ValueError("Tier-2 checkpoint shard inventory is empty")
    seen: list[str] = []
    aggregate_bytes = 0
    aggregate_tensor_bytes = 0
    for expected_index, row in enumerate(shards):
        row_fields = {"index", "path", "sha256", "bytes", "tensor_payload_bytes", "parameters"}
        if not isinstance(row, dict) or set(row) != row_fields:
            raise ValueError("Tier-2 checkpoint shard row is invalid")
        expected_name = f"a1-tier2-shard-{expected_index:05d}.pt"
        if row["index"] != expected_index or row["path"] != expected_name:
            raise ValueError("Tier-2 checkpoint shard order is invalid")
        path = manifest_path.parent / expected_name
        if not path.is_file() or _sha(path) != row["sha256"] or path.stat().st_size != row["bytes"]:
            raise ValueError("Tier-2 checkpoint shard raw bytes mismatch")
        try:
            payload = torch.load(path, map_location="cpu", weights_only=True)
        except Exception as error:
            raise ValueError("Tier-2 checkpoint shard cannot be reopened") from error
        if (
            not isinstance(payload, dict)
            or set(payload) != {"schema_version", "index", "parameters"}
            or payload["schema_version"] != SHARD_SCHEMA
            or payload["index"] != expected_index
        ):
            raise ValueError("Tier-2 checkpoint shard payload is invalid")
        if not isinstance(payload["parameters"], list) or len(payload["parameters"]) != len(row["parameters"]):
            raise ValueError("Tier-2 checkpoint shard parameter inventory mismatch")
        for actual, declared in zip(payload["parameters"], row["parameters"]):
            if (
                not isinstance(actual, dict)
                or set(actual) != {"name", "model", "optimizer"}
                or actual["name"] != declared.get("name")
                or _metadata(actual["model"]) != declared.get("model")
                or actual["model"].device.type != "cpu"
            ):
                raise ValueError("Tier-2 checkpoint model tensor metadata mismatch")
            optimizer_state = actual["optimizer"]
            declared_state = declared["optimizer"]
            scalar_fields = {"step", "direction", "rank", "refresh_ordinal", "parameter_shape"}
            if (
                not isinstance(optimizer_state, dict)
                or set(optimizer_state) != scalar_fields | {"basis", "exp_avg", "exp_avg_sq"}
                or any(optimizer_state[field] != declared_state.get(field) for field in scalar_fields)
            ):
                raise ValueError("Tier-2 checkpoint optimizer metadata mismatch")
            basis = optimizer_state["basis"]
            if (basis is None) != (declared_state["basis"] is None):
                raise ValueError("Tier-2 checkpoint basis metadata mismatch")
            tensor_bytes = actual["model"].numel() * actual["model"].element_size()
            if basis is not None:
                tensor_bytes += _validate_quantized_payload(basis, declared_state["basis"], "basis")
            tensor_bytes += _validate_quantized_payload(optimizer_state["exp_avg"], declared_state["exp_avg"], "first moment")
            tensor_bytes += _validate_quantized_payload(optimizer_state["exp_avg_sq"], declared_state["exp_avg_sq"], "second moment")
            seen.append(actual["name"])
            aggregate_tensor_bytes += tensor_bytes
        aggregate_bytes += row["bytes"]
    if seen != names:
        raise ValueError("Tier-2 checkpoint parameter names are missing or reordered")
    if aggregate_bytes != manifest["aggregate_payload_bytes"] or aggregate_tensor_bytes != manifest["aggregate_tensor_payload_bytes"]:
        raise ValueError("Tier-2 checkpoint aggregate bytes mismatch")
    if manifest["optimizer_inventory"].get("initialized_parameters") != len(names):
        raise ValueError("Tier-2 checkpoint optimizer inventory is incomplete")
    return manifest
