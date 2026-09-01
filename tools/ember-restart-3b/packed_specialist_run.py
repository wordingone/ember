# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Governed receipts for issue #1413's packed specialist training arms."""

from __future__ import annotations

import argparse
import dataclasses
import gc
import hashlib
import json
import math
import os
import re
import shutil
from collections.abc import Iterable, Mapping, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any

import torch
from batch import decode_owned_packed_batch
from checkpoint_artifacts import (
    build_packed_fresh_genesis_specialist_lineage,
    load_checkpoint_artifacts,
    published_checkpoint_receipt,
    write_checkpoint_artifacts,
)
from model import RestartDecoderConfig, UnifiedDecoder
from issue1946_complete_update_profile import (
    BoardEnergyTracker,
    build_arm_receipt as build_issue1946_arm_receipt,
    build_comparison_receipt as build_issue1946_comparison_receipt,
    build_oom_arm_receipt as build_issue1946_oom_arm_receipt,
    build_preflight_receipt as build_issue1946_preflight_receipt,
    gpu_covariate,
    load_accounting_spec as load_issue1946_accounting_spec,
    load_authority_crosswalk as load_issue1946_authority_crosswalk,
    validate_arm_a_receipt as validate_issue1946_arm_a_receipt,
    validate_preflight_receipt as validate_issue1946_preflight_receipt,
    verified_execution_source_commit,
)
from parameter_counter import measure_parameter_counts
from pretrain import (
    COMPLETE_UPDATE_BACKWARD_MARKER,
    COMPLETE_UPDATE_FORWARD_LOSS_MARKER,
    COMPLETE_UPDATE_GRADIENT_CLIPPING_MARKER,
    COMPLETE_UPDATE_OPTIMIZER_MARKER,
    CensusBoundStage2Executor,
    run_packed_selection_pretraining_segment,
)
from run_vertical_slice import (
    _COUNTER_SUCCESS_RECEIPT,
    _atomic_json,
    _canonical_disk_budget_runner_authority,
    _execute_realization_counter,
    build_production_optimizer,
    checkpoint_host_commit_reserve_bytes,
    governed_resource_preflight,
    governed_vertical_checkpoint_byte_bound,
    load_memory_contract,
    load_optimizer_contract,
    production_memory_preflight,
    require_counter_success_receipt,
)
from specialist_stream import open_specialist_stream
from training_acceleration import (
    Stage2ActivationAuthority,
    disabled_fp8_installation_receipt,
    load_stage2_activation_authority,
)

ISSUE_PROFILE_MODES = (
    "issue1946-preflight",
    "issue1946-arm-a",
    "issue1946-arm-b",
    "issue2024-smoke",
    "issue2024-arm-a",
    "issue2024-arm-b",
)

_SHA256 = re.compile(r"[0-9a-f]{64}")
_COMMIT = re.compile(r"[0-9a-f]{40}")
_CLAIM_BOUNDARY = "THROUGHPUT_ONLY_NO_CAPABILITY_CLAIM"
_DIAGNOSTIC_CLAIM_BOUNDARY = "DIAGNOSTIC_ONLY_NOT_CLOSE_EVIDENCE"
_B_EXECUTION_FLOOR_BYTES = 255 * 1024**3
_MAX_TRANSIENT_CHECKPOINT_SCRATCH_BYTES = 4 * 1024**3
_ARMS = {"bf16_packed_eager", "census_bound_stage2"}
_IDENTITY_KEYS = {
    "source_commit", "runner_source_sha256", "model_config_sha256",
    "stream_manifest_sha256", "stream_build_receipt_sha256",
    "selection_receipt_sha256", "density_raw_sha256", "density_self_sha256",
    "census_raw_sha256", "census_self_sha256", "execution_record_order_sha256",
    "execution_tokens_sha256", "pack_sequence_sha256", "genesis_lineage_sha256",
    "lineage_mode", "seed", "initial_cursor", "pack_records",
}
_CURSOR_KEYS = {
    "selected_ordinal", "global_step", "tokens_seen",
    "processed_tokens_seen", "pack_ordinal",
}
_MECHANISM_KEYS = {
    "fp8_dispatches", "fp8_fallbacks", "cuda_graph_captures",
    "cuda_graph_replays", "cuda_graph_fallbacks",
    "captures_during_preparation", "captures_during_measured_window",
}
_PREPARATION_KEYS = {
    "regions_per_signature", "signature_count", "region_count",
    "optimizer_state_preinitialized_parameters", "no_capture_in_measured_window",
}
_FP8_INSTALLATION_KEYS = {
    "schema_version", "scope", "layer_indexes", "installed_sites", "sites", "fallbacks",
}
_FP8_INSTALLATION_SCOPE = "final_decoder_layer_shared_swiglu_down_4h_to_h"
_ISSUE1946_FORWARD_OWNERS = (
    "projection", "attention", "mlp_routing", "norm_rope_residual", "loss",
    "precision", "launch_graph_synchronization",
)



def issue2024_profiler_configuration() -> dict[str, object]:
    return {
        "profile_memory": True,
        "record_shapes": True,
        "with_stack": True,
        # Kineto's default Windows activity configuration accepts with_stack
        # but leaves every event.stack empty.  Verbose mode is what asks the
        # runtime to materialize the Python call-site frames in profiler.events().
        "experimental_config": torch.profiler._ExperimentalConfig(verbose=True),
    }


def issue2024_profile_mode(mode: str) -> dict[str, str]:
    rows = {
        "issue2024-smoke": {
            "policy_mode": "issue1946-arm-a",
            "output_name": "issue2024-smoke-stack-ledger.json",
        },
        "issue2024-arm-a": {
            "policy_mode": "issue1946-arm-a",
            "output_name": "issue2024-arm-a-stack-ledger.json",
        },
        "issue2024-arm-b": {
            "policy_mode": "issue1946-arm-b",
            "output_name": "issue2024-arm-b-stack-ledger.json",
        },
    }
    try:
        return dict(rows[mode])
    except KeyError as error:
        raise ValueError("unknown #2024 profile mode") from error


def profiler_configuration_for_mode(mode: str) -> dict[str, bool]:
    if mode in {"issue2024-smoke", "issue2024-arm-a", "issue2024-arm-b"}:
        return issue2024_profiler_configuration()
    return {"profile_memory": True, "record_shapes": True, "with_stack": False}


def issue2024_profile_schedule(mode: str, policy_mode: str) -> dict[str, object]:
    if mode == "issue2024-smoke" or policy_mode == "issue1946-preflight":
        return {"packs": 1, "wait": 0, "active": 1, "update_indexes": [0]}
    return {"packs": 64, "wait": 16, "active": 8, "update_indexes": list(range(16, 24))}


def _issue2024_decimal_text(value: object) -> str:
    return format(Decimal(str(value)), "f")


def _issue2024_source_stack_with_depth(event: Any) -> tuple[list[str], int]:
    """Return the first recorded source stack and inspected ancestry depth."""

    current: Any | None = event
    visited: set[int] = set()
    while current is not None:
        identity = id(current)
        if identity in visited:
            raise ValueError("ISSUE2024_EVENT_CPU_PARENT_CYCLE")
        visited.add(identity)
        stack = [str(frame) for frame in (getattr(current, "stack", None) or [])]
        if stack:
            return stack, len(visited)
        current = getattr(current, "cpu_parent", None)
    return [], len(visited)


def _issue2024_source_stack(event: Any) -> list[str]:
    """Return the first recorded source stack on the event's CPU ancestry."""

    stack, _depth = _issue2024_source_stack_with_depth(event)
    if not stack:
        raise ValueError("ISSUE2024_EVENT_SOURCE_STACK_REQUIRED")
    return stack


def build_issue2024_event_ledger(
    events: Iterable[Any],
    *,
    declared_self_device_time_total_us: str,
) -> dict[str, object]:
    rows: list[dict[str, object]] = []
    excluded_zero_device_time_events: list[dict[str, object]] = []
    metadata_failures: list[dict[str, object]] = []
    event_ids: set[int] = set()
    ledger_total = Decimal("0")
    for event in events:
        event_id = int(event.id)
        if event_id in event_ids:
            raise ValueError(f"ISSUE2024_EVENT_ID_DUPLICATE:{event_id}")
        event_ids.add(event_id)
        device_time = Decimal(str(event.self_device_time_total))
        ledger_total += device_time
        if device_time == 0:
            excluded_zero_device_time_events.append({
                "event_id": event_id,
                "key": str(event.key),
                "reason": "ZERO_SELF_DEVICE_TIME",
                "self_device_time_us": _issue2024_decimal_text(device_time),
            })
            continue
        stack, ancestry_depth = _issue2024_source_stack_with_depth(event)
        parent = event.cpu_parent
        shapes = event.input_shapes
        common = {
            "ancestry_depth": ancestry_depth,
            "device_type": str(getattr(event, "device_type", "UNKNOWN")),
            "event_id": event_id,
            "key": str(event.key),
            "self_device_time_us": _issue2024_decimal_text(device_time),
        }
        if not stack:
            metadata_failures.append({
                **common,
                "failure_class": "ISSUE2024_EVENT_SOURCE_STACK_REQUIRED",
            })
        if parent is None or getattr(parent, "id", None) is None:
            metadata_failures.append({
                **common,
                "failure_class": "ISSUE2024_EVENT_CPU_PARENT_REQUIRED",
            })
        if shapes is None:
            metadata_failures.append({
                **common,
                "failure_class": "ISSUE2024_EVENT_INPUT_SHAPES_REQUIRED",
            })
        if not stack or parent is None or getattr(parent, "id", None) is None or shapes is None:
            continue
        rows.append({
            "cpu_parent_id": int(parent.id),
            "event_id": event_id,
            "input_shapes": shapes,
            "key": str(event.key),
            "self_device_time_us": _issue2024_decimal_text(device_time),
            "source_stack": stack,
        })

    if metadata_failures:
        raise ValueError(
            "ISSUE2024_EVENT_METADATA_REFUSED:"
            + json.dumps(metadata_failures, sort_keys=True, separators=(",", ":"))
        )

    declared_total = Decimal(declared_self_device_time_total_us)
    gap_ns = abs(declared_total - ledger_total) * Decimal("1000")
    if gap_ns > Decimal("1"):
        raise ValueError(f"ISSUE2024_EVENT_RECONCILIATION_MISS:{gap_ns}")
    return {
        "schema_version": "ember-issue2024-full-precision-event-ledger-v1",
        "declared_self_device_time_total_us": _issue2024_decimal_text(declared_total),
        "ledger_self_device_time_total_us": _issue2024_decimal_text(ledger_total),
        "excluded_self_device_time_total_us": "0",
        "excluded_zero_device_time_events": excluded_zero_device_time_events,
        "reconciliation_gap_ns": int(gap_ns),
        "events": rows,
    }

def _issue1946_event_inside_marker(event: object, marker: str) -> bool:
    parent = getattr(event, "cpu_parent", None)
    while parent is not None:
        if str(getattr(parent, "key", "")) == marker:
            return True
        parent = getattr(parent, "cpu_parent", None)
    return False


def _issue1946_forward_owner(name: str, shapes: object, *, hidden: int, vocab_size: int) -> str | None:
    lowered = name.lower()
    if any(needle in lowered for needle in ("cross_entropy", "log_softmax", "nll_loss")):
        return "loss"
    if any(needle in lowered for needle in ("layer_norm", "rms_norm", "rotary", "rope", "residual")):
        return "norm_rope_residual"
    if any(needle in lowered for needle in ("autocast", "convert", "_to_copy", "cast")):
        return "precision"
    if any(needle in lowered for needle in ("synchronize", "cuda_graph", "launch")):
        return "launch_graph_synchronization"
    if not any(needle in lowered for needle in ("mm", "linear", "matmul")):
        return None
    dimensions: set[int] = set()

    def visit(value: object) -> None:
        if type(value) is int:
            dimensions.add(value)
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            for item in value:
                visit(item)

    visit(shapes)
    if vocab_size in dimensions:
        return "projection"
    if 4 * hidden in dimensions or 8 * hidden in dimensions:
        return "mlp_routing"
    if 3 * hidden in dimensions or hidden in dimensions:
        return "attention"
    return "projection"


def _issue1946_safety_margin_failure_bytes(error: MemoryError) -> tuple[int, int]:
    match = re.search(r"requires (\d+) bytes but only (\d+) are free", str(error))
    if match is None:
        raise RuntimeError("all-off safety refusal did not expose required/free bytes") from error
    required_bytes, free_bytes = (int(value) for value in match.groups())
    if required_bytes <= free_bytes or free_bytes <= 0:
        raise RuntimeError("all-off safety refusal required/free evidence is inconsistent") from error
    return required_bytes, free_bytes


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _require_sha(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{label} must be lowercase 64hex")
    return value


def _require_cursor(value: object, label: str) -> dict[str, int]:
    if not isinstance(value, Mapping) or set(value) != _CURSOR_KEYS:
        raise ValueError(f"{label} must use the closed packed cursor projection")
    cursor = dict(value)
    if any(type(cursor[key]) is not int or cursor[key] < 0 for key in _CURSOR_KEYS):
        raise ValueError(f"{label} counters must be nonnegative integers")
    return cursor


def packed_genesis_lineage_sha256(
    *, source_commit: str, model_config_sha256: str, seed: int,
) -> str:
    if _COMMIT.fullmatch(source_commit) is None:
        raise ValueError("packed genesis source commit must be lowercase 40hex")
    _require_sha(model_config_sha256, "packed genesis model config hash")
    if type(seed) is not int or seed < 0:
        raise ValueError("packed genesis seed must be a nonnegative integer")
    return hashlib.sha256(_canonical({
        "schema_version": "ember-issue1413-packed-fresh-genesis-v1",
        "lineage_mode": "FRESH_GENESIS_NO_EXTERNAL_PREDECESSOR",
        "source_commit": source_commit,
        "model_config_sha256": model_config_sha256,
        "seed": seed,
        "active_expert": "audio",
    })).hexdigest()


def prepare_packed_execution_slice(
    *, selection: object, config: object, device: torch.device,
    packs: int, initial_selection_cursor: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Resolve and hash the exact fixed packs before model allocation."""

    if type(packs) is not int or packs < 1:
        raise ValueError("packed execution packs must be positive")
    receipt = getattr(selection, "receipt", None)
    iter_from = getattr(selection, "iter_from", None)
    if not isinstance(receipt, Mapping) or not callable(iter_from):
        raise ValueError("packed execution requires a bound sequential selection")
    start_ordinal = 0 if initial_selection_cursor is None else initial_selection_cursor.get("selected_ordinal")
    if type(start_ordinal) is not int or start_ordinal < 0:
        raise ValueError("packed execution start cursor is malformed")
    selected_count = receipt.get("selected_record_count")
    if type(selected_count) is not int or start_ordinal + packs * 64 > selected_count:
        raise ValueError("packed execution slice exceeds the selected records")
    iterator = iter(iter_from(initial_selection_cursor))
    records: list[dict[str, object]] = []
    pack_signatures: list[str] = []
    pack_record_order_sha256: list[str] = []
    pack_tokens_sha256: list[str] = []
    end_cursor: dict[str, object] | None = None
    for _ in range(packs):
        pack: list[dict[str, object]] = []
        for _ in range(64):
            try:
                item = next(iterator)
            except StopIteration as error:
                raise ValueError("packed execution selection ended before its bound slice") from error
            if not isinstance(item, tuple) or len(item) != 2 or not isinstance(item[0], Mapping) or not isinstance(item[1], Mapping):
                raise ValueError("packed execution selection yielded a malformed row")
            record = dict(item[0])
            pack.append(record)
            records.append(record)
            end_cursor = dict(item[1])
        batch = decode_owned_packed_batch(pack, config, device=device, expected_records=64)
        if (
            batch.get("record_count") != 64
            or batch.get("true_source_tokens") != 960
            or batch.get("processed_padded_tokens") != 960
            or batch.get("padding_tokens") != 0
            or batch.get("active_expert") != "audio"
        ):
            raise ValueError("packed execution requires only fixed zero-padding audio-64 packs")
        pack_signatures.append(_require_sha(batch.get("pack_signature_sha256"), "packed execution signature"))
        pack_record_order_sha256.append(_require_sha(batch.get("record_order_sha256"), "packed execution record order"))
        pack_tokens_sha256.append(_require_sha(batch.get("tokens_sha256"), "packed execution tokens"))
    if end_cursor is None:
        raise RuntimeError("packed execution retained no end cursor")
    records_sha256 = hashlib.sha256(_canonical(records)).hexdigest()
    tokens_sha256 = hashlib.sha256(_canonical([record["token_ids"] for record in records])).hexdigest()
    pack_sequence_sha256 = hashlib.sha256(_canonical(pack_signatures)).hexdigest()
    return {
        "schema_version": "ember-issue1413-packed-execution-slice-v1",
        "start_selected_ordinal": start_ordinal,
        "record_count": packs * 64,
        "true_source_tokens": packs * 960,
        "processed_padded_tokens": packs * 960,
        "padding_tokens": 0,
        "execution_record_order_sha256": records_sha256,
        "execution_tokens_sha256": tokens_sha256,
        "pack_signatures": pack_signatures,
        "pack_record_order_sha256": pack_record_order_sha256,
        "pack_tokens_sha256": pack_tokens_sha256,
        "pack_sequence_sha256": pack_sequence_sha256,
        "end_selection_cursor": end_cursor,
    }


def _validate_identity(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping) or set(value) != _IDENTITY_KEYS:
        raise ValueError("packed arm identity must use its closed key set")
    identity = dict(value)
    if _COMMIT.fullmatch(str(identity["source_commit"])) is None:
        raise ValueError("packed arm source commit must be lowercase 40hex")
    for key in _IDENTITY_KEYS - {"source_commit", "lineage_mode", "seed", "initial_cursor", "pack_records"}:
        _require_sha(identity[key], f"packed arm {key}")
    if identity["lineage_mode"] != "FRESH_GENESIS_NO_EXTERNAL_PREDECESSOR":
        raise ValueError("packed arm lineage must start from governed fresh genesis")
    if type(identity["seed"]) is not int or identity["seed"] < 0:
        raise ValueError("packed arm seed must be a nonnegative integer")
    if identity["pack_records"] != 64:
        raise ValueError("packed arm requires the fixed audio-64 pack")
    identity["initial_cursor"] = _require_cursor(identity["initial_cursor"], "packed arm initial cursor")
    return identity


def build_packed_arm_receipt(
    *, arm: str, identity: Mapping[str, object], steps: int,
    true_source_tokens: int, processed_padded_tokens: int, padding_tokens: int,
    losses: Sequence[float], step_timings_seconds: Sequence[float],
    single_record_reference_losses: Sequence[float] | None,
    max_memory_allocated_bytes: int, max_memory_reserved_bytes: int,
    mechanisms: Mapping[str, object], fp8_installation: Mapping[str, object],
    measurement_preparation: Mapping[str, object],
    final_cursor: Mapping[str, object], runtime_custody: Mapping[str, object],
) -> dict[str, object]:
    """Build a closed arm receipt; padding can never satisfy the close rate."""

    if arm not in _ARMS:
        raise ValueError("packed arm identity is invalid")
    bound_identity = _validate_identity(identity)
    if type(steps) is not int or steps < 1:
        raise ValueError("packed arm steps must be positive")
    counts = (true_source_tokens, processed_padded_tokens, padding_tokens)
    if any(type(value) is not int or value < 0 for value in counts):
        raise ValueError("packed arm token counts must be nonnegative integers")
    if true_source_tokens < 1 or processed_padded_tokens - true_source_tokens != padding_tokens:
        raise ValueError("packed arm true, processed, and padding token counts disagree")
    if true_source_tokens != steps * 960:
        raise ValueError("packed arm true tokens do not match fixed audio-64 steps")
    if len(losses) != steps or len(step_timings_seconds) != steps:
        raise ValueError("packed arm losses and timings must cover every step")
    normalized_losses = [float(value) for value in losses]
    normalized_timings = [float(value) for value in step_timings_seconds]
    if any(not math.isfinite(value) for value in normalized_losses):
        raise ValueError("packed arm losses must be finite")
    if arm == "bf16_packed_eager":
        if single_record_reference_losses is None or len(single_record_reference_losses) != steps:
            raise ValueError("packed BF16 eager arm requires a single-record reference loss for every step")
        normalized_reference_losses: list[float] | None = [
            float(value) for value in single_record_reference_losses
        ]
        if any(not math.isfinite(value) for value in normalized_reference_losses):
            raise ValueError("packed single-record reference losses must be finite")
        relative_reference_deltas = [
            abs(packed - reference) / max(abs(reference), 1e-12)
            for packed, reference in zip(
                normalized_losses, normalized_reference_losses, strict=True,
            )
        ]
        if any(delta >= 0.01 for delta in relative_reference_deltas):
            raise ValueError("packed BF16 loss must remain strictly within one percent of the single-record reference")
    else:
        if single_record_reference_losses is not None:
            raise ValueError("packed Stage-2 arm cannot carry BF16 single-record reference losses")
        normalized_reference_losses = None
    if any(not math.isfinite(value) or value <= 0.0 for value in normalized_timings):
        raise ValueError("packed arm step timings must be finite and positive")
    if any(type(value) is not int or value < 1 for value in (max_memory_allocated_bytes, max_memory_reserved_bytes)):
        raise ValueError("packed arm memory counters must be positive integers")
    if max_memory_reserved_bytes < max_memory_allocated_bytes:
        raise ValueError("packed arm reserved memory cannot be below allocated memory")
    if not isinstance(runtime_custody, Mapping) or set(runtime_custody) != {
        "canonical_disk_budget_runner", "b_floor_preflight", "governor", "memory_preflight",
    }:
        raise ValueError("packed arm runtime custody must use its closed key set")
    custody = dict(runtime_custody)
    canonical_runner = custody["canonical_disk_budget_runner"]
    b_floor = custody["b_floor_preflight"]
    memory_preflight = custody["memory_preflight"]
    if (
        not isinstance(canonical_runner, Mapping)
        or canonical_runner.get("schema_version") != "ember-canonical-disk-budget-startup-v1"
        or not isinstance(b_floor, Mapping) or b_floor.get("status") != "PASS"
        or b_floor.get("required_free_gib") != 255
        or not isinstance(custody["governor"], Mapping)
        or not isinstance(memory_preflight, Mapping)
        or memory_preflight.get("parameter_dtype") != "bfloat16"
    ):
        raise ValueError("packed arm runtime custody is not admitted")
    if not isinstance(mechanisms, Mapping) or set(mechanisms) != _MECHANISM_KEYS:
        raise ValueError("packed arm mechanisms must use their closed key set")
    normalized_mechanisms = dict(mechanisms)
    if any(type(value) is not int or value < 0 for value in normalized_mechanisms.values()):
        raise ValueError("packed arm mechanism counters must be nonnegative integers")
    if normalized_mechanisms["fp8_fallbacks"] or normalized_mechanisms["cuda_graph_fallbacks"]:
        raise ValueError("packed arm cannot carry any fallback")
    if arm == "bf16_packed_eager":
        if any(normalized_mechanisms.values()):
            raise ValueError("packed BF16 eager arm cannot carry Stage-2 mechanisms")
    elif (
        normalized_mechanisms["fp8_dispatches"] < 1
        or normalized_mechanisms["cuda_graph_captures"] < 1
        or normalized_mechanisms["cuda_graph_replays"] < steps
        or normalized_mechanisms["captures_during_preparation"] < 1
        or normalized_mechanisms["captures_during_measured_window"] != 0
    ):
        raise ValueError("packed Stage-2 arm lacks required mechanisms")
    if not isinstance(fp8_installation, Mapping) or set(fp8_installation) != _FP8_INSTALLATION_KEYS:
        raise ValueError("packed arm FP8 installation must use its closed key set")
    normalized_installation = dict(fp8_installation)
    disabled_installation = disabled_fp8_installation_receipt()
    if arm == "bf16_packed_eager":
        if normalized_installation != disabled_installation:
            raise ValueError("packed BF16 arm FP8 installation must be disabled")
    else:
        layer_indexes = normalized_installation.get("layer_indexes")
        sites = normalized_installation.get("sites")
        if (
            normalized_installation.get("schema_version") != "ember-fp8-down-projection-installation-v2"
            or normalized_installation.get("scope") != _FP8_INSTALLATION_SCOPE
            or normalized_installation.get("installed_sites") != 1
            or normalized_installation.get("fallbacks") != 0
            or not isinstance(layer_indexes, list) or len(layer_indexes) != 1
            or type(layer_indexes[0]) is not int or layer_indexes[0] < 0
            or sites != [f"layers.{layer_indexes[0]}.shared_ffn.down"]
        ):
            raise ValueError("packed Stage-2 FP8 installation scope is invalid")
    if not isinstance(measurement_preparation, Mapping) or set(measurement_preparation) != _PREPARATION_KEYS:
        raise ValueError("packed arm measurement preparation must use its closed key set")
    preparation = dict(measurement_preparation)
    if (
        preparation["regions_per_signature"] != 4
        or preparation["signature_count"] != 1
        or preparation["region_count"] != 4
        or type(preparation["optimizer_state_preinitialized_parameters"]) is not int
        or preparation["optimizer_state_preinitialized_parameters"] < 1
        or preparation["no_capture_in_measured_window"] is not True
    ):
        raise ValueError("packed arm measurement preparation is invalid")
    final = _require_cursor(final_cursor, "packed arm final cursor")
    initial = bound_identity["initial_cursor"]
    if (
        final["selected_ordinal"] - initial["selected_ordinal"] != steps * 64
        or final["global_step"] - initial["global_step"] != steps
        or final["tokens_seen"] - initial["tokens_seen"] != true_source_tokens
        or final["processed_tokens_seen"] - initial["processed_tokens_seen"] != processed_padded_tokens
        or final["pack_ordinal"] - initial["pack_ordinal"] != steps
    ):
        raise ValueError("packed arm final cursor does not match measured work")
    elapsed = float(sum(normalized_timings))
    receipt: dict[str, object] = {
        "schema_version": "ember-issue1413-packed-training-arm-v2",
        "arm": arm,
        "claim_boundary": _CLAIM_BOUNDARY,
        **bound_identity,
        "steps": steps,
        "true_source_tokens": true_source_tokens,
        "processed_padded_tokens": processed_padded_tokens,
        "padding_tokens": padding_tokens,
        "losses": normalized_losses,
        "single_record_reference_losses": normalized_reference_losses,
        "step_timings_seconds": normalized_timings,
        "step_elapsed_seconds": elapsed,
        "true_tokens_per_second": true_source_tokens / elapsed,
        "processed_tokens_per_second": processed_padded_tokens / elapsed,
        "max_memory_allocated_bytes": max_memory_allocated_bytes,
        "max_memory_reserved_bytes": max_memory_reserved_bytes,
        "runtime_custody": custody,
        "mechanisms": normalized_mechanisms,
        "fp8_installation": normalized_installation,
        "measurement_preparation": preparation,
        "final_cursor": final,
    }
    receipt["self_sha256"] = hashlib.sha256(_canonical(receipt)).hexdigest()
    return receipt


def _validate_self(value: Mapping[str, object], label: str) -> dict[str, object]:
    receipt = dict(value)
    claimed = _require_sha(receipt.pop("self_sha256", None), f"{label} self hash")
    if hashlib.sha256(_canonical(receipt)).hexdigest() != claimed:
        raise ValueError(f"{label} self hash mismatch")
    receipt["self_sha256"] = claimed
    return receipt


def _validate_arm_receipt(value: Mapping[str, object], label: str) -> dict[str, object]:
    receipt = _validate_self(value, label)
    expected_keys = _IDENTITY_KEYS | {
        "schema_version", "arm", "claim_boundary", "steps",
        "true_source_tokens", "processed_padded_tokens", "padding_tokens",
        "losses", "single_record_reference_losses", "step_timings_seconds", "step_elapsed_seconds",
        "true_tokens_per_second", "processed_tokens_per_second",
        "max_memory_allocated_bytes", "max_memory_reserved_bytes",
        "runtime_custody", "mechanisms", "fp8_installation", "measurement_preparation",
        "final_cursor", "self_sha256",
    }
    if set(receipt) != expected_keys:
        raise ValueError(f"{label} must use the closed packed arm key set")
    if (
        receipt["schema_version"] != "ember-issue1413-packed-training-arm-v2"
        or receipt["claim_boundary"] != _CLAIM_BOUNDARY
    ):
        raise ValueError(f"{label} schema or claim boundary is invalid")
    rebuilt = build_packed_arm_receipt(
        arm=str(receipt["arm"]),
        identity={key: receipt[key] for key in _IDENTITY_KEYS},
        steps=receipt["steps"],
        true_source_tokens=receipt["true_source_tokens"],
        processed_padded_tokens=receipt["processed_padded_tokens"],
        padding_tokens=receipt["padding_tokens"],
        losses=receipt["losses"],
        single_record_reference_losses=receipt["single_record_reference_losses"],
        step_timings_seconds=receipt["step_timings_seconds"],
        max_memory_allocated_bytes=receipt["max_memory_allocated_bytes"],
        max_memory_reserved_bytes=receipt["max_memory_reserved_bytes"],
        mechanisms=receipt["mechanisms"],
        fp8_installation=receipt["fp8_installation"],
        measurement_preparation=receipt["measurement_preparation"],
        final_cursor=receipt["final_cursor"],
        runtime_custody=receipt["runtime_custody"],
    )
    if rebuilt != receipt:
        raise ValueError(f"{label} derived fields are inconsistent")
    return receipt


def build_packed_graph_bf16_diagnostic_receipt(
    *, identity: Mapping[str, object], segment: Mapping[str, object],
    runtime_custody: Mapping[str, object],
) -> dict[str, object]:
    """Bind an exact packed graph/workspace differential without close credit."""

    bound_identity = _validate_identity(identity)
    steps = segment.get("steps")
    losses = segment.get("losses")
    timings = segment.get("step_timings_seconds")
    runtime = segment.get("stage2_runtime")
    preparation = segment.get("measurement_preparation")
    if (
        type(steps) is not int or steps < 1
        or not isinstance(losses, list) or len(losses) != steps
        or not isinstance(timings, list) or len(timings) != steps
        or any(not isinstance(value, (int, float)) or not math.isfinite(float(value)) for value in losses)
        or any(not isinstance(value, (int, float)) or float(value) <= 0.0 for value in timings)
        or not isinstance(runtime, Mapping)
        or not isinstance(preparation, Mapping)
    ):
        raise ValueError("packed graph-only BF16 diagnostic result is malformed")
    if (
        runtime.get("fp8_dispatches") != 0
        or runtime.get("fp8_fallbacks") != 0
        or runtime.get("cuda_graph_captures") != 1
        or runtime.get("cuda_graph_replays") != steps
        or runtime.get("cuda_graph_fallbacks") != 0
    ):
        raise ValueError("packed graph-only BF16 diagnostic mechanisms are invalid")
    receipt: dict[str, object] = {
        "schema_version": "ember-issue1413-packed-graph-bf16-diagnostic-v1",
        "mode": "graph_only_bf16_down",
        "claim_boundary": _DIAGNOSTIC_CLAIM_BOUNDARY,
        **bound_identity,
        "steps": steps,
        "losses": [float(value) for value in losses],
        "step_timings_seconds": [float(value) for value in timings],
        "final_cursor": _cursor_projection(segment.get("data_cursor")),
        "measurement_preparation": dict(preparation),
        "stage2_runtime": dict(runtime),
        "runtime_custody": dict(runtime_custody),
    }
    receipt["self_sha256"] = hashlib.sha256(_canonical(receipt)).hexdigest()
    return receipt


def load_packed_activation_authority(
    *, census_path: Path, expected_census_raw_sha256: str,
    expected_census_self_sha256: str, density_path: Path,
    expected_density_raw_sha256: str, expected_density_self_sha256: str,
    source_commit: str, model_config_sha256: str,
) -> tuple[dict[str, object], Stage2ActivationAuthority]:
    """Reopen the exact observation-only census and its audio-64 density authority."""

    expected_hashes = (
        (expected_census_raw_sha256, "packed census raw hash"),
        (expected_census_self_sha256, "packed census self hash"),
        (expected_density_raw_sha256, "packed density raw hash"),
        (expected_density_self_sha256, "packed density self hash"),
        (model_config_sha256, "packed activation model config hash"),
    )
    for value, label in expected_hashes:
        _require_sha(value, label)
    if _COMMIT.fullmatch(source_commit) is None:
        raise ValueError("packed activation source commit must be lowercase 40hex")
    try:
        density_raw = density_path.read_bytes()
        density = json.loads(density_raw)
        census_raw = census_path.read_bytes()
        census = json.loads(census_raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("packed activation authorities are not readable strict JSON") from error
    if hashlib.sha256(density_raw).hexdigest() != expected_density_raw_sha256:
        raise ValueError("packed density raw hash mismatch")
    if not isinstance(density, dict):
        raise ValueError("packed density receipt is malformed")
    density_unsigned = dict(density)
    density_self = _require_sha(density_unsigned.pop("self_sha256", None), "packed density self hash")
    if density_self != expected_density_self_sha256 or hashlib.sha256(_canonical(density_unsigned)).hexdigest() != density_self:
        raise ValueError("packed density self hash mismatch")
    if hashlib.sha256(census_raw).hexdigest() != expected_census_raw_sha256:
        raise ValueError("packed census raw hash mismatch")
    if not isinstance(census, dict) or census.get("self_sha256") != expected_census_self_sha256:
        raise ValueError("packed census self hash mismatch")
    fixed_shape = density.get("fixed_shape")
    if (
        density.get("schema_version") != "ember-issue1413-packed-density-v1"
        or density.get("status") != "OBSERVED_NOT_ACTIVATED"
        or density.get("claim_boundary") != "THROUGHPUT_SHAPE_ONLY_NO_TRAINING_OR_CAPABILITY_CLAIM"
        or density.get("stream_boundary") != "STREAM_CONSTRUCTION_NOT_SUFFICIENT_PRETRAINING_OR_CAPABILITY"
        or fixed_shape != {"capability": "audio", "pack_records": 64, "tokens_per_record": 15}
        or density.get("true_source_tokens") != 960
        or density.get("processed_padded_tokens") != 960
        or density.get("padding_tokens") != 0
        or density.get("source_commit") != source_commit
        or density.get("model_config_sha256") != model_config_sha256
    ):
        raise ValueError("packed density authority is not the fixed observation-only audio-64 receipt")
    probe_sha256 = hashlib.sha256(Path(__file__).with_name("packed_specialist_probe.py").read_bytes()).hexdigest()
    if (
        census.get("schema_version") != "ember-training-signature-census-v1"
        or census.get("status") != "OBSERVED_NOT_ACTIVATED"
        or census.get("activation_enabled") is not False
        or census.get("fallbacks") != 0
        or census.get("signature_count") != 1
        or census.get("observed_steps") != 1
        or census.get("source_commit") != source_commit
        or census.get("model_config_sha256") != model_config_sha256
        or census.get("input_identity_sha256") != density.get("selection_receipt_sha256")
        or census.get("runner_source_sha256") != probe_sha256
    ):
        raise ValueError("packed census does not bind the fixed density authority")
    authority = load_stage2_activation_authority(
        census_path, expected_raw_sha256=expected_census_raw_sha256,
    )
    if authority.census_self_sha256 != expected_census_self_sha256:
        raise ValueError("packed census reopened self hash mismatch")
    return density, authority


def _sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json_no_replace(path: Path, value: Mapping[str, object]) -> tuple[str, str]:
    payload = dict(value)
    raw = json.dumps(payload, sort_keys=True, indent=2).encode("utf-8") + b"\n"
    with path.open("xb") as handle:
        handle.write(raw)
    return hashlib.sha256(raw).hexdigest(), str(payload["self_sha256"])


def _load_self_hashed_json(path: Path, label: str) -> tuple[dict[str, object], str]:
    raw = path.resolve(strict=True).read_bytes()
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} is not valid JSON") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    unsigned = dict(value)
    claimed = unsigned.pop("self_sha256", None)
    if not isinstance(claimed, str) or hashlib.sha256(_canonical(unsigned)).hexdigest() != claimed:
        raise ValueError(f"{label} self hash is invalid")
    return value, hashlib.sha256(raw).hexdigest()


def require_b_execution_floor() -> dict[str, object]:
    """Enforce the integration-side 255 GiB pre-write guard above the runner's 250 GiB floor."""

    free_bytes = int(shutil.disk_usage(Path("B:/")).free)
    receipt = {
        "schema_version": "ember-issue1413-b-floor-preflight-v1",
        "drive": "B",
        "observed_free_bytes": free_bytes,
        "required_free_bytes": _B_EXECUTION_FLOOR_BYTES,
        "required_free_gib": 255,
        "status": "PASS" if free_bytes >= _B_EXECUTION_FLOOR_BYTES else "REFUSED",
    }
    if receipt["status"] != "PASS":
        raise RuntimeError("packed issue #1413 leg requires at least 255 GiB free on B before writing")
    return receipt


def _open_selection(
    *, repo_root: Path, manifest_path: Path, manifest_sha256: str,
    build_receipt_path: Path, build_receipt_sha256: str,
) -> object:
    manifest_raw = manifest_path.read_bytes()
    if hashlib.sha256(manifest_raw).hexdigest() != manifest_sha256:
        raise ValueError("packed runtime stream manifest raw hash mismatch")
    manifest = json.loads(manifest_raw)
    stream = open_specialist_stream(
        repo_root=repo_root,
        manifest_path=manifest_path,
        expected_manifest_sha256=manifest_sha256,
        expected_corpus_root_sha256=manifest["corpus_root_sha256"],
        manifest_bytes=manifest_raw,
    )
    return stream.prepare_execution_selection(
        capability="audio",
        selection_rule_id="all_records_semantic_pretraining_v1",
        build_receipt_path=build_receipt_path,
        expected_build_receipt_sha256=build_receipt_sha256,
    )


def _hash_tensor(digest: Any, tensor: torch.Tensor) -> None:
    contiguous = tensor.detach().contiguous()
    digest.update(str(contiguous.dtype).encode("ascii"))
    digest.update(_canonical(list(contiguous.shape)))
    digest.update(contiguous.reshape(-1).view(torch.uint8).cpu().numpy().tobytes())


def active_route_parameter_sha256(model: UnifiedDecoder) -> str:
    """Hash every shared and audio parameter after an update, in name order."""

    digest = hashlib.sha256()
    selected = [
        (name, parameter)
        for name, parameter in model.named_parameters()
        if ".experts." not in name or ".experts.audio." in name
    ]
    if not selected:
        raise RuntimeError("packed active-route parameter set is empty")
    for name, parameter in sorted(selected):
        digest.update(name.encode("utf-8"))
        _hash_tensor(digest, parameter)
    return digest.hexdigest()


def all_parameter_sha256(model: UnifiedDecoder) -> str:
    """Hash every model parameter byte in stable name order for matched-arm genesis."""

    parameters = sorted(model.named_parameters())
    if not parameters:
        raise RuntimeError("packed model parameter set is empty")
    digest = hashlib.sha256()
    for name, parameter in parameters:
        digest.update(name.encode("utf-8"))
        _hash_tensor(digest, parameter)
    return digest.hexdigest()


def _hash_optimizer_value(digest: Any, value: object) -> None:
    if isinstance(value, torch.Tensor):
        digest.update(b"tensor:")
        _hash_tensor(digest, value)
    elif isinstance(value, Mapping):
        digest.update(b"mapping:")
        for key in sorted(value, key=lambda item: str(item)):
            digest.update(str(key).encode("utf-8"))
            _hash_optimizer_value(digest, value[key])
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        digest.update(b"sequence:")
        for item in value:
            _hash_optimizer_value(digest, item)
    else:
        digest.update(_canonical(value))


def active_route_optimizer_sha256(
    model: UnifiedDecoder, optimizer: torch.optim.Optimizer,
) -> str:
    names = {id(parameter): name for name, parameter in model.named_parameters()}
    selected: list[tuple[str, torch.Tensor]] = []
    for group in optimizer.param_groups:
        for parameter in group["params"]:
            name = names.get(id(parameter))
            if name is None:
                raise RuntimeError("packed optimizer contains an unnamed parameter")
            if ".experts." not in name or ".experts.audio." in name:
                selected.append((name, parameter))
    digest = hashlib.sha256()
    populated = 0
    for name, parameter in sorted(selected):
        state = optimizer.state.get(parameter)
        if state:
            populated += 1
        digest.update(name.encode("utf-8"))
        _hash_optimizer_value(digest, state or {})
    if populated < 1:
        raise RuntimeError("packed optimizer retained no active-route state")
    return digest.hexdigest()


def _cursor_projection(
    cursor: Mapping[str, object] | None, *, initial: bool = False,
) -> dict[str, int]:
    if cursor is None:
        if not initial:
            raise ValueError("packed cursor projection is absent")
        return {
            "selected_ordinal": 0, "global_step": 0, "tokens_seen": 0,
            "processed_tokens_seen": 0, "pack_ordinal": 0,
        }
    selection_cursor = cursor.get("packed_selection_cursor", cursor)
    if not isinstance(selection_cursor, Mapping):
        raise ValueError("packed cursor lacks its selection projection")
    projected = {
        "selected_ordinal": selection_cursor.get("selected_ordinal"),
        "global_step": cursor.get("global_step", 0),
        "tokens_seen": cursor.get("tokens_seen", 0),
        "processed_tokens_seen": cursor.get("processed_tokens_seen", 0),
        "pack_ordinal": cursor.get("pack_ordinal", 0),
    }
    return _require_cursor(projected, "packed cursor projection")


def _allocate_runtime(
    *, repo_root: Path, seed: int,
) -> tuple[RestartDecoderConfig, UnifiedDecoder, torch.optim.Optimizer, dict[str, object], dict[str, object]]:
    if os.environ.get("EMBER_GATE_AUTHORIZED") != "1":
        raise RuntimeError("packed production launch requires EMBER_GATE_AUTHORIZED=1")
    if not torch.cuda.is_available():
        raise RuntimeError("packed production launch requires CUDA")
    config_path = repo_root / "configs" / "ember-restart-3b.json"
    config = RestartDecoderConfig.from_contract(config_path)
    load_memory_contract(config_path)
    governor = governed_resource_preflight()
    free_bytes, _total_bytes = torch.cuda.mem_get_info()
    total_parameters = config.structural_parameter_count()
    active_parameters = total_parameters - (
        (len(config.expert_names) - 1)
        * config.layers * 12 * config.hidden_size * config.hidden_size
    )
    memory = production_memory_preflight(
        total_parameters=total_parameters,
        active_parameters=active_parameters,
        device_free_bytes=int(free_bytes),
    )
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    previous_dtype = torch.get_default_dtype()
    torch.set_default_dtype(torch.bfloat16)
    try:
        model = UnifiedDecoder(
            config, device="cuda", allow_production_allocation=True,
            genesis_seed=seed,
        )
    finally:
        torch.set_default_dtype(previous_dtype)
    model._activate_expert("audio")
    model.train()
    counts = measure_parameter_counts(model)
    if counts["unique_parameters"] != 3_839_161_856 or counts["active_parameters"] != 1_725_232_640:
        raise RuntimeError("packed runtime instantiated the wrong model capacity")
    optimizer = build_production_optimizer(
        model, optimizer_contract=load_optimizer_contract(config_path),
    )
    return config, model, optimizer, governor, memory


def release_first_runtime_for_resume(config: RestartDecoderConfig) -> dict[str, object]:
    """Synchronously return the first CUDA runtime before resume allocation."""

    if not torch.cuda.is_available():
        raise RuntimeError("packed durable resume release requires CUDA")
    torch.cuda.synchronize()
    collected = gc.collect()
    torch.cuda.empty_cache()
    torch.cuda.synchronize()
    free_bytes, total_bytes = torch.cuda.mem_get_info()
    total_parameters = config.structural_parameter_count()
    active_parameters = total_parameters - (
        (len(config.expert_names) - 1)
        * config.layers * 12 * config.hidden_size * config.hidden_size
    )
    memory = production_memory_preflight(
        total_parameters=total_parameters,
        active_parameters=active_parameters,
        device_free_bytes=int(free_bytes),
    )
    return {
        "schema_version": "ember-packed-runtime-release-v1",
        "status": "PASS",
        "gc_collected": int(collected),
        "post_release_free_bytes": int(free_bytes),
        "device_total_bytes": int(total_bytes),
        "production_memory_preflight": memory,
    }


def checkpoint_serialized_bytes_from_writer_receipt(
    writer_receipt: Mapping[str, object],
) -> int:
    """Use the final admission receipt field that is intentionally out-of-manifest."""

    serialized_bytes = writer_receipt.get("serialized_bytes")
    if type(serialized_bytes) is not int or serialized_bytes < 1:
        raise ValueError("checkpoint writer receipt lacks serialized bytes")
    return serialized_bytes


def _rng_state(device: torch.device) -> dict[str, torch.Tensor]:
    return {
        "cpu": torch.get_rng_state().clone(),
        "cuda": torch.cuda.get_rng_state(device).clone(),
    }


def run_durable_resume_leg(args: argparse.Namespace) -> dict[str, object]:
    """Publish the sole durable pack-1 checkpoint and prove exact pack-2 resume."""

    if args.live is not True:
        raise RuntimeError("packed durable resume leg requires explicit --live")
    repo_root = args.repo_root.resolve(strict=True)
    artifact_root = args.artifact_root.resolve(strict=True)
    checkpoint_root = artifact_root / "checkpoint-after-audio64-pack-1"
    proof_path = artifact_root / "packed-resume-equivalence.json"
    if checkpoint_root.exists() or proof_path.exists():
        raise FileExistsError("refusing to overwrite packed durable resume custody")
    canonical_runner, custody_root = _canonical_disk_budget_runner_authority()
    if not artifact_root.is_relative_to(custody_root):
        raise ValueError("packed durable artifact root escapes canonical runner custody")
    b_floor_start = require_b_execution_floor()
    config_path = repo_root / "configs" / "ember-restart-3b.json"
    config_sha256 = _sha256_path(config_path)
    density, _authority = load_packed_activation_authority(
        census_path=args.census,
        expected_census_raw_sha256=args.census_raw_sha256,
        expected_census_self_sha256=args.census_self_sha256,
        density_path=args.density,
        expected_density_raw_sha256=args.density_raw_sha256,
        expected_density_self_sha256=args.density_self_sha256,
        source_commit=args.source_commit,
        model_config_sha256=config_sha256,
    )
    selection = _open_selection(
        repo_root=repo_root,
        manifest_path=args.stream_manifest.resolve(strict=True),
        manifest_sha256=args.stream_manifest_sha256,
        build_receipt_path=args.stream_build_receipt.resolve(strict=True),
        build_receipt_sha256=args.stream_build_receipt_sha256,
    )
    execution = prepare_packed_execution_slice(
        selection=selection,
        config=RestartDecoderConfig.from_contract(config_path),
        device=torch.device("cpu"), packs=2,
    )
    if (
        execution["pack_signatures"][0] != density["pack_signature_sha256"]
        or execution["pack_record_order_sha256"][0] != density["record_order_sha256"]
        or execution["pack_tokens_sha256"][0] != density["tokens_sha256"]
    ):
        raise ValueError("packed durable execution does not begin at the census-bound pack")
    identity = {
        "source_commit": args.source_commit,
        "runner_source_sha256": _sha256_path(Path(__file__)),
        "model_config_sha256": config_sha256,
        "stream_manifest_sha256": args.stream_manifest_sha256,
        "stream_build_receipt_sha256": args.stream_build_receipt_sha256,
        "selection_receipt_sha256": density["selection_receipt_sha256"],
        "density_raw_sha256": args.density_raw_sha256,
        "density_self_sha256": args.density_self_sha256,
        "census_raw_sha256": args.census_raw_sha256,
        "census_self_sha256": args.census_self_sha256,
        "execution_record_order_sha256": execution["execution_record_order_sha256"],
        "execution_tokens_sha256": execution["execution_tokens_sha256"],
        "pack_sequence_sha256": execution["pack_sequence_sha256"],
        "genesis_lineage_sha256": packed_genesis_lineage_sha256(
            source_commit=args.source_commit,
            model_config_sha256=config_sha256,
            seed=args.seed,
        ),
        "lineage_mode": "FRESH_GENESIS_NO_EXTERNAL_PREDECESSOR",
        "seed": args.seed,
        "initial_cursor": _cursor_projection(None, initial=True),
        "pack_records": 64,
    }
    config: RestartDecoderConfig | None = None
    model: UnifiedDecoder | None = None
    optimizer: torch.optim.Optimizer | None = None
    checkpoint: dict[str, object] | None = None
    counter_receipt: dict[str, object] | None = None
    first_governor: dict[str, object] | None = None
    first_memory: dict[str, object] | None = None
    live_model: UnifiedDecoder | None = None
    live_optimizer: torch.optim.Optimizer | None = None
    checkpoint_callback: Any = None
    uninterrupted_segment: dict[str, Any] | None = None
    try:
        config, model, optimizer, first_governor, first_memory = _allocate_runtime(
            repo_root=repo_root, seed=args.seed,
        )
        live_model = model
        live_optimizer = optimizer
        if live_model is None or live_optimizer is None:
            raise RuntimeError("packed durable runtime allocation disappeared")
        genesis_hashes = live_model.expert_bank_genesis_hashes()
        optimizer_contract = load_optimizer_contract(config_path)
        integration_contract = repo_root / "docs" / "domains" / "governance" / "ember-restart" / "integration-contract-v1.md"

        def checkpoint_callback(
            global_step: int,
            state: dict[str, Any],
            bound_model: UnifiedDecoder = live_model,
            bound_optimizer: torch.optim.Optimizer = live_optimizer,
        ) -> None:
            nonlocal checkpoint, counter_receipt
            if global_step != 1:
                return
            if checkpoint is not None:
                raise RuntimeError("packed durable leg attempted a second checkpoint")
            b_floor_before_checkpoint = require_b_execution_floor()
            data_cursor = dict(state["data_cursor"])
            data_cursor["input_identity_receipt_sha256"] = density["selection_receipt_sha256"]
            data_cursor["genesis_lineage_sha256"] = identity["genesis_lineage_sha256"]
            data_cursor["governor"] = first_governor
            data_cursor["b_floor_preflight"] = b_floor_before_checkpoint
            fresh_genesis_lineage = build_packed_fresh_genesis_specialist_lineage(
                source_commit=args.source_commit,
                model_config_sha256=config_sha256,
                seed=args.seed,
                active_expert="audio",
                selection_receipt_sha256=density["selection_receipt_sha256"],
                execution_record_order_sha256=execution["execution_record_order_sha256"],
                execution_tokens_sha256=execution["execution_tokens_sha256"],
                pack_sequence_sha256=execution["pack_sequence_sha256"],
                initial_cursor=identity["initial_cursor"],
                checkpoint_cursor=_cursor_projection(data_cursor),
            )
            verified_holder: dict[str, object] = {}

            def verify_staging(staging_root: Path, _manifest: dict[str, object]) -> dict[str, object]:
                verified = _execute_realization_counter(
                    root=repo_root, config_path=config_path,
                    checkpoint_manifest_path=staging_root / "checkpoint-manifest.json",
                    active_expert="audio",
                    expected_counts=measure_parameter_counts(bound_model),
                )
                _atomic_json(staging_root / _COUNTER_SUCCESS_RECEIPT, verified)
                require_counter_success_receipt(staging_root)
                verified_holder["receipt"] = verified
                return verified

            published = write_checkpoint_artifacts(
                bound_model, bound_optimizer, checkpoint_root,
                launch_seed=args.seed, rng_state=_rng_state(torch.device("cuda")),
                data_cursor=data_cursor, model_config_sha256=config_sha256,
                contract_sha256=_sha256_path(integration_contract),
                expert_genesis_sha256=genesis_hashes,
                optimizer_contract=optimizer_contract,
                optimizer_state_layout="owner-sharded-v1",
                specialist_lineage=fresh_genesis_lineage,
                max_serialized_bytes=governed_vertical_checkpoint_byte_bound(config_path),
                max_transient_scratch_bytes=_MAX_TRANSIENT_CHECKPOINT_SCRATCH_BYTES,
                host_commit_reserve_bytes=checkpoint_host_commit_reserve_bytes(config_path),
                pre_publish_verifier=verify_staging,
            )
            checkpoint = dict(published)
            counter_receipt = dict(verified_holder["receipt"])

        torch.cuda.reset_peak_memory_stats()
        uninterrupted_segment = run_packed_selection_pretraining_segment(
            model=live_model, optimizer=live_optimizer, selection=selection, config=config,
            device=torch.device("cuda"), pack_records=64, checkpoint_every=1,
            checkpoint_callback=checkpoint_callback, max_packs=2,
        )
        if checkpoint is None or counter_receipt is None:
            raise RuntimeError("packed durable leg completed without its verified checkpoint")
        uninterrupted = {
            "next_loss": float(uninterrupted_segment["losses"][1]),
            "final_cursor": dict(uninterrupted_segment["data_cursor"]),
            "active_route_parameter_sha256": active_route_parameter_sha256(live_model),
            "active_route_optimizer_sha256": active_route_optimizer_sha256(live_model, live_optimizer),
        }
        first_peak_allocated = int(torch.cuda.max_memory_allocated())
        first_peak_reserved = int(torch.cuda.max_memory_reserved())
    finally:
        checkpoint_callback = None
        uninterrupted_segment = None
        del live_optimizer
        del live_model
        del optimizer
        del model
        if config is not None:
            first_runtime_release = release_first_runtime_for_resume(config)

    reopened_checkpoint = published_checkpoint_receipt(checkpoint_root)
    if reopened_checkpoint["checkpoint_manifest_sha256"] != checkpoint["checkpoint_manifest_sha256"]:
        raise RuntimeError("packed durable checkpoint did not reopen to its published identity")
    b_floor_after_checkpoint = require_b_execution_floor()
    resume_model: UnifiedDecoder | None = None
    resume_optimizer: torch.optim.Optimizer | None = None
    try:
        torch.cuda.reset_peak_memory_stats()
        resume_config, resume_model, resume_optimizer, resume_governor, resume_memory = _allocate_runtime(
            repo_root=repo_root, seed=args.seed,
        )
        restored = load_checkpoint_artifacts(
            resume_model, resume_optimizer, checkpoint_root, reopened_checkpoint,
        )
        checkpoint_cursor = dict(restored["data_cursor"])
        resumed_segment = run_packed_selection_pretraining_segment(
            model=resume_model, optimizer=resume_optimizer, selection=selection,
            config=resume_config, device=torch.device("cuda"), pack_records=64,
            checkpoint_every=2, checkpoint_callback=lambda _step, _state: None,
            initial_selection_cursor=checkpoint_cursor["packed_selection_cursor"],
            initial_global_step=int(checkpoint_cursor["global_step"]),
            initial_tokens_seen=int(checkpoint_cursor["tokens_seen"]),
            initial_processed_tokens_seen=int(checkpoint_cursor["processed_tokens_seen"]),
            initial_pack_ordinal=int(checkpoint_cursor["pack_ordinal"]),
            max_packs=1,
        )
        resumed = {
            "next_loss": float(resumed_segment["losses"][0]),
            "final_cursor": dict(resumed_segment["data_cursor"]),
            "active_route_parameter_sha256": active_route_parameter_sha256(resume_model),
            "active_route_optimizer_sha256": active_route_optimizer_sha256(resume_model, resume_optimizer),
        }
        runtime_custody = {
            "canonical_disk_budget_runner": canonical_runner,
            "b_floor_at_start": b_floor_start,
            "b_floor_after_checkpoint": b_floor_after_checkpoint,
            "first_governor": first_governor,
            "first_memory_preflight": first_memory,
            "first_runtime_release": first_runtime_release,
            "resume_governor": resume_governor,
            "resume_memory_preflight": resume_memory,
            "first_peak_memory_allocated_bytes": first_peak_allocated,
            "first_peak_memory_reserved_bytes": first_peak_reserved,
            "resume_peak_memory_allocated_bytes": int(torch.cuda.max_memory_allocated()),
            "resume_peak_memory_reserved_bytes": int(torch.cuda.max_memory_reserved()),
        }
        counter_path = checkpoint_root / _COUNTER_SUCCESS_RECEIPT
        checkpoint_serialized_bytes = checkpoint_serialized_bytes_from_writer_receipt(
            checkpoint,
        )
        proof = build_resume_equivalence_receipt(
            identity=identity,
            checkpoint_manifest_sha256=str(reopened_checkpoint["checkpoint_manifest_sha256"]),
            checkpoint_serialized_bytes=checkpoint_serialized_bytes,
            counter_receipt_sha256=_sha256_path(counter_path),
            checkpoint_cursor=checkpoint_cursor,
            uninterrupted=uninterrupted,
            resumed=resumed,
            runtime_custody=runtime_custody,
        )
        raw_sha256, self_sha256 = _write_json_no_replace(proof_path, proof)
        return {
            "result": "DURABLE_RESUME_EQUIVALENCE_PASS",
            "checkpoint_root": str(checkpoint_root),
            "checkpoint_manifest_sha256": reopened_checkpoint["checkpoint_manifest_sha256"],
            "checkpoint_serialized_bytes": checkpoint_serialized_bytes,
            "proof_path": str(proof_path),
            "proof_raw_sha256": raw_sha256,
            "proof_self_sha256": self_sha256,
        }
    finally:
        del resume_optimizer
        del resume_model
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()


def run_formal_packed_arm(
    args: argparse.Namespace, *, accelerated: bool,
    diagnostic_graph_bf16: bool = False,
) -> dict[str, object]:
    """Execute one receipt-only matched arm from deterministic fresh genesis."""

    if args.live is not True:
        raise RuntimeError("packed formal arm requires explicit --live")
    if type(args.packs) is not int or args.packs < 2:
        raise ValueError("packed formal arm requires at least two measured packs")
    repo_root = args.repo_root.resolve(strict=True)
    artifact_root = args.artifact_root.resolve(strict=True)
    if accelerated and diagnostic_graph_bf16:
        raise ValueError("packed formal arm modes are mutually exclusive")
    arm_output = artifact_root / (
        "packed-graph-bf16-diagnostic.json" if diagnostic_graph_bf16
        else "packed-stage2-arm.json" if accelerated else "packed-bf16-arm.json"
    )
    if arm_output.exists():
        raise FileExistsError(f"refusing to overwrite packed arm receipt: {arm_output}")
    canonical_runner, custody_root = _canonical_disk_budget_runner_authority()
    if not artifact_root.is_relative_to(custody_root):
        raise ValueError("packed arm artifact root escapes canonical runner custody")
    b_floor = require_b_execution_floor()
    config_path = repo_root / "configs" / "ember-restart-3b.json"
    config_sha256 = _sha256_path(config_path)
    density, authority = load_packed_activation_authority(
        census_path=args.census,
        expected_census_raw_sha256=args.census_raw_sha256,
        expected_census_self_sha256=args.census_self_sha256,
        density_path=args.density,
        expected_density_raw_sha256=args.density_raw_sha256,
        expected_density_self_sha256=args.density_self_sha256,
        source_commit=args.source_commit,
        model_config_sha256=config_sha256,
    )
    selection = _open_selection(
        repo_root=repo_root,
        manifest_path=args.stream_manifest.resolve(strict=True),
        manifest_sha256=args.stream_manifest_sha256,
        build_receipt_path=args.stream_build_receipt.resolve(strict=True),
        build_receipt_sha256=args.stream_build_receipt_sha256,
    )
    config_for_slice = RestartDecoderConfig.from_contract(config_path)
    execution = prepare_packed_execution_slice(
        selection=selection, config=config_for_slice,
        device=torch.device("cpu"), packs=args.packs,
    )
    if (
        execution["pack_signatures"][0] != density["pack_signature_sha256"]
        or execution["pack_record_order_sha256"][0] != density["record_order_sha256"]
        or execution["pack_tokens_sha256"][0] != density["tokens_sha256"]
    ):
        raise ValueError("packed formal execution does not begin at the census-bound pack")
    initial_cursor = _cursor_projection(None, initial=True)
    identity = {
        "source_commit": args.source_commit,
        "runner_source_sha256": _sha256_path(Path(__file__)),
        "model_config_sha256": config_sha256,
        "stream_manifest_sha256": args.stream_manifest_sha256,
        "stream_build_receipt_sha256": args.stream_build_receipt_sha256,
        "selection_receipt_sha256": density["selection_receipt_sha256"],
        "density_raw_sha256": args.density_raw_sha256,
        "density_self_sha256": args.density_self_sha256,
        "census_raw_sha256": args.census_raw_sha256,
        "census_self_sha256": args.census_self_sha256,
        "execution_record_order_sha256": execution["execution_record_order_sha256"],
        "execution_tokens_sha256": execution["execution_tokens_sha256"],
        "pack_sequence_sha256": execution["pack_sequence_sha256"],
        "genesis_lineage_sha256": packed_genesis_lineage_sha256(
            source_commit=args.source_commit,
            model_config_sha256=config_sha256,
            seed=args.seed,
        ),
        "lineage_mode": "FRESH_GENESIS_NO_EXTERNAL_PREDECESSOR",
        "seed": args.seed,
        "initial_cursor": initial_cursor,
        "pack_records": 64,
    }
    model: UnifiedDecoder | None = None
    optimizer: torch.optim.Optimizer | None = None
    try:
        config, model, optimizer, governor, memory = _allocate_runtime(
            repo_root=repo_root, seed=args.seed,
        )
        stage2_executor = (
            CensusBoundStage2Executor(
                model=model, optimizer=optimizer, config=config,
                authority=authority,
                diagnostic_bf16_down=diagnostic_graph_bf16,
            )
            if accelerated or diagnostic_graph_bf16 else None
        )
        torch.cuda.reset_peak_memory_stats()
        segment = run_packed_selection_pretraining_segment(
            model=model, optimizer=optimizer, selection=selection,
            config=config, device=torch.device("cuda"), pack_records=64,
            checkpoint_every=args.packs + 1,
            checkpoint_callback=lambda _step, _state: None,
            max_packs=args.packs,
            stage2_executor=stage2_executor,
            measurement_preparation_regions_per_signature=4,
            measure_single_record_reference=not accelerated and not diagnostic_graph_bf16,
        )
        runtime = segment["stage2_runtime"]
        runtime_custody = {
            "canonical_disk_budget_runner": canonical_runner,
            "b_floor_preflight": b_floor,
            "governor": governor,
            "memory_preflight": memory,
        }
        if diagnostic_graph_bf16:
            receipt = build_packed_graph_bf16_diagnostic_receipt(
                identity=identity, segment=segment, runtime_custody=runtime_custody,
            )
            raw_sha256, self_sha256 = _write_json_no_replace(arm_output, receipt)
            return {
                "result": "PACKED_GRAPH_BF16_DIAGNOSTIC_COMPLETE",
                "receipt_path": str(arm_output),
                "receipt_raw_sha256": raw_sha256,
                "receipt_self_sha256": self_sha256,
                "losses": receipt["losses"],
            }
        mechanisms = (
            {
                "fp8_dispatches": int(runtime["fp8_dispatches"]),
                "fp8_fallbacks": int(runtime["fp8_fallbacks"]),
                "cuda_graph_captures": int(runtime["cuda_graph_captures"]),
                "cuda_graph_replays": int(runtime["cuda_graph_replays"]),
                "cuda_graph_fallbacks": int(runtime["cuda_graph_fallbacks"]),
                "captures_during_preparation": int(runtime["captures_during_preparation"]),
                "captures_during_measured_window": int(runtime["captures_during_measured_window"]),
            }
            if accelerated
            else {key: 0 for key in _MECHANISM_KEYS}
        )
        receipt = build_packed_arm_receipt(
            arm="census_bound_stage2" if accelerated else "bf16_packed_eager",
            identity=identity,
            steps=int(segment["steps"]),
            true_source_tokens=int(segment["tokens_seen"]),
            processed_padded_tokens=int(segment["processed_tokens_seen"]),
            padding_tokens=int(segment["processed_tokens_seen"]) - int(segment["tokens_seen"]),
            losses=segment["losses"],
            single_record_reference_losses=segment["single_record_reference_losses"],
            step_timings_seconds=segment["step_timings_seconds"],
            max_memory_allocated_bytes=int(torch.cuda.max_memory_allocated()),
            max_memory_reserved_bytes=int(torch.cuda.max_memory_reserved()),
            mechanisms=mechanisms,
            fp8_installation=(
                runtime["fp8_installation"]
                if accelerated else disabled_fp8_installation_receipt()
            ),
            measurement_preparation=segment["measurement_preparation"],
            final_cursor=_cursor_projection(segment["data_cursor"]),
            runtime_custody=runtime_custody,
        )
        raw_sha256, self_sha256 = _write_json_no_replace(arm_output, receipt)
        return {
            "result": "FORMAL_ARM_COMPLETE",
            "arm": receipt["arm"], "receipt_path": str(arm_output),
            "receipt_raw_sha256": raw_sha256,
            "receipt_self_sha256": self_sha256,
            "true_tokens_per_second": receipt["true_tokens_per_second"],
        }
    finally:
        del optimizer
        del model
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()


def run_issue1946_profile(
    args: argparse.Namespace, *, mode: str,
) -> dict[str, object]:
    """Run the fixed preflight/arms or the stack-ledger measurement successor."""

    allowed_modes = set(ISSUE_PROFILE_MODES)
    if mode not in allowed_modes:
        raise ValueError("unknown #1946 profile mode")
    issue2024 = mode.startswith("issue2024-")
    successor_mode = issue2024_profile_mode(mode) if issue2024 else None
    policy_mode = successor_mode["policy_mode"] if successor_mode is not None else mode
    if args.live is not True:
        raise RuntimeError("#1946 profile execution requires explicit --live")
    repo_root = args.repo_root.resolve(strict=True)
    artifact_root = args.artifact_root.resolve(strict=True)
    canonical_runner, custody_root = _canonical_disk_budget_runner_authority()
    if not artifact_root.is_relative_to(custody_root):
        raise ValueError("#1946 artifact root escapes canonical runner custody")
    output_name = successor_mode["output_name"] if successor_mode is not None else {
        "issue1946-preflight": "issue1946-instrument-preflight.json",
        "issue1946-arm-a": "issue1946-arm-a-recompute-on.json",
        "issue1946-arm-b": "issue1946-arm-b-recompute-off.json",
    }[policy_mode]
    output_path = artifact_root / output_name
    trace_path = output_path.with_suffix(".profiler-trace.json")
    if output_path.exists() or trace_path.exists():
        raise FileExistsError("#1946 profile output custody is no-overwrite")
    b_floor = require_b_execution_floor()
    config_path = repo_root / "configs" / "ember-restart-3b.json"
    config_sha256 = _sha256_path(config_path)
    accounting_path = repo_root / "tools" / "ember-restart-3b" / "issue1946-complete-update-accounting.json"
    accounting = load_issue1946_accounting_spec(accounting_path)
    execution_source_commit = verified_execution_source_commit(
        repo_root, args.execution_source_commit,
    )
    authority_crosswalk = load_issue1946_authority_crosswalk(
        repo_root,
        repo_root / "tools" / "ember-restart-3b" / "issue1946-authority-crosswalk.json",
    )
    density, _authority = load_packed_activation_authority(
        census_path=args.census,
        expected_census_raw_sha256=args.census_raw_sha256,
        expected_census_self_sha256=args.census_self_sha256,
        density_path=args.density,
        expected_density_raw_sha256=args.density_raw_sha256,
        expected_density_self_sha256=args.density_self_sha256,
        source_commit=args.source_commit,
        model_config_sha256=config_sha256,
    )
    selection = _open_selection(
        repo_root=repo_root,
        manifest_path=args.stream_manifest.resolve(strict=True),
        manifest_sha256=args.stream_manifest_sha256,
        build_receipt_path=args.stream_build_receipt.resolve(strict=True),
        build_receipt_sha256=args.stream_build_receipt_sha256,
    )
    stream_manifest = json.loads(args.stream_manifest.read_bytes())
    tokenizer_binding = stream_manifest.get("tokenizer")
    tokenizer_sha256 = _require_sha(
        tokenizer_binding.get("sha256") if isinstance(tokenizer_binding, Mapping) else None,
        "#1946 tokenizer",
    )
    selected_count = getattr(selection, "receipt", {}).get("selected_record_count")
    if selected_count != 4096:
        raise ValueError("#1946 requires the exact 4096-record bound selection")
    profile_schedule = issue2024_profile_schedule(mode, policy_mode)
    packs = int(profile_schedule["packs"])
    execution = prepare_packed_execution_slice(
        selection=selection,
        config=RestartDecoderConfig.from_contract(config_path),
        device=torch.device("cpu"),
        packs=packs,
    )
    if execution["start_selected_ordinal"] != 0 or execution["record_count"] != packs * 64:
        raise ValueError("#1946 execution must start at cursor zero without replay")
    if execution["pack_signatures"][0] != density["pack_signature_sha256"]:
        raise ValueError("#1946 execution does not begin on the census-bound audio-64 pack")
    thermal_before = gpu_covariate()
    preflight_binding: dict[str, str] | None = None
    arm_a_binding: dict[str, object] | None = None
    arm_a: dict[str, object] | None = None
    if policy_mode == "issue1946-arm-a":
        preflight_receipt, preflight_raw_sha256 = _load_self_hashed_json(
            args.preflight_receipt, "#1946 preflight receipt",
        )
        preflight = validate_issue1946_preflight_receipt(
            preflight_receipt,
            execution_source_commit=execution_source_commit,
            accounting_spec_sha256=accounting["raw_sha256"],
            gpu_uuid=str(thermal_before["gpu_uuid"]),
        )
        preflight_binding = {
            "preflight_raw_sha256": preflight_raw_sha256,
            "preflight_self_sha256": str(preflight["self_sha256"]),
        }
    if policy_mode == "issue1946-arm-b":
        arm_a_receipt, arm_a_raw_sha256 = _load_self_hashed_json(
            args.arm_a_receipt, "#1946 Arm A receipt",
        )
        arm_a = validate_issue1946_arm_a_receipt(
            arm_a_receipt,
            execution_source_commit=execution_source_commit,
            gpu_uuid=str(thermal_before["gpu_uuid"]),
            current_process_id=os.getpid(),
        )
        first_warmup_temperature_c = float(arm_a["power_rows"][0]["temperature_c"])
        if float(thermal_before["temperature_c"]) > first_warmup_temperature_c + 2.0:
            raise RuntimeError("arm B thermal re-baseline gate is not yet satisfied")
        arm_a_custody = arm_a["runtime_custody"]
        arm_a_binding = {
            "arm_a_raw_sha256": arm_a_raw_sha256,
            "arm_a_self_sha256": str(arm_a["self_sha256"]),
            "preflight_raw_sha256": str(arm_a_custody["preflight_raw_sha256"]),
            "preflight_self_sha256": str(arm_a_custody["preflight_self_sha256"]),
            "arm_a_process_id": int(arm_a_custody["process_id"]),
        }

    model: UnifiedDecoder | None = None
    optimizer: torch.optim.Optimizer | None = None
    try:
        try:
            config, model, optimizer, governor, memory = _allocate_runtime(
                repo_root=repo_root,
                seed=args.seed,
            )
        except MemoryError as error:
            if policy_mode != "issue1946-arm-b" or arm_a is None:
                raise
            required_bytes, free_bytes = _issue1946_safety_margin_failure_bytes(error)
            safety_receipt = build_issue1946_oom_arm_receipt(
                identity=arm_a["identity"],
                completed_updates=0,
                peak_demand_bytes=required_bytes,
                ceiling_bytes=free_bytes,
                first_temperature_c=float(thermal_before["temperature_c"]),
                error_class="SAFETY_MARGIN_FAILURE",
            )
            unsigned = dict(safety_receipt)
            unsigned.pop("self_sha256")
            safety_receipt = {
                **unsigned,
                "runtime_custody": {
                    "canonical_disk_budget_runner": canonical_runner,
                    "b_floor_preflight": b_floor,
                    "process_id": os.getpid(),
                    "fresh_process_and_cuda_context_required": True,
                    "gpu_uuid": thermal_before["gpu_uuid"],
                    "thermal_before_allocation": thermal_before,
                    "accounting_spec_sha256": accounting["raw_sha256"],
                    "authority_crosswalk": authority_crosswalk,
                    "density_source_commit": args.source_commit,
                    **(arm_a_binding or {}),
                },
            }
            safety_receipt["self_sha256"] = hashlib.sha256(_canonical(safety_receipt)).hexdigest()
            raw_sha256, self_sha256 = _write_json_no_replace(output_path, safety_receipt)
            return {
                "result": "ISSUE1946_VALID_ALL_OFF_SAFETY_MARGIN_FAILURE",
                "mode": mode,
                "receipt_path": str(output_path),
                "receipt_raw_sha256": raw_sha256,
                "receipt_self_sha256": self_sha256,
                "measured_vram_gap_bytes": safety_receipt["measured_vram_gap_bytes"],
            }
        if policy_mode == "issue1946-arm-b":
            config = dataclasses.replace(config, gradient_checkpointing=False)
            model.config = config
        expected_checkpointing = policy_mode != "issue1946-arm-b"
        if bool(model.config.gradient_checkpointing) is not expected_checkpointing:
            raise RuntimeError("#1946 recompute policy did not bind every layer")
        parameter_sha256 = all_parameter_sha256(model)
        if optimizer.state:
            raise RuntimeError("#1946 arm optimizer state was not reset")
        optimizer_initial_state_sha256 = hashlib.sha256(_canonical({
            "implementation": type(optimizer).__qualname__,
            "defaults": optimizer.defaults,
            "state_entry_count": 0,
        })).hexdigest()
        cpu_rng_state_sha256 = hashlib.sha256(torch.get_rng_state().numpy().tobytes()).hexdigest()
        cuda_rng_state_sha256 = hashlib.sha256(torch.cuda.get_rng_state(0).cpu().numpy().tobytes()).hexdigest()
        allocator_rows: list[dict[str, object]] = []
        power_rows: list[dict[str, object]] = []
        observed_kernel_rows: list[dict[str, object]] = []
        forward_owner_device_time_us = {owner: 0.0 for owner in _ISSUE1946_FORWARD_OWNERS}
        forward_unmapped_device_time_us = 0.0
        profiler_indexes = list(profile_schedule["update_indexes"])
        issue2024_event_ledger: dict[str, object] | None = None

        def trace_ready(profiler: Any) -> None:
            nonlocal forward_unmapped_device_time_us, issue2024_event_ledger
            unmapped_events: list[Any] = []
            for event in profiler.events():
                name = str(event.key)
                self_device_time_us = float(getattr(event, "self_device_time_total", 0.0))
                inside_forward = _issue1946_event_inside_marker(
                    event, COMPLETE_UPDATE_FORWARD_LOSS_MARKER,
                )
                owner = _issue1946_forward_owner(
                    name, event.input_shapes, hidden=int(config.hidden_size), vocab_size=int(config.vocab_size),
                ) if inside_forward and self_device_time_us > 0 else None
                if inside_forward and self_device_time_us > 0:
                    if owner is None:
                        forward_unmapped_device_time_us += self_device_time_us
                        if issue2024:
                            unmapped_events.append(event)
                    else:
                        forward_owner_device_time_us[owner] += self_device_time_us
                if any(marker in name for marker in ("mm", "addmm", "linear")):
                    observed_kernel_rows.append({
                        "kernel": name,
                        "input_shapes": event.input_shapes,
                        "cpu_time_us": float(event.cpu_time_total),
                        "device_time_us": float(getattr(event, "device_time_total", 0.0)),
                        "self_device_time_us": self_device_time_us,
                        "inside_forward_loss_marker": inside_forward,
                        "forward_owner": owner,
                    })
            if issue2024:
                if issue2024_event_ledger is not None:
                    raise RuntimeError("ISSUE2024_PROFILER_CALLBACK_REPEATED")
                issue2024_event_ledger = build_issue2024_event_ledger(
                    unmapped_events,
                    declared_self_device_time_total_us=str(forward_unmapped_device_time_us),
                )
            # The canonical in-memory ledger is complete before this secondary export.
            profiler.export_chrome_trace(str(trace_path))

        wait_updates = int(profile_schedule["wait"])
        active_updates = int(profile_schedule["active"])
        profiler = torch.profiler.profile(
            activities=[torch.profiler.ProfilerActivity.CPU, torch.profiler.ProfilerActivity.CUDA],
            schedule=torch.profiler.schedule(wait=wait_updates, warmup=0, active=active_updates, repeat=1),
            on_trace_ready=trace_ready,
            **profiler_configuration_for_mode(mode),
        )

        def update_telemetry(_row: Mapping[str, object]) -> None:
            stats = torch.cuda.memory_stats()
            allocated = int(torch.cuda.memory_allocated())
            reserved = int(torch.cuda.memory_reserved())
            allocator_rows.append({
                "allocated": allocated,
                "reserved": reserved,
                "peak_allocated": int(torch.cuda.max_memory_allocated()),
                "peak_reserved": int(torch.cuda.max_memory_reserved()),
                "workspace": int(stats.get("active_bytes.all.current", allocated)) - allocated,
                "graph_pool": int(stats.get("graph_pool_reserved_bytes.all.current", 0)),
                "fragmentation": max(0, reserved - allocated),
            })
            power_rows.append(energy_tracker.capture_update())
            profiler.step()

        torch.cuda.reset_peak_memory_stats()
        energy_tracker = BoardEnergyTracker(interval_seconds=0.25)
        energy_tracker.start()
        profiler.start()
        oom_error: torch.OutOfMemoryError | None = None
        segment: dict[str, object] | None = None
        try:
            try:
                segment = run_packed_selection_pretraining_segment(
                    model=model,
                    optimizer=optimizer,
                    selection=selection,
                    config=config,
                    device=torch.device("cuda"),
                    pack_records=64,
                    checkpoint_every=packs + 1,
                    checkpoint_callback=lambda _step, _state: None,
                    progress_callback=update_telemetry,
                    max_packs=packs,
                    measure_single_record_reference=True,
                    complete_update_data_stall_seconds=(0.1 if policy_mode == "issue1946-preflight" else 0.0),
                    measure_complete_update_cuda_events=True,
                    stream_complete_update_data_readiness=True,
                )
            except torch.OutOfMemoryError as error:
                oom_error = error
        finally:
            try:
                profiler.stop()
            finally:
                energy_tracker.stop()
        if oom_error is not None:
            if policy_mode != "issue1946-arm-b":
                raise oom_error
            match = re.search(r"Tried to allocate ([0-9.]+) (KiB|MiB|GiB)", str(oom_error))
            if match is None:
                raise RuntimeError("all-off OOM did not expose the attempted allocation size") from oom_error
            scale = {"KiB": 1024, "MiB": 1024**2, "GiB": 1024**3}[match.group(2)]
            requested_bytes = math.ceil(float(match.group(1)) * scale)
            ceiling_bytes = int(memory["device_free_bytes"]) - int(memory["runtime_reserve_bytes"])
            peak_demand_bytes = int(torch.cuda.max_memory_reserved()) + requested_bytes
            if peak_demand_bytes <= ceiling_bytes:
                raise RuntimeError("all-off OOM demand/ceiling evidence is internally inconsistent") from oom_error
            oom_receipt = build_issue1946_oom_arm_receipt(
                identity={
                    "execution_source_commit": execution_source_commit,
                    "parameter_sha256": parameter_sha256,
                    "optimizer_initial_state_sha256": optimizer_initial_state_sha256,
                    "cpu_rng_state_sha256": cpu_rng_state_sha256,
                    "cuda_rng_state_sha256": cuda_rng_state_sha256,
                    "config_sha256": config_sha256,
                    "seed": args.seed,
                    "initial_cursor": 0,
                    "selection_receipt_sha256": density["selection_receipt_sha256"],
                    "stream_manifest_sha256": args.stream_manifest_sha256,
                    "stream_build_receipt_sha256": args.stream_build_receipt_sha256,
                    "tokenizer_sha256": tokenizer_sha256,
                    "execution_record_order_sha256": execution["execution_record_order_sha256"],
                    "execution_tokens_sha256": execution["execution_tokens_sha256"],
                },
                completed_updates=len(power_rows),
                peak_demand_bytes=peak_demand_bytes,
                ceiling_bytes=ceiling_bytes,
                first_temperature_c=float(power_rows[0]["temperature_c"] if power_rows else thermal_before["temperature_c"]),
                error_class="torch.OutOfMemoryError",
            )
            oom_unsigned = dict(oom_receipt)
            oom_unsigned.pop("self_sha256")
            oom_receipt = {
                **oom_unsigned,
                "runtime_custody": {
                    "canonical_disk_budget_runner": canonical_runner,
                    "b_floor_preflight": b_floor,
                    "process_id": os.getpid(),
                    "fresh_process_and_cuda_context_required": True,
                    "gpu_uuid": thermal_before["gpu_uuid"],
                    "thermal_before_allocation": thermal_before,
                    "accounting_spec_sha256": accounting["raw_sha256"],
                    "authority_crosswalk": authority_crosswalk,
                    "density_source_commit": args.source_commit,
                    **(arm_a_binding or {}),
                },
            }
            oom_receipt["self_sha256"] = hashlib.sha256(_canonical(oom_receipt)).hexdigest()
            raw_sha256, self_sha256 = _write_json_no_replace(output_path, oom_receipt)
            return {
                "result": "ISSUE1946_VALID_ALL_OFF_OOM",
                "mode": mode,
                "receipt_path": str(output_path),
                "receipt_raw_sha256": raw_sha256,
                "receipt_self_sha256": self_sha256,
                "measured_vram_gap_bytes": oom_receipt["measured_vram_gap_bytes"],
            }
        if segment is None:
            raise RuntimeError("#1946 segment returned no result")
        if not trace_path.exists():
            raise RuntimeError("#1946 profiler did not flush its immutable trace")
        if not observed_kernel_rows:
            raise RuntimeError("#1946 profiler trace contains no actual material linear kernel event")
        if sum(forward_owner_device_time_us.values()) + forward_unmapped_device_time_us <= 0:
            raise RuntimeError("#1946 profiler trace contains no forward-marker device-time evidence")
        if issue2024 and (
            issue2024_event_ledger is None
            or not issue2024_event_ledger.get("events")
            or int(issue2024_event_ledger.get("reconciliation_gap_ns", 2)) > 1
        ):
            raise RuntimeError("ISSUE2024_EVENT_LEDGER_NONTERMINAL")
        trace_sha256 = _sha256_path(trace_path)
        hidden = int(config.hidden_size)
        material_shapes = [
            {"owner": "attention_qkv", "fprop": [64, 15, hidden, 3 * hidden], "dgrad": [64, 15, 3 * hidden, hidden], "wgrad": [hidden, 64 * 15, 3 * hidden]},
            {"owner": "attention_output", "fprop": [64, 15, hidden, hidden], "dgrad": [64, 15, hidden, hidden], "wgrad": [hidden, 64 * 15, hidden]},
            {"owner": "shared_and_audio_swiglu_up_gate", "fprop": [64, 15, hidden, 8 * hidden], "dgrad": [64, 15, 8 * hidden, hidden], "wgrad": [hidden, 64 * 15, 8 * hidden]},
            {"owner": "shared_and_audio_swiglu_down", "fprop": [64, 15, 4 * hidden, hidden], "dgrad": [64, 15, hidden, 4 * hidden], "wgrad": [4 * hidden, 64 * 15, hidden]},
            {"owner": "language_head", "fprop": [64, 15, hidden, int(config.vocab_size)], "dgrad": [64, 15, int(config.vocab_size), hidden], "wgrad": [hidden, 64 * 15, int(config.vocab_size)]},
        ]
        kernel_trace = {
            "sha256": trace_sha256,
            "path": trace_path.name,
            "layer_count": int(config.layers),
            "material_linear_shapes": material_shapes,
            "observed_kernels": observed_kernel_rows,
            "forward_owner_device_time_us": forward_owner_device_time_us,
            "forward_unmapped_device_time_us": forward_unmapped_device_time_us,
            "owner_weight_provenance": {
                "source_rows": "PROFILER_INSTRUMENTED_ONLY",
                "update_indexes": profiler_indexes,
                "marker": COMPLETE_UPDATE_FORWARD_LOSS_MARKER,
                "deduplication_metric": "self_device_time_total",
                "excluded_markers": [
                    COMPLETE_UPDATE_BACKWARD_MARKER,
                    COMPLETE_UPDATE_GRADIENT_CLIPPING_MARKER,
                    COMPLETE_UPDATE_OPTIMIZER_MARKER,
                ],
            },
        }
        if issue2024:
            kernel_trace["full_precision_unmapped_event_ledger"] = issue2024_event_ledger
        identity = {
            "execution_source_commit": execution_source_commit,
            "parameter_sha256": parameter_sha256,
            "optimizer_initial_state_sha256": optimizer_initial_state_sha256,
            "cpu_rng_state_sha256": cpu_rng_state_sha256,
            "cuda_rng_state_sha256": cuda_rng_state_sha256,
            "config_sha256": config_sha256,
            "seed": args.seed,
            "initial_cursor": 0,
            "selection_receipt_sha256": density["selection_receipt_sha256"],
            "stream_manifest_sha256": args.stream_manifest_sha256,
            "stream_build_receipt_sha256": args.stream_build_receipt_sha256,
            "tokenizer_sha256": tokenizer_sha256,
            "execution_record_order_sha256": execution["execution_record_order_sha256"],
            "execution_tokens_sha256": execution["execution_tokens_sha256"],
        }
        if policy_mode == "issue1946-preflight":
            event_seconds = segment["complete_update_cuda_event_seconds"][0]
            receipt = build_issue1946_preflight_receipt(
                identity={
                    "execution_source_commit": execution_source_commit,
                    "accounting_spec_sha256": accounting["raw_sha256"],
                },
                update_seconds=float(segment["step_timings_seconds"][0]),
                phase_seconds=segment["complete_update_phase_timings_seconds"][0],
                injected_data_stall_seconds=0.1,
                instruments={
                    "profiler": {"status": "PASS", "trace_sha256": trace_sha256},
                    "allocator": {"status": "PASS", "row": allocator_rows[0]},
                    "power": {"status": "PASS", "row": power_rows[0]},
                    "event": {"status": "PASS", "cuda_event_seconds": event_seconds},
                    "identity": {"status": "PASS", "parameter_sha256": parameter_sha256},
                    "receipt": {"status": "PASS", "no_overwrite": True},
                },
            )
            unsigned = dict(receipt)
            unsigned.pop("self_sha256")
            receipt = {
                **unsigned,
                "authority_crosswalk": authority_crosswalk,
                "complete_update_timing_boundary": segment["complete_update_timing_boundary"],
            }
            receipt["self_sha256"] = hashlib.sha256(_canonical(receipt)).hexdigest()
        else:
            receipt = build_issue1946_arm_receipt(
                policy="WHOLE_LAYER_RECOMPUTE" if policy_mode == "issue1946-arm-a" else "DISABLED_EVERY_LAYER",
                identity=identity,
                update_seconds=segment["step_timings_seconds"],
                phase_seconds=segment["complete_update_phase_timings_seconds"],
                profiler_update_indexes=profiler_indexes,
                allocator_rows=allocator_rows,
                power_rows=power_rows,
                kernel_trace=kernel_trace,
                checkpoint_cadence={
                    "in_measured_window": "NONE",
                    "checkpoint_every_updates": packs + 1,
                    "callback_identity": "NO_OP",
                    "final_callback_timed": False,
                },
            )
            receipt["runtime_custody"] = {
                "canonical_disk_budget_runner": canonical_runner,
                "b_floor_preflight": b_floor,
                "process_id": os.getpid(),
                "fresh_process_and_cuda_context_required": True,
                "gpu_uuid": thermal_before["gpu_uuid"],
                "governor": governor,
                "memory_preflight": memory,
                "thermal_before_allocation": thermal_before,
                "execution_record_order_sha256": execution["execution_record_order_sha256"],
                "execution_tokens_sha256": execution["execution_tokens_sha256"],
                "accounting_spec_sha256": accounting["raw_sha256"],
                "authority_crosswalk": authority_crosswalk,
                "density_source_commit": args.source_commit,
                "cuda_event_seconds": segment["complete_update_cuda_event_seconds"],
                "complete_update_timing_boundary": segment["complete_update_timing_boundary"],
                **(preflight_binding or {}),
                **(arm_a_binding or {}),
            }
            unsigned = dict(receipt)
            unsigned.pop("self_sha256")
            receipt = dict(unsigned)
            if issue2024:
                receipt["claim_boundary"] = (
                    "ISSUE2024_MEASUREMENT_IDENTITY_ONLY_NO_SPEEDUP_TREATMENT_VALIDITY_"
                    "LEARNING_20K_PARENT_CLOSE_OR_CAMPAIGN_CREDIT"
                )
            receipt["self_sha256"] = hashlib.sha256(_canonical(receipt)).hexdigest()
        raw_sha256, self_sha256 = _write_json_no_replace(output_path, receipt)
        return {
            "result": "ISSUE2024_STACK_LEDGER_COMPLETE" if issue2024 else "ISSUE1946_PROFILE_COMPLETE",
            "mode": mode,
            "receipt_path": str(output_path),
            "receipt_raw_sha256": raw_sha256,
            "receipt_self_sha256": self_sha256,
            "profiler_trace_sha256": trace_sha256,
            "arm_a_first_warmup_temperature_c": (
                power_rows[0]["temperature_c"] if policy_mode == "issue1946-arm-a" else None
            ),
        }
    finally:
        del optimizer
        del model
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()


def preflight_packed_runtime(args: argparse.Namespace) -> dict[str, object]:
    """CPU-only closure of exact execution and authority inputs."""

    repo_root = args.repo_root.resolve(strict=True)
    config_path = repo_root / "configs" / "ember-restart-3b.json"
    config_sha256 = _sha256_path(config_path)
    density, authority = load_packed_activation_authority(
        census_path=args.census,
        expected_census_raw_sha256=args.census_raw_sha256,
        expected_census_self_sha256=args.census_self_sha256,
        density_path=args.density,
        expected_density_raw_sha256=args.density_raw_sha256,
        expected_density_self_sha256=args.density_self_sha256,
        source_commit=args.source_commit,
        model_config_sha256=config_sha256,
    )
    selection = _open_selection(
        repo_root=repo_root,
        manifest_path=args.stream_manifest.resolve(strict=True),
        manifest_sha256=args.stream_manifest_sha256,
        build_receipt_path=args.stream_build_receipt.resolve(strict=True),
        build_receipt_sha256=args.stream_build_receipt_sha256,
    )
    packs = 2 if args.command == "durable-preflight" else args.packs
    execution = prepare_packed_execution_slice(
        selection=selection,
        config=RestartDecoderConfig.from_contract(config_path),
        device=torch.device("cpu"), packs=packs,
    )
    if (
        execution["pack_signatures"][0] != density["pack_signature_sha256"]
        or execution["pack_record_order_sha256"][0] != density["record_order_sha256"]
        or execution["pack_tokens_sha256"][0] != density["tokens_sha256"]
    ):
        raise ValueError("packed runtime preflight does not begin at the census-bound pack")
    return {
        "decision": "PREFLIGHT_ONLY",
        "mode": args.command,
        "source_commit": args.source_commit,
        "runner_source_sha256": _sha256_path(Path(__file__)),
        "model_config_sha256": config_sha256,
        "census_raw_sha256": authority.census_raw_sha256,
        "census_self_sha256": authority.census_self_sha256,
        "density_raw_sha256": args.density_raw_sha256,
        "density_self_sha256": args.density_self_sha256,
        "execution": execution,
        "genesis_lineage_sha256": packed_genesis_lineage_sha256(
            source_commit=args.source_commit,
            model_config_sha256=config_sha256,
            seed=args.seed,
        ),
        "b_floor_preflight": require_b_execution_floor(),
        "checkpoint_byte_bound": governed_vertical_checkpoint_byte_bound(config_path),
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def compare_packed_paths(
    baseline_path: Path, accelerated_path: Path, output_path: Path,
) -> dict[str, object]:
    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite packed comparison: {output_path}")
    try:
        baseline_raw = baseline_path.read_bytes()
        accelerated_raw = accelerated_path.read_bytes()
        baseline = json.loads(baseline_raw)
        accelerated = json.loads(accelerated_raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("packed arm receipt is not readable strict JSON") from error
    comparison = build_packed_comparison(baseline, accelerated)
    unsigned = dict(comparison)
    unsigned.pop("self_sha256")
    unsigned["baseline_raw_sha256"] = hashlib.sha256(baseline_raw).hexdigest()
    unsigned["accelerated_raw_sha256"] = hashlib.sha256(accelerated_raw).hexdigest()
    unsigned["self_sha256"] = hashlib.sha256(_canonical(unsigned)).hexdigest()
    _write_json_no_replace(output_path, unsigned)
    return unsigned


def _add_runtime_arguments(parser: argparse.ArgumentParser, *, packs: bool) -> None:
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path)
    parser.add_argument("--stream-manifest", type=Path, required=True)
    parser.add_argument("--stream-manifest-sha256", required=True)
    parser.add_argument("--stream-build-receipt", type=Path, required=True)
    parser.add_argument("--stream-build-receipt-sha256", required=True)
    parser.add_argument("--census", type=Path, required=True)
    parser.add_argument("--census-raw-sha256", required=True)
    parser.add_argument("--census-self-sha256", required=True)
    parser.add_argument("--density", type=Path, required=True)
    parser.add_argument("--density-raw-sha256", required=True)
    parser.add_argument("--density-self-sha256", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--seed", type=int, required=True)
    if packs:
        parser.add_argument("--packs", type=int, required=True)
    parser.add_argument("--live", action="store_true")


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in (
        "durable-preflight", "formal-preflight", "durable-bf16",
        "bf16", "stage2", "diagnostic-graph-bf16",
        *ISSUE_PROFILE_MODES,
    ):
        child = subparsers.add_parser(name)
        _add_runtime_arguments(
            child,
            packs=name in {"formal-preflight", "bf16", "stage2", "diagnostic-graph-bf16"},
        )
        if name.startswith("issue1946-") or name.startswith("issue2024-"):
            child.add_argument("--execution-source-commit", required=True)
        else:
            child.set_defaults(execution_source_commit=None)
        policy_mode = (
            issue2024_profile_mode(name)["policy_mode"]
            if name.startswith("issue2024-")
            else name
        )
        if policy_mode == "issue1946-arm-a":
            child.add_argument("--preflight-receipt", type=Path, required=True)
        else:
            child.set_defaults(preflight_receipt=None)
        if policy_mode == "issue1946-arm-b":
            child.add_argument("--arm-a-receipt", type=Path, required=True)
        else:
            child.set_defaults(arm_a_receipt=None)
    compare = subparsers.add_parser("compare")
    compare.add_argument("--baseline", type=Path, required=True)
    compare.add_argument("--accelerated", type=Path, required=True)
    compare.add_argument("--output", type=Path, required=True)
    issue1946_compare = subparsers.add_parser("issue1946-compare")
    issue1946_compare.add_argument("--arm-a", type=Path, required=True)
    issue1946_compare.add_argument("--arm-b", type=Path, required=True)
    issue1946_compare.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    parser = _build_argument_parser()
    args = parser.parse_args()
    if args.command in {"durable-preflight", "formal-preflight"}:
        if args.artifact_root is not None or args.live:
            parser.error("preflight commands cannot accept --artifact-root or --live")
        result = preflight_packed_runtime(args)
    elif args.command == "durable-bf16":
        if args.artifact_root is None:
            parser.error("durable-bf16 requires --artifact-root")
        result = run_durable_resume_leg(args)
    elif args.command in {"bf16", "stage2", "diagnostic-graph-bf16"}:
        if args.artifact_root is None:
            parser.error(f"{args.command} requires --artifact-root")
        result = run_formal_packed_arm(
            args,
            accelerated=args.command == "stage2",
            diagnostic_graph_bf16=args.command == "diagnostic-graph-bf16",
        )
    elif args.command in ISSUE_PROFILE_MODES:
        if args.artifact_root is None:
            parser.error(f"{args.command} requires --artifact-root")
        result = run_issue1946_profile(args, mode=args.command)
    elif args.command == "issue1946-compare":
        if args.output.exists():
            parser.error("issue1946 comparison output is no-overwrite")
        arm_a_raw = args.arm_a.read_bytes()
        arm_b_raw = args.arm_b.read_bytes()
        comparison_receipt = build_issue1946_comparison_receipt(
            json.loads(arm_a_raw),
            json.loads(arm_b_raw),
            arm_a_raw_sha256=hashlib.sha256(arm_a_raw).hexdigest(),
        )
        comparison_receipt["arm_a_raw_sha256"] = hashlib.sha256(arm_a_raw).hexdigest()
        comparison_receipt["arm_b_raw_sha256"] = hashlib.sha256(arm_b_raw).hexdigest()
        unsigned = dict(comparison_receipt)
        unsigned.pop("self_sha256")
        comparison_receipt = dict(unsigned)
        comparison_receipt["self_sha256"] = hashlib.sha256(_canonical(comparison_receipt)).hexdigest()
        _write_json_no_replace(args.output, comparison_receipt)
        result = comparison_receipt
    else:
        result = compare_packed_paths(args.baseline, args.accelerated, args.output)
    print(json.dumps(result, sort_keys=True))
    return 0


def build_packed_comparison(
    baseline: Mapping[str, object], accelerated: Mapping[str, object],
) -> dict[str, object]:
    """Compare matched packed arms and enforce the strict true-token close gate."""

    baseline_value = _validate_arm_receipt(baseline, "packed baseline")
    accelerated_value = _validate_arm_receipt(accelerated, "packed accelerated")
    if baseline_value.get("arm") != "bf16_packed_eager" or accelerated_value.get("arm") != "census_bound_stage2":
        raise ValueError("packed comparison requires BF16 baseline and census-bound Stage-2 arms")
    matched_keys = _IDENTITY_KEYS | {
        "steps", "true_source_tokens", "processed_padded_tokens", "padding_tokens",
        "final_cursor", "claim_boundary", "measurement_preparation",
    }
    if any(baseline_value.get(key) != accelerated_value.get(key) for key in matched_keys):
        raise ValueError("packed arm identity does not match")
    mechanisms = accelerated_value.get("mechanisms")
    if not isinstance(mechanisms, Mapping) or mechanisms.get("fp8_fallbacks") != 0 or mechanisms.get("cuda_graph_fallbacks") != 0:
        raise ValueError("packed accelerated arm contains a fallback")
    baseline_losses = baseline_value.get("losses")
    accelerated_losses = accelerated_value.get("losses")
    if not isinstance(baseline_losses, list) or not isinstance(accelerated_losses, list) or len(baseline_losses) != len(accelerated_losses):
        raise ValueError("packed arm loss vectors do not match")
    relative = [abs(float(a) - float(b)) / max(abs(float(b)), 1e-12) for b, a in zip(baseline_losses, accelerated_losses)]
    if any(delta >= 0.01 for delta in relative):
        raise ValueError("packed accelerated losses exceed the matched 1 percent tolerance")
    reference_losses = baseline_value["single_record_reference_losses"]
    reference_relative = [
        abs(float(packed) - float(reference)) / max(abs(float(reference)), 1e-12)
        for packed, reference in zip(baseline_losses, reference_losses, strict=True)
    ]
    rate = float(accelerated_value["true_tokens_per_second"])
    if not rate > 1000.0:
        raise ValueError("issue #1413 close evidence must be greater than 1000 true source tok/s")
    receipt: dict[str, object] = {
        "schema_version": "ember-issue1413-packed-training-ab-v1",
        "status": "PASS",
        "claim_boundary": _CLAIM_BOUNDARY,
        "baseline_receipt_sha256": baseline_value["self_sha256"],
        "accelerated_receipt_sha256": accelerated_value["self_sha256"],
        "matched_identity": {key: baseline_value[key] for key in sorted(matched_keys)},
        "max_relative_loss_delta": max(relative),
        "max_single_record_reference_relative_loss_delta": max(reference_relative),
        "baseline_true_tokens_per_second": baseline_value["true_tokens_per_second"],
        "accelerated_true_tokens_per_second": rate,
        "throughput_speedup": rate / float(baseline_value["true_tokens_per_second"]),
        "close_evidence": {
            "strictly_greater_than_1000_true_tokens_per_second": True,
            "padding_excluded": True,
            "zero_fallbacks": True,
            "matched_loss_within_one_percent": True,
            "unchanged_single_record_reference_within_one_percent": True,
        },
    }
    receipt["self_sha256"] = hashlib.sha256(_canonical(receipt)).hexdigest()
    return receipt


def build_resume_equivalence_receipt(
    *, identity: Mapping[str, object], checkpoint_manifest_sha256: str,
    checkpoint_serialized_bytes: int, counter_receipt_sha256: str,
    checkpoint_cursor: Mapping[str, object], uninterrupted: Mapping[str, object],
    resumed: Mapping[str, object], runtime_custody: Mapping[str, object],
) -> dict[str, object]:
    """Prove the sole durable checkpoint reproduces the uninterrupted next pack."""

    bound_identity = _validate_identity(identity)
    for value, label in (
        (checkpoint_manifest_sha256, "resume checkpoint manifest"),
        (counter_receipt_sha256, "resume counter receipt"),
    ):
        _require_sha(value, label)
    if type(checkpoint_serialized_bytes) is not int or checkpoint_serialized_bytes < 1:
        raise ValueError("resume checkpoint serialized bytes must be positive")
    checkpoint_projection = _cursor_projection(checkpoint_cursor)
    expected_keys = {
        "next_loss", "final_cursor", "active_route_parameter_sha256",
        "active_route_optimizer_sha256",
    }
    if not isinstance(uninterrupted, Mapping) or not isinstance(resumed, Mapping):
        raise ValueError("resume equivalence observations are malformed")
    if set(uninterrupted) != expected_keys or set(resumed) != expected_keys:
        raise ValueError("resume equivalence observations use an open key set")
    left, right = dict(uninterrupted), dict(resumed)
    for observation in (left, right):
        if not isinstance(observation["next_loss"], float) or not math.isfinite(observation["next_loss"]):
            raise ValueError("resume equivalence loss must be finite float")
        observation["final_cursor"] = _cursor_projection(observation["final_cursor"])
        _require_sha(observation["active_route_parameter_sha256"], "resume active-route parameter hash")
        _require_sha(observation["active_route_optimizer_sha256"], "resume active-route optimizer hash")
    if left != right:
        raise ValueError("resumed next pack differs from uninterrupted execution")
    if checkpoint_projection["selected_ordinal"] != 64 or checkpoint_projection["global_step"] != 1:
        raise ValueError("durable checkpoint must be the exact first audio-64 pack")
    if left["final_cursor"]["selected_ordinal"] != 128 or left["final_cursor"]["global_step"] != 2:
        raise ValueError("resume equivalence must cover the exact second audio-64 pack")
    if (
        not isinstance(runtime_custody, Mapping)
        or not isinstance(runtime_custody.get("b_floor_at_start"), Mapping)
        or runtime_custody["b_floor_at_start"].get("status") != "PASS"
        or not isinstance(runtime_custody.get("b_floor_after_checkpoint"), Mapping)
        or runtime_custody["b_floor_after_checkpoint"].get("status") != "PASS"
    ):
        raise ValueError("resume equivalence runtime custody lacks both B-floor gates")
    receipt: dict[str, object] = {
        "schema_version": "ember-issue1413-packed-resume-equivalence-v1",
        "status": "PASS",
        "claim_boundary": "RESUME_EQUIVALENCE_ONLY_NO_CAPABILITY_CLAIM",
        **bound_identity,
        "checkpoint_manifest_sha256": checkpoint_manifest_sha256,
        "checkpoint_serialized_bytes": checkpoint_serialized_bytes,
        "counter_receipt_sha256": counter_receipt_sha256,
        "checkpoint_cursor": checkpoint_projection,
        "uninterrupted_next_pack": left,
        "resumed_next_pack": right,
        "runtime_custody": dict(runtime_custody),
        "equivalence": {
            "loss_bit_exact": True,
            "cursor_exact": True,
            "active_route_parameters_exact": True,
            "active_route_optimizer_exact": True,
        },
    }
    receipt["self_sha256"] = hashlib.sha256(_canonical(receipt)).hexdigest()
    return receipt


if __name__ == "__main__":
    raise SystemExit(main())
