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
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Mapping

import torch

from durable_io import atomic_replace_durable
from model import EXPERT_NAMES, UnifiedDecoder
from parameter_counter import SPECIALIST_VERIFICATION_FIELDS, measure_parameter_counts, validate_p2b_stream_episode, validate_realization_receipt
from specialist_stream import SELECTION_CURSOR_SCHEMA_VERSION, TRAINING_CURSOR_SCHEMA_VERSION


_STAGING_LEASE = ".writer-lease.json"
_ALLOWED_CANDIDATE_METADATA = {"parameter-counter-receipt.json"}
_FAILURE_EVIDENCE_LIMIT = 64 * 1024
_STREAMING_OVERHEAD_BYTES = 64 * 1024 * 1024


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


def configured_maximum_available_commit_bytes(
    *,
    physical_ram_bytes: int,
    commit_total_bytes: int,
    current_commit_limit_bytes: int,
    paging_files: object,
) -> int:
    """Return headroom against fixed maximum pagefile capacity, or fail closed."""

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
    maximum_commit_capacity_bytes = physical_ram_bytes + pagefile_maximum_mib * 1024**2
    if maximum_commit_capacity_bytes < current_commit_limit_bytes:
        raise RuntimeError("configured pagefile maximum is below the live Windows commit limit")
    if maximum_commit_capacity_bytes < commit_total_bytes:
        raise RuntimeError("live committed bytes exceed configured maximum commit capacity")
    return maximum_commit_capacity_bytes - commit_total_bytes


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
) -> dict[str, int | str]:
    if any(type(value) is not int or value < 0 for value in (available_commit_bytes, streaming_peak_bytes, reserve_bytes)):
        raise ValueError("checkpoint host commit values must be nonnegative integers")
    required = streaming_peak_bytes + reserve_bytes
    if available_commit_bytes < required:
        raise RuntimeError(
            "checkpoint host commit reserve is insufficient: "
            f"available={available_commit_bytes}, required={required}, "
            f"streaming_peak={streaming_peak_bytes}, reserve={reserve_bytes}"
        )
    return {
        "status": "PASS",
        "available_commit_bytes": available_commit_bytes,
        "streaming_peak_bytes": streaming_peak_bytes,
        "reserve_bytes": reserve_bytes,
        "required_commit_bytes": required,
    }


def _retain_write_failure_evidence(
    published_root: Path,
    staging_root: Path,
    error: BaseException,
    *,
    quarantine_candidate: str | None = None,
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
    payload = {
        "schema_version": "ember-checkpoint-write-failure-v1",
        "target": published_root.name,
        "quarantine_candidate": quarantine_candidate,
        "error_type": type(error).__name__,
        "error_message": str(error)[:4096],
        "checkpoint_manifest_sha256": manifest_sha256,
        "shards": shards,
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


class _ScratchCappedWriter:
    """Reject a temporary shard before a write would cross its byte cap."""

    def __init__(self, handle: Any, max_bytes: int) -> None:
        self._handle = handle
        self._max_bytes = max_bytes

    def write(self, payload: bytes | bytearray | memoryview) -> int:
        projected_end = self._handle.tell() + len(payload)
        if projected_end > self._max_bytes:
            raise RuntimeError(
                f"checkpoint transient scratch exceeds {self._max_bytes} bytes"
            )
        return self._handle.write(payload)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._handle, name)


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
) -> dict[str, Any]:
    """Bind the post-update optimizer floor and four-expert checkpoint floor."""

    if type(global_step) is not int or global_step < 1:
        raise ValueError(
            "checkpoint storage projection requires post-update global_step"
        )
    if model.active_expert not in EXPERT_NAMES:
        raise ValueError(
            "checkpoint storage projection requires one active specialist expert"
        )
    expected_shards = {
        "shared-model.pt",
        "optimizer-state.pt",
        "replay-state.pt",
        *(f"expert-{name}.pt" for name in EXPERT_NAMES),
    }
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

    optimizer_actual = _unique_tensor_storage_bytes(optimizer_file_payload)
    routed_optimizer = _optimizer_tensor_storage_by_route(model, optimizer)
    active_bytes = routed_optimizer[model.active_expert]
    active_routes = [
        name for name in EXPERT_NAMES if routed_optimizer[name] > 0
    ]
    if optimizer_actual < 1 or active_bytes < 1 or active_routes != [
        model.active_expert
    ]:
        raise ValueError(
            "checkpoint storage projection requires one post-update optimizer state"
        )
    # Admission cannot recover the runtime parameter-to-route identity from a
    # generic optimizer state_dict without trusting candidate-authored labels.
    # Use the closed worst-case bound: every initialized byte may belong to the
    # one active specialist and therefore exist once per specialist at full
    # four-expert realization.
    projected_optimizer = optimizer_actual * len(EXPERT_NAMES)
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
    if transient_new_write_peak > max_transient_scratch_bytes:
        raise RuntimeError(
            "checkpoint transient new-write projection exceeds scratch cap"
        )
    if projected_checkpoint_floor > max_serialized_bytes:
        raise RuntimeError(
            "checkpoint all-expert projected tensor-storage lower bound "
            "exceeds the derived serialized byte bound"
        )

    projection = {
        "schema_version": "ember-checkpoint-storage-projection-v1",
        "active_expert": model.active_expert,
        "optimizer_state_after_global_step": global_step,
        "optimizer_state_active_expert_ids": active_routes,
        "optimizer_state_tensor_storage_lower_bound_bytes": optimizer_actual,
        "optimizer_state_tensor_storage_by_route_bytes": routed_optimizer,
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
    if not isinstance(projection, Mapping) or set(projection) != required:
        raise ValueError("checkpoint storage projection has an invalid shape")
    materialized = dict(projection)
    digest = materialized.pop("projection_sha256")
    if (
        materialized["schema_version"]
        != "ember-checkpoint-storage-projection-v1"
        or not isinstance(digest, str)
        or digest != _canonical_sha256(materialized)
    ):
        raise ValueError("checkpoint storage projection digest mismatch")
    if (
        materialized["active_expert"] not in EXPERT_NAMES
        or materialized["optimizer_state_active_expert_ids"]
        != [materialized["active_expert"]]
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
    expected_shards = {
        "shared-model.pt",
        "optimizer-state.pt",
        "replay-state.pt",
        *(f"expert-{name}.pt" for name in EXPERT_NAMES),
    }
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
    active_routes = [
        name for name in EXPERT_NAMES if route_bounds[name] > 0
    ]
    if active_routes != [active_expert]:
        raise ValueError("checkpoint optimizer route projection is invalid")
    optimizer_actual = materialized[
        "optimizer_state_tensor_storage_lower_bound_bytes"
    ]
    expected_projected_optimizer = optimizer_actual * len(EXPERT_NAMES)
    if (
        shard_bounds["optimizer-state.pt"] != optimizer_actual
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

    expected_shards = {
        "shared-model.pt",
        "optimizer-state.pt",
        "replay-state.pt",
        *(f"expert-{name}.pt" for name in EXPERT_NAMES),
    }
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

    optimizer_actual = measured["optimizer-state.pt"]
    projected_optimizer = optimizer_actual * len(EXPERT_NAMES)
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
    if set(expert_genesis_sha256) != set(EXPERT_NAMES):
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

def _specialist_lineage(
    lineage: Mapping[str, Any], *, active_expert: str, candidate_parameter_sha256: Mapping[str, str],
    data_cursor: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, str], dict[str, str], Path]:
    """Close one-family accretion against independently supplied parent/root bundles."""

    if active_expert not in EXPERT_NAMES:
        raise ValueError("specialist lineage requires one specialist active expert")
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
        }, dict(root["expert_genesis_sha256"]), dict(parent_experts), parent_path.parent)
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
    }, dict(root["expert_genesis_sha256"]), dict(parent_experts), parent_path.parent)
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


def _checkpoint_candidate_receipt(candidate: Path) -> dict[str, Any]:
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
    records = _validated_records(candidate, receipt)
    projection = receipt.get("storage_projection")
    if projection is not None:
        validated_projection = _validate_checkpoint_storage_projection(
            projection
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
    receipt = _checkpoint_candidate_receipt(candidate)
    if receipt.get("storage_projection") is not None:
        _validate_checkpoint_storage_projection(
            receipt["storage_projection"],
            max_serialized_bytes=max_serialized_bytes,
        )
    try:
        # Take a snapshot after direct verifier work, then materialize the returned
        # Mapping before the final snapshot.  No callback-controlled object is touched
        # after final_snapshot.
        returned_counter_receipt = verifier(candidate, dict(receipt))
        try:
            post_callback_receipt = _checkpoint_candidate_receipt(candidate)
        except Exception as error:
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
        final_receipt = _checkpoint_candidate_receipt(candidate)
        if final_receipt != post_callback_receipt:
            raise ValueError("checkpoint candidate changed after verifier validation")
    except Exception as error:
        _retain_write_failure_evidence(published_root, candidate, error)
        raise
    try:
        _atomic_publish_no_replace(candidate, published_root)
    except OSError as error:
        if isinstance(error, FileExistsError) or error.errno in (errno.EEXIST, errno.ENOTEMPTY) or published_root.exists():
            _retain_write_failure_evidence(published_root, candidate, error)
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
    specialist_lineage: Mapping[str, Any] | None = None,
    max_serialized_bytes: int | None = None,
    max_transient_scratch_bytes: int | None = None,
    host_commit_reserve_bytes: int | None = None,
    pre_publish_verifier: Callable[[Path, dict[str, Any]], Mapping[str, Any]],
) -> dict[str, Any]:
    """Publish complete post-step artifacts, manifest last, with replay bindings."""

    if max_serialized_bytes is not None and (type(max_serialized_bytes) is not int or max_serialized_bytes < 1):
        raise ValueError("max_serialized_bytes must be a positive integer")
    if max_transient_scratch_bytes is not None and (
        type(max_transient_scratch_bytes) is not int
        or max_transient_scratch_bytes < 1
    ):
        raise ValueError("max_transient_scratch_bytes must be a positive integer")
    if not callable(pre_publish_verifier):
        raise ValueError("pre-publish verifier is required")
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
    expert_parameter_sha256 = model.expert_bank_genesis_hashes()
    preflight_lineage = None
    preflight_genesis = None
    if specialist_lineage is not None:
        preflight_lineage, preflight_genesis, preflight_parent_shards, preflight_parent_root = _specialist_lineage(specialist_lineage, active_expert=model.active_expert, candidate_parameter_sha256=expert_parameter_sha256, data_cursor=data_cursor)
    published_root = root
    if published_root.exists():
        raise FileExistsError(f"published checkpoint bundle already exists: {published_root}")
    published_root.parent.mkdir(parents=True, exist_ok=True)
    host_commit_plan: dict[str, int | str] | None = None
    if host_commit_reserve_bytes is not None:
        host_commit_plan = checkpoint_commit_preflight(
            available_commit_bytes=available_host_commit_bytes(),
            streaming_peak_bytes=checkpoint_streaming_peak_bytes(model, optimizer),
            reserve_bytes=host_commit_reserve_bytes,
        )
    # The PID in the private name lets a later retention pass distinguish an
    # active writer from crash residue without publishing a mutable lease file
    # inside the checkpoint bundle.
    root = published_root.parent / f".{published_root.name}.{os.getpid()}.{uuid.uuid4().hex}.staging"
    root.mkdir()
    try:
        model_state = model.state_dict()
        shared_state = _select_detached_state(model_state, lambda name: ".experts." not in name)
        optimizer_state_payload = optimizer.state_dict()
        optimizer_file_payload = {
            "optimizer": optimizer_state_payload,
            "optimizer_contract": optimizer_contract,
            "optimizer_realization": optimizer_realization,
        }
        shard_storage_lower_bounds = {
            "shared-model.pt": _unique_tensor_storage_bytes(shared_state),
            "optimizer-state.pt": _unique_tensor_storage_bytes(
                optimizer_file_payload
            ),
            "replay-state.pt": _unique_tensor_storage_bytes(rng_state),
            **{
                f"expert-{name}.pt": _unique_tensor_storage_bytes(
                    _select_detached_state(
                        model_state,
                        lambda key, selected=name: f".experts.{selected}." in key,
                    )
                )
                for name in EXPERT_NAMES
            },
        }
        if max_transient_scratch_bytes is not None:
            for shard_name, lower_bound in shard_storage_lower_bounds.items():
                if lower_bound > max_transient_scratch_bytes:
                    raise RuntimeError(
                        f"checkpoint {shard_name} tensor-storage lower bound "
                        f"{lower_bound} exceeds transient scratch cap "
                        f"{max_transient_scratch_bytes}"
                    )
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
        optimizer_state_path = _write_atomic(
            root,
            "optimizer-state.pt",
            lambda handle: torch.save(optimizer_file_payload, handle),
            max_transient_scratch_bytes=max_transient_scratch_bytes,
        )
        shards = [
            _record(shared_model, root, role="shared_model"),
            _record(optimizer_state_path, root, role="optimizer_state"),
        ]
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
            if specialist_lineage is not None and name != model.active_expert:
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
            )

        counts = measure_parameter_counts(model)
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
            "optimizer_state_shard_sha256": shards[1]["sha256"],
            "optimizer_contract": optimizer_contract,
            "optimizer_realization": optimizer_realization,
            "shards": shards,
        }
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
            raise ValueError("serialized checkpoint exceeds the derived byte bound")
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
            )
        _atomic_publish_no_replace(root, published_root)
        return _bind_checkpoint_identity(published_root, receipt)
    except Exception as error:
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
    specialist_lineage: Mapping[str, Any] | None = None,
    max_serialized_bytes: int | None = None,
    max_transient_scratch_bytes: int | None = None,
    host_commit_reserve_bytes: int | None = None,
    pre_publish_verifier: Callable[[Path, dict[str, Any]], Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
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
    if schema_version == "ember-sparse-checkpoint-v5":
        expected_paths = {
            "shared-model.pt",
            "optimizer-state.pt",
            "replay-state.pt",
            *(f"expert-{name}.pt" for name in EXPERT_NAMES),
        }
    elif schema_version in {
        "ember-sparse-checkpoint-v3",
        "ember-sparse-checkpoint-v4",
    }:
        expected_paths = {
            "shared.pt",
            "replay-state.pt",
            *(f"expert-{name}.pt" for name in EXPERT_NAMES),
        }
    else:
        raise ValueError("checkpoint schema version is unsupported")
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


def load_checkpoint_artifacts(
    model: UnifiedDecoder,
    optimizer: torch.optim.Optimizer,
    root: Path,
    receipt: Mapping[str, Any],
) -> None:
    """Verify every manifest/shard/payload before mutating model or optimizer."""

    root = _admitted_checkpoint_root(root)
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
        if (
            receipt.get("shared_model_shard_sha256")
            != records["shared-model.pt"]["sha256"]
            or receipt.get("optimizer_state_shard_sha256")
            != records["optimizer-state.pt"]["sha256"]
        ):
            raise ValueError("v5 checkpoint does not bind its split shared and optimizer shards")
    elif (
        receipt.get("shared_optimizer_shard_sha256")
        != records["shared.pt"]["sha256"]
    ):
        raise ValueError("legacy checkpoint does not bind its shared optimizer shard")

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
        payloads[relative] = torch.load(root / relative, map_location="cpu", weights_only=False)
    replay_payload = payloads["replay-state.pt"]
    if (not isinstance(replay_payload, dict) or not isinstance(replay_payload.get("rng_state"), dict) or set(replay_payload["rng_state"]) != {"cpu", "cuda"} or replay_payload.get("data_cursor") != receipt.get("data_cursor")):
        raise ValueError("checkpoint replay state is incomplete or cursor-mismatched")
    for name, state in replay_payload["rng_state"].items():
        if not isinstance(state, torch.Tensor) or state.dtype != torch.uint8 or state.ndim != 1:
            raise ValueError(f"checkpoint replay RNG state is invalid: {name}")
    if schema_version == "ember-sparse-checkpoint-v5":
        shared_payload = payloads["shared-model.pt"]
        optimizer_payload = payloads["optimizer-state.pt"]
    else:
        shared_payload = payloads["shared.pt"]
        optimizer_payload = shared_payload
    if (
        not isinstance(shared_payload, dict)
        or not isinstance(optimizer_payload, dict)
        or not isinstance(optimizer_payload.get("optimizer"), dict)
    ):
        raise ValueError("checkpoint does not contain split model and optimizer state")
    if (
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

    model.load_state_dict(shared_state, strict=False)
    for state in expert_states.values():
        model.load_state_dict(state, strict=False)
    if optimizer is not None:
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
