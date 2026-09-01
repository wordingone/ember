#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Closed optimizer-transplant provenance and durable custody (issue #677).

RMS is diagnostic only.  Authority comes from exhaustive named optimizer-slot
mappings, canonical source/destination content hashes, a verified deterministic
replay, and a content-addressed checkpoint copy outside the disposable source
worktree.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import shutil
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

SCHEMA = "ember-optimizer-transplant-provenance/v1"
SHA_CONVENTION = (
    "sha256 over canonical UTF-8 JSON for projections; tensor content hashes "
    "cover dtype, shape, and contiguous CPU bytes"
)
_ROW_KEYS = {
    "mapping_key",
    "optimizer",
    "local_index",
    "parameter_fqn",
    "slot",
    "status",
    "status_reason",
    "source",
    "destination",
    "transform",
    "transform_error",
}
_TOP_KEYS = {
    "schema_version",
    "sha_convention",
    "source_checkpoint_sha256",
    "transplant_method",
    "cure_version",
    "build_timestamp",
    "source_optimizer_state_sha256",
    "destination_optimizer_state_sha256",
    "global_step",
    "scheduler_provenance",
    "scaler_provenance",
    "mapping_rows",
    "mapping_rows_sha256",
    "mapping_counts",
    "deterministic_replay",
    "provenance_sha256",
}
_HEX = set("0123456789abcdef")


class ProvenanceError(ValueError):
    """A transplant claim is incomplete, stale, ambiguous, or unverified."""


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def sha256_file(path: str | os.PathLike[str]) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_sha256(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(char not in _HEX for char in value)
    ):
        raise ProvenanceError(f"{field} must be lowercase sha256")
    return value


def _tensor_record(value: Any) -> dict[str, Any]:
    import torch

    if not torch.is_tensor(value):
        raise ProvenanceError("optimizer slot value is not a tensor")
    tensor = value.detach().cpu().contiguous()
    raw = tensor.reshape(-1).view(torch.uint8).numpy().tobytes()
    header = {
        "dtype": str(tensor.dtype),
        "shape": list(tensor.shape),
    }
    digest = hashlib.sha256(_canonical_bytes(header) + b"\0" + raw).hexdigest()
    if tensor.numel():
        rms = float(
            torch.sqrt(torch.mean(tensor.to(torch.float64) ** 2)).item()
        )
    else:
        rms = 0.0
    return {
        **header,
        "content_sha256": digest,
        "rms": rms,
    }


def _json_scalar(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ProvenanceError("optimizer scalar is not finite")
        return value
    if isinstance(value, (list, tuple)):
        return [_json_scalar(item) for item in value]
    if isinstance(value, Mapping):
        return {
            str(key): _json_scalar(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    raise ProvenanceError(
        f"unsupported optimizer metadata type: {type(value).__name__}"
    )


def _optimizer_projection(
    optimizer_state: Mapping[str, Any],
    param_names: Mapping[str, list[str]],
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    import torch

    if not isinstance(optimizer_state, Mapping):
        raise ProvenanceError("optimizer state must be a mapping")
    projection: dict[str, Any] = {}
    tensor_slots: dict[str, dict[str, Any]] = {}
    for optimizer_name in sorted(param_names):
        names = param_names[optimizer_name]
        if (
            not isinstance(names, list)
            or not all(isinstance(name, str) and name for name in names)
        ):
            raise ProvenanceError(
                f"parameter names for {optimizer_name} must be nonempty strings"
            )
        if len(names) != len(set(names)):
            raise ProvenanceError(
                f"duplicate parameter name in {optimizer_name} routing"
            )
        group = optimizer_state.get(optimizer_name)
        if not isinstance(group, Mapping):
            raise ProvenanceError(f"optimizer group {optimizer_name!r} is missing")
        states = group.get("state")
        if not isinstance(states, Mapping):
            raise ProvenanceError(f"optimizer group {optimizer_name!r} has no state")
        projected_states: dict[str, Any] = {}
        normalized_ids: set[int] = set()
        for raw_index, entry in states.items():
            if isinstance(raw_index, bool):
                raise ProvenanceError("boolean optimizer local index is forbidden")
            try:
                local_index = int(raw_index)
            except (TypeError, ValueError) as exc:
                raise ProvenanceError(
                    f"invalid optimizer local index {raw_index!r}"
                ) from exc
            if str(local_index) != str(raw_index):
                raise ProvenanceError(
                    f"noncanonical optimizer local index {raw_index!r}"
                )
            if local_index in normalized_ids:
                raise ProvenanceError(
                    f"duplicate optimizer local index {local_index}"
                )
            normalized_ids.add(local_index)
            if local_index < 0 or local_index >= len(names):
                raise ProvenanceError(
                    f"optimizer local index {local_index} has no parameter name"
                )
            if not isinstance(entry, Mapping):
                raise ProvenanceError(
                    f"optimizer entry {optimizer_name}:{local_index} is not a mapping"
                )
            slots: dict[str, Any] = {}
            for raw_slot, value in sorted(entry.items(), key=lambda pair: str(pair[0])):
                slot = str(raw_slot)
                if not slot or slot in slots:
                    raise ProvenanceError(
                        f"invalid or duplicate optimizer slot {raw_slot!r}"
                    )
                if torch.is_tensor(value):
                    record = _tensor_record(value)
                    slots[slot] = {"kind": "tensor", **record}
                    key = f"{optimizer_name}:{names[local_index]}:{slot}"
                    if key in tensor_slots:
                        raise ProvenanceError(f"duplicate mapping key {key}")
                    tensor_slots[key] = {
                        "optimizer": optimizer_name,
                        "local_index": local_index,
                        "parameter_fqn": names[local_index],
                        "slot": slot,
                        **record,
                    }
                else:
                    slots[slot] = {
                        "kind": "metadata",
                        "value": _json_scalar(value),
                    }
            projected_states[str(local_index)] = {
                "parameter_fqn": names[local_index],
                "slots": slots,
            }
        projection[optimizer_name] = {
            "state": projected_states,
            "param_groups": _json_scalar(group.get("param_groups", [])),
        }
    extra_groups = sorted(
        key for key in optimizer_state if str(key) not in set(param_names)
    )
    if extra_groups:
        raise ProvenanceError(f"unbound optimizer groups: {extra_groups}")
    return projection, tensor_slots


def _with_provenance_hash(manifest: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(manifest)
    result.pop("provenance_sha256", None)
    result["provenance_sha256"] = _sha256_json(result)
    return result


def build_transplant_provenance(
    *,
    source_checkpoint_sha256: str,
    transplant_method: str,
    cure_version: str,
    build_timestamp: str,
    source_optimizer_state: Mapping[str, Any],
    destination_optimizer_state: Mapping[str, Any],
    param_names: Mapping[str, list[str]],
    transforms: Mapping[str, str],
    transform_errors: Mapping[str, float],
    authorized_fresh: Mapping[str, str],
    dropped: Mapping[str, str],
    global_step: int,
    scheduler_provenance: Mapping[str, Any],
    scaler_provenance: Mapping[str, Any],
) -> dict[str, Any]:
    _require_sha256(source_checkpoint_sha256, "source_checkpoint_sha256")
    if not isinstance(transplant_method, str) or not transplant_method:
        raise ProvenanceError("transplant_method is required")
    if not isinstance(cure_version, str) or not cure_version:
        raise ProvenanceError("cure_version is required")
    if not isinstance(build_timestamp, str) or not build_timestamp:
        raise ProvenanceError("build_timestamp is required")
    if not isinstance(global_step, int) or isinstance(global_step, bool) or global_step < 0:
        raise ProvenanceError("global_step must be a nonnegative integer")
    source_projection, source_slots = _optimizer_projection(
        source_optimizer_state, param_names
    )
    destination_projection, destination_slots = _optimizer_projection(
        destination_optimizer_state, param_names
    )
    all_keys = set(source_slots) | set(destination_slots)
    unknown_policy_keys = (
        set(transforms) | set(transform_errors) | set(authorized_fresh) | set(dropped)
    ) - all_keys
    if unknown_policy_keys:
        raise ProvenanceError(
            f"policy names unknown mapping keys: {sorted(unknown_policy_keys)}"
        )
    rows: list[dict[str, Any]] = []
    for key in sorted(all_keys):
        source = source_slots.get(key)
        destination = destination_slots.get(key)
        if source is None:
            if key not in authorized_fresh:
                raise ProvenanceError(f"unmapped destination slot {key}")
            status = "authorized_fresh"
            status_reason = authorized_fresh[key]
            if not isinstance(status_reason, str) or not status_reason.strip():
                raise ProvenanceError(f"authorized-fresh mapping lacks reason for {key}")
            transform = "authorized-fresh-init"
            error = 0.0
        elif destination is None:
            if key not in dropped:
                raise ProvenanceError(f"unmapped source slot {key}")
            status = "dropped"
            status_reason = dropped[key]
            if not isinstance(status_reason, str) or not status_reason.strip():
                raise ProvenanceError(f"dropped mapping lacks reason for {key}")
            transform = "authorized-drop"
            error = 0.0
        else:
            status = "mapped"
            status_reason = None
            transform = transforms.get(key, "identity")
            if not isinstance(transform, str) or not transform:
                raise ProvenanceError(f"transform is invalid for {key}")
            if transform == "identity":
                if source["content_sha256"] != destination["content_sha256"]:
                    raise ProvenanceError(
                        f"identity transform changed bytes for {key}"
                    )
                error = 0.0
            else:
                if key not in transform_errors:
                    raise ProvenanceError(
                        f"non-identity transform lacks error evidence for {key}"
                    )
                error = transform_errors[key]
                if (
                    isinstance(error, bool)
                    or not isinstance(error, (int, float))
                    or not math.isfinite(float(error))
                    or float(error) < 0
                ):
                    raise ProvenanceError(
                        f"transform error must be finite and nonnegative for {key}"
                    )
                error = float(error)
        basis = destination or source
        assert basis is not None
        rows.append(
            {
                "mapping_key": key,
                "optimizer": basis["optimizer"],
                "local_index": basis["local_index"],
                "parameter_fqn": basis["parameter_fqn"],
                "slot": basis["slot"],
                "status": status,
                "status_reason": status_reason,
                "source": (
                    None
                    if source is None
                    else {
                        "shape": source["shape"],
                        "dtype": source["dtype"],
                        "content_sha256": source["content_sha256"],
                        "rms": source["rms"],
                    }
                ),
                "destination": (
                    None
                    if destination is None
                    else {
                        "shape": destination["shape"],
                        "dtype": destination["dtype"],
                        "content_sha256": destination["content_sha256"],
                        "rms": destination["rms"],
                    }
                ),
                "transform": transform,
                "transform_error": error,
            }
        )
    counts = {
        status: sum(row["status"] == status for row in rows)
        for status in ("mapped", "authorized_fresh", "dropped")
    }
    manifest = {
        "schema_version": SCHEMA,
        "sha_convention": SHA_CONVENTION,
        "source_checkpoint_sha256": source_checkpoint_sha256,
        "transplant_method": transplant_method,
        "cure_version": cure_version,
        "build_timestamp": build_timestamp,
        "source_optimizer_state_sha256": _sha256_json(source_projection),
        "destination_optimizer_state_sha256": _sha256_json(destination_projection),
        "global_step": global_step,
        "scheduler_provenance": _json_scalar(scheduler_provenance),
        "scaler_provenance": _json_scalar(scaler_provenance),
        "mapping_rows": rows,
        "mapping_rows_sha256": _sha256_json(rows),
        "mapping_counts": counts,
        "deterministic_replay": {
            "performed": False,
            "all_destination_hashes_reproduced": False,
            "replayed_mapping_keys": [],
        },
    }
    return _with_provenance_hash(manifest)


def _validate_tensor_endpoint(value: Any, field: str) -> None:
    expected = {"shape", "dtype", "content_sha256", "rms"}
    if not isinstance(value, Mapping) or set(value) != expected:
        raise ProvenanceError(f"{field} tensor endpoint schema is not closed")
    shape = value["shape"]
    if not isinstance(shape, list) or not all(
        isinstance(dim, int) and not isinstance(dim, bool) and dim >= 0 for dim in shape
    ):
        raise ProvenanceError(f"{field} tensor shape is invalid")
    if not isinstance(value["dtype"], str) or not value["dtype"].startswith("torch."):
        raise ProvenanceError(f"{field} tensor dtype is invalid")
    _require_sha256(value["content_sha256"], f"{field} tensor")
    rms = value["rms"]
    if (
        isinstance(rms, bool)
        or not isinstance(rms, (int, float))
        or not math.isfinite(float(rms))
        or float(rms) < 0
    ):
        raise ProvenanceError(f"{field} tensor RMS is invalid")


def _validate_manifest_shape(manifest: Mapping[str, Any]) -> None:
    if not isinstance(manifest, Mapping) or set(manifest) != _TOP_KEYS:
        raise ProvenanceError("provenance top-level schema is not closed")
    if manifest.get("schema_version") != SCHEMA:
        raise ProvenanceError("unsupported provenance schema")
    if manifest.get("sha_convention") != SHA_CONVENTION:
        raise ProvenanceError("sha convention mismatch")
    for field in ("transplant_method", "cure_version"):
        if not isinstance(manifest.get(field), str) or not manifest[field]:
            raise ProvenanceError(f"{field} is required")
    if not isinstance(manifest.get("build_timestamp"), str) or not re.fullmatch(
        r"\d{8}T\d{6}Z", manifest["build_timestamp"]
    ):
        raise ProvenanceError("build_timestamp is invalid")
    global_step = manifest.get("global_step")
    if (
        not isinstance(global_step, int)
        or isinstance(global_step, bool)
        or global_step < 0
    ):
        raise ProvenanceError("global_step is invalid")
    if not isinstance(manifest.get("scheduler_provenance"), Mapping):
        raise ProvenanceError("scheduler_provenance must be an object")
    if not isinstance(manifest.get("scaler_provenance"), Mapping):
        raise ProvenanceError("scaler_provenance must be an object")
    _require_sha256(manifest.get("source_checkpoint_sha256"), "source checkpoint")
    _require_sha256(
        manifest.get("source_optimizer_state_sha256"), "source optimizer state"
    )
    _require_sha256(
        manifest.get("destination_optimizer_state_sha256"),
        "destination optimizer state",
    )
    _require_sha256(manifest.get("mapping_rows_sha256"), "mapping rows")
    _require_sha256(manifest.get("provenance_sha256"), "provenance")
    rows = manifest.get("mapping_rows")
    if not isinstance(rows, list) or not rows:
        raise ProvenanceError("mapping_rows must be nonempty")
    keys: list[str] = []
    statuses: list[str] = []
    replay_required: list[str] = []
    for row in rows:
        if not isinstance(row, Mapping) or set(row) != _ROW_KEYS:
            raise ProvenanceError("mapping row schema is not closed")
        for field in ("mapping_key", "optimizer", "parameter_fqn", "slot", "transform"):
            if not isinstance(row.get(field), str) or not row[field]:
                raise ProvenanceError(f"mapping row {field} is invalid")
        if row["mapping_key"] != (
            f"{row['optimizer']}:{row['parameter_fqn']}:{row['slot']}"
        ):
            raise ProvenanceError("mapping key does not bind its row identity")
        local_index = row.get("local_index")
        if (
            not isinstance(local_index, int)
            or isinstance(local_index, bool)
            or local_index < 0
        ):
            raise ProvenanceError("mapping row local index is invalid")
        status = row.get("status")
        if status not in {"mapped", "authorized_fresh", "dropped"}:
            raise ProvenanceError("mapping row status is invalid")
        reason = row.get("status_reason")
        if status == "mapped":
            if reason is not None or row["source"] is None or row["destination"] is None:
                raise ProvenanceError("mapped row shape is invalid")
        else:
            if not isinstance(reason, str) or not reason.strip():
                raise ProvenanceError("non-mapped row requires a reason")
            if status == "authorized_fresh" and not (
                row["source"] is None and row["destination"] is not None
            ):
                raise ProvenanceError("authorized-fresh row shape is invalid")
            if status == "dropped" and not (
                row["source"] is not None and row["destination"] is None
            ):
                raise ProvenanceError("dropped row shape is invalid")
        if row["source"] is not None:
            _validate_tensor_endpoint(row["source"], "source")
        if row["destination"] is not None:
            _validate_tensor_endpoint(row["destination"], "destination")
        error = row.get("transform_error")
        if (
            isinstance(error, bool)
            or not isinstance(error, (int, float))
            or not math.isfinite(float(error))
            or float(error) < 0
        ):
            raise ProvenanceError("mapping row transform error is invalid")
        if status == "mapped" and row["transform"] != "identity":
            replay_required.append(row["mapping_key"])
        keys.append(row["mapping_key"])
        statuses.append(status)
    if keys != sorted(keys) or len(keys) != len(set(keys)):
        raise ProvenanceError("mapping rows must be unique and sorted")
    if _sha256_json(rows) != manifest["mapping_rows_sha256"]:
        raise ProvenanceError("mapping rows hash mismatch")
    counts = manifest.get("mapping_counts")
    expected_counts = {
        status: statuses.count(status)
        for status in ("mapped", "authorized_fresh", "dropped")
    }
    if counts != expected_counts:
        raise ProvenanceError("mapping counts do not match rows")
    replay = manifest.get("deterministic_replay")
    if not isinstance(replay, Mapping) or set(replay) != {
        "performed",
        "all_destination_hashes_reproduced",
        "replayed_mapping_keys",
    }:
        raise ProvenanceError("deterministic replay schema is not closed")
    if not isinstance(replay["performed"], bool) or not isinstance(
        replay["all_destination_hashes_reproduced"], bool
    ):
        raise ProvenanceError("deterministic replay verdict is invalid")
    replayed = replay["replayed_mapping_keys"]
    if not isinstance(replayed, list) or replayed != sorted(set(replayed)):
        raise ProvenanceError("deterministic replay keys are invalid")
    if replay["performed"]:
        if not replay["all_destination_hashes_reproduced"]:
            raise ProvenanceError("performed deterministic replay did not pass")
        if replayed != sorted(replay_required):
            raise ProvenanceError("deterministic replay coverage is incomplete")
    elif replay["all_destination_hashes_reproduced"] or replayed:
        raise ProvenanceError("unperformed replay cannot claim evidence")
    copy_without_hash = copy.deepcopy(dict(manifest))
    claimed_hash = copy_without_hash.pop("provenance_sha256")
    if _sha256_json(copy_without_hash) != claimed_hash:
        raise ProvenanceError("provenance hash mismatch")

def verify_transplant_provenance(
    manifest: Mapping[str, Any],
    *,
    source_optimizer_state: Mapping[str, Any],
    destination_optimizer_state: Mapping[str, Any],
    param_names: Mapping[str, list[str]],
    replay_tensors: Mapping[str, Any],
) -> dict[str, Any]:
    _validate_manifest_shape(manifest)
    rebuilt = build_transplant_provenance(
        source_checkpoint_sha256=manifest["source_checkpoint_sha256"],
        transplant_method=manifest["transplant_method"],
        cure_version=manifest["cure_version"],
        build_timestamp=manifest["build_timestamp"],
        source_optimizer_state=source_optimizer_state,
        destination_optimizer_state=destination_optimizer_state,
        param_names=param_names,
        transforms={
            row["mapping_key"]: row["transform"]
            for row in manifest["mapping_rows"]
            if row["status"] == "mapped" and row["transform"] != "identity"
        },
        transform_errors={
            row["mapping_key"]: row["transform_error"]
            for row in manifest["mapping_rows"]
            if row["status"] == "mapped" and row["transform"] != "identity"
        },
        authorized_fresh={
            row["mapping_key"]: row["status_reason"]
            for row in manifest["mapping_rows"]
            if row["status"] == "authorized_fresh"
        },
        dropped={
            row["mapping_key"]: row["status_reason"]
            for row in manifest["mapping_rows"]
            if row["status"] == "dropped"
        },
        global_step=manifest["global_step"],
        scheduler_provenance=manifest["scheduler_provenance"],
        scaler_provenance=manifest["scaler_provenance"],
    )
    if (
        rebuilt["source_optimizer_state_sha256"]
        != manifest["source_optimizer_state_sha256"]
    ):
        raise ProvenanceError("source optimizer hash mismatch")
    if (
        rebuilt["destination_optimizer_state_sha256"]
        != manifest["destination_optimizer_state_sha256"]
    ):
        raise ProvenanceError("destination optimizer hash mismatch")
    if rebuilt["mapping_rows"] != manifest["mapping_rows"]:
        raise ProvenanceError("mapping rows do not match optimizer bytes")

    replayed: list[str] = []
    for row in manifest["mapping_rows"]:
        if row["status"] != "mapped" or row["transform"] == "identity":
            continue
        key = row["mapping_key"]
        if key not in replay_tensors:
            raise ProvenanceError(f"missing replay tensor for {key}")
        replay_hash = _tensor_record(replay_tensors[key])["content_sha256"]
        expected = row["destination"]["content_sha256"]
        if replay_hash != expected:
            raise ProvenanceError(f"replay hash mismatch for {key}")
        replayed.append(key)
    result = copy.deepcopy(dict(manifest))
    result["deterministic_replay"] = {
        "performed": True,
        "all_destination_hashes_reproduced": True,
        "replayed_mapping_keys": replayed,
    }
    return _with_provenance_hash(result)


def checkpoint_bundle_sha256(checkpoint_dir: str | os.PathLike[str]) -> str:
    root = Path(checkpoint_dir)
    try:
        manifest = json.loads(
            (root / "manifest.json").read_text(encoding="utf-8", errors="strict")
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProvenanceError(f"checkpoint manifest is unreadable: {exc}") from exc
    if not isinstance(manifest, Mapping) or not isinstance(manifest.get("files"), Mapping):
        raise ProvenanceError("checkpoint manifest has no closed file hash binding")
    rows = []
    for name, expected in sorted(manifest["files"].items()):
        if not isinstance(name, str) or not name or Path(name).name != name:
            raise ProvenanceError("checkpoint manifest contains an unsafe file name")
        _require_sha256(expected, f"checkpoint file {name}")
        path = root / name
        if not path.is_file() or sha256_file(path) != expected:
            raise ProvenanceError(f"checkpoint file hash mismatch: {name}")
        rows.append({"path": name, "sha256": expected})
    return _sha256_json({"step": manifest.get("step"), "files": rows})


def verify_destination_optimizer_binding(
    manifest: Mapping[str, Any], destination_optimizer_state: Mapping[str, Any]
) -> str:
    _validate_manifest_shape(manifest)
    names_by_optimizer: dict[str, dict[int, str]] = {}
    for row in manifest["mapping_rows"]:
        optimizer = row["optimizer"]
        local_index = row["local_index"]
        fqn = row["parameter_fqn"]
        if not isinstance(local_index, int) or isinstance(local_index, bool) or local_index < 0:
            raise ProvenanceError("mapping row local index is invalid")
        prior = names_by_optimizer.setdefault(optimizer, {}).get(local_index)
        if prior is not None and prior != fqn:
            raise ProvenanceError("mapping rows disagree on parameter routing")
        names_by_optimizer[optimizer][local_index] = fqn
    param_names: dict[str, list[str]] = {}
    for optimizer, indexed in names_by_optimizer.items():
        if sorted(indexed) != list(range(max(indexed) + 1)):
            raise ProvenanceError("mapping rows do not cover contiguous optimizer routing")
        param_names[optimizer] = [indexed[index] for index in range(max(indexed) + 1)]
    projection, _slots = _optimizer_projection(destination_optimizer_state, param_names)
    digest = _sha256_json(projection)
    if digest != manifest["destination_optimizer_state_sha256"]:
        raise ProvenanceError("destination optimizer hash mismatch")
    replay = manifest["deterministic_replay"]
    if not isinstance(replay, Mapping) or replay.get("performed") is not True or replay.get("all_destination_hashes_reproduced") is not True:
        raise ProvenanceError("deterministic transplant replay is not verified")
    return digest

def load_verified_custody_checkpoint(
    checkpoint_dir: str | os.PathLike[str],
) -> dict[str, Any]:
    """Consume a transplanted checkpoint only after #677's full binding."""
    import torch

    root = Path(checkpoint_dir).resolve(strict=True)
    try:
        manifest = json.loads(
            (root / "manifest.json").read_text(encoding="utf-8", errors="strict")
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProvenanceError(f"transplant checkpoint manifest is unreadable: {exc}") from exc
    if not isinstance(manifest, Mapping):
        raise ProvenanceError("transplant checkpoint manifest must be an object")
    checkpoint_bundle_sha256(root)
    custody = manifest.get("custody")
    if not isinstance(custody, Mapping):
        raise ProvenanceError("transplant checkpoint has no durable custody record")
    if custody.get("artifact_id") != root.name:
        raise ProvenanceError("transplant checkpoint path does not match custody artifact id")
    if (
        custody.get("all_payload_hashes_preserved") is not True
        or custody.get("source_mutated") is not False
    ):
        raise ProvenanceError("transplant checkpoint custody is not hash-preserved")
    provenance_name = manifest.get("transplant_provenance_path")
    if provenance_name != "transplant-provenance.json":
        raise ProvenanceError("transplant provenance path is missing or noncanonical")
    provenance = load_transplant_provenance(
        root / provenance_name,
        expected_sha256=manifest.get("transplant_provenance_file_sha256"),
        expected_build_timestamp=manifest.get("ts"),
    )
    if manifest.get("transplant_provenance") != provenance:
        raise ProvenanceError("inline and sidecar transplant provenance disagree")
    optimizer_state = torch.load(
        root / "optimizer.pt", map_location="cpu", weights_only=True, mmap=True
    )
    verify_destination_optimizer_binding(provenance, optimizer_state)
    return {
        "note": (
            "issue #677 verified transplant provenance is inline and in "
            f"{provenance_name}; both are hash-bound by manifest.json"
        ),
        "transplant_provenance_path": provenance_name,
        "transplant_provenance_file_sha256": manifest[
            "transplant_provenance_file_sha256"
        ],
        "transplant_provenance": provenance,
        "custody": dict(custody),
    }

def load_transplant_provenance(
    path: str | os.PathLike[str],
    *,
    expected_sha256: str | None = None,
    expected_build_timestamp: str | None = None,
) -> dict[str, Any]:
    try:
        raw = Path(path).read_bytes()
        if expected_sha256 is not None:
            _require_sha256(expected_sha256, "expected provenance file")
            if hashlib.sha256(raw).hexdigest() != expected_sha256:
                raise ProvenanceError("transplant provenance file hash mismatch")
        value = json.loads(raw.decode("utf-8", errors="strict"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProvenanceError(f"cannot read transplant provenance: {exc}") from exc
    _validate_manifest_shape(value)
    if (
        expected_build_timestamp is not None
        and value["build_timestamp"] != expected_build_timestamp
    ):
        raise ProvenanceError("stale transplant provenance build timestamp")
    return value


def write_transplant_provenance_atomic(
    path: str | os.PathLike[str], manifest: Mapping[str, Any]
) -> None:
    _validate_manifest_shape(manifest)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    data = _canonical_bytes(manifest) + b"\n"
    fd, staging_name = tempfile.mkstemp(
        dir=target.parent, prefix=f".{target.name}.", suffix=".tmp"
    )
    staging = Path(staging_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(staging, target)
        loaded = load_transplant_provenance(target)
        if loaded != manifest:
            raise ProvenanceError("published provenance did not round-trip")
    finally:
        staging.unlink(missing_ok=True)


def _worktree_root(path: Path) -> Path | None:
    for candidate in (path, *path.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def publish_checkpoint_to_custody(
    checkpoint_dir: str | os.PathLike[str],
    custody_root: str | os.PathLike[str],
) -> dict[str, Any]:
    source = Path(checkpoint_dir).resolve(strict=True)
    custody = Path(custody_root).resolve()
    if not source.is_dir():
        raise ProvenanceError("checkpoint source must be a directory")
    source_worktree = _worktree_root(source)
    if source_worktree is not None and (
        custody == source_worktree or source_worktree in custody.parents
    ):
        raise ProvenanceError(
            "custody root must be outside the disposable worktree"
        )
    paths = sorted(path for path in source.iterdir() if path.is_file())
    if not paths or not (source / "manifest.json").is_file():
        raise ProvenanceError("checkpoint bundle is incomplete")
    if any(path.is_symlink() for path in paths):
        raise ProvenanceError("checkpoint custody refuses symlink payloads")
    source_hashes = {path.name: sha256_file(path) for path in paths}
    bundle_projection = [
        {"path": name, "sha256": digest}
        for name, digest in sorted(source_hashes.items())
    ]
    bundle_sha = _sha256_json(bundle_projection)
    artifact_id = f"optimizer-transplant-{bundle_sha[:24]}"
    destination = custody / artifact_id
    if destination.exists():
        raise ProvenanceError("custody artifact already exists")
    custody.mkdir(parents=True, exist_ok=True)
    staging = custody / f".{artifact_id}.{os.getpid()}.tmp"
    if staging.exists():
        raise ProvenanceError("custody staging path already exists")
    staging.mkdir()
    publication_modes: dict[str, str] = {}
    try:
        for path in paths:
            if path.name == "manifest.json":
                continue
            target = staging / path.name
            try:
                os.link(path, target)
                publication_modes[path.name] = "hardlink"
            except OSError:
                shutil.copyfile(path, target)
                publication_modes[path.name] = "copy"
            if sha256_file(target) != source_hashes[path.name]:
                raise ProvenanceError(
                    f"custody payload hash changed for {path.name}"
                )
        try:
            manifest = json.loads(
                (source / "manifest.json").read_text(
                    encoding="utf-8", errors="strict"
                )
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProvenanceError(f"checkpoint manifest is unreadable: {exc}") from exc
        if not isinstance(manifest, dict):
            raise ProvenanceError("checkpoint manifest must be an object")
        manifest = copy.deepcopy(manifest)
        manifest["custody"] = {
            "schema_version": "ember-checkpoint-custody-publication/v1",
            "artifact_id": artifact_id,
            "source_bundle_sha256": bundle_sha,
            "source_worktree_disposable": source_worktree is not None,
            "destination_relative": artifact_id,
            "publication_modes": publication_modes,
            "payload_sha256": {
                name: digest
                for name, digest in source_hashes.items()
                if name != "manifest.json"
            },
            "all_payload_hashes_preserved": True,
            "source_mutated": False,
        }
        manifest_path = staging / "manifest.json"
        manifest_path.write_bytes(_canonical_bytes(manifest) + b"\n")
        with open(manifest_path, "r+b") as stream:
            os.fsync(stream.fileno())
        os.replace(staging, destination)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    for path in paths:
        if sha256_file(path) != source_hashes[path.name]:
            raise ProvenanceError(f"source mutated during custody: {path.name}")
    return {
        "artifact_id": artifact_id,
        "destination_path": str(destination),
        "source_bundle_sha256": bundle_sha,
        "source_mutated": False,
        "all_payload_hashes_preserved": True,
    }
