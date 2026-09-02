#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Closed receipts for #1946's complete-update recompute experiment."""

from __future__ import annotations

import hashlib
import json
import math
import os
import statistics
import subprocess
import threading
import time
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
_WALL_OWNERS = {
    "data", "projection", "attention", "mlp_routing", "norm_rope_residual", "loss",
    "backward", "gradient_clipping", "optimizer", "precision",
    "launch_graph_synchronization", "checkpoint", "telemetry", "explicit_remainder",
}
_FORWARD_OWNERS = {
    "projection", "attention", "mlp_routing", "norm_rope_residual", "loss",
    "precision", "launch_graph_synchronization",
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
    def query(fields: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["nvidia-smi", f"--query-gpu={fields}", "--format=csv,noheader,nounits"],
            text=True, capture_output=True, check=False, shell=False, creationflags=creationflags,
        )

    base_fields = "uuid,clocks.sm,clocks.mem,temperature.gpu,power.draw,memory.used,memory.total"
    completed = query(base_fields + ",total_energy_consumption")
    energy_supported = completed.returncode == 0
    if not energy_supported:
        completed = query(base_fields)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "nvidia-smi GPU covariate query failed")
    rows = [row.strip() for row in completed.stdout.splitlines() if row.strip()]
    if len(rows) != 1:
        raise RuntimeError("#1946 requires exactly one governed physical GPU")
    fields = [field.strip() for field in rows[0].split(",")]
    if len(fields) != (8 if energy_supported else 7):
        raise RuntimeError("nvidia-smi GPU covariate row is malformed")
    result = {
        "gpu_uuid": fields[0],
        "sm_clock_mhz": int(float(fields[1])),
        "memory_clock_mhz": int(float(fields[2])),
        "temperature_c": float(fields[3]),
        "power_w": float(fields[4]),
        "memory_used_mib": float(fields[5]),
        "memory_total_mib": float(fields[6]),
    }
    if energy_supported:
        try:
            result["total_energy_mj"] = int(float(fields[7]))
        except ValueError:
            energy_supported = False
    return result


def energy_counter_delta_joules(start_mj: float, end_mj: float) -> float:
    start = float(start_mj)
    end = float(end_mj)
    if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end < start:
        raise ValueError("total-energy counter must be finite, nonnegative, and monotonic")
    return (end - start) / 1000.0


def trapezoidal_energy_joules(samples: Sequence[tuple[float, float]]) -> float:
    rows = [(float(timestamp), float(power)) for timestamp, power in samples]
    if len(rows) < 2:
        raise ValueError("energy fallback requires at least two fixed-interval samples")
    if any(not math.isfinite(t) or not math.isfinite(p) or p < 0 for t, p in rows):
        raise ValueError("energy samples must be finite with nonnegative power")
    if any(right[0] <= left[0] for left, right in zip(rows, rows[1:])):
        raise ValueError("energy sample timestamps must be strictly monotonic")
    return sum(
        (right_time - left_time) * (left_power + right_power) / 2.0
        for (left_time, left_power), (right_time, right_power) in zip(rows, rows[1:])
    )


class BoardEnergyTracker:
    """Per-update NVML energy deltas with a fixed-interval power fallback."""

    def __init__(self, *, interval_seconds: float = 0.25) -> None:
        if not math.isfinite(interval_seconds) or interval_seconds <= 0:
            raise ValueError("energy sampling interval must be positive")
        self.interval_seconds = float(interval_seconds)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._samples: list[tuple[float, float]] = []
        self._last_row: dict[str, object] | None = None
        self._last_time: float | None = None
        self._error: BaseException | None = None

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("energy tracker was already started")
        row = gpu_covariate()
        now = time.perf_counter()
        self._last_row = row
        self._last_time = now
        self._samples = [(now, float(row["power_w"]))]
        self._thread = threading.Thread(target=self._sample_loop, name="issue1946-energy", daemon=True)
        self._thread.start()

    def _sample_loop(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            try:
                row = gpu_covariate()
                sample = (time.perf_counter(), float(row["power_w"]))
                with self._lock:
                    self._samples.append(sample)
            except BaseException as error:  # surfaced synchronously at the next boundary
                self._error = error
                return

    def capture_update(self) -> dict[str, object]:
        if self._last_row is None or self._last_time is None:
            raise RuntimeError("energy tracker was not started")
        if self._error is not None:
            raise RuntimeError("fixed-interval board-energy sampler failed") from self._error
        row = gpu_covariate()
        now = time.perf_counter()
        previous_counter = self._last_row.get("total_energy_mj")
        current_counter = row.get("total_energy_mj")
        if previous_counter is not None and current_counter is not None:
            joules = energy_counter_delta_joules(float(previous_counter), float(current_counter))
            method = "NVML_TOTAL_ENERGY_COUNTER_DELTA"
        else:
            with self._lock:
                samples = [sample for sample in self._samples if sample[0] >= self._last_time]
            boundary_samples = [(self._last_time, float(self._last_row["power_w"])), *samples, (now, float(row["power_w"]))]
            deduplicated = [boundary_samples[0]]
            for sample in boundary_samples[1:]:
                if sample[0] > deduplicated[-1][0]:
                    deduplicated.append(sample)
            joules = trapezoidal_energy_joules(deduplicated)
            method = "FIXED_INTERVAL_TRAPEZOID"
        self._last_row = row
        self._last_time = now
        with self._lock:
            self._samples = [(now, float(row["power_w"]))]
        return {**row, "board_energy_joules": joules, "energy_measurement_method": method}

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(1.0, 4 * self.interval_seconds))
            if self._thread.is_alive():
                raise RuntimeError("fixed-interval board-energy sampler did not stop")


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
        declared = _require_sha(row.get("raw_sha256"), f"{row.get('role')} declared raw hash")
        computed = hashlib.sha256(artifact.read_bytes()).hexdigest()
        if computed != declared:
            raise ValueError(f"{row.get('role')} declared raw hash mismatch")
        reopened.append({**dict(row), "declared_raw_sha256": declared, "computed_raw_sha256": computed})
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


def derive_wall_owner_rows(
    phase_seconds: Sequence[Mapping[str, object]],
    forward_owner_device_time_us: Mapping[str, object],
    *,
    forward_unmapped_device_time_us: float,
) -> list[dict[str, float]]:
    if set(forward_owner_device_time_us) != _FORWARD_OWNERS:
        raise ValueError("kernel trace must use the closed forward-owner set")
    weights = {owner: float(forward_owner_device_time_us[owner]) for owner in _FORWARD_OWNERS}
    unmapped = float(forward_unmapped_device_time_us)
    if any(not math.isfinite(v) or v < 0 for v in weights.values()) or not math.isfinite(unmapped) or unmapped < 0:
        raise ValueError("kernel-to-owner device-time weights must be finite and nonnegative")
    denominator = sum(weights.values()) + unmapped
    if denominator <= 0:
        raise ValueError("kernel-to-owner device-time evidence must be positive")
    result = []
    for raw_phase in phase_seconds:
        if set(raw_phase) != _PHASES:
            raise ValueError("phase row must use the closed attribution owner set")
        phase = {key: float(raw_phase[key]) for key in _PHASES}
        if any(not math.isfinite(v) or v < 0 for v in phase.values()):
            raise ValueError("phase timing values must be finite and nonnegative")
        forward_wall = phase["reference_forward"] + phase["forward"]
        row = {owner: 0.0 for owner in _WALL_OWNERS}
        row["data"] = phase["data_readiness"]
        for owner, weight in weights.items():
            row[owner] = forward_wall * weight / denominator
        row["backward"] = phase["backward"]
        row["gradient_clipping"] = phase["gradient_clipping"]
        row["optimizer"] = phase["optimizer"]
        row["launch_graph_synchronization"] += phase["mandatory_synchronization"]
        row["checkpoint"] = 0.0
        row["telemetry"] = phase["telemetry_checkpoint"]
        row["explicit_remainder"] = phase["explicit_remainder"] + forward_wall * unmapped / denominator
        direct_total = sum(phase.values())
        if direct_total <= 0 or not 0.99 <= sum(row.values()) / direct_total <= 1.01:
            raise ValueError("derived wall owners must cover 99 to 101 percent of direct wall")
        result.append(row)
    return result


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
    checkpoint_cadence: Mapping[str, object],
) -> dict[str, object]:
    if policy not in {"WHOLE_LAYER_RECOMPUTE", "DISABLED_EVERY_LAYER"}:
        raise ValueError("profile arm must use one of the two frozen recompute policies")
    expected_identity = {
        "execution_source_commit", "parameter_sha256", "optimizer_initial_state_sha256",
        "cpu_rng_state_sha256", "cuda_rng_state_sha256", "config_sha256",
        "seed", "initial_cursor", "selection_receipt_sha256",
        "stream_manifest_sha256", "stream_build_receipt_sha256", "tokenizer_sha256",
        "execution_record_order_sha256", "execution_tokens_sha256",
    }
    if set(identity) != expected_identity:
        raise ValueError("profile arm identity must use its closed fields")
    _require_sha(identity["execution_source_commit"], "execution source commit", length=40)
    _require_sha(identity["parameter_sha256"], "parameter identity")
    _require_sha(identity["selection_receipt_sha256"], "selection receipt")
    for key in (
        "optimizer_initial_state_sha256", "cpu_rng_state_sha256", "cuda_rng_state_sha256",
        "config_sha256", "stream_manifest_sha256", "stream_build_receipt_sha256",
        "tokenizer_sha256", "execution_record_order_sha256", "execution_tokens_sha256",
    ):
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
    owner_weights = kernel_trace.get("forward_owner_device_time_us")
    if not isinstance(owner_weights, Mapping):
        raise ValueError("kernel trace must bind forward-owner device-time evidence")
    derived_owner_rows = derive_wall_owner_rows(
        [item[0] for item in phases_and_fractions],
        owner_weights,
        forward_unmapped_device_time_us=float(kernel_trace.get("forward_unmapped_device_time_us", -1)),
    )
    if dict(checkpoint_cadence) != {
        "in_measured_window": "NONE",
        "checkpoint_every_updates": 65,
        "callback_identity": "NO_OP",
        "final_callback_timed": False,
    }:
        raise ValueError("checkpoint cadence must disclose the frozen no-checkpoint measured window")
    measured = timings[16:]
    governed = timings[24:]
    governed_sorted = sorted(governed)
    p10 = governed_sorted[math.ceil(0.10 * len(governed_sorted)) - 1]
    p90 = governed_sorted[math.ceil(0.90 * len(governed_sorted)) - 1]
    peak_allocated = max(int(row["allocated"]) for row in allocator_rows)
    peak_reserved = max(int(row["reserved"]) for row in allocator_rows)
    peak_workspace = max(int(row["workspace"]) for row in allocator_rows)
    peak_graph_pool = max(int(row["graph_pool"]) for row in allocator_rows)
    peak_fragmentation = max(int(row["fragmentation"]) for row in allocator_rows)
    energy_methods = {row.get("energy_measurement_method") for row in power_rows}
    if len(energy_methods) != 1 or next(iter(energy_methods)) not in {
        "NVML_TOTAL_ENERGY_COUNTER_DELTA", "FIXED_INTERVAL_TRAPEZOID",
    }:
        raise ValueError("power rows must use one governed board-energy measurement method")
    energy_method = str(next(iter(energy_methods)))
    energy = [float(row["board_energy_joules"]) for row in power_rows]
    if any(not math.isfinite(value) or value < 0 for value in energy):
        raise ValueError("board energy rows must be finite and nonnegative")
    compute_factor = 8 if policy == "WHOLE_LAYER_RECOMPUTE" else 6
    active_parameters = 1_725_232_640
    median_seconds = statistics.median(governed)
    profiler_seconds = timings[16:24]
    return _self_hashed({
        "schema_version": "ember-issue1946-complete-update-arm-v1",
        "result": "PASS",
        "claim_boundary": "CURRENT_AUDIO64_SYSTEMS_MEASUREMENT_ONLY",
        "policy": policy,
        "identity": dict(identity),
        "counts": {"complete_updates": 64, "warmup": 16, "measured": 48, "profiler": 8, "governed_nonprofiled": 40},
        "update_seconds": timings,
        "warmup_update_seconds": timings[:16],
        "measured_update_seconds": measured,
        "governed_nonprofiled_update_indexes": list(range(24, 64)),
        "governed_nonprofiled_update_seconds": governed,
        "profiler_instrumented_update_seconds": profiler_seconds,
        "profiler_overhead_seconds": [
            {"index": index, "seconds": timings[index], "delta_vs_nonprofiled_median_seconds": timings[index] - median_seconds}
            for index in profiler
        ],
        "complete_update_distribution_seconds": {"p10": p10, "median": median_seconds, "p90": p90},
        "phase_seconds": [item[0] for item in phases_and_fractions],
        "derived_wall_owner_rows": derived_owner_rows,
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
        "energy_measurement_method": energy_method,
        "checkpoint_cadence": dict(checkpoint_cadence),
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
    median_a = statistics.median(float(value) for value in left["governed_nonprofiled_update_seconds"])
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
    median_b = statistics.median(float(value) for value in right["governed_nonprofiled_update_seconds"])
    improvement = (median_a - median_b) / median_a
    removable_by_owner = {
        owner: max(
            0.0,
            (
                statistics.median(float(row[owner]) for row in left["derived_wall_owner_rows"][24:])
                - statistics.median(float(row[owner]) for row in right["derived_wall_owner_rows"][24:])
            ) * 1000.0,
        )
        for owner in sorted(_WALL_OWNERS)
    }
    first_owner = max(
        _WALL_OWNERS,
        key=lambda owner: statistics.median(float(row[owner]) for row in left["derived_wall_owner_rows"][24:]),
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
