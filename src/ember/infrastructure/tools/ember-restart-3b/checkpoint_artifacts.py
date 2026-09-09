# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Atomically publish and fail-closed restore sparse checkpoint artifacts."""

from __future__ import annotations

import ctypes
import errno
import hashlib
import inspect
import json
import os
import shutil
import stat
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Mapping

import torch
from checkpoint_scratch import ScratchCappedWriter as _ScratchCappedWriter
from durable_io import atomic_replace_durable
_REPO_IMPORT_HOME = Path(__file__).resolve().parents[5]
if str(_REPO_IMPORT_HOME) not in sys.path:
    sys.path.insert(0, str(_REPO_IMPORT_HOME))
from src.ember.model.ember_v0_model import EXPERT_NAMES, UnifiedDecoder
# issue2015 exact-local-import:src/ember/infrastructure/tools/ember-restart-3b/parameter_counter.py
import importlib.util as _ember_1601eccb5605602b_importlib
import sys as _ember_1601eccb5605602b_sys
from pathlib import Path as _ember_1601eccb5605602b_Path
_ember_1601eccb5605602b_path = _ember_1601eccb5605602b_Path(__file__).resolve().parent.joinpath('parameter_counter.py')
if not _ember_1601eccb5605602b_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/infrastructure/tools/ember-restart-3b/parameter_counter.py')
_ember_1601eccb5605602b_aliases = ('_ember_issue2015_1601eccb5605602b', 'parameter_counter', 'src.ember.infrastructure.tools.ember-restart-3b.parameter_counter')
_ember_1601eccb5605602b_existing = []
for _ember_1601eccb5605602b_alias in _ember_1601eccb5605602b_aliases:
    _ember_1601eccb5605602b_candidate = _ember_1601eccb5605602b_sys.modules.get(_ember_1601eccb5605602b_alias)
    if _ember_1601eccb5605602b_candidate is not None and all(_ember_1601eccb5605602b_candidate is not item for item in _ember_1601eccb5605602b_existing):
        _ember_1601eccb5605602b_existing.append(_ember_1601eccb5605602b_candidate)
if len(_ember_1601eccb5605602b_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/infrastructure/tools/ember-restart-3b/parameter_counter.py')
if _ember_1601eccb5605602b_existing:
    _ember_1601eccb5605602b_module = _ember_1601eccb5605602b_existing[0]
    _ember_1601eccb5605602b_observed = getattr(_ember_1601eccb5605602b_module, '__file__', None)
    if _ember_1601eccb5605602b_observed is None or _ember_1601eccb5605602b_Path(_ember_1601eccb5605602b_observed).resolve() != _ember_1601eccb5605602b_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/infrastructure/tools/ember-restart-3b/parameter_counter.py')
else:
    _ember_1601eccb5605602b_spec = _ember_1601eccb5605602b_importlib.spec_from_file_location('_ember_issue2015_1601eccb5605602b', _ember_1601eccb5605602b_path)
    if _ember_1601eccb5605602b_spec is None or _ember_1601eccb5605602b_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/infrastructure/tools/ember-restart-3b/parameter_counter.py')
    _ember_1601eccb5605602b_module = _ember_1601eccb5605602b_importlib.module_from_spec(_ember_1601eccb5605602b_spec)
    for _ember_1601eccb5605602b_alias in _ember_1601eccb5605602b_aliases:
        _ember_1601eccb5605602b_prior = _ember_1601eccb5605602b_sys.modules.get(_ember_1601eccb5605602b_alias)
        if _ember_1601eccb5605602b_prior is not None and _ember_1601eccb5605602b_prior is not _ember_1601eccb5605602b_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/infrastructure/tools/ember-restart-3b/parameter_counter.py')
        _ember_1601eccb5605602b_sys.modules[_ember_1601eccb5605602b_alias] = _ember_1601eccb5605602b_module
    try:
        _ember_1601eccb5605602b_spec.loader.exec_module(_ember_1601eccb5605602b_module)
    except BaseException:
        for _ember_1601eccb5605602b_alias in _ember_1601eccb5605602b_aliases:
            if _ember_1601eccb5605602b_sys.modules.get(_ember_1601eccb5605602b_alias) is _ember_1601eccb5605602b_module:
                _ember_1601eccb5605602b_sys.modules.pop(_ember_1601eccb5605602b_alias, None)
        raise
for _ember_1601eccb5605602b_alias in _ember_1601eccb5605602b_aliases:
    _ember_1601eccb5605602b_prior = _ember_1601eccb5605602b_sys.modules.get(_ember_1601eccb5605602b_alias)
    if _ember_1601eccb5605602b_prior is not None and _ember_1601eccb5605602b_prior is not _ember_1601eccb5605602b_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/infrastructure/tools/ember-restart-3b/parameter_counter.py')
    _ember_1601eccb5605602b_sys.modules[_ember_1601eccb5605602b_alias] = _ember_1601eccb5605602b_module
SPECIALIST_VERIFICATION_FIELDS = getattr(_ember_1601eccb5605602b_module, 'SPECIALIST_VERIFICATION_FIELDS')
measure_parameter_counts = getattr(_ember_1601eccb5605602b_module, 'measure_parameter_counts')
validate_p2b_stream_episode = getattr(_ember_1601eccb5605602b_module, 'validate_p2b_stream_episode')
validate_realization_receipt = getattr(_ember_1601eccb5605602b_module, 'validate_realization_receipt')
# issue2015 exact-local-import-end:src/ember/infrastructure/tools/ember-restart-3b/parameter_counter.py
from specialist_stream import (
    SELECTION_CURSOR_SCHEMA_VERSION,
    TRAINING_CURSOR_SCHEMA_VERSION,
)

_STAGING_LEASE = ".writer-lease.json"
_ALLOWED_CANDIDATE_METADATA = {"parameter-counter-receipt.json"}
_FAILURE_EVIDENCE_LIMIT = 64 * 1024
_STREAMING_OVERHEAD_BYTES = 64 * 1024 * 1024
_OWNER_SHARDED_OPTIMIZER_STATE_LAYOUT = "owner-sharded-v1"
_PACKED_FRESH_GENESIS_LINEAGE_SCHEMA = (
    "ember-issue1413-packed-fresh-genesis-specialist-lineage-v1"
)
_PACKED_FRESH_GENESIS_MODE = "FRESH_GENESIS_NO_EXTERNAL_PREDECESSOR"
_PACKED_CURSOR_FIELDS = {
    "selected_ordinal", "global_step", "tokens_seen",
    "processed_tokens_seen", "pack_ordinal",
}
_PACKED_FRESH_GENESIS_LINEAGE_FIELDS = {
    "schema_version", "lineage_mode", "source_commit",
    "model_config_sha256", "seed", "active_expert", "trained_expert_ids",
    "genesis_lineage_sha256", "selection_receipt_sha256",
    "execution_record_order_sha256", "execution_tokens_sha256",
    "pack_sequence_sha256", "initial_cursor", "checkpoint_cursor",
    "lineage_sha256",
}

_FAILURE_COMPARISON_OPERAND_FIELDS = {
    "derived_byte_bound_bytes",
    "derived_byte_bound_inputs",
    "projected_storage_floor_bytes",
    "projected_storage_floor_inputs",
    "staged_shard_bytes",
    "available_commit_bytes",
    "required_commit_bytes",
}
_FAILURE_DERIVED_INPUT_FIELDS = {
    "max_serialized_bytes",
    "max_transient_scratch_bytes",
    "active_parameters",
    "model_config_sha256",
    "contract_sha256",
    "optimizer_state_layout",
}
_FAILURE_PROJECTED_INPUT_FIELDS = {
    "route_multiplier",
    "active_expert",
    "optimizer_state_layout",
    "optimizer_state_tensor_storage_lower_bound_bytes",
    "projected_optimizer_state_tensor_storage_lower_bound_bytes",
    "optimizer_state_tensor_storage_by_route_bytes",
    "per_shard_tensor_storage_lower_bound_bytes",
    "retained_shard_paths",
}


def _failure_operand_int(value: Any, *, name: str, nullable: bool = True) -> int | None:
    if value is None and nullable:
        return None
    if type(value) is not int or value < 0:
        raise ValueError(f"checkpoint failure operand {name} must be a nonnegative integer")
    return value


def _failure_operand_path(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or "\\" in value
        or value.startswith("/")
        or ":" in value
        or any(part in {"", ".", ".."} for part in value.split("/"))
    ):
        raise ValueError(f"checkpoint failure operand {name} must be a relative path")
    return value


def _empty_failure_comparison_operands() -> dict[str, Any]:
    return {
        "derived_byte_bound_bytes": None,
        "derived_byte_bound_inputs": {
            "max_serialized_bytes": None,
            "max_transient_scratch_bytes": None,
            "active_parameters": None,
            "model_config_sha256": None,
            "contract_sha256": None,
            "optimizer_state_layout": None,
        },
        "projected_storage_floor_bytes": None,
        "projected_storage_floor_inputs": {
            "route_multiplier": None,
            "active_expert": None,
            "optimizer_state_layout": None,
            "optimizer_state_tensor_storage_lower_bound_bytes": None,
            "projected_optimizer_state_tensor_storage_lower_bound_bytes": None,
            "optimizer_state_tensor_storage_by_route_bytes": {},
            "per_shard_tensor_storage_lower_bound_bytes": {},
            "retained_shard_paths": [],
        },
        "staged_shard_bytes": [],
        "available_commit_bytes": None,
        "required_commit_bytes": None,
    }


def _normalize_failure_comparison_operands(value: Mapping[str, Any] | None) -> dict[str, Any]:
    if value is None:
        value = _empty_failure_comparison_operands()
    if not isinstance(value, Mapping) or set(value) != _FAILURE_COMPARISON_OPERAND_FIELDS:
        raise ValueError("checkpoint failure comparison operands have an invalid shape")

    derived = value["derived_byte_bound_inputs"]
    if not isinstance(derived, Mapping) or set(derived) != _FAILURE_DERIVED_INPUT_FIELDS:
        raise ValueError("checkpoint failure derived-bound inputs have an invalid shape")
    projected = value["projected_storage_floor_inputs"]
    if not isinstance(projected, Mapping) or set(projected) != _FAILURE_PROJECTED_INPUT_FIELDS:
        raise ValueError("checkpoint failure projected-floor inputs have an invalid shape")

    normalized_derived: dict[str, Any] = {
        "max_serialized_bytes": _failure_operand_int(derived["max_serialized_bytes"], name="max_serialized_bytes"),
        "max_transient_scratch_bytes": _failure_operand_int(derived["max_transient_scratch_bytes"], name="max_transient_scratch_bytes"),
        "active_parameters": _failure_operand_int(derived["active_parameters"], name="active_parameters"),
        "model_config_sha256": derived["model_config_sha256"],
        "contract_sha256": derived["contract_sha256"],
        "optimizer_state_layout": derived["optimizer_state_layout"],
    }
    for field in ("model_config_sha256", "contract_sha256"):
        digest = normalized_derived[field]
        if digest is not None:
            _sha256_value(digest, name=f"checkpoint failure {field}")
    if normalized_derived["optimizer_state_layout"] is not None and (
        not isinstance(normalized_derived["optimizer_state_layout"], str)
        or not normalized_derived["optimizer_state_layout"]
    ):
        raise ValueError("checkpoint failure optimizer state layout is invalid")

    route_bytes = projected["optimizer_state_tensor_storage_by_route_bytes"]
    shard_bytes = projected["per_shard_tensor_storage_lower_bound_bytes"]
    if not isinstance(route_bytes, Mapping) or not isinstance(shard_bytes, Mapping):
        raise ValueError("checkpoint failure projected tensor maps have an invalid shape")
    normalized_route_bytes = {
        _failure_operand_path(name, name="optimizer route"): _failure_operand_int(
            amount, name="optimizer route bytes", nullable=False
        )
        for name, amount in sorted(route_bytes.items())
    }
    normalized_shard_bytes = {
        _failure_operand_path(name, name="projected shard"): _failure_operand_int(
            amount, name="projected shard bytes", nullable=False
        )
        for name, amount in sorted(shard_bytes.items())
    }
    retained = projected["retained_shard_paths"]
    if not isinstance(retained, list):
        raise ValueError("checkpoint failure retained shard paths have an invalid shape")
    normalized_retained_values = [
        _failure_operand_path(path, name="retained shard") for path in retained
    ]
    if len(normalized_retained_values) != len(set(normalized_retained_values)):
        raise ValueError("checkpoint failure retained shard paths are duplicated")
    normalized_retained = sorted(normalized_retained_values)
    normalized_projected: dict[str, Any] = {
        "route_multiplier": _failure_operand_int(projected["route_multiplier"], name="route_multiplier"),
        "active_expert": projected["active_expert"],
        "optimizer_state_layout": projected["optimizer_state_layout"],
        "optimizer_state_tensor_storage_lower_bound_bytes": _failure_operand_int(
            projected["optimizer_state_tensor_storage_lower_bound_bytes"],
            name="optimizer state floor",
        ),
        "projected_optimizer_state_tensor_storage_lower_bound_bytes": _failure_operand_int(
            projected["projected_optimizer_state_tensor_storage_lower_bound_bytes"],
            name="projected optimizer state floor",
        ),
        "optimizer_state_tensor_storage_by_route_bytes": normalized_route_bytes,
        "per_shard_tensor_storage_lower_bound_bytes": normalized_shard_bytes,
        "retained_shard_paths": normalized_retained,
    }
    if normalized_projected["active_expert"] is not None and (
        not isinstance(normalized_projected["active_expert"], str)
        or not normalized_projected["active_expert"]
    ):
        raise ValueError("checkpoint failure active expert is invalid")
    if normalized_projected["optimizer_state_layout"] is not None and (
        not isinstance(normalized_projected["optimizer_state_layout"], str)
        or not normalized_projected["optimizer_state_layout"]
    ):
        raise ValueError("checkpoint failure projected optimizer layout is invalid")

    staged = value["staged_shard_bytes"]
    if not isinstance(staged, list):
        raise ValueError("checkpoint failure staged shard inventory has an invalid shape")
    normalized_staged: list[dict[str, Any]] = []
    seen_staged: set[str] = set()
    for item in staged:
        if not isinstance(item, Mapping) or set(item) != {"path", "bytes"}:
            raise ValueError("checkpoint failure staged shard inventory has an invalid row")
        path = _failure_operand_path(item["path"], name="staged shard")
        if path in seen_staged:
            raise ValueError("checkpoint failure staged shard inventory is duplicated")
        seen_staged.add(path)
        normalized_staged.append({"path": path, "bytes": _failure_operand_int(item["bytes"], name="staged shard bytes", nullable=False)})
    normalized_staged.sort(key=lambda item: item["path"])

    normalized = {
        "derived_byte_bound_bytes": _failure_operand_int(value["derived_byte_bound_bytes"], name="derived byte bound"),
        "derived_byte_bound_inputs": normalized_derived,
        "projected_storage_floor_bytes": _failure_operand_int(value["projected_storage_floor_bytes"], name="projected storage floor"),
        "projected_storage_floor_inputs": normalized_projected,
        "staged_shard_bytes": normalized_staged,
        "available_commit_bytes": _failure_operand_int(value["available_commit_bytes"], name="available commit"),
        "required_commit_bytes": _failure_operand_int(value["required_commit_bytes"], name="required commit"),
    }
    if (
        normalized["available_commit_bytes"] is not None
        and normalized["required_commit_bytes"] is None
    ) or (
        normalized["available_commit_bytes"] is None
        and normalized["required_commit_bytes"] is not None
    ):
        raise ValueError("checkpoint failure host commit operands must be paired")
    return normalized


def _merge_failure_comparison_operands(
    base: Mapping[str, Any], update: Mapping[str, Any] | None
) -> dict[str, Any]:
    current = _normalize_failure_comparison_operands(base)
    if update is None:
        return current
    incoming = _normalize_failure_comparison_operands(update)
    for field in ("derived_byte_bound_bytes", "projected_storage_floor_bytes", "available_commit_bytes", "required_commit_bytes"):
        if incoming[field] is not None:
            current[field] = incoming[field]
    for field in ("derived_byte_bound_inputs", "projected_storage_floor_inputs"):
        current[field] = {
            **current[field],
            **{
                key: val
                for key, val in incoming[field].items()
                if val not in (None, {}, [])
            },
        }
    if incoming["staged_shard_bytes"]:
        current["staged_shard_bytes"] = incoming["staged_shard_bytes"]
    return _normalize_failure_comparison_operands(current)


class _CheckpointWriteRefusal(RuntimeError):
    def __init__(self, message: str, *, comparison_operands: Mapping[str, Any]) -> None:
        self.comparison_operands = _normalize_failure_comparison_operands(comparison_operands)
        super().__init__(message)


class CheckpointIdentityMismatch(ValueError):
    """A checkpoint's recorded cond3 identity manifest binding diverges from its
    on-disk bytes, or the binding is absent entirely.

    Raised by ``load_checkpoint_artifacts`` BEFORE any model/optimizer mutation.
    This is additive to (never a replacement for) the existing v3/v4 receipt's
    optimizer-contract / expert-hash / ``_validated_records`` checks -- it binds
    the checkpoint to the cond3 identity manifest surface (``checkpoint.byte_sha256``)
    that increments 1/1b/2a/2b established, closing the gap where this module's own
    internal receipt could round-trip while carrying an identity the manifest would
    reject.
    """


class CheckpointDeferredLowCommit(RuntimeError):
    """Host commit headroom is below the checkpoint's measured streaming peak plus
    its frozen reserve at admission time (:func:`checkpoint_commit_preflight`).

    Distinct from a writer, counter, or storage failure: no staging directory or
    published bytes are ever created for this attempt (the preflight always runs
    before ``root.mkdir()``), so the caller may defer this publication to the next
    bounded checkpoint boundary -- preserving the last known-good checkpoint
    untouched and selectable -- instead of aborting the run. Still a ``RuntimeError``
    so any caller that only distinguishes failure-vs-success is unaffected; callers
    that want DEFERRED_LOW_COMMIT semantics catch this subclass explicitly.
    """

    def __init__(
        self,
        *,
        available_commit_bytes: int,
        required_commit_bytes: int,
        streaming_peak_bytes: int,
        reserve_bytes: int,
        comparison_operands: Mapping[str, Any] | None = None,
    ) -> None:
        self.available_commit_bytes = available_commit_bytes
        self.required_commit_bytes = required_commit_bytes
        self.streaming_peak_bytes = streaming_peak_bytes
        self.reserve_bytes = reserve_bytes
        self.comparison_operands = _normalize_failure_comparison_operands(
            comparison_operands
        ) if comparison_operands is not None else None
        super().__init__(
            "checkpoint host commit reserve is insufficient: "
            f"available={available_commit_bytes}, required={required_commit_bytes}, "
            f"streaming_peak={streaming_peak_bytes}, reserve={reserve_bytes}"
        )


def _is_link_or_reparse(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError as error:
        raise ValueError(f"checkpoint path cannot be inspected: {path}") from error
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def _path_has_link(path: Path, root: Path) -> bool:
    current = path
    while current != root:
        if _is_link_or_reparse(current):
            return True
        current = current.parent
    return _is_link_or_reparse(root)


def _admitted_checkpoint_root(root: Path) -> Path:
    lexical = Path(root)
    resolved = lexical.resolve()
    for path in (lexical, resolved):
        if any(str(part).casefold() == ".checkpoint-quarantine" for part in path.parts):
            raise ValueError("quarantined checkpoint is not admitted or selectable")
    return resolved


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _bind_checkpoint_identity(published_root: Path, receipt: Mapping[str, Any]) -> dict[str, Any]:
    """Bind ``checkpoint.byte_sha256`` to the just-published manifest bytes on disk.

    Reuses ``_sha256``'s streaming disk-hash discipline against the FINAL published
    location -- never a passed-in constant, never the pre-publish staging candidate
    -- so the identity binding proves what is actually selectable on disk. This is
    the cond3 identity manifest surface's ``checkpoint.byte_sha256`` field (same
    convention as ``scripts/ember_01_identity/parameter_identity_binding.py``'s
    ``subject_checkpoint_sha256``: the checkpoint manifest file's own bytes are the
    checkpoint's identity subject). Additive -- every existing receipt field is
    preserved untouched.
    """
    manifest_path = published_root / "checkpoint-manifest.json"
    byte_sha256 = _sha256(manifest_path)
    return {**dict(receipt), "checkpoint": {"byte_sha256": byte_sha256}}


def published_checkpoint_receipt(published_root: Path) -> dict[str, Any]:
    """Reconstruct the complete load receipt from frozen published bytes.

    ``checkpoint.byte_sha256`` cannot live inside the manifest whose bytes it
    identifies. Reopening consumers therefore derive that outer binding from
    the exact manifest snapshot they parse, rather than dropping the writer's
    out-of-band identity field.
    """

    published_root = _admitted_checkpoint_root(published_root)
    manifest_path = published_root / "checkpoint-manifest.json"
    if _is_link_or_reparse(manifest_path):
        raise CheckpointIdentityMismatch("checkpoint manifest cannot be a symlink or reparse point")
    try:
        manifest_bytes = manifest_path.read_bytes()
        manifest = json.loads(manifest_bytes)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise CheckpointIdentityMismatch("checkpoint manifest is not valid published JSON") from error
    if not isinstance(manifest, dict):
        raise CheckpointIdentityMismatch("checkpoint manifest must be a JSON object")
    byte_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    return {
        **manifest,
        "checkpoint_manifest_sha256": byte_sha256,
        "checkpoint": {"byte_sha256": byte_sha256},
    }


def _select_detached_state(
    state: Mapping[str, torch.Tensor],
    predicate: Callable[[str], bool],
) -> dict[str, torch.Tensor]:
    """Select storage-sharing detached views; never clone the model to host memory."""

    return {name: value.detach() for name, value in state.items() if predicate(name)}


def _tensor_bytes(value: object) -> int:
    if isinstance(value, torch.Tensor):
        return int(value.numel() * value.element_size())
    if isinstance(value, Mapping):
        return max((_tensor_bytes(item) for item in value.values()), default=0)
    if isinstance(value, (list, tuple)):
        return max((_tensor_bytes(item) for item in value), default=0)
    return 0


def _unique_tensor_storage_bytes(value: object) -> int:
    """Return the tensor-storage lower bound for one serialized shard payload."""

    seen: set[tuple[str, int, int]] = set()

    def visit(item: object) -> int:
        if isinstance(item, torch.Tensor):
            storage = item.untyped_storage()
            size = int(storage.nbytes())
            key = (str(item.device), int(storage.data_ptr()), size)
            if key in seen:
                return 0
            seen.add(key)
            return size
        if isinstance(item, Mapping):
            return sum(visit(child) for child in item.values())
        if isinstance(item, (list, tuple)):
            return sum(visit(child) for child in item)
        return 0

    return visit(value)


def _optimizer_tensor_storage_by_route_for_write(
    *,
    model: UnifiedDecoder,
    optimizer: torch.optim.Optimizer,
    shard_storage_lower_bounds: Mapping[str, int],
    optimizer_state_layout: str,
) -> dict[str, int]:
    """Per-route optimizer tensor-storage bytes, consistent with the shards actually written.

    ``_optimizer_tensor_storage_by_route`` measures the live in-memory
    optimizer, where a tensor an optimizer shares across parameters --
    bitsandbytes AdamW8bit's ``qmap1``/``qmap2`` -- is still one shared
    object and dedupes to a single copy. Owner-sharded layout detaches each
    owner's state independently before writing (``_detach_optimizer_value``
    calls ``.cpu()`` per reference), which breaks that shared identity: the
    written ``optimizer-state-{owner}.pt`` files each carry their own
    physical copy. Re-deriving route bytes from the live optimizer after
    that split understates what is actually on disk and desyncs from the
    independently reopened per-shard measurement this projection is later
    checked against. For owner-sharded layout, read the real bytes already
    measured per shard instead of re-measuring the live optimizer.
    """

    if optimizer_state_layout == _OWNER_SHARDED_OPTIMIZER_STATE_LAYOUT:
        return {
            owner: shard_storage_lower_bounds.get(f"optimizer-state-{owner}.pt", 0)
            for owner in ("shared", *EXPERT_NAMES)
        }
    return _optimizer_tensor_storage_by_route(model, optimizer)


def _optimizer_state_actual_tensor_storage_bytes(
    *,
    optimizer_file_payload: Mapping[str, Any],
    shard_storage_lower_bounds: Mapping[str, int],
    optimizer_state_layout: str,
) -> int:
    """The realized optimizer-state tensor-storage floor for what is actually written.

    Owner-sharded layout writes one independent ``optimizer-state-{owner}.pt``
    file per owner. Any tensor an optimizer shares across parameters -- for
    example bitsandbytes AdamW8bit's ``qmap1``/``qmap2`` quantization lookup
    tables, which are the exact same tensor object on every 8-bit parameter's
    state -- is therefore physically duplicated once per owner file on disk,
    not deduplicated the way a single unsplit blob would dedupe it. The
    realized floor must sum the real per-shard bounds already measured at
    write time (``shard_storage_lower_bounds``); deduping a blob that will
    never be serialized as one file understates the owner-sharded layout's
    true disk footprint and desyncs from the independently re-measured
    per-shard total this projection is later checked against.
    """

    if optimizer_state_layout == _OWNER_SHARDED_OPTIMIZER_STATE_LAYOUT:
        return sum(
            bound
            for path, bound in shard_storage_lower_bounds.items()
            if path.startswith("optimizer-state-")
        )
    return _unique_tensor_storage_bytes(optimizer_file_payload)


def _optimizer_owner_for_parameter(name: str) -> str:
    for expert_name in EXPERT_NAMES:
        if f".experts.{expert_name}." in name:
            return expert_name
    return "shared"


def _detach_optimizer_value(value: object) -> object:
    if isinstance(value, torch.Tensor):
        return value.detach().cpu()
    if isinstance(value, Mapping):
        return {str(key): _detach_optimizer_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_detach_optimizer_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_detach_optimizer_value(item) for item in value)
    return value


def _optimizer_owner_payloads(
    model: UnifiedDecoder,
    optimizer: torch.optim.Optimizer,
    optimizer_contract: Mapping[str, Any],
    optimizer_realization: Mapping[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    """Project live optimizer state into closed, name-addressed owner shards."""

    parameter_names = {id(parameter): name for name, parameter in model.named_parameters()}
    by_owner: dict[str, dict[str, Any]] = {
        "shared": {},
        **{name: {} for name in EXPERT_NAMES},
    }
    owner_by_parameter: dict[str, str] = {}
    for parameter, state in optimizer.state.items():
        name = parameter_names.get(id(parameter))
        if name is None:
            raise ValueError("optimizer state contains a parameter outside the checkpoint model")
        owner = _optimizer_owner_for_parameter(name)
        if name in owner_by_parameter:
            raise ValueError(f"optimizer parameter is duplicated in owner projection: {name}")
        owner_by_parameter[name] = owner
        by_owner[owner][name] = _detach_optimizer_value(state)

    parameter_groups: list[dict[str, Any]] = []
    for group in optimizer.param_groups:
        descriptor = {
            str(key): _detach_optimizer_value(value)
            for key, value in group.items()
            if key != "params"
        }
        try:
            descriptor["param_names"] = [
                parameter_names[id(parameter)] for parameter in group["params"]
            ]
        except (KeyError, TypeError) as error:
            raise ValueError("optimizer parameter group contains a foreign parameter") from error
        parameter_groups.append(descriptor)

    payloads: dict[str, dict[str, Any]] = {}
    for owner in ("shared", *EXPERT_NAMES):
        if not by_owner[owner]:
            continue
        payloads[owner] = {
            "schema_version": "ember-optimizer-owner-shard-v1",
            "owner": owner,
            "state": dict(sorted(by_owner[owner].items())),
            "param_groups": parameter_groups,
            "optimizer_contract": dict(optimizer_contract),
            "optimizer_realization": dict(optimizer_realization),
        }
    if not payloads:
        raise ValueError("owner-sharded optimizer state is empty")
    return payloads, dict(sorted(owner_by_parameter.items()))


def _optimizer_state_shard_paths(owner_ids: list[str] | tuple[str, ...]) -> set[str]:
    if not owner_ids or owner_ids[0] != "shared":
        raise ValueError("owner-sharded optimizer state must start with shared ownership")
    expected_order = ["shared", *EXPERT_NAMES]
    if list(owner_ids) != [owner for owner in expected_order if owner in owner_ids]:
        raise ValueError("owner-sharded optimizer owners are not closed and ordered")
    if any(owner not in {"shared", *EXPERT_NAMES} for owner in owner_ids):
        raise ValueError("owner-sharded optimizer owner is unknown")
    return {f"optimizer-state-{owner}.pt" for owner in owner_ids}


def _checkpoint_shard_paths(
    *,
    schema_version: str,
    optimizer_state_layout: str | None = None,
    optimizer_state_owner_ids: list[str] | tuple[str, ...] | None = None,
) -> set[str]:
    if schema_version == "ember-sparse-checkpoint-v5":
        if optimizer_state_layout == _OWNER_SHARDED_OPTIMIZER_STATE_LAYOUT:
            if optimizer_state_owner_ids is None:
                raise ValueError("owner-sharded optimizer state lacks owner ids")
            optimizer_paths = _optimizer_state_shard_paths(optimizer_state_owner_ids)
        else:
            optimizer_paths = {"optimizer-state.pt"}
        return {
            "shared-model.pt",
            *optimizer_paths,
            "replay-state.pt",
            *(f"expert-{name}.pt" for name in EXPERT_NAMES),
        }
    if schema_version in {"ember-sparse-checkpoint-v3", "ember-sparse-checkpoint-v4"}:
        return {
            "shared.pt",
            "replay-state.pt",
            *(f"expert-{name}.pt" for name in EXPERT_NAMES),
        }
    raise ValueError("checkpoint schema version is unsupported")


def checkpoint_streaming_peak_bytes(
    model: UnifiedDecoder,
    optimizer: torch.optim.Optimizer,
) -> int:
    """Bound one-storage-at-a-time serialization plus a fixed runtime buffer."""

    largest = max(
        _tensor_bytes(model.state_dict()),
        _tensor_bytes(optimizer.state_dict()),
    )
    return largest + _STREAMING_OVERHEAD_BYTES


def host_commit_headroom_diagnostic(
    *,
    physical_ram_bytes: int,
    commit_total_bytes: int,
    current_commit_limit_bytes: int,
    paging_files: object,
) -> dict[str, int | str]:
    """Return host commit headroom bounded by BOTH capacity bounds, naming each.

    Two independent quantities bound how much host commit is actually
    available: the configured (registry) maximum pagefile capacity, and the
    live Windows commit limit Windows is currently enforcing. Between a
    pagefile registry change and the next reboot, the live limit lags the
    newly configured maximum -- the OS has not yet grown into the new
    capacity. Bounding headroom by the configured maximum alone overstates
    what is actually available during that window (receipted, #898
    2026-08-21 amendment: 87 GiB reported by the configured-maximum-only
    computation while the live commit limit still capped real headroom at
    ~56 GiB, immediately before the E8 dense A1 launch refusal). Headroom is
    therefore the lesser of the two bounds; both bounds and which one binds
    are returned so a preflight refusal receipt can show both, not just the
    resulting number.
    """

    for name, value in (
        ("physical RAM", physical_ram_bytes),
        ("commit total", commit_total_bytes),
        ("current commit limit", current_commit_limit_bytes),
    ):
        if type(value) is not int or value < 0:
            raise ValueError(f"{name} bytes must be a nonnegative integer")
    if not isinstance(paging_files, list) or not paging_files:
        raise RuntimeError("pagefile setting is not a fixed positive maximum")
    pagefile_maximum_mib = 0
    for entry in paging_files:
        if not isinstance(entry, str) or not entry.strip():
            raise RuntimeError("pagefile setting is not a fixed positive maximum")
        try:
            maximum_mib = int(entry.split()[-1])
        except (IndexError, ValueError) as error:
            raise RuntimeError("pagefile setting is not a fixed positive maximum") from error
        if maximum_mib <= 0:
            raise RuntimeError("pagefile setting is not a fixed positive maximum")
        pagefile_maximum_mib += maximum_mib
    configured_maximum_capacity_bytes = physical_ram_bytes + pagefile_maximum_mib * 1024**2
    if configured_maximum_capacity_bytes < current_commit_limit_bytes:
        raise RuntimeError("configured pagefile maximum is below the live Windows commit limit")
    if configured_maximum_capacity_bytes < commit_total_bytes:
        raise RuntimeError("live committed bytes exceed configured maximum commit capacity")
    if current_commit_limit_bytes < commit_total_bytes:
        raise RuntimeError("live committed bytes exceed the live Windows commit limit")
    if current_commit_limit_bytes < configured_maximum_capacity_bytes:
        bound_by = "live_commit_limit"
        effective_capacity_bytes = current_commit_limit_bytes
    else:
        bound_by = "configured_maximum"
        effective_capacity_bytes = configured_maximum_capacity_bytes
    return {
        "configured_maximum_capacity_bytes": configured_maximum_capacity_bytes,
        "live_commit_limit_bytes": current_commit_limit_bytes,
        "commit_total_bytes": commit_total_bytes,
        "effective_capacity_bytes": effective_capacity_bytes,
        "available_commit_bytes": effective_capacity_bytes - commit_total_bytes,
        "bound_by": bound_by,
    }


def configured_maximum_available_commit_bytes(
    *,
    physical_ram_bytes: int,
    commit_total_bytes: int,
    current_commit_limit_bytes: int,
    paging_files: object,
) -> int:
    """Return headroom bounded by the lesser of configured pagefile capacity
    and the live Windows commit limit, or fail closed.

    Thin wrapper preserving the original int-returning contract for existing
    callers; see :func:`host_commit_headroom_diagnostic` for the full
    computation naming both bounds and which one binds.
    """

    return host_commit_headroom_diagnostic(
        physical_ram_bytes=physical_ram_bytes,
        commit_total_bytes=commit_total_bytes,
        current_commit_limit_bytes=current_commit_limit_bytes,
        paging_files=paging_files,
    )["available_commit_bytes"]


def available_host_commit_bytes() -> int:
    """Return Windows headroom against physical RAM plus fixed pagefile maximum."""

    if os.name != "nt":
        raise RuntimeError("host commit probe currently requires Windows")

    class PerformanceInformation(ctypes.Structure):
        _fields_ = [
            ("cb", ctypes.c_ulong),
            ("CommitTotal", ctypes.c_size_t),
            ("CommitLimit", ctypes.c_size_t),
            ("CommitPeak", ctypes.c_size_t),
            ("PhysicalTotal", ctypes.c_size_t),
            ("PhysicalAvailable", ctypes.c_size_t),
            ("SystemCache", ctypes.c_size_t),
            ("KernelTotal", ctypes.c_size_t),
            ("KernelPaged", ctypes.c_size_t),
            ("KernelNonpaged", ctypes.c_size_t),
            ("PageSize", ctypes.c_size_t),
            ("HandleCount", ctypes.c_ulong),
            ("ProcessCount", ctypes.c_ulong),
            ("ThreadCount", ctypes.c_ulong),
        ]

    info = PerformanceInformation()
    info.cb = ctypes.sizeof(info)
    if not ctypes.windll.psapi.GetPerformanceInfo(ctypes.byref(info), info.cb):
        raise RuntimeError("Windows host commit probe failed")
    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management",
        ) as key:
            paging_files, value_type = winreg.QueryValueEx(key, "PagingFiles")
    except OSError as error:
        raise RuntimeError("fixed pagefile maximum registry read failed") from error
    if value_type != winreg.REG_MULTI_SZ:
        raise RuntimeError("pagefile setting is not a fixed positive maximum")
    page_size = int(info.PageSize)
    return configured_maximum_available_commit_bytes(
        physical_ram_bytes=int(info.PhysicalTotal) * page_size,
        commit_total_bytes=int(info.CommitTotal) * page_size,
        current_commit_limit_bytes=int(info.CommitLimit) * page_size,
        paging_files=paging_files,
    )


def checkpoint_commit_preflight(
    *,
    available_commit_bytes: int,
    streaming_peak_bytes: int,
    reserve_bytes: int,
    comparison_operands: Mapping[str, Any] | None = None,
) -> dict[str, int | str]:
    if any(type(value) is not int or value < 0 for value in (available_commit_bytes, streaming_peak_bytes, reserve_bytes)):
        raise ValueError("checkpoint host commit values must be nonnegative integers")
    required = streaming_peak_bytes + reserve_bytes
    if available_commit_bytes < required:
        raise CheckpointDeferredLowCommit(
            available_commit_bytes=available_commit_bytes,
            required_commit_bytes=required,
            streaming_peak_bytes=streaming_peak_bytes,
            reserve_bytes=reserve_bytes,
            comparison_operands=comparison_operands,
        )
    return {
        "status": "PASS",
        "available_commit_bytes": available_commit_bytes,
        "streaming_peak_bytes": streaming_peak_bytes,
        "reserve_bytes": reserve_bytes,
        "required_commit_bytes": required,
    }


def _staged_failure_inventory(staging_root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not staging_root.exists():
        return rows
    for path in sorted(staging_root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(staging_root).as_posix()
        rows.append({"path": relative, "bytes": path.stat().st_size})
    return rows


def _failure_comparison_operands_from_receipt(
    receipt: Mapping[str, Any],
    candidate: Path,
    *,
    max_serialized_bytes: int | None = None,
) -> dict[str, Any]:
    operands = _empty_failure_comparison_operands()
    projection = receipt.get("storage_projection")
    architecture = receipt.get("architecture")
    if isinstance(projection, Mapping):
        optimizer_actual = projection.get("optimizer_state_tensor_storage_lower_bound_bytes")
        projected_optimizer = projection.get(
            "projected_all_expert_optimizer_state_tensor_storage_lower_bound_bytes"
        )
        try:
            route_multiplier = _optimizer_projection_route_multiplier(
                routed_optimizer=projection.get(
                    "optimizer_state_tensor_storage_by_route_bytes", {}
                ),
                active_expert=projection.get("active_expert"),
            )
        except ValueError:
            route_multiplier = None
        operands = _merge_failure_comparison_operands(
            operands,
            {
                "derived_byte_bound_bytes": max_serialized_bytes,
                "derived_byte_bound_inputs": {
                    "max_serialized_bytes": max_serialized_bytes,
                    "max_transient_scratch_bytes": projection.get("max_transient_scratch_bytes"),
                    "active_parameters": architecture.get("active_parameters") if isinstance(architecture, Mapping) else None,
                    "model_config_sha256": receipt.get("model_config_sha256"),
                    "contract_sha256": receipt.get("contract_sha256"),
                    "optimizer_state_layout": projection.get("optimizer_state_layout"),
                },
                "projected_storage_floor_bytes": projection.get(
                    "all_expert_projected_tensor_storage_lower_bound_bytes"
                ),
                "projected_storage_floor_inputs": {
                    "route_multiplier": route_multiplier,
                    "active_expert": projection.get("active_expert"),
                    "optimizer_state_layout": projection.get("optimizer_state_layout"),
                    "optimizer_state_tensor_storage_lower_bound_bytes": optimizer_actual,
                    "projected_optimizer_state_tensor_storage_lower_bound_bytes": projected_optimizer,
                    "optimizer_state_tensor_storage_by_route_bytes": projection.get("optimizer_state_tensor_storage_by_route_bytes", {}),
                    "per_shard_tensor_storage_lower_bound_bytes": projection.get("per_shard_tensor_storage_lower_bound_bytes", {}),
                    "retained_shard_paths": projection.get("retained_shard_paths", []),
                },
                "staged_shard_bytes": _staged_failure_inventory(candidate),
                "available_commit_bytes": None,
                "required_commit_bytes": None,
            },
        )
    if not operands["staged_shard_bytes"]:
        operands["staged_shard_bytes"] = _staged_failure_inventory(candidate)
    host_plan = receipt.get("host_commit_preflight")
    if isinstance(host_plan, Mapping):
        operands["available_commit_bytes"] = host_plan.get("available_commit_bytes")
        operands["required_commit_bytes"] = host_plan.get("required_commit_bytes")
    return _normalize_failure_comparison_operands(operands)


def _retain_write_failure_evidence(
    published_root: Path,
    staging_root: Path,
    error: BaseException,
    *,
    quarantine_candidate: str | None = None,
    comparison_operands: Mapping[str, Any] | None = None,
) -> Path:
    manifest_path = staging_root / "checkpoint-manifest.json"
    manifest_sha256 = _sha256(manifest_path) if manifest_path.is_file() else None
    shards: list[dict[str, object]] = []
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            for record in manifest.get("shards", []):
                if isinstance(record, dict):
                    shards.append({
                        field: record.get(field)
                        for field in ("path", "role", "sha256", "bytes", "publication_mode", "incremental_bytes")
                    })
        except (OSError, ValueError, TypeError):
            shards = []
    operands = _normalize_failure_comparison_operands(comparison_operands)
    payload = {
        "schema_version": "ember-checkpoint-write-failure-v1",
        "target": published_root.name,
        "quarantine_candidate": quarantine_candidate,
        "error_type": type(error).__name__,
        "error_message": str(error)[:4096],
        "checkpoint_manifest_sha256": manifest_sha256,
        "shards": shards,
        "comparison_operands": operands,
    }
    encoded = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    if len(encoded) >= _FAILURE_EVIDENCE_LIMIT:
        raise RuntimeError("checkpoint failure evidence exceeds its bounded retention limit")
    digest = hashlib.sha256(encoded).hexdigest()
    quarantine = published_root.parent / ".checkpoint-quarantine"
    quarantine.mkdir(exist_ok=True)
    return _write_atomic(
        quarantine,
        f"checkpoint-write-failed-{digest}.json",
        lambda handle: handle.write(encoded),
    )


def _record(
    path: Path,
    root: Path,
    *,
    role: str,
    publication_mode: str = "written",
) -> dict[str, Any]:
    if publication_mode not in {"written", "hardlink", "copy"}:
        raise ValueError("unknown checkpoint publication mode")
    logical_bytes = path.stat().st_size
    return {
        "path": path.relative_to(root).as_posix(),
        "role": role,
        "sha256": _sha256(path),
        "bytes": logical_bytes,
        "publication_mode": publication_mode,
        "incremental_bytes": 0 if publication_mode == "hardlink" else logical_bytes,
    }


def _write_atomic(
    root: Path,
    filename: str,
    writer: Callable[[Any], None],
    *,
    max_transient_scratch_bytes: int | None = None,
) -> Path:
    """Write, fsync, and rename one artifact without publishing partial bytes."""

    if max_transient_scratch_bytes is not None and (
        type(max_transient_scratch_bytes) is not int
        or max_transient_scratch_bytes < 1
    ):
        raise ValueError("max_transient_scratch_bytes must be a positive integer")
    target = root / filename
    temporary = root / f".{filename}.{uuid.uuid4().hex}.tmp"
    try:
        with temporary.open("wb") as handle:
            bounded_handle = (
                _ScratchCappedWriter(handle, max_transient_scratch_bytes)
                if max_transient_scratch_bytes is not None
                else handle
            )
            writer(bounded_handle)
            handle.flush()
            os.fsync(handle.fileno())
        atomic_replace_durable(temporary, target)
        return target
    finally:
        if temporary.exists():
            temporary.unlink()


def _write_json_atomic(
    root: Path,
    filename: str,
    payload: Mapping[str, Any],
    *,
    max_transient_scratch_bytes: int | None = None,
) -> Path:
    encoded = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    return _write_atomic(
        root,
        filename,
        lambda handle: handle.write(encoded),
        max_transient_scratch_bytes=max_transient_scratch_bytes,
    )


def _atomic_publish_no_replace(source: Path, target: Path) -> None:
    """Atomically rename a directory without replacing a late target."""

    source = source.resolve(strict=True)
    target_parent = target.parent.resolve(strict=True)
    target_entry = target_parent / target.name
    # Preserve the lexical leaf: resolve() on a dangling symlink would follow
    # it and could redirect publication to an absent referent.
    if os.path.lexists(str(target_entry)):
        raise FileExistsError(errno.EEXIST, "checkpoint publication target already exists", str(target_entry))
    if os.name == "nt":
        # Python's Windows os.rename maps to MoveFileEx without REPLACE_EXISTING.
        os.rename(source, target_entry)
        return
    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(libc, "renameat2", None)
    if renameat2 is None:
        raise RuntimeError("Linux checkpoint publication requires renameat2(RENAME_NOREPLACE)")
    renameat2.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]  # type: ignore[attr-defined]
    renameat2.restype = ctypes.c_int  # type: ignore[attr-defined]
    at_fdcwd = -100
    rename_noreplace = 1
    result = renameat2(
        at_fdcwd, os.fsencode(source), at_fdcwd, os.fsencode(target_entry), rename_noreplace,
    )
    if result != 0:
        error_number = ctypes.get_errno()
        if error_number in (errno.EEXIST, errno.ENOTEMPTY):
            raise FileExistsError(error_number, "checkpoint publication target appeared", str(target_entry))
        raise OSError(error_number, os.strerror(error_number), str(target_entry))


def _sha256_value(value: str, *, name: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _canonical_sha256(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(dict(value), sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _optimizer_tensor_storage_by_route(
    model: UnifiedDecoder,
    optimizer: torch.optim.Optimizer,
) -> dict[str, int]:
    """Measure initialized optimizer tensor storage by shared/expert route."""

    parameter_names = {
        id(parameter): name for name, parameter in model.named_parameters()
    }
    routed_state: dict[str, dict[str, Any]] = {
        "shared": {},
        **{name: {} for name in EXPERT_NAMES},
    }
    for parameter, state in optimizer.state.items():
        name = parameter_names.get(id(parameter))
        if name is None:
            raise ValueError(
                "optimizer state contains a parameter outside the checkpoint model"
            )
        route = "shared"
        for expert_name in EXPERT_NAMES:
            if f".experts.{expert_name}." in name:
                route = expert_name
                break
        routed_state[route][name] = state
    return {
        route: _unique_tensor_storage_bytes(state)
        for route, state in routed_state.items()
    }


def optimizer_covers_every_expert_route(
    model: UnifiedDecoder,
    optimizer: torch.optim.Optimizer,
) -> bool:
    """True when the live optimizer holds initialized moments on every specialist route.

    A lineage episode that exact-resumed a full-coverage parent restores the parent's
    moments verbatim (#1473's second closed admissible shape), so its serialized
    checkpoint legitimately carries full-coverage optimizer state at projection
    factor 1. The byte bound the runner budgets for such an episode must be derived
    from the SAME live measurement this module's storage projection later verifies:
    budgeting shared-plus-one-expert while the projection admits the inherited full
    set refused the by-design publication (#1483).
    """

    routed = _optimizer_tensor_storage_by_route(model, optimizer)
    return all(routed[name] > 0 for name in EXPERT_NAMES)


def _projected_all_expert_optimizer_storage_bytes(
    *, routed_optimizer: Mapping[str, int], active_expert: str
) -> int:
    """Project one routed optimizer state across the closed expert set.

    Shared moments are common to every route and therefore count once.  For a
    partial expert set, missing symmetric routes are conservatively priced at
    the largest populated expert route.
    """

    if (
        set(routed_optimizer) != {"shared", *EXPERT_NAMES}
        or any(type(value) is not int or value < 0 for value in routed_optimizer.values())
        or active_expert not in {"shared", *EXPERT_NAMES}
    ):
        raise ValueError("checkpoint optimizer route projection is invalid")
    specialist_routes = [name for name in EXPERT_NAMES if routed_optimizer[name] > 0]
    if active_expert != "shared" and routed_optimizer[active_expert] < 1:
        raise ValueError("checkpoint optimizer route projection is invalid")
    if specialist_routes == []:
        return routed_optimizer["shared"]
    populated = [routed_optimizer[name] for name in specialist_routes]
    return (
        routed_optimizer["shared"]
        + sum(populated)
        + (len(EXPERT_NAMES) - len(populated)) * max(populated)
    )


def _optimizer_projection_route_multiplier(
    *, routed_optimizer: Mapping[str, int], active_expert: str
) -> int:
    if (
        set(routed_optimizer) != {"shared", *EXPERT_NAMES}
        or any(type(value) is not int or value < 0 for value in routed_optimizer.values())
        or active_expert not in {"shared", *EXPERT_NAMES}
    ):
        raise ValueError("checkpoint optimizer route projection is invalid")
    specialist_routes = [name for name in EXPERT_NAMES if routed_optimizer[name] > 0]
    if active_expert != "shared" and routed_optimizer[active_expert] < 1:
        raise ValueError("checkpoint optimizer route projection is invalid")
    return (
        1
        if not specialist_routes or specialist_routes == list(EXPERT_NAMES)
        else len(EXPERT_NAMES)
    )


def _storage_failure_comparison_operands(
    *,
    model: UnifiedDecoder,
    optimizer: torch.optim.Optimizer,
    optimizer_file_payload: Mapping[str, Any],
    shard_storage_lower_bounds: Mapping[str, int],
    max_transient_scratch_bytes: int | None,
    max_serialized_bytes: int | None,
    optimizer_state_layout: str,
    model_config_sha256: str | None = None,
    contract_sha256: str | None = None,
    active_parameters: int | None = None,
    shard_publication_modes: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    routed_optimizer = _optimizer_tensor_storage_by_route_for_write(
        model=model,
        optimizer=optimizer,
        shard_storage_lower_bounds=shard_storage_lower_bounds,
        optimizer_state_layout=optimizer_state_layout,
    )
    optimizer_actual = _optimizer_state_actual_tensor_storage_bytes(
        optimizer_file_payload=optimizer_file_payload,
        shard_storage_lower_bounds=shard_storage_lower_bounds,
        optimizer_state_layout=optimizer_state_layout,
    )
    try:
        route_multiplier = _optimizer_projection_route_multiplier(
            routed_optimizer=routed_optimizer,
            active_expert=model.active_expert,
        )
        projected_optimizer = _projected_all_expert_optimizer_storage_bytes(
            routed_optimizer=routed_optimizer,
            active_expert=model.active_expert,
        )
    except ValueError:
        # Failure evidence must remain serializable even when the optimizer
        # route shape itself is the refusal (for example, pre-update state).
        route_multiplier = (
            1 if model.active_expert == "shared" else len(EXPERT_NAMES)
        )
        projected_optimizer = optimizer_actual * route_multiplier
    projected_floor = sum(shard_storage_lower_bounds.values()) - optimizer_actual + projected_optimizer
    publication_modes = shard_publication_modes or {}
    retained = sorted(path for path, mode in publication_modes.items() if mode == "hardlink")
    return {
        "derived_byte_bound_bytes": max_serialized_bytes,
        "derived_byte_bound_inputs": {
            "max_serialized_bytes": max_serialized_bytes,
            "max_transient_scratch_bytes": max_transient_scratch_bytes,
            "active_parameters": active_parameters,
            "model_config_sha256": model_config_sha256,
            "contract_sha256": contract_sha256,
            "optimizer_state_layout": optimizer_state_layout,
        },
        "projected_storage_floor_bytes": projected_floor,
        "projected_storage_floor_inputs": {
            "route_multiplier": route_multiplier,
            "active_expert": model.active_expert,
            "optimizer_state_layout": optimizer_state_layout,
            "optimizer_state_tensor_storage_lower_bound_bytes": optimizer_actual,
            "projected_optimizer_state_tensor_storage_lower_bound_bytes": projected_optimizer,
            "optimizer_state_tensor_storage_by_route_bytes": routed_optimizer,
            "per_shard_tensor_storage_lower_bound_bytes": dict(sorted(shard_storage_lower_bounds.items())),
            "retained_shard_paths": retained,
        },
        "staged_shard_bytes": [],
        "available_commit_bytes": None,
        "required_commit_bytes": None,
    }


def _derive_checkpoint_storage_projection(
    *,
    model: UnifiedDecoder,
    optimizer: torch.optim.Optimizer,
    optimizer_file_payload: Mapping[str, Any],
    shard_storage_lower_bounds: Mapping[str, int],
    shard_sha256: Mapping[str, str],
    publication_modes: Mapping[str, str],
    global_step: int,
    max_transient_scratch_bytes: int,
    max_serialized_bytes: int,
    specialist_parent_optimizer_routes: tuple[str, ...] | None,
    optimizer_state_layout: str = "legacy-v1",
    model_config_sha256: str | None = None,
    contract_sha256: str | None = None,
    active_parameters: int | None = None,
) -> dict[str, Any]:
    """Bind the post-update optimizer floor and four-expert checkpoint floor.

    ``specialist_parent_optimizer_routes`` is ``None`` for a non-lineage
    publication; for a single-specialist lineage episode it is the (possibly
    empty) closed set of expert routes the resumed parent's own digest-bound
    storage projection attests as initialized -- the only authority on what
    optimizer state the episode legitimately inherited (#1473).
    """

    if type(global_step) is not int or global_step < 1:
        raise ValueError(
            "checkpoint storage projection requires post-update global_step"
        )
    if specialist_parent_optimizer_routes is not None and (
        [name for name in EXPERT_NAMES if name in set(specialist_parent_optimizer_routes)]
        != list(specialist_parent_optimizer_routes)
    ):
        raise ValueError(
            "checkpoint storage projection parent optimizer routes are not closed"
        )
    route_names = ("shared", *EXPERT_NAMES)
    if model.active_expert not in route_names:
        raise ValueError(
            "checkpoint storage projection requires one active checkpoint route"
        )
    routed_optimizer = _optimizer_tensor_storage_by_route(model, optimizer)
    if optimizer_state_layout == _OWNER_SHARDED_OPTIMIZER_STATE_LAYOUT:
        owner_ids = [
            "shared",
            *[
                name
                for name in EXPERT_NAMES
                if routed_optimizer[name] > 0
            ],
        ]
        expected_shards = _checkpoint_shard_paths(
            schema_version="ember-sparse-checkpoint-v5",
            optimizer_state_layout=optimizer_state_layout,
            optimizer_state_owner_ids=owner_ids,
        )
    elif optimizer_state_layout == "legacy-v1":
        expected_shards = _checkpoint_shard_paths(
            schema_version="ember-sparse-checkpoint-v5"
        )
    else:
        raise ValueError("checkpoint optimizer state layout is unsupported")
    if set(shard_storage_lower_bounds) != expected_shards:
        raise ValueError("checkpoint storage projection shard set is not closed")
    if set(shard_sha256) != expected_shards:
        raise ValueError("checkpoint storage projection shard hashes are not closed")
    for path, digest in shard_sha256.items():
        _sha256_value(digest, name=f"checkpoint projection {path}")
    if set(publication_modes) != expected_shards:
        raise ValueError(
            "checkpoint storage projection publication modes are not closed"
        )
    if any(
        type(value) is not int or value < 0
        for value in shard_storage_lower_bounds.values()
    ):
        raise ValueError("checkpoint storage projection contains an invalid bound")
    if any(
        mode not in {"written", "hardlink"}
        for mode in publication_modes.values()
    ):
        raise ValueError(
            "checkpoint storage projection contains an unbounded publication mode"
        )

    optimizer_actual = _optimizer_state_actual_tensor_storage_bytes(
        optimizer_file_payload=optimizer_file_payload,
        shard_storage_lower_bounds=shard_storage_lower_bounds,
        optimizer_state_layout=optimizer_state_layout,
    )
    active_bytes = routed_optimizer[model.active_expert]
    specialist_routes = [
        name for name in EXPERT_NAMES if routed_optimizer[name] > 0
    ]
    if specialist_parent_optimizer_routes is None:
        route_valid = (
            routed_optimizer["shared"] > 0
            and (
                model.active_expert == "shared"
                or model.active_expert in specialist_routes
            )
        )
        active_routes = list(specialist_routes) if specialist_routes else ["shared"]
    else:
        # A lineage episode may carry exactly its independently attested parent
        # routes plus the route trained by this episode.  No other populated
        # optimizer owner is admitted.
        inherited = set(specialist_parent_optimizer_routes)
        expected_routes = [
            name
            for name in EXPERT_NAMES
            if name in inherited or name == model.active_expert
        ]
        route_valid = (
            active_bytes > 0
            and model.active_expert in EXPERT_NAMES
            and specialist_routes == expected_routes
        )
        active_routes = list(specialist_routes)
    if optimizer_actual < 1 or not route_valid:
        raise ValueError(
            "checkpoint storage projection requires one post-update optimizer state"
        )
    # Price the same owner-sharded bytes that will be stored in the projection.
    # The live optimizer may share one tensor identity across owners (for
    # example bitsandbytes qmaps), while independent owner files each carry a
    # physical copy.  Using the live deduplicated route totals here would make
    # the projected floor disagree with the stored per-owner attribution.
    routed_optimizer_actual = _optimizer_tensor_storage_by_route_for_write(
        model=model,
        optimizer=optimizer,
        shard_storage_lower_bounds=shard_storage_lower_bounds,
        optimizer_state_layout=optimizer_state_layout,
    )
    projected_optimizer = _projected_all_expert_optimizer_storage_bytes(
        routed_optimizer=routed_optimizer_actual,
        active_expert=model.active_expert,
    )
    actual_checkpoint_floor = sum(shard_storage_lower_bounds.values())
    projected_checkpoint_floor = (
        actual_checkpoint_floor - optimizer_actual + projected_optimizer
    )
    retained_paths = sorted(
        path for path, mode in publication_modes.items() if mode == "hardlink"
    )
    transient_new_write_peak = max(
        (
            shard_storage_lower_bounds[path]
            for path, mode in publication_modes.items()
            if mode == "written"
        ),
        default=0,
    )
    comparison_operands = _storage_failure_comparison_operands(
        model=model,
        optimizer=optimizer,
        optimizer_file_payload=optimizer_file_payload,
        shard_storage_lower_bounds=shard_storage_lower_bounds,
        max_transient_scratch_bytes=max_transient_scratch_bytes,
        max_serialized_bytes=max_serialized_bytes,
        optimizer_state_layout=optimizer_state_layout,
        shard_publication_modes=publication_modes,
        model_config_sha256=model_config_sha256,
        contract_sha256=contract_sha256,
        active_parameters=active_parameters,
    )
    if transient_new_write_peak > max_transient_scratch_bytes:
        raise _CheckpointWriteRefusal(
            "checkpoint transient new-write projection exceeds scratch cap",
            comparison_operands=comparison_operands,
        )
    if projected_checkpoint_floor > max_serialized_bytes:
        raise _CheckpointWriteRefusal(
            "checkpoint all-expert projected tensor-storage lower bound "
            "exceeds the derived serialized byte bound",
            comparison_operands=comparison_operands,
        )

    # owner_ids/route_valid/active_bytes above only need route positivity,
    # which the live-optimizer measurement gives correctly regardless of
    # whether owner-sharded writing later breaks shared-tensor identity, and
    # cross-checking that positivity against shard_storage_lower_bounds'
    # independently-derived owner set is a real integrity check worth
    # keeping. The stored by-route byte field is checked byte-exactly
    # against the reopened per-shard measurement in
    # _validate_owner_storage_projection_authority, so it needs the same
    # real, write-time bytes as optimizer_actual above -- not the live,
    # pre-detach dedup this function otherwise uses for routed_optimizer.
    projection = {
        "schema_version": "ember-checkpoint-storage-projection-v1",
        **({"optimizer_state_layout": optimizer_state_layout} if optimizer_state_layout != "legacy-v1" else {}),
        **({"optimizer_state_owner_ids": owner_ids} if optimizer_state_layout == _OWNER_SHARDED_OPTIMIZER_STATE_LAYOUT else {}),
        "active_expert": model.active_expert,
        "optimizer_state_after_global_step": global_step,
        "optimizer_state_active_expert_ids": active_routes,
        "optimizer_state_tensor_storage_lower_bound_bytes": optimizer_actual,
        "optimizer_state_tensor_storage_by_route_bytes": routed_optimizer_actual,
        "projected_all_expert_optimizer_state_tensor_storage_lower_bound_bytes": (
            projected_optimizer
        ),
        "per_shard_tensor_storage_lower_bound_bytes": dict(
            sorted(shard_storage_lower_bounds.items())
        ),
        "per_shard_sha256": dict(sorted(shard_sha256.items())),
        "transient_new_write_peak_lower_bound_bytes": transient_new_write_peak,
        "retained_shard_paths": retained_paths,
        "all_expert_projected_tensor_storage_lower_bound_bytes": (
            projected_checkpoint_floor
        ),
        "max_transient_scratch_bytes": max_transient_scratch_bytes,
        "max_serialized_bytes": max_serialized_bytes,
        "manifest_written_last": True,
    }
    return {
        **projection,
        "projection_sha256": _canonical_sha256(projection),
    }


def _validate_checkpoint_storage_projection(
    projection: Any,
    *,
    max_serialized_bytes: int | None = None,
) -> dict[str, Any]:
    """Revalidate the closed projection before quarantine admission."""

    required = {
        "schema_version",
        "active_expert",
        "optimizer_state_after_global_step",
        "optimizer_state_active_expert_ids",
        "optimizer_state_tensor_storage_lower_bound_bytes",
        "optimizer_state_tensor_storage_by_route_bytes",
        "projected_all_expert_optimizer_state_tensor_storage_lower_bound_bytes",
        "per_shard_tensor_storage_lower_bound_bytes",
        "per_shard_sha256",
        "transient_new_write_peak_lower_bound_bytes",
        "retained_shard_paths",
        "all_expert_projected_tensor_storage_lower_bound_bytes",
        "max_transient_scratch_bytes",
        "max_serialized_bytes",
        "manifest_written_last",
        "projection_sha256",
    }
    if not isinstance(projection, Mapping):
        raise ValueError("checkpoint storage projection has an invalid shape")
    projection_keys = set(projection)
    owner_projection_keys = required | {"optimizer_state_layout", "optimizer_state_owner_ids"}
    if projection_keys == required:
        if projection.get("optimizer_state_layout") is not None:
            raise ValueError("legacy checkpoint storage projection cannot carry owner layout")
    elif projection_keys == owner_projection_keys and projection.get("optimizer_state_layout") == _OWNER_SHARDED_OPTIMIZER_STATE_LAYOUT:
        pass
    else:
        raise ValueError("checkpoint storage projection has an invalid shape")
    materialized = dict(projection)
    digest = materialized.pop("projection_sha256")
    optimizer_state_layout = materialized.get("optimizer_state_layout", "legacy-v1")
    if (
        materialized["schema_version"]
        != "ember-checkpoint-storage-projection-v1"
        or not isinstance(digest, str)
        or digest != _canonical_sha256(materialized)
    ):
        raise ValueError("checkpoint storage projection digest mismatch")
    if (
        materialized["active_expert"] not in {"shared", *EXPERT_NAMES}
        or not isinstance(materialized["optimizer_state_active_expert_ids"], list)
        or type(materialized["optimizer_state_after_global_step"]) is not int
        or materialized["optimizer_state_after_global_step"] < 1
        or materialized["manifest_written_last"] is not True
    ):
        raise ValueError("checkpoint storage projection is not post-update")
    route_bounds = materialized[
        "optimizer_state_tensor_storage_by_route_bytes"
    ]
    if (
        not isinstance(route_bounds, Mapping)
        or set(route_bounds) != {"shared", *EXPERT_NAMES}
        or any(type(value) is not int or value < 0 for value in route_bounds.values())
        or route_bounds[materialized["active_expert"]] < 1
    ):
        raise ValueError("checkpoint optimizer route projection is invalid")
    shard_bounds = materialized[
        "per_shard_tensor_storage_lower_bound_bytes"
    ]
    if optimizer_state_layout == _OWNER_SHARDED_OPTIMIZER_STATE_LAYOUT:
        owner_ids = materialized.get("optimizer_state_owner_ids")
        if not isinstance(owner_ids, list):
            raise ValueError("checkpoint optimizer owner projection is invalid")
        expected_shards = _checkpoint_shard_paths(
            schema_version="ember-sparse-checkpoint-v5",
            optimizer_state_layout=optimizer_state_layout,
            optimizer_state_owner_ids=owner_ids,
        )
    elif optimizer_state_layout == "legacy-v1":
        expected_shards = _checkpoint_shard_paths(
            schema_version="ember-sparse-checkpoint-v5"
        )
    else:
        raise ValueError("checkpoint optimizer state layout is unsupported")
    if (
        not isinstance(shard_bounds, Mapping)
        or set(shard_bounds) != expected_shards
        or any(type(value) is not int or value < 0 for value in shard_bounds.values())
    ):
        raise ValueError("checkpoint shard storage projection is invalid")
    shard_hashes = materialized["per_shard_sha256"]
    if not isinstance(shard_hashes, Mapping) or set(shard_hashes) != expected_shards:
        raise ValueError("checkpoint shard-byte projection is invalid")
    for path, digest in shard_hashes.items():
        _sha256_value(digest, name=f"checkpoint projection {path}")
    for field in (
        "optimizer_state_tensor_storage_lower_bound_bytes",
        "projected_all_expert_optimizer_state_tensor_storage_lower_bound_bytes",
        "transient_new_write_peak_lower_bound_bytes",
        "all_expert_projected_tensor_storage_lower_bound_bytes",
        "max_transient_scratch_bytes",
        "max_serialized_bytes",
    ):
        if type(materialized[field]) is not int or materialized[field] < 1:
            raise ValueError("checkpoint storage projection byte bound is invalid")
    if (
        materialized["transient_new_write_peak_lower_bound_bytes"]
        > materialized["max_transient_scratch_bytes"]
        or materialized["all_expert_projected_tensor_storage_lower_bound_bytes"]
        > materialized["max_serialized_bytes"]
        or (
            max_serialized_bytes is not None
            and materialized["max_serialized_bytes"] != max_serialized_bytes
        )
    ):
        raise ValueError("checkpoint storage projection exceeds its hard gate")
    retained = materialized["retained_shard_paths"]
    if (
        not isinstance(retained, list)
        or retained != sorted(set(retained))
        or any(path not in expected_shards for path in retained)
    ):
        raise ValueError("checkpoint retained-shard projection is invalid")
    active_expert = materialized["active_expert"]
    specialist_routes = [
        name for name in EXPERT_NAMES if route_bounds[name] > 0
    ]
    expected_active_ids = specialist_routes if specialist_routes else ["shared"]
    route_valid = (
        route_bounds["shared"] > 0
        and materialized["optimizer_state_active_expert_ids"]
        == expected_active_ids
        and (
            active_expert == "shared"
            or active_expert in specialist_routes
        )
    )
    if not route_valid:
        raise ValueError("checkpoint optimizer route projection is invalid")
    optimizer_actual = materialized[
        "optimizer_state_tensor_storage_lower_bound_bytes"
    ]
    expected_projected_optimizer = _projected_all_expert_optimizer_storage_bytes(
        routed_optimizer=route_bounds,
        active_expert=active_expert,
    )
    optimizer_shard_total = sum(
        bound
        for path, bound in shard_bounds.items()
        if path.startswith("optimizer-state-")
    )
    if optimizer_state_layout == "legacy-v1":
        optimizer_shard_total = shard_bounds["optimizer-state.pt"]
    route_total = sum(route_bounds.values())
    route_total_invalid = (
        route_total != optimizer_actual
        if optimizer_state_layout == "legacy-v1"
        else route_total < optimizer_actual
    )
    if (
        optimizer_shard_total != optimizer_actual
        or route_total_invalid
        or materialized[
            "projected_all_expert_optimizer_state_tensor_storage_lower_bound_bytes"
        ]
        != expected_projected_optimizer
    ):
        raise ValueError("checkpoint optimizer storage projection is inconsistent")
    expected_checkpoint_floor = (
        sum(shard_bounds.values())
        - optimizer_actual
        + expected_projected_optimizer
    )
    expected_transient_peak = max(
        (
            bound
            for path, bound in shard_bounds.items()
            if path not in retained
        ),
        default=0,
    )
    if (
        materialized["all_expert_projected_tensor_storage_lower_bound_bytes"]
        != expected_checkpoint_floor
        or materialized["transient_new_write_peak_lower_bound_bytes"]
        != expected_transient_peak
    ):
        raise ValueError("checkpoint storage projection arithmetic is inconsistent")
    return dict(projection)


def _measure_candidate_storage_projection(
    candidate: Path,
    projection: Mapping[str, Any],
) -> None:
    """Recompute the hard storage gate from quarantined serialized bytes."""

    optimizer_state_layout = projection.get("optimizer_state_layout", "legacy-v1")
    expected_shards = _checkpoint_shard_paths(
        schema_version="ember-sparse-checkpoint-v5",
        optimizer_state_layout=optimizer_state_layout,
        optimizer_state_owner_ids=projection.get("optimizer_state_owner_ids")
        if optimizer_state_layout == _OWNER_SHARDED_OPTIMIZER_STATE_LAYOUT
        else None,
    )
    measured: dict[str, int] = {}
    for relative in sorted(expected_shards):
        try:
            payload = torch.load(
                candidate / relative,
                map_location="cpu",
                weights_only=False,
                mmap=True,
            )
        except Exception as error:
            raise ValueError(
                f"checkpoint shard cannot be measured independently: {relative}"
            ) from error
        measured[relative] = _unique_tensor_storage_bytes(payload)
        del payload

    optimizer_actual = sum(
        measured[path]
        for path in measured
        if path.startswith("optimizer-state-")
    )
    if optimizer_state_layout == "legacy-v1":
        optimizer_actual = measured["optimizer-state.pt"]
    projected_optimizer = _projected_all_expert_optimizer_storage_bytes(
        routed_optimizer=projection[
            "optimizer_state_tensor_storage_by_route_bytes"
        ],
        active_expert=projection["active_expert"],
    )
    projected_checkpoint = (
        sum(measured.values()) - optimizer_actual + projected_optimizer
    )
    retained = projection["retained_shard_paths"]
    transient_peak = max(
        (
            bound
            for path, bound in measured.items()
            if path not in retained
        ),
        default=0,
    )
    if (
        projection["per_shard_tensor_storage_lower_bound_bytes"] != measured
        or projection["optimizer_state_tensor_storage_lower_bound_bytes"]
        != optimizer_actual
        or projection[
            "projected_all_expert_optimizer_state_tensor_storage_lower_bound_bytes"
        ]
        != projected_optimizer
        or projection[
            "all_expert_projected_tensor_storage_lower_bound_bytes"
        ]
        != projected_checkpoint
        or projection["transient_new_write_peak_lower_bound_bytes"]
        != transient_peak
    ):
        raise ValueError(
            "checkpoint independent tensor-storage measurement does not match projection"
        )
    if (
        transient_peak > projection["max_transient_scratch_bytes"]
        or projected_checkpoint > projection["max_serialized_bytes"]
    ):
        raise ValueError(
            "checkpoint independent tensor-storage measurement exceeds hard gate"
        )


def _default_optimizer_contract(optimizer: torch.optim.Optimizer) -> dict[str, Any]:
    cls = type(optimizer)
    return {
        "name": cls.__name__,
        "implementation": f"{cls.__module__}.{cls.__qualname__}",
        "hyperparameters": {"param_group_count": len(optimizer.param_groups), "learning_rate": float(optimizer.param_groups[0]["lr"]), "weight_decay": float(optimizer.param_groups[0]["weight_decay"])},
        "state_format": "torch-optimizer-state-dict-v1",
    }


def _validate_optimizer_contract(contract: Mapping[str, Any]) -> dict[str, Any]:
    required = {"name", "implementation", "hyperparameters", "state_format"}
    if not isinstance(contract, Mapping) or set(contract) not in (required, required | {"placement"}):
        raise ValueError("checkpoint optimizer contract has an invalid shape")
    if not isinstance(contract["name"], str) or not contract["name"]:
        raise ValueError("checkpoint optimizer contract name is invalid")
    if not isinstance(contract["implementation"], str) or not contract["implementation"]:
        raise ValueError("checkpoint optimizer contract implementation is invalid")
    if not isinstance(contract["hyperparameters"], Mapping) or not contract["hyperparameters"]:
        raise ValueError("checkpoint optimizer contract hyperparameters are invalid")
    if not isinstance(contract["state_format"], str) or not contract["state_format"]:
        raise ValueError("checkpoint optimizer contract state format is invalid")
    if "placement" in contract and contract["placement"] != "cuda_non_paged":
        raise ValueError("checkpoint optimizer contract placement is invalid")
    validated = {"name": contract["name"], "implementation": contract["implementation"], "hyperparameters": dict(contract["hyperparameters"]), "state_format": contract["state_format"]}
    if "placement" in contract:
        validated["placement"] = contract["placement"]
    return validated


def _runtime_optimizer_contract(optimizer: torch.optim.Optimizer) -> dict[str, Any]:
    """Derive the optimizer identity from the supplied runtime, never its receipt."""

    cls = type(optimizer)
    runtime_implementation = f"{cls.__module__}.{cls.__qualname__}"
    if runtime_implementation == "bitsandbytes.optim.adamw.AdamW8bit":
        if not optimizer.param_groups or not hasattr(optimizer, "args"):
            raise ValueError("runtime AdamW8bit lacks required state")
        group = optimizer.param_groups[0]
        args = optimizer.args
        required_group = ("lr", "weight_decay")
        required_args = ("percentile_clipping", "block_wise", "optim_bits")
        if any(field not in group for field in required_group) or any(not hasattr(args, field) for field in required_args):
            raise ValueError("runtime AdamW8bit lacks required hyperparameters")
        if int(args.optim_bits) != 8:
            raise ValueError("runtime AdamW8bit does not use 8-bit optimizer state")
        if bool(getattr(optimizer, "is_paged", True)):
            raise ValueError("runtime AdamW8bit is not device-resident")
        implementation = "bitsandbytes.optim.AdamW8bit"
        name = "device_resident_8bit_adamw"
        hyperparameters = {
            "learning_rate": float(group["lr"]),
            "weight_decay": float(group["weight_decay"]),
            "percentile_clipping": int(args.percentile_clipping),
            "block_wise": bool(args.block_wise),
        }
        state_format = "bitsandbytes-device-resident-8bit-adamw-state-dict-v1"
        placement = "cuda_non_paged"
    else:
        implementation = runtime_implementation
        name = cls.__name__
        if not optimizer.param_groups or any("lr" not in group or "weight_decay" not in group for group in optimizer.param_groups):
            raise ValueError("runtime optimizer lacks required hyperparameters")
        hyperparameters = {"param_group_count": len(optimizer.param_groups), "learning_rate": float(optimizer.param_groups[0]["lr"]), "weight_decay": float(optimizer.param_groups[0]["weight_decay"])}
        state_format = "torch-optimizer-state-dict-v1"
    return {
        "name": name,
        "implementation": implementation,
        "hyperparameters": hyperparameters,
        "state_format": state_format,
        **({"placement": placement} if runtime_implementation == "bitsandbytes.optim.adamw.AdamW8bit" else {}),
    }


def _optimizer_realization(optimizer: torch.optim.Optimizer, contract: Mapping[str, Any]) -> dict[str, str]:
    runtime_contract = _runtime_optimizer_contract(optimizer)
    if runtime_contract != _validate_optimizer_contract(contract):
        raise ValueError("runtime optimizer realization does not match the declared contract")
    source = inspect.getsourcefile(type(optimizer))
    if source is None or not Path(source).is_file():
        raise ValueError("optimizer implementation source cannot be content-addressed")
    return {
        "implementation": runtime_contract["implementation"],
        "implementation_source_sha256": _sha256(Path(source)),
        "state_format": runtime_contract["state_format"],
        "optimizer_contract_sha256": _canonical_sha256(runtime_contract),
        **({"placement": runtime_contract["placement"]} if "placement" in runtime_contract else {}),
    }


def _validate_runtime_optimizer_realization(
    optimizer: torch.optim.Optimizer,
    contract: Mapping[str, Any],
    realization: Mapping[str, Any],
) -> None:
    """Recompute the receipt from live optimizer code and reject self-consistent forgeries."""

    runtime_realization = _optimizer_realization(optimizer, contract)
    if runtime_realization != dict(realization):
        raise ValueError("runtime optimizer realization does not match the checkpoint receipt")

def _validate_optimizer_realization(contract: Mapping[str, Any], realization: Any) -> dict[str, str]:
    required = {"implementation", "implementation_source_sha256", "state_format", "optimizer_contract_sha256"}
    if "placement" in contract:
        required.add("placement")
    if not isinstance(realization, Mapping) or set(realization) != required:
        raise ValueError("checkpoint optimizer realization has an invalid shape")
    if realization.get("implementation") != contract["implementation"] or realization.get("state_format") != contract["state_format"] or ("placement" in contract and realization.get("placement") != contract["placement"]):
        raise ValueError("checkpoint optimizer realization drifts from its contract")
    for field in ("implementation_source_sha256", "optimizer_contract_sha256"):
        _sha256_value(str(realization.get(field, "")), name=f"optimizer realization {field}")
    if realization["optimizer_contract_sha256"] != _canonical_sha256(contract):
        raise ValueError("checkpoint optimizer realization contract hash mismatch")
    return dict(realization)

def _validate_replay_bindings(
    *,
    launch_seed: int,
    rng_state: Mapping[str, torch.Tensor],
    data_cursor: Mapping[str, Any],
    model_config_sha256: str,
    contract_sha256: str,
    expert_genesis_sha256: Mapping[str, str],
    expected_expert_names=None,
) -> None:
    if not isinstance(launch_seed, int) or launch_seed < 0:
        raise ValueError("launch_seed must be a nonnegative integer")
    if set(rng_state) != {"cpu", "cuda"}:
        raise ValueError("checkpoint requires CPU and CUDA RNG states")
    for name, state in rng_state.items():
        if not isinstance(state, torch.Tensor) or state.dtype != torch.uint8 or state.ndim != 1:
            raise ValueError(f"{name} RNG state must be a one-dimensional uint8 tensor")
    if not isinstance(data_cursor, Mapping):
        raise ValueError("checkpoint requires a nonempty data cursor")
    required_cursor = {"shard", "record_index", "global_step", "tokens_seen"}
    p2b_fields = {"schema_version", "selection_cursor", "global_step", "tokens_seen"}
    if "selection_cursor" in data_cursor or data_cursor.get("schema_version") == TRAINING_CURSOR_SCHEMA_VERSION:
        if set(data_cursor) != p2b_fields or data_cursor.get("schema_version") != TRAINING_CURSOR_SCHEMA_VERSION:
            raise ValueError("P2B training cursor must have an exact outer schema")
        selection = data_cursor["selection_cursor"]
        selection_fields = {"schema_version", "selection_receipt_sha256", "selection_rule_id", "selected_ordinal", "next_source_index"}
        if not isinstance(selection, Mapping) or set(selection) != selection_fields or selection.get("schema_version") != SELECTION_CURSOR_SCHEMA_VERSION:
            raise ValueError("P2B training cursor requires an exact selection cursor")
        receipt_sha256 = selection.get("selection_receipt_sha256")
        if not isinstance(receipt_sha256, str) or len(receipt_sha256) != 64 or any(character not in "0123456789abcdef" for character in receipt_sha256):
            raise ValueError("P2B training cursor selection receipt is invalid")
        if not isinstance(selection.get("selection_rule_id"), str) or not selection["selection_rule_id"]:
            raise ValueError("P2B training cursor selection rule is invalid")
        for field in ("selected_ordinal", "next_source_index", "global_step", "tokens_seen"):
            value = selection[field] if field in selection else data_cursor[field]
            if type(value) is not int or value < 0:
                raise ValueError("P2B training cursor counters are invalid")
    else:
        if not required_cursor.issubset(data_cursor):
            raise ValueError("checkpoint data cursor must bind shard, record_index, global_step, and tokens_seen")
        if not isinstance(data_cursor["shard"], str) or not data_cursor["shard"]:
            raise ValueError("checkpoint data cursor shard must be a nonempty string")
        for field in ("record_index", "global_step", "tokens_seen"):
            if not isinstance(data_cursor[field], int) or data_cursor[field] < 0:
                raise ValueError(f"checkpoint data cursor {field} must be a nonnegative integer")
    _sha256_value(model_config_sha256, name="model_config_sha256")
    _sha256_value(contract_sha256, name="contract_sha256")
    if set(expert_genesis_sha256) != (set(EXPERT_NAMES) if expected_expert_names is None else expected_expert_names):
        raise ValueError("checkpoint requires genesis hashes for all four experts")
    for name, digest in expert_genesis_sha256.items():
        _sha256_value(digest, name=f"{name} expert genesis hash")


def _validate_p2b_checkpoint_progress(episode: Mapping[str, Any], candidate_data_cursor: Mapping[str, Any], parent_data_cursor: Mapping[str, Any]) -> dict[str, Any]:
    """Bind a P2B episode to the exact outer training-cursor delta without I/O."""

    if not isinstance(episode, Mapping):
        raise ValueError("P2B checkpoint episode is invalid")
    for field in ("completed_updates", "training_token_delta"):
        if type(episode.get(field)) is not int or episode[field] <= 0:
            raise ValueError("P2B checkpoint episode counters are invalid")
    end = episode.get("end_selection_cursor")
    expected_outer = {"schema_version", "selection_cursor", "global_step", "tokens_seen"}
    if not isinstance(candidate_data_cursor, Mapping) or set(candidate_data_cursor) != expected_outer or candidate_data_cursor.get("schema_version") != TRAINING_CURSOR_SCHEMA_VERSION:
        raise ValueError("P2B checkpoint candidate cursor is invalid")
    if candidate_data_cursor.get("selection_cursor") != end:
        raise ValueError("P2B checkpoint cursor does not match episode end")
    if not isinstance(parent_data_cursor, Mapping) or set(parent_data_cursor) != {"global_step", "tokens_seen"}:
        raise ValueError("P2B checkpoint parent cursor is invalid")
    for cursor in (candidate_data_cursor, parent_data_cursor):
        for field in ("global_step", "tokens_seen"):
            if type(cursor.get(field)) is not int or cursor[field] < 0:
                raise ValueError("P2B checkpoint cursor counters are invalid")
    if candidate_data_cursor["global_step"] - parent_data_cursor["global_step"] != episode["completed_updates"]:
        raise ValueError("P2B checkpoint global-step delta does not match episode")
    if candidate_data_cursor["tokens_seen"] - parent_data_cursor["tokens_seen"] != episode["training_token_delta"]:
        raise ValueError("P2B checkpoint token delta does not match episode")
    return dict(candidate_data_cursor)


def _external_checkpoint_manifest(path: Path, *, label: str) -> tuple[dict[str, Any], str]:
    """Verify an externally supplied parent/root bundle without serializing its path."""

    path = Path(path).resolve()
    if not path.is_file() or path.name != "checkpoint-manifest.json":
        raise ValueError(f"{label} manifest must be an externally supplied checkpoint manifest")
    try:
        manifest_bytes = path.read_bytes()
        manifest = json.loads(manifest_bytes)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} manifest is not JSON") from error
    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    if manifest.get("schema_version") not in {
        "ember-sparse-checkpoint-v3",
        "ember-sparse-checkpoint-v4",
        "ember-sparse-checkpoint-v5",
    }:
        raise ValueError(f"{label} manifest has an unsupported schema")
    _validated_records(path.parent, {**manifest, "checkpoint_manifest_sha256": manifest_sha256})
    experts = manifest.get("expert_checkpoint_sha256")
    genesis = manifest.get("expert_genesis_sha256")
    if not isinstance(experts, Mapping) or set(experts) != set(EXPERT_NAMES):
        raise ValueError(f"{label} manifest lacks the four expert checkpoint hashes")
    if not isinstance(genesis, Mapping) or set(genesis) != set(EXPERT_NAMES):
        raise ValueError(f"{label} manifest lacks the four expert genesis hashes")
    for name in EXPERT_NAMES:
        _sha256_value(experts[name], name=f"{label} {name} expert hash")
        _sha256_value(genesis[name], name=f"{label} {name} expert genesis hash")
    return dict(manifest), manifest_sha256


def preflight_specialist_lineage_sources(*, parent_manifest: Path, root_manifest: Path) -> dict[str, Any]:
    """Verify immutable parent/root bundles and history before CUDA allocation or staging."""

    parent, parent_sha256 = _external_checkpoint_manifest(Path(parent_manifest), label="parent")
    root, root_sha256 = _external_checkpoint_manifest(Path(root_manifest), label="root genesis")
    if not isinstance(parent.get("lineage"), Mapping):
        if parent_sha256 != root_sha256:
            raise ValueError("first specialist successor requires exact parent and root checkpoint hashes")
        history = []
    else:
        lineage = parent.get("lineage")
        if not isinstance(lineage, Mapping) or lineage.get("root_genesis_checkpoint_sha256") != root_sha256:
            raise ValueError("specialist lineage root must match the immutable parent root genesis")
        history = lineage.get("trained_expert_ids")
        if not isinstance(history, list):
            raise ValueError("parent lineage has invalid trained expert history")
    if any(name not in EXPERT_NAMES for name in history) or len(set(history)) != len(history):
        raise ValueError("parent lineage has invalid trained expert history")
    return {
        "parent_checkpoint_sha256": parent_sha256,
        "root_genesis_checkpoint_sha256": root_sha256,
        "parent_history": list(history),
    }

def _attested_parent_optimizer_expert_routes(
    parent: Mapping[str, Any], *, parent_root: Path | None = None,
    parent_manifest_sha256: str | None = None,
) -> tuple[str, ...]:
    """Reopen an external parent's owner shards before granting route inheritance.

    Legacy aggregate optimizer payloads cannot independently recover
    parameter-to-route ownership and therefore attest no inherited specialist
    routes. Owner-sharded parents must rederive every route byte from immutable
    payloads and match the stored projection exactly; a forged parent refuses
    instead of degrading into candidate-authored route authority.
    """

    projection = parent.get("storage_projection")
    if not isinstance(projection, Mapping):
        return ()
    if (
        parent_root is None
        or parent_manifest_sha256 is None
        or parent.get("optimizer_state_layout")
        != _OWNER_SHARDED_OPTIMIZER_STATE_LAYOUT
    ):
        return ()
    parent_receipt = {
        **parent,
        "checkpoint_manifest_sha256": parent_manifest_sha256,
    }
    records = _validated_records(parent_root, parent_receipt)
    owner_authority = _validate_owner_sharded_optimizer_payloads(
        parent_root,
        parent_receipt,
        records,
        expected_optimizer_contract=parent_receipt.get("optimizer_contract"),
        expected_optimizer_realization=parent_receipt.get("optimizer_realization"),
    )
    _validate_owner_storage_projection_authority(parent_receipt, owner_authority)
    return tuple(owner_authority["specialist_owner_ids"])


def _packed_cursor(value: Mapping[str, Any], *, label: str) -> dict[str, int]:
    if not isinstance(value, Mapping) or set(value) != _PACKED_CURSOR_FIELDS:
        raise ValueError(f"{label} must use the closed packed cursor projection")
    cursor = dict(value)
    if any(type(cursor[field]) is not int or cursor[field] < 0 for field in _PACKED_CURSOR_FIELDS):
        raise ValueError(f"{label} counters must be nonnegative integers")
    return cursor


def _packed_cursor_from_training_state(value: Mapping[str, Any]) -> dict[str, int]:
    selection_cursor = value.get("packed_selection_cursor")
    if not isinstance(selection_cursor, Mapping):
        raise ValueError("packed fresh-genesis checkpoint lacks its selection cursor")
    return _packed_cursor({
        "selected_ordinal": selection_cursor.get("selected_ordinal"),
        "global_step": value.get("global_step"),
        "tokens_seen": value.get("tokens_seen"),
        "processed_tokens_seen": value.get("processed_tokens_seen"),
        "pack_ordinal": value.get("pack_ordinal"),
    }, label="packed fresh-genesis checkpoint cursor")


def build_packed_fresh_genesis_specialist_lineage(
    *, source_commit: str, model_config_sha256: str, seed: int,
    active_expert: str, selection_receipt_sha256: str,
    execution_record_order_sha256: str, execution_tokens_sha256: str,
    pack_sequence_sha256: str, initial_cursor: Mapping[str, Any],
    checkpoint_cursor: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the closed no-parent lineage for issue #1413's first audio checkpoint."""

    if (
        not isinstance(source_commit, str)
        or len(source_commit) != 40
        or any(character not in "0123456789abcdef" for character in source_commit)
    ):
        raise ValueError("packed fresh-genesis source commit must be lowercase 40hex")
    for value, label in (
        (model_config_sha256, "model config"),
        (selection_receipt_sha256, "selection receipt"),
        (execution_record_order_sha256, "execution record order"),
        (execution_tokens_sha256, "execution tokens"),
        (pack_sequence_sha256, "pack sequence"),
    ):
        _sha256_value(value, name=f"packed fresh-genesis {label} hash")
    if type(seed) is not int or seed < 0:
        raise ValueError("packed fresh-genesis seed must be a nonnegative integer")
    if active_expert not in EXPERT_NAMES:
        raise ValueError("packed fresh-genesis lineage requires one specialist expert")
    initial = _packed_cursor(initial_cursor, label="packed fresh-genesis initial cursor")
    checkpoint = _packed_cursor(checkpoint_cursor, label="packed fresh-genesis checkpoint cursor")
    if (
        checkpoint["selected_ordinal"] <= initial["selected_ordinal"]
        or checkpoint["global_step"] <= initial["global_step"]
        or checkpoint["tokens_seen"] <= initial["tokens_seen"]
        or checkpoint["processed_tokens_seen"] < checkpoint["tokens_seen"]
        or checkpoint["pack_ordinal"] <= initial["pack_ordinal"]
    ):
        raise ValueError("packed fresh-genesis checkpoint cursor made no valid progress")
    genesis_lineage_sha256 = _canonical_sha256({
        "schema_version": "ember-issue1413-packed-fresh-genesis-v1",
        "lineage_mode": _PACKED_FRESH_GENESIS_MODE,
        "source_commit": source_commit,
        "model_config_sha256": model_config_sha256,
        "seed": seed,
    })
    lineage: dict[str, Any] = {
        "schema_version": _PACKED_FRESH_GENESIS_LINEAGE_SCHEMA,
        "lineage_mode": _PACKED_FRESH_GENESIS_MODE,
        "source_commit": source_commit,
        "model_config_sha256": model_config_sha256,
        "seed": seed,
        "active_expert": active_expert,
        "trained_expert_ids": [active_expert],
        "genesis_lineage_sha256": genesis_lineage_sha256,
        "selection_receipt_sha256": selection_receipt_sha256,
        "execution_record_order_sha256": execution_record_order_sha256,
        "execution_tokens_sha256": execution_tokens_sha256,
        "pack_sequence_sha256": pack_sequence_sha256,
        "initial_cursor": initial,
        "checkpoint_cursor": checkpoint,
    }
    lineage["lineage_sha256"] = _canonical_sha256(lineage)
    return lineage


def _validate_packed_fresh_genesis_specialist_lineage(
    lineage: Mapping[str, Any],
) -> dict[str, Any] | None:
    if lineage.get("schema_version") != _PACKED_FRESH_GENESIS_LINEAGE_SCHEMA:
        return None
    if set(lineage) != _PACKED_FRESH_GENESIS_LINEAGE_FIELDS:
        raise ValueError("packed fresh-genesis lineage has an invalid closed shape")
    rebuilt = build_packed_fresh_genesis_specialist_lineage(
        source_commit=lineage["source_commit"],
        model_config_sha256=lineage["model_config_sha256"],
        seed=lineage["seed"],
        active_expert=lineage["active_expert"],
        selection_receipt_sha256=lineage["selection_receipt_sha256"],
        execution_record_order_sha256=lineage["execution_record_order_sha256"],
        execution_tokens_sha256=lineage["execution_tokens_sha256"],
        pack_sequence_sha256=lineage["pack_sequence_sha256"],
        initial_cursor=lineage["initial_cursor"],
        checkpoint_cursor=lineage["checkpoint_cursor"],
    )
    if rebuilt != dict(lineage):
        raise ValueError("packed fresh-genesis lineage derived fields are inconsistent")
    return rebuilt


def _specialist_lineage(
    lineage: Mapping[str, Any], *, active_expert: str, candidate_parameter_sha256: Mapping[str, str],
    expert_genesis_sha256: Mapping[str, str] | None = None,
    model_config_sha256: str | None = None, launch_seed: int | None = None,
    data_cursor: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, str], dict[str, str], Path | None, tuple[str, ...]]:
    """Close one-family accretion against independently supplied parent/root bundles."""

    if active_expert not in EXPERT_NAMES:
        raise ValueError("specialist lineage requires one specialist active expert")
    fresh = _validate_packed_fresh_genesis_specialist_lineage(lineage)
    if fresh is not None:
        if fresh["active_expert"] != active_expert:
            raise ValueError("packed fresh-genesis lineage active expert drifted")
        if fresh["model_config_sha256"] != model_config_sha256 or fresh["seed"] != launch_seed:
            raise ValueError("packed fresh-genesis lineage launch identity drifted")
        if not isinstance(data_cursor, Mapping) or fresh["checkpoint_cursor"] != _packed_cursor_from_training_state(data_cursor):
            raise ValueError("packed fresh-genesis lineage checkpoint cursor drifted")
        if not isinstance(expert_genesis_sha256, Mapping) or set(expert_genesis_sha256) != set(EXPERT_NAMES):
            raise ValueError("packed fresh-genesis lineage lacks the four initial expert hashes")
        if candidate_parameter_sha256[active_expert] == expert_genesis_sha256[active_expert]:
            raise ValueError("packed fresh-genesis active expert did not change from genesis")
        for name in EXPERT_NAMES:
            if name != active_expert and candidate_parameter_sha256[name] != expert_genesis_sha256[name]:
                raise ValueError(f"packed fresh-genesis inactive expert changed from genesis: {name}")
        return fresh, dict(expert_genesis_sha256), {}, None, ()
    p2b_fields = {"parent_manifest", "root_manifest", "trained_expert_ids", "episode"}
    p2b_cursor = isinstance(data_cursor, Mapping) and (
        "selection_cursor" in data_cursor or data_cursor.get("schema_version") == TRAINING_CURSOR_SCHEMA_VERSION
    )
    is_p2b = isinstance(lineage, Mapping) and set(lineage) == p2b_fields
    if p2b_cursor and not is_p2b:
        raise ValueError("P2B training cursor requires P2B specialist lineage")
    if is_p2b and not p2b_cursor:
        raise ValueError("P2B specialist lineage requires a P2B training cursor")
    required = {"parent_manifest", "root_manifest", "trained_expert_ids", "data_verification_receipt", "execution_slice"}
    expected_fields = {*required, "scene_split_selection"} if active_expert == "vision" else required
    if not is_p2b and (not isinstance(lineage, Mapping) or set(lineage) != expected_fields):
        raise ValueError("specialist lineage has an invalid shape")
    parent_source, root_source = lineage["parent_manifest"], lineage["root_manifest"]
    if not isinstance(parent_source, (str, Path)) or not isinstance(root_source, (str, Path)):
        raise ValueError("specialist lineage requires content-addressed external manifests")
    parent_path = Path(parent_source).resolve()
    root_path = Path(root_source).resolve()
    parent, parent_sha256 = _external_checkpoint_manifest(parent_path, label="parent")
    root, root_sha256 = _external_checkpoint_manifest(root_path, label="root genesis")
    # Bound to the same one-byte manifest snapshot the lineage hashes: a second
    # read here could attest routes from different bytes than parent_sha256.
    parent_optimizer_routes = _attested_parent_optimizer_expert_routes(
        parent,
        parent_root=parent_path.parent,
        parent_manifest_sha256=parent_sha256,
    )
    parent_lineage = parent.get("lineage")
    if not isinstance(parent_lineage, Mapping):
        if parent_sha256 != root_sha256:
            raise ValueError("first specialist successor requires exact parent and root checkpoint hashes")
        parent_history = []
    else:
        if not isinstance(parent_lineage, Mapping) or parent_lineage.get("root_genesis_checkpoint_sha256") != root_sha256:
            raise ValueError("specialist lineage root must match the immutable parent root genesis")
        parent_history = parent_lineage.get("trained_expert_ids")
        if not isinstance(parent_history, list):
            raise ValueError("parent lineage has invalid trained expert history")
    if any(name not in EXPERT_NAMES for name in parent_history) or len(set(parent_history)) != len(parent_history):
        raise ValueError("parent lineage has invalid trained expert history")
    trained = lineage["trained_expert_ids"]
    expected_history = [*parent_history, *([] if active_expert in parent_history else [active_expert])]
    if trained != expected_history:
        raise ValueError("specialist lineage trained experts must be parent history union active expert")
    parent_experts = parent["expert_checkpoint_sha256"]
    parent_parameters = parent.get("expert_parameter_sha256", parent["expert_genesis_sha256"])
    root_parameters = root.get("expert_parameter_sha256", root["expert_genesis_sha256"])
    if candidate_parameter_sha256[active_expert] == parent_parameters[active_expert]:
        raise ValueError("active expert parameter content must change from parent")
    for name in EXPERT_NAMES:
        if name == active_expert:
            continue
        if candidate_parameter_sha256[name] != parent_parameters[name]:
            raise ValueError(f"inactive expert parameter content changed from parent: {name}")
        if name not in trained and candidate_parameter_sha256[name] != root_parameters[name]:
            raise ValueError(f"not-yet-trained expert must remain equal to root genesis: {name}")
    if is_p2b:
        episode = validate_p2b_stream_episode(lineage["episode"], active_expert=active_expert)
        parent_cursor = parent.get("data_cursor")
        if not isinstance(parent_cursor, Mapping):
            raise ValueError("P2B specialist lineage parent lacks a replay cursor")
        _validate_p2b_checkpoint_progress(
            episode,
            data_cursor,
            {"global_step": parent_cursor.get("global_step"), "tokens_seen": parent_cursor.get("tokens_seen")},
        )
        return ({
            "parent_checkpoint_sha256": parent_sha256,
            "root_genesis_checkpoint_sha256": root_sha256,
            "trained_expert_ids": list(trained),
            "episode": episode,
        }, dict(root["expert_genesis_sha256"]), dict(parent_experts), parent_path.parent, parent_optimizer_routes)
    verification = lineage["data_verification_receipt"]
    capability_experts = {"image": "vision", "audio": "audio", "reasoning": "reasoning", "tool": "tool"}
    if not isinstance(verification, Mapping) or set(verification) != SPECIALIST_VERIFICATION_FIELDS:
        raise ValueError("specialist lineage requires the exact executed data verification receipt")
    if verification.get("schema_version") != "ember-training-data-verification-v1" or verification.get("result") != "VERIFIED" or verification.get("data_class") != "SEMANTIC_PRETRAINING" or verification.get("generator_replay_verified") is not True:
        raise ValueError("specialist lineage data verification was not replay-verified")
    if verification.get("admission") != "ADMISSIBLE_SEMANTIC_CONTRACT":
        raise ValueError("specialist lineage data verification lacks semantic-contract admission")
    for field in ("semantic_model_contract_sha256", "runtime_semantic_model_contract_sha256"):
        _sha256_value(verification.get(field), name=f"specialist verification {field}")
    if verification["semantic_model_contract_sha256"] != verification["runtime_semantic_model_contract_sha256"]:
        raise ValueError("specialist lineage data verification semantic contract differs from runtime")
    expected_checks = {"image": ["token_roundtrip", "source_target_pair", "raw_image_text_pair"], "audio": ["token_roundtrip", "source_target_pair", "raw_audio_text_pair"], "reasoning": ["token_roundtrip", "source_target_pair", "local_answer_execution"], "tool": ["token_roundtrip", "source_target_pair", "typed_tool_execution"]}
    if capability_experts.get(verification.get("capability")) != active_expert:
        raise ValueError("specialist lineage verification capability does not map to active expert")
    if verification.get("semantic_checks") != expected_checks[verification["capability"]]:
        raise ValueError("specialist lineage verification semantic checks are not canonical")
    for field in ("data_manifest_sha256", "tokenizer_sha256", "verifier_sha256", "source_manifest_sha256", "records_artifact_sha256"):
        _sha256_value(verification.get(field), name=f"specialist verification {field}")
    if type(verification.get("record_count")) is not int or verification["record_count"] <= 0 or type(verification.get("token_count")) is not int or verification["token_count"] <= 0:
        raise ValueError("specialist lineage verification has no training evidence")
    scene_selection: Mapping[str, Any] | None = None
    if active_expert == "vision":
        scene_selection = lineage["scene_split_selection"]
        selection_fields = {"schema_version", "capability", "scene_split", "full_records_artifact_sha256", "selected_record_count", "selected_token_count", "selected_records_sha256", "selected_tokens_sha256"}
        if (not isinstance(scene_selection, Mapping) or set(scene_selection) != selection_fields
                or scene_selection.get("schema_version") != "ember-specialist-scene-split-selection-v1"
                or scene_selection.get("capability") != "image" or scene_selection.get("scene_split") != "train"
                or scene_selection.get("full_records_artifact_sha256") != verification.get("records_artifact_sha256")):
            raise ValueError("vision specialist lineage lacks a closed train scene split selection")
        for field in ("full_records_artifact_sha256", "selected_records_sha256", "selected_tokens_sha256"):
            _sha256_value(scene_selection.get(field), name=f"vision scene split {field}")
        for field in ("selected_record_count", "selected_token_count"):
            if type(scene_selection.get(field)) is not int or scene_selection[field] <= 0:
                raise ValueError("vision specialist lineage has invalid scene split selected counts")
    execution_slice = lineage["execution_slice"]
    slice_fields = {"schema_version", "start_record", "record_count", "token_count", "records_sha256", "tokens_sha256"}
    allowed_slice_fields = slice_fields | ({"scene_split_record_count"} if scene_selection is not None else set())
    if not isinstance(execution_slice, Mapping) or set(execution_slice) != allowed_slice_fields:
        raise ValueError("specialist lineage execution slice has an invalid shape")
    if execution_slice.get("schema_version") != "ember-specialist-execution-slice-v1":
        raise ValueError("specialist lineage execution slice has an unsupported schema")
    if type(execution_slice.get("start_record")) is not int or execution_slice["start_record"] < 0:
        raise ValueError("specialist lineage execution slice has an invalid start record")
    for field in ("record_count", "token_count"):
        if type(execution_slice.get(field)) is not int or execution_slice[field] <= 0:
            raise ValueError(f"specialist lineage execution slice has an invalid {field}")
    if execution_slice["start_record"] + execution_slice["record_count"] > verification["record_count"]:
        raise ValueError("specialist lineage execution slice exceeds the verified corpus")
    if scene_selection is not None and (
            set(execution_slice) != {"schema_version", "start_record", "record_count", "token_count", "records_sha256", "tokens_sha256", "scene_split_record_count"}
            or execution_slice["scene_split_record_count"] != scene_selection["selected_record_count"]
            or execution_slice["start_record"] + execution_slice["record_count"] > scene_selection["selected_record_count"]
            or execution_slice["token_count"] > scene_selection["selected_token_count"]):
        raise ValueError("vision specialist execution slice does not bind the selected train receipt")
    for field in ("records_sha256", "tokens_sha256"):
        _sha256_value(execution_slice.get(field), name=f"specialist execution slice {field}")
    return ({
        "parent_checkpoint_sha256": parent_sha256,
        "root_genesis_checkpoint_sha256": root_sha256,
        "trained_expert_ids": list(trained),
        "episode": {
            "active_expert": active_expert,
            "data_verification_receipt": dict(verification),
            "data_verification_receipt_sha256": _canonical_sha256(verification),
            "execution_slice": dict(execution_slice),
            "execution_slice_sha256": _canonical_sha256(execution_slice),
            **({"scene_split_selection": dict(scene_selection), "scene_split_selection_sha256": _canonical_sha256(scene_selection)} if scene_selection is not None else {}),
        },
    }, dict(root["expert_genesis_sha256"]), dict(parent_experts), parent_path.parent, parent_optimizer_routes)
def _link_or_copy_verified(
    source: Path,
    target: Path,
    expected_sha256: str,
    *,
    max_transient_scratch_bytes: int | None = None,
) -> tuple[Path, str]:
    publication_mode = "copy"
    try:
        os.link(source, target)
        source_stat = source.stat()
        target_stat = target.stat()
        if (
            source_stat.st_dev == target_stat.st_dev
            and source_stat.st_ino == target_stat.st_ino
            and target_stat.st_nlink > 1
        ):
            publication_mode = "hardlink"
        else:
            target.unlink(missing_ok=True)
            if max_transient_scratch_bytes is not None:
                raise RuntimeError(
                    "inactive-bank copy fallback is forbidden under the "
                    "transient scratch cap"
                )
            shutil.copyfile(source, target)
    except OSError:
        target.unlink(missing_ok=True)
        if max_transient_scratch_bytes is not None:
            raise RuntimeError(
                "inactive-bank copy fallback is forbidden under the "
                "transient scratch cap"
            )
        shutil.copyfile(source, target)
    if _sha256(target) != expected_sha256:
        raise ValueError("parent expert shard hash mismatch during inactive-bank reuse")
    return target, publication_mode


def _materialize_counter_receipt(returned: Any) -> dict[str, Any]:
    """Force every callback-controlled Mapping access before closure revalidation."""

    if not isinstance(returned, Mapping):
        raise ValueError("post-run judge must return a validated counter receipt")
    try:
        encoded = json.dumps(dict(returned.items()), sort_keys=True, separators=(",", ":"))
        materialized = json.loads(encoded)
    except (TypeError, ValueError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("post-run judge returned a non-JSON counter receipt") from error
    if not isinstance(materialized, dict):
        raise ValueError("post-run judge must return a counter receipt object")
    return materialized


def _validate_counter_receipt(manifest_receipt: Mapping[str, Any], returned: Mapping[str, Any], persisted: Any) -> dict[str, Any]:
    """Validate only immutable snapshots; this function must never read candidate paths."""

    validated = validate_realization_receipt(returned)
    if not isinstance(persisted, Mapping) or validate_realization_receipt(persisted) != validated:
        raise ValueError("post-run counter receipt file does not match the judge result")
    architecture = manifest_receipt.get("architecture")
    if not isinstance(architecture, Mapping):
        raise ValueError("checkpoint manifest lacks measured architecture for counter validation")
    expected = {
        "model_config_sha256": manifest_receipt.get("model_config_sha256"),
        "subject_checkpoint_sha256": manifest_receipt.get("checkpoint_manifest_sha256"),
        "architecture_revision": manifest_receipt.get("architecture_revision"),
        "counter_sha256": _sha256(Path(__file__).with_name("parameter_counter.py")),
        "active_expert_ids": manifest_receipt.get("active_expert_ids"),
        "expert_genesis_sha256": manifest_receipt.get("expert_genesis_sha256"),
        "expert_parameter_sha256": manifest_receipt.get("expert_parameter_sha256"),
    }
    for field in ("allocated_parameters", "unique_parameters", "trainable_parameters", "served_parameters", "active_parameters", "episode_trainable_parameters"):
        expected[field] = architecture.get(field)
    if any(validated.get(field) != value for field, value in expected.items()):
        raise ValueError("post-run counter receipt does not bind subject, source, genesis, or measured counts")
    return validated


def _validate_owner_sharded_optimizer_payloads(
    root: Path,
    receipt: Mapping[str, Any],
    records: Mapping[str, Mapping[str, Any]],
    *,
    expected_optimizer_contract: Mapping[str, Any] | None = None,
    expected_optimizer_realization: Mapping[str, Any] | None = None,
    expected_parameter_names: set[str] | None = None,
) -> dict[str, Any]:
    optimizer_contract = _validate_optimizer_contract(receipt.get("optimizer_contract", {}))
    optimizer_realization = _validate_optimizer_realization(
        optimizer_contract, receipt.get("optimizer_realization")
    )
    if expected_optimizer_contract is not None:
        expected_contract = _validate_optimizer_contract(expected_optimizer_contract)
        if optimizer_contract != expected_contract:
            raise ValueError("checkpoint optimizer contract does not match runtime optimizer authority")
        if expected_optimizer_realization is None:
            raise ValueError("runtime optimizer realization is required with runtime optimizer contract")
        expected_realization = _validate_optimizer_realization(
            expected_contract, expected_optimizer_realization
        )
        if optimizer_realization != expected_realization:
            raise ValueError("checkpoint optimizer realization does not match runtime optimizer authority")
    owner_ids = receipt.get("optimizer_state_owner_ids")
    owner_by_parameter = receipt.get("optimizer_state_owner_by_parameter")
    owner_hashes = receipt.get("optimizer_state_owner_shard_sha256")
    if (
        not isinstance(owner_ids, list)
        or not isinstance(owner_by_parameter, Mapping)
        or not isinstance(owner_hashes, Mapping)
        or owner_ids != [owner for owner in ["shared", *EXPERT_NAMES] if owner in owner_ids]
        or set(owner_ids) != set(owner_hashes)
        or set(owner_by_parameter.values()) - set(owner_ids)
    ):
        raise ValueError("checkpoint optimizer owner projection is not closed")
    _optimizer_state_shard_paths(owner_ids)
    merged: dict[str, str] = {}
    route_storage_bytes = {"shared": 0, **{name: 0 for name in EXPERT_NAMES}}
    parameter_groups: list[Mapping[str, Any]] | None = None
    for owner in owner_ids:
        relative = f"optimizer-state-{owner}.pt"
        if relative not in records:
            raise ValueError(f"checkpoint optimizer owner shard is missing: {owner}")
        if owner_hashes.get(owner) != records[relative].get("sha256"):
            raise ValueError(f"checkpoint optimizer owner shard hash is not bound: {owner}")
        payload = torch.load(root / relative, map_location="cpu", weights_only=False, mmap=True)
        if (
            not isinstance(payload, Mapping)
            or set(payload) != {"schema_version", "owner", "state", "param_groups", "optimizer_contract", "optimizer_realization"}
            or payload.get("schema_version") != "ember-optimizer-owner-shard-v1"
            or payload.get("owner") != owner
            or payload.get("optimizer_contract") != optimizer_contract
            or payload.get("optimizer_realization") != optimizer_realization
            or not isinstance(payload.get("state"), Mapping)
            or not payload["state"]
            or not isinstance(payload.get("param_groups"), list)
        ):
            raise ValueError(f"checkpoint optimizer owner payload is malformed: {owner}")
        if parameter_groups is None:
            parameter_groups = payload["param_groups"]
        elif payload["param_groups"] != parameter_groups:
            raise ValueError("checkpoint optimizer owner payloads disagree on parameter groups")
        for name in payload["state"]:
            if (
                not isinstance(name, str)
                or (expected_parameter_names is not None and name not in expected_parameter_names)
                or _optimizer_owner_for_parameter(name) != owner
                or name in merged
            ):
                raise ValueError("checkpoint optimizer owner payload violates closed ownership")
            merged[name] = owner
        route_storage_bytes[owner] = _unique_tensor_storage_bytes(payload["state"])
        if route_storage_bytes[owner] < 1:
            raise ValueError(
                f"checkpoint optimizer owner payload has no tensor storage: {owner}"
            )
        del payload
    if dict(sorted(merged.items())) != dict(sorted(owner_by_parameter.items())):
        raise ValueError("checkpoint optimizer owner projection does not match shard payloads")
    if parameter_groups is None:
        raise ValueError("checkpoint optimizer owner payloads have no parameter groups")
    for descriptor in parameter_groups:
        if not isinstance(descriptor, Mapping) or "param_names" not in descriptor:
            raise ValueError("checkpoint optimizer parameter-group descriptor is malformed")
        names = descriptor["param_names"]
        if (
            not isinstance(names, list)
            or len(names) != len(set(names))
            or any(not isinstance(name, str) for name in names)
            or (
                expected_parameter_names is not None
                and any(name not in expected_parameter_names for name in names)
            )
        ):
            raise ValueError("checkpoint optimizer parameter-group names are invalid")
    return {
        "route_storage_bytes": route_storage_bytes,
        "specialist_owner_ids": [
            name for name in EXPERT_NAMES if route_storage_bytes[name] > 0
        ],
        "optimizer_state_tensor_storage_lower_bound_bytes": sum(
            route_storage_bytes.values()
        ),
    }


def _validate_owner_storage_projection_authority(
    receipt: Mapping[str, Any],
    owner_storage_authority: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind candidate projection claims to reopened owner-shard tensor bytes."""

    validated_projection = _validate_checkpoint_storage_projection(
        receipt.get("storage_projection")
    )
    expected_active_ids = (
        ["shared"]
        if validated_projection["active_expert"] == "shared"
        else owner_storage_authority["specialist_owner_ids"]
    )
    if (
        validated_projection.get("optimizer_state_owner_ids")
        != receipt.get("optimizer_state_owner_ids")
        or validated_projection[
            "optimizer_state_tensor_storage_by_route_bytes"
        ]
        != owner_storage_authority["route_storage_bytes"]
        or validated_projection["optimizer_state_active_expert_ids"]
        != expected_active_ids
        or validated_projection[
            "optimizer_state_tensor_storage_lower_bound_bytes"
        ]
        != owner_storage_authority[
            "optimizer_state_tensor_storage_lower_bound_bytes"
        ]
    ):
        raise ValueError(
            "checkpoint optimizer owner payload does not match storage projection"
        )
    return validated_projection


def _checkpoint_candidate_receipt(
    candidate: Path,
    *,
    expected_optimizer_contract: Mapping[str, Any] | None = None,
    expected_optimizer_realization: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    manifest_path = candidate / "checkpoint-manifest.json"
    if _is_link_or_reparse(manifest_path):
        raise ValueError("checkpoint manifest cannot be a symlink or reparse point")
    try:
        manifest_bytes = manifest_path.read_bytes()
        manifest = json.loads(manifest_bytes)
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("quarantined checkpoint candidate lacks a valid manifest") from error
    if not isinstance(manifest, dict):
        raise ValueError("quarantined checkpoint candidate manifest is not an object")
    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    receipt = {**manifest, "checkpoint_manifest_sha256": manifest_sha256}
    if manifest.get('schema_version') == 'ember-cia-checkpoint-v1':
        if expected_optimizer_contract is not None or expected_optimizer_realization is None:
            raise ValueError('CIA admission requires its captured runtime optimizer realization')
        if manifest.get('optimizer_identity') != expected_optimizer_realization:
            raise ValueError('CIA admission optimizer identity differs from runtime realization')
        return _cia_validated_checkpoint(candidate, receipt)[0]
    records = _validated_records(candidate, receipt)
    owner_storage_authority: dict[str, Any] | None = None
    if receipt.get("optimizer_state_layout") == _OWNER_SHARDED_OPTIMIZER_STATE_LAYOUT:
        if expected_optimizer_contract is None or expected_optimizer_realization is None:
            raise ValueError("owner-sharded checkpoint admission requires runtime optimizer authority")
        try:
            owner_storage_authority = _validate_owner_sharded_optimizer_payloads(
                candidate,
                receipt,
                records,
                expected_optimizer_contract=expected_optimizer_contract,
                expected_optimizer_realization=expected_optimizer_realization,
            )
        except ValueError:
            raise
        except Exception as error:
            raise ValueError("checkpoint optimizer owner payload cannot be read") from error
    projection = receipt.get("storage_projection")
    if projection is not None:
        validated_projection = (
            _validate_owner_storage_projection_authority(
                receipt, owner_storage_authority
            )
            if owner_storage_authority is not None
            else _validate_checkpoint_storage_projection(projection)
        )
        retained_paths = sorted(
            path
            for path, record in records.items()
            if record.get("publication_mode") == "hardlink"
        )
        if validated_projection["retained_shard_paths"] != retained_paths:
            raise ValueError(
                "checkpoint retained-shard projection does not match records"
            )
        if validated_projection["per_shard_sha256"] != {
            path: record["sha256"] for path, record in records.items()
        }:
            raise ValueError(
                "checkpoint shard-byte projection does not match records"
            )
        active_expert_ids = receipt.get("active_expert_ids")
        if active_expert_ids != [validated_projection["active_expert"]]:
            raise ValueError(
                "checkpoint storage projection route does not match manifest"
            )
        data_cursor = receipt.get("data_cursor")
        if (
            not isinstance(data_cursor, Mapping)
            or data_cursor.get("global_step")
            != validated_projection["optimizer_state_after_global_step"]
        ):
            raise ValueError(
                "checkpoint storage projection global step does not match manifest"
            )
        try:
            if validated_projection.get("optimizer_state_layout") == _OWNER_SHARDED_OPTIMIZER_STATE_LAYOUT:
                optimizer_payload = None
            else:
                optimizer_payload = torch.load(
                    candidate / "optimizer-state.pt",
                    map_location="cpu",
                    weights_only=False,
                    mmap=True,
                )
            replay_payload = torch.load(
                candidate / "replay-state.pt",
                map_location="cpu",
                weights_only=False,
                mmap=True,
            )
        except Exception as error:
            raise ValueError(
                "checkpoint projection payload bindings cannot be read"
            ) from error
        if optimizer_payload is not None and (
            not isinstance(optimizer_payload, Mapping)
            or set(optimizer_payload)
            != {"optimizer", "optimizer_contract", "optimizer_realization"}
            or optimizer_payload.get("optimizer_contract")
            != receipt.get("optimizer_contract")
            or optimizer_payload.get("optimizer_realization")
            != receipt.get("optimizer_realization")
        ):
            raise ValueError(
                "checkpoint optimizer projection payload does not match manifest"
            )
        if (
            not isinstance(replay_payload, Mapping)
            or replay_payload.get("data_cursor") != data_cursor
        ):
            raise ValueError(
                "checkpoint replay projection payload does not match manifest"
            )
        _measure_candidate_storage_projection(candidate, validated_projection)
    declared_files = {"checkpoint-manifest.json", *records}
    actual_files: set[str] = set()
    for path in candidate.rglob("*"):
        relative = path.relative_to(candidate).as_posix()
        if _is_link_or_reparse(path):
            raise ValueError("checkpoint candidate filesystem closure contains a symlink or reparse point")
        if path.is_dir():
            raise ValueError("checkpoint candidate filesystem closure contains an unexpected directory")
        if path.is_file():
            actual_files.add(relative)
    unexpected = actual_files - declared_files - _ALLOWED_CANDIDATE_METADATA
    missing = declared_files - actual_files
    if unexpected or missing:
        raise ValueError("checkpoint candidate filesystem closure is not exact")
    metadata: dict[str, dict[str, Any]] = {}
    counter_receipt_payload: dict[str, Any] | None = None
    for name in sorted(actual_files & _ALLOWED_CANDIDATE_METADATA):
        path = candidate / name
        try:
            payload_bytes = path.read_bytes()
        except OSError as error:
            raise ValueError("checkpoint candidate metadata cannot be read") from error
        metadata[name] = {"sha256": hashlib.sha256(payload_bytes).hexdigest(), "bytes": len(payload_bytes)}
        if name == "parameter-counter-receipt.json":
            try:
                payload = json.loads(payload_bytes)
            except (UnicodeError, json.JSONDecodeError) as error:
                raise ValueError("post-run judge did not persist a valid counter receipt") from error
            if not isinstance(payload, dict):
                raise ValueError("post-run judge did not persist a valid counter receipt")
            counter_receipt_payload = payload
    metadata_bytes = sum(int(item["bytes"]) for item in metadata.values())
    serialized_bytes = sum(int(record["bytes"]) for record in records.values()) + len(manifest_bytes) + metadata_bytes
    incremental_bytes = sum(int(record["incremental_bytes"]) for record in records.values()) + len(manifest_bytes) + metadata_bytes
    return {
        **receipt,
        "metadata": metadata,
        "serialized_bytes": serialized_bytes,
        "incremental_publication_bytes": incremental_bytes,
        "_counter_receipt_payload": counter_receipt_payload,
    }


def admit_quarantined_checkpoint(
    candidate: Path,
    published_root: Path,
    *,
    verifier: Callable[[Path, dict[str, Any]], Mapping[str, Any]],
    max_serialized_bytes: int | None = None,
    expected_optimizer_contract: Mapping[str, Any] | None = None,
    expected_optimizer_realization: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Judge durable raw bytes and atomically make only a passing candidate selectable."""

    candidate = candidate.resolve(strict=True)
    published_root = Path(published_root)
    published_root = published_root.parent.resolve(strict=True) / published_root.name
    quarantine = (published_root.parent / ".checkpoint-quarantine").resolve(strict=True)
    if candidate.parent != quarantine or not candidate.name.startswith("candidate-"):
        raise ValueError("checkpoint candidate is not in the bound quarantine namespace")
    if published_root.exists():
        raise FileExistsError(f"published checkpoint bundle already exists: {published_root}")
    if (candidate / _STAGING_LEASE).exists():
        raise ValueError("quarantined checkpoint candidate retains a writer lease")
    receipt = _checkpoint_candidate_receipt(
        candidate,
        expected_optimizer_contract=expected_optimizer_contract,
        expected_optimizer_realization=expected_optimizer_realization,
    )
    if receipt.get("storage_projection") is not None:
        _validate_checkpoint_storage_projection(
            receipt["storage_projection"],
            max_serialized_bytes=max_serialized_bytes,
        )
    failure_operands = _failure_comparison_operands_from_receipt(
        receipt,
        candidate,
        max_serialized_bytes=max_serialized_bytes,
    )
    try:
        # Take a snapshot after direct verifier work, then materialize the returned
        # Mapping before the final snapshot.  No callback-controlled object is touched
        # after final_snapshot.
        returned_counter_receipt = verifier(candidate, dict(receipt))
        try:
            post_callback_receipt = _checkpoint_candidate_receipt(
                candidate,
                expected_optimizer_contract=expected_optimizer_contract,
                expected_optimizer_realization=expected_optimizer_realization,
            )
        except Exception as error:
            if isinstance(error, ValueError) and "symlink or reparse" in str(error):
                raise
            raise ValueError("checkpoint candidate changed after verifier validation") from error
        volatile = {"metadata", "serialized_bytes", "incremental_publication_bytes", "_counter_receipt_payload"}
        initial_stable = {key: value for key, value in receipt.items() if key not in volatile}
        post_callback_stable = {key: value for key, value in post_callback_receipt.items() if key not in volatile}
        if post_callback_stable != initial_stable:
            raise ValueError("checkpoint candidate changed after verifier validation")
        returned_counter_receipt = _materialize_counter_receipt(returned_counter_receipt)
        _validate_counter_receipt(post_callback_receipt, returned_counter_receipt, post_callback_receipt.get("_counter_receipt_payload"))
        post_verifier_bytes = int(post_callback_receipt["incremental_publication_bytes"])
        if max_serialized_bytes is not None and post_verifier_bytes > max_serialized_bytes:
            raise ValueError("counter evidence exceeds the derived byte bound")
        if published_root.exists():
            raise FileExistsError(f"published checkpoint bundle appeared during admission: {published_root}")
        # This is deliberately the final candidate operation before no-replace promotion.
        final_receipt = _checkpoint_candidate_receipt(
            candidate,
            expected_optimizer_contract=expected_optimizer_contract,
            expected_optimizer_realization=expected_optimizer_realization,
        )
        if final_receipt != post_callback_receipt:
            raise ValueError("checkpoint candidate changed after verifier validation")
    except Exception as error:
        _retain_write_failure_evidence(
            published_root,
            candidate,
            error,
            comparison_operands=failure_operands,
        )
        raise
    try:
        _atomic_publish_no_replace(candidate, published_root)
    except OSError as error:
        if isinstance(error, FileExistsError) or error.errno in (errno.EEXIST, errno.ENOTEMPTY) or published_root.exists():
            _retain_write_failure_evidence(
                published_root,
                candidate,
                error,
                comparison_operands=failure_operands,
            )
            raise FileExistsError(f"published checkpoint bundle appeared during admission: {published_root}") from error
        raise
    published_receipt = {key: value for key, value in final_receipt.items() if key != "_counter_receipt_payload"}
    return _bind_checkpoint_identity(published_root, published_receipt)

def _write_checkpoint_artifacts_impl(
    model: UnifiedDecoder,
    optimizer: torch.optim.Optimizer,
    root: Path,
    *,
    launch_seed: int,
    rng_state: Mapping[str, torch.Tensor],
    data_cursor: Mapping[str, Any],
    model_config_sha256: str,
    contract_sha256: str,
    expert_genesis_sha256: Mapping[str, str],
    optimizer_contract: Mapping[str, Any] | None = None,
    optimizer_state_layout: str = "legacy-v1",
    specialist_lineage: Mapping[str, Any] | None = None,
    max_serialized_bytes: int | None = None,
    max_transient_scratch_bytes: int | None = None,
    host_commit_reserve_bytes: int | None = None,
    pre_publish_verifier: Callable[[Path, dict[str, Any]], Mapping[str, Any]],
) -> dict[str, Any]:
    """Publish complete post-step artifacts, manifest last, with replay bindings."""

    comparison_operands = _empty_failure_comparison_operands()
    if max_serialized_bytes is not None and (type(max_serialized_bytes) is not int or max_serialized_bytes < 1):
        raise ValueError("max_serialized_bytes must be a positive integer")
    if max_transient_scratch_bytes is not None and (
        type(max_transient_scratch_bytes) is not int
        or max_transient_scratch_bytes < 1
    ):
        raise ValueError("max_transient_scratch_bytes must be a positive integer")
    if not callable(pre_publish_verifier):
        raise ValueError("pre-publish verifier is required")
    comparison_operands = _merge_failure_comparison_operands(
        comparison_operands,
        {
            "derived_byte_bound_bytes": max_serialized_bytes,
            "derived_byte_bound_inputs": {
                "max_serialized_bytes": max_serialized_bytes,
                "max_transient_scratch_bytes": max_transient_scratch_bytes,
                "active_parameters": None,
                "model_config_sha256": model_config_sha256,
                "contract_sha256": contract_sha256,
                "optimizer_state_layout": optimizer_state_layout,
            },
            "projected_storage_floor_bytes": None,
            "projected_storage_floor_inputs": _empty_failure_comparison_operands()["projected_storage_floor_inputs"],
            "staged_shard_bytes": [],
            "available_commit_bytes": None,
            "required_commit_bytes": None,
        },
    )
    _validate_replay_bindings(
        launch_seed=launch_seed,
        rng_state=rng_state,
        data_cursor=data_cursor,
        model_config_sha256=model_config_sha256,
        contract_sha256=contract_sha256,
        expert_genesis_sha256=expert_genesis_sha256,
    )
    optimizer_contract = _validate_optimizer_contract(optimizer_contract or _default_optimizer_contract(optimizer))
    optimizer_realization = _optimizer_realization(optimizer, optimizer_contract)
    if optimizer_state_layout not in {"legacy-v1", _OWNER_SHARDED_OPTIMIZER_STATE_LAYOUT}:
        raise ValueError("checkpoint optimizer state layout is unsupported")
    expert_parameter_sha256 = model.expert_bank_genesis_hashes()
    preflight_lineage = None
    preflight_genesis = None
    specialist_parent_optimizer_routes: tuple[str, ...] | None = None
    if specialist_lineage is not None:
        preflight_lineage, preflight_genesis, preflight_parent_shards, preflight_parent_root, specialist_parent_optimizer_routes = _specialist_lineage(
            specialist_lineage,
            active_expert=model.active_expert,
            candidate_parameter_sha256=expert_parameter_sha256,
            expert_genesis_sha256=expert_genesis_sha256,
            model_config_sha256=model_config_sha256,
            launch_seed=launch_seed,
            data_cursor=data_cursor,
        )
    published_root = root
    if published_root.exists():
        raise FileExistsError(f"published checkpoint bundle already exists: {published_root}")
    host_commit_plan: dict[str, int | str] | None = None
    if host_commit_reserve_bytes is not None:
        host_commit_plan = checkpoint_commit_preflight(
            available_commit_bytes=available_host_commit_bytes(),
            streaming_peak_bytes=checkpoint_streaming_peak_bytes(model, optimizer),
            reserve_bytes=host_commit_reserve_bytes,
            comparison_operands=comparison_operands,
        )
    published_root.parent.mkdir(parents=True, exist_ok=True)
    staging_root = published_root.parent / f".{published_root.name}.{os.getpid()}.{uuid.uuid4().hex}.staging"
    model_state = model.state_dict()
    counts = measure_parameter_counts(model)
    comparison_operands["derived_byte_bound_inputs"]["active_parameters"] = int(
        counts["active_parameters"]
    )
    shared_state = _select_detached_state(model_state, lambda name: ".experts." not in name)
    optimizer_state_payload = optimizer.state_dict()
    optimizer_file_payload = {
        "optimizer": optimizer_state_payload,
        "optimizer_contract": optimizer_contract,
        "optimizer_realization": optimizer_realization,
    }
    owner_payloads: dict[str, dict[str, Any]] = {}
    owner_by_parameter: dict[str, str] = {}
    if optimizer_state_layout == _OWNER_SHARDED_OPTIMIZER_STATE_LAYOUT:
        owner_payloads, owner_by_parameter = _optimizer_owner_payloads(
            model,
            optimizer,
            optimizer_contract,
            optimizer_realization,
        )
    optimizer_owner_ids = list(owner_payloads)
    shard_storage_lower_bounds = {
        "shared-model.pt": _unique_tensor_storage_bytes(shared_state),
    }
    if optimizer_state_layout == _OWNER_SHARDED_OPTIMIZER_STATE_LAYOUT:
        shard_storage_lower_bounds.update(
            {
                f"optimizer-state-{owner}.pt": _unique_tensor_storage_bytes(
                    owner_payloads[owner]
                )
                for owner in optimizer_owner_ids
            }
        )
    else:
        shard_storage_lower_bounds["optimizer-state.pt"] = _unique_tensor_storage_bytes(
            optimizer_file_payload
        )
    shard_storage_lower_bounds["replay-state.pt"] = _unique_tensor_storage_bytes(rng_state)
    shard_storage_lower_bounds.update(
        {
            f"expert-{name}.pt": _unique_tensor_storage_bytes(
                _select_detached_state(
                    model_state,
                    lambda key, selected=name: f".experts.{selected}." in key,
                )
            )
            for name in EXPERT_NAMES
        }
    )
    if max_transient_scratch_bytes is not None:
        comparison_operands = _merge_failure_comparison_operands(
            comparison_operands,
            _storage_failure_comparison_operands(
                model=model,
                optimizer=optimizer,
                optimizer_file_payload=optimizer_file_payload,
                shard_storage_lower_bounds=shard_storage_lower_bounds,
                max_transient_scratch_bytes=max_transient_scratch_bytes,
                max_serialized_bytes=max_serialized_bytes,
                optimizer_state_layout=optimizer_state_layout,
                model_config_sha256=model_config_sha256,
                contract_sha256=contract_sha256,
                active_parameters=int(counts["active_parameters"]),
            ),
        )
        for shard_name, lower_bound in shard_storage_lower_bounds.items():
            if lower_bound > max_transient_scratch_bytes:
                error = _CheckpointWriteRefusal(
                    f"checkpoint {shard_name} tensor-storage lower bound "
                    f"{lower_bound} exceeds transient scratch cap "
                    f"{max_transient_scratch_bytes}",
                    comparison_operands=comparison_operands,
                )
                _retain_write_failure_evidence(
                    published_root,
                    staging_root,
                    error,
                    comparison_operands=comparison_operands,
                )
                raise error
    # The PID in the private name lets a later retention pass distinguish an
    # active writer from crash residue without publishing a mutable lease file
    # inside the checkpoint bundle.
    root = staging_root
    root.mkdir()
    try:
        _write_json_atomic(
            root,
            _STAGING_LEASE,
            {"pid": os.getpid(), "started_at_ns": time.time_ns()},
            max_transient_scratch_bytes=max_transient_scratch_bytes,
        )
        shared_model = _write_atomic(
            root,
            "shared-model.pt",
            lambda handle: torch.save({"model": shared_state}, handle),
            max_transient_scratch_bytes=max_transient_scratch_bytes,
        )
        shards = [_record(shared_model, root, role="shared_model")]
        if optimizer_state_layout == _OWNER_SHARDED_OPTIMIZER_STATE_LAYOUT:
            for owner in optimizer_owner_ids:
                owner_path = _write_atomic(
                    root,
                    f"optimizer-state-{owner}.pt",
                    lambda handle, payload=owner_payloads[owner]: torch.save(payload, handle),
                    max_transient_scratch_bytes=max_transient_scratch_bytes,
                )
                shards.append(
                    _record(owner_path, root, role=f"optimizer_state_{owner}")
                )
        else:
            optimizer_state_path = _write_atomic(
                root,
                "optimizer-state.pt",
                lambda handle: torch.save(optimizer_file_payload, handle),
                max_transient_scratch_bytes=max_transient_scratch_bytes,
            )
            shards.append(
                _record(optimizer_state_path, root, role="optimizer_state")
            )
        replay = _write_atomic(
            root,
            "replay-state.pt",
            lambda handle: torch.save(
                {
                    "rng_state": {
                        name: state.detach().cpu() for name, state in rng_state.items()
                    },
                    "data_cursor": dict(data_cursor),
                },
                handle,
            ),
            max_transient_scratch_bytes=max_transient_scratch_bytes,
        )
        shards.append(_record(replay, root, role="replay_state"))
        expert_checkpoint_sha256: dict[str, str] = {}
        for name in EXPERT_NAMES:
            publication_mode = "written"
            if (
                specialist_lineage is not None
                and preflight_parent_root is not None
                and name != model.active_expert
            ):
                path, publication_mode = _link_or_copy_verified(
                    preflight_parent_root / f"expert-{name}.pt",
                    root / f"expert-{name}.pt",
                    preflight_parent_shards[name],
                    max_transient_scratch_bytes=max_transient_scratch_bytes,
                )
            else:
                state = _select_detached_state(
                    model_state,
                    lambda key, selected=name: f".experts.{selected}." in key,
                )
                path = _write_atomic(
                    root,
                    f"expert-{name}.pt",
                    lambda handle, selected=name, selected_state=state: torch.save(
                        {"expert": selected, "model": selected_state}, handle
                    ),
                    max_transient_scratch_bytes=max_transient_scratch_bytes,
                )
            record = _record(path, root, role=f"expert_{name}", publication_mode=publication_mode)
            shards.append(record)
            expert_checkpoint_sha256[name] = record["sha256"]

        storage_projection = None
        if (
            max_transient_scratch_bytes is not None
            and max_serialized_bytes is not None
        ):
            storage_projection = _derive_checkpoint_storage_projection(
                model=model,
                optimizer=optimizer,
                optimizer_file_payload=optimizer_file_payload,
                shard_storage_lower_bounds=shard_storage_lower_bounds,
                shard_sha256={
                    str(record["path"]): str(record["sha256"])
                    for record in shards
                },
                publication_modes={
                    str(record["path"]): str(record["publication_mode"])
                    for record in shards
                },
                global_step=int(data_cursor["global_step"]),
                max_transient_scratch_bytes=max_transient_scratch_bytes,
                max_serialized_bytes=int(max_serialized_bytes),
                specialist_parent_optimizer_routes=specialist_parent_optimizer_routes,
                optimizer_state_layout=optimizer_state_layout,
                model_config_sha256=model_config_sha256,
                contract_sha256=contract_sha256,
                active_parameters=int(counts["active_parameters"]),
            )
            comparison_operands = _merge_failure_comparison_operands(
                comparison_operands,
                {
                    "derived_byte_bound_bytes": max_serialized_bytes,
                    "derived_byte_bound_inputs": comparison_operands["derived_byte_bound_inputs"],
                    "projected_storage_floor_bytes": storage_projection["all_expert_projected_tensor_storage_lower_bound_bytes"],
                    "projected_storage_floor_inputs": {
                        "route_multiplier": _optimizer_projection_route_multiplier(
                            routed_optimizer=storage_projection[
                                "optimizer_state_tensor_storage_by_route_bytes"
                            ],
                            active_expert=storage_projection["active_expert"],
                        ),
                        "active_expert": storage_projection["active_expert"],
                        "optimizer_state_layout": optimizer_state_layout,
                        "optimizer_state_tensor_storage_lower_bound_bytes": storage_projection["optimizer_state_tensor_storage_lower_bound_bytes"],
                        "projected_optimizer_state_tensor_storage_lower_bound_bytes": storage_projection["projected_all_expert_optimizer_state_tensor_storage_lower_bound_bytes"],
                        "optimizer_state_tensor_storage_by_route_bytes": storage_projection["optimizer_state_tensor_storage_by_route_bytes"],
                        "per_shard_tensor_storage_lower_bound_bytes": storage_projection["per_shard_tensor_storage_lower_bound_bytes"],
                        "retained_shard_paths": storage_projection["retained_shard_paths"],
                    },
                    "staged_shard_bytes": [],
                    "available_commit_bytes": None,
                    "required_commit_bytes": None,
                },
            )

        comparison_operands["derived_byte_bound_inputs"]["active_parameters"] = int(
            counts["active_parameters"]
        )
        expert_parameter_sha256 = model.expert_bank_genesis_hashes()
        lineage = None
        manifest_genesis = dict(expert_genesis_sha256)
        if specialist_lineage is not None:
            lineage, manifest_genesis = preflight_lineage, preflight_genesis
        manifest = {
            "schema_version": "ember-sparse-checkpoint-v5",
            "contract_version": 5,
            "architecture_revision": "ember-sparse-3b-v2",
            "architecture": {
                "revision": "ember-sparse-3b-v2",
                "allocated_parameters": int(counts["allocated_parameters"]),
                "unique_parameters": int(counts["unique_parameters"]),
                "trainable_parameters": int(counts["trainable_parameters"]),
                "served_parameters": int(counts["served_parameters"]),
                "active_parameters": int(counts["active_parameters"]),
                "episode_trainable_parameters": int(counts["episode_trainable_parameters"]),
                "shared_text_ffn": "always_active_SwiGLU_4H",
            },
            "launch_seed": launch_seed,
            "rng_state_sha256": {name: hashlib.sha256(state.detach().cpu().numpy().tobytes()).hexdigest() for name, state in rng_state.items()},
            "data_cursor": dict(data_cursor),
            "model_config_sha256": model_config_sha256,
            "contract_sha256": contract_sha256,
            "active_expert_ids": [model.active_expert],
            "expert_genesis_sha256": manifest_genesis,
            "expert_checkpoint_sha256": expert_checkpoint_sha256,
            "expert_parameter_sha256": expert_parameter_sha256,
            "shared_model_shard_sha256": shards[0]["sha256"],
            "optimizer_contract": optimizer_contract,
            "optimizer_realization": optimizer_realization,
            "shards": shards,
        }
        if optimizer_state_layout == _OWNER_SHARDED_OPTIMIZER_STATE_LAYOUT:
            manifest.update(
                {
                    "optimizer_state_layout": optimizer_state_layout,
                    "optimizer_state_owner_ids": list(optimizer_owner_ids),
                    "optimizer_state_owner_by_parameter": owner_by_parameter,
                    "optimizer_state_owner_shard_sha256": {
                        record["path"][len("optimizer-state-"):-len(".pt")]: record["sha256"]
                        for record in shards
                        if str(record["path"]).startswith("optimizer-state-")
                    },
                }
            )
        else:
            manifest["optimizer_state_shard_sha256"] = shards[1]["sha256"]
        if storage_projection is not None:
            manifest["storage_projection"] = storage_projection
        if lineage is not None:
            manifest["lineage"] = lineage
        if host_commit_plan is not None:
            manifest["host_commit_preflight"] = host_commit_plan
        manifest_path = _write_json_atomic(
            root,
            "checkpoint-manifest.json",
            manifest,
            max_transient_scratch_bytes=max_transient_scratch_bytes,
        )
        logical_serialized_bytes = sum(
            path.stat().st_size
            for path in root.rglob("*")
            if path.is_file() and path.name != _STAGING_LEASE
        )
        recorded_logical_bytes = sum(int(record["bytes"]) for record in shards) + manifest_path.stat().st_size
        if logical_serialized_bytes != recorded_logical_bytes:
            raise ValueError("checkpoint bundle contains unrecorded files")
        incremental_publication_bytes = sum(int(record["incremental_bytes"]) for record in shards) + manifest_path.stat().st_size
        if max_serialized_bytes is not None and incremental_publication_bytes > max_serialized_bytes:
            raise _CheckpointWriteRefusal(
                "serialized checkpoint exceeds the derived byte bound",
                comparison_operands=comparison_operands,
            )
        receipt = {
            **manifest,
            "checkpoint_manifest_sha256": _sha256(manifest_path),
            "serialized_bytes": logical_serialized_bytes,
            "incremental_publication_bytes": incremental_publication_bytes,
        }
        (root / _STAGING_LEASE).unlink(missing_ok=True)
        if pre_publish_verifier is not None:
            quarantine = published_root.parent / ".checkpoint-quarantine"
            quarantine.mkdir(exist_ok=True)
            candidate = quarantine / f"candidate-{published_root.name}-{receipt['checkpoint_manifest_sha256'][:16]}"
            if candidate.exists():
                raise FileExistsError(f"quarantined checkpoint candidate already exists: {candidate}")
            _atomic_publish_no_replace(root, candidate)
            return admit_quarantined_checkpoint(
                candidate,
                published_root,
                verifier=pre_publish_verifier,
                max_serialized_bytes=max_serialized_bytes,
                expected_optimizer_contract=optimizer_contract,
                expected_optimizer_realization=optimizer_realization,
            )
        _atomic_publish_no_replace(root, published_root)
        return _bind_checkpoint_identity(published_root, receipt)
    except Exception as error:
        comparison_operands = _merge_failure_comparison_operands(
            comparison_operands,
            getattr(error, "comparison_operands", None),
        )
        evidence_error: Exception | None = None
        if root.exists():
            try:
                quarantine = published_root.parent / ".checkpoint-quarantine"
                quarantine.mkdir(parents=True, exist_ok=True)
                candidate = quarantine / f"candidate-write-failed-{root.name}-{uuid.uuid4().hex[:16]}"
                _atomic_publish_no_replace(root, candidate)
                _retain_write_failure_evidence(
                    published_root,
                    candidate,
                    error,
                    quarantine_candidate=candidate.name,
                    comparison_operands={
                        **comparison_operands,
                        "staged_shard_bytes": (
                            _staged_failure_inventory(candidate)
                            or comparison_operands["staged_shard_bytes"]
                        ),
                    },
                )
            except Exception as retention_error:
                evidence_error = retention_error
        if evidence_error is not None:
            raise RuntimeError(
                f"checkpoint write failed and bounded evidence retention also failed: {evidence_error}"
            ) from error
        raise

def write_checkpoint_artifacts(
    model: UnifiedDecoder,
    optimizer: torch.optim.Optimizer,
    root: Path,
    *,
    launch_seed: int,
    rng_state: Mapping[str, torch.Tensor],
    data_cursor: Mapping[str, Any],
    model_config_sha256: str,
    contract_sha256: str,
    expert_genesis_sha256: Mapping[str, str],
    optimizer_contract: Mapping[str, Any] | None = None,
    optimizer_state_layout: str = "legacy-v1",
    specialist_lineage: Mapping[str, Any] | None = None,
    cia_parent_checkpoint: Path | None = None,
    max_serialized_bytes: int | None = None,
    max_transient_scratch_bytes: int | None = None,
    host_commit_reserve_bytes: int | None = None,
    pre_publish_verifier: Callable[[Path, dict[str, Any]], Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    from ember.model.ember_v0_decoder import CIADecoder
    if type(model) is CIADecoder:
        if optimizer_contract is not None or specialist_lineage is not None or optimizer_state_layout != 'legacy-v1':
            raise ValueError('CIA checkpoint refuses v2 optimizer or specialist contracts')
        return _write_cia_checkpoint_artifacts(model,optimizer,root,launch_seed=launch_seed,
            rng_state=rng_state,data_cursor=data_cursor,model_config_sha256=model_config_sha256,
            contract_sha256=contract_sha256,expert_genesis_sha256=expert_genesis_sha256,
            max_serialized_bytes=max_serialized_bytes,max_transient_scratch_bytes=max_transient_scratch_bytes,
            host_commit_reserve_bytes=host_commit_reserve_bytes,pre_publish_verifier=pre_publish_verifier,
            cia_parent_checkpoint=cia_parent_checkpoint)
    if cia_parent_checkpoint is not None:
        raise ValueError('CIA parent checkpoint cannot supply v2 lineage')
    return _write_checkpoint_artifacts_impl(
        model,
        optimizer,
        root,
        launch_seed=launch_seed,
        rng_state=rng_state,
        data_cursor=data_cursor,
        model_config_sha256=model_config_sha256,
        contract_sha256=contract_sha256,
        expert_genesis_sha256=expert_genesis_sha256,
        optimizer_contract=optimizer_contract,
        optimizer_state_layout=optimizer_state_layout,
        specialist_lineage=specialist_lineage,
        max_serialized_bytes=max_serialized_bytes,
        max_transient_scratch_bytes=max_transient_scratch_bytes,
        host_commit_reserve_bytes=host_commit_reserve_bytes,
        pre_publish_verifier=pre_publish_verifier,
    )



def _validated_records(root: Path, receipt: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    manifest_path = root / "checkpoint-manifest.json"
    expected_manifest = _sha256_value(str(receipt.get("checkpoint_manifest_sha256", "")), name="checkpoint_manifest_sha256")
    if _sha256(manifest_path) != expected_manifest:
        raise ValueError("checkpoint manifest hash mismatch")
    records: dict[str, dict[str, Any]] = {}
    for item in receipt.get("shards", []):
        if not isinstance(item, dict):
            raise ValueError("checkpoint shard record is invalid")
        relative = item.get("path")
        if not isinstance(relative, str) or Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise ValueError("checkpoint shard path is not bundle-relative")
        if relative in records:
            raise ValueError("checkpoint contains duplicate shard paths")
        path = root / relative
        if _path_has_link(path, root):
            raise ValueError(f"checkpoint shard is a symlink or reparse point: {relative}")
        if not path.is_file():
            raise ValueError(f"checkpoint shard is missing: {relative}")
        expected_size = item.get("bytes")
        expected_hash = item.get("sha256")
        publication_mode = item.get("publication_mode")
        incremental_bytes = item.get("incremental_bytes")
        if not isinstance(expected_size, int) or expected_size <= 0 or not isinstance(expected_hash, str):
            raise ValueError(f"checkpoint shard record is invalid: {relative}")
        if (
            publication_mode is not None
            or incremental_bytes is not None
            or receipt.get("storage_projection") is not None
        ):
            if (
                publication_mode not in {"written", "hardlink", "copy"}
                or type(incremental_bytes) is not int
                or incremental_bytes
                != (0 if publication_mode == "hardlink" else expected_size)
            ):
                raise ValueError(
                    f"checkpoint shard publication record is invalid: {relative}"
                )
            if publication_mode == "hardlink" and path.stat().st_nlink < 2:
                raise ValueError(
                    f"checkpoint shard hardlink identity is not independently present: {relative}"
                )
        if path.stat().st_size != expected_size or _sha256(path) != expected_hash:
            if relative.startswith("expert-") and relative.endswith(".pt"):
                name = relative[len("expert-"):-len(".pt")]
                raise ValueError(f"checkpoint expert shard hash mismatch: {name}")
            raise ValueError(f"checkpoint shard hash mismatch: {relative}")
        records[relative] = item
    schema_version = receipt.get("schema_version")
    expected_paths = _checkpoint_shard_paths(
        schema_version=str(schema_version),
        optimizer_state_layout=receipt.get("optimizer_state_layout"),
        optimizer_state_owner_ids=receipt.get("optimizer_state_owner_ids"),
    )
    if set(records) != expected_paths:
        raise ValueError("checkpoint shard set is not closed for its schema version")
    return records


def _validate_model_state(expected: Mapping[str, torch.Tensor], actual: Any, *, label: str) -> dict[str, torch.Tensor]:
    if not isinstance(actual, dict) or set(actual) != set(expected):
        raise ValueError(f"{label} model state keys do not match this architecture")
    for key, tensor in actual.items():
        if not isinstance(tensor, torch.Tensor) or tuple(tensor.shape) != tuple(expected[key].shape):
            raise ValueError(f"{label} tensor shape does not match this architecture: {key}")
    return actual


def _prepare_owner_sharded_optimizer_state(
    model: UnifiedDecoder,
    optimizer: torch.optim.Optimizer,
    root: Path,
    receipt: Mapping[str, Any],
    records: Mapping[str, Mapping[str, Any]],
    optimizer_contract: Mapping[str, Any],
    optimizer_realization: Mapping[str, Any],
) -> dict[str, Any]:
    owner_ids = receipt.get("optimizer_state_owner_ids")
    owner_by_parameter = receipt.get("optimizer_state_owner_by_parameter")
    owner_hashes = receipt.get("optimizer_state_owner_shard_sha256")
    if (
        not isinstance(owner_ids, list)
        or not isinstance(owner_by_parameter, Mapping)
        or not isinstance(owner_hashes, Mapping)
        or owner_ids != [owner for owner in ["shared", *EXPERT_NAMES] if owner in owner_ids]
        or set(owner_ids) != set(owner_hashes)
        or set(owner_by_parameter.values()) - set(owner_ids)
    ):
        raise ValueError("checkpoint optimizer owner projection is not closed")
    _optimizer_state_shard_paths(owner_ids)
    parameter_names_by_id = {id(parameter): name for name, parameter in model.named_parameters()}
    parameter_names = set(parameter_names_by_id.values())
    if set(owner_by_parameter) - parameter_names:
        raise ValueError("checkpoint optimizer owner projection names an unknown parameter")
    payloads: dict[str, Mapping[str, Any]] = {}
    merged_state: dict[str, Any] = {}
    merged_owner_by_parameter: dict[str, str] = {}
    parameter_groups: list[Mapping[str, Any]] | None = None
    for owner in owner_ids:
        relative = f"optimizer-state-{owner}.pt"
        if relative not in records:
            raise ValueError(f"checkpoint optimizer owner shard is missing: {owner}")
        if owner_hashes.get(owner) != records[relative].get("sha256"):
            raise ValueError(f"checkpoint optimizer owner shard hash is not bound: {owner}")
        payload = torch.load(root / relative, map_location="cpu", weights_only=False)
        if (
            not isinstance(payload, Mapping)
            or set(payload) != {"schema_version", "owner", "state", "param_groups", "optimizer_contract", "optimizer_realization"}
            or payload.get("schema_version") != "ember-optimizer-owner-shard-v1"
            or payload.get("owner") != owner
            or payload.get("optimizer_contract") != dict(optimizer_contract)
            or payload.get("optimizer_realization") != dict(optimizer_realization)
            or not isinstance(payload.get("state"), Mapping)
            or not payload["state"]
            or not isinstance(payload.get("param_groups"), list)
        ):
            raise ValueError(f"checkpoint optimizer owner payload is malformed: {owner}")
        if parameter_groups is None:
            parameter_groups = payload["param_groups"]
        elif payload["param_groups"] != parameter_groups:
            raise ValueError("checkpoint optimizer owner payloads disagree on parameter groups")
        for name, state in payload["state"].items():
            if not isinstance(name, str) or name not in parameter_names:
                raise ValueError("checkpoint optimizer owner payload names an unknown parameter")
            if _optimizer_owner_for_parameter(name) != owner:
                raise ValueError("checkpoint optimizer owner payload violates parameter ownership")
            if name in merged_state:
                raise ValueError("checkpoint optimizer parameter appears in multiple owner shards")
            merged_state[name] = state
            merged_owner_by_parameter[name] = owner
        payloads[owner] = payload
    if dict(sorted(merged_owner_by_parameter.items())) != dict(sorted(owner_by_parameter.items())):
        raise ValueError("checkpoint optimizer owner projection does not match shard payloads")
    if parameter_groups is None:
        raise ValueError("checkpoint optimizer owner payloads have no parameter groups")

    current_state = optimizer.state_dict()
    parameter_ids_by_name: dict[str, int] = {}
    runtime_group_names: list[list[str]] = []
    if len(optimizer.param_groups) != len(current_state["param_groups"]):
        raise ValueError("checkpoint optimizer parameter-group count differs from runtime")
    for runtime_group, saved_group in zip(optimizer.param_groups, current_state["param_groups"]):
        group_names: list[str] = []
        for parameter, parameter_id in zip(runtime_group["params"], saved_group["params"]):
            name = parameter_names_by_id.get(id(parameter))
            if name is None or name in parameter_ids_by_name:
                raise ValueError("checkpoint optimizer runtime parameter identity is not closed")
            parameter_ids_by_name[name] = parameter_id
            group_names.append(name)
        runtime_group_names.append(group_names)
    if set(merged_state) - set(parameter_ids_by_name):
        raise ValueError("checkpoint optimizer state cannot bind runtime parameters")
    if len(parameter_groups) != len(current_state["param_groups"]):
        raise ValueError("checkpoint optimizer parameter-group count differs from runtime")
    loaded_groups = [dict(group) for group in current_state["param_groups"]]
    for index, descriptor in enumerate(parameter_groups):
        if not isinstance(descriptor, Mapping) or "param_names" not in descriptor:
            raise ValueError("checkpoint optimizer parameter-group descriptor is malformed")
        names = descriptor["param_names"]
        if (
            not isinstance(names, list)
            or len(names) != len(set(names))
            or any(name not in runtime_group_names[index] for name in names)
        ):
            raise ValueError("checkpoint optimizer parameter-group names are invalid")
        descriptor_keys = set(descriptor) - {"param_names"}
        runtime_keys = set(loaded_groups[index]) - {"params"}
        if descriptor_keys != runtime_keys:
            raise ValueError("checkpoint optimizer parameter-group fields are invalid")
        for key, value in descriptor.items():
            if key != "param_names":
                loaded_groups[index][key] = value
    return {
        "state": {
            parameter_ids_by_name[name]: state
            for name, state in merged_state.items()
        },
        "param_groups": loaded_groups,
    }


def load_checkpoint_artifacts(
    model: UnifiedDecoder,
    optimizer: torch.optim.Optimizer,
    root: Path,
    receipt: Mapping[str, Any],
    *, max_transient_scratch_bytes: int | None = None,
    host_commit_reserve_bytes: int | None = None,
) -> dict[str, Any] | None:
    """Verify every manifest/shard/payload before mutating model or optimizer."""

    root = _admitted_checkpoint_root(root)
    if receipt.get('schema_version') == 'ember-cia-checkpoint-v1':
        return _load_cia_checkpoint_artifacts(model,optimizer,root,receipt,
            max_transient_scratch_bytes=max_transient_scratch_bytes,host_commit_reserve_bytes=host_commit_reserve_bytes)
    schema_version = receipt.get("schema_version")
    if schema_version not in {
        "ember-sparse-checkpoint-v3",
        "ember-sparse-checkpoint-v4",
        "ember-sparse-checkpoint-v5",
    }:
        raise ValueError("checkpoint optimizer contract requires a v3, v4, or v5 manifest")
    optimizer_contract = _validate_optimizer_contract(receipt.get("optimizer_contract", {}))
    optimizer_realization = _validate_optimizer_realization(optimizer_contract, receipt.get("optimizer_realization"))
    if optimizer is not None:
        _validate_runtime_optimizer_realization(optimizer, optimizer_contract, optimizer_realization)
    expected = receipt.get("expert_checkpoint_sha256")
    genesis = receipt.get("expert_genesis_sha256")
    active = receipt.get("active_expert_ids")
    if not isinstance(expected, dict) or set(expected) != set(EXPERT_NAMES):
        raise ValueError("checkpoint receipt lacks the four expert hashes")
    if not isinstance(genesis, dict) or set(genesis) != set(EXPERT_NAMES):
        raise ValueError("checkpoint receipt lacks the four expert genesis hashes")
    if not isinstance(active, list) or len(active) != 1 or active[0] not in {*EXPERT_NAMES, "shared"}:
        raise ValueError("checkpoint receipt lacks exactly one declared active expert")
    records = _validated_records(root, receipt)
    if schema_version == "ember-sparse-checkpoint-v5":
        if receipt.get("shared_model_shard_sha256") != records["shared-model.pt"]["sha256"]:
            raise ValueError("v5 checkpoint does not bind its shared model shard")
        if receipt.get("optimizer_state_layout") == _OWNER_SHARDED_OPTIMIZER_STATE_LAYOUT:
            if not isinstance(receipt.get("optimizer_state_owner_ids"), list):
                raise ValueError("v5 checkpoint does not bind owner-sharded optimizer state")
        elif receipt.get("optimizer_state_shard_sha256") != records["optimizer-state.pt"]["sha256"]:
            raise ValueError("v5 checkpoint does not bind its optimizer shard")
    elif (
        receipt.get("shared_optimizer_shard_sha256")
        != records["shared.pt"]["sha256"]
    ):
        raise ValueError("legacy checkpoint does not bind its shared optimizer shard")

    owner_sharded = (
        schema_version == "ember-sparse-checkpoint-v5"
        and receipt.get("optimizer_state_layout") == _OWNER_SHARDED_OPTIMIZER_STATE_LAYOUT
    )
    if owner_sharded:
        try:
            owner_storage_authority = _validate_owner_sharded_optimizer_payloads(
                root,
                receipt,
                records,
                expected_optimizer_contract=optimizer_contract,
                expected_optimizer_realization=optimizer_realization,
                expected_parameter_names=set(dict(model.named_parameters())),
            )
            if receipt.get("storage_projection") is not None:
                _validate_owner_storage_projection_authority(
                    receipt, owner_storage_authority
                )
        except ValueError:
            raise
        except Exception as error:
            raise ValueError("checkpoint optimizer owner payload cannot be read") from error

    identity = receipt.get("checkpoint")
    if not isinstance(identity, dict) or not isinstance(identity.get("byte_sha256"), str):
        raise CheckpointIdentityMismatch(
            "checkpoint receipt is missing a cond3 identity manifest binding "
            "(checkpoint.byte_sha256) -- refusing to load"
        )
    identity_manifest_path = root / "checkpoint-manifest.json"
    actual_identity_byte_sha256 = _sha256(identity_manifest_path)
    if actual_identity_byte_sha256 != identity["byte_sha256"]:
        raise CheckpointIdentityMismatch(
            f"checkpoint identity mismatch: on-disk checkpoint-manifest.json bytes hash "
            f"to {actual_identity_byte_sha256!r} but the recorded checkpoint.byte_sha256 "
            f"is {identity['byte_sha256']!r}"
        )

    payloads: dict[str, Any] = {}
    for relative in records:
        if relative.startswith("optimizer-state-"):
            continue
        payloads[relative] = torch.load(root / relative, map_location="cpu", weights_only=False)
    replay_payload = payloads["replay-state.pt"]
    if (not isinstance(replay_payload, dict) or not isinstance(replay_payload.get("rng_state"), dict) or set(replay_payload["rng_state"]) != {"cpu", "cuda"} or replay_payload.get("data_cursor") != receipt.get("data_cursor")):
        raise ValueError("checkpoint replay state is incomplete or cursor-mismatched")
    for name, state in replay_payload["rng_state"].items():
        if not isinstance(state, torch.Tensor) or state.dtype != torch.uint8 or state.ndim != 1:
            raise ValueError(f"checkpoint replay RNG state is invalid: {name}")
    if owner_sharded:
        shared_payload = payloads["shared-model.pt"]
        optimizer_payload = None
    elif schema_version == "ember-sparse-checkpoint-v5":
        shared_payload = payloads["shared-model.pt"]
        optimizer_payload = payloads["optimizer-state.pt"]
    else:
        shared_payload = payloads["shared.pt"]
        optimizer_payload = shared_payload
    if (
        not isinstance(shared_payload, dict)
        or (
            not owner_sharded
            and (
                not isinstance(optimizer_payload, dict)
                or not isinstance(optimizer_payload.get("optimizer"), dict)
            )
        )
    ):
        raise ValueError("checkpoint does not contain split model and optimizer state")
    if not owner_sharded and (
        optimizer_payload.get("optimizer_contract") != optimizer_contract
        or optimizer_payload.get("optimizer_realization") != optimizer_realization
    ):
        raise ValueError("checkpoint optimizer realization does not match manifest")
    expected_state = model.state_dict()
    shared_expected = {key: value for key, value in expected_state.items() if ".experts." not in key}
    shared_state = _validate_model_state(shared_expected, shared_payload.get("model"), label="shared")
    expert_states: dict[str, dict[str, torch.Tensor]] = {}
    for name in EXPERT_NAMES:
        relative = f"expert-{name}.pt"
        payload = payloads[relative]
        if not isinstance(payload, dict) or payload.get("expert") != name:
            raise ValueError(f"checkpoint expert payload does not identify {name}")
        if records[relative]["sha256"] != expected[name]:
            raise ValueError(f"checkpoint expert receipt does not bind {name}")
        expert_expected = {
            key: value for key, value in expected_state.items() if f".experts.{name}." in key
        }
        expert_states[name] = _validate_model_state(expert_expected, payload.get("model"), label=f"expert {name}")

    prepared_optimizer_state: dict[str, Any] | None = None
    if optimizer is not None and owner_sharded:
        prepared_optimizer_state = _prepare_owner_sharded_optimizer_state(
            model,
            optimizer,
            root,
            receipt,
            records,
            optimizer_contract,
            optimizer_realization,
        )

    model.load_state_dict(shared_state, strict=False)
    for state in expert_states.values():
        model.load_state_dict(state, strict=False)
    if optimizer is not None:
        if owner_sharded:
            assert prepared_optimizer_state is not None
            optimizer.load_state_dict(prepared_optimizer_state)
        else:
            optimizer.load_state_dict(optimizer_payload["optimizer"])
    model._activate_expert(active[0])
    torch.set_rng_state(replay_payload["rng_state"]["cpu"])
    if torch.cuda.is_available():
            torch.cuda.set_rng_state(replay_payload["rng_state"]["cuda"])
    return {"data_cursor": dict(replay_payload["data_cursor"])}


def load_checkpoint_model_only_transition(
    model: UnifiedDecoder,
    root: Path,
    receipt: Mapping[str, Any],
) -> dict[str, Any]:
    """Stream a verified historical checkpoint without reusing optimizer state.

    Historical v3/v4 shared shards physically contain model and optimizer
    state.  V5 stores those payloads separately, so this path verifies the
    optimizer authority from the manifest but never opens the optimizer shard.
    Expert shards are loaded and released one at a time so host demand is
    bounded by the largest single model shard rather than the whole bundle.
    """

    root = _admitted_checkpoint_root(root)
    schema_version = receipt.get("schema_version")
    if schema_version not in {
        "ember-sparse-checkpoint-v3",
        "ember-sparse-checkpoint-v4",
        "ember-sparse-checkpoint-v5",
    }:
        raise ValueError("model-only optimizer transition requires a v3, v4, or v5 source checkpoint")
    optimizer_contract = _validate_optimizer_contract(receipt.get("optimizer_contract", {}))
    expected_optimizer = {
        "name": "paged_8bit_adamw",
        "implementation": "bitsandbytes.optim.PagedAdamW8bit",
        "state_format": "bitsandbytes-paged-8bit-adamw-state-dict-v1",
    }
    if any(optimizer_contract.get(field) != value for field, value in expected_optimizer.items()):
        raise ValueError("model-only transition source optimizer is not canonical paged AdamW8bit")
    optimizer_realization = _validate_optimizer_realization(optimizer_contract, receipt.get("optimizer_realization"))
    expected = receipt.get("expert_checkpoint_sha256")
    genesis = receipt.get("expert_genesis_sha256")
    active = receipt.get("active_expert_ids")
    if not isinstance(expected, dict) or set(expected) != set(EXPERT_NAMES):
        raise ValueError("checkpoint receipt lacks the four expert hashes")
    if not isinstance(genesis, dict) or set(genesis) != set(EXPERT_NAMES):
        raise ValueError("checkpoint receipt lacks the four expert genesis hashes")
    if not isinstance(active, list) or len(active) != 1 or active[0] not in {*EXPERT_NAMES, "shared"}:
        raise ValueError("checkpoint receipt lacks exactly one declared active expert")
    records = _validated_records(root, receipt)
    if (
        schema_version == "ember-sparse-checkpoint-v5"
        and receipt.get("optimizer_state_layout") == _OWNER_SHARDED_OPTIMIZER_STATE_LAYOUT
    ):
        owner_storage_authority = _validate_owner_sharded_optimizer_payloads(
            root,
            receipt,
            records,
            expected_parameter_names=set(dict(model.named_parameters())),
        )
        if receipt.get("storage_projection") is not None:
            _validate_owner_storage_projection_authority(
                receipt, owner_storage_authority
            )
    expected_state = model.state_dict()

    replay_payload = torch.load(root / "replay-state.pt", map_location="cpu", weights_only=False, mmap=True)
    if (not isinstance(replay_payload, dict) or not isinstance(replay_payload.get("rng_state"), dict) or set(replay_payload["rng_state"]) != {"cpu", "cuda"} or replay_payload.get("data_cursor") != receipt.get("data_cursor")):
        raise ValueError("checkpoint replay state is incomplete or cursor-mismatched")
    for name, state in replay_payload["rng_state"].items():
        if not isinstance(state, torch.Tensor) or state.dtype != torch.uint8 or state.ndim != 1:
            raise ValueError(f"checkpoint replay RNG state is invalid: {name}")

    shared_name = "shared-model.pt" if schema_version == "ember-sparse-checkpoint-v5" else "shared.pt"
    shared_payload = torch.load(root / shared_name, map_location="cpu", weights_only=False, mmap=True)
    if not isinstance(shared_payload, dict):
        raise ValueError("shared checkpoint payload is invalid")
    if schema_version != "ember-sparse-checkpoint-v5":
        if not isinstance(shared_payload.get("optimizer"), dict):
            raise ValueError("shared checkpoint does not contain optimizer state")
        if shared_payload.get("optimizer_contract") != optimizer_contract or shared_payload.get("optimizer_realization") != optimizer_realization:
            raise ValueError("shared checkpoint optimizer realization does not match manifest")
    shared_expected = {key: value for key, value in expected_state.items() if ".experts." not in key}
    shared_state = _validate_model_state(shared_expected, shared_payload.get("model"), label="shared")
    model.load_state_dict(shared_state, strict=False)
    del shared_state
    del shared_payload

    for name in EXPERT_NAMES:
        relative = f"expert-{name}.pt"
        payload = torch.load(root / relative, map_location="cpu", weights_only=False, mmap=True)
        if not isinstance(payload, dict) or payload.get("expert") != name:
            raise ValueError(f"checkpoint expert payload does not identify {name}")
        if records[relative]["sha256"] != expected[name]:
            raise ValueError(f"checkpoint expert receipt does not bind {name}")
        expert_expected = {key: value for key, value in expected_state.items() if f".experts.{name}." in key}
        expert_state = _validate_model_state(expert_expected, payload.get("model"), label=f"expert {name}")
        model.load_state_dict(expert_state, strict=False)
        del expert_state
        del payload

    model._activate_expert(active[0])
    torch.set_rng_state(replay_payload["rng_state"]["cpu"])
    if torch.cuda.is_available():
        torch.cuda.set_rng_state(replay_payload["rng_state"]["cuda"])
    return {"data_cursor": dict(replay_payload["data_cursor"])}


def read_cia_expert_object(index_path, *, expected_index_sha256, expert_id):
    """Read one exact CIA object from a caller-pinned generation index.

    This is checkpoint deserialization, not generation admission or model mutation.
    The activation owner must separately verify the complete generation and retain
    its request lease. No integer-only object lookup or mutable slot identity exists.
    """
    import io
    from ember.model.ember_v0_inventory import equation_inventory

    if type(expert_id) is not int or not 0 <= expert_id < 25:
        raise ValueError("CIA expert identity must be an integer in [0,25)")
    expected_index_sha256 = _sha256_value(expected_index_sha256, name="expected_index_sha256")
    index_path = Path(index_path)
    root = index_path.parent
    if _path_has_link(index_path, root):
        raise ValueError("CIA index is a symlink or reparse point")
    with index_path.open("rb") as handle:
        index_bytes = handle.read(65537)
    if len(index_bytes) > 65536 or hashlib.sha256(index_bytes).hexdigest() != expected_index_sha256:
        raise ValueError("CIA generation index digest mismatch or size bound exceeded")
    index = json.loads(index_bytes)
    if (type(index) is not dict or set(index) != {"schema_version", "candidate_revision", "experts"}
        or index["schema_version"] != "ember-cia-expert-index-v1"
        or index["candidate_revision"] != "CIA3-R1-N61"
        or type(index["experts"]) is not list or len(index["experts"]) != 25):
        raise ValueError("CIA expert index must use the closed 25-expert schema")
    seen = set()
    for identity, record in enumerate(index["experts"]):
        if (type(record) is not dict or set(record) != {"expert_id", "sha256", "bytes"}
            or type(record["expert_id"]) is not int or record["expert_id"] != identity
            or type(record["bytes"]) is not int or not 1 <= record["bytes"] <= 113246208 * 2 + 4194304):
            raise ValueError("CIA expert index record is invalid")
        object_digest = _sha256_value(record["sha256"], name="expert object digest")
        if object_digest in seen:
            raise ValueError("CIA expert object identity reused across global experts")
        seen.add(object_digest)
    record = index["experts"][expert_id]
    path = root / "objects" / (record["sha256"] + ".pt")
    if _path_has_link(path, root):
        raise ValueError("CIA expert object is a symlink or reparse point")
    # Deserialize the same bounded byte snapshot that was hashed, even if the
    # pathname is changed concurrently. No check-then-reopen loading path.
    with path.open("rb") as handle:
        snapshot = handle.read(record["bytes"] + 1)
    if len(snapshot) != record["bytes"] or hashlib.sha256(snapshot).hexdigest() != record["sha256"]:
        raise ValueError("CIA expert object digest or size mismatch")
    payload = torch.load(io.BytesIO(snapshot), map_location="cpu", weights_only=True)
    return _validate_cia_expert_payload(payload, expert_id=expert_id)


def _validate_cia_expert_payload(payload, *, expert_id):
    from ember.model.ember_v0_inventory import equation_inventory
    if type(expert_id) is not int or not 0 <= expert_id < 25:
        raise ValueError("CIA expert identity must be an integer in [0,25)" )
    if (type(payload) is not dict or set(payload) != {"schema_version", "candidate_revision", "expert_id", "model"}
        or payload["schema_version"] != "ember-cia-expert-object-v1"
        or payload["candidate_revision"] != "CIA3-R1-N61"
        or type(payload["expert_id"]) is not int or payload["expert_id"] != expert_id):
        raise ValueError("CIA expert payload identity mismatch")
    expected = {spec.name: spec.shape for spec in equation_inventory() if spec.expert == expert_id}
    return _validate_cia_tensor_inventory(payload["model"], expected, label="expert")


def _validate_cia_tensor_inventory(tensors, expected, *, label):
    if type(tensors) is not dict or set(tensors) != set(expected):
        raise ValueError(f"CIA {label} tensor inventory mismatch")
    addresses = set()
    ranges = []
    for name, shape in expected.items():
        tensor = tensors[name]
        if (type(tensor) is not torch.Tensor or tuple(tensor.shape) != shape
            or tensor.dtype != torch.bfloat16 or tensor.device.type != "cpu"
            or not tensor.is_contiguous() or tensor.storage_offset() != 0
            or tensor.untyped_storage().nbytes() != tensor.numel() * tensor.element_size()
            or not torch.isfinite(tensor).all()):
            raise ValueError(f"CIA {label} tensor mismatch: {name}")
        address = tensor.untyped_storage().data_ptr()
        if address in addresses:
            raise ValueError(f"CIA {label} tensor storage alias")
        addresses.add(address)
        ranges.append((address, address + tensor.untyped_storage().nbytes()))
    ranges.sort()
    if any(left[1] > right[0] for left, right in zip(ranges, ranges[1:])):
        raise ValueError(f"CIA {label} tensor storage alias")
    return tensors

def write_cia_expert_object(candidate, *, expert_id, tensors, max_serialized_bytes):
    """Create one immutable expert object inside the existing writer quarantine.

    This does not publish/admit a checkpoint generation. The existing complete
    checkpoint transaction owns the lease, index and eventual bundle admission.
    """
    import io
    from durable_io import atomic_create_durable

    candidate = _require_cia_writer_candidate(candidate)
    if type(max_serialized_bytes) is not int or not 1 <= max_serialized_bytes <= 113246208 * 2 + 4194304:
        raise ValueError("CIA object requires an explicit bounded serialized-byte allowance")
    payload = {"schema_version": "ember-cia-expert-object-v1", "candidate_revision": "CIA3-R1-N61",
               "expert_id": expert_id, "model": tensors}
    _validate_cia_expert_payload(payload, expert_id=expert_id)
    buffer = io.BytesIO()
    torch.save(payload, _ScratchCappedWriter(buffer, max_serialized_bytes))
    snapshot = buffer.getvalue()
    digest = hashlib.sha256(snapshot).hexdigest()
    objects = candidate / "objects"
    objects.mkdir(exist_ok=True)
    if _path_has_link(objects, candidate):
        raise ValueError("CIA object directory is a symlink or reparse point")
    # Existing durable no-replace primitive; a collision never overwrites bytes.
    atomic_create_durable(objects / (digest + ".pt"), snapshot)
    return {"expert_id": expert_id, "sha256": digest, "bytes": len(snapshot)}


def _require_cia_writer_candidate(candidate):
    candidate = Path(candidate)
    if candidate.name.startswith("candidate-") is False or candidate.parent.name != ".checkpoint-quarantine":
        raise ValueError("CIA objects require the checkpoint candidate quarantine")
    if _path_has_link(candidate, candidate.parent):
        raise ValueError("CIA candidate is a symlink or reparse point")
    lease_path = candidate / _STAGING_LEASE
    if _path_has_link(lease_path, candidate):
        raise ValueError("CIA writer lease is a symlink or reparse point")
    lease = json.loads(lease_path.read_bytes())
    if type(lease) is not dict or type(lease.get("pid")) is not int or lease["pid"] != os.getpid():
        raise ValueError("CIA candidate requires this process's writer lease")
    return candidate

def write_cia_expert_index(candidate, *, records, max_total_object_bytes):
    """Verify all 25 expert objects before creating an immutable candidate index.

    An index is not a complete checkpoint: core, optimizer, replay state and
    qualification remain required by the existing bundle admission transaction.
    """
    from durable_io import atomic_create_durable
    candidate = _require_cia_writer_candidate(candidate)
    if type(max_total_object_bytes) is not int or max_total_object_bytes < 1:
        raise ValueError("CIA index requires an explicit aggregate object-byte allowance")
    if type(records) is not list or len(records) != 25:
        raise ValueError("CIA index requires exactly 25 expert object records")
    # Materialize plain JSON before validation; later caller mutations do not
    # change the records that were checked or the index ultimately published.
    snapshot = json.dumps({"schema_version": "ember-cia-expert-index-v1",
                           "candidate_revision": "CIA3-R1-N61", "experts": records},
                          sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    if len(snapshot) > 65536:
        raise ValueError("CIA index exceeds its byte allowance")
    frozen = json.loads(snapshot)
    sizes = [record.get("bytes") if type(record) is dict else None for record in frozen["experts"]]
    if any(type(size) is not int or size < 1 for size in sizes) or sum(sizes) > max_total_object_bytes:
        raise ValueError("CIA index exceeds its aggregate object-byte allowance")
    digest = hashlib.sha256(snapshot).hexdigest()
    draft = _write_atomic(candidate, ".cia-index-" + uuid.uuid4().hex + ".json",
                          lambda handle: handle.write(snapshot), max_transient_scratch_bytes=65536)
    try:
        for expert in range(25):
            # Load, validate and release one full expert at a time; never retain
            # all deserialized object tensors alongside the live population.
            tensors = read_cia_expert_object(draft, expected_index_sha256=digest, expert_id=expert)
            del tensors
        _require_cia_writer_candidate(candidate)
        target = candidate / ("expert-index-" + digest + ".json")
        atomic_create_durable(target, snapshot)
    finally:
        draft.unlink(missing_ok=True)
    return {"path": target.name, "sha256": digest, "bytes": len(snapshot), "expert_object_bytes": sum(sizes)}


def _validate_cia_core_payload(payload, *, architecture_sha256):
    from ember.model.ember_v0_inventory import equation_inventory
    if (type(payload) is not dict or set(payload) != {"schema_version", "architecture_sha256", "model"}
        or payload["schema_version"] != "ember-cia-core-object-v1"
        or payload["architecture_sha256"] != architecture_sha256):
        raise ValueError("CIA core payload identity mismatch")
    expected = {spec.name: spec.shape for spec in equation_inventory() if spec.expert is None}
    return _validate_cia_tensor_inventory(payload["model"], expected, label="core")


def write_cia_core_object(candidate, *, tensors, architecture_config, max_serialized_bytes):
    """Snapshot shared core/router/adapters inside existing checkpoint quarantine.

    This component cannot substitute for optimizer/RNG/cursor, the full expert
    index or the complete checkpoint's existing admission transaction.
    """
    import io
    from durable_io import atomic_create_durable
    from ember.model.ember_v0_contract import cia_architecture_sha256
    candidate = _require_cia_writer_candidate(candidate)
    if type(max_serialized_bytes) is not int or not 1 <= max_serialized_bytes <= 251383808 * 2 + 4194304:
        raise ValueError("CIA core requires an explicit bounded serialized-byte allowance")
    architecture_sha256 = cia_architecture_sha256(architecture_config)
    payload = {"schema_version": "ember-cia-core-object-v1",
               "architecture_sha256": architecture_sha256, "model": tensors}
    _validate_cia_core_payload(payload, architecture_sha256=architecture_sha256)
    buffer = io.BytesIO()
    torch.save(payload, _ScratchCappedWriter(buffer, max_serialized_bytes))
    snapshot = buffer.getvalue()
    digest = hashlib.sha256(snapshot).hexdigest()
    objects = candidate / "objects"
    objects.mkdir(exist_ok=True)
    if _path_has_link(objects, candidate):
        raise ValueError("CIA core object directory is a symlink or reparse point")
    atomic_create_durable(objects / (digest + ".pt"), snapshot)
    return {"sha256": digest, "bytes": len(snapshot), "architecture_sha256": architecture_sha256}


def read_cia_core_object(root, *, record, architecture_config):
    """Read a caller-pinned core component; no model mutation or admission.

    The caller must obtain this record from its verified complete checkpoint.
    Hash and deserialize one bounded snapshot, never reopen a checked pathname.
    """
    import io
    from ember.model.ember_v0_contract import cia_architecture_sha256
    architecture_sha256 = cia_architecture_sha256(architecture_config)
    if type(record) is not dict or set(record) != {"sha256", "bytes", "architecture_sha256"}:
        raise ValueError("CIA core record requires the closed component schema")
    record = dict(record)
    digest = _sha256_value(record["sha256"], name="core object digest")
    if record["architecture_sha256"] != architecture_sha256:
        raise ValueError("CIA core architecture identity mismatch")
    if type(record["bytes"]) is not int or not 1 <= record["bytes"] <= 251383808 * 2 + 4194304:
        raise ValueError("CIA core object byte bound invalid")
    root = Path(root)
    path = root / "objects" / (digest + ".pt")
    if _path_has_link(path, root):
        raise ValueError("CIA core object is a symlink or reparse point")
    with path.open("rb") as handle:
        snapshot = handle.read(record["bytes"] + 1)
    if len(snapshot) != record["bytes"] or hashlib.sha256(snapshot).hexdigest() != digest:
        raise ValueError("CIA core object digest or size mismatch")
    payload = torch.load(io.BytesIO(snapshot), map_location="cpu", weights_only=True)
    return _validate_cia_core_payload(payload, architecture_sha256=architecture_sha256)


def cia_optimizer_identity(model, optimizer) -> dict[str, Any]:
    """Bind the native CPU conformance optimizer; not production qualification.

    Parameter objects are mapped to the complete CIA inventory, not transient
    optimizer integer IDs. Every group's ordered membership and effective
    settings participate. Other realizations require their own strict versioned
    adapter; this does not weaken the legacy checkpoint optimizer contract.
    """
    import math
    from torch.optim import adam, adamw, optimizer as optimizer_module, _functional
    import marshal
    from ember.model.ember_v0_decoder import CIADecoder
    from ember.model.ember_v0_contract import cia_architecture_config, cia_architecture_sha256, validate_cia_architecture

    if type(model) is not CIADecoder:
        raise ValueError("CIA optimizer identity requires the exact CIA decoder revision")
    architecture_config = cia_architecture_config()
    if model.config != validate_cia_architecture(architecture_config):
        raise ValueError("CIA optimizer identity refuses a changed runtime revision")
    if type(optimizer) is not torch.optim.AdamW:
        raise ValueError("CIA optimizer identity currently supports native AdamW only")
    for name in ('step', 'state_dict', 'load_state_dict', 'add_param_group', 'zero_grad'):
        if name in vars(optimizer):
            raise ValueError("CIA optimizer identity refuses an instance method override")
    if any(value for name, value in vars(optimizer).items() if name.endswith('_hooks')):
        raise ValueError("CIA optimizer identity refuses runtime hooks")
    dependency_candidates = {module.__name__: module for module in (adam, adamw, optimizer_module, _functional)}
    if (optimizer_module._global_optimizer_pre_hooks
            or optimizer_module._global_optimizer_post_hooks):
        raise ValueError("CIA optimizer identity refuses global runtime hooks")
    parameters = model.parameter_inventory()
    names_by_id = {id(parameter): name for name, parameter in parameters.items()}

    def normalized(value):
        if value is None or type(value) in (bool, str, int):
            return value
        if type(value) is float:
            if not math.isfinite(value):
                raise ValueError("CIA optimizer hyperparameter must be finite")
            return value
        if type(value) in (tuple, list):
            return [normalized(item) for item in value]
        raise ValueError("unsupported CIA optimizer hyperparameter type")

    groups = []
    seen = set()
    for group in optimizer.param_groups:
        members = []
        for parameter in group['params']:
            identity = id(parameter)
            if identity not in names_by_id or identity in seen:
                raise ValueError("CIA optimizer membership is foreign or duplicated")
            seen.add(identity)
            members.append(names_by_id[identity])
        if not members:
            raise ValueError("CIA optimizer membership contains an empty group")
        if any(type(key) is not str for key in group):
            raise ValueError("CIA optimizer hyperparameter keys must be strings")
        groups.append({'params': members,
                       'hyperparameters': {key: normalized(value) for key, value in group.items()
                                           if key != 'params'}})
    if seen != set(names_by_id):
        raise ValueError("CIA optimizer membership does not cover the complete inventory")
    if any(id(parameter) not in seen for parameter in optimizer.state):
        raise ValueError("CIA optimizer state membership is foreign")
    source = inspect.getsourcefile(type(optimizer))
    if source is None or not Path(source).is_file():
        raise ValueError("CIA optimizer implementation source cannot be content-addressed")
    # Include inherited/decorated and functional implementations, not only the
    # AdamW class's source file. Runtime code hashes also distinguish monkeypatches.
    implementation_dependencies = {}
    optimizer_classes = tuple(cls for cls in type(optimizer).__mro__
                              if cls.__module__.startswith('torch.optim.'))
    dependency_modules = {'torch.optim._functional',
                          *(cls.__module__ for cls in optimizer_classes)}
    effective_step = inspect.unwrap(type(optimizer).step)
    dependency_modules.add(effective_step.__module__)
    for module_name in sorted(dependency_modules):
        if module_name not in dependency_candidates:
            raise ValueError('CIA optimizer has an unsupported implementation dependency')
        module = dependency_candidates[module_name]
        module_source = inspect.getsourcefile(module)
        if module_source is None or not Path(module_source).is_file():
            raise ValueError("CIA optimizer dependency source is unavailable")
        functions = {name: value for name, value in vars(module).items()
                     if inspect.isfunction(value)}
        for cls in optimizer_classes:
            if cls.__module__ == module_name:
                functions.update({f'{cls.__name__}.{name}': value
                                  for name, value in vars(cls).items() if inspect.isfunction(value)})
        code_hashes = {}
        for name, function in sorted(functions.items()):
            chain = []
            visited = set()
            while inspect.isfunction(function):
                if id(function) in visited:
                    raise ValueError("CIA optimizer implementation wrapper cycle")
                visited.add(id(function))
                chain.append(hashlib.sha256(marshal.dumps(function.__code__)).hexdigest())
                function = getattr(function, '__wrapped__', None)
            code_hashes[name] = chain
        implementation_dependencies[module_name] = {
            'source_sha256': _sha256(Path(module_source)), 'runtime_code_sha256': code_hashes}
    return {
        'schema_version': 'ember-cia-optimizer-identity-v1',
        'architecture_sha256': cia_architecture_sha256(architecture_config),
        'implementation': f'{type(optimizer).__module__}.{type(optimizer).__qualname__}',
        'implementation_source_sha256': _sha256(Path(source)),
        'torch_version': str(torch.__version__),
        'implementation_dependencies': implementation_dependencies,
        'defaults': {key: normalized(value) for key, value in optimizer.defaults.items()},
        'parameter_elements': sum(parameter.numel() for parameter in parameters.values()),
        'param_groups': groups,
    }


def _cia_validate_named_optimizer_state(model, optimizer, state, *, max_state_bytes):
    """Validate all named native BF16 CPU moments before creating a snapshot."""
    if type(max_state_bytes) is not int or max_state_bytes <= 0:
        raise ValueError('CIA optimizer state byte cap must be a positive integer')
    if type(state) is not dict:
        raise ValueError('CIA optimizer named state must be a dictionary')
    parameters = model.parameter_inventory()
    names = {id(parameter): name for name, parameter in parameters.items()}
    groups = {names[id(parameter)]: group for group in optimizer.param_groups
              for parameter in group['params']}
    if any(group.get('capturable') or group.get('fused') or group.get('differentiable')
           for group in optimizer.param_groups) or optimizer.defaults.get('differentiable'):
        raise ValueError('CIA native CPU state does not support this optimizer execution mode')
    _cia_validate_optimizer_fields(parameters, groups, state, max_state_bytes=max_state_bytes)


def _cia_validate_optimizer_fields(parameters, groups, state, *, max_state_bytes):
    if type(state) is not dict:
        raise ValueError('CIA optimizer named state must be a dictionary')
    total_bytes = 0
    storage_ranges = []
    for name, fields in state.items():
        if name not in parameters or type(fields) is not dict:
            raise ValueError('CIA optimizer state names an unknown parameter or invalid fields')
        if not fields:
            continue  # Preserve explicitly present but uninitialized lazy state.
        expected = {'step', 'exp_avg', 'exp_avg_sq'}
        if groups[name]['amsgrad']:
            expected.add('max_exp_avg_sq')
        if set(fields) != expected:
            raise ValueError('CIA optimizer state fields do not match native AdamW')
        for key, tensor in fields.items():
            shape = () if key == 'step' else tuple(parameters[name].shape)
            dtype = torch.float32 if key == 'step' else torch.bfloat16
            if (type(tensor) is not torch.Tensor or tuple(tensor.shape) != shape
                    or tensor.dtype != dtype or tensor.device.type != 'cpu'
                    or tensor.requires_grad or not tensor.is_contiguous()
                    or tensor.storage_offset() != 0
                    or tensor.untyped_storage().nbytes() != tensor.numel() * tensor.element_size()):
                raise ValueError('CIA optimizer tensor layout or dtype is invalid')
            total_bytes += tensor.numel() * tensor.element_size()
            if total_bytes > max_state_bytes:
                raise ValueError('CIA optimizer state exceeds its byte cap')
            pointer = tensor.untyped_storage().data_ptr()
            storage_ranges.append((pointer, pointer + tensor.untyped_storage().nbytes()))
            if not torch.isfinite(tensor).all().item():
                raise ValueError('CIA optimizer state must be finite')
            if key == 'step':
                value = tensor.item()
                if value < 0 or value != int(value) or value > 2**24:
                    raise ValueError('CIA optimizer step is not an exact bounded clock')
            elif key in ('exp_avg_sq', 'max_exp_avg_sq') and (tensor < 0).any().item():
                raise ValueError('CIA optimizer second moment cannot be negative')
        if groups[name]['amsgrad'] and (fields['max_exp_avg_sq'] < fields['exp_avg_sq']).any().item():
            raise ValueError('CIA optimizer AMSGrad maximum is below its current second moment')
    storage_ranges.sort()
    if any(left[1] > right[0] for left, right in zip(storage_ranges, storage_ranges[1:])):
        raise ValueError('CIA optimizer state has overlapping tensor storage')


def _cia_named_optimizer_state(model, optimizer, state, *, max_state_bytes):
    _cia_validate_named_optimizer_state(model, optimizer, state, max_state_bytes=max_state_bytes)
    return {name: {key: tensor.detach().clone() for key, tensor in fields.items()}
            for name, fields in state.items()}


def capture_cia_optimizer_state(model, optimizer, *, max_state_bytes):
    """Snapshot a quiescent optimizer; checkpoint owner must exclude concurrent steps.

    Native BF16 moments and FP32 scalar clocks only, without master weights.
    This payload is not standalone checkpoint admission or a selected production
    optimizer. Complete model, replay, lineage and custody bindings remain required.
    """
    identity = cia_optimizer_identity(model, optimizer)
    names = {id(parameter): name for name, parameter in model.parameter_inventory().items()}
    state = {names[id(parameter)]: fields for parameter, fields in optimizer.state.items()}
    snapshot = _cia_named_optimizer_state(model, optimizer, state, max_state_bytes=max_state_bytes)
    if cia_optimizer_identity(model, optimizer) != identity:
        raise ValueError('CIA optimizer identity changed during capture')
    return {'schema_version': 'ember-cia-native-optimizer-state-v1',
            'identity': identity, 'master_weights': None, 'state': snapshot}


def prepare_cia_optimizer_state(model, optimizer, payload, *, max_state_bytes):
    """Prepare native load_state_dict input after full validation; mutate nothing."""
    import copy
    identity = cia_optimizer_identity(model, optimizer)
    if (type(payload) is not dict or set(payload) != {'schema_version', 'identity', 'master_weights', 'state'}
            or payload['schema_version'] != 'ember-cia-native-optimizer-state-v1'
            or payload['master_weights'] is not None):
        raise ValueError('CIA optimizer state payload schema is invalid')
    try:
        actual_identity = json.dumps(payload['identity'], sort_keys=True, allow_nan=False)
    except (TypeError, ValueError) as error:
        raise ValueError('CIA optimizer state identity is not canonical JSON') from error
    if actual_identity != json.dumps(identity, sort_keys=True, allow_nan=False):
        raise ValueError('CIA optimizer state identity differs from the runtime')
    snapshot = _cia_named_optimizer_state(model, optimizer, payload['state'], max_state_bytes=max_state_bytes)
    runtime_groups = optimizer.state_dict()['param_groups']
    ids_by_name = {}
    for named_group, runtime_group in zip(identity['param_groups'], runtime_groups):
        ids_by_name.update(zip(named_group['params'], runtime_group['params']))
    return {'state': {ids_by_name[name]: fields for name, fields in snapshot.items()},
            'param_groups': copy.deepcopy(runtime_groups)}


def _cia_tensor_identity(value):
    return (id(value), value._version, str(value.device),
            value.untyped_storage().data_ptr(), value.untyped_storage().nbytes(),
            tuple(value.shape), tuple(value.stride()), value.dtype,
            value.storage_offset(), value.requires_grad)


def _cia_snapshot_placed_moments(parameters, state, *, max_state_bytes, restore=False):
    """Bound and snapshot native moments on their parameter devices; clocks stay CPU.

    No model/device migration, checkpoint write, optimizer mutation or receipt is
    performed. Do not accept meta storage as physical state. Preserve source
    tensor identities/versions throughout the copy, and reject aliased moments.
    """
    if type(max_state_bytes) is not int or max_state_bytes <= 0:
        raise ValueError('state byte cap must be a positive integer')
    if type(restore) is not bool:
        raise ValueError('closed copy direction required')
    if type(parameters) is not dict or type(state) is not dict:
        raise ValueError('closed named parameter and state dictionaries required')
    before, storage, total, devices = {}, [], 0, set()
    structure = tuple((name, tuple(fields)) for name, fields in state.items())
    parameter_storage = []
    parameter_identity = {}
    for name, parameter in parameters.items():
        if type(parameter) is not torch.nn.Parameter or parameter.device.type not in ('cpu', 'cuda'):
            raise ValueError('physical CPU/CUDA parameter required')
        device = str(parameter.device)
        begin = parameter.untyped_storage().data_ptr()
        size = parameter.untyped_storage().nbytes()
        parameter_storage.append((device, begin, begin + size))
        parameter_identity[name] = _cia_tensor_identity(parameter)
    for name, fields in state.items():
        if name not in parameters or type(fields) is not dict:
            raise ValueError('unknown parameter or invalid state fields')
        parameter = parameters[name]
        if type(parameter) is not torch.nn.Parameter or parameter.device.type not in ('cpu', 'cuda'):
            raise ValueError('physical CPU/CUDA parameter required')
        if parameter.dtype != torch.bfloat16:
            raise ValueError('BF16 parameter required')
        for key, value in fields.items():
            if key not in ('step', 'exp_avg', 'exp_avg_sq', 'max_exp_avg_sq'):
                raise ValueError('unknown native moment field')
            expected_device = torch.device('cpu') if key == 'step' or restore else parameter.device
            expected_shape = () if key == 'step' else tuple(parameter.shape)
            expected_dtype = torch.float32 if key == 'step' else torch.bfloat16
            if (type(value) is not torch.Tensor or value.device != expected_device
                    or tuple(value.shape) != expected_shape or value.dtype != expected_dtype
                    or value.requires_grad or not value.is_contiguous()
                    or value.storage_offset() != 0):
                raise ValueError('moment placement, layout or dtype mismatch')
            size = value.numel() * value.element_size()
            if value.untyped_storage().nbytes() != size:
                raise ValueError('moment must own its complete storage')
            total += size
            if total > max_state_bytes:
                raise ValueError('state exceeds byte cap before copying')
            device = str(value.device)
            begin = value.untyped_storage().data_ptr()
            storage.append((device, begin, begin + size))
            before[(name, key)] = _cia_tensor_identity(value)
            if value.device.type == 'cuda':
                devices.add(value.device)
    # Compare virtual addresses only within the same address space.
    storage.sort()
    if any(a[0] == b[0] and a[2] > b[1] for a, b in zip(storage, storage[1:])):
        raise ValueError('moment storage alias')
    combined = sorted([(*item, 'moment') for item in storage] +
                      [(*item, 'parameter') for item in parameter_storage])
    if any(a[0] == b[0] and a[2] > b[1] for a, b in zip(combined, combined[1:])):
        raise ValueError('state aliases parameter storage or parameters overlap')
    for device in devices:
        torch.cuda.synchronize(device)
    snapshot = {name: {key: value.detach().to(
                            device=parameters[name].device if restore and key != 'step' else 'cpu',
                            copy=True)
                       for key, value in fields.items()} for name, fields in state.items()}
    if structure != tuple((name, tuple(fields)) for name, fields in state.items()):
        raise ValueError('moment state membership changed during snapshot')
    after = {(name, key): _cia_tensor_identity(value)
             for name, fields in state.items() for key, value in fields.items()}
    if before != after:
        raise ValueError('moment state changed during snapshot')
    current_parameters = {name: _cia_tensor_identity(value)
                          for name, value in parameters.items()}
    if current_parameters != parameter_identity:
        raise ValueError('parameter state changed during snapshot')
    return snapshot


def _cia_physical_placement(parameters):
    placement = {}
    for name, parameter in parameters.items():
        if (type(parameter) is not torch.nn.Parameter
                or parameter.device.type not in ('cpu', 'cuda')
                or parameter.dtype != torch.bfloat16):
            raise ValueError('CIA placed state requires physical BF16 CPU/CUDA parameters')
        placement[name] = {'device': str(parameter.device), 'requires_grad': parameter.requires_grad}
    return placement


def _cia_live_optimizer_state_identity(optimizer):
    rows = []
    for parameter, fields in optimizer.state.items():
        if type(parameter) is not torch.nn.Parameter or type(fields) is not dict:
            raise ValueError('CIA live optimizer state membership is invalid')
        tensors = []
        for key, value in fields.items():
            if type(value) is not torch.Tensor:
                raise ValueError('CIA live optimizer state tensor is invalid')
            tensors.append((key, _cia_tensor_identity(value)))
        rows.append((id(parameter), id(fields), tuple(tensors)))
    return id(optimizer.state), tuple(rows)


def capture_cia_placed_optimizer_state(model, optimizer, *, max_state_bytes):
    """Capture v2 native moments once on CPU, under owner-held update exclusion.

    All model parameters must be physical. The owner must be outside a candidate
    step with a quiescent paging cache, and reserve live state plus snapshot memory.
    max_state_bytes bounds payload, not process peak. No checkpoint is admitted.
    """
    identity = cia_optimizer_identity(model, optimizer)
    parameters = model.parameter_inventory()
    placement = _cia_physical_placement(parameters)
    names = {id(parameter): name for name, parameter in parameters.items()}
    live_identity = _cia_live_optimizer_state_identity(optimizer)
    state = {names[id(parameter)]: fields for parameter, fields in optimizer.state.items()}
    snapshot = _cia_snapshot_placed_moments(parameters, state, max_state_bytes=max_state_bytes)
    _cia_validate_named_optimizer_state(model, optimizer, snapshot, max_state_bytes=max_state_bytes)
    if _cia_live_optimizer_state_identity(optimizer) != live_identity:
        raise ValueError('CIA live optimizer state changed during capture')
    if (cia_optimizer_identity(model, optimizer) != identity
            or _cia_physical_placement(model.parameter_inventory()) != placement):
        raise ValueError('CIA optimizer identity or placement changed during capture')
    return {'schema_version': 'ember-cia-placed-optimizer-state-v2',
            'identity': identity, 'placement': placement, 'master_weights': None, 'state': snapshot}


def prepare_cia_placed_optimizer_state(model, optimizer, payload, *, max_state_bytes):
    """Validate all CPU state before placement copies; mutate no runtime or payload.

    This prepares native optimizer input only. The complete recovery transaction
    owns update exclusion, cache quiescence, peak memory and checkpoint admission.
    """
    import copy
    identity = cia_optimizer_identity(model, optimizer)
    parameters = model.parameter_inventory()
    placement = _cia_physical_placement(parameters)
    if (type(payload) is not dict
            or set(payload) != {'schema_version', 'identity', 'placement', 'master_weights', 'state'}
            or payload['schema_version'] != 'ember-cia-placed-optimizer-state-v2'
            or payload['master_weights'] is not None):
        raise ValueError('CIA placed optimizer state payload schema is invalid')
    try:
        actual = json.dumps({'identity': payload['identity'], 'placement': payload['placement']},
                            sort_keys=True, allow_nan=False)
        expected = json.dumps({'identity': identity, 'placement': placement},
                              sort_keys=True, allow_nan=False)
    except (TypeError, ValueError) as error:
        raise ValueError('CIA placed optimizer identity is not canonical JSON') from error
    if actual != expected:
        raise ValueError('CIA placed optimizer identity or placement differs from runtime')
    # Validation does not copy: every field is checked before any device transfer.
    _cia_validate_named_optimizer_state(model, optimizer, payload['state'], max_state_bytes=max_state_bytes)
    snapshot = _cia_snapshot_placed_moments(parameters, payload['state'],
                                           max_state_bytes=max_state_bytes, restore=True)
    if (cia_optimizer_identity(model, optimizer) != identity
            or _cia_physical_placement(model.parameter_inventory()) != placement):
        raise ValueError('CIA optimizer identity or placement changed during preparation')
    runtime_groups = optimizer.state_dict()['param_groups']
    ids_by_name = {}
    for named_group, runtime_group in zip(identity['param_groups'], runtime_groups):
        ids_by_name.update(zip(named_group['params'], runtime_group['params']))
    return {'state': {ids_by_name[name]: fields for name, fields in snapshot.items()},
            'param_groups': copy.deepcopy(runtime_groups)}


_CIA_CHECKPOINT_SCHEMA = 'ember-cia-checkpoint-v1'


def _cia_quiescent_parameters(model):
    parameters = model.parameter_inventory()
    _cia_physical_placement(parameters)
    execution = model._cuda_execution
    if execution is not None and (execution.cache.active or execution.cache.pending
            or execution.cache.entries or execution.cache.leased or execution.cache.poisoned):
        raise ValueError('CIA checkpoint requires a quiescent candidate cache')
    if any(parameter.grad is not None for parameter in parameters.values()):
        raise ValueError('CIA checkpoint requires cleared gradients at an update boundary')
    return parameters


def _cia_parameter_snapshot_identity(parameters):
    return {name: _cia_tensor_identity(value) for name, value in parameters.items()}


def _cia_lineage_facts(parameters, optimizer_state):
    """Hash current or reopened tensor values without changing their placement."""
    def digest(value):
        view = value.detach().cpu().contiguous().view(torch.uint8)
        return hashlib.sha256(memoryview(view.numpy())).hexdigest()
    facts = {'parameters':{name:digest(value) for name,value in parameters.items()},
        'elements':{name:value.numel() for name,value in parameters.items()},'optimizer':{}}
    for name,state in optimizer_state.items():
        if state:
            facts['optimizer'][name] = {key:int(value.item()) if key=='step' else digest(value)
                                       for key,value in state.items()}
    return facts


def _cia_checkpoint_replay(manifest, replay):
    if type(replay) is not dict or set(replay) != {'rng_state', 'data_cursor'}:
        raise ValueError('CIA checkpoint replay schema mismatch')
    _validate_replay_bindings(launch_seed=manifest['launch_seed'], rng_state=replay['rng_state'],
        data_cursor=replay['data_cursor'], model_config_sha256=manifest['model_config_sha256'],
        contract_sha256=manifest['contract_sha256'], expert_genesis_sha256=manifest['expert_genesis_sha256'],
        expected_expert_names={str(i) for i in range(25)})
    if replay['data_cursor'] != manifest['data_cursor']:
        raise ValueError('CIA checkpoint replay cursor differs from manifest')
    hashes = {name: hashlib.sha256(value.cpu().numpy().tobytes()).hexdigest()
              for name, value in replay['rng_state'].items()}
    if hashes != manifest['rng_state_sha256']:
        raise ValueError('CIA checkpoint RNG differs from manifest')
    # Exercise the CPU state parser before mutating any global RNG or model.
    torch.Generator(device='cpu').set_state(replay['rng_state']['cpu'])


def _cia_read_component(root, record):
    import io
    if type(record) is not dict or set(record) != {'path', 'sha256', 'bytes'}:
        raise ValueError('CIA checkpoint component record schema mismatch')
    name = record['path']
    if name not in {'optimizer-state.pt', 'replay-state.pt'}:
        raise ValueError('CIA checkpoint component path mismatch')
    path = root / name
    if _path_has_link(path, root):
        raise ValueError('CIA checkpoint component is a symlink or reparse point')
    if type(record['bytes']) is not int or record['bytes'] < 1:
        raise ValueError('CIA checkpoint component byte bound mismatch')
    with path.open('rb') as handle:
        snapshot = handle.read(record['bytes'] + 1)
    if len(snapshot) != record['bytes'] or hashlib.sha256(snapshot).hexdigest() != record['sha256']:
        raise ValueError('CIA checkpoint component digest mismatch')
    return torch.load(io.BytesIO(snapshot), map_location='cpu', weights_only=True)


def _cia_validated_checkpoint(root, receipt, *, retain_model=False, max_restore_payload_bytes=None):
    """Inspect one complete raw generation, optionally retaining verified tensors.

    A retained snapshot prevents a later pathname read during restore. Admission
    uses the streaming mode and remains owned by admit_quarantined_checkpoint.
    """
    from ember.model.ember_v0_contract import validate_cia_architecture, cia_architecture_sha256
    root = Path(root)
    manifest_path = root / 'checkpoint-manifest.json'
    if _path_has_link(manifest_path, root):
        raise ValueError('CIA manifest is a symlink or reparse point')
    with manifest_path.open('rb') as handle:
        raw = handle.read(1048577)
    if len(raw) > 1048576: raise ValueError('CIA checkpoint manifest exceeds its byte bound')
    digest = hashlib.sha256(raw).hexdigest()
    manifest = json.loads(raw)
    descendant = 'lineage' in manifest
    fields = {'schema_version', 'architecture_revision', 'architecture_config', 'architecture',
        'launch_seed', 'rng_state_sha256', 'data_cursor', 'model_config_sha256', 'contract_sha256',
        'expert_genesis_sha256', 'expert_parameter_sha256', 'active_expert_ids', 'core', 'expert_index',
        'optimizer', 'replay', 'optimizer_identity', 'placement', 'max_restore_payload_bytes', 'genesis_provenance', 'qualification'} | ({'lineage'} if descendant else set())
    if type(manifest) is not dict or set(manifest) != fields or manifest['schema_version'] != _CIA_CHECKPOINT_SCHEMA:
        raise ValueError('CIA checkpoint manifest schema mismatch')
    if digest != receipt.get('checkpoint_manifest_sha256'):
        raise ValueError('CIA checkpoint manifest digest mismatch')
    if any(receipt.get(key) != value for key,value in manifest.items()):
        raise ValueError('CIA checkpoint receipt differs from raw manifest')
    if manifest['architecture_revision'] != 'CIA3-R1-N61':
        raise ValueError('CIA checkpoint architecture revision mismatch')
    if manifest['genesis_provenance'] != {'kind':'VERIFIED_ZERO_STEP_PARENT' if descendant else 'ZERO_STEP_OBJECT_BINDING','independently_qualified':False}:
        raise ValueError('CIA checkpoint genesis provenance is not an unqualified object binding')
    if manifest['qualification'] != {'clean_genesis':False,'trained':False,'served':False}:
        raise ValueError('CIA checkpoint bytes cannot grant model qualification')
    if not descendant and (manifest['data_cursor'].get('global_step') != 0 or manifest['data_cursor'].get('tokens_seen') != 0):
        raise ValueError('CIA descendant publication requires a verified parent-lineage consumer')
    config = manifest['architecture_config']
    validate_cia_architecture(config)
    cia_architecture_sha256(config)
    cap = manifest['max_restore_payload_bytes']
    if type(cap) is not int or cap < 1:
        raise ValueError('CIA checkpoint restore byte bound mismatch')
    if retain_model and (type(max_restore_payload_bytes) is not int or max_restore_payload_bytes < cap):
        raise ValueError('CIA checkpoint restore exceeds the explicit caller byte bound')
    parent = parent_facts = None
    if descendant:
        lineage = manifest['lineage']
        if type(lineage) is not dict: raise ValueError('CIA descendant lineage schema mismatch')
        import parameter_counter as cia_counter
        parent, parent_facts = cia_counter._cia_parent_snapshot(lineage.get('parent_checkpoint',''),
            max_restore_payload_bytes=cap, expected_digest=lineage.get('parent_manifest_sha256'))
        _cia_validated_checkpoint(Path(lineage['parent_checkpoint']),parent)
    index = manifest['expert_index']
    if type(index) is not dict or set(index) != {'path', 'sha256', 'bytes', 'expert_object_bytes'}:
        raise ValueError('CIA checkpoint expert index record schema mismatch')
    if index['path'] != 'expert-index-' + _sha256_value(index['sha256'], name='CIA index digest') + '.json':
        raise ValueError('CIA checkpoint expert index path mismatch')
    index_path = root / index['path']
    if _path_has_link(index_path, root):
        raise ValueError('CIA checkpoint index is a symlink or reparse point')
    with index_path.open("rb") as handle:
        index_raw = handle.read(65537)
    if len(index_raw) > 65536 or len(index_raw) != index['bytes'] or hashlib.sha256(index_raw).hexdigest() != index['sha256']:
        raise ValueError('CIA checkpoint expert index digest mismatch')
    object_index = json.loads(index_raw)
    objects = object_index.get('experts', [])
    if len(objects) != 25:
        raise ValueError('CIA checkpoint requires all 25 expert objects')
    object_total = sum(record['bytes'] for record in objects)
    if object_total != index['expert_object_bytes']:
        raise ValueError('CIA checkpoint expert byte arithmetic mismatch')
    component_records = [manifest['core'], *objects, manifest['optimizer'], manifest['replay']]
    if any(type(record.get('bytes')) is not int or record['bytes'] < 1 for record in component_records):
        raise ValueError('CIA checkpoint component byte bound mismatch')
    if sum(record['bytes'] for record in component_records) > cap:
        raise ValueError('CIA checkpoint components exceed restore byte bound')
    expected = {'checkpoint-manifest.json', index['path'], 'optimizer-state.pt', 'replay-state.pt',
                *('objects/'+record['sha256']+'.pt' for record in [manifest['core'], *objects])}
    observed = set()
    for path in root.rglob('*'):
        if _path_has_link(path, root):
            raise ValueError('CIA checkpoint closure is a symlink or reparse point')
        relative = path.relative_to(root).as_posix()
        if path.is_dir():
            if relative != 'objects': raise ValueError('CIA checkpoint directory closure mismatch')
        else: observed.add(relative)
    if observed - _ALLOWED_CANDIDATE_METADATA != expected:
        raise ValueError('CIA checkpoint requires exact complete object closure')
    tensors = read_cia_core_object(root, record=manifest['core'], architecture_config=config)
    inventory = {name: (tuple(value.shape), value.numel()) for name,value in tensors.items()}
    lineage_facts = _cia_lineage_facts(tensors,{}) if descendant else None
    if not retain_model: tensors = {}
    for expert_id in range(25):
        expert = read_cia_expert_object(index_path, expected_index_sha256=index['sha256'], expert_id=expert_id)
        inventory.update({name: (tuple(value.shape), value.numel()) for name,value in expert.items()})
        if descendant:
            expert_facts = _cia_lineage_facts(expert,{})
            lineage_facts['parameters'].update(expert_facts['parameters'])
            lineage_facts['elements'].update(expert_facts['elements'])
        if retain_model: tensors.update(expert)
        del expert
    optimizer = _cia_read_component(root, manifest['optimizer'])
    if optimizer.get('identity') != manifest['optimizer_identity'] or optimizer.get('placement') != manifest['placement']:
        raise ValueError('CIA checkpoint optimizer identity or placement binding mismatch')
    placement = manifest['placement']
    if type(placement) is not dict or set(placement) != set(inventory):
        raise ValueError('CIA checkpoint placement inventory mismatch')
    for item in placement.values():
        if type(item) is not dict or set(item) != {'device','requires_grad'} or type(item['requires_grad']) is not bool:
            raise ValueError('CIA checkpoint placement record mismatch')
        if item['device'] != 'cpu' and not (type(item['device']) is str and item['device'].startswith('cuda:') and item['device'][5:].isdigit()):
            raise ValueError('CIA checkpoint placement device mismatch')
    membership = [name for group in manifest['optimizer_identity'].get('param_groups', []) for name in group['params']]
    if len(membership) != len(inventory) or set(membership) != set(inventory):
        raise ValueError('CIA checkpoint optimizer full membership mismatch')
    if (type(optimizer) is not dict or set(optimizer) != {'schema_version','identity','placement','master_weights','state'}
            or optimizer['schema_version'] != 'ember-cia-placed-optimizer-state-v2' or optimizer['master_weights'] is not None):
        raise ValueError('CIA checkpoint native optimizer payload schema mismatch')
    from types import SimpleNamespace
    shapes = {name: SimpleNamespace(shape=shape) for name,(shape,_) in inventory.items()}
    groups = {name: group['hyperparameters'] for group in manifest['optimizer_identity']['param_groups'] for name in group['params']}
    if any(group.get('capturable') or group.get('fused') or group.get('differentiable') for group in groups.values()):
        raise ValueError('CIA checkpoint optimizer execution mode is unsupported')
    _cia_validate_optimizer_fields(shapes,groups,optimizer['state'],max_state_bytes=cap)
    replay = _cia_read_component(root, manifest['replay'])
    _cia_checkpoint_replay(manifest, replay)
    total = sum(value[1] for value in inventory.values())
    active = sum(inventory[name][1] for name in inventory if placement[name]['requires_grad'])
    counts = dict(allocated_parameters=total, unique_parameters=total, trainable_parameters=total,
                  served_parameters=total, active_parameters=active, episode_trainable_parameters=active)
    if manifest['architecture'] != counts:
        raise ValueError('CIA checkpoint measured inventory differs from manifest')
    active_experts = [str(i) for i in range(25) if any(name.startswith(f'experts.{i}.') and placement[name]['requires_grad'] for name in inventory)]
    if manifest['active_expert_ids'] != active_experts:
        raise ValueError('CIA checkpoint update support differs from manifest')
    if manifest['expert_parameter_sha256'] != {str(i): record['sha256'] for i,record in enumerate(objects)}:
        raise ValueError('CIA checkpoint expert object identities differ from manifest')
    if not descendant and manifest['expert_genesis_sha256'] != manifest['expert_parameter_sha256']:
        raise ValueError('CIA zero-step genesis object map differs from immutable expert objects')
    if descendant:
        lineage_facts['optimizer'] = _cia_lineage_facts({},optimizer['state'])['optimizer']
        derived = cia_counter._cia_derive_first_lineage(Path(manifest['lineage']['parent_checkpoint']),
            parent,parent_facts,manifest,lineage_facts)
        if manifest['lineage'] != derived:
            raise ValueError('CIA descendant lineage differs from reopened parent and child bytes')
    metadata, persisted = {}, None
    for name in sorted(observed & _ALLOWED_CANDIDATE_METADATA):
        data = (root/name).read_bytes()
        metadata[name] = {'sha256':hashlib.sha256(data).hexdigest(), 'bytes':len(data)}
        if name == 'parameter-counter-receipt.json': persisted = json.loads(data)
    serialized = sum((root/name).stat().st_size for name in observed)
    result = dict(manifest, checkpoint_manifest_sha256=digest, metadata=metadata,
                  serialized_bytes=serialized, incremental_publication_bytes=serialized,
                  _counter_receipt_payload=persisted)
    return result, tensors, optimizer, replay


def _write_cia_checkpoint_artifacts(model, optimizer, root, *, launch_seed, rng_state, data_cursor,
        model_config_sha256, contract_sha256, expert_genesis_sha256, max_serialized_bytes,
        max_transient_scratch_bytes, pre_publish_verifier, host_commit_reserve_bytes=None,
        cia_parent_checkpoint=None):
    """Complete CIA publication through the existing quarantine admission authority.

    Caller owns exclusion from updates throughout capture. Native optimizer
    moments retain their dtypes; no master weights are created or claimed.
    """
    from ember.model.ember_v0_inventory import equation_inventory
    from ember.model.ember_v0_contract import cia_architecture_config, validate_cia_architecture
    config = cia_architecture_config()
    if model.config != validate_cia_architecture(config):
        raise ValueError("CIA checkpoint runtime architecture mismatch")
    if not callable(pre_publish_verifier): raise ValueError('pre-publish verifier is required')
    for cap in (max_serialized_bytes, max_transient_scratch_bytes):
        if type(cap) is not int or cap < 1: raise ValueError('CIA checkpoint requires explicit positive byte bounds')
    descendant = cia_parent_checkpoint is not None
    if not descendant and (data_cursor.get('global_step') != 0 or data_cursor.get('tokens_seen') != 0):
        raise ValueError('CIA descendant publication requires a verified parent-lineage consumer')
    parameters = _cia_quiescent_parameters(model)
    identity = cia_optimizer_identity(model, optimizer)
    before = _cia_parameter_snapshot_identity(parameters)
    live_optimizer = _cia_live_optimizer_state_identity(optimizer)
    minimum = sum(value.numel()*value.element_size() for value in parameters.values())
    minimum += sum(value.numel()*value.element_size() for fields in optimizer.state.values() for value in fields.values())
    if minimum > max_serialized_bytes or minimum > max_transient_scratch_bytes:
        raise ValueError('CIA checkpoint population exceeds the declared serialized or restore byte bound')
    if host_commit_reserve_bytes is not None:
        checkpoint_commit_preflight(available_commit_bytes=available_host_commit_bytes(),
            streaming_peak_bytes=2*max_transient_scratch_bytes, reserve_bytes=host_commit_reserve_bytes)
    parent = parent_facts = None
    if descendant:
        import parameter_counter as cia_counter
        parent, parent_facts = cia_counter._cia_parent_snapshot(cia_parent_checkpoint,
            max_restore_payload_bytes=max_transient_scratch_bytes)
        _cia_validated_checkpoint(Path(cia_parent_checkpoint),parent)
        if Path(root).resolve() == Path(cia_parent_checkpoint).resolve():
            raise ValueError('CIA child checkpoint cannot replace its parent')
    _validate_replay_bindings(launch_seed=launch_seed, rng_state=rng_state, data_cursor=data_cursor,
        model_config_sha256=model_config_sha256, contract_sha256=contract_sha256,
        expert_genesis_sha256=expert_genesis_sha256, expected_expert_names=({str(i) for i in range(25)} if expert_genesis_sha256 else set()))
    published = Path(root)
    if published.exists(): raise FileExistsError('published CIA checkpoint already exists')
    published.parent.mkdir(parents=True, exist_ok=True)
    quarantine = published.parent / '.checkpoint-quarantine'
    quarantine.mkdir(exist_ok=True)
    if _path_has_link(quarantine, published.parent): raise ValueError('CIA quarantine is a symlink or reparse point')
    candidate = quarantine / ('candidate-' + published.name + '-' + uuid.uuid4().hex)
    candidate.mkdir()
    _write_json_atomic(candidate, _STAGING_LEASE, {'pid':os.getpid()})
    try:
        specs = equation_inventory()
        def snapshot(selected):
            return {spec.name: parameters[spec.name].detach().to('cpu', copy=True) for spec in specs if selected(spec)}
        core = write_cia_core_object(candidate, tensors=snapshot(lambda spec: spec.expert is None),
            architecture_config=config, max_serialized_bytes=min(max_transient_scratch_bytes,251383808*2+4194304))
        objects = [write_cia_expert_object(candidate, expert_id=i, tensors=snapshot(lambda spec: spec.expert == i),
                   max_serialized_bytes=min(max_transient_scratch_bytes,113246208*2+4194304)) for i in range(25)]
        index = write_cia_expert_index(candidate, records=objects, max_total_object_bytes=max_serialized_bytes)
        object_genesis = (dict(parent['expert_genesis_sha256']) if descendant else
                          {str(i):record['sha256'] for i,record in enumerate(objects)})
        if expert_genesis_sha256 and dict(expert_genesis_sha256) != object_genesis:
            raise ValueError('CIA supplied genesis map differs from immutable object identities')
        optimizer_payload = capture_cia_placed_optimizer_state(model, optimizer, max_state_bytes=max_transient_scratch_bytes)
        replay_payload = {'rng_state':{name:value.detach().cpu().clone() for name,value in rng_state.items()}, 'data_cursor':dict(data_cursor)}
        components = {}
        for name,payload in (('optimizer-state.pt', optimizer_payload), ('replay-state.pt',replay_payload)):
            path = _write_atomic(candidate, name, lambda handle: torch.save(payload, handle), max_transient_scratch_bytes=max_transient_scratch_bytes)
            components[name] = {'path':name,'sha256':_sha256(path),'bytes':path.stat().st_size}
        total = sum(value.numel() for value in parameters.values())
        active = sum(value.numel() for value in parameters.values() if value.requires_grad)
        manifest = dict(schema_version=_CIA_CHECKPOINT_SCHEMA, architecture_revision='CIA3-R1-N61',
            architecture_config=config, architecture=dict(allocated_parameters=total,unique_parameters=total,
                trainable_parameters=total,served_parameters=total,active_parameters=active,episode_trainable_parameters=active),
            launch_seed=launch_seed, rng_state_sha256={name:hashlib.sha256(value.numpy().tobytes()).hexdigest() for name,value in replay_payload['rng_state'].items()},
            data_cursor=dict(data_cursor),model_config_sha256=model_config_sha256,contract_sha256=contract_sha256,
            expert_genesis_sha256=object_genesis,expert_parameter_sha256={str(i):record['sha256'] for i,record in enumerate(objects)},
            active_expert_ids=[str(i) for i in range(25) if any(spec.expert == i and parameters[spec.name].requires_grad for spec in specs)],
            core=core,expert_index=index,optimizer=components['optimizer-state.pt'],replay=components['replay-state.pt'],
            optimizer_identity=identity,placement=optimizer_payload['placement'],max_restore_payload_bytes=max_transient_scratch_bytes,
            genesis_provenance={'kind':'VERIFIED_ZERO_STEP_PARENT' if descendant else 'ZERO_STEP_OBJECT_BINDING','independently_qualified':False},
            qualification={'clean_genesis':False,'trained':False,'served':False})
        if descendant:
            facts = _cia_lineage_facts(parameters,optimizer_payload['state'])
            manifest['lineage'] = cia_counter._cia_derive_first_lineage(Path(cia_parent_checkpoint),
                parent,parent_facts,manifest,facts)
        if (_cia_parameter_snapshot_identity(_cia_quiescent_parameters(model)) != before or cia_optimizer_identity(model,optimizer) != identity
                or _cia_live_optimizer_state_identity(optimizer) != live_optimizer):
            raise ValueError('CIA model or optimizer identity changed during checkpoint capture')
        _write_json_atomic(candidate, 'checkpoint-manifest.json', manifest, max_transient_scratch_bytes=max_transient_scratch_bytes)
        (candidate/_STAGING_LEASE).unlink()
        return admit_quarantined_checkpoint(candidate,published,verifier=pre_publish_verifier,
            max_serialized_bytes=max_serialized_bytes,expected_optimizer_realization=identity)
    except Exception as error:
        _retain_write_failure_evidence(published,candidate,error)
        raise


def _load_cia_checkpoint_artifacts(model, optimizer, root, receipt, *, max_transient_scratch_bytes=None, host_commit_reserve_bytes=None):
    """Validate complete immutable payloads before the first runtime mutation."""
    root = _admitted_checkpoint_root(root)
    parameters = _cia_quiescent_parameters(model)
    identity = cia_optimizer_identity(model, optimizer)
    before = _cia_parameter_snapshot_identity(parameters)
    if type(max_transient_scratch_bytes) is not int or max_transient_scratch_bytes < 1:
        raise ValueError('CIA restore requires an explicit positive caller byte bound')
    if host_commit_reserve_bytes is not None:
        checkpoint_commit_preflight(available_commit_bytes=available_host_commit_bytes(),
            streaming_peak_bytes=2*max_transient_scratch_bytes,reserve_bytes=host_commit_reserve_bytes)
    verified, tensors, optimizer_payload, replay = _cia_validated_checkpoint(root,receipt,retain_model=True,
        max_restore_payload_bytes=max_transient_scratch_bytes)

    if receipt.get('checkpoint',{}).get('byte_sha256') != verified['checkpoint_manifest_sha256']:
        raise ValueError('CIA published checkpoint identity mismatch')
    from ember.model.ember_v0_contract import validate_cia_architecture
    if model.config != validate_cia_architecture(verified['architecture_config']) or identity != verified['optimizer_identity']:
        raise ValueError('CIA restore runtime architecture or optimizer identity mismatch')
    if set(tensors) != set(parameters): raise ValueError('CIA restore complete parameter inventory mismatch')
    for name, tensor in tensors.items():
        if tensor.shape != parameters[name].shape or tensor.dtype != parameters[name].dtype:
            raise ValueError('CIA restore parameter shape or dtype mismatch')
    prepared = prepare_cia_placed_optimizer_state(model,optimizer,optimizer_payload,max_state_bytes=verified['max_restore_payload_bytes'])
    cuda_rng = replay['rng_state']['cuda']
    if any(parameter.device.type == 'cuda' for parameter in parameters.values()):
        device = next(parameter.device for parameter in parameters.values() if parameter.device.type == 'cuda')
        torch.Generator(device=device).set_state(cuda_rng)
    elif cuda_rng.numel():
        raise ValueError('CIA CPU restore cannot silently discard CUDA RNG state')
    _validate_counter_receipt(verified,verified['_counter_receipt_payload'],verified['_counter_receipt_payload'])
    if _cia_parameter_snapshot_identity(_cia_quiescent_parameters(model)) != before or cia_optimizer_identity(model,optimizer) != identity:
        raise ValueError('CIA runtime identity changed during restore preparation')
    # All checkpoint, optimizer, RNG and placement checks precede this boundary.
    with torch.no_grad():
        for name,value in tensors.items(): parameters[name].copy_(value)
    optimizer.load_state_dict(prepared)
    torch.set_rng_state(replay['rng_state']['cpu'])
    if cuda_rng.numel(): torch.cuda.set_rng_state(cuda_rng,device=device)
    return {'data_cursor':dict(replay['data_cursor'])}
