#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Live MTP parameter ownership and split-accounting evidence.

The declaration in ``v0-pretrain-config.json`` is only a contract pin.  This
module measures the live ``torch.nn.Module`` and optimizer objects at the
consumer boundary, deduplicates storage before counting, and fails closed on
ambiguous ownership or optimizer membership.  The JSON form is intentionally
path-free and content-addressed so launch, pricing, and H-Q receipts can bind
the same evidence without trusting a caller-provided total.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


class MtpParameterManifestError(ValueError):
    """The live parameter partition is missing, ambiguous, or inconsistent."""


_TOP_LEVEL_KEYS = {
    "schema",
    "parameter_accounting",
    "parameters",
    "optimizer",
    "manifest_sha256",
}
_ROW_KEYS = {
    "names",
    "aliases",
    "shape",
    "numel",
    "dtype",
    "python_object_id",
    "storage_identity",
    "optimizer_param_group",
    "owner",
}
_STORAGE_KEYS = {"storage_id", "data_ptr", "nbytes"}
_ACCOUNTING_KEYS = {"base_excluding_mtp", "mtp_aux", "realized"}
_OPTIMIZER_KEYS = {"group_count", "parameter_count"}
_MTP_NAME = re.compile(r"(?:^|\.)mtp_heads\.(\d+)(?:\.|$)")
_BASE_ROOTS = {
    "base",
    "backbone",
    "backbone_model",
    "blocks",
    "embed_tokens",
    "embed",
    "extra",
    "head",
    "layers",
    "lm_head",
    "model",
    "norm",
    "tok_embeddings",
    "transformer",
}


def _config_accounting(config: Mapping[str, Any]) -> dict[str, int] | None:
    model = config.get("model") if isinstance(config, Mapping) else None
    value = model.get("parameter_accounting") if isinstance(model, Mapping) else None
    if value is None:
        value = config.get("parameter_accounting") if isinstance(config, Mapping) else None
    if not isinstance(value, Mapping):
        return None
    if set(value) != _ACCOUNTING_KEYS:
        raise MtpParameterManifestError(
            "config parameter_accounting must contain exactly base_excluding_mtp, mtp_aux, realized"
        )
    if any(type(value[key]) is not int or value[key] < 0 for key in _ACCOUNTING_KEYS):
        raise MtpParameterManifestError("config parameter_accounting values must be non-negative integers")
    return {key: int(value[key]) for key in _ACCOUNTING_KEYS}


def _storage_identity(parameter: Any) -> dict[str, Any]:
    try:
        storage = parameter.untyped_storage()
    except AttributeError:
        try:
            storage = parameter.storage()
        except AttributeError as error:
            raise MtpParameterManifestError("trainable parameter has no storage identity") from error
    data_ptr = int(storage.data_ptr())
    nbytes = int(storage.nbytes())
    cdata = getattr(storage, "_cdata", None)
    storage_id = str(int(cdata)) if cdata is not None else f"{data_ptr}:{nbytes}"
    return {"storage_id": storage_id, "data_ptr": data_ptr, "nbytes": nbytes}


def _owner_for_names(names: Sequence[str]) -> str:
    owners: set[str] = set()
    for name in names:
        match = _MTP_NAME.search(name)
        if match:
            owners.add(f"mtp_head_{int(match.group(1))}")
            continue
        root = name.split(".", 1)[0]
        if root in _BASE_ROOTS:
            owners.add("base")
        else:
            raise MtpParameterManifestError(
                f"parameter {name!r} has no canonical MTP owner (orphan owner)"
            )
    if len(owners) != 1:
        raise MtpParameterManifestError(
            f"parameter aliases cross owners: {sorted(owners)!r}"
        )
    return next(iter(owners))


def _optimizer_items(optimizers: Any) -> list[tuple[str, Any]]:
    if isinstance(optimizers, Mapping):
        return [(str(name), value) for name, value in optimizers.items()]
    if isinstance(optimizers, Sequence) and not isinstance(optimizers, (str, bytes)):
        return [(f"optimizer_{index}", value) for index, value in enumerate(optimizers)]
    return [("optimizer", optimizers)]


def _optimizer_membership(optimizers: Any) -> tuple[dict[int, list[dict[str, Any]]], int, int]:
    membership: dict[int, list[dict[str, Any]]] = defaultdict(list)
    group_count = 0
    for optimizer_name, optimizer in _optimizer_items(optimizers):
        groups = getattr(optimizer, "param_groups", None)
        if not isinstance(groups, list):
            raise MtpParameterManifestError("optimizer has no param_groups")
        for group_index, group in enumerate(groups):
            if not isinstance(group, Mapping) or not isinstance(group.get("params"), (list, tuple)):
                raise MtpParameterManifestError("optimizer param_group is malformed")
            group_count += 1
            for parameter in group["params"]:
                membership[id(parameter)].append(
                    {"optimizer": optimizer_name, "index": group_index}
                )
    return membership, group_count, sum(len(value) for value in membership.values())


def _canonical_bytes(manifest: Mapping[str, Any]) -> bytes:
    payload = copy.deepcopy(dict(manifest))
    payload.pop("manifest_sha256", None)
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def manifest_sha256(manifest: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_bytes(manifest)).hexdigest()


def _validate_accounting(accounting: Mapping[str, Any], config: Mapping[str, Any] | None = None) -> None:
    if set(accounting) != _ACCOUNTING_KEYS:
        raise MtpParameterManifestError("manifest parameter_accounting has unknown or missing fields")
    if any(type(accounting[key]) is not int or accounting[key] < 0 for key in _ACCOUNTING_KEYS):
        raise MtpParameterManifestError("manifest parameter_accounting values must be non-negative integers")
    if accounting["base_excluding_mtp"] + accounting["mtp_aux"] != accounting["realized"]:
        raise MtpParameterManifestError("base_excluding_mtp + mtp_aux != realized")
    expected = _config_accounting(config) if config is not None else None
    if expected is not None and dict(accounting) != expected:
        raise MtpParameterManifestError(
            f"live parameter accounting {dict(accounting)!r} != declared {expected!r}"
        )


def build_parameter_manifest(model: Any, optimizers: Any, config: Mapping[str, Any]) -> dict[str, Any]:
    """Build and validate a manifest from the live module and optimizer objects."""
    named = []
    try:
        iterator = model.named_parameters(remove_duplicate=False)
    except TypeError:
        iterator = model.named_parameters()
    for name, parameter in iterator:
        if getattr(parameter, "requires_grad", False):
            named.append((str(name), parameter))
    if not named:
        raise MtpParameterManifestError("live model has no trainable parameters")

    by_object: dict[int, dict[str, Any]] = {}
    for name, parameter in named:
        object_id = id(parameter)
        row = by_object.setdefault(object_id, {"parameter": parameter, "names": []})
        row["names"].append(name)

    membership, group_count, optimizer_parameter_count = _optimizer_membership(optimizers)
    rows: list[dict[str, Any]] = []
    storage_owners: dict[str, set[str]] = defaultdict(set)
    for object_id, item in sorted(by_object.items(), key=lambda pair: sorted(pair[1]["names"])):
        names = sorted(set(item["names"]))
        groups = membership.get(object_id, [])
        if len(groups) != 1:
            raise MtpParameterManifestError(
                f"parameter {names!r} must belong to exactly one optimizer param-group; got {groups!r}"
            )
        parameter = item["parameter"]
        storage = _storage_identity(parameter)
        owner = _owner_for_names(names)
        storage_owners[storage["storage_id"]].add(owner)
        rows.append({
            "names": names,
            "aliases": names[1:],
            "shape": [int(value) for value in parameter.shape],
            "numel": int(parameter.numel()),
            "dtype": str(parameter.dtype),
            "python_object_id": int(object_id),
            "storage_identity": storage,
            "optimizer_param_group": groups[0],
            "owner": owner,
        })

    cross_owner = {key: sorted(values) for key, values in storage_owners.items() if len(values) > 1}
    if cross_owner:
        raise MtpParameterManifestError(f"cross-owner storage sharing refused: {cross_owner!r}")

    seen_storage: set[tuple[str, str]] = set()
    base = 0
    aux = 0
    for row in rows:
        key = (row["storage_identity"]["storage_id"], row["owner"])
        if key in seen_storage:
            continue
        seen_storage.add(key)
        if row["owner"] == "base":
            base += row["numel"]
        else:
            aux += row["numel"]
    accounting = {"base_excluding_mtp": base, "mtp_aux": aux, "realized": base + aux}
    _validate_accounting(accounting, config)
    manifest = {
        "schema": "ember-mtp-parameter-manifest-v1",
        "parameter_accounting": accounting,
        "parameters": rows,
        "optimizer": {
            "group_count": group_count,
            "parameter_count": optimizer_parameter_count,
        },
    }
    manifest["manifest_sha256"] = manifest_sha256(manifest)
    validate_parameter_manifest(manifest, config)
    return manifest


def validate_parameter_manifest(manifest: Mapping[str, Any], config: Mapping[str, Any] | None = None) -> None:
    """Validate closed schema, hash, optimizer membership, and split arithmetic."""
    if not isinstance(manifest, Mapping):
        raise MtpParameterManifestError("manifest must be an object")
    unknown = set(manifest) - _TOP_LEVEL_KEYS
    missing = _TOP_LEVEL_KEYS - set(manifest)
    if unknown or missing:
        raise MtpParameterManifestError(f"manifest unknown or missing fields: unknown={sorted(unknown)} missing={sorted(missing)}")
    if manifest.get("schema") != "ember-mtp-parameter-manifest-v1":
        raise MtpParameterManifestError("manifest schema is not ember-mtp-parameter-manifest-v1")
    if manifest.get("manifest_sha256") != manifest_sha256(manifest):
        raise MtpParameterManifestError("manifest_sha256 does not match canonical manifest bytes")
    accounting = manifest.get("parameter_accounting")
    if not isinstance(accounting, Mapping):
        raise MtpParameterManifestError("parameter_accounting must be an object")
    _validate_accounting(accounting, config)
    optimizer = manifest.get("optimizer")
    if not isinstance(optimizer, Mapping) or set(optimizer) != _OPTIMIZER_KEYS:
        raise MtpParameterManifestError("optimizer schema is not closed")
    if any(type(optimizer[key]) is not int or optimizer[key] < 0 for key in _OPTIMIZER_KEYS):
        raise MtpParameterManifestError("optimizer counts must be non-negative integers")
    rows = manifest.get("parameters")
    if not isinstance(rows, list) or not rows:
        raise MtpParameterManifestError("parameters must be a non-empty list")
    storage_owners: dict[str, set[str]] = defaultdict(set)
    seen_objects: set[int] = set()
    seen_names: set[str] = set()
    seen_storage_owner: set[tuple[str, str]] = set()
    derived = {"base_excluding_mtp": 0, "mtp_aux": 0}
    for row in rows:
        if not isinstance(row, Mapping):
            raise MtpParameterManifestError("parameter row must be an object")
        if set(row) != _ROW_KEYS:
            raise MtpParameterManifestError("parameter row has unknown or missing fields")
        names = row.get("names")
        aliases = row.get("aliases")
        if not isinstance(names, list) or not names or names != sorted(set(names)):
            raise MtpParameterManifestError("parameter names must be a sorted unique non-empty list")
        if aliases != names[1:]:
            raise MtpParameterManifestError("parameter aliases must be names[1:]")
        if any(not isinstance(name, str) or not name for name in names):
            raise MtpParameterManifestError("parameter names must be non-empty strings")
        if seen_names.intersection(names):
            raise MtpParameterManifestError("duplicate parameter name")
        seen_names.update(names)
        object_id = row.get("python_object_id")
        if type(object_id) is not int or object_id <= 0 or object_id in seen_objects:
            raise MtpParameterManifestError("python_object_id must be a unique positive integer")
        seen_objects.add(object_id)
        shape = row.get("shape")
        if not isinstance(shape, list) or any(type(value) is not int or value < 0 for value in shape):
            raise MtpParameterManifestError("parameter shape is malformed")
        if type(row.get("numel")) is not int or row["numel"] < 0:
            raise MtpParameterManifestError("parameter numel is malformed")
        if not isinstance(row.get("dtype"), str) or not row["dtype"]:
            raise MtpParameterManifestError("parameter dtype is malformed")
        expected_numel = 1
        for value in shape:
            expected_numel *= value
        if expected_numel != row["numel"]:
            raise MtpParameterManifestError("parameter shape/numel mismatch")
        storage = row.get("storage_identity")
        if not isinstance(storage, Mapping) or set(storage) != _STORAGE_KEYS:
            raise MtpParameterManifestError("storage_identity schema is not closed")
        if not isinstance(storage["storage_id"], str) or not storage["storage_id"]:
            raise MtpParameterManifestError("storage_identity.storage_id is malformed")
        if (type(storage["data_ptr"]) is not int or storage["data_ptr"] < 0
                or type(storage["nbytes"]) is not int or storage["nbytes"] < 0):
            raise MtpParameterManifestError("storage_identity numeric fields are malformed")
        owner = row.get("owner")
        if not isinstance(owner, str) or (owner != "base" and not re.fullmatch(r"mtp_head_[0-9]+", owner)):
            raise MtpParameterManifestError("parameter owner is malformed")
        try:
            expected_owner = _owner_for_names(names)
        except MtpParameterManifestError as exc:
            raise MtpParameterManifestError(
                f"parameter owner cannot be derived from names: {exc}"
            ) from exc
        if expected_owner != owner:
            raise MtpParameterManifestError(
                f"parameter owner does not match names: {owner!r} != {expected_owner!r}"
            )
        storage_owners[storage["storage_id"]].add(owner)
        group = row.get("optimizer_param_group")
        if not isinstance(group, Mapping) or set(group) != {"optimizer", "index"}:
            raise MtpParameterManifestError("optimizer_param_group schema is not closed")
        if not isinstance(group["optimizer"], str) or not group["optimizer"] or type(group["index"]) is not int or group["index"] < 0:
            raise MtpParameterManifestError("optimizer_param_group is malformed")
        key = (storage["storage_id"], owner)
        if key not in seen_storage_owner:
            seen_storage_owner.add(key)
            derived["base_excluding_mtp" if owner == "base" else "mtp_aux"] += row["numel"]
    cross_owner = {key: sorted(value) for key, value in storage_owners.items() if len(value) > 1}
    if cross_owner:
        raise MtpParameterManifestError(f"cross-owner storage sharing refused: {cross_owner!r}")
    if derived["base_excluding_mtp"] != accounting["base_excluding_mtp"] or derived["mtp_aux"] != accounting["mtp_aux"]:
        raise MtpParameterManifestError(f"manifest accounting is not derived from rows: {derived!r} != {dict(accounting)!r}")
    if optimizer["parameter_count"] != len(rows):
        raise MtpParameterManifestError("optimizer parameter_count does not equal manifest rows")


def build_parameter_manifest_from_parts(
    backbone: Any,
    head: Any,
    mtp_heads: Any,
    optimizers: Any,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    """Measure the exact model parts and optimizers constructed for a live run.

    The production optimizer-equivalence bench constructs these parts separately;
    this adapter gives the manifest builder one canonical module tree without
    accepting caller-declared counts or identities.
    """
    import torch

    class _LiveMtpParts(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.backbone = backbone
            self.head = head
            self.mtp_heads = mtp_heads

    return build_parameter_manifest(_LiveMtpParts(), optimizers, config)

def write_parameter_manifest(path: str | Path, model: Any, optimizers: Any, config: Mapping[str, Any]) -> dict[str, Any]:
    manifest = build_parameter_manifest(model, optimizers, config)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def write_parameter_manifest_from_parts(
    path: str | Path,
    backbone: Any,
    head: Any,
    mtp_heads: Any,
    optimizers: Any,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    manifest = build_parameter_manifest_from_parts(
        backbone, head, mtp_heads, optimizers, config
    )
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest

def attach_parameter_manifest(
    receipt: Mapping[str, Any],
    model: Any,
    optimizers: Any,
    config: Mapping[str, Any],
    path: str | Path | None = None,
) -> dict[str, Any]:
    manifest = write_parameter_manifest(path, model, optimizers, config) if path is not None else build_parameter_manifest(model, optimizers, config)
    bound = copy.deepcopy(dict(receipt))
    bound["parameter_manifest"] = {
        "schema": manifest["schema"],
        "sha256": manifest["manifest_sha256"],
        "path": Path(path).name if path is not None else None,
    }
    bound["parameter_accounting"] = dict(manifest["parameter_accounting"])
    return bound


def canonical_accounting_projection(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Return the identity-free projection shared by independently built arms."""
    validate_parameter_manifest(manifest)
    return {
        "parameter_accounting": dict(manifest["parameter_accounting"]),
        "optimizer": {
            "group_count": manifest["optimizer"]["group_count"],
            "parameter_count": manifest["optimizer"]["parameter_count"],
        },
    }


def bind_manifest_evidence(receipt: Mapping[str, Any], manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Bind an already validated manifest to a downstream H-Q receipt."""
    validate_parameter_manifest(manifest)
    bound = copy.deepcopy(dict(receipt))
    bound["parameter_manifest"] = {
        "schema": manifest["schema"],
        "sha256": manifest["manifest_sha256"],
        "path": None,
    }
    bound["parameter_accounting"] = dict(manifest["parameter_accounting"])
    return bound

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_EXECUTION_CANDIDATE_KEYS = {
    "schema", "run_id", "update_count", "source_sha256", "config_sha256",
    "manifest_sha256", "before_state_sha256", "after_state_sha256",
    "before_optimizer_state_sha256", "optimizer_state_sha256", "receipt_sha256",
}
_GOVERNED_RUNNER_CAPABILITY = object()
_GOVERNED_EXECUTION_KEYS = {
    "schema", "authority", "status", "run_id", "update_count", "child_exit_code",
    "manifest_sha256", "execution_candidate", "execution_candidate_sha256",
    "command", "command_sha256", "process_identity", "verifier_id",
    "verifier_sha256", "disk_budget_receipt", "disk_budget_receipt_sha256",
    "runner_module_sha256", "receipt_sha256",
}
_EXECUTED_RUN_KEYS = {
    "schema", "evidence", "run_id", "update_count", "source_sha256", "config_sha256",
    "manifest_sha256", "governed_execution_receipt", "governed_execution_receipt_sha256",
    "receipt_sha256",
}


def _require_sha256(value: Any, label: str) -> None:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise MtpParameterManifestError(f"{label} must be a lowercase SHA-256")


def _execution_candidate_bytes(receipt: Mapping[str, Any]) -> bytes:
    payload = copy.deepcopy(dict(receipt))
    payload.pop("receipt_sha256", None)
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def execution_candidate_sha256(receipt: Mapping[str, Any]) -> str:
    return hashlib.sha256(_execution_candidate_bytes(receipt)).hexdigest()


def _governed_execution_receipt_bytes(receipt: Mapping[str, Any]) -> bytes:
    payload = copy.deepcopy(dict(receipt))
    payload.pop("receipt_sha256", None)
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def governed_execution_receipt_sha256(receipt: Mapping[str, Any]) -> str:
    return hashlib.sha256(_governed_execution_receipt_bytes(receipt)).hexdigest()


def _canonical_mapping_sha256(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(dict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def validate_execution_candidate(
    receipt: Mapping[str, Any], manifest: Mapping[str, Any] | None = None
) -> None:
    if not isinstance(receipt, Mapping) or set(receipt) != _EXECUTION_CANDIDATE_KEYS:
        raise MtpParameterManifestError("execution candidate schema is not closed")
    if receipt["schema"] != "ember-mtp-execution-candidate-v1":
        raise MtpParameterManifestError("execution candidate schema is invalid")
    if not isinstance(receipt["run_id"], str) or not receipt["run_id"].strip():
        raise MtpParameterManifestError("execution candidate run_id is invalid")
    if type(receipt["update_count"]) is not int or receipt["update_count"] < 1:
        raise MtpParameterManifestError("execution candidate update_count must be positive")
    for key in (
        "source_sha256", "config_sha256", "manifest_sha256",
        "before_state_sha256", "after_state_sha256",
        "before_optimizer_state_sha256", "optimizer_state_sha256", "receipt_sha256",
    ):
        _require_sha256(receipt[key], f"execution candidate {key}")
    if receipt["before_state_sha256"] == receipt["after_state_sha256"]:
        raise MtpParameterManifestError("execution candidate update evidence is unchanged")
    if receipt["receipt_sha256"] != execution_candidate_sha256(receipt):
        raise MtpParameterManifestError("execution candidate receipt hash mismatch")
    if manifest is not None:
        validate_parameter_manifest(manifest)
        if receipt["manifest_sha256"] != manifest["manifest_sha256"]:
            raise MtpParameterManifestError("execution candidate manifest hash mismatch")


def validate_governed_execution_receipt(
    receipt: Mapping[str, Any], manifest: Mapping[str, Any] | None = None
) -> None:
    if not isinstance(receipt, Mapping) or set(receipt) != _GOVERNED_EXECUTION_KEYS:
        raise MtpParameterManifestError("governed execution receipt schema is not closed")
    if receipt["schema"] != "ember-mtp-governed-execution-receipt-v2":
        raise MtpParameterManifestError("governed execution receipt schema is invalid")
    if receipt["authority"] != "external-disk-budget-runner" or receipt["status"] != "VERIFIED_COMPLETED":
        raise MtpParameterManifestError("governed execution authority is not externally verified")
    if not isinstance(receipt["run_id"], str) or not receipt["run_id"].strip():
        raise MtpParameterManifestError("governed execution run_id is invalid")
    if type(receipt["update_count"]) is not int or receipt["update_count"] < 1:
        raise MtpParameterManifestError("governed execution update_count must be positive")
    if type(receipt["child_exit_code"]) is not int or receipt["child_exit_code"] != 0:
        raise MtpParameterManifestError("governed execution observed child exit must be zero")
    if not isinstance(receipt["command"], list) or not receipt["command"] or not all(
        isinstance(item, str) and item and "\x00" not in item for item in receipt["command"]
    ):
        raise MtpParameterManifestError("governed execution command is invalid")
    command_bytes = json.dumps(receipt["command"], separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if receipt["command_sha256"] != hashlib.sha256(command_bytes).hexdigest():
        raise MtpParameterManifestError("governed execution command hash mismatch")
    identity = receipt["process_identity"]
    if not isinstance(identity, Mapping) or set(identity) != {"pid", "start_time_ns", "executable_sha256"}:
        raise MtpParameterManifestError("governed execution process identity is not closed")
    if type(identity["pid"]) is not int or identity["pid"] <= 0:
        raise MtpParameterManifestError("governed execution process identity pid is invalid")
    if type(identity["start_time_ns"]) is not int or identity["start_time_ns"] <= 0:
        raise MtpParameterManifestError("governed execution process identity start time is invalid")
    _require_sha256(identity["executable_sha256"], "governed execution executable_sha256")
    if not isinstance(receipt["verifier_id"], str) or not receipt["verifier_id"].strip():
        raise MtpParameterManifestError("governed execution verifier_id is invalid")
    _require_sha256(receipt["verifier_sha256"], "governed execution verifier_sha256")
    disk_receipt = receipt["disk_budget_receipt"]
    disk_keys = {
        "schema_version", "receipt_sha256", "outcome", "child_exit_code",
        "runner_exit_code", "command", "child_pid", "child_start_time_ns",
        "child_executable_sha256",
    }
    if not isinstance(disk_receipt, Mapping) or set(disk_receipt) != disk_keys:
        raise MtpParameterManifestError("governed disk-budget receipt projection is not closed")
    if disk_receipt["schema_version"] != 7 or disk_receipt["outcome"] != "COMPLETED":
        raise MtpParameterManifestError("governed disk-budget runner did not complete")
    if type(disk_receipt["child_exit_code"]) is not int or disk_receipt["child_exit_code"] != 0:
        raise MtpParameterManifestError("governed disk-budget child exit is not zero")
    if type(disk_receipt["runner_exit_code"]) is not int or disk_receipt["runner_exit_code"] != 0:
        raise MtpParameterManifestError("governed disk-budget runner exit is not zero")
    if disk_receipt["command"] != receipt["command"]:
        raise MtpParameterManifestError("governed disk-budget command binding mismatch")
    if type(disk_receipt["child_pid"]) is not int or disk_receipt["child_pid"] <= 0:
        raise MtpParameterManifestError("governed disk-budget child pid is invalid")
    if type(disk_receipt["child_start_time_ns"]) is not int or disk_receipt["child_start_time_ns"] <= 0:
        raise MtpParameterManifestError("governed disk-budget child start time is invalid")
    _require_sha256(disk_receipt["child_executable_sha256"], "governed disk-budget executable_sha256")
    _require_sha256(receipt["disk_budget_receipt_sha256"], "governed disk-budget receipt_sha256")
    if disk_receipt["receipt_sha256"] != receipt["disk_budget_receipt_sha256"]:
        raise MtpParameterManifestError("governed disk-budget receipt identity mismatch")
    if receipt["process_identity"]["pid"] != disk_receipt["child_pid"] or receipt["process_identity"]["start_time_ns"] != disk_receipt["child_start_time_ns"]:
        raise MtpParameterManifestError("governed execution process identity mismatch")
    if receipt["process_identity"]["executable_sha256"] != disk_receipt["child_executable_sha256"]:
        raise MtpParameterManifestError("governed execution executable identity mismatch")
    _require_sha256(receipt["runner_module_sha256"], "governed runner module_sha256")
    validate_execution_candidate(receipt["execution_candidate"], manifest)
    candidate = receipt["execution_candidate"]
    if receipt["execution_candidate_sha256"] != candidate["receipt_sha256"]:
        raise MtpParameterManifestError("governed execution candidate hash mismatch")
    if receipt["run_id"] != candidate["run_id"] or receipt["update_count"] != candidate["update_count"]:
        raise MtpParameterManifestError("governed execution candidate identity mismatch")
    if manifest is not None and receipt["manifest_sha256"] != manifest["manifest_sha256"]:
        raise MtpParameterManifestError("governed execution manifest hash mismatch")
    if receipt["receipt_sha256"] != governed_execution_receipt_sha256(receipt):
        raise MtpParameterManifestError("governed execution receipt hash mismatch")
    if manifest is not None:
        validate_parameter_manifest(manifest)
        if receipt["manifest_sha256"] != manifest["manifest_sha256"]:
            raise MtpParameterManifestError("governed execution manifest hash mismatch")


@dataclass(frozen=True)
class GovernedExecutionBoundary:
    model_ids: tuple[int, ...]
    optimizer_ids: tuple[int, ...]
    before_state_sha256: str
    before_optimizer_state_sha256: str


def build_execution_candidate(
    manifest: Mapping[str, Any],
    run_id: str,
    source_path: str | Path,
    config_path: str | Path,
    boundary: GovernedExecutionBoundary,
    model: Any,
    optimizers: Any,
    *,
    update_count: int,
) -> dict[str, Any]:
    """Emit child-side candidate evidence; never certify process completion."""
    validate_parameter_manifest(manifest)
    if type(update_count) is not int or update_count < 1:
        raise MtpParameterManifestError("governed execution update_count must be positive")
    modules = model if isinstance(model, (list, tuple)) else [model]
    model_ids = tuple(id(module) for module in modules)
    optimizer_ids = tuple(id(item) for _, item in _optimizer_items(optimizers))
    if model_ids != boundary.model_ids or optimizer_ids != boundary.optimizer_ids:
        raise MtpParameterManifestError("governed execution boundary object identity changed")
    source_bytes = Path(source_path).read_bytes()
    config_bytes = Path(config_path).read_bytes()
    after_state_sha256 = execution_probe_sha256(model, optimizers)
    optimizer_state_sha256 = execution_probe_sha256([], optimizers)
    if after_state_sha256 == boundary.before_state_sha256:
        raise MtpParameterManifestError("governed execution update evidence is unchanged")
    receipt: dict[str, Any] = {
        "schema": "ember-mtp-execution-candidate-v1",
        "run_id": run_id,
        "update_count": update_count,
        "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "config_sha256": hashlib.sha256(config_bytes).hexdigest(),
        "manifest_sha256": manifest["manifest_sha256"],
        "before_state_sha256": boundary.before_state_sha256,
        "after_state_sha256": after_state_sha256,
        "before_optimizer_state_sha256": boundary.before_optimizer_state_sha256,
        "optimizer_state_sha256": optimizer_state_sha256,
    }
    receipt["receipt_sha256"] = execution_candidate_sha256(receipt)
    validate_execution_candidate(receipt, manifest)
    return receipt


def build_governed_execution_receipt(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Refuse the legacy child-minted completion API."""
    raise MtpParameterManifestError(
        "child cannot mint governed completion; external launcher verification is required"
    )


def finalize_governed_execution_receipt(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Refuse direct caller-authored governed parent creation."""
    raise MtpParameterManifestError(
        "only the external runner may mint governed execution receipts"
    )


def _finalize_governed_execution_receipt(
    manifest: Mapping[str, Any],
    candidate: Mapping[str, Any],
    *,
    command: Sequence[str],
    process_identity: Mapping[str, Any],
    child_exit_code: int,
    verifier_id: str,
    verifier_sha256: str,
    disk_budget_receipt: Mapping[str, Any],
    disk_budget_receipt_sha256: str,
    runner_module_sha256: str,
    capability: object,
) -> dict[str, Any]:
    """Mint completion authority from observations made after child exit."""
    if capability is not _GOVERNED_RUNNER_CAPABILITY:
        raise MtpParameterManifestError("governed receipt minting requires the external runner capability")
    validate_parameter_manifest(manifest)
    validate_execution_candidate(candidate, manifest)
    if type(child_exit_code) is not int:
        raise MtpParameterManifestError("external child exit code must be an integer")
    if not isinstance(command, Sequence) or isinstance(command, (str, bytes)):
        raise MtpParameterManifestError("external command must be a sequence")
    identity = dict(process_identity)
    if set(identity) != {"pid", "start_time_ns", "executable_sha256"}:
        raise MtpParameterManifestError("external process identity is not closed")
    command_list = [str(item) for item in command]
    command_sha256 = hashlib.sha256(
        json.dumps(command_list, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    receipt: dict[str, Any] = {
        "schema": "ember-mtp-governed-execution-receipt-v2",
        "authority": "external-disk-budget-runner",
        "status": "VERIFIED_COMPLETED" if child_exit_code == 0 else "VERIFIED_FAILED",
        "run_id": candidate["run_id"],
        "update_count": candidate["update_count"],
        "child_exit_code": child_exit_code,
        "manifest_sha256": manifest["manifest_sha256"],
        "execution_candidate": copy.deepcopy(dict(candidate)),
        "execution_candidate_sha256": candidate["receipt_sha256"],
        "command": command_list,
        "command_sha256": command_sha256,
        "process_identity": identity,
        "verifier_id": verifier_id,
        "verifier_sha256": verifier_sha256,
        "disk_budget_receipt": copy.deepcopy(dict(disk_budget_receipt)),
        "disk_budget_receipt_sha256": disk_budget_receipt_sha256,
        "runner_module_sha256": runner_module_sha256,
    }
    receipt["receipt_sha256"] = governed_execution_receipt_sha256(receipt)
    if child_exit_code != 0:
        raise MtpParameterManifestError("external child did not complete successfully")
    validate_governed_execution_receipt(receipt, manifest)
    return receipt
def execution_probe_sha256(model: Any, optimizers: Any) -> str:
    """Hash bounded live model/optimizer state probes at an execution boundary."""
    h = hashlib.sha256()
    modules = model if isinstance(model, (list, tuple)) else [model]
    for module_index, module in enumerate(modules):
        iterator = module.named_parameters(remove_duplicate=False)
        for name, parameter in iterator:
            tensor = parameter.detach()
            flat = tensor.reshape(-1)
            first = float(flat[0].item()) if flat.numel() else 0.0
            last = float(flat[-1].item()) if flat.numel() else 0.0
            total = float(tensor.sum().item())
            abs_total = float(tensor.abs().sum().item())
            h.update(json.dumps({
                "module": module_index, "name": str(name), "shape": list(tensor.shape),
                "dtype": str(tensor.dtype), "first": first, "last": last,
                "sum": total, "abs_sum": abs_total,
            }, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    for optimizer_name, optimizer in _optimizer_items(optimizers):
        state = getattr(optimizer, "state", {})
        for parameter_id, values in sorted(state.items(), key=lambda item: str(item[0])):
            h.update(str(optimizer_name).encode("utf-8"))
            h.update(str(parameter_id).encode("utf-8"))
            for key, value in sorted(values.items(), key=lambda item: str(item[0])):
                if hasattr(value, "detach"):
                    tensor = value.detach()
                    flat = tensor.reshape(-1)
                    summary = (str(key), str(tensor.dtype), list(tensor.shape),
                               float(flat[0].item()) if flat.numel() else 0.0,
                               float(flat[-1].item()) if flat.numel() else 0.0,
                               float(tensor.sum().item()))
                else:
                    summary = (str(key), repr(value))
                h.update(repr(summary).encode("utf-8"))
    return h.hexdigest()


def begin_governed_execution(model: Any, optimizers: Any) -> GovernedExecutionBoundary:
    modules = model if isinstance(model, (list, tuple)) else [model]
    return GovernedExecutionBoundary(
        model_ids=tuple(id(module) for module in modules),
        optimizer_ids=tuple(id(item) for _, item in _optimizer_items(optimizers)),
        before_state_sha256=execution_probe_sha256(model, optimizers),
        before_optimizer_state_sha256=execution_probe_sha256([], optimizers),
    )


def _executed_run_receipt_bytes(receipt: Mapping[str, Any]) -> bytes:
    payload = copy.deepcopy(dict(receipt))
    payload.pop("receipt_sha256", None)
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def executed_run_receipt_sha256(receipt: Mapping[str, Any]) -> str:
    return hashlib.sha256(_executed_run_receipt_bytes(receipt)).hexdigest()


def build_executed_run_receipt(
    manifest: Mapping[str, Any], governed_execution_receipt: Mapping[str, Any]
) -> dict[str, Any]:
    """Derive pricing input only from a validated governed parent receipt."""
    validate_parameter_manifest(manifest)
    validate_governed_execution_receipt(governed_execution_receipt, manifest)
    receipt: dict[str, Any] = {
        "schema": "ember-mtp-executed-run-receipt-v1",
        "evidence": "authorized-executed-run",
        "run_id": governed_execution_receipt["run_id"],
        "update_count": governed_execution_receipt["update_count"],
        "source_sha256": governed_execution_receipt["execution_candidate"]["source_sha256"],
        "config_sha256": governed_execution_receipt["execution_candidate"]["config_sha256"],
        "manifest_sha256": manifest["manifest_sha256"],
        "governed_execution_receipt": copy.deepcopy(dict(governed_execution_receipt)),
        "governed_execution_receipt_sha256": governed_execution_receipt["receipt_sha256"],
    }
    receipt["receipt_sha256"] = executed_run_receipt_sha256(receipt)
    validate_executed_run_receipt(receipt, manifest)
    return receipt


def validate_executed_run_receipt(
    receipt: Mapping[str, Any], manifest: Mapping[str, Any] | None = None
) -> None:
    if not isinstance(receipt, Mapping) or set(receipt) != _EXECUTED_RUN_KEYS:
        raise MtpParameterManifestError("executed-run evidence schema is not closed")
    if receipt["schema"] != "ember-mtp-executed-run-receipt-v1" or receipt["evidence"] != "authorized-executed-run":
        raise MtpParameterManifestError("executed-run evidence is not authorized")
    validate_governed_execution_receipt(receipt["governed_execution_receipt"], manifest)
    parent = receipt["governed_execution_receipt"]
    if receipt["governed_execution_receipt_sha256"] != parent["receipt_sha256"]:
        raise MtpParameterManifestError("executed-run governed parent hash mismatch")
    for key in ("run_id", "update_count", "source_sha256", "config_sha256", "manifest_sha256"):
        candidate = parent["execution_candidate"]
        expected = manifest["manifest_sha256"] if key == "manifest_sha256" and manifest is not None else candidate.get(key)
        if receipt[key] != expected:
            raise MtpParameterManifestError(f"executed-run evidence {key} mismatch")
    _require_sha256(receipt["receipt_sha256"], "executed-run evidence receipt_sha256")
    if receipt["receipt_sha256"] != executed_run_receipt_sha256(receipt):
        raise MtpParameterManifestError("executed-run evidence receipt hash mismatch")
    if manifest is not None:
        validate_parameter_manifest(manifest)
        if receipt["manifest_sha256"] != manifest["manifest_sha256"]:
            raise MtpParameterManifestError("executed-run evidence manifest hash mismatch")

def _pricing_receipt_bytes(receipt: Mapping[str, Any]) -> bytes:
    payload = copy.deepcopy(dict(receipt))
    payload.pop("receipt_sha256", None)
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def pricing_receipt_sha256(receipt: Mapping[str, Any]) -> str:
    """Hash canonical path-free pricing evidence, excluding its self-hash."""
    return hashlib.sha256(_pricing_receipt_bytes(receipt)).hexdigest()


def build_pricing_receipt(
    manifest: Mapping[str, Any], executed_run_receipt: Mapping[str, Any]
) -> dict[str, Any]:
    """Create pricing evidence bound to immutable completed-run evidence."""
    validate_parameter_manifest(manifest)
    if not isinstance(executed_run_receipt, Mapping):
        raise MtpParameterManifestError("executed-run evidence is required")
    validate_executed_run_receipt(executed_run_receipt, manifest)
    accounting = dict(manifest["parameter_accounting"])
    receipt: dict[str, Any] = {
        "schema": "ember-mtp-parameter-pricing-receipt-v1",
        "evidence": "authorized-executed-run",
        "run_id": executed_run_receipt["run_id"],
        "update_count": executed_run_receipt["update_count"],
        "source_sha256": executed_run_receipt["source_sha256"],
        "config_sha256": executed_run_receipt["config_sha256"],
        "manifest_sha256": manifest["manifest_sha256"],
        "executed_run_receipt": copy.deepcopy(dict(executed_run_receipt)),
        "executed_run_receipt_sha256": executed_run_receipt["receipt_sha256"],
        "parameter_accounting": accounting,
        "realized_parameter_count": accounting["realized"],
        "optimizer_parameter_count": manifest["optimizer"]["parameter_count"],
    }
    receipt["receipt_sha256"] = pricing_receipt_sha256(receipt)

    return receipt

def write_pricing_receipt(path: str | Path, manifest: Mapping[str, Any], executed_run_receipt: Mapping[str, Any]) -> dict[str, Any]:
    receipt = build_pricing_receipt(manifest, executed_run_receipt)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def validate_pricing_receipt(receipt: Mapping[str, Any], manifest: Mapping[str, Any] | None = None) -> None:
    if not isinstance(receipt, Mapping):
        raise MtpParameterManifestError("pricing receipt must be an object")
    expected_keys = {
        "schema", "evidence", "run_id", "update_count", "source_sha256",
        "config_sha256", "manifest_sha256", "executed_run_receipt",
        "executed_run_receipt_sha256", "parameter_accounting",
        "realized_parameter_count", "optimizer_parameter_count", "receipt_sha256",
    }
    if set(receipt) != expected_keys:
        raise MtpParameterManifestError("pricing receipt schema is not closed")
    if receipt["schema"] != "ember-mtp-parameter-pricing-receipt-v1" or receipt["evidence"] != "authorized-executed-run":
        raise MtpParameterManifestError("pricing receipt evidence/schema is invalid")
    if not isinstance(receipt["run_id"], str) or not receipt["run_id"].strip():
        raise MtpParameterManifestError("pricing receipt run_id is invalid")
    for key in ("source_sha256", "config_sha256", "manifest_sha256", "executed_run_receipt_sha256", "receipt_sha256"):
        _require_sha256(receipt[key], f"pricing receipt {key}")
    validate_executed_run_receipt(receipt["executed_run_receipt"], manifest)
    executed = receipt["executed_run_receipt"]
    if receipt["executed_run_receipt_sha256"] != executed["receipt_sha256"]:
        raise MtpParameterManifestError("pricing receipt executed-run hash mismatch")
    for key in ("run_id", "update_count", "source_sha256", "config_sha256", "manifest_sha256"):
        if receipt[key] != executed[key]:
            raise MtpParameterManifestError(f"pricing receipt {key} mismatch")
    if receipt["receipt_sha256"] != pricing_receipt_sha256(receipt):
        raise MtpParameterManifestError("pricing receipt hash mismatch")
    if manifest is not None:
        validate_parameter_manifest(manifest)
        if receipt["manifest_sha256"] != manifest["manifest_sha256"]:
            raise MtpParameterManifestError("pricing receipt manifest hash mismatch")
        if dict(receipt["parameter_accounting"]) != dict(manifest["parameter_accounting"]):
            raise MtpParameterManifestError("pricing receipt accounting mismatch")
        if receipt["optimizer_parameter_count"] != manifest["optimizer"]["parameter_count"]:
            raise MtpParameterManifestError("pricing receipt optimizer count mismatch")
    accounting = receipt["parameter_accounting"]
    if not isinstance(accounting, Mapping) or set(accounting) != _ACCOUNTING_KEYS:
        raise MtpParameterManifestError("pricing receipt accounting schema is invalid")
    if receipt["realized_parameter_count"] != accounting["realized"]:
        raise MtpParameterManifestError("pricing receipt realized count mismatch")
