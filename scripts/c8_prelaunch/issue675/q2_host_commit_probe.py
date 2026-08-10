# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Measure the cumulative process commit high-water for the #675 dry run.

The production sampler uses Windows ``PeakPagefileUsage`` (committed virtual
memory high-water), not RSS and not an estimate.  Tests inject a sampler; the
resulting trace is consumed by ``q2_host_commit_simulation``.
"""

from __future__ import annotations

import ctypes
import json
import os
import re
import time
from pathlib import Path
from typing import Callable, Mapping

from ctypes import wintypes


PHASES = (
    ("model_reconstruction", "checkpoint_writer"),
    ("optimizer_momentum", "checkpoint_writer"),
    ("frozen_batch", "training_data_loader"),
    ("capture_staging", "checkpoint_writer"),
    ("python_cuda_host_overhead", "telemetry_buffer"),
)
_BINDING_KEYS = {
    "measurement_tool_sha256",
    "config_sha256",
    "checkpoint_manifest_sha256",
    "batch_manifest_sha256",
    "producer_sha256",
}
_SHA256 = re.compile(r"[0-9a-f]{64}")
_COMMIT = re.compile(r"[0-9a-f]{40}")
_JOB_ID = re.compile(r"[A-Za-z0-9_.-]{1,128}")


class HostCommitProbeRefusal(ValueError):
    """Named refusal for a non-measured or incomplete commit trace."""


def _refuse(code: str) -> None:
    raise HostCommitProbeRefusal(code)


def _plain_positive(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def windows_peak_commit_bytes() -> int:
    """Return this process's OS-reported committed-memory high-water."""

    if os.name != "nt":
        _refuse("HOST_COMMIT_OS_PROBE_UNAVAILABLE")

    class PROCESS_MEMORY_COUNTERS_EX(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
            ("PrivateUsage", ctypes.c_size_t),
        ]

    counters = PROCESS_MEMORY_COUNTERS_EX()
    counters.cb = ctypes.sizeof(counters)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    psapi.GetProcessMemoryInfo.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(PROCESS_MEMORY_COUNTERS_EX),
        wintypes.DWORD,
    ]
    psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
    process = kernel32.GetCurrentProcess()
    ok = psapi.GetProcessMemoryInfo(process, ctypes.byref(counters), counters.cb)
    if not ok or not _plain_positive(int(counters.PeakPagefileUsage)):
        _refuse("HOST_COMMIT_OS_PROBE_FAILED")
    return int(counters.PeakPagefileUsage)


class HostCommitProbe:
    """Record an ordered five-phase cumulative commit high-water trace."""

    def __init__(
        self,
        *,
        job_id: str,
        source_commit: str,
        bindings: Mapping[str, str],
        peak_commit_sampler: Callable[[], int] = windows_peak_commit_bytes,
        clock_ms: Callable[[], int] = lambda: time.time_ns() // 1_000_000,
        pid: int | None = None,
    ) -> None:
        if not isinstance(job_id, str) or _JOB_ID.fullmatch(job_id) is None:
            _refuse("HOST_COMMIT_JOB_ID_INVALID")
        if not isinstance(source_commit, str) or _COMMIT.fullmatch(source_commit) is None:
            _refuse("HOST_COMMIT_SOURCE_COMMIT_INVALID")
        if (
            not isinstance(bindings, Mapping)
            or set(bindings) != _BINDING_KEYS
            or any(not isinstance(value, str) or _SHA256.fullmatch(value) is None for value in bindings.values())
        ):
            _refuse("HOST_COMMIT_BINDINGS_INVALID")
        self._job_id = job_id
        self._source_commit = source_commit
        self._bindings = dict(bindings)
        self._sampler = peak_commit_sampler
        self._clock = clock_ms
        self._pid = os.getpid() if pid is None else pid
        if not _plain_positive(self._pid):
            _refuse("HOST_COMMIT_PROCESS_INVALID")
        self._started_at = self._clock()
        if not isinstance(self._started_at, int) or isinstance(self._started_at, bool):
            _refuse("HOST_COMMIT_CLOCK_INVALID")
        self._previous_peak = self._sample_peak()
        self._rows: list[dict[str, object]] = []
        self._active_name: str | None = None
        self._active_samples: list[int] = []

    def _sample_peak(self) -> int:
        try:
            value = self._sampler()
        except Exception:
            _refuse("HOST_COMMIT_OS_PROBE_FAILED")
        if not _plain_positive(value):
            _refuse("HOST_COMMIT_OS_PROBE_FAILED")
        if hasattr(self, "_previous_peak") and value < self._previous_peak:
            _refuse("HOST_COMMIT_HIGH_WATER_REGRESSED")
        return value

    def begin_phase(self, name: str) -> None:
        if self._active_name is not None:
            _refuse("HOST_COMMIT_PHASE_OVERLAP")
        if len(self._rows) >= len(PHASES) or name != PHASES[len(self._rows)][0]:
            _refuse("HOST_COMMIT_PHASE_ORDER_INVALID")
        self._active_name = name
        self._active_samples = []

    def sample(self) -> int:
        if self._active_name is None:
            _refuse("HOST_COMMIT_PHASE_NOT_ACTIVE")
        value = self._sample_peak()
        self._active_samples.append(value)
        return value

    def end_phase(self) -> None:
        if self._active_name is None:
            _refuse("HOST_COMMIT_PHASE_NOT_ACTIVE")
        self._active_samples.append(self._sample_peak())
        if len(self._active_samples) < 2:
            _refuse("HOST_COMMIT_PHASE_UNDERSAMPLED")
        peak = max(self._active_samples)
        if peak <= self._previous_peak:
            _refuse("HOST_COMMIT_PHASE_NO_GROWTH")
        ordinal = len(self._rows)
        expected_name, producer = PHASES[ordinal]
        if self._active_name != expected_name:
            _refuse("HOST_COMMIT_PHASE_ORDER_INVALID")
        self._rows.append(
            {
                "ordinal": ordinal,
                "name": expected_name,
                "producer_kind": producer,
                "baseline_commit_bytes": self._previous_peak,
                "peak_commit_bytes": peak,
                "sample_count": len(self._active_samples),
                "measurement_source": "os_commit_probe",
            }
        )
        self._previous_peak = peak
        self._active_name = None
        self._active_samples = []

    def finish(self, *, exit_code: int) -> dict[str, object]:
        if self._active_name is not None or len(self._rows) != len(PHASES):
            _refuse("HOST_COMMIT_PHASE_SET_INVALID")
        if exit_code != 0:
            _refuse("HOST_COMMIT_DRY_RUN_FAILED")
        ended_at = self._clock()
        if (
            not isinstance(ended_at, int)
            or isinstance(ended_at, bool)
            or ended_at <= self._started_at
        ):
            _refuse("HOST_COMMIT_CLOCK_INVALID")
        return {
            "schema_version": "q2-host-commit-measurement-v1",
            "job_id": self._job_id,
            "measurement_mode": "bounded_dry_run",
            "source_commit": self._source_commit,
            "process": {
                "pid": self._pid,
                "started_at_ms": self._started_at,
                "ended_at_ms": ended_at,
                "exit_code": 0,
            },
            "bindings": dict(self._bindings),
            "phases": [dict(row) for row in self._rows],
        }


def write_trace_atomic(path: Path, trace: Mapping[str, object]) -> None:
    """Write a small trace in the target directory, then atomically replace."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(target.name + ".tmp")
    raw = json.dumps(trace, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(raw) > 1024 * 1024:
        _refuse("HOST_COMMIT_TRACE_TOO_LARGE")
    try:
        with temp.open("xb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, target)
    except OSError:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass
        _refuse("HOST_COMMIT_TRACE_WRITE_FAILED")
