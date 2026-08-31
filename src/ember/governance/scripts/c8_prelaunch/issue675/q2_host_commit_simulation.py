# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Validate a measured #675 host-commit dry run and seal its dispatch inputs.

This module does not estimate memory and does not dispatch work.  It converts a
closed, OS-measured phase trace into the exact conservative peak and producer
budgets consumed by Ember Lab's governed dispatch manifest.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping


_TOP_FIELDS = {
    "schema_version",
    "job_id",
    "measurement_mode",
    "source_commit",
    "process",
    "bindings",
    "phases",
}
_PROCESS_FIELDS = {"pid", "started_at_ms", "ended_at_ms", "exit_code"}
_BINDING_FIELDS = {
    "measurement_tool_sha256",
    "config_sha256",
    "checkpoint_manifest_sha256",
    "batch_manifest_sha256",
    "producer_sha256",
}
_PHASE_FIELDS = {
    "ordinal",
    "name",
    "producer_kind",
    "baseline_commit_bytes",
    "peak_commit_bytes",
    "sample_count",
    "measurement_source",
}
_PHASES = (
    ("model_reconstruction", "checkpoint_writer"),
    ("optimizer_momentum", "checkpoint_writer"),
    ("frozen_batch", "training_data_loader"),
    ("capture_staging", "checkpoint_writer"),
    ("python_cuda_host_overhead", "telemetry_buffer"),
)
_SHA256 = re.compile(r"[0-9a-f]{64}")
_COMMIT = re.compile(r"[0-9a-f]{40}")
_JOB_ID = re.compile(r"[A-Za-z0-9_.-]{1,128}")


class HostCommitRefusal(ValueError):
    """Named fail-closed refusal for an unusable measurement trace."""


def _refuse(code: str) -> None:
    raise HostCommitRefusal(code)


def _plain_int(value: object, *, minimum: int = 0) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= minimum


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def receipt_sha256(receipt: Mapping[str, Any]) -> str:
    unsigned = dict(receipt)
    unsigned.pop("receipt_sha256", None)
    return hashlib.sha256(_canonical_bytes(unsigned)).hexdigest()


def _read_trace(path: Path) -> dict[str, Any]:
    try:
        raw = Path(path).read_bytes()
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        _refuse("HOST_COMMIT_TRACE_UNREADABLE")
    if not isinstance(value, dict) or set(value) != _TOP_FIELDS:
        _refuse("HOST_COMMIT_TRACE_SCHEMA_INVALID")
    return value


def validate_host_commit_measurement(trace_path: Path) -> dict[str, Any]:
    """Return path-free, self-hashed dispatch inputs from an exact measured trace."""

    trace = _read_trace(trace_path)
    if trace["schema_version"] != "q2-host-commit-measurement-v1":
        _refuse("HOST_COMMIT_TRACE_SCHEMA_INVALID")
    if trace["measurement_mode"] != "bounded_dry_run":
        _refuse("HOST_COMMIT_NOT_MEASURED")
    if not isinstance(trace["job_id"], str) or _JOB_ID.fullmatch(trace["job_id"]) is None:
        _refuse("HOST_COMMIT_JOB_ID_INVALID")
    if not isinstance(trace["source_commit"], str) or _COMMIT.fullmatch(trace["source_commit"]) is None:
        _refuse("HOST_COMMIT_SOURCE_COMMIT_INVALID")

    process = trace["process"]
    if not isinstance(process, dict) or set(process) != _PROCESS_FIELDS:
        _refuse("HOST_COMMIT_PROCESS_SCHEMA_INVALID")
    if (
        not _plain_int(process["pid"], minimum=1)
        or not _plain_int(process["started_at_ms"])
        or not _plain_int(process["ended_at_ms"])
        or process["ended_at_ms"] <= process["started_at_ms"]
        or process["exit_code"] != 0
    ):
        _refuse("HOST_COMMIT_DRY_RUN_FAILED")

    bindings = trace["bindings"]
    if (
        not isinstance(bindings, dict)
        or set(bindings) != _BINDING_FIELDS
        or any(not isinstance(value, str) or _SHA256.fullmatch(value) is None for value in bindings.values())
    ):
        _refuse("HOST_COMMIT_BINDINGS_INVALID")

    phases = trace["phases"]
    if not isinstance(phases, list) or len(phases) != len(_PHASES):
        _refuse("HOST_COMMIT_PHASE_SET_INVALID")

    producer_budgets = {
        "training_data_loader": 0,
        "checkpoint_writer": 0,
        "telemetry_buffer": 0,
    }
    measured_rows: list[dict[str, Any]] = []
    previous_peak: int | None = None
    for ordinal, ((expected_name, expected_producer), row) in enumerate(zip(_PHASES, phases)):
        if not isinstance(row, dict) or set(row) != _PHASE_FIELDS:
            _refuse("HOST_COMMIT_PHASE_SCHEMA_INVALID")
        if row["ordinal"] != ordinal:
            _refuse("HOST_COMMIT_PHASE_ORDER_INVALID")
        if row["name"] != expected_name or row["producer_kind"] != expected_producer:
            _refuse("HOST_COMMIT_PHASE_SET_INVALID")
        if row["measurement_source"] != "os_commit_probe":
            _refuse("HOST_COMMIT_PHASE_NOT_OS_MEASURED")
        if not _plain_int(row["sample_count"], minimum=2):
            _refuse("HOST_COMMIT_PHASE_UNDERSAMPLED")
        baseline = row["baseline_commit_bytes"]
        peak = row["peak_commit_bytes"]
        if not _plain_int(baseline) or not _plain_int(peak, minimum=1) or peak <= baseline:
            _refuse("HOST_COMMIT_PHASE_RANGE_INVALID")
        if previous_peak is not None and baseline != previous_peak:
            _refuse("HOST_COMMIT_PHASE_OVERLAP_OR_GAP")
        measured_bytes = peak - baseline
        producer_budgets[expected_producer] += measured_bytes
        measured_rows.append(
            {
                "ordinal": ordinal,
                "name": expected_name,
                "producer_kind": expected_producer,
                "measured_commit_bytes": measured_bytes,
                "sample_count": row["sample_count"],
                "measurement_source": "os_commit_probe",
            }
        )
        previous_peak = peak

    simulated_peak = sum(producer_budgets.values())
    if simulated_peak <= 0 or any(value <= 0 for value in producer_budgets.values()):
        _refuse("HOST_COMMIT_PRODUCER_BUDGET_INVALID")

    receipt: dict[str, Any] = {
        "schema_version": "q2-host-commit-simulation-receipt-v1",
        "job_id": trace["job_id"],
        "source_commit": trace["source_commit"],
        "measurement_mode": "bounded_dry_run",
        "process": dict(process),
        "bindings": dict(bindings),
        "phases": measured_rows,
        "simulated_peak_commit_bytes": simulated_peak,
        "maximum_job_memory_bytes": simulated_peak,
        "producer_budgets": producer_budgets,
        "trace_sha256": sha256_file(trace_path),
        "event_credit": False,
        "scientific_credit": False,
        "no_new_parallel_authority": True,
    }
    receipt["receipt_sha256"] = receipt_sha256(receipt)
    return receipt
