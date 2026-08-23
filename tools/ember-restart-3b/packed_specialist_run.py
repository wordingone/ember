# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Governed receipts for issue #1413's packed specialist training arms."""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import math
import os
import re
import shutil
from collections.abc import Mapping, Sequence
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
from parameter_counter import measure_parameter_counts
from pretrain import CensusBoundStage2Executor, run_packed_selection_pretraining_segment
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
        integration_contract = repo_root / "docs" / "ember-restart" / "integration-contract-v1.md"

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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in (
        "durable-preflight", "formal-preflight", "durable-bf16",
        "bf16", "stage2", "diagnostic-graph-bf16",
    ):
        child = subparsers.add_parser(name)
        _add_runtime_arguments(
            child,
            packs=name in {"formal-preflight", "bf16", "stage2", "diagnostic-graph-bf16"},
        )
    compare = subparsers.add_parser("compare")
    compare.add_argument("--baseline", type=Path, required=True)
    compare.add_argument("--accelerated", type=Path, required=True)
    compare.add_argument("--output", type=Path, required=True)
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
