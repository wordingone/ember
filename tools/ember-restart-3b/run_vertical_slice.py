# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Bounded CUDA one-batch sparse slice; invoke only through the disk budget runner."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

import tokenizers
import torch

from checkpoint_artifacts import _atomic_publish_no_replace, load_checkpoint_artifacts, load_checkpoint_model_only_transition, preflight_specialist_lineage_sources, write_checkpoint_artifacts
from parameter_counter import validate_realization_receipt
from model import RestartDecoderConfig, UnifiedDecoder
from pretrain import run_manifest_bound_semantic_segment, run_pretraining_segment
from parameter_counter import measure_parameter_counts
from semantic_stream import ManifestBoundTokenStream
from semantic_contract import semantic_model_contract_sha256
from optimizer_transition import validate_optimizer_transition_registry
from step2_realization_registry import validate_step2_realization_registry_bundle
from train import run_launch


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_sha256(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def bind_specialist_execution_slice(
    records: list[dict[str, object]], *, start_record: int, max_records: int,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    """Bind one exact contiguous execution slice without weakening full-corpus verification."""

    if type(start_record) is not int or start_record < 0 or start_record >= len(records):
        raise ValueError("specialist execution slice start record is outside the verified corpus")
    if type(max_records) is not int or max_records < 1:
        raise ValueError("specialist execution slice max records must be positive")
    if start_record + max_records > len(records):
        raise ValueError("specialist execution slice exceeds the verified corpus")
    selected = records[start_record:start_record + max_records]
    return selected, specialist_execution_slice_receipt(selected, source_start_record=start_record)


def specialist_execution_slice_receipt(
    records: list[dict[str, object]], *, source_start_record: int,
) -> dict[str, object]:
    """Content-address records executed since the immediate checkpoint parent."""

    if type(source_start_record) is not int or source_start_record < 0 or not records:
        raise ValueError("specialist execution slice selected no verified records")
    token_rows: list[list[int]] = []
    for record in records:
        token_ids = record.get("token_ids")
        if not isinstance(token_ids, list) or not token_ids or any(type(token) is not int or token < 0 for token in token_ids):
            raise ValueError("specialist execution slice requires nonempty nonnegative token_ids")
        token_rows.append(list(token_ids))
    canonical_records = json.dumps(records, sort_keys=True, separators=(",", ":")).encode("utf-8")
    canonical_tokens = json.dumps(token_rows, separators=(",", ":")).encode("utf-8")
    return {
        "schema_version": "ember-specialist-execution-slice-v1",
        "start_record": source_start_record,
        "record_count": len(records),
        "token_count": sum(len(row) for row in token_rows),
        "records_sha256": hashlib.sha256(canonical_records).hexdigest(),
        "tokens_sha256": hashlib.sha256(canonical_tokens).hexdigest(),
    }


def validate_specialist_execution_slice(
    execution_slice: dict[str, object], *, verified_record_count: int,
) -> None:
    fields = {"schema_version", "start_record", "record_count", "token_count", "records_sha256", "tokens_sha256"}
    if not isinstance(execution_slice, dict) or set(execution_slice) != fields:
        raise ValueError("specialist execution slice has an invalid shape")
    if execution_slice.get("schema_version") != "ember-specialist-execution-slice-v1":
        raise ValueError("specialist execution slice has an unsupported schema")
    if type(verified_record_count) is not int or verified_record_count < 1:
        raise ValueError("specialist execution slice requires a verified corpus size")
    start, count, tokens = execution_slice.get("start_record"), execution_slice.get("record_count"), execution_slice.get("token_count")
    if type(start) is not int or start < 0 or type(count) is not int or count < 1 or start + count > verified_record_count:
        raise ValueError("specialist execution slice exceeds the verified corpus")
    if type(tokens) is not int or tokens < 1:
        raise ValueError("specialist execution slice has no token evidence")
    for field in ("records_sha256", "tokens_sha256"):
        digest = execution_slice.get(field)
        if not isinstance(digest, str) or len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise ValueError(f"specialist execution slice has an invalid {field}")


def append_training_telemetry(path: Path, *, kind: str, payload: dict[str, object]) -> None:
    """Append one bounded, path-free cockpit event from the canonical trainer."""

    if kind not in {"run_status", "train_step", "checkpoint"}:
        raise ValueError("training telemetry kind is not authorized")
    if any("path" in key.lower() for key in payload):
        raise ValueError("training telemetry payload must not disclose filesystem paths")
    event = {
        "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "kind": kind,
        "source": "ember-restart-3b",
        "payload": payload,
    }
    encoded = json.dumps(event, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
    if len(encoded) > 4096:
        raise ValueError("training telemetry event exceeds the bounded channel contract")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab") as handle:
        handle.write(encoded)


def specialist_resume_cursor(cursor: dict[str, object], *, data_shard_id: str) -> dict[str, object]:
    """Preserve global accounting while starting a new verified specialist source at zero."""
    if not isinstance(data_shard_id, str) or not data_shard_id.startswith("VERIFIED_SPECIALIST:"):
        raise ValueError("specialist cursor requires a verified specialist source identity")
    global_step, tokens_seen = cursor.get("global_step"), cursor.get("tokens_seen")
    if type(global_step) is not int or global_step < 0 or type(tokens_seen) is not int or tokens_seen < 0:
        raise ValueError("resume cursor lacks nonnegative global counters")
    return {"shard": data_shard_id, "record_index": 0, "global_step": global_step, "tokens_seen": tokens_seen}


def resume_expert_genesis(manifest: dict[str, Any], *, requested_seed: int) -> dict[str, str]:
    """Carry verified parent genesis through resume; a new launch seed cannot rewrite lineage."""

    if not isinstance(requested_seed, int) or requested_seed < 0:
        raise ValueError("resume requested seed must be nonnegative")
    genesis = manifest.get("expert_genesis_sha256")
    expected = {"vision", "audio", "reasoning", "tool"}
    if not isinstance(genesis, dict) or set(genesis) != expected:
        raise ValueError("resume manifest lacks four verified expert genesis hashes")
    for name, digest in genesis.items():
        if not isinstance(digest, str) or len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise ValueError(f"resume manifest has malformed {name} genesis hash")
    return dict(genesis)

def production_memory_preflight(*, total_parameters: int, active_parameters: int, device_free_bytes: int) -> dict[str, int | str]:
    """Derive the exact BF16 episode envelope before CUDA model construction."""
    if min(total_parameters, active_parameters, device_free_bytes) <= 0 or active_parameters > total_parameters:
        raise ValueError("production memory preflight requires positive total/active/free byte values")
    parameter_bytes = total_parameters * 2
    gradient_bytes = active_parameters * 2
    optimizer_state_bytes = active_parameters * 2
    activation_reserve_bytes = 4 * 1024**3
    runtime_reserve_bytes = 2 * 1024**3
    required_bytes = parameter_bytes + gradient_bytes + optimizer_state_bytes + activation_reserve_bytes + runtime_reserve_bytes
    if required_bytes > device_free_bytes:
        raise MemoryError(f"BF16 production envelope requires {required_bytes} bytes but only {device_free_bytes} are free; refusing before allocation")
    return {
        "parameter_dtype": "bfloat16",
        "parameter_bytes": parameter_bytes,
        "gradient_bytes": gradient_bytes,
        "optimizer_state_bytes": optimizer_state_bytes,
        "activation_reserve_bytes": activation_reserve_bytes,
        "runtime_reserve_bytes": runtime_reserve_bytes,
        "required_bytes": required_bytes,
        "device_free_bytes": device_free_bytes,
    }
def checkpoint_serialization_byte_bound(config_path: Path, *, active_parameters: int | None = None) -> int:
    """Derive one publishable checkpoint bound from the frozen architecture and optimizer contract."""

    payload = json.loads(config_path.read_text(encoding="utf-8"))
    serialization = payload.get("checkpoints", {}).get("serialization")
    required = {"model_parameter_bytes", "optimizer_state_bytes_per_active_parameter", "format_overhead_bytes", "host_commit_reserve_gib"}
    if not isinstance(serialization, dict) or set(serialization) != required:
        raise ValueError("checkpoint serialization contract has an invalid shape")
    if any(type(serialization[field]) is not int or serialization[field] < 1 for field in required):
        raise ValueError("checkpoint serialization contract requires positive integer bounds")
    memory = load_memory_contract(config_path)
    if serialization["model_parameter_bytes"] != memory["parameter_bytes"] or serialization["optimizer_state_bytes_per_active_parameter"] != memory["optimizer_state_bytes_per_active_parameter"]:
        raise ValueError("checkpoint serialization contract drifts from the BF16 optimizer memory contract")
    config = RestartDecoderConfig.from_contract(config_path)
    specialist_parameters = config.layers * 12 * config.hidden_size * config.hidden_size
    shared_active_parameters = config.structural_parameter_count() - len(config.expert_names) * specialist_parameters
    selected_active_parameters = shared_active_parameters if active_parameters is None else active_parameters
    if type(selected_active_parameters) is not int or selected_active_parameters < shared_active_parameters or selected_active_parameters > config.structural_parameter_count():
        raise ValueError("checkpoint serialization active parameter count is outside the frozen architecture")
    return (
        config.structural_parameter_count() * serialization["model_parameter_bytes"]
        + selected_active_parameters * serialization["optimizer_state_bytes_per_active_parameter"]
        + serialization["format_overhead_bytes"]
    )


def checkpoint_host_commit_reserve_bytes(config_path: Path) -> int:
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    serialization = payload.get("checkpoints", {}).get("serialization")
    if not isinstance(serialization, dict):
        raise ValueError("checkpoint serialization contract has an invalid shape")
    reserve_gib = serialization.get("host_commit_reserve_gib")
    if type(reserve_gib) is not int or reserve_gib < 1:
        raise ValueError("checkpoint host commit reserve must be a positive integer GiB value")
    return reserve_gib * 1024**3


def semantic_publication_plan(*, steps: int, checkpoint_interval: int, checkpoint_byte_bound: int, write_budget_bytes: int, initial_global_step: int = 0) -> dict[str, int]:
    """Bound checkpoint publications using a frozen derived byte bound, never a caller estimate."""

    if (not isinstance(steps, int) or steps < 1 or not isinstance(checkpoint_interval, int) or checkpoint_interval < 1
            or not isinstance(checkpoint_byte_bound, int) or checkpoint_byte_bound < 1
            or not isinstance(write_budget_bytes, int) or write_budget_bytes < 1 or not isinstance(initial_global_step, int) or initial_global_step < 0):
        raise ValueError("semantic publication plan requires positive integer steps, interval, derived bound, and write budget")
    final_global_step = initial_global_step + steps
    periodic = sum(1 for step in range(initial_global_step + 1, final_global_step + 1) if step % checkpoint_interval == 0)
    publication_count = periodic + (0 if final_global_step % checkpoint_interval == 0 else 1)
    projected_write_bytes = publication_count * checkpoint_byte_bound
    if projected_write_bytes > write_budget_bytes:
        raise ValueError("semantic publication plan exceeds the declared write budget")
    return {"publication_count": publication_count, "checkpoint_byte_bound": checkpoint_byte_bound, "projected_write_bytes": projected_write_bytes}
def specialist_publication_plan(
    *, records: int, checkpoint_interval: int, checkpoint_byte_bound: int,
    write_budget_bytes: int, initial_global_step: int,
) -> dict[str, int]:
    """Bound every specialist publication, including the mandatory final bundle."""

    if (
        not isinstance(records, int) or records < 1
        or not isinstance(checkpoint_interval, int) or checkpoint_interval < 1
        or not isinstance(checkpoint_byte_bound, int) or checkpoint_byte_bound < 1
        or not isinstance(write_budget_bytes, int) or write_budget_bytes < 1
        or not isinstance(initial_global_step, int) or initial_global_step < 0
    ):
        raise ValueError("specialist publication plan requires positive integer records, interval, bound, budget, and global step")
    final_global_step = initial_global_step + records
    periodic = sum(
        1
        for step in range(initial_global_step + 1, final_global_step + 1)
        if step % checkpoint_interval == 0
    )
    publication_count = periodic + (0 if final_global_step % checkpoint_interval == 0 else 1)
    projected_write_bytes = publication_count * checkpoint_byte_bound
    if projected_write_bytes > write_budget_bytes:
        raise ValueError("specialist publication plan exceeds the declared write budget")
    return {
        "publication_count": publication_count,
        "checkpoint_byte_bound": checkpoint_byte_bound,
        "projected_write_bytes": projected_write_bytes,
    }

def _has_quarantine_component(path: Path) -> bool:
    return any(str(part).casefold() == ".checkpoint-quarantine" for part in Path(path).parts)


def _reject_quarantined_checkpoint_path(*paths: Path) -> None:
    if any(_has_quarantine_component(path) for path in paths):
        raise ValueError("quarantined checkpoint is not admitted or selectable")


def production_artifact_root(
    candidate: Path,
    *,
    c_relocated_under_disk_budget_runner: bool = False,
    relocation_custody_root: Path | None = None,
) -> Path:
    """Accept B: custody, or an explicit C: child of the disk-runner custody root."""

    if type(c_relocated_under_disk_budget_runner) is not bool:
        raise ValueError("C relocation custody flag must be boolean")
    lexical = Path(candidate)
    resolved = lexical.resolve()
    _reject_quarantined_checkpoint_path(lexical, resolved)
    if c_relocated_under_disk_budget_runner:
        if not isinstance(relocation_custody_root, Path):
            raise ValueError("runner-bound C relocation requires an explicit custody root")
        custody = relocation_custody_root.resolve()
        if custody.drive.upper() != "C:" or resolved.drive.upper() != "C:" or not resolved.is_relative_to(custody):
            raise ValueError("runner-bound C relocation requires a C: custody root containing the artifact root")
        return resolved
    if relocation_custody_root is not None:
        raise ValueError("relocation custody root requires runner-bound C relocation")
    if resolved.drive.upper() != "B:":
        raise ValueError("production artifact root must be an explicit B: path unless runner-bound C relocation is declared")
    return resolved


def _bundle_serialized_bytes(bundle: Path) -> int:
    """Measure exactly the bytes currently published beneath one bundle root."""
    return sum(path.stat().st_size for path in bundle.rglob("*") if path.is_file())

def _custody_link_or_reparse(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError as error:
        raise RuntimeError(f"custody byte accounting could not inspect {path}") from error
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def _lexical_nonreparse_directory(path: Path) -> Path:
    """Return an absolute lexical directory only after inspecting every component."""

    lexical = Path(os.path.abspath(str(path)))
    parts = lexical.parts
    current = Path(parts[0]) if parts else lexical
    for part in parts[1:]:
        current = current / part
        if _custody_link_or_reparse(current):
            raise ValueError("checkpoint quarantine source contains a link or reparse component")
    if _custody_link_or_reparse(lexical):
        raise ValueError("checkpoint quarantine source contains a link or reparse component")
    if not lexical.is_dir():
        raise ValueError("checkpoint quarantine source must be a directory")
    return lexical


def _file_identity(path: Path) -> tuple[int, int] | str:
    stat = path.stat()
    inode = int(getattr(stat, "st_ino", 0))
    if inode:
        return (int(getattr(stat, "st_dev", 0)), inode)
    return str(path.resolve())

def _custody_file_rows(parent: Path) -> list[dict[str, object]]:
    """Snapshot every physical custody file once and classify its root bucket."""

    parent = parent.resolve()
    seen: set[tuple[int, int] | str] = set()
    rows: list[dict[str, object]] = []
    for path in parent.rglob("*"):
        try:
            if _custody_link_or_reparse(path):
                raise RuntimeError(f"custody accounting encountered a symlink or reparse point: {path}")
            if not path.is_file():
                continue
            identity = _file_identity(path)
            if identity in seen:
                continue
            seen.add(identity)
            relative = path.relative_to(parent)
            top = relative.parts[0] if relative.parts else ""
            bucket = "quarantine" if top == ".checkpoint-quarantine" else "live" if top.startswith("checkpoint-") else "evidence" if top == _CUSTODY_LEDGER else "other"
            rows.append({"path": relative.as_posix(), "bucket": bucket, "bytes": path.stat().st_size})
        except OSError as error:
            raise RuntimeError(f"custody byte accounting could not inspect {path}") from error
    return rows


def _custody_serialized_bytes(parent: Path) -> int:
    """Charge all custody bytes with a unique-inode walk."""

    return sum(int(row["bytes"]) for row in _custody_file_rows(parent))


def _custody_reconciliation(parent: Path) -> dict[str, object]:
    """Reconcile custody bytes with an ordered, fail-closed deletion ledger."""

    parent = parent.resolve()
    rows = _custody_file_rows(parent)
    totals = {"live": 0, "quarantine": 0, "evidence": 0, "other": 0}
    for row in rows:
        totals[str(row["bucket"])] += int(row["bytes"])
    ledger = parent / _CUSTODY_LEDGER
    transitions: dict[str, dict[str, object]] = {}
    legacy_deleted: dict[str, dict[str, object]] = {}
    if ledger.exists():
        try:
            lines = ledger.read_bytes().splitlines()
        except OSError as error:
            raise RuntimeError("custody deletion ledger could not be read") from error
        for line in lines:
            try:
                event = json.loads(line)
            except (UnicodeError, json.JSONDecodeError) as error:
                raise RuntimeError("custody deletion ledger is malformed") from error
            if not isinstance(event, dict):
                raise RuntimeError("custody deletion ledger has an invalid schema")
            schema = event.get("schema_version")
            kind = event.get("event")
            pointer = event.get("pointer")
            if schema not in {_CUSTODY_LEDGER_SCHEMA, _LEGACY_CUSTODY_LEDGER_SCHEMA}:
                raise RuntimeError("custody deletion ledger has an invalid schema")
            if not isinstance(pointer, str) or not pointer or Path(pointer).is_absolute() or ".." in Path(pointer).parts:
                raise RuntimeError("custody deletion ledger lacks a safe pointer")
            if type(event.get("bytes")) is not int or event["bytes"] < 0 or not _is_sha256(event.get("sha256")):
                raise RuntimeError("custody deletion ledger has invalid byte evidence")
            if not isinstance(event.get("reason"), str) or not event["reason"]:
                raise RuntimeError("custody deletion ledger lacks a deletion reason")
            identity = {
                "schema_version": schema,
                "pointer": pointer,
                "bytes": event["bytes"],
                "sha256": event["sha256"],
                "reason": event["reason"],
            }
            if schema == _LEGACY_CUSTODY_LEDGER_SCHEMA:
                if kind != "DELETED":
                    raise RuntimeError("legacy custody deletion ledger permits only DELETED")
                if pointer in transitions or pointer in legacy_deleted:
                    raise RuntimeError("custody deletion ledger has a duplicate legacy deletion")
                legacy_deleted[pointer] = identity
                continue
            if kind not in {"PREPARED", "COMMITTED"}:
                raise RuntimeError("custody deletion ledger has an invalid event")
            if pointer in legacy_deleted:
                raise RuntimeError("custody deletion ledger mixes legacy and ordered events")
            prior = transitions.get(pointer)
            if prior is None:
                if kind != "PREPARED":
                    raise RuntimeError("custody deletion ledger has COMMITTED without PREPARED")
                transitions[pointer] = {**identity, "state": "PREPARED"}
                continue
            if any(prior[field] != identity[field] for field in ("schema_version", "pointer", "bytes", "sha256", "reason")):
                raise RuntimeError("custody deletion ledger changes a prepared pointer identity")
            if prior["state"] != "PREPARED" or kind != "COMMITTED":
                raise RuntimeError("custody deletion ledger has a duplicate or reversed transition")
            prior["state"] = "COMMITTED"
    deleted_bytes = 0
    for pointer, record in transitions.items():
        deleted_path = parent / pointer
        if deleted_path.exists():
            if record["state"] == "COMMITTED":
                raise RuntimeError("custody deletion ledger claims deletion while bytes still exist")
            continue
        # PREPARED+missing is an interruption-safe inferred deletion; count once.
        deleted_bytes += int(record["bytes"])
    for pointer, record in legacy_deleted.items():
        if (parent / pointer).exists():
            raise RuntimeError("legacy custody deletion claims deletion while bytes still exist")
        deleted_bytes += int(record["bytes"])
    physical_bytes = sum(int(row["bytes"]) for row in rows)
    return {
        "schema_version": "ember-checkpoint-custody-reconciliation-v1",
        "live_bytes": totals["live"],
        "quarantine_bytes": totals["quarantine"],
        "evidence_bytes": totals["evidence"],
        "other_bytes": totals["other"],
        "physical_bytes": physical_bytes,
        "deleted_bytes": deleted_bytes,
        "reconciled_bytes": physical_bytes + deleted_bytes,
        "file_count": len(rows),
    }

def _receipt_valid_for_retention(bundle: Path) -> bool:
    try:
        require_counter_success_receipt(bundle)
    except (OSError, ValueError, TypeError):
        return False
    return True

_WRITER_LEASE = ".writer-lease.json"
_MAX_QUARANTINE_FILES = 32
_MAX_QUARANTINE_BYTES = 1024 * 1024
_CUSTODY_LEDGER = ".checkpoint-custody-deletion-ledger.jsonl"
_LEGACY_CUSTODY_LEDGER_SCHEMA = "ember-checkpoint-custody-deletion-v1"
_CUSTODY_LEDGER_SCHEMA = "ember-checkpoint-custody-deletion-v2"


def _pid_is_alive(pid: object) -> bool:
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False
    if os.name == "nt":
        # ``os.kill(pid, 0)`` is not a harmless existence probe on Windows.
        # Query the process object without signalling it instead.
        import ctypes

        process_query_limited_information = 0x1000
        still_active = 259
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return False
            return exit_code.value == still_active
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _staging_writer_pid(path: Path) -> int | None:
    if not path.name.startswith(".") or not path.name.endswith(".staging"):
        return None
    parts = path.name.rsplit(".", 3)
    if len(parts) != 4 or parts[-1] != "staging":
        return None
    try:
        pid = int(parts[-3])
    except ValueError:
        return None
    return pid if pid > 0 else None


def _writer_is_active(root: Path) -> bool:
    staging_pid = _staging_writer_pid(root)
    if staging_pid is not None:
        return _pid_is_alive(staging_pid)
    try:
        lease, _ = _json_snapshot(root / _WRITER_LEASE, label="writer lease")
    except (OSError, ValueError):
        return False
    return _pid_is_alive(lease.get("pid"))


def _write_bounded_quarantine_evidence(parent: Path, name: str, payload: dict[str, object]) -> Path:
    evidence_dir = parent / ".checkpoint-quarantine"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    payload_bytes = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    digest = hashlib.sha256(payload_bytes).hexdigest()
    ledger = parent / _CUSTODY_LEDGER

    def ledger_events(pointer_path: Path) -> set[str]:
        if not ledger.exists():
            return set()
        pointer = pointer_path.relative_to(parent).as_posix()
        events: set[str] = set()
        try:
            for line in ledger.read_bytes().splitlines():
                event = json.loads(line)
                if event.get("pointer") == pointer:
                    events.add(str(event.get("event")))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise RuntimeError("custody deletion ledger could not be inspected") from error
        return events

    terminal_events = {"PREPARED", "COMMITTED", "DELETED"}
    base_path = evidence_dir / f"{name}-{digest}.json"
    evidence_path = base_path
    base_events = ledger_events(base_path)
    if base_path.exists():
        if base_events & terminal_events:
            raise RuntimeError("historical quarantine evidence pointer reappeared")
        if base_path.read_bytes() != payload_bytes:
            raise RuntimeError("quarantine evidence collision is not content-addressed")
    elif base_events & terminal_events:
        generation = 1
        while True:
            candidate = evidence_dir / f"{name}-{digest}-g{generation}.json"
            candidate_events = ledger_events(candidate)
            if candidate.exists():
                if candidate_events & terminal_events:
                    raise RuntimeError("historical quarantine evidence pointer reappeared")
                if candidate.read_bytes() != payload_bytes:
                    raise RuntimeError("quarantine evidence collision is not content-addressed")
                evidence_path = candidate
                break
            if candidate_events & terminal_events:
                generation += 1
                continue
            evidence_path = candidate
            break

    if not evidence_path.exists():
        try:
            with evidence_path.open("xb") as handle:
                handle.write(payload_bytes)
                handle.flush()
                os.fsync(handle.fileno())
        except FileExistsError:
            if ledger_events(evidence_path) & terminal_events:
                raise RuntimeError("historical quarantine evidence pointer reappeared")
            if evidence_path.read_bytes() != payload_bytes:
                raise RuntimeError("quarantine evidence appeared with different bytes")
    files = sorted(
        (path for path in evidence_dir.glob("*.json") if path.is_file()),
        key=lambda path: (path.stat().st_mtime_ns, path.name),
    )
    while len(files) > _MAX_QUARANTINE_FILES or sum(path.stat().st_size for path in files) > _MAX_QUARANTINE_BYTES:
        victim = next((path for path in files if path != evidence_path), None)
        if victim is None:
            break
        ledger = parent / _CUSTODY_LEDGER
        deletion = {
            "schema_version": _CUSTODY_LEDGER_SCHEMA,
            "pointer": victim.relative_to(parent).as_posix(),
            "bytes": victim.stat().st_size,
            "sha256": _sha256(victim),
            "reason": "bounded evidence retention",
        }
        prepared = {**deletion, "event": "PREPARED"}
        with ledger.open("ab") as handle:
            handle.write((json.dumps(prepared, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        try:
            victim.unlink()
        except OSError as error:
            raise RuntimeError("bounded evidence deletion did not commit; bytes preserved") from error
        committed = {**deletion, "event": "COMMITTED"}
        with ledger.open("ab") as handle:
            handle.write((json.dumps(committed, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        files.remove(victim)
    return evidence_path


def _move_bundle_to_quarantine(bundle: Path, *, prefix: str = "candidate") -> Path:
    """Atomically preserve serialized bytes in the nonselectable quarantine namespace."""

    lexical = _lexical_nonreparse_directory(bundle)
    source = lexical.resolve(strict=True)
    if not source.is_dir():
        raise ValueError("checkpoint quarantine source must be a directory")
    quarantine = source.parent / ".checkpoint-quarantine"
    if quarantine.exists() and _custody_link_or_reparse(quarantine):
        raise ValueError("checkpoint quarantine target contains a link or reparse component")
    quarantine.mkdir(parents=True, exist_ok=True)
    if _custody_link_or_reparse(quarantine):
        raise ValueError("checkpoint quarantine target contains a link or reparse component")
    candidate = quarantine / f"{prefix}-{source.name}-{uuid.uuid4().hex[:16]}"
    _atomic_publish_no_replace(source, candidate)
    return candidate


def _quarantine_unverified_bundle(bundle: Path, *, reason: str) -> None:
    """Preserve an unselectable checkpoint for rejudging; only bounded JSON is prunable."""

    if not bundle.is_dir() or not bundle.name.startswith("checkpoint-"):
        raise ValueError("retention quarantine requires a checkpoint-* directory")
    manifest = bundle / "checkpoint-manifest.json"
    try:
        manifest_sha256 = _sha256(manifest) if manifest.is_file() else None
    except OSError as error:
        manifest_sha256 = None
        reason = f"{reason}; manifest_hash_error={type(error).__name__}"
    candidate = _move_bundle_to_quarantine(bundle)
    evidence = {
        "schema_version": "ember-checkpoint-quarantine-v1",
        "result": "UNSELECTABLE",
        "source_bundle": bundle.name,
        "quarantine_candidate": candidate.name,
        "reason": reason[:512],
        "manifest_sha256": manifest_sha256,
        "bulk_candidate_cleanup": "moved_to_quarantine",
    }
    _write_bounded_quarantine_evidence(candidate.parent.parent, bundle.name, evidence)


def _reclaim_stale_staging(parent: Path) -> None:
    for staging in list(parent.glob(".*.staging")):
        if not staging.is_dir() or _writer_is_active(staging):
            continue
        manifest = staging / "checkpoint-manifest.json"
        try:
            manifest_sha256 = _sha256(manifest) if manifest.is_file() else None
        except OSError:
            manifest_sha256 = None
        evidence_name = f"staging-{hashlib.sha256(staging.name.encode()).hexdigest()[:16]}"
        candidate = _move_bundle_to_quarantine(staging, prefix="candidate")
        _write_bounded_quarantine_evidence(parent, evidence_name, {
            "schema_version": "ember-staging-failure-v1",
            "result": "UNSELECTABLE",
            "source_bundle": staging.name,
            "quarantine_candidate": candidate.name,
            "manifest_sha256": manifest_sha256,
            "bulk_candidate_cleanup": "moved_to_quarantine",
        })


def _reclaim_unverified_orphans(parent: Path) -> None:
    for candidate in list(parent.iterdir()):
        if not candidate.is_dir() or not candidate.name.startswith("checkpoint-") or _writer_is_active(candidate):
            continue
        try:
            require_counter_success_receipt(candidate)
        except (OSError, ValueError, TypeError) as error:
            _quarantine_unverified_bundle(
                candidate,
                reason=f"counter receipt invalid: {type(error).__name__}: {error}",
            )
def _enforce_retention(parent: Path, *, max_count: int | None = None, max_serialized_bytes: int | None = None, receipt_aware: bool = False) -> None:
    """Prune only older successful bundles; never delete the final known-good bundle."""
    if max_count is None and max_serialized_bytes is None:
        raise ValueError("checkpoint retention requires a count or serialized-byte budget")
    if max_count is not None and max_count < 1:
        raise ValueError("checkpoint retention count must retain at least one bundle")
    if max_serialized_bytes is not None and max_serialized_bytes < 1:
        raise ValueError("checkpoint retention serialized-byte budget must be positive")
    parent.mkdir(parents=True, exist_ok=True)
    if receipt_aware:
        _reclaim_stale_staging(parent)
    candidates = [path for path in parent.iterdir() if path.is_dir() and path.name.startswith("checkpoint-")]
    bundles: list[Path] = []
    for candidate in candidates:
        if not receipt_aware:
            bundles.append(candidate)
            continue
        if _writer_is_active(candidate):
            continue
        try:
            require_counter_success_receipt(candidate)
        except (OSError, ValueError, TypeError) as error:
            _quarantine_unverified_bundle(candidate, reason=f"counter receipt invalid: {type(error).__name__}: {error}")
        else:
            bundles.append(candidate)
    bundles.sort(key=lambda path: (path.stat().st_mtime_ns, path.name))
    if max_count is not None and len(bundles) > max_count:
        raise RuntimeError("selectable checkpoint count cannot be reduced without evidence-qualified deletion")
    if max_serialized_bytes is not None:
        total = int(_custody_reconciliation(parent)["reconciled_bytes"])
        while total > max_serialized_bytes and len(bundles) > 1:
            _move_bundle_to_quarantine(bundles.pop(0))
            total = int(_custody_reconciliation(parent)["reconciled_bytes"])
        if total > max_serialized_bytes:
            raise RuntimeError("checkpoint custody exceeds serialized-byte retention budget; quarantined bytes remain charged")


def _retain_after_success(
    parent: Path, *, operation: Callable[[], Any], max_count: int | None = None, max_serialized_bytes: int | None = None, receipt_aware: bool = False
) -> Any:
    """Publish first, then prune only successful older bundles."""

    if max_count is None and max_serialized_bytes is None:
        raise ValueError("successful checkpoint retention requires a bound")
    parent.mkdir(parents=True, exist_ok=True)
    if receipt_aware:
        _reclaim_stale_staging(parent)
        _reclaim_unverified_orphans(parent)
    result = operation()
    _enforce_retention(parent, max_count=max_count, max_serialized_bytes=max_serialized_bytes, receipt_aware=receipt_aware)
    return result


def load_verified_specialist_records(
    *, root: Path, data_manifest: Path, tokenizer_path: Path, capability: str,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    """Execute the independent manifest verifier and admit one routed expert family."""

    expert_for_capability = {"image": "vision", "audio": "audio", "reasoning": "reasoning", "tool": "tool"}
    if capability not in expert_for_capability:
        raise ValueError("specialist capability must be image, audio, reasoning, or tool")
    root = root.resolve()
    manifest = data_manifest.resolve()
    if root not in manifest.parents:
        raise ValueError("specialist data manifest must reside in the selected worktree")
    verifier = Path(__file__).with_name("verify_training_data.py")
    completed = subprocess.run(
        [sys.executable, "-I", "-c", "import runpy,sys;sys.path[:0]=[sys.argv[1],sys.argv[2]];sys.argv=sys.argv[3:];runpy.run_path(sys.argv[0],run_name=\"__main__\")", str(verifier.parent.resolve()), str(Path(tokenizers.__file__).resolve().parent.parent), str(verifier), "--data-manifest", str(manifest), "--tokenizer", str(tokenizer_path), "--capability", capability],
        cwd=root, env={name: os.environ[name] for name in ("SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP", "TMP") if name in os.environ}, text=True, capture_output=True, check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"specialist data verifier failed: {completed.stderr.strip() or completed.stdout.strip()}")
    try:
        verification = json.loads(completed.stdout)
        manifest_bytes = manifest.read_bytes()
        payload = json.loads(manifest_bytes)
    except json.JSONDecodeError as error:
        raise RuntimeError("specialist data verifier or manifest did not emit JSON") from error
    if not isinstance(verification, dict) or verification.get("result") != "VERIFIED" or verification.get("capability") != capability:
        raise RuntimeError("specialist data verifier did not produce the required verified receipt")
    if verification.get("generator_replay_verified") is not True:
        raise RuntimeError("specialist data verifier did not prove canonical generator replay")
    semantic_hash = verification.get("semantic_model_contract_sha256")
    if verification.get("admission") != "ADMISSIBLE_SEMANTIC_CONTRACT" or not isinstance(semantic_hash, str) or len(semantic_hash) != 64 or semantic_hash.lower() != semantic_hash:
        raise RuntimeError("specialist data verifier did not bind an admissible semantic model contract")
    runtime_config_path = root / "configs" / "ember-restart-3b.json"
    try:
        runtime_semantic_hash = semantic_model_contract_sha256(
            json.loads(runtime_config_path.read_bytes())
        )
    except (OSError, json.JSONDecodeError, ValueError) as error:
        raise RuntimeError("runtime model config cannot establish its semantic contract") from error
    if semantic_hash != runtime_semantic_hash:
        raise RuntimeError("specialist data semantic contract does not match the runtime model contract")
    verification["runtime_semantic_model_contract_sha256"] = runtime_semantic_hash
    if verification.get("data_manifest_sha256") != hashlib.sha256(manifest_bytes).hexdigest():
        raise RuntimeError("verified specialist data manifest changed after verification")

    def reread_bound_artifact(reference: object, *, receipt_field: str, label: str) -> tuple[Path, bytes]:
        relative = reference.get("path") if isinstance(reference, dict) else None
        if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
            raise RuntimeError(f"verified specialist manifest lacks a {label} artifact path")
        path = (root / relative).resolve()
        if root not in path.parents or not path.is_file():
            raise RuntimeError(f"verified specialist {label} artifact path escapes the worktree")
        artifact_bytes = path.read_bytes()
        if verification.get(receipt_field) != hashlib.sha256(artifact_bytes).hexdigest():
            raise RuntimeError(f"verified specialist {label} artifact changed after verification")
        return path, artifact_bytes

    reread_bound_artifact(payload.get("source_manifest") if isinstance(payload, dict) else None, receipt_field="source_manifest_sha256", label="source manifest")
    _records_path, records_bytes = reread_bound_artifact(payload.get("records_artifact") if isinstance(payload, dict) else None, receipt_field="records_artifact_sha256", label="records")
    records_payload = json.loads(records_bytes)
    records = records_payload.get("records") if isinstance(records_payload, dict) else None
    if not isinstance(records, list) or not records or any(not isinstance(record, dict) for record in records):
        raise RuntimeError("verified specialist records artifact is malformed")
    if {record.get("active_expert") for record in records} != {expert_for_capability[capability]}:
        raise RuntimeError("verified specialist records do not contain exactly the requested route")
    return records, verification

def load_authorized_records(root: Path) -> tuple[list[dict[str, object]], dict[str, object], dict[str, object]]:
    """Consume #812 identity before reading the exact owned four-domain bytes."""

    packet, validation, input_receipt = run_launch(repo_root=root)
    if validation["decision"] != "ACCEPTED":
        raise RuntimeError("input launch gate did not accept the selected shard")
    identity = packet.get("input_identity")
    if not isinstance(identity, dict):
        raise RuntimeError("accepted launch packet lacks a concrete input identity")
    if identity.get("artifact_id") == "owned-clean-curriculum-128-v1" or identity.get("shard_path") == "data/ember-restart-3b/owned-curriculum-128.json":
        raise RuntimeError("retired bootstrap curriculum is mechanics-only evidence and cannot drive production training")
    shard = root / str(packet["input_identity"]["shard_path"])
    payload = json.loads(shard.read_text(encoding="utf-8"))
    records = payload.get("records") if isinstance(payload, dict) else None
    if payload.get("schema_version") != "ember-owned-pretraining-shard-v1" or not isinstance(records, list) or not records:
        raise RuntimeError("production slice requires a nonempty owned four-domain shard")
    if {record.get("active_expert") for record in records if isinstance(record, dict)} != {"vision", "audio", "reasoning", "tool"}:
        raise RuntimeError("production slice requires one record for every declared expert")
    return records, packet, input_receipt


_COUNTER_SUCCESS_RECEIPT = "parameter-counter-receipt.json"
_COUNTER_FAILURE_RECEIPT = "counter-failure.json"
_COUNTER_COUNT_FIELDS = (
    "allocated_parameters",
    "unique_parameters",
    "trainable_parameters",
    "served_parameters",
    "active_parameters",
    "episode_trainable_parameters",
)


def _atomic_bytes(path: Path, payload: bytes) -> None:
    """Publish small custody evidence only after complete bytes are durable."""

    temporary = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
    try:
        with temporary.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _atomic_json(path: Path, payload: dict[str, object]) -> None:
    _atomic_bytes(path, (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"))


def _json_snapshot(path: Path, *, label: str) -> tuple[dict[str, object], str]:
    try:
        payload = path.read_bytes()
        parsed = json.loads(payload)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} is not valid JSON") from error
    if not isinstance(parsed, dict):
        raise ValueError(f"{label} must be a JSON object")
    return parsed, hashlib.sha256(payload).hexdigest()


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def require_counter_success_receipt(checkpoint_root: Path, *, receipt_path: Path | None = None) -> dict[str, object]:
    """Make resumability contingent on the exact successful realization counter output."""
    checkpoint_root = checkpoint_root.resolve()
    manifest, manifest_sha256 = _json_snapshot(checkpoint_root / "checkpoint-manifest.json", label="checkpoint manifest")
    receipt_source = (receipt_path if receipt_path is not None else checkpoint_root / _COUNTER_SUCCESS_RECEIPT).resolve()
    receipt, _receipt_sha256 = _json_snapshot(receipt_source, label="counter-success receipt")
    validated = validate_realization_receipt(receipt)
    architecture = manifest.get("architecture")
    expected = {
        "model_config_sha256": manifest.get("model_config_sha256"),
        "subject_checkpoint_sha256": manifest_sha256,
        "architecture_revision": manifest.get("architecture_revision"),
        "counter_sha256": _sha256(Path(__file__).with_name("parameter_counter.py")),
        "active_expert_ids": manifest.get("active_expert_ids"),
        "expert_genesis_sha256": manifest.get("expert_genesis_sha256"),
        "expert_parameter_sha256": manifest.get("expert_parameter_sha256"),
    }
    if not isinstance(architecture, dict):
        raise ValueError("counter-success receipt does not reproduce checkpoint capacity")
    expected.update({field: architecture.get(field) for field in _COUNTER_COUNT_FIELDS})
    if any(validated.get(field) != value for field, value in expected.items()):
        raise ValueError("counter-success receipt does not bind this checkpoint realization")
    return validated


def _quarantine_counter_failed_checkpoint(checkpoint_target: Path, error: BaseException) -> Path | None:
    """Preserve a counter-failed candidate as durable, nonselectable raw bytes."""

    if not checkpoint_target.exists():
        return None
    manifest_path = checkpoint_target / "checkpoint-manifest.json"
    manifest_sha256: str | None = None
    try:
        if manifest_path.is_file():
            manifest_sha256 = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    except OSError:
        manifest_sha256 = None
    candidate = _move_bundle_to_quarantine(checkpoint_target, prefix="candidate")
    evidence = _write_bounded_quarantine_evidence(
        candidate.parent.parent,
        f"counter-failed-{checkpoint_target.name}-{candidate.name.rsplit('-', 1)[-1]}",
        {
            "schema_version": "ember-counter-failure-v1",
            "result": "COUNTER_FAILED",
            "source_bundle": checkpoint_target.name,
            "quarantine_candidate": candidate.name,
            "checkpoint_manifest_sha256": manifest_sha256,
            "error_type": type(error).__name__,
            "error": str(error)[:512],
            "bulk_candidate_cleanup": "moved_to_quarantine",
        },
    )
    return evidence


def authorize_production_resume_checkpoint(
    candidate: Path,
    *,
    counter_success_receipt: Path | None = None,
    realization_registry: Path | None = None,
    optimizer_transition_registry: Path | None = None,
    optimizer_transition_registry_sha256: str | None = None,
    c_relocated_under_disk_budget_runner: bool = False,
    relocation_custody_root: Path | None = None,
) -> tuple[Path, dict[str, object]]:
    """Authorize a resume and disclose the exact verifier trust path used."""

    lexical = Path(candidate)
    resolved = lexical.resolve()
    _reject_quarantined_checkpoint_path(lexical, resolved)
    accepted = resolved.drive.upper() == "B:" and resolved.is_dir()
    if not accepted and c_relocated_under_disk_budget_runner:
        resolved = production_artifact_root(
            resolved,
            c_relocated_under_disk_budget_runner=True,
            relocation_custody_root=relocation_custody_root,
        )
        accepted = resolved.is_dir()
    if not accepted:
        raise ValueError("resume checkpoint must be a published B: bundle or declared C: custody bundle")
    authorities = (counter_success_receipt, realization_registry, optimizer_transition_registry)
    if sum(value is not None for value in authorities) > 1:
        raise ValueError("resume authority inputs are mutually exclusive")
    if optimizer_transition_registry is not None:
        if optimizer_transition_registry_sha256 is None:
            raise ValueError("optimizer transition requires an expected registry SHA-256")
        if (
            len(optimizer_transition_registry_sha256) != 64
            or any(character not in "0123456789abcdef" for character in optimizer_transition_registry_sha256)
        ):
            raise ValueError("expected optimizer transition registry SHA-256 is invalid")
        actual_registry_sha256 = _sha256(optimizer_transition_registry.resolve())
        if actual_registry_sha256 != optimizer_transition_registry_sha256:
            raise ValueError("optimizer transition registry SHA-256 mismatch")
        current_model_config = Path(__file__).resolve().parents[2] / "configs" / "ember-restart-3b.json"
        transition = validate_optimizer_transition_registry(
            optimizer_transition_registry.resolve(),
            checkpoint_root=resolved,
            current_target_config_path=current_model_config,
        )
        authority = {
            "schema_version": "ember-resume-authority-v1",
            "mode": "MODEL_ONLY_OPTIMIZER_CONTRACT_TRANSITION",
            "checkpoint_manifest_sha256": transition["source"]["checkpoint_manifest_sha256"],
            "transition_registry_sha256": transition["registry_sha256"],
            "transition_receipt_sha256": transition["receipt_sha256"],
            "source_semantic_model_contract_sha256": transition["source"]["semantic_model_contract_sha256"],
            "target_model_config_sha256": transition["target"]["model_config_sha256"],
            "target_semantic_model_contract_sha256": transition["target"]["semantic_model_contract_sha256"],
            "model_state_reused": True,
            "optimizer_state_reused": False,
        }
        if authority["transition_registry_sha256"] != optimizer_transition_registry_sha256:
            raise ValueError("optimizer transition validator registry SHA-256 mismatch")
    elif optimizer_transition_registry_sha256 is not None:
        raise ValueError("expected optimizer transition registry SHA-256 requires its registry path")
    elif realization_registry is not None:
        current_model_config = Path(__file__).resolve().parents[2] / "configs" / "ember-restart-3b.json"
        receipt = validate_step2_realization_registry_bundle(
            realization_registry.resolve(),
            (resolved / "checkpoint-manifest.json").resolve(),
            current_model_config,
        )
        authority = {
            "schema_version": "ember-resume-authority-v1",
            "mode": "TRUSTED_HISTORICAL_REALIZATION_REGISTRY",
            "checkpoint_manifest_sha256": _sha256(resolved / "checkpoint-manifest.json"),
            "registry_sha256": _sha256(realization_registry.resolve()),
            "counter_sha256": receipt["counter_sha256"],
            "receipt_sha256": receipt["receipt_sha256"],
            "historical_model_config_sha256": receipt["historical_model_config_sha256"],
            "current_model_config_sha256": receipt["current_model_config_sha256"],
            "semantic_model_contract_sha256": receipt["semantic_model_contract_sha256"],
        }
    else:
        receipt = require_counter_success_receipt(resolved, receipt_path=counter_success_receipt)
        receipt_source = (counter_success_receipt if counter_success_receipt is not None else resolved / _COUNTER_SUCCESS_RECEIPT).resolve()
        authority = {
            "schema_version": "ember-resume-authority-v1",
            "mode": "CURRENT_COUNTER_SUCCESS_RECEIPT",
            "checkpoint_manifest_sha256": _sha256(resolved / "checkpoint-manifest.json"),
            "counter_sha256": receipt["counter_sha256"],
            "receipt_sha256": _sha256(receipt_source),
        }
    return resolved, authority


def production_resume_checkpoint(
    candidate: Path,
    *,
    counter_success_receipt: Path | None = None,
    realization_registry: Path | None = None,
    optimizer_transition_registry: Path | None = None,
    optimizer_transition_registry_sha256: str | None = None,
    c_relocated_under_disk_budget_runner: bool = False,
    relocation_custody_root: Path | None = None,
) -> Path:
    """Backward-compatible path-only wrapper around disclosed resume authority."""

    resolved, _authority = authorize_production_resume_checkpoint(
        candidate,
        counter_success_receipt=counter_success_receipt,
        realization_registry=realization_registry,
        optimizer_transition_registry=optimizer_transition_registry,
        optimizer_transition_registry_sha256=optimizer_transition_registry_sha256,
        c_relocated_under_disk_budget_runner=c_relocated_under_disk_budget_runner,
        relocation_custody_root=relocation_custody_root,
    )
    return resolved


def restore_authorized_checkpoint(
    model: UnifiedDecoder,
    optimizer: torch.optim.Optimizer,
    checkpoint: Path,
    receipt: Mapping[str, Any],
    authority: Mapping[str, Any],
) -> dict[str, Any]:
    """Restore model/replay state while enforcing explicit optimizer-state disposition."""

    if authority.get("mode") == "MODEL_ONLY_OPTIMIZER_CONTRACT_TRANSITION":
        return load_checkpoint_model_only_transition(model, checkpoint, receipt)
    return load_checkpoint_artifacts(model, optimizer, checkpoint, receipt)

def checkpoint_retention_budget_bytes(config_path: Path) -> int:
    """Load the measured serialized-byte ceiling for published checkpoint bundles."""
    try:
        retention = json.loads(config_path.read_text(encoding="utf-8"))["checkpoints"]["retention"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise ValueError("production contract must declare checkpoint retention") from error
    gib = retention.get("max_serialized_gib") if isinstance(retention, dict) else None
    if not isinstance(gib, int) or gib < 1 or retention.get("preserve_last_known_good") is not True:
        raise ValueError("checkpoint retention must declare a positive serialized-byte budget and preserve the last good bundle")
    return gib * 1024**3

def checkpoint_retention_limit(config_path: Path) -> int:
    """Read the contract retention policy instead of maintaining a runner-local copy."""

    try:
        value = json.loads(config_path.read_text(encoding="utf-8"))["checkpoints"]["retention"]["max_count"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise ValueError("production contract must declare checkpoint retention") from error
    if not isinstance(value, int) or value < 1:
        raise ValueError("checkpoint retention max_count must be a positive integer")
    return value


def load_memory_contract(config_path: Path) -> dict[str, object]:
    """Load the numerics declaration that must agree with the allocation preflight."""
    try:
        value = json.loads(config_path.read_text(encoding="utf-8"))["training"]["memory"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise ValueError("production contract must declare BF16 memory numerics") from error
    expected = {
        "parameter_dtype": "bfloat16",
        "parameter_bytes": 2,
        "gradient_bytes_per_active_parameter": 2,
        "optimizer_state_bytes_per_active_parameter": 2,
        "activation_reserve_gib": 4,
        "runtime_reserve_gib": 2,
    }
    if value != expected:
        raise ValueError("production BF16 memory contract differs from the audited numerical envelope")
    return dict(value)

def load_optimizer_contract(config_path: Path) -> dict[str, object]:
    """Load the one structured optimizer declaration used by config, runtime, and checkpoint."""

    try:
        contract = json.loads(config_path.read_text(encoding="utf-8"))["training"]["optimizer"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise ValueError("production contract must declare a structured optimizer") from error
    return validate_optimizer_contract(contract)


def validate_optimizer_contract(contract: object) -> dict[str, object]:
    """Validate an optimizer object taken from an already verified config snapshot."""

    if not isinstance(contract, dict) or set(contract) != {"name", "implementation", "placement", "hyperparameters", "state_format"}:
        raise ValueError("production optimizer contract has an invalid shape")
    expected = {
        "name": "device_resident_8bit_adamw",
        "implementation": "bitsandbytes.optim.AdamW8bit",
        "placement": "cuda_non_paged",
        "state_format": "bitsandbytes-device-resident-8bit-adamw-state-dict-v1",
    }
    if any(contract.get(field) != value for field, value in expected.items()):
        raise ValueError("production optimizer contract does not declare canonical device-resident AdamW8bit")
    hyperparameters = contract.get("hyperparameters")
    if not isinstance(hyperparameters, dict) or set(hyperparameters) != {"learning_rate", "weight_decay", "percentile_clipping", "block_wise"}:
        raise ValueError("production optimizer hyperparameters have an invalid shape")
    if (not isinstance(hyperparameters["learning_rate"], (int, float)) or hyperparameters["learning_rate"] <= 0 or not isinstance(hyperparameters["weight_decay"], (int, float)) or hyperparameters["weight_decay"] < 0 or not isinstance(hyperparameters["percentile_clipping"], int) or hyperparameters["percentile_clipping"] <= 0 or not isinstance(hyperparameters["block_wise"], bool)):
        raise ValueError("production optimizer hyperparameters are invalid")
    return dict(contract)

def _rng_state(device: torch.device) -> dict[str, torch.Tensor]:
    return {"cpu": torch.get_rng_state().clone(), "cuda": torch.cuda.get_rng_state(device).clone()}


def _rng_state_hash(device: torch.device) -> dict[str, str]:
    return {
        name: hashlib.sha256(state.cpu().numpy().tobytes()).hexdigest()
        for name, state in _rng_state(device).items()
    }

def _counter_expected_counts(model: UnifiedDecoder) -> dict[str, object]:
    """Capture counter expectations at publication, after the routed expert is selected."""
    return measure_parameter_counts(model)


def _execute_realization_counter(
    *,
    root: Path,
    config_path: Path,
    checkpoint_manifest_path: Path,
    active_expert: str,
    expected_counts: dict[str, object],
    parent_manifest: Path | None = None,
    root_manifest: Path | None = None,
) -> dict[str, object]:
    counter_path = root / "tools" / "ember-restart-3b" / "parameter_counter.py"
    if (parent_manifest is None) != (root_manifest is None):
        raise ValueError("counter replay requires both external parent and root manifests")
    arguments = [
        sys.executable,
        "-I",
        str(counter_path),
        "--model-config",
        str(config_path),
        "--checkpoint-manifest",
        str(checkpoint_manifest_path),
        "--active-expert",
        active_expert,
    ]
    if parent_manifest is not None and root_manifest is not None:
        arguments.extend(["--parent-manifest", str(parent_manifest), "--root-manifest", str(root_manifest)])
    completed = subprocess.run(
        arguments,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"isolated parameter counter failed: {completed.stderr.strip()}")
    try:
        receipt = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError("isolated parameter counter did not emit JSON") from error
    required = (
        "allocated_parameters",
        "unique_parameters",
        "trainable_parameters",
        "served_parameters",
        "active_parameters",
        "episode_trainable_parameters",
        "active_expert_ids",
    )
    if any(receipt.get(name) != expected_counts.get(name) for name in required):
        raise RuntimeError("isolated parameter counter disagrees with instantiated capacity")
    if receipt.get("counter_sha256") != _sha256(counter_path):
        raise RuntimeError("isolated parameter counter source hash is not self-consistent")
    return receipt


def build_production_optimizer(model: UnifiedDecoder, *, optimizer_contract: dict[str, object]) -> torch.optim.Optimizer:
    """Build exactly the structured device-resident AdamW8bit declared by config."""

    if optimizer_contract.get("implementation") != "bitsandbytes.optim.AdamW8bit" or optimizer_contract.get("placement") != "cuda_non_paged":
        raise ValueError("production optimizer must declare cuda_non_paged device-resident AdamW8bit")
    hyperparameters = optimizer_contract.get("hyperparameters")
    if not isinstance(hyperparameters, dict):
        raise ValueError("production optimizer contract lacks hyperparameters")
    import bitsandbytes as bnb

    return bnb.optim.AdamW8bit(
        model.parameters(),
        lr=float(hyperparameters["learning_rate"]),
        weight_decay=float(hyperparameters["weight_decay"]),
        percentile_clipping=int(hyperparameters["percentile_clipping"]),
        block_wise=bool(hyperparameters["block_wise"]),
    )

def run(
    *, seed: int, artifact_root: Path, resume_checkpoint: Path | None = None, resume_counter_receipt: Path | None = None,
    resume_realization_registry: Path | None = None,
    resume_optimizer_transition_registry: Path | None = None,
    resume_optimizer_transition_registry_sha256: str | None = None,
    records_override: list[dict[str, object]] | None = None,
    specialist_verification: dict[str, object] | None = None,
    specialist_lineage: dict[str, object] | None = None,
    checkpoint_interval: int | None = None,
    write_budget_bytes: int | None = None,
    c_relocated_under_disk_budget_runner: bool = False,
    relocation_custody_root: Path | None = None,
    telemetry_path: Path | None = None,
    telemetry_run_id: str | None = None,
    model_chat_restore_not_before: str | None = None,
) -> dict[str, object]:
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for the production vertical slice")
    if not isinstance(seed, int) or seed < 0:
        raise ValueError("launch seed must be a nonnegative integer")
    telemetry_values = (telemetry_path, telemetry_run_id, model_chat_restore_not_before)
    if any(value is not None for value in telemetry_values) and not all(value is not None for value in telemetry_values):
        raise ValueError("training telemetry requires path, run id, and model-chat restore time together")
    if telemetry_run_id is not None and (not telemetry_run_id or len(telemetry_run_id) > 128):
        raise ValueError("training telemetry run id is invalid")
    artifact_root = production_artifact_root(
        artifact_root,
        c_relocated_under_disk_budget_runner=c_relocated_under_disk_budget_runner,
        relocation_custody_root=relocation_custody_root,
    )
    root = Path(__file__).resolve().parents[2]
    config_path = root / "configs" / "ember-restart-3b.json"
    integration_contract_path = root / "docs" / "ember-restart" / "integration-contract-v1.md"
    if not integration_contract_path.is_file():
        raise RuntimeError("the merged Ember integration contract is required for production launch")
    config = RestartDecoderConfig.from_contract(config_path)
    memory_contract = load_memory_contract(config_path)
    episode_expert: str | None = None
    total_parameters = config.structural_parameter_count()
    active_parameters = total_parameters - (len(config.expert_names) - 1) * config.layers * 12 * config.hidden_size * config.hidden_size
    device_free_bytes, _device_total_bytes = torch.cuda.mem_get_info()
    memory_preflight = production_memory_preflight(
        total_parameters=total_parameters,
        active_parameters=active_parameters,
        device_free_bytes=int(device_free_bytes),
    )
    if telemetry_path is not None and telemetry_run_id is not None and model_chat_restore_not_before is not None:
        append_training_telemetry(telemetry_path, kind="run_status", payload={
            "run_id": telemetry_run_id,
            "phase": "ALLOCATING",
            "model_chat": "OFFLINE",
            "restore_not_before": model_chat_restore_not_before,
        })
    if memory_preflight["parameter_dtype"] != memory_contract["parameter_dtype"]:
        raise RuntimeError("memory preflight and production numerics disagree")
    if records_override is None:
        records, launch_packet, input_receipt = load_authorized_records(root)
        data_shard_id = str(launch_packet["input_identity"]["shard_path"])
    else:
        if not records_override or not isinstance(specialist_verification, dict) or not isinstance(specialist_lineage, dict):
            raise ValueError("specialist production run requires verified routed records and v4 lineage")
        if checkpoint_interval is None or write_budget_bytes is None:
            raise ValueError("specialist production run requires an explicit checkpoint interval and write budget")
        records = records_override
        launch_packet = {"input_identity": {"shard_path": "verified-specialist"}}
        input_receipt = specialist_verification
        execution_slice = specialist_lineage.get("execution_slice")
        if not isinstance(execution_slice, dict) or not isinstance(execution_slice.get("records_sha256"), str):
            raise ValueError("specialist production run requires an execution-slice receipt")
        data_shard_id = (
            "VERIFIED_SPECIALIST:"
            + str(specialist_verification["data_manifest_sha256"])[:12]
            + ":SLICE:"
            + str(execution_slice["records_sha256"])[:12]
        )
        episode_expert = verified_specialist_episode_expert(records, specialist_verification)
    checkpoint_parent = artifact_root / "checkpoints"
    checkpoint_root = checkpoint_parent / f"checkpoint-vertical-slice-seed-{seed}"
    resume_authority: dict[str, object] | None = None
    if resume_checkpoint is not None:
        resume_checkpoint, resume_authority = authorize_production_resume_checkpoint(
            resume_checkpoint,
            counter_success_receipt=resume_counter_receipt,
            realization_registry=resume_realization_registry,
            optimizer_transition_registry=resume_optimizer_transition_registry,
            optimizer_transition_registry_sha256=resume_optimizer_transition_registry_sha256,
            c_relocated_under_disk_budget_runner=c_relocated_under_disk_budget_runner,
            relocation_custody_root=relocation_custody_root,
        )

    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    rng_state_before_init = _rng_state_hash(torch.device("cuda"))
    previous_dtype = torch.get_default_dtype()
    torch.set_default_dtype(torch.bfloat16)
    try:
        model = UnifiedDecoder(config, device="cuda", allow_production_allocation=True, genesis_seed=seed)
    finally:
        torch.set_default_dtype(previous_dtype)
    if episode_expert is not None:
        model._activate_expert(episode_expert)
    genesis_hashes = model.expert_bank_genesis_hashes()
    model.train()
    counts = measure_parameter_counts(model)
    if counts["unique_parameters"] != 3_839_161_856 or counts["active_parameters"] != 1_725_232_640:
        raise RuntimeError("instantiated sparse counts differ from the authorized architecture")
    optimizer_contract = load_optimizer_contract(config_path)
    optimizer = build_production_optimizer(model, optimizer_contract=optimizer_contract)
    resume_cursor = {"record_index": 0, "global_step": 0, "tokens_seen": 0}
    if resume_checkpoint is not None:
        manifest_path = resume_checkpoint / "checkpoint-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        genesis_hashes = resume_expert_genesis(manifest, requested_seed=seed)
        receipt = {**manifest, "checkpoint_manifest_sha256": _sha256(manifest_path)}
        resume_cursor = restore_authorized_checkpoint(model, optimizer, resume_checkpoint, receipt, resume_authority)["data_cursor"]
        for group in optimizer.param_groups:
            group["lr"] = 1e-5
        if records_override is not None:
            resume_cursor = specialist_resume_cursor(resume_cursor, data_shard_id=data_shard_id)
        checkpoint_root = checkpoint_parent / f"checkpoint-continue-seed-{seed}-from-step-{resume_cursor['global_step'] + len(records)}"
    checkpoint_byte_bound = checkpoint_serialization_byte_bound(config_path, active_parameters=active_parameters)
    specialist_plan: dict[str, int] | None = None
    if records_override is not None:
        specialist_plan = specialist_publication_plan(
            records=len(records), checkpoint_interval=int(checkpoint_interval),
            checkpoint_byte_bound=checkpoint_byte_bound, write_budget_bytes=int(write_budget_bytes),
            initial_global_step=int(resume_cursor["global_step"]),
        )
    torch.cuda.reset_peak_memory_stats()
    checkpoint: dict[str, object] | None = None
    parameter_receipt: dict[str, object] | None = None
    latest_parent_manifest = Path(specialist_lineage["parent_manifest"]) if specialist_lineage is not None else None
    published_specialist_records = 0

    def checkpoint_callback(global_step: int, state: dict[str, Any]) -> None:
        nonlocal checkpoint, parameter_receipt, latest_parent_manifest, published_specialist_records
        data_cursor = dict(state["data_cursor"])
        data_cursor["input_identity_receipt_sha256"] = _json_sha256(input_receipt)
        if resume_authority is not None:
            data_cursor["resume_authority"] = resume_authority
        current_lineage: dict[str, object] | None = None
        if specialist_lineage is not None:
            if latest_parent_manifest is None:
                raise RuntimeError("specialist checkpoint publication lost its verified parent manifest")
            planned_slice = specialist_lineage["execution_slice"]
            processed_records = int(data_cursor["record_index"])
            if processed_records <= published_specialist_records or processed_records > len(records):
                raise RuntimeError("specialist checkpoint cursor does not identify a new bound episode")
            episode_slice = specialist_execution_slice_receipt(
                records[published_specialist_records:processed_records],
                source_start_record=int(planned_slice["start_record"]) + published_specialist_records,
            )
            current_lineage = {
                **specialist_lineage,
                "parent_manifest": str(latest_parent_manifest),
                "execution_slice": episode_slice,
            }
            data_cursor["specialist_verification"] = specialist_verification
            checkpoint_target = checkpoint_parent / f"checkpoint-continue-seed-{seed}-from-step-{global_step}"
        else:
            checkpoint_target = checkpoint_root

        verified_holder: dict[str, object] = {}

        def verify_staging(staging_root: Path, manifest_receipt: dict[str, object]) -> None:
            verified = _execute_realization_counter(
                root=root, config_path=config_path,
                checkpoint_manifest_path=staging_root / "checkpoint-manifest.json",
                active_expert=str(model.active_expert), expected_counts=_counter_expected_counts(model),
                parent_manifest=(Path(current_lineage["parent_manifest"]) if current_lineage is not None else None),
                root_manifest=(Path(current_lineage["root_manifest"]) if current_lineage is not None else None),
            )
            _atomic_json(staging_root / _COUNTER_SUCCESS_RECEIPT, verified)
            require_counter_success_receipt(staging_root)
            verified_holder["receipt"] = verified
            return verified

        def publish_and_verify() -> tuple[dict[str, object], dict[str, object]]:
            published = write_checkpoint_artifacts(
                model, optimizer, checkpoint_target, launch_seed=seed,
                rng_state=_rng_state(torch.device("cuda")), data_cursor=data_cursor,
                model_config_sha256=_sha256(config_path), contract_sha256=_sha256(integration_contract_path),
                expert_genesis_sha256=genesis_hashes, optimizer_contract=optimizer_contract,
                specialist_lineage=current_lineage, max_serialized_bytes=checkpoint_byte_bound,
                host_commit_reserve_bytes=checkpoint_host_commit_reserve_bytes(config_path),
                pre_publish_verifier=verify_staging,
            )
            return published, verified_holder["receipt"]

        checkpoint, parameter_receipt = _retain_after_success(
            checkpoint_parent,
            max_serialized_bytes=checkpoint_retention_budget_bytes(config_path),
            receipt_aware=True,
            operation=publish_and_verify,
        )
        if current_lineage is not None:
            latest_parent_manifest = checkpoint_target / "checkpoint-manifest.json"
            published_specialist_records = int(data_cursor["record_index"])
        if telemetry_path is not None and telemetry_run_id is not None:
            append_training_telemetry(telemetry_path, kind="checkpoint", payload={
                "run_id": telemetry_run_id,
                "step": global_step,
                "checkpoint_manifest_sha256": _sha256(checkpoint_target / "checkpoint-manifest.json"),
            })

    def progress_callback(progress: dict[str, object]) -> None:
        if telemetry_path is None or telemetry_run_id is None:
            return
        free_bytes, total_bytes = torch.cuda.mem_get_info()
        append_training_telemetry(telemetry_path, kind="train_step", payload={
            "run_id": telemetry_run_id,
            **progress,
            "free_gib": float(free_bytes / 1024**3),
            "total_gib": float(total_bytes / 1024**3),
            "vram_fraction_applied": float(torch.cuda.get_per_process_memory_fraction()),
        })

    segment = run_pretraining_segment(
        model=model, optimizer=optimizer, records=records, config=config, device=torch.device("cuda"),
        checkpoint_every=(int(checkpoint_interval) if records_override is not None else len(records)),
        checkpoint_callback=checkpoint_callback, initial_global_step=int(resume_cursor["global_step"]),
        progress_callback=progress_callback,
        initial_tokens_seen=int(resume_cursor["tokens_seen"]), initial_data_cursor=int(resume_cursor["record_index"]),
        data_shard_id=data_shard_id, require_complete_coverage=(records_override is None),
    )
    if checkpoint is None or parameter_receipt is None:
        raise RuntimeError("training segment completed without a durable verified checkpoint")
    if telemetry_path is not None and telemetry_run_id is not None and model_chat_restore_not_before is not None:
        append_training_telemetry(telemetry_path, kind="run_status", payload={
            "run_id": telemetry_run_id,
            "phase": "COMPLETE",
            "model_chat": "OFFLINE",
            "restore_not_before": model_chat_restore_not_before,
        })
    counts = measure_parameter_counts(model)
    if counts["unique_parameters"] != 3_839_161_856 or counts["active_parameters"] != 1_725_232_640:
        raise RuntimeError("instantiated sparse counts differ from the authorized architecture")
    return {
        "losses": segment["losses"], "counts": counts, "memory_preflight": memory_preflight,
        "launch_seed": seed, "rng_state_before_init_sha256": rng_state_before_init,
        "expert_genesis_sha256": genesis_hashes, "peak_memory_bytes": int(torch.cuda.max_memory_allocated()),
        "input_identity_receipt": input_receipt, "post_step_checkpoint": checkpoint,
        "parameter_receipt": parameter_receipt, "publication_plan": specialist_plan,
        "resume_authority": resume_authority,
    }

def specialist_lineage_request(
    *, capability: str, verification: dict[str, object], resume_checkpoint: Path | None,
    parent_manifest: Path, root_manifest: Path, execution_slice: dict[str, object],
) -> dict[str, object]:
    """Bind a specialist launch to externally supplied parent/root manifests before allocation."""

    expected_expert = {"image": "vision", "audio": "audio", "reasoning": "reasoning", "tool": "tool"}.get(capability)
    if expected_expert is None or verification.get("capability") != capability or verification.get("result") != "VERIFIED":
        raise ValueError("specialist lineage requires a verified capability-matched data receipt")
    validate_specialist_execution_slice(execution_slice, verified_record_count=verification.get("record_count"))
    if resume_checkpoint is None:
        raise ValueError("specialist v4 launch requires the parent checkpoint for resume")
    resume_manifest = resume_checkpoint.resolve() / "checkpoint-manifest.json"
    if parent_manifest.resolve() != resume_manifest:
        raise ValueError("specialist parent manifest must be the exact resumed checkpoint manifest")
    preflight = preflight_specialist_lineage_sources(
        parent_manifest=parent_manifest.resolve(), root_manifest=root_manifest.resolve(),
    )
    parent_history = preflight["parent_history"]
    return {
        "parent_manifest": parent_manifest.resolve(),
        "root_manifest": root_manifest.resolve(),
        "trained_expert_ids": [*parent_history, *([] if expected_expert in parent_history else [expected_expert])],
        "data_verification_receipt": verification,
        "execution_slice": execution_slice,
    }


def verified_specialist_episode_expert(
    records: list[dict[str, object]], verification: Mapping[str, object],
) -> str:
    """Bind one verified capability episode to its declared specialist before setup."""

    capability_experts = {"image": "vision", "audio": "audio", "reasoning": "reasoning", "tool": "tool"}
    capability = verification.get("capability")
    expected = capability_experts.get(capability)
    if expected is None:
        raise ValueError("verified specialist receipt lacks a declared capability")
    routed = {record.get("active_expert") for record in records}
    if routed != {expected}:
        raise ValueError(f"verified {capability} episode must route to {expected}")
    return expected


def run_specialist(
    *, seed: int, artifact_root: Path, data_manifest: Path, tokenizer_path: Path,
    capability: str, resume_checkpoint: Path | None = None, resume_counter_receipt: Path | None = None,
    resume_realization_registry: Path | None = None, resume_optimizer_transition_registry: Path | None = None,
    resume_optimizer_transition_registry_sha256: str | None = None,
    parent_manifest: Path, root_manifest: Path,
    checkpoint_interval: int, write_budget_bytes: int,
    start_record: int = 0, max_records: int | None = None,
    c_relocated_under_disk_budget_runner: bool = False,
    relocation_custody_root: Path | None = None,
    telemetry_path: Path | None = None,
    telemetry_run_id: str | None = None,
    model_chat_restore_not_before: str | None = None,
) -> dict[str, object]:
    """Run one verifier-bound specialist family through the canonical v4 lineage path."""

    root = Path(__file__).resolve().parents[2]
    records, verification = load_verified_specialist_records(
        root=root, data_manifest=data_manifest, tokenizer_path=tokenizer_path, capability=capability,
    )
    selected_records, execution_slice = bind_specialist_execution_slice(
        records, start_record=start_record,
        max_records=(len(records) - start_record if max_records is None else max_records),
    )
    lineage = specialist_lineage_request(
        capability=capability, verification=verification, resume_checkpoint=resume_checkpoint,
        parent_manifest=parent_manifest, root_manifest=root_manifest, execution_slice=execution_slice,
    )
    return run(
        seed=seed, artifact_root=artifact_root, resume_checkpoint=resume_checkpoint, resume_counter_receipt=resume_counter_receipt,
        resume_realization_registry=resume_realization_registry,
        resume_optimizer_transition_registry=resume_optimizer_transition_registry,
        resume_optimizer_transition_registry_sha256=resume_optimizer_transition_registry_sha256,
        records_override=selected_records, specialist_verification=verification, specialist_lineage=lineage,
        checkpoint_interval=checkpoint_interval, write_budget_bytes=write_budget_bytes,
        c_relocated_under_disk_budget_runner=c_relocated_under_disk_budget_runner,
        relocation_custody_root=relocation_custody_root,
        telemetry_path=telemetry_path,
        telemetry_run_id=telemetry_run_id,
        model_chat_restore_not_before=model_chat_restore_not_before,
    )
def run_semantic(
    *, seed: int, artifact_root: Path, receipt_path: Path, shards_root: Path, tokenizer_path: Path,
    steps: int, sequence_length: int, checkpoint_interval: int, write_budget_bytes: int, resume_checkpoint: Path | None = None,
    resume_counter_receipt: Path | None = None, resume_realization_registry: Path | None = None,
    resume_optimizer_transition_registry: Path | None = None,
    resume_optimizer_transition_registry_sha256: str | None = None,
) -> dict[str, object]:
    """Train receipt-bound semantic text through the shared nonlinear language path."""

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for the production semantic runner")
    if not isinstance(seed, int) or seed < 0 or not isinstance(steps, int) or steps < 1 or not isinstance(sequence_length, int) or sequence_length < 1 or not isinstance(checkpoint_interval, int) or checkpoint_interval < 1 or not isinstance(write_budget_bytes, int) or write_budget_bytes < 1:
        raise ValueError("semantic launch requires nonnegative seed and positive steps and sequence length")
    artifact_root = production_artifact_root(artifact_root)
    root = Path(__file__).resolve().parents[2]
    config_path = root / "configs" / "ember-restart-3b.json"
    integration_contract_path = root / "docs" / "ember-restart" / "integration-contract-v1.md"
    if not integration_contract_path.is_file():
        raise RuntimeError("the merged Ember integration contract is required for production launch")
    stream = ManifestBoundTokenStream.from_receipt(
        receipt_path=receipt_path, shards_root=shards_root, tokenizer_path=tokenizer_path
    )
    config = RestartDecoderConfig.from_contract(config_path)
    if stream.vocab_size != config.vocab_size:
        raise ValueError("semantic receipt tokenizer vocabulary does not match the production model config")
    total_parameters = config.structural_parameter_count()
    shared_active_parameters = 1_020_589_568
    device_free_bytes, _device_total_bytes = torch.cuda.mem_get_info()
    memory_preflight = production_memory_preflight(
        total_parameters=total_parameters, active_parameters=shared_active_parameters, device_free_bytes=int(device_free_bytes)
    )
    if memory_preflight["parameter_dtype"] != load_memory_contract(config_path)["parameter_dtype"]:
        raise RuntimeError("memory preflight and production numerics disagree")
    checkpoint_parent = artifact_root / "checkpoints"
    resume_authority: dict[str, object] | None = None
    if resume_checkpoint is not None:
        resume_checkpoint, resume_authority = authorize_production_resume_checkpoint(
            resume_checkpoint,
            counter_success_receipt=resume_counter_receipt,
            realization_registry=resume_realization_registry,
            optimizer_transition_registry=resume_optimizer_transition_registry,
            optimizer_transition_registry_sha256=resume_optimizer_transition_registry_sha256,
        )
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    rng_state_before_init = _rng_state_hash(torch.device("cuda"))
    previous_dtype = torch.get_default_dtype()
    torch.set_default_dtype(torch.bfloat16)
    try:
        model = UnifiedDecoder(config, device="cuda", allow_production_allocation=True, genesis_seed=seed)
    finally:
        torch.set_default_dtype(previous_dtype)
    model._activate_expert("shared")
    genesis_hashes = model.expert_bank_genesis_hashes()
    counts = measure_parameter_counts(model)
    if counts["unique_parameters"] != 3_839_161_856 or counts["active_parameters"] != shared_active_parameters:
        raise RuntimeError("instantiated shared semantic counts differ from the authorized architecture")
    optimizer_contract = load_optimizer_contract(config_path)
    optimizer = build_production_optimizer(model, optimizer_contract=optimizer_contract)
    resume_cursor: dict[str, object] | None = None
    initial_global_step = 0
    initial_tokens_seen = 0
    if resume_checkpoint is not None:
        manifest_path = resume_checkpoint / "checkpoint-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        genesis_hashes = resume_expert_genesis(manifest, requested_seed=seed)
        loaded = restore_authorized_checkpoint(
            model, optimizer, resume_checkpoint,
            {**manifest, "checkpoint_manifest_sha256": _sha256(manifest_path)}, resume_authority,
        )
        resume_cursor = dict(loaded["data_cursor"])
        initial_global_step = int(resume_cursor["global_step"])
        initial_tokens_seen = int(resume_cursor["tokens_seen"])
    checkpoint_byte_bound = checkpoint_serialization_byte_bound(config_path, active_parameters=shared_active_parameters)
    publication_plan = semantic_publication_plan(steps=steps, checkpoint_interval=checkpoint_interval, checkpoint_byte_bound=checkpoint_byte_bound, write_budget_bytes=write_budget_bytes, initial_global_step=initial_global_step)
    torch.cuda.reset_peak_memory_stats()
    checkpoint: dict[str, object] | None = None
    parameter_receipt: dict[str, object] | None = None

    def checkpoint_callback(global_step: int, state: dict[str, Any]) -> None:
        nonlocal checkpoint, parameter_receipt
        checkpoint_root = checkpoint_parent / f"checkpoint-semantic-seed-{seed}-step-{global_step}"
        verified_holder: dict[str, object] = {}

        def verify_staging(staging_root: Path, manifest_receipt: dict[str, object]) -> None:
            verified = _execute_realization_counter(
                root=root, config_path=config_path,
                checkpoint_manifest_path=staging_root / "checkpoint-manifest.json",
                active_expert="shared", expected_counts=counts,
            )
            _atomic_json(staging_root / _COUNTER_SUCCESS_RECEIPT, verified)
            require_counter_success_receipt(staging_root)
            verified_holder["receipt"] = verified
            return verified

        def publish_and_verify() -> tuple[dict[str, object], dict[str, object]]:
            data_cursor = dict(state["data_cursor"])
            if resume_authority is not None:
                data_cursor["resume_authority"] = resume_authority
            published = write_checkpoint_artifacts(
                model, optimizer, checkpoint_root, launch_seed=seed,
                rng_state=_rng_state(torch.device("cuda")), data_cursor=data_cursor,
                model_config_sha256=_sha256(config_path), contract_sha256=_sha256(integration_contract_path),
                expert_genesis_sha256=genesis_hashes, optimizer_contract=optimizer_contract,
                max_serialized_bytes=checkpoint_byte_bound,
                host_commit_reserve_bytes=checkpoint_host_commit_reserve_bytes(config_path),
                pre_publish_verifier=verify_staging,
            )
            return published, verified_holder["receipt"]

        checkpoint, parameter_receipt = _retain_after_success(
            checkpoint_parent,
            max_serialized_bytes=checkpoint_retention_budget_bytes(config_path),
            receipt_aware=True,
            operation=publish_and_verify,
        )

    segment = run_manifest_bound_semantic_segment(
        model=model,
        optimizer=optimizer,
        stream=stream,
        config=config,
        device=torch.device("cuda"),
        sequence_length=sequence_length,
        steps=steps,
        checkpoint_every=checkpoint_interval,
        checkpoint_callback=checkpoint_callback,
        initial_data_cursor=resume_cursor,
        initial_global_step=initial_global_step,
        initial_tokens_seen=initial_tokens_seen,
    )
    if checkpoint is None or parameter_receipt is None:
        raise RuntimeError("semantic runner did not publish its required counter-verified checkpoint")
    counts = measure_parameter_counts(model)
    return {
        "segment": segment,
        "counts": counts,
        "memory_preflight": memory_preflight,
        "launch_seed": seed,
        "rng_state_before_init_sha256": rng_state_before_init,
        "expert_genesis_sha256": genesis_hashes,
        "peak_memory_bytes": int(torch.cuda.max_memory_allocated()),
        "post_step_checkpoint": checkpoint,
        "parameter_receipt": parameter_receipt,
        "publication_plan": publication_plan,
        "stream_receipt_sha256": stream.receipt_sha256,
        "tokenizer_sha256": stream.tokenizer_sha256,
        "resume_authority": resume_authority,
    }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    vertical = subparsers.add_parser("vertical")
    vertical.add_argument("--seed", type=int, required=True)
    vertical.add_argument("--artifact-root", type=Path, required=True)
    vertical.add_argument("--resume-checkpoint", type=Path)
    vertical_resume = vertical.add_mutually_exclusive_group()
    vertical_resume.add_argument("--resume-counter-receipt", type=Path)
    vertical_resume.add_argument("--resume-realization-registry", type=Path)
    vertical_resume.add_argument("--resume-optimizer-transition-registry", type=Path)
    vertical.add_argument("--resume-optimizer-transition-registry-sha256")
    specialist = subparsers.add_parser("specialist")
    specialist.add_argument("--seed", type=int, required=True)
    specialist.add_argument("--artifact-root", type=Path, required=True)
    specialist.add_argument("--data-manifest", type=Path, required=True)
    specialist.add_argument("--tokenizer", type=Path, required=True)
    specialist.add_argument("--capability", choices=("image", "audio", "reasoning", "tool"), required=True)
    specialist.add_argument("--resume-checkpoint", type=Path, required=True)
    specialist_resume = specialist.add_mutually_exclusive_group(required=True)
    specialist_resume.add_argument("--resume-counter-receipt", type=Path)
    specialist_resume.add_argument("--resume-realization-registry", type=Path)
    specialist_resume.add_argument("--resume-optimizer-transition-registry", type=Path)
    specialist.add_argument("--resume-optimizer-transition-registry-sha256")
    specialist.add_argument("--parent-manifest", type=Path, required=True)
    specialist.add_argument("--root-manifest", type=Path, required=True)
    specialist.add_argument("--start-record", type=int, default=0)
    specialist.add_argument("--max-records", type=int, required=True)
    specialist.add_argument("--checkpoint-interval", type=int, required=True)
    specialist.add_argument("--write-budget-gib", type=int, required=True)
    specialist.add_argument("--c-relocated-under-disk-budget-runner", action="store_true")
    specialist.add_argument("--relocation-custody-root", type=Path)
    specialist.add_argument("--telemetry-path", type=Path, required=True)
    specialist.add_argument("--telemetry-run-id", required=True)
    specialist.add_argument("--model-chat-restore-not-before", required=True)
    semantic = subparsers.add_parser("semantic")
    semantic.add_argument("--seed", type=int, required=True)
    semantic.add_argument("--artifact-root", type=Path, required=True)
    semantic.add_argument("--receipt", type=Path, required=True)
    semantic.add_argument("--shards-root", type=Path, required=True)
    semantic.add_argument("--tokenizer", type=Path, required=True)
    semantic.add_argument("--steps", type=int, required=True)
    semantic.add_argument("--sequence-length", type=int, required=True)
    semantic.add_argument("--checkpoint-interval", type=int, required=True)
    semantic.add_argument("--write-budget-gib", type=int, required=True)
    semantic.add_argument("--resume-checkpoint", type=Path)
    semantic_resume = semantic.add_mutually_exclusive_group()
    semantic_resume.add_argument("--resume-counter-receipt", type=Path)
    semantic_resume.add_argument("--resume-realization-registry", type=Path)
    semantic_resume.add_argument("--resume-optimizer-transition-registry", type=Path)
    semantic.add_argument("--resume-optimizer-transition-registry-sha256")
    args = parser.parse_args()
    if args.command == "specialist":
        result = run_specialist(seed=args.seed, artifact_root=args.artifact_root, data_manifest=args.data_manifest, tokenizer_path=args.tokenizer, capability=args.capability, resume_checkpoint=args.resume_checkpoint, resume_counter_receipt=args.resume_counter_receipt, resume_realization_registry=args.resume_realization_registry, resume_optimizer_transition_registry=args.resume_optimizer_transition_registry, resume_optimizer_transition_registry_sha256=args.resume_optimizer_transition_registry_sha256, parent_manifest=args.parent_manifest, root_manifest=args.root_manifest, start_record=args.start_record, max_records=args.max_records, checkpoint_interval=args.checkpoint_interval, write_budget_bytes=args.write_budget_gib * 1024**3, c_relocated_under_disk_budget_runner=args.c_relocated_under_disk_budget_runner, relocation_custody_root=args.relocation_custody_root, telemetry_path=args.telemetry_path, telemetry_run_id=args.telemetry_run_id, model_chat_restore_not_before=args.model_chat_restore_not_before)
    elif args.command == "semantic":
        result = run_semantic(
            seed=args.seed,
            artifact_root=args.artifact_root,
            receipt_path=args.receipt,
            shards_root=args.shards_root,
            tokenizer_path=args.tokenizer,
            steps=args.steps,
            sequence_length=args.sequence_length,
            checkpoint_interval=args.checkpoint_interval,
            write_budget_bytes=args.write_budget_gib * 1024**3,
            resume_checkpoint=args.resume_checkpoint,
            resume_counter_receipt=args.resume_counter_receipt,
            resume_realization_registry=args.resume_realization_registry,
            resume_optimizer_transition_registry=args.resume_optimizer_transition_registry,
            resume_optimizer_transition_registry_sha256=args.resume_optimizer_transition_registry_sha256,
        )
    else:
        result = run(seed=args.seed, artifact_root=args.artifact_root, resume_checkpoint=args.resume_checkpoint, resume_counter_receipt=args.resume_counter_receipt, resume_realization_registry=args.resume_realization_registry, resume_optimizer_transition_registry=args.resume_optimizer_transition_registry, resume_optimizer_transition_registry_sha256=args.resume_optimizer_transition_registry_sha256)
    print(json.dumps(result, sort_keys=True))
if __name__ == "__main__":
    main()
