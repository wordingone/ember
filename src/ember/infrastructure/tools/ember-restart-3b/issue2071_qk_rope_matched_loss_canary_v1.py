#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Frozen paired complete-update matched-loss canary for issue #2071."""

from __future__ import annotations

import argparse
import copy
import ctypes
import hashlib
import importlib
import json
import math
import os
import shutil
import subprocess
import sys
import time
import traceback
import types
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = "ember-issue2071-qk-rope-matched-loss-canary-v1"
CONTROL_HEAD = "a0cc9acd565af48636e3ed40c6f8cd98b1b94a70"
TREATMENT_HEAD = "3dbc1197d4cd23363b3223c1fb340aed50c93d6a"
ADMITTED_ROW_SET_SHA256 = "6467005d9d692d80cb2792712336cbd332934fb3afbfe7292ebebde1a2e1d879"
TEXT_LAB_CORPUS_RELATIVE_PATH = Path("data/ember-restart-3b/owned-text-lab-corpus-v4.json")
TEXT_LAB_CORPUS_SHA256 = "c494b4cd325a0b0c91e4c2075f5b1aad42a413af037590063781384d210261ca"
CASCADE_ARTIFACT_SHA256 = {
    "data/ember-restart-3b/owned-text-lab-corpus-v4.json": "c494b4cd325a0b0c91e4c2075f5b1aad42a413af037590063781384d210261ca",
    "data/ember-restart-3b/owned-text-lab-input-identity-v4.json": "1b349fa33e45c4653d14a6f62dc1bb825d3086ddf0c85e5eddfeeddbf97fb26c",
    "data/ember-restart-3b/text-lab-authority-index-v2.json": "fbe376f31b878baf14924cef592c9959c4064f626a44abc237aeb1446417c794",
    "data/ember-restart-3b/text-lab-source-receipt-bundle-v4.json": "94fee7e03049ebb4ebb5cbe6b93450e449d8b558384e8d3f8bf90f4a55cfde09",
}
SCOPE_RUN_SPEC_RAW_SHA256 = "e457d7ede3fcd08151236bbd9b730a48976212551e2620e1751eb92e35974c89"
SCOPE_RUN_SPEC_SELF_SHA256 = "a149c50852d3d1622bf6fa1f8da8fd34b64cfcaa7633c7656dfcf4f7e310d68c"
SCOPE_CERTIFICATE_RAW_SHA256 = "5dab87d6af3d841e022a80bccacb75e25f636124d036d3d36f5c1610e8ba965e"
SCOPE_CERTIFICATE_SELF_SHA256 = "b94a7c8a08a4d8fa2823b31ef9426c4abef9c91e0bc63c98408fd27d8a4cff5b"
DESIGNATION_RAW_SHA256 = "5868ad71089a35703fbd9903d36aafaddb22bc6ce5cfc941076508c7a27ebf34"
DESIGNATION_SELF_SHA256 = "ae34f7b46b96fc9151a2810658fe302b897a95fa28f998f8600d7e2d8971c624"
MEASURED_ORDER = ("control", "treatment", "treatment", "control") * 4
PAIR_ORDERS = (("control", "treatment"), ("treatment", "control")) * 4
BURN_IN_UPDATES_PER_ARM = 2
MEASURED_UPDATES_PER_ARM = 8
LOSS_ABSOLUTE_LIMIT = 0.001
LOSS_RELATIVE_LIMIT = 0.001
PARAMETER_ABSOLUTE_LIMIT = 0.015625
PARAMETER_RELATIVE_LIMIT = 0.015625
SPEEDUP_RATIO_FLOOR = 1.02
EXTERNAL_GPU_LIMIT_BYTES = 3072 * 1024**2
COMMIT_FREE_FLOOR_BYTES = 45 * 1024**3
C_FREE_FLOOR_BYTES = 150 * 1024**3
B_FREE_FLOOR_BYTES = 250 * 1024**3
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_LAST_PHASE = "PROCESS_START"


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_treatment_checkout(root: Path, head: str, porcelain: bytes) -> None:
    """Permit only the exact, receipt-bound four-file authority cascade overlay."""

    lines = porcelain.decode("utf-8").splitlines()
    expected = [f" M {path}" for path in sorted(CASCADE_ARTIFACT_SHA256)]
    if head != TREATMENT_HEAD or sorted(lines) != expected:
        raise ValueError(f"SOURCE_HEAD_OR_CLEANLINESS_REFUSED:{head}")
    for relative, expected_sha256 in CASCADE_ARTIFACT_SHA256.items():
        observed = sha256_path(root / relative)
        if observed != expected_sha256:
            raise ValueError(f"CASCADE_ARTIFACT_HASH_DRIFT_REFUSED:{relative}:{observed}")


def emit_progress(output: Path, phase: str, **evidence: object) -> None:
    """Flush one durable phase boundary beside the terminal receipt."""

    global _LAST_PHASE
    _LAST_PHASE = phase
    path = output.with_name(output.stem + ".progress.jsonl")
    row = {"phase": phase, "at_unix": time.time(), **evidence}
    row["row_sha256"] = sha256_bytes(canonical(row))
    raw = canonical(row) + b"\n"
    mode = "ab" if path.exists() else "xb"
    with path.open(mode) as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def append_measurement_row(
    output: Path,
    measured_row: Mapping[str, object],
    *,
    runner_source_sha256: str,
) -> None:
    """Append and fsync one complete measured row before adjudication."""

    if len(runner_source_sha256) != 64:
        raise ValueError("RUNNER_SOURCE_HASH_REFUSED")
    path = output.with_name(output.stem + ".measurements.jsonl")
    path.parent.mkdir(parents=True, exist_ok=True)
    row = copy.deepcopy(dict(measured_row))
    row["runner_source_sha256"] = runner_source_sha256
    row["row_sha256"] = sha256_bytes(canonical(row))
    raw = canonical(row) + b"\n"
    mode = "ab" if path.exists() else "xb"
    with path.open(mode) as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def load_measurement_pairs(path: Path) -> list[list[dict[str, object]]]:
    required = {
        "arm", "pair", "loss", "processed_tokens", "event_seconds",
        "tokens_per_second", "start_identity", "post_model_identity",
        "post_optimizer_identity", "optimizer_structure_census",
        "post_scheduler_identity", "post_scaler_identity", "post_cursor",
        "post_rng_identity", "backend_identity", "sampled_parameters",
        "event_ids", "runner_source_sha256", "row_sha256",
    }
    rows: list[dict[str, object]] = []
    for index, raw in enumerate(path.read_bytes().splitlines()):
        try:
            row = json.loads(raw)
        except (TypeError, ValueError) as error:
            raise ValueError(f"MEASUREMENT_ROW_JSON_REFUSED:{index}") from error
        if not isinstance(row, dict) or set(row) != required:
            raise ValueError(f"MEASUREMENT_ROW_SCHEMA_REFUSED:{index}")
        claimed = row.pop("row_sha256")
        if claimed != sha256_bytes(canonical(row)):
            raise ValueError(f"MEASUREMENT_ROW_HASH_DRIFT_REFUSED:{index}")
        row["row_sha256"] = claimed
        rows.append(row)
    if len(rows) != 2 * len(PAIR_ORDERS):
        raise ValueError(f"MEASUREMENT_ROW_COUNT_REFUSED:{len(rows)}")
    source_hashes = {str(row["runner_source_sha256"]) for row in rows}
    if len(source_hashes) != 1 or len(next(iter(source_hashes))) != 64:
        raise ValueError("MEASUREMENT_RUNNER_SOURCE_DRIFT_REFUSED")
    pairs: list[list[dict[str, object]]] = []
    for pair_index in range(len(PAIR_ORDERS)):
        pair_rows = rows[2 * pair_index:2 * pair_index + 2]
        if [row["pair"] for row in pair_rows] != [pair_index, pair_index]:
            raise ValueError(f"MEASUREMENT_ROW_ORDER_REFUSED:{pair_index}")
        pairs.append(pair_rows)
    return pairs


def adjudicate_measurement_file(path: Path) -> dict[str, object]:
    return adjudicate_pairs(load_measurement_pairs(path.resolve(strict=True)))


def write_refusal_from_exception(output: Path, error: BaseException) -> tuple[str, str] | None:
    if isinstance(error, SystemExit) and error.code in (None, 0):
        return None
    path = output.with_name(output.stem + ".refusal.json")
    if path.exists():
        return None
    return write_receipt(path, {
        "schema_version": SCHEMA_VERSION,
        "result": "REFUSED",
        "refusal_class": type(error).__name__,
        "refusal_message": str(error),
        "last_phase": _LAST_PHASE,
        "issue": 2071,
    })


def write_terminal_refusal(output: Path, error: BaseException) -> tuple[str, str] | None:
    if isinstance(error, SystemExit) and error.code in (None, 0):
        return None
    if output.exists():
        return None
    receipt: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "result": "REFUSED",
        "refusal_class": type(error).__name__,
        "refusal_message": str(error),
        "last_phase": _LAST_PHASE,
        "issue": 2071,
        "runner_source_sha256": sha256_path(Path(__file__).resolve(strict=True)),
    }
    measurements = output.with_name(output.stem + ".measurements.jsonl")
    if measurements.is_file():
        receipt["measurement_rows_raw_sha256"] = sha256_path(measurements)
    return write_receipt(output, receipt)


def p10(values: Sequence[float]) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered or any(not math.isfinite(value) or value <= 0 for value in ordered):
        raise ValueError("TIMING_SAMPLE_INVALID_REFUSED")
    position = 0.1 * (len(ordered) - 1)
    low, high = math.floor(position), math.ceil(position)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def validate_initial_identity(left: Mapping[str, object], right: Mapping[str, object]) -> None:
    if dict(left) != dict(right) or not left:
        raise ValueError("INITIAL_STATE_IDENTITY_DRIFT_REFUSED")


def validate_prestart(row: Mapping[str, object]) -> None:
    checks = (
        ("external_gpu_bytes", int(row.get("external_gpu_bytes", -1)) <= EXTERNAL_GPU_LIMIT_BYTES),
        ("commit_free_bytes", int(row.get("commit_free_bytes", -1)) >= COMMIT_FREE_FLOOR_BYTES),
        ("c_free_bytes", int(row.get("c_free_bytes", -1)) >= C_FREE_FLOOR_BYTES),
        ("b_free_bytes", int(row.get("b_free_bytes", -1)) >= B_FREE_FLOOR_BYTES),
    )
    for field, ok in checks:
        if not ok:
            raise ValueError(f"PRESTART_{field.upper()}_REFUSED")


def external_gpu_bytes(process_rows: str, device_rows: str | None = None) -> int:
    """Return a conservative prestart allocation on both TCC and WDDM hosts.

    Windows WDDM commonly reports ``[N/A]`` for every per-process memory row.
    In that case the device-wide used-memory counter is the only fail-closed
    measurement available and deliberately over-counts desktop allocations.
    """

    values: list[int] = []
    unavailable = False
    for raw in process_rows.splitlines():
        if not raw.strip():
            continue
        field = raw.rsplit(",", 1)[-1].strip()
        try:
            values.append(int(field))
        except ValueError:
            unavailable = True
    if not unavailable:
        return sum(values) * 1024**2
    if device_rows is None:
        raise ValueError("EXTERNAL_GPU_ACCOUNTING_UNAVAILABLE_REFUSED")
    device_values: list[int] = []
    for raw in device_rows.splitlines():
        field = raw.strip().split()[0] if raw.strip() else ""
        try:
            device_values.append(int(field))
        except ValueError as error:
            raise ValueError("EXTERNAL_GPU_ACCOUNTING_UNAVAILABLE_REFUSED") from error
    if len(device_values) != 1:
        raise ValueError("EXTERNAL_GPU_DEVICE_CENSUS_REFUSED")
    return device_values[0] * 1024**2


def validate_designation(
    path: Path,
    expected_raw_sha256: str,
    expected_self_sha256: str,
    checkpoint_root: Path,
    published: Mapping[str, object],
) -> dict[str, object]:
    raw = path.read_bytes()
    if sha256_bytes(raw) != expected_raw_sha256:
        raise ValueError("DESIGNATION_RAW_HASH_DRIFT_REFUSED")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("DESIGNATION_SCHEMA_REFUSED")
    body = dict(value)
    claimed = body.pop("self_sha256", None)
    if claimed != expected_self_sha256 or sha256_bytes(canonical(body)) != expected_self_sha256:
        raise ValueError("DESIGNATION_SELF_HASH_DRIFT_REFUSED")
    if value.get("result") != "DESIGNATED" or value.get("schema_version") != "ember-issue1947-release-candidate-checkpoint-designation-v1":
        raise ValueError("DESIGNATION_VERDICT_REFUSED")
    root = checkpoint_root.resolve(strict=True)
    if Path(str(value.get("candidate_custody", ""))).resolve(strict=True) != root:
        raise ValueError("DESIGNATION_CUSTODY_DRIFT_REFUSED")
    manifest = value.get("manifest")
    shards = value.get("shards")
    if not isinstance(manifest, Mapping) or not isinstance(shards, list) or len(shards) != 7:
        raise ValueError("DESIGNATION_CLOSED_SHARD_SET_REFUSED")
    manifest_path = root / str(manifest.get("path", ""))
    if (
        not manifest_path.is_file()
        or manifest_path.stat().st_size != manifest.get("bytes")
        or sha256_path(manifest_path) != manifest.get("raw_sha256")
        or published.get("checkpoint_manifest_sha256") != manifest.get("raw_sha256")
    ):
        raise ValueError("DESIGNATION_MANIFEST_BINDING_REFUSED")
    seen: set[str] = set()
    for shard in shards:
        if not isinstance(shard, Mapping) or not isinstance(shard.get("path"), str):
            raise ValueError("DESIGNATION_SHARD_SCHEMA_REFUSED")
        relative = str(shard["path"])
        candidate = (root / relative).resolve()
        if relative in seen or not candidate.is_relative_to(root) or not candidate.is_file():
            raise ValueError("DESIGNATION_SHARD_PATH_REFUSED")
        seen.add(relative)
        if candidate.stat().st_size != shard.get("bytes"):
            raise ValueError("DESIGNATION_SHARD_BYTES_DRIFT_REFUSED")
        if sha256_path(candidate) != shard.get("raw_sha256"):
            raise ValueError("DESIGNATION_SHARD_RAW_DRIFT_REFUSED")
    return value


def validate_self_hashed_authority(
    value: Mapping[str, object], expected_self_sha256: str, label: str,
) -> None:
    body = dict(value)
    claimed = body.pop("self_sha256", None)
    if claimed != expected_self_sha256 or sha256_bytes(canonical(body)) != expected_self_sha256:
        raise ValueError(f"{label}_SELF_HASH_DRIFT_REFUSED")


def validate_text_lab_corpus(path: Path, expected_sha256: str) -> str:
    observed = sha256_path(path.resolve(strict=True))
    if expected_sha256 != TEXT_LAB_CORPUS_SHA256 or observed != expected_sha256:
        raise ValueError(f"TEXT_LAB_CORPUS_HASH_DRIFT_REFUSED:{observed}")
    return observed


def validate_admitted_set(
    designation: Mapping[str, object],
    admitted_subset: Mapping[str, object],
    scope_run_spec: Mapping[str, object],
    scope_certificate: Mapping[str, object],
) -> str:
    checkpoint_identity = designation.get("checkpoint_identity")
    expected = checkpoint_identity.get("admitted_row_set_sha256") if isinstance(checkpoint_identity, Mapping) else None
    execution_scope = scope_certificate.get("execution_scope")
    scope_observed = {
        expected,
        scope_run_spec.get("admitted_row_set_sha256"),
        execution_scope.get("allowed_admitted_row_set_sha256")
        if isinstance(execution_scope, Mapping)
        else None,
    }
    observed = scope_observed | {admitted_subset.get("admitted_row_set_sha256")}
    if (
        expected != ADMITTED_ROW_SET_SHA256
        or admitted_subset.get("result") != "VERIFIED_ADMITTED_SUBSET"
        or scope_run_spec.get("schema_version") != "ember-certified-train-run-v1"
        or scope_certificate.get("schema_version")
        != "ember-spine-certified-declaration-v1"
        or observed != {expected}
    ):
        raise ValueError(f"ADMITTED_ROW_SET_IDENTITY_REFUSED:{sorted(str(value) for value in observed)}")
    if (
        admitted_subset.get("admitted_row_count") != 28
        or admitted_subset.get("run_manifest_row_count") != 28
    ):
        raise ValueError(
            "ADMITTED_ROW_COUNT_REFUSED:"
            f"admitted={admitted_subset.get('admitted_row_count')}:"
            f"manifest={admitted_subset.get('run_manifest_row_count')}"
        )
    return str(expected)


def classify_cursor(
    cursor: Mapping[str, object],
    receipt_sha256: str,
    tokenizer_sha256: str,
) -> dict[str, object]:
    legacy_fields = {
        "global_step", "governor", "receipt_sha256", "record_index", "shard",
        "shard_index", "token_offset", "tokenizer_sha256", "tokens_seen",
    }
    runtime_fields = legacy_fields - {"governor"}
    fields = set(cursor)
    if frozenset(fields) not in {frozenset(legacy_fields), frozenset(runtime_fields)}:
        raise ValueError(f"DATA_CURSOR_SCHEMA_REFUSED:{sorted(fields)}")
    integers = ("global_step", "record_index", "shard_index", "token_offset", "tokens_seen")
    if any(type(cursor.get(field)) is not int or int(cursor[field]) < 0 for field in integers):
        raise ValueError("DATA_CURSOR_VALUE_REFUSED")
    if (
        cursor["record_index"] != cursor["global_step"]
        or cursor.get("receipt_sha256") != receipt_sha256
        or cursor.get("tokenizer_sha256") != tokenizer_sha256
        or cursor.get("shard") != "TOKEN-SHARDS-V0:" + receipt_sha256[:12]
    ):
        raise ValueError("DATA_CURSOR_IDENTITY_REFUSED")
    return {
        "cursor_schema": "legacy-record-index" if fields == legacy_fields else "runtime-bound-record-index",
        "selection_start": "semantic-resume",
        "initial_data_cursor": copy.deepcopy(dict(cursor)),
        "initial_global_step": int(cursor["global_step"]),
        "initial_tokens_seen": int(cursor["tokens_seen"]),
    }


def validate_cursor_restoration(
    expected: Mapping[str, object],
    restored: Mapping[str, object],
    receipt_sha256: str,
    tokenizer_sha256: str,
) -> None:
    classify_cursor(expected, receipt_sha256, tokenizer_sha256)
    classify_cursor(restored, receipt_sha256, tokenizer_sha256)
    if dict(expected) != dict(restored):
        raise ValueError("DATA_CURSOR_RESTORE_DRIFT_REFUSED")


def _validate_tensor_state(expected: Mapping[str, Any], actual: object, label: str) -> None:
    if not isinstance(actual, Mapping) or set(actual) != set(expected):
        raise ValueError(f"CPU_PREFLIGHT_{label}_KEYS_REFUSED")
    for name, tensor in actual.items():
        expected_tensor = expected[name]
        if not hasattr(tensor, "shape") or tuple(tensor.shape) != tuple(expected_tensor.shape):
            raise ValueError(f"CPU_PREFLIGHT_{label}_SHAPE_REFUSED:{name}")
        if tensor.dtype != expected_tensor.dtype:
            raise ValueError(f"CPU_PREFLIGHT_{label}_DTYPE_REFUSED:{name}")


def safe_checkpoint_load(
    torch: Any, model: Any, root: Path, receipt: Mapping[str, object],
) -> dict[str, object]:
    """Load all real checkpoint payloads with PyTorch's restricted weights-only unpickler."""

    root = root.resolve(strict=True)
    records = receipt.get("shards")
    if not isinstance(records, list) or len(records) != 7:
        raise ValueError("CPU_PREFLIGHT_SHARD_SET_REFUSED")
    payloads: dict[str, object] = {}
    for record in records:
        if not isinstance(record, Mapping) or not isinstance(record.get("path"), str):
            raise ValueError("CPU_PREFLIGHT_SHARD_SCHEMA_REFUSED")
        relative = str(record["path"])
        path = (root / relative).resolve(strict=True)
        if not path.is_relative_to(root) or path.stat().st_size != record.get("bytes"):
            raise ValueError(f"CPU_PREFLIGHT_SHARD_PATH_REFUSED:{relative}")
        if sha256_path(path) != record.get("sha256"):
            raise ValueError(f"CPU_PREFLIGHT_SHARD_HASH_REFUSED:{relative}")
        payloads[relative] = torch.load(path, map_location="cpu", weights_only=True, mmap=True)

    replay = payloads.get("replay-state.pt")
    if not isinstance(replay, Mapping) or replay.get("data_cursor") != receipt.get("data_cursor"):
        raise ValueError("CPU_PREFLIGHT_REPLAY_CURSOR_REFUSED")
    rng = replay.get("rng_state")
    if not isinstance(rng, Mapping) or set(rng) != {"cpu", "cuda"}:
        raise ValueError("CPU_PREFLIGHT_REPLAY_RNG_REFUSED")
    for state in rng.values():
        if not hasattr(state, "dtype") or state.dtype != torch.uint8 or state.ndim != 1:
            raise ValueError("CPU_PREFLIGHT_REPLAY_RNG_REFUSED")

    expected_state = model.state_dict()
    shared_expected = {key: value for key, value in expected_state.items() if ".experts." not in key}
    shared = payloads.get("shared-model.pt")
    if not isinstance(shared, Mapping):
        raise ValueError("CPU_PREFLIGHT_SHARED_PAYLOAD_REFUSED")
    _validate_tensor_state(shared_expected, shared.get("model"), "SHARED")
    for expert in ("vision", "audio", "reasoning", "tool"):
        payload = payloads.get(f"expert-{expert}.pt")
        if not isinstance(payload, Mapping) or payload.get("expert") != expert:
            raise ValueError(f"CPU_PREFLIGHT_EXPERT_ROLE_REFUSED:{expert}")
        expected = {key: value for key, value in expected_state.items() if f".experts.{expert}." in key}
        _validate_tensor_state(expected, payload.get("model"), f"EXPERT_{expert.upper()}")

    optimizer = payloads.get("optimizer-state-shared.pt")
    if not isinstance(optimizer, Mapping) or optimizer.get("owner") != "shared":
        raise ValueError("CPU_PREFLIGHT_OPTIMIZER_ROLE_REFUSED")
    if optimizer.get("optimizer_contract") != receipt.get("optimizer_contract"):
        raise ValueError("CPU_PREFLIGHT_OPTIMIZER_CONTRACT_REFUSED")
    if optimizer.get("optimizer_realization") != receipt.get("optimizer_realization"):
        raise ValueError("CPU_PREFLIGHT_OPTIMIZER_REALIZATION_REFUSED")
    owner_by_parameter = receipt.get("optimizer_state_owner_by_parameter")
    expected_owner_names = {
        name for name, owner in owner_by_parameter.items() if owner == "shared"
    } if isinstance(owner_by_parameter, Mapping) else set()
    if not isinstance(optimizer.get("state"), Mapping) or set(optimizer["state"]) != expected_owner_names:
        raise ValueError("CPU_PREFLIGHT_OPTIMIZER_STATE_KEYS_REFUSED")
    return {"data_cursor": dict(replay["data_cursor"]), "shards_loaded": len(payloads)}


def cpu_checkpoint_preflight(
    packed: Any,
    torch: Any,
    checkpoint_module: Any,
    checkpoint: Path,
    checkpoint_receipt: Mapping[str, object],
    stream: Any,
    seed: int,
    config_path: Path,
    checkpoint_loader: Any = safe_checkpoint_load,
) -> dict[str, object]:
    """Execute the real checkpoint loader against a metadata-only model, never CUDA."""

    config = packed.RestartDecoderConfig.from_contract(config_path)
    previous_dtype = torch.get_default_dtype()
    torch.set_default_dtype(torch.bfloat16)
    try:
        model = packed.UnifiedDecoder(
            config, device="meta", allow_production_allocation=True, genesis_seed=seed,
        )
    finally:
        torch.set_default_dtype(previous_dtype)
    model._activate_expert("shared")
    counts = packed.measure_parameter_counts(model)
    if counts["unique_parameters"] != 3_839_161_856 or counts["active_parameters"] != 1_020_589_568:
        raise RuntimeError("CPU_PREFLIGHT_MODEL_CAPACITY_REFUSED")
    initial_cursor = dict(checkpoint_receipt["data_cursor"])
    classify_cursor(initial_cursor, stream.receipt_sha256, stream.tokenizer_sha256)
    loaded = checkpoint_loader(torch, model, checkpoint, checkpoint_receipt)
    restored_cursor = dict(loaded["data_cursor"])
    validate_cursor_restoration(
        initial_cursor, restored_cursor, stream.receipt_sha256, stream.tokenizer_sha256,
    )
    _, advanced = stream.next_episode(
        shard_index=int(restored_cursor["shard_index"]),
        token_offset=int(restored_cursor["token_offset"]),
        sequence_length=512,
    )
    successor_cursor = {
        "shard": "TOKEN-SHARDS-V0:" + stream.receipt_sha256[:12],
        "record_index": int(restored_cursor["global_step"]) + 1,
        "receipt_sha256": stream.receipt_sha256,
        "tokenizer_sha256": stream.tokenizer_sha256,
        "shard_index": advanced["shard_index"],
        "token_offset": advanced["token_offset"],
        "global_step": int(restored_cursor["global_step"]) + 1,
        "tokens_seen": int(restored_cursor["tokens_seen"]) + int(advanced["tokens_seen"]),
    }
    successor = classify_cursor(successor_cursor, stream.receipt_sha256, stream.tokenizer_sha256)
    return {
        "result": "PASS",
        "device": "meta-cpu-loader",
        "gpu_allocation_allowed": False,
        "unique_parameters": counts["unique_parameters"],
        "active_parameters": counts["active_parameters"],
        "cursor_schema": "legacy-record-index",
        "successor_cursor_schema": successor["cursor_schema"],
        "cursor_sha256": sha256_bytes(canonical(restored_cursor)),
        "successor_cursor_sha256": sha256_bytes(canonical(successor_cursor)),
        "shards_loaded": loaded["shards_loaded"],
    }


def disk_budget_child_binding() -> dict[str, object]:
    assertion_raw = os.environ.get("EMBER_DISK_BUDGET_ENV_ASSERTION")
    expected_nonce = os.environ.get("EMBER_DISK_BUDGET_ENV_NONCE")
    if not assertion_raw or not expected_nonce:
        raise ValueError("DISK_BUDGET_ADAPTER_BINDING_REFUSED")
    assertion_path = Path(assertion_raw).resolve(strict=True)
    value = json.loads(assertion_path.read_text(encoding="utf-8"))
    if value.get("nonce") != expected_nonce or value.get("schema_version") != 1:
        raise ValueError("DISK_BUDGET_ADAPTER_BINDING_REFUSED")
    bindings = value.get("bindings")
    if not isinstance(bindings, Mapping) or any(not str(path).upper().startswith("B:\\") for path in bindings.values()):
        raise ValueError("DISK_BUDGET_CACHE_BINDING_REFUSED")
    return {"assertion_path": str(assertion_path), "assertion_sha256": sha256_path(assertion_path), "nonce": expected_nonce}


def _finite(value: object, refusal: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(refusal)
    return result


def _relative(left: float, right: float) -> float:
    return abs(right - left) / max(abs(left), 1e-12)


def adjudicate_pairs(pairs: Sequence[Sequence[Mapping[str, object]]]) -> dict[str, object]:
    if len(pairs) != len(PAIR_ORDERS):
        raise ValueError("PAIR_COUNT_REFUSED")
    events: list[str] = []
    rows_by_arm: dict[str, list[Mapping[str, object]]] = {"control": [], "treatment": []}
    repeated_by_arm_and_start: dict[tuple[str, str], Mapping[str, object]] = {}
    comparisons: list[dict[str, object]] = []
    for pair_index, (rows, expected_order) in enumerate(zip(pairs, PAIR_ORDERS)):
        if len(rows) != 2 or tuple(row.get("arm") for row in rows) != expected_order:
            raise ValueError(f"ABBA_ORDER_DRIFT_REFUSED:{pair_index}")
        left, right = rows
        if left.get("pair") != pair_index or right.get("pair") != pair_index:
            raise ValueError(f"PAIR_INDEX_DRIFT_REFUSED:{pair_index}")
        if left.get("start_identity") != right.get("start_identity"):
            raise ValueError(f"PAIR_START_IDENTITY_DRIFT_REFUSED:{pair_index}")
        left_loss = _finite(left.get("loss"), "NONFINITE_LOSS_REFUSED")
        right_loss = _finite(right.get("loss"), "NONFINITE_LOSS_REFUSED")
        loss_absolute = abs(right_loss - left_loss)
        loss_relative = _relative(left_loss, right_loss)
        if loss_absolute > LOSS_ABSOLUTE_LIMIT or loss_relative > LOSS_RELATIVE_LIMIT:
            raise ValueError(f"LOSS_DIVERGENCE_REFUSED:{pair_index}:{loss_absolute}:{loss_relative}")
        left_samples = left.get("sampled_parameters")
        right_samples = right.get("sampled_parameters")
        if not isinstance(left_samples, Mapping) or not isinstance(right_samples, Mapping) or set(left_samples) != set(right_samples):
            raise ValueError(f"SAMPLED_PARAMETER_CENSUS_DRIFT_REFUSED:{pair_index}")
        maximum_absolute = maximum_relative = 0.0
        for key in sorted(left_samples):
            a = _finite(left_samples[key], "NONFINITE_SAMPLED_PARAMETER_REFUSED")
            b = _finite(right_samples[key], "NONFINITE_SAMPLED_PARAMETER_REFUSED")
            maximum_absolute = max(maximum_absolute, abs(b - a))
            maximum_relative = max(maximum_relative, _relative(a, b))
        if maximum_absolute > PARAMETER_ABSOLUTE_LIMIT or maximum_relative > PARAMETER_RELATIVE_LIMIT:
            raise ValueError(f"SAMPLED_PARAMETER_DIVERGENCE_REFUSED:{pair_index}:{maximum_absolute}:{maximum_relative}")
        left_structure = left.get("optimizer_structure_census")
        right_structure = right.get("optimizer_structure_census")
        if not isinstance(left_structure, Mapping) or left_structure != right_structure:
            raise ValueError(f"OPTIMIZER_STRUCTURE_DRIFT_REFUSED:{pair_index}")
        for field, refusal in (
            ("post_scheduler_identity", "POST_SCHEDULER_DRIFT_REFUSED"),
            ("post_scaler_identity", "POST_SCALER_DRIFT_REFUSED"),
            ("post_cursor", "POST_CURSOR_DRIFT_REFUSED"),
            ("post_rng_identity", "POST_RNG_DRIFT_REFUSED"),
            ("backend_identity", "BACKEND_IDENTITY_DRIFT_REFUSED"),
        ):
            if left.get(field) != right.get(field):
                raise ValueError(f"{refusal}:{pair_index}")
        for row in rows:
            event_ids = row.get("event_ids")
            if not isinstance(event_ids, list) or len(event_ids) != 2 or not all(isinstance(item, str) and item for item in event_ids):
                raise ValueError("CUDA_EVENT_IDENTITY_REFUSED")
            events.extend(event_ids)
            tokens = int(row.get("processed_tokens", 0))
            seconds = _finite(row.get("event_seconds"), "TIMING_SAMPLE_INVALID_REFUSED")
            rate = _finite(row.get("tokens_per_second"), "TIMING_SAMPLE_INVALID_REFUSED")
            if tokens <= 0 or seconds <= 0 or not math.isclose(rate, tokens / seconds, rel_tol=1e-12, abs_tol=1e-12):
                raise ValueError("TOKEN_ACCOUNTING_REFUSED")
            determinism_key = (str(row["arm"]), str(row["start_identity"]))
            previous = repeated_by_arm_and_start.get(determinism_key)
            for field in (
                "post_model_identity", "post_optimizer_identity",
                "post_scheduler_identity", "post_scaler_identity", "post_cursor",
                "post_rng_identity", "backend_identity", "sampled_parameters",
            ):
                if previous is not None and previous.get(field) != row.get(field):
                    raise ValueError(f"WITHIN_ARM_{field.upper()}_DRIFT_REFUSED:{pair_index}")
            repeated_by_arm_and_start[determinism_key] = row
            rows_by_arm[str(row["arm"])].append(row)
        comparisons.append({
            "pair": pair_index,
            "order": list(expected_order),
            "loss_absolute_difference": loss_absolute,
            "loss_relative_difference": loss_relative,
            "sampled_parameter_max_absolute_difference": maximum_absolute,
            "sampled_parameter_max_relative_difference": maximum_relative,
        })
    if len(events) != len(set(events)):
        raise ValueError("CUDA_EVENT_IDENTITY_REFUSED")
    if any(len(rows_by_arm[arm]) != MEASURED_UPDATES_PER_ARM for arm in rows_by_arm):
        raise ValueError("MEASURED_UPDATE_COUNT_REFUSED")
    control_p10 = p10([float(row["tokens_per_second"]) for row in rows_by_arm["control"]])
    treatment_p10 = p10([float(row["tokens_per_second"]) for row in rows_by_arm["treatment"]])
    ratio = treatment_p10 / control_p10
    return {
        "disposition": "PASS_POSITIVE" if ratio >= SPEEDUP_RATIO_FLOOR else "REJECTED",
        "control_p10_tokens_per_second": control_p10,
        "treatment_p10_tokens_per_second": treatment_p10,
        "aggregate_p10_ratio": ratio,
        "comparisons": comparisons,
    }


def write_receipt(path: Path, value: dict[str, object]) -> tuple[str, str]:
    if path.exists():
        raise FileExistsError(f"OUTPUT_EXISTS_REFUSED:{path}")
    body = copy.deepcopy(value)
    body.pop("self_sha256", None)
    body["self_sha256"] = sha256_bytes(canonical(body))
    raw = json.dumps(body, indent=2, sort_keys=True).encode() + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return sha256_bytes(raw), str(body["self_sha256"])


def git(root: Path, *args: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(root), *args], stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=NO_WINDOW, check=False,
    )
    if result.returncode:
        raise RuntimeError(f"GIT_REFUSED:{result.stderr.decode(errors='replace')}")
    return result.stdout


class PerformanceInformation(ctypes.Structure):
    _fields_ = [("cb", ctypes.c_uint32), ("CommitTotal", ctypes.c_size_t), ("CommitLimit", ctypes.c_size_t),
                ("CommitPeak", ctypes.c_size_t), ("PhysicalTotal", ctypes.c_size_t), ("PhysicalAvailable", ctypes.c_size_t),
                ("SystemCache", ctypes.c_size_t), ("KernelTotal", ctypes.c_size_t), ("KernelPaged", ctypes.c_size_t),
                ("KernelNonpaged", ctypes.c_size_t), ("PageSize", ctypes.c_size_t), ("HandleCount", ctypes.c_uint32),
                ("ProcessCount", ctypes.c_uint32), ("ThreadCount", ctypes.c_uint32)]


def commit_free_bytes() -> int:
    info = PerformanceInformation()
    info.cb = ctypes.sizeof(info)
    if not ctypes.windll.psapi.GetPerformanceInfo(ctypes.byref(info), info.cb):
        raise RuntimeError("GET_PERFORMANCE_INFORMATION_REFUSED")
    return int(info.CommitLimit - info.CommitTotal) * int(info.PageSize)


def _hash_update(digest: Any, value: object) -> None:
    torch = importlib.import_module("torch")
    if isinstance(value, torch.Tensor):
        tensor = value.detach().cpu().contiguous()
        digest.update(str(tuple(tensor.shape)).encode())
        digest.update(str(tensor.dtype).encode())
        digest.update(tensor.view(torch.uint8).numpy().tobytes())
    elif isinstance(value, Mapping):
        for key in sorted(value, key=lambda item: str(item)):
            digest.update(str(key).encode())
            _hash_update(digest, value[key])
    elif isinstance(value, (list, tuple)):
        for item in value:
            _hash_update(digest, item)
    else:
        digest.update(repr(value).encode())


def state_identity(value: object) -> str:
    digest = hashlib.sha256()
    _hash_update(digest, value)
    return digest.hexdigest()


def optimizer_structure_census(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            "kind": "mapping",
            "entries": [
                [str(key), optimizer_structure_census(value[key])]
                for key in sorted(value, key=lambda item: str(item))
            ],
        }
    if isinstance(value, (list, tuple)):
        return {"kind": type(value).__name__, "items": [optimizer_structure_census(item) for item in value]}
    if hasattr(value, "shape") and hasattr(value, "dtype"):
        return {"kind": "tensor", "shape": list(value.shape), "dtype": str(value.dtype)}
    return {"kind": "scalar", "type": type(value).__name__}


def run_offline_adjudication(custody: Path) -> int:
    custody = custody.resolve(strict=True)
    if not custody.is_dir():
        raise ValueError("ADJUDICATION_CUSTODY_NOT_DIRECTORY_REFUSED")
    measurements = custody / "terminal.measurements.jsonl"
    pairs = load_measurement_pairs(measurements.resolve(strict=True))
    decision = adjudicate_pairs(pairs)
    source_hashes = {
        str(row["runner_source_sha256"])
        for pair_rows in pairs
        for row in pair_rows
    }
    if len(source_hashes) != 1:
        raise ValueError("MEASUREMENT_RUNNER_SOURCE_DRIFT_REFUSED")
    output = custody / "terminal.json"
    raw_sha, self_sha = write_receipt(output, {
        "schema_version": SCHEMA_VERSION,
        "result": decision["disposition"],
        "issue": 2071,
        "offline_adjudication": True,
        "measurement_rows_raw_sha256": sha256_path(measurements),
        "measurement_row_count": sum(len(pair_rows) for pair_rows in pairs),
        "measured_pairs": pairs,
        "runner_source_sha256": next(iter(source_hashes)),
        "adjudicator_source_sha256": sha256_path(Path(__file__).resolve(strict=True)),
        "adjudication": decision,
        "claim_boundary": "OFFLINE RE-ADJUDICATION OF DURABLE MEASUREMENT ROWS ONLY; NO NEW MEASUREMENT OR GOAL CREDIT",
    })
    print(json.dumps({"result": decision["disposition"], "raw_sha256": raw_sha, "self_sha256": self_sha}, sort_keys=True))
    return 0


def snapshot_runtime(model: Any, optimizer: Any, cursor: Mapping[str, object]) -> dict[str, object]:
    torch = importlib.import_module("torch")

    def clone(value: object) -> object:
        if isinstance(value, torch.Tensor):
            return value.detach().cpu().clone()
        if isinstance(value, Mapping):
            return {key: clone(item) for key, item in value.items()}
        if isinstance(value, list):
            return [clone(item) for item in value]
        if isinstance(value, tuple):
            return tuple(clone(item) for item in value)
        return copy.deepcopy(value)

    return {
        "model": clone(model.state_dict()),
        "optimizer": clone(optimizer.state_dict()),
        "cursor": copy.deepcopy(dict(cursor)),
        "cpu_rng": torch.random.get_rng_state().cpu().clone(),
        "cuda_rng": torch.cuda.get_rng_state().cpu().clone(),
    }


def restore_runtime(model: Any, optimizer: Any, snapshot: Mapping[str, object]) -> dict[str, object]:
    torch = importlib.import_module("torch")
    model.load_state_dict(snapshot["model"], strict=True)
    optimizer.load_state_dict(snapshot["optimizer"])
    torch.random.set_rng_state(snapshot["cpu_rng"])
    torch.cuda.set_rng_state(snapshot["cuda_rng"])
    torch.cuda.synchronize()
    return copy.deepcopy(dict(snapshot["cursor"]))


def frozen_parameter_census(model: Any, width: int = 16) -> list[tuple[str, int]]:
    named = [(name, parameter) for name, parameter in sorted(model.named_parameters()) if parameter.numel()]
    if not named:
        raise ValueError("PARAMETER_CENSUS_EMPTY_REFUSED")
    positions = sorted({round(index * (len(named) - 1) / max(width - 1, 1)) for index in range(min(width, len(named)))})
    result: list[tuple[str, int]] = []
    for position in positions:
        name, parameter = named[position]
        for index in sorted({0, parameter.numel() // 2, parameter.numel() - 1}):
            result.append((name, index))
    return result


def sample_parameters(model: Any, census: Sequence[tuple[str, int]]) -> dict[str, float]:
    parameters = dict(model.named_parameters())
    return {f"{name}:{index}": float(parameters[name].detach().reshape(-1)[index].float().cpu()) for name, index in census}


def load_source_module(name: str, raw: bytes, filename: str) -> Any:
    module = types.ModuleType(name)
    module.__file__ = filename
    sys.modules[name] = module
    exec(compile(raw, filename, "exec"), module.__dict__)
    return module


def allocate_semantic_runtime(*, packed: Any, repo_root: Path, seed: int) -> tuple[Any, Any, Any, dict[str, object], dict[str, object]]:
    torch = importlib.import_module("torch")
    if os.environ.get("EMBER_GATE_AUTHORIZED") != "1" or not torch.cuda.is_available():
        raise RuntimeError("semantic canary requires authorized CUDA runtime")
    config_path = repo_root / "configs" / "ember-restart-3b.json"
    config = packed.RestartDecoderConfig.from_contract(config_path)
    packed.load_memory_contract(config_path)
    governor = packed.governed_resource_preflight()
    free_bytes, _ = torch.cuda.mem_get_info()
    memory = packed.production_memory_preflight(
        total_parameters=config.structural_parameter_count(),
        active_parameters=1_020_589_568,
        device_free_bytes=int(free_bytes),
    )
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    previous_dtype = torch.get_default_dtype()
    torch.set_default_dtype(torch.bfloat16)
    try:
        model = packed.UnifiedDecoder(
            config, device="cuda", allow_production_allocation=True, genesis_seed=seed,
        )
    finally:
        torch.set_default_dtype(previous_dtype)
    model._activate_expert("shared")
    model.train()
    counts = packed.measure_parameter_counts(model)
    if counts["unique_parameters"] != 3_839_161_856 or counts["active_parameters"] != 1_020_589_568:
        raise RuntimeError("semantic canary instantiated the wrong model capacity")
    optimizer = packed.build_production_optimizer(
        model, optimizer_contract=packed.load_optimizer_contract(config_path),
    )
    return config, model, optimizer, governor, memory


def prepare_peak_memory_accounting(torch: Any, device: Any) -> dict[str, object]:
    """Reset peak counters or prove the pinned backend starts at a zero baseline."""

    try:
        torch.cuda.reset_peak_memory_stats(device)
    except AttributeError as error:
        if "_cuda_resetPeakMemoryStats" not in str(error):
            raise
        allocated = int(torch.cuda.memory_allocated(device))
        maximum = int(torch.cuda.max_memory_allocated(device))
        if allocated != 0 or maximum != 0:
            raise RuntimeError(
                "CUDA_PEAK_RESET_BACKEND_ABSENT_NONZERO_REFUSED:"
                f"memory_allocated={allocated}:max_memory_allocated={maximum}"
            ) from error
        return {
            "backend_present": False,
            "mode": "zero-baseline-max-memory-allocated",
            "baseline_memory_allocated_bytes": allocated,
            "baseline_max_memory_allocated_bytes": maximum,
        }
    return {
        "backend_present": True,
        "mode": "reset_peak_memory_stats",
        "baseline_memory_allocated_bytes": int(torch.cuda.memory_allocated(device)),
        "baseline_max_memory_allocated_bytes": int(torch.cuda.max_memory_allocated(device)),
    }


def interpreter_binding_preflight(
    torch: Any, *, expected_python_sha256: str, expected_torch_version: str,
) -> dict[str, object]:
    executable = Path(sys.executable).resolve(strict=True)
    identity = {
        "result": "PASS",
        "sys_executable": str(executable),
        "sys_executable_sha256": sha256_path(executable),
        "torch_version": str(torch.__version__),
        "cuda_available": bool(torch.cuda.is_available()),
        "cuda_device_count": int(torch.cuda.device_count()),
        "cuda_device_name": None,
    }
    if identity["cuda_available"] and identity["cuda_device_count"]:
        identity["cuda_device_name"] = str(torch.cuda.get_device_name(0))
    if (
        identity["sys_executable_sha256"] != expected_python_sha256
        or identity["torch_version"] != expected_torch_version
        or identity["cuda_available"] is not True
        or int(identity["cuda_device_count"]) < 1
        or not identity["cuda_device_name"]
    ):
        identity["result"] = "REFUSED"
        raise RuntimeError(
            "INTERPRETER_BINDING_REFUSED:"
            + canonical({
                **identity,
                "expected_python_sha256": expected_python_sha256,
                "expected_torch_version": expected_torch_version,
            }).decode("utf-8")
        )
    return identity


def run_one_update(*, arm: str, pair: int, model: Any, optimizer: Any, stream: Any, config: Any,
                   pretrain: Any, model_module: Any, methods: Mapping[str, object], cursor: Mapping[str, object],
                   census: Sequence[tuple[str, int]], backend_identity: Sequence[str], sequence_length: int) -> tuple[dict[str, object], dict[str, object]]:
    torch = importlib.import_module("torch")
    model_module.SharedAttention.forward = methods[arm]
    resume = classify_cursor(cursor, stream.receipt_sha256, stream.tokenizer_sha256)
    initial_tokens = int(resume["initial_tokens_seen"])
    initial_step = int(resume["initial_global_step"])
    start_event = torch.cuda.Event(enable_timing=True)
    end_event = torch.cuda.Event(enable_timing=True)
    start_event.record()
    segment = pretrain.run_manifest_bound_semantic_segment(
        model=model, optimizer=optimizer, stream=stream, config=config,
        device=torch.device("cuda"), sequence_length=sequence_length, steps=1,
        checkpoint_every=2, checkpoint_callback=lambda _step, _state: None,
        initial_data_cursor=resume["initial_data_cursor"],
        initial_global_step=initial_step, initial_tokens_seen=initial_tokens,
    )
    end_event.record()
    end_event.synchronize()
    seconds = float(start_event.elapsed_time(end_event)) / 1000.0
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError("CUDA_EVENT_TIMING_REFUSED")
    processed = int(segment["tokens_seen"]) - initial_tokens
    post_cursor = dict(segment["data_cursor"])
    classify_cursor(post_cursor, stream.receipt_sha256, stream.tokenizer_sha256)
    row = {
        "arm": arm, "pair": pair, "loss": float(segment["losses"][0]),
        "processed_tokens": processed, "event_seconds": seconds,
        "tokens_per_second": processed / seconds,
        "post_model_identity": state_identity(model.state_dict()),
        "post_optimizer_identity": state_identity(optimizer.state_dict()),
        "optimizer_structure_census": optimizer_structure_census(optimizer.state_dict()),
        "post_scheduler_identity": "scheduler-none-v1", "post_scaler_identity": "scaler-none-v1",
        "post_cursor": post_cursor,
        "post_rng_identity": state_identity({"cpu": torch.random.get_rng_state(), "cuda": torch.cuda.get_rng_state()}),
        "backend_identity": list(backend_identity), "sampled_parameters": sample_parameters(model, census),
        "event_ids": [f"pair-{pair}-{arm}-cuda-start", f"pair-{pair}-{arm}-cuda-end"],
    }
    return row, post_cursor


def main() -> int:
    if "--adjudicate" in sys.argv:
        if len(sys.argv) != 3 or sys.argv[1] != "--adjudicate":
            raise ValueError("OFFLINE_ADJUDICATION_ARGUMENTS_REFUSED")
        return run_offline_adjudication(Path(sys.argv[2]))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--designation-receipt", type=Path, required=True)
    parser.add_argument("--designation-raw-sha256", default=DESIGNATION_RAW_SHA256)
    parser.add_argument("--designation-self-sha256", default=DESIGNATION_SELF_SHA256)
    parser.add_argument("--checkpoint-manifest-sha256", required=True)
    parser.add_argument("--text-lab-corpus", type=Path, required=True)
    parser.add_argument("--text-lab-corpus-sha256", required=True)
    parser.add_argument("--semantic-receipt", type=Path, required=True)
    parser.add_argument("--semantic-receipt-sha256", required=True)
    parser.add_argument("--semantic-shards-root", type=Path, required=True)
    parser.add_argument("--semantic-tokenizer", type=Path, required=True)
    parser.add_argument("--semantic-tokenizer-sha256", required=True)
    parser.add_argument("--receipt-custody-root", type=Path, required=True)
    parser.add_argument("--scope-run-spec", type=Path, required=True)
    parser.add_argument("--scope-run-spec-raw-sha256", default=SCOPE_RUN_SPEC_RAW_SHA256)
    parser.add_argument("--scope-run-spec-self-sha256", default=SCOPE_RUN_SPEC_SELF_SHA256)
    parser.add_argument("--scope-certificate", type=Path, required=True)
    parser.add_argument("--scope-certificate-raw-sha256", default=SCOPE_CERTIFICATE_RAW_SHA256)
    parser.add_argument("--scope-certificate-self-sha256", default=SCOPE_CERTIFICATE_SELF_SHA256)
    parser.add_argument("--microprofile", type=Path, required=True)
    parser.add_argument("--microprofile-raw-sha256", required=True)
    parser.add_argument("--microprofile-self-sha256", required=True)
    parser.add_argument("--model-sha256", required=True)
    parser.add_argument("--test-sha256", required=True)
    parser.add_argument("--python-sha256", required=True)
    parser.add_argument("--torch-version", required=True)
    parser.add_argument("--seed", type=int, default=2071)
    parser.add_argument("--sequence-length", type=int, default=512)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    root = args.repo_root.resolve(strict=True)
    output = args.output.resolve()
    runner_source_sha256 = sha256_path(Path(__file__).resolve(strict=True))
    emit_progress(output, "ARGS_BOUND")
    if (
        args.designation_raw_sha256 != DESIGNATION_RAW_SHA256
        or args.designation_self_sha256 != DESIGNATION_SELF_SHA256
        or args.scope_run_spec_raw_sha256 != SCOPE_RUN_SPEC_RAW_SHA256
        or args.scope_run_spec_self_sha256 != SCOPE_RUN_SPEC_SELF_SHA256
        or args.scope_certificate_raw_sha256 != SCOPE_CERTIFICATE_RAW_SHA256
        or args.scope_certificate_self_sha256 != SCOPE_CERTIFICATE_SELF_SHA256
    ):
        raise ValueError("IMMUTABLE_AUTHORITY_PIN_OVERRIDE_REFUSED")
    if output.exists():
        raise FileExistsError(f"OUTPUT_EXISTS_REFUSED:{output}")
    head = git(root, "rev-parse", "HEAD").decode().strip()
    validate_treatment_checkout(root, head, git(root, "status", "--porcelain"))
    pinned = {
        root / "tools/ember-restart-3b/model.py": args.model_sha256,
        root / "tests/ember_restart_model/test_model.py": args.test_sha256,
        args.checkpoint.resolve(strict=True) / "checkpoint-manifest.json": args.checkpoint_manifest_sha256,
        args.text_lab_corpus.resolve(strict=True): args.text_lab_corpus_sha256,
        args.semantic_receipt.resolve(strict=True): args.semantic_receipt_sha256,
        args.semantic_tokenizer.resolve(strict=True): args.semantic_tokenizer_sha256,
        args.scope_run_spec.resolve(strict=True): args.scope_run_spec_raw_sha256,
        args.scope_certificate.resolve(strict=True): args.scope_certificate_raw_sha256,
        args.microprofile.resolve(strict=True): args.microprofile_raw_sha256,
    }
    for path, expected in pinned.items():
        actual = sha256_path(path)
        if actual != expected:
            raise ValueError(f"INPUT_HASH_DRIFT_REFUSED:{path}:{actual}")
    emit_progress(output, "IMMUTABLE_INPUT_HASHES_PASS")
    if args.text_lab_corpus.resolve() != (root / TEXT_LAB_CORPUS_RELATIVE_PATH).resolve():
        raise ValueError("TEXT_LAB_CORPUS_PATH_REFUSED")
    validate_text_lab_corpus(args.text_lab_corpus, args.text_lab_corpus_sha256)
    microprofile = json.loads(args.microprofile.read_text(encoding="utf-8"))
    if microprofile.get("result") != "PASS_POSITIVE" or microprofile.get("self_sha256") != args.microprofile_self_sha256:
        raise ValueError("MICROPROFILE_PREDECESSOR_REFUSED")
    if (
        microprofile.get("treatment_head") != TREATMENT_HEAD
        or microprofile.get("control_head") != CONTROL_HEAD
        or microprofile.get("treatment_model_sha256") != args.model_sha256
        or microprofile.get("treatment_test_sha256") != args.test_sha256
    ):
        raise ValueError("MICROPROFILE_SOURCE_IDENTITY_REFUSED")
    backend = microprofile.get("backend")
    if isinstance(backend, Mapping):
        values = [tuple(value) for value in backend.values()]
        if not values or len(set(values)) != 1:
            raise ValueError("MICROPROFILE_BACKEND_IDENTITY_REFUSED")
        backend_identity = list(values[0])
    elif isinstance(backend, list) and backend:
        backend_identity = list(backend)
    else:
        raise ValueError("MICROPROFILE_BACKEND_IDENTITY_REFUSED")
    probe = subprocess.run(["nvidia-smi", "--query-compute-apps=pid,used_memory", "--format=csv,noheader,nounits"],
                           stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           text=True, creationflags=NO_WINDOW, check=False)
    if probe.returncode:
        raise ValueError("NVIDIA_SMI_REFUSED")
    device_probe = None
    if any("[N/A]" in row for row in probe.stdout.splitlines()):
        device_probe = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, creationflags=NO_WINDOW, check=False,
        )
        if device_probe.returncode:
            raise ValueError("NVIDIA_SMI_DEVICE_FALLBACK_REFUSED")
    external_gpu = external_gpu_bytes(
        probe.stdout, None if device_probe is None else device_probe.stdout,
    )
    disk_budget_binding = disk_budget_child_binding()
    prestart = {"external_gpu_bytes": external_gpu, "commit_free_bytes": commit_free_bytes(),
                "c_free_bytes": shutil.disk_usage("C:/").free, "b_free_bytes": shutil.disk_usage("B:/").free}
    validate_prestart(prestart)
    emit_progress(output, "PRESTART_RESOURCE_FLOORS_PASS", **prestart)
    os.environ["EMBER_GATE_AUTHORIZED"] = "1"
    if args.preflight_only:
        os.environ["CUDA_VISIBLE_DEVICES"] = "-1"
    module_root = root / "tools/ember-restart-3b"
    sys.path.insert(0, str(module_root))
    torch = importlib.import_module("torch")
    try:
        interpreter_binding = interpreter_binding_preflight(
            torch,
            expected_python_sha256=args.python_sha256,
            expected_torch_version=args.torch_version,
        )
    except RuntimeError as error:
        if str(error).startswith("INTERPRETER_BINDING_REFUSED:"):
            emit_progress(
                output,
                "PRE_ALLOCATION_INTERPRETER_BINDING_REFUSED",
                refusal_message=str(error),
            )
        raise
    emit_progress(output, "PRE_ALLOCATION_INTERPRETER_BINDING_PASS", **interpreter_binding)
    packed = importlib.import_module("packed_specialist_run")
    pretrain = importlib.import_module("pretrain")
    model_module = importlib.import_module("model")
    checkpoint_module = importlib.import_module("checkpoint_artifacts")
    semantic_module = importlib.import_module("semantic_stream")
    text_lab_module = importlib.import_module("text_lab_corpus")
    train_module = importlib.import_module("train")
    emit_progress(output, "RUNTIME_MODULES_IMPORTED")
    control_raw = git(root, "show", f"{CONTROL_HEAD}:tools/ember-restart-3b/model.py")
    control_module = load_source_module("issue2071_control_model", control_raw, f"{CONTROL_HEAD}:model.py")
    methods = {"control": control_module.SharedAttention.forward, "treatment": model_module.SharedAttention.forward}
    checkpoint_receipt = checkpoint_module.published_checkpoint_receipt(args.checkpoint)
    designation = validate_designation(
        args.designation_receipt.resolve(strict=True), args.designation_raw_sha256,
        args.designation_self_sha256, args.checkpoint, checkpoint_receipt,
    )
    emit_progress(output, "CHECKPOINT_DESIGNATION_PASS")
    scope_run_spec = json.loads(args.scope_run_spec.read_text(encoding="utf-8"))
    scope_certificate = json.loads(args.scope_certificate.read_text(encoding="utf-8"))
    validate_self_hashed_authority(scope_run_spec, args.scope_run_spec_self_sha256, "RUN_SPEC")
    validate_self_hashed_authority(scope_certificate, args.scope_certificate_self_sha256, "CERTIFICATE")
    if (
        Path(str(scope_run_spec.get("semantic_canary_receipt", ""))).resolve()
        != args.semantic_receipt.resolve()
        or Path(str(scope_run_spec.get("semantic_canary_shards_root", ""))).resolve()
        != args.semantic_shards_root.resolve(strict=True)
        or Path(str(scope_run_spec.get("receipt_custody_root", ""))).resolve()
        != args.receipt_custody_root.resolve(strict=True)
    ):
        raise ValueError("SCOPE_PRECEDENT_PATH_REFUSED")
    text_lab_preflight = train_module.run_text_lab_preflight(
        repo_root=root, receipt_custody_root=args.receipt_custody_root,
    )
    admitted_subset = text_lab_module.validate_admitted_authority_subset(
        root, text_lab_preflight,
    )
    admitted_row_set_sha256 = validate_admitted_set(
        designation,
        admitted_subset,
        scope_run_spec,
        scope_certificate,
    )
    emit_progress(output, "ADMITTED_SCOPE_PASS")
    stream = semantic_module.ManifestBoundTokenStream.from_receipt(
        receipt_path=args.semantic_receipt,
        shards_root=args.semantic_shards_root,
        tokenizer_path=args.semantic_tokenizer,
    )
    if (
        stream.receipt_sha256 != args.semantic_receipt_sha256
        or stream.tokenizer_sha256 != args.semantic_tokenizer_sha256
    ):
        raise ValueError("SEMANTIC_STREAM_IDENTITY_REFUSED")
    emit_progress(output, "SEMANTIC_STREAM_PASS")
    initial_manifest_cursor = dict(checkpoint_receipt["data_cursor"])
    initial_cursor_contract = classify_cursor(
        initial_manifest_cursor, stream.receipt_sha256, stream.tokenizer_sha256,
    )
    if args.preflight_only:
        cpu_evidence = cpu_checkpoint_preflight(
            packed, torch, checkpoint_module, args.checkpoint, checkpoint_receipt,
            stream, args.seed, root / "configs" / "ember-restart-3b.json",
        )
        emit_progress(output, "CPU_CHECKPOINT_LOAD_PASS", **cpu_evidence)
        receipt = {
            "schema_version": "ember-issue2071-full-chain-cpu-preflight-v1",
            "result": "PASS",
            "issue": 2071,
            "campaign_issue": 1945,
            "control_source_head": CONTROL_HEAD,
            "treatment_source_head": TREATMENT_HEAD,
            "admitted_row_set_sha256": admitted_row_set_sha256,
            "designation_raw_sha256": args.designation_raw_sha256,
            "designation_self_sha256": args.designation_self_sha256,
            "run_spec_raw_sha256": args.scope_run_spec_raw_sha256,
            "run_spec_self_sha256": args.scope_run_spec_self_sha256,
            "certificate_raw_sha256": args.scope_certificate_raw_sha256,
            "certificate_self_sha256": args.scope_certificate_self_sha256,
            "checkpoint_manifest_sha256": designation["manifest"]["raw_sha256"],
            "text_lab_corpus_sha256": args.text_lab_corpus_sha256,
            "semantic_receipt_sha256": stream.receipt_sha256,
            "semantic_tokenizer_sha256": stream.tokenizer_sha256,
            "initial_cursor_contract": initial_cursor_contract,
            "cpu_checkpoint_load": cpu_evidence,
            "exact_loader_predecessor": {
                "progress_raw_sha256": "d19206b5b47dafb84105ab9db5230e1db094679ca8d09ce00d1afb95d2fdfab2",
                "checkpoint_loaded_row_sha256": "68003f04db8d019a1c003c7babe108514d18df54a6eab182c6611df2c3ec9fe6",
                "phase": "CHECKPOINT_LOADED",
                "checkpoint_manifest_sha256": "255cdb164b770f868da9a6727b1067512b5ce9caecd968f4544389c5a908aeef",
                "equivalence_boundary": "EXACT_UNSAFE_LOADER_ALREADY_PASSED_SAME_HASH_PINNED_CHECKPOINT; THIS_PREFLIGHT_USES_WEIGHTS_ONLY_TRUE_MMAP",
            },
            "prestart": prestart,
            "disk_budget_adapter": disk_budget_binding,
            "phases_executed": [
                "ARGS_BOUND", "IMMUTABLE_INPUT_HASHES_PASS", "PRESTART_RESOURCE_FLOORS_PASS",
                "RUNTIME_MODULES_IMPORTED", "CHECKPOINT_DESIGNATION_PASS", "ADMITTED_SCOPE_PASS",
                "SEMANTIC_STREAM_PASS", "CPU_CHECKPOINT_LOAD_PASS",
            ],
            "claim_boundary": "FULL_PRE_OPTIMIZER_CPU_PREFLIGHT_ONLY; ZERO_GPU_ALLOCATION; NO_RUNTIME_OR_GOAL_CREDIT",
        }
        raw_sha, self_sha = write_receipt(output, receipt)
        print(json.dumps({"result": "PASS", "raw_sha256": raw_sha, "self_sha256": self_sha}, sort_keys=True))
        return 0
    started = time.perf_counter()
    measurement_device = torch.device("cuda")
    peak_memory_accounting = prepare_peak_memory_accounting(torch, measurement_device)
    config, model, optimizer, governor, memory = allocate_semantic_runtime(
        packed=packed, repo_root=root, seed=args.seed,
    )
    emit_progress(output, "RUNTIME_ALLOCATED")
    loaded = checkpoint_module.load_checkpoint_artifacts(model, optimizer, args.checkpoint, checkpoint_receipt)
    emit_progress(output, "CHECKPOINT_LOADED")
    cursor = dict(loaded["data_cursor"])
    validate_cursor_restoration(
        initial_manifest_cursor, cursor, stream.receipt_sha256, stream.tokenizer_sha256,
    )
    initial = snapshot_runtime(model, optimizer, cursor)
    initial_identity = {"model": state_identity(initial["model"]), "optimizer": state_identity(initial["optimizer"]),
                        "cursor": sha256_bytes(canonical(initial["cursor"])),
                        "rng": state_identity({"cpu": initial["cpu_rng"], "cuda": initial["cuda_rng"]})}
    restored_cursor = restore_runtime(model, optimizer, initial)
    validate_initial_identity(initial_identity, {"model": state_identity(model.state_dict()),
        "optimizer": state_identity(optimizer.state_dict()), "cursor": sha256_bytes(canonical(restored_cursor)),
        "rng": state_identity({"cpu": torch.random.get_rng_state(), "cuda": torch.cuda.get_rng_state()})})
    census = frozen_parameter_census(model)
    burn_in: list[dict[str, object]] = []
    for arm in ("control", "treatment"):
        cursor = restore_runtime(model, optimizer, initial)
        for burn_index in range(BURN_IN_UPDATES_PER_ARM):
            burn, cursor = run_one_update(arm=arm, pair=-1 - burn_index, model=model, optimizer=optimizer,
                stream=stream, config=config, pretrain=pretrain, model_module=model_module, methods=methods,
                cursor=cursor, census=census, backend_identity=backend_identity, sequence_length=args.sequence_length)
            burn_in.append({"arm": arm, "loss": burn["loss"], "processed_tokens": burn["processed_tokens"]})
        emit_progress(output, "BURN_IN_ARM_COMPLETE", arm=arm)
    cursor = restore_runtime(model, optimizer, initial)
    measured: list[list[dict[str, object]]] = []
    for pair_index, order in enumerate(PAIR_ORDERS):
        common = snapshot_runtime(model, optimizer, cursor)
        start_identity = state_identity(common)
        pair_rows: list[dict[str, object]] = []
        for position, arm in enumerate(order):
            if position:
                cursor = restore_runtime(model, optimizer, common)
            row, post_cursor = run_one_update(arm=arm, pair=pair_index, model=model, optimizer=optimizer,
                stream=stream, config=config, pretrain=pretrain, model_module=model_module, methods=methods,
                cursor=cursor, census=census, backend_identity=backend_identity, sequence_length=args.sequence_length)
            row["start_identity"] = start_identity
            append_measurement_row(
                output, row, runner_source_sha256=runner_source_sha256,
            )
            pair_rows.append(row)
            cursor = post_cursor
        measured.append(pair_rows)
        emit_progress(output, "MEASURED_PAIR_COMPLETE", pair=pair_index)
    decision = adjudicate_pairs(measured)
    receipt = {"schema_version": SCHEMA_VERSION, "result": decision["disposition"], "issue": 2071,
        "campaign_issue": 1945, "control_source_head": CONTROL_HEAD, "treatment_source_head": TREATMENT_HEAD,
        "admitted_row_set_sha256": admitted_row_set_sha256,
        "designation_raw_sha256": args.designation_raw_sha256,
        "designation_self_sha256": args.designation_self_sha256,
        "checkpoint_manifest_sha256": designation["manifest"]["raw_sha256"],
        "text_lab_authority": {
            "corpus_sha256": args.text_lab_corpus_sha256,
            "admitted_row_count": admitted_subset["admitted_row_count"],
            "run_manifest_row_count": admitted_subset["run_manifest_row_count"],
        },
        "semantic_stream": {
            "receipt_sha256": stream.receipt_sha256,
            "tokenizer_sha256": stream.tokenizer_sha256,
            "sequence_length": args.sequence_length,
        },
        "scope_precedent": {
            "run_spec_raw_sha256": args.scope_run_spec_raw_sha256,
            "run_spec_self_sha256": args.scope_run_spec_self_sha256,
            "certificate_raw_sha256": args.scope_certificate_raw_sha256,
            "certificate_self_sha256": args.scope_certificate_self_sha256,
            "authority_only": True,
            "new_certificate_minted": True,
        },
        "initial_cursor_contract": initial_cursor_contract,
        "source_model_sha256": args.model_sha256,
        "runner_source_sha256": runner_source_sha256,
        "source_test_sha256": args.test_sha256, "microprofile_raw_sha256": args.microprofile_raw_sha256,
        "microprofile_self_sha256": args.microprofile_self_sha256, "seed": args.seed,
        "burn_in_updates_per_arm": BURN_IN_UPDATES_PER_ARM, "measured_updates_per_arm": MEASURED_UPDATES_PER_ARM,
        "measured_order": list(MEASURED_ORDER), "parameter_census": [[name, index] for name, index in census],
        "burn_in": burn_in, "pairs": measured, "adjudication": decision, "prestart": prestart,
        "disk_budget_adapter": disk_budget_binding,
        "governor": governor, "memory_preflight": memory,
        "peak_memory_accounting": peak_memory_accounting,
        "peak_allocated_vram_bytes": max(
            0,
            int(torch.cuda.max_memory_allocated(measurement_device))
            - int(peak_memory_accounting["baseline_max_memory_allocated_bytes"]),
        ),
        "peak_reserved_vram_bytes": int(torch.cuda.max_memory_reserved()), "wall_seconds": time.perf_counter() - started,
        "claim_boundary": "EIGHT-PAIR MATCHED-LOSS CANARY ONLY; NO 20K, CAPABILITY, SUFFICIENT-PRETRAINING, CAMPAIGN, EMBER-02, OR GOAL CREDIT"}
    raw_sha, self_sha = write_receipt(output, receipt)
    print(json.dumps({"result": decision["disposition"], "raw_sha256": raw_sha, "self_sha256": self_sha}, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BaseException as error:
        try:
            output = None
            if "--output" in sys.argv:
                output = Path(sys.argv[sys.argv.index("--output") + 1]).resolve()
            elif "--adjudicate" in sys.argv and sys.argv.index("--adjudicate") + 1 < len(sys.argv):
                output = Path(sys.argv[sys.argv.index("--adjudicate") + 1]).resolve() / "terminal.json"
            if output is not None:
                write_terminal_refusal(output, error)
                write_refusal_from_exception(output, error)
        except BaseException:
            traceback.print_exc()
        raise
