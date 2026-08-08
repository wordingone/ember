#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Run one command inside an owned process tree with a finite timeout."""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import signal
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Mapping, Sequence


class ProcessContainmentError(RuntimeError):
    """The command could not be placed under process-tree ownership."""


@dataclass(frozen=True)
class OwnedProcessResult:
    command: list[str]
    pid: int
    timeout_s: float
    status: str
    returncode: int
    stdout: str
    stderr: str
    backend: str
    cleanup_verified: bool


if sys.platform == "win32":
    from ctypes import wintypes

    class _JobBasicLimitInformation(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _IoCounters(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class _JobExtendedLimitInformation(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _JobBasicLimitInformation),
            ("IoInfo", _IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _ntdll = ctypes.WinDLL("ntdll", use_last_error=True)
    _kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    _kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    _kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    _kernel32.SetInformationJobObject.restype = wintypes.BOOL
    _kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    _kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.CloseHandle.restype = wintypes.BOOL
    _ntdll.NtResumeProcess.argtypes = [wintypes.HANDLE]
    _ntdll.NtResumeProcess.restype = ctypes.c_long
    _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
    _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000

    class _WindowsJob:
        def __init__(self) -> None:
            self._handle = _kernel32.CreateJobObjectW(None, None)
            if not self._handle:
                raise ProcessContainmentError(f"CreateJobObjectW failed: {ctypes.get_last_error()}")
            info = _JobExtendedLimitInformation()
            info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not _kernel32.SetInformationJobObject(
                self._handle,
                _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
                ctypes.byref(info),
                ctypes.sizeof(info),
            ):
                error = ctypes.get_last_error()
                self.close()
                raise ProcessContainmentError(f"SetInformationJobObject failed: {error}")

        def assign_and_resume(self, proc: subprocess.Popen[str]) -> None:
            if not _kernel32.AssignProcessToJobObject(self._handle, wintypes.HANDLE(proc._handle)):
                raise ProcessContainmentError(f"AssignProcessToJobObject failed: {ctypes.get_last_error()}")
            status = _ntdll.NtResumeProcess(wintypes.HANDLE(proc._handle))
            if status != 0:
                raise ProcessContainmentError(f"NtResumeProcess failed: 0x{status & 0xFFFFFFFF:08x}")

        def close(self) -> None:
            if self._handle:
                if not _kernel32.CloseHandle(self._handle):
                    raise ProcessContainmentError(f"CloseHandle(job) failed: {ctypes.get_last_error()}")
                self._handle = None

        def __enter__(self) -> "_WindowsJob":
            return self

        def __exit__(self, *_: object) -> None:
            self.close()


class OwnedProcessRunner:
    def __init__(self, *, windows_job_factory=None) -> None:
        self._windows_job_factory = windows_job_factory

    def run(
        self,
        command: Sequence[str],
        *,
        timeout_s: float,
        cwd: str | os.PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
    ) -> OwnedProcessResult:
        argv = [str(part) for part in command]
        if not argv:
            raise ValueError("command must not be empty")
        if not isinstance(timeout_s, (int, float)) or timeout_s <= 0:
            raise ValueError("timeout_s must be positive")
        if sys.platform == "win32":
            return self._run_windows(argv, float(timeout_s), cwd=cwd, env=env)
        return self._run_posix(argv, float(timeout_s), cwd=cwd, env=env)

    def _run_windows(self, argv: list[str], timeout_s: float, *, cwd: str | os.PathLike[str] | None, env: Mapping[str, str] | None) -> OwnedProcessResult:
        creationflags = 0x00000004 | subprocess.CREATE_NEW_PROCESS_GROUP  # CREATE_SUSPENDED
        job_factory = self._windows_job_factory or _WindowsJob
        with job_factory() as job:
            proc = subprocess.Popen(
                argv, cwd=cwd, env=dict(env) if env is not None else None,
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, creationflags=creationflags,
            )
            try:
                job.assign_and_resume(proc)
            except Exception:
                if proc.poll() is None:
                    proc.kill()
                job.close()
                proc.wait(timeout=5)
                raise
            timed_out = False
            try:
                stdout, stderr = proc.communicate(timeout=timeout_s)
            except subprocess.TimeoutExpired:
                timed_out = True
                job.close()
                stdout, stderr = proc.communicate(timeout=5)
            finally:
                job.close()
        return OwnedProcessResult(argv, proc.pid, timeout_s, "terminated" if timed_out else "completed", int(proc.returncode), stdout, stderr, "windows-job-object", True)

    def _run_posix(self, argv: list[str], timeout_s: float, *, cwd: str | os.PathLike[str] | None, env: Mapping[str, str] | None) -> OwnedProcessResult:
        proc = subprocess.Popen(
            argv, cwd=cwd, env=dict(env) if env is not None else None,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, start_new_session=True,
        )
        timed_out = False
        try:
            stdout, stderr = proc.communicate(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            timed_out = True
            self._kill_posix_group(proc.pid)
            stdout, stderr = proc.communicate(timeout=5)
        finally:
            self._kill_posix_group(proc.pid)
        return OwnedProcessResult(argv, proc.pid, timeout_s, "terminated" if timed_out else "completed", int(proc.returncode), stdout, stderr, "posix-process-group", True)

    @staticmethod
    def _kill_posix_group(pid: int) -> None:
        try:
            os.killpg(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout-seconds", type=float, required=True)
    parser.add_argument("--cwd", type=Path)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    try:
        result = OwnedProcessRunner().run(command, timeout_s=args.timeout_seconds, cwd=args.cwd)
    except (ProcessContainmentError, ValueError) as exc:
        print(f"OWNED_PROCESS_REFUSED: {exc}", file=sys.stderr)
        return 125
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    status = asdict(result)
    status.pop("stdout")
    status.pop("stderr")
    print(f"OWNED_PROCESS_STATUS {json.dumps(status, sort_keys=True)}", file=sys.stderr)
    return 124 if result.status == "terminated" else result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
