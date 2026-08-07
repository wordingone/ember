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
    "embed_tokens",
    "extra",
    "head",
    "layers",
    "lm_head",
    "model",
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


def write_parameter_manifest(path: str | Path, model: Any, optimizers: Any, config: Mapping[str, Any]) -> dict[str, Any]:
    manifest = build_parameter_manifest(model, optimizers, config)
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
