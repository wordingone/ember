#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Closed receipts for #1946's complete-update recompute experiment."""

from __future__ import annotations

import hashlib
import json
import math
import os
import statistics
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


_SHA256 = frozenset("0123456789abcdef")
_PHASES = {
    "data_readiness",
    "reference_forward",
    "forward",
    "backward",
    "gradient_clipping",
    "optimizer",
    "mandatory_synchronization",
    "telemetry_checkpoint",
    "explicit_remainder",
}
_INSTRUMENTS = {"profiler", "allocator", "power", "event", "identity", "receipt"}
_AUTHORITY = {
    "goal_id": "EMBER-02",
    "workstream_id": "EMBER-02B",
    "next_executed_outcome": "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember",
}


def verified_execution_source_commit(repo_root: Path, expected_commit: str) -> str:
    """Bind a claimed execution commit to one clean tracked checkout."""

    _require_sha(expected_commit, "execution source commit", length=40)
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0

    def run_git(*arguments: str) -> str:
        completed = subprocess.run(
            ["git", "-C", str(repo_root), *arguments],
            text=True,
            capture_output=True,
            check=False,
            shell=False,
            creationflags=creationflags,
        )
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or "#1946 execution checkout query failed")
        return completed.stdout.strip()

    actual = run_git("rev-parse", "HEAD")
    if actual != expected_commit:
        raise ValueError("#1946 execution source commit does not match repo HEAD")
    if run_git("status", "--porcelain", "--untracked-files=no"):
        raise ValueError("#1946 execution checkout has tracked or index drift")
    return actual


def gpu_covariate() -> dict[str, object]:
    """Read one exact physical-GPU row without opening a Windows console."""

    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    completed = subprocess.run(
        [
            "nvidia-smi",
            "--query-gpu=uuid,clocks.sm,clocks.mem,temperature.gpu,power.draw,memory.used,memory.total",
            "--format=csv,noheader,nounits",
        ],
        text=True,
        capture_output=True,
        check=False,
        shell=False,
        creationflags=creationflags,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "nvidia-smi GPU covariate query failed")
    rows = [row.strip() for row in completed.stdout.splitlines() if row.strip()]
    if len(rows) != 1:
        raise RuntimeError("#1946 requires exactly one governed physical GPU")
    fields = [field.strip() for field in rows[0].split(",")]
    if len(fields) != 7:
        raise RuntimeError("nvidia-smi GPU covariate row is malformed")
    return {
        "gpu_uuid": fields[0],
        "sm_clock_mhz": int(float(fields[1])),
        "memory_clock_mhz": int(float(fields[2])),
        "temperature_c": float(fields[3]),
        "power_w": float(fields[4]),
        "memory_used_mib": float(fields[5]),
        "memory_total_mib": float(fields[6]),
    }


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _self_hashed(value: dict[str, object]) -> dict[str, object]:
    result = dict(value)
    result["self_sha256"] = hashlib.sha256(_canonical(result)).hexdigest()
    return result


def _require_sha(value: object, label: str, *, length: int = 64) -> str:
    if not isinstance(value, str) or len(value) != length or any(character not in _SHA256 for character in value):
        raise ValueError(f"{label} must be lowercase {length}hex")
    return value


def _verify_self(receipt: Mapping[str, object], label: str) -> dict[str, object]:
    value = dict(receipt)
    claimed = _require_sha(value.pop("self_sha256", None), f"{label} self hash")
    if hashlib.sha256(_canonical(value)).hexdigest() != claimed:
        raise ValueError(f"{label} self hash differs")
    value["self_sha256"] = claimed
    return value


def validate_preflight_receipt(
    receipt: Mapping[str, object], *, execution_source_commit: str,
    accounting_spec_sha256: str, gpu_uuid: str,
) -> dict[str, object]:
    """Verify the exact preflight that authorizes expensive Arm A."""

    value = _verify_self(receipt, "#1946 preflight")
    if value.get("schema_version") != "ember-issue1946-instrument-preflight-v1" or value.get("result") != "PASS":
        raise ValueError("#1946 Arm A requires a PASS instrument preflight")
    identity = value.get("identity")
    if not isinstance(identity, Mapping) or identity.get("execution_source_commit") != execution_source_commit:
        raise ValueError("#1946 preflight execution source does not match Arm A")
    if identity.get("accounting_spec_sha256") != accounting_spec_sha256:
        raise ValueError("#1946 preflight accounting spec does not match Arm A")
    instruments = value.get("instruments")
    if not isinstance(instruments, Mapping) or set(instruments) != _INSTRUMENTS or any(
        not isinstance(row, Mapping) or row.get("status") != "PASS" for row in instruments.values()
    ):
        raise ValueError("#1946 preflight does not prove every required instrument")
    power = instruments.get("power")
    power_row = power.get("row") if isinstance(power, Mapping) else None
    if not isinstance(power_row, Mapping) or power_row.get("gpu_uuid") != gpu_uuid:
        raise ValueError("#1946 preflight GPU UUID does not match Arm A")
    stall = value.get("injected_data_stall_seconds")
    phase = value.get("phase_seconds")
    if not isinstance(stall, (int, float)) or not isinstance(phase, Mapping) or float(phase.get("data_readiness", -1)) < float(stall):
        raise ValueError("#1946 preflight does not bind the charged data stall")
    boundary = value.get("complete_update_timing_boundary")
    if not isinstance(boundary, Mapping) or boundary.get("data_readiness_mode") != "STREAMED_INSIDE_GOVERNED_WALL":
        raise ValueError("#1946 preflight did not stream actual data readiness inside the governed wall")
    return value


def validate_arm_a_receipt(
    receipt: Mapping[str, object], *, execution_source_commit: str,
    gpu_uuid: str, current_process_id: int,
) -> dict[str, object]:
    """Verify the exact Arm A receipt that authorizes expensive Arm B."""

    value = _verify_self(receipt, "#1946 Arm A")
    if (
        value.get("schema_version") != "ember-issue1946-complete-update-arm-v1"
        or value.get("result") != "PASS"
        or value.get("policy") != "WHOLE_LAYER_RECOMPUTE"
    ):
        raise ValueError("#1946 Arm B requires the PASS whole-layer Arm A receipt")
    identity = value.get("identity")
    if not isinstance(identity, Mapping) or identity.get("execution_source_commit") != execution_source_commit:
        raise ValueError("#1946 Arm A execution source does not match Arm B")
    custody = value.get("runtime_custody")
    if not isinstance(custody, Mapping) or custody.get("gpu_uuid") != gpu_uuid:
        raise ValueError("#1946 Arm A GPU UUID does not match Arm B")
    process_id = custody.get("process_id")
    if type(process_id) is not int or process_id <= 0 or process_id == current_process_id:
        raise ValueError("#1946 Arm B requires a distinct positive Arm A process")
    _require_sha(custody.get("preflight_raw_sha256"), "preflight raw receipt")
    _require_sha(custody.get("preflight_self_sha256"), "preflight self receipt")
    return value


def load_accounting_spec(path: Path) -> dict[str, object]:
    raw = path.read_bytes()
    try:
        spec = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("accounting spec must be strict JSON") from error
    expected_route = {
        "pack_records": 64,
        "selected_record_count": 4096,
        "warmup_updates": 16,
        "measured_updates": 48,
        "profiler_updates": 8,
    }
    if (
        spec.get("schema_version") != "ember-issue1946-complete-update-accounting-v1"
        or spec.get("authority") != _AUTHORITY
        or spec.get("route") != expected_route
        or spec.get("numerator", {}).get("tokens_per_update") != 960
        or spec.get("numerator", {}).get("filters") != ["applied", "non_padding", "loss_bearing", "decoder_target"]
        or spec.get("denominator", {}).get("opens_before") != ["data_readiness", "reference_forward"]
        or spec.get("denominator", {}).get("closes_after") != ["optimizer", "mandatory_synchronization", "telemetry", "charged_checkpoint"]
    ):
        raise ValueError("accounting spec is not the closed #1946 audio-64 contract")
    spec["raw_sha256"] = hashlib.sha256(raw).hexdigest()
    return spec


def load_authority_crosswalk(repo_root: Path, path: Path) -> dict[str, object]:
    raw = path.read_bytes()
    try:
        crosswalk = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("authority crosswalk must be strict JSON") from error
    expected_roles = {"fp33_profiler", "c04_muon_bf16ns5_qat", "eager_compile", "cuda_graph", "r1_e8", "energy"}
    rows = crosswalk.get("artifacts")
    predecessor = crosswalk.get("issue1413_predecessor")
    if (
        crosswalk.get("schema_version") != "ember-issue1946-authority-crosswalk-v1"
        or crosswalk.get("authority") != _AUTHORITY
        or not isinstance(rows, list)
        or {row.get("role") for row in rows if isinstance(row, Mapping)} != expected_roles
        or not isinstance(predecessor, Mapping)
    ):
        raise ValueError("authority crosswalk does not cover the closed #1946 evidence roles")
    for key in ("density_selection_receipt_sha256", "raw_sha256", "self_sha256"):
        _require_sha(predecessor.get(key), f"#1413 predecessor {key}")
    reopened = []
    for row in rows:
        relative = Path(str(row["path"]))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("authority crosswalk path escapes the repository")
        artifact = (repo_root / relative).resolve(strict=True)
        if not artifact.is_relative_to(repo_root.resolve(strict=True)):
            raise ValueError("authority crosswalk artifact escapes the repository")
        reopened.append({**dict(row), "raw_sha256": hashlib.sha256(artifact.read_bytes()).hexdigest()})
    return {
        "schema_version": crosswalk["schema_version"],
        "authority": dict(crosswalk["authority"]),
        "crosswalk_raw_sha256": hashlib.sha256(raw).hexdigest(),
        "issue1413_predecessor": dict(predecessor),
        "artifacts": reopened,
    }


def _phases(value: Mapping[str, object], update_seconds: float) -> tuple[dict[str, float], float]:
    if set(value) != _PHASES:
        raise ValueError("phase row must use the closed attribution owner set")
    row = {key: float(value[key]) for key in _PHASES}
    if not math.isfinite(update_seconds) or update_seconds <= 0 or any(not math.isfinite(item) or item < 0 for item in row.values()):
        raise ValueError("phase timing values must be finite and nonnegative")
    fraction = sum(row.values()) / update_seconds
    if fraction < 0.99 or fraction > 1.01:
        raise ValueError("complete-update attribution must cover 99 to 101 percent of wall")
    return row, fraction


def build_preflight_receipt(
    *,
    identity: Mapping[str, object],
    update_seconds: float,
    phase_seconds: Mapping[str, object],
    injected_data_stall_seconds: float,
    instruments: Mapping[str, object],
) -> dict[str, object]:
    if set(identity) != {"execution_source_commit", "accounting_spec_sha256"}:
        raise ValueError("preflight identity must be closed")
    _require_sha(identity["execution_source_commit"], "execution source commit", length=40)
    _require_sha(identity["accounting_spec_sha256"], "accounting spec")
    if not math.isfinite(injected_data_stall_seconds) or injected_data_stall_seconds <= 0:
        raise ValueError("preflight data-stall injection must be positive")
    if float(phase_seconds.get("data_readiness", -1)) < injected_data_stall_seconds:
        raise ValueError("complete-update data-stall probe was not charged to the governed wall")
    if set(instruments) != _INSTRUMENTS or any(not isinstance(row, Mapping) or row.get("status") != "PASS" for row in instruments.values()):
        raise ValueError("preflight requires PASS from profiler, allocator, power, event, identity, and receipt paths")
    row, fraction = _phases(phase_seconds, float(update_seconds))
    return _self_hashed({
        "schema_version": "ember-issue1946-instrument-preflight-v1",
        "result": "PASS",
        "claim_boundary": "INSTRUMENT_PREFLIGHT_ONLY",
        "identity": dict(identity),
        "update_seconds": float(update_seconds),
        "phase_seconds": row,
        "attribution_fraction": fraction,
        "injected_data_stall_seconds": float(injected_data_stall_seconds),
        "instruments": {name: dict(value) for name, value in instruments.items()},
    })


def build_arm_receipt(
    *,
    policy: str,
    identity: Mapping[str, object],
    update_seconds: Sequence[float],
    phase_seconds: Sequence[Mapping[str, object]],
    profiler_update_indexes: Sequence[int],
    allocator_rows: Sequence[Mapping[str, object]],
    power_rows: Sequence[Mapping[str, object]],
    kernel_trace: Mapping[str, object],
) -> dict[str, object]:
    if policy not in {"WHOLE_LAYER_RECOMPUTE", "DISABLED_EVERY_LAYER"}:
        raise ValueError("profile arm must use one of the two frozen recompute policies")
    expected_identity = {
        "execution_source_commit", "parameter_sha256", "optimizer_initial_state_sha256",
        "cpu_rng_state_sha256", "cuda_rng_state_sha256", "config_sha256",
        "seed", "initial_cursor", "selection_receipt_sha256",
    }
    if set(identity) != expected_identity:
        raise ValueError("profile arm identity must use its closed fields")
    _require_sha(identity["execution_source_commit"], "execution source commit", length=40)
    _require_sha(identity["parameter_sha256"], "parameter identity")
    _require_sha(identity["selection_receipt_sha256"], "selection receipt")
    for key in ("optimizer_initial_state_sha256", "cpu_rng_state_sha256", "cuda_rng_state_sha256", "config_sha256"):
        _require_sha(identity[key], key)
    if type(identity["seed"]) is not int or identity["initial_cursor"] != 0:
        raise ValueError("profile arm requires a fixed integer seed and cursor zero")
    timings = [float(value) for value in update_seconds]
    if len(timings) != 64 or any(not math.isfinite(value) or value <= 0 for value in timings):
        raise ValueError("profile arm requires exactly 64 positive complete-update walls")
    if len(phase_seconds) != 64 or len(allocator_rows) != 64 or len(power_rows) != 64:
        raise ValueError("profile arm instruments must cover all 64 complete updates")
    profiler = list(profiler_update_indexes)
    if profiler != list(range(16, 24)):
        raise ValueError("profile arm requires exactly measured updates 16 through 23 under profiler")
    phases_and_fractions = [_phases(row, timing) for row, timing in zip(phase_seconds, timings, strict=True)]
    _require_sha(kernel_trace.get("sha256"), "kernel trace")
    if not kernel_trace.get("material_linear_shapes") or not kernel_trace.get("observed_kernels"):
        raise ValueError("kernel trace must bind material linear shapes and actual observed kernels")
    layer_count = kernel_trace.get("layer_count")
    if type(layer_count) is not int or layer_count < 1:
        raise ValueError("kernel trace must bind the exact positive layer count")
    measured = timings[16:]
    measured_sorted = sorted(measured)
    p10 = measured_sorted[math.ceil(0.10 * len(measured_sorted)) - 1]
    p90 = measured_sorted[math.ceil(0.90 * len(measured_sorted)) - 1]
    peak_allocated = max(int(row["allocated"]) for row in allocator_rows)
    peak_reserved = max(int(row["reserved"]) for row in allocator_rows)
    peak_workspace = max(int(row["workspace"]) for row in allocator_rows)
    peak_graph_pool = max(int(row["graph_pool"]) for row in allocator_rows)
    peak_fragmentation = max(int(row["fragmentation"]) for row in allocator_rows)
    energy = [float(row["power_w"]) * seconds for row, seconds in zip(power_rows, timings, strict=True)]
    compute_factor = 8 if policy == "WHOLE_LAYER_RECOMPUTE" else 6
    active_parameters = 1_725_232_640
    median_seconds = statistics.median(measured)
    return _self_hashed({
        "schema_version": "ember-issue1946-complete-update-arm-v1",
        "result": "PASS",
        "claim_boundary": "CURRENT_AUDIO64_SYSTEMS_MEASUREMENT_ONLY",
        "policy": policy,
        "identity": dict(identity),
        "counts": {"complete_updates": 64, "warmup": 16, "measured": 48, "profiler": 8},
        "update_seconds": timings,
        "warmup_update_seconds": timings[:16],
        "measured_update_seconds": measured,
        "complete_update_distribution_seconds": {"p10": p10, "median": median_seconds, "p90": p90},
        "phase_seconds": [item[0] for item in phases_and_fractions],
        "attribution_fraction_min": min(item[1] for item in phases_and_fractions),
        "profiler_update_indexes": profiler,
        "allocator_rows": [dict(row) for row in allocator_rows],
        "power_rows": [dict(row) for row in power_rows],
        "kernel_trace": dict(kernel_trace),
        "applied_decoder_target_tokens_per_update": 960,
        "recomputed_layer_forwards": 64 * layer_count if policy == "WHOLE_LAYER_RECOMPUTE" else 0,
        "memory": {
            "peak_allocated_bytes": peak_allocated,
            "peak_reserved_bytes": peak_reserved,
            "peak_workspace_bytes": peak_workspace,
            "peak_graph_pool_bytes": peak_graph_pool,
            "peak_fragmentation_bytes": peak_fragmentation,
        },
        "board_energy_joules_per_update": energy,
        "implied_20k_required_tflops": compute_factor * active_parameters * 20_000 / 1e12,
        "measured_compute_tflops": compute_factor * active_parameters * 960 / median_seconds / 1e12,
        "fallbacks": [],
        "errors": [],
    })


def build_oom_arm_receipt(
    *,
    identity: Mapping[str, object],
    completed_updates: int,
    peak_demand_bytes: int,
    ceiling_bytes: int,
    first_temperature_c: float,
    error_class: str,
) -> dict[str, object]:
    if type(completed_updates) is not int or not 0 <= completed_updates < 64:
        raise ValueError("all-off OOM completed-update count is invalid")
    if type(peak_demand_bytes) is not int or type(ceiling_bytes) is not int or min(peak_demand_bytes, ceiling_bytes) <= 0:
        raise ValueError("all-off OOM requires positive measured VRAM values")
    if peak_demand_bytes <= ceiling_bytes:
        raise ValueError("all-off OOM peak demand must exceed the measured ceiling")
    if error_class not in {"torch.OutOfMemoryError", "SAFETY_MARGIN_FAILURE"}:
        raise ValueError("all-off memory result has an unsupported error class")
    return _self_hashed({
        "schema_version": "ember-issue1946-complete-update-arm-oom-v1",
        "result": "VALID_ALL_OFF_MEMORY_FAILURE",
        "claim_boundary": "ALL_OFF_POLICY_ONLY_SELECTIVE_UNADJUDICATED",
        "policy": "DISABLED_EVERY_LAYER",
        "identity": dict(identity),
        "completed_updates": completed_updates,
        "peak_demand_bytes": peak_demand_bytes,
        "ceiling_bytes": ceiling_bytes,
        "measured_vram_gap_bytes": peak_demand_bytes - ceiling_bytes,
        "first_temperature_c": float(first_temperature_c),
        "error_class": error_class,
    })


def build_comparison_receipt(
    arm_a: Mapping[str, object], arm_b: Mapping[str, object], *, arm_a_raw_sha256: str,
) -> dict[str, object]:
    left = _verify_self(arm_a, "arm A")
    right = _verify_self(arm_b, "arm B")
    _require_sha(arm_a_raw_sha256, "Arm A raw receipt")
    if left.get("policy") != "WHOLE_LAYER_RECOMPUTE" or right.get("policy") != "DISABLED_EVERY_LAYER":
        raise ValueError("comparison requires frozen A-then-B recompute order")
    if left.get("identity") != right.get("identity"):
        raise ValueError("profile arm initial identities differ")
    left_custody = left.get("runtime_custody")
    right_custody = right.get("runtime_custody")
    if not isinstance(left_custody, Mapping) or not isinstance(right_custody, Mapping):
        raise ValueError("profile arms require runtime custody")
    if (
        left_custody.get("fresh_process_and_cuda_context_required") is not True
        or right_custody.get("fresh_process_and_cuda_context_required") is not True
    ):
        raise ValueError("profile arms must require a fresh process and CUDA context")
    left_process_id = left_custody.get("process_id")
    right_process_id = right_custody.get("process_id")
    if (
        type(left_process_id) is not int
        or type(right_process_id) is not int
        or left_process_id <= 0
        or right_process_id <= 0
        or left_process_id == right_process_id
    ):
        raise ValueError("profile arms must come from distinct fresh process IDs")
    left_gpu_uuid = left_custody.get("gpu_uuid")
    right_gpu_uuid = right_custody.get("gpu_uuid")
    if not isinstance(left_gpu_uuid, str) or not left_gpu_uuid or left_gpu_uuid != right_gpu_uuid:
        raise ValueError("profile arms must bind the same GPU UUID")
    if (
        right_custody.get("arm_a_raw_sha256") != arm_a_raw_sha256
        or right_custody.get("arm_a_self_sha256") != left.get("self_sha256")
    ):
        raise ValueError("Arm B does not bind the exact Arm A receipt presented for comparison")
    preflight_raw_sha256 = left_custody.get("preflight_raw_sha256")
    preflight_self_sha256 = left_custody.get("preflight_self_sha256")
    _require_sha(preflight_raw_sha256, "comparison preflight raw receipt")
    _require_sha(preflight_self_sha256, "comparison preflight self receipt")
    if (
        right_custody.get("preflight_raw_sha256") != preflight_raw_sha256
        or right_custody.get("preflight_self_sha256") != preflight_self_sha256
    ):
        raise ValueError("profile arms do not bind the same exact preflight receipt")
    first_a_temp = float(left["power_rows"][0]["temperature_c"])
    first_b_temp = float(
        right["first_temperature_c"]
        if right.get("schema_version") == "ember-issue1946-complete-update-arm-oom-v1"
        else right["power_rows"][0]["temperature_c"]
    )
    if first_b_temp > first_a_temp + 2.0:
        raise ValueError("arm B thermal re-baseline gate failed")
    warmups = [float(value) for value in left["warmup_update_seconds"]]
    warmup_median = statistics.median(warmups)
    mad = statistics.median(abs(value - warmup_median) for value in warmups)
    frozen_r = max(0.01, 3.0 * 1.4826 * mad / warmup_median)
    median_a = statistics.median(float(value) for value in left["measured_update_seconds"])
    if right.get("schema_version") == "ember-issue1946-complete-update-arm-oom-v1":
        return _self_hashed({
            "schema_version": "ember-issue1946-recompute-comparison-v1",
            "result": "PASS",
            "claim_boundary": "ALL_OFF_POLICY_ONLY_SELECTIVE_UNADJUDICATED",
            "arm_a_self_sha256": left["self_sha256"],
            "arm_b_self_sha256": right["self_sha256"],
            "arm_a_raw_sha256": arm_a_raw_sha256,
            "preflight_raw_sha256": preflight_raw_sha256,
            "preflight_self_sha256": preflight_self_sha256,
            "frozen_R": frozen_r,
            "median_a_seconds": median_a,
            "median_b_seconds": None,
            "relative_median_improvement": None,
            "hypothesis_supported": False,
            "all_off_result": "OOM",
            "measured_vram_gap_bytes": right["measured_vram_gap_bytes"],
            "successor_input": {
                "retained_policy": "WHOLE_LAYER_RECOMPUTE",
                "measured_wall_seconds": median_a,
                "selective_recompute_study": "C1-W1-RECOMPUTE-REMOVAL",
                "selective_recompute_adjudicated": False,
                "measured_vram_gap_bytes": right["measured_vram_gap_bytes"],
            },
        })
    median_b = statistics.median(float(value) for value in right["measured_update_seconds"])
    improvement = (median_a - median_b) / median_a
    removable_by_owner = {
        owner: max(
            0.0,
            (
                statistics.median(float(row[owner]) for row in left["phase_seconds"][16:])
                - statistics.median(float(row[owner]) for row in right["phase_seconds"][16:])
            ) * 1000.0,
        )
        for owner in sorted(_PHASES)
    }
    first_owner = max(
        _PHASES,
        key=lambda owner: statistics.median(float(row[owner]) for row in left["phase_seconds"][16:]),
    )
    return _self_hashed({
        "schema_version": "ember-issue1946-recompute-comparison-v1",
        "result": "PASS",
        "claim_boundary": "CURRENT_AUDIO64_SYSTEMS_MEASUREMENT_ONLY",
        "arm_a_self_sha256": left["self_sha256"],
        "arm_b_self_sha256": right["self_sha256"],
        "arm_a_raw_sha256": arm_a_raw_sha256,
        "preflight_raw_sha256": preflight_raw_sha256,
        "preflight_self_sha256": preflight_self_sha256,
        "frozen_R": frozen_r,
        "median_a_seconds": median_a,
        "median_b_seconds": median_b,
        "relative_median_improvement": improvement,
        "hypothesis_supported": improvement > frozen_r,
        "saved_activation_bytes": max(0, int(right["memory"]["peak_allocated_bytes"]) - int(left["memory"]["peak_allocated_bytes"])),
        "successor_input": {
            "retained_policy": "DISABLED_EVERY_LAYER" if improvement > frozen_r else "WHOLE_LAYER_RECOMPUTE",
            "measured_wall_seconds": min(median_a, median_b),
            "maximum_removable_milliseconds_by_owner": removable_by_owner,
            "first_owner": first_owner,
        },
    })
