#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Run one command inside an owned process tree with a finite timeout."""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import signal
import stat
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Mapping, Sequence


_SIGKILL = int(getattr(signal, "SIGKILL", 9))
_POSIX_GUARD_FLAG = "--owned-process-posix-guard"


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


def _posix_controller_death_backend(platform: str | None = None) -> str | None:
    """Return the closed controller-death backend for a POSIX platform.

    The public runner remains the sole process authority.  The private
    process-group sentinel installed by that runner is only a kernel-facing
    cleanup guard; it is not a second launcher or caller-visible API.
    """
    platform_name = sys.platform if platform is None else platform
    if platform_name == "linux":
        return "linux-prctl-pdeathsig+process-group-sentinel"
    if platform_name == "darwin":
        return "darwin-process-group-sentinel"
    return None


def _set_linux_parent_death_signal() -> None:
    """Arm Linux's native fast path; the pipe sentinel remains authoritative."""
    libc = ctypes.CDLL(None, use_errno=True)
    prctl = getattr(libc, "prctl", None)
    if prctl is None or prctl(1, _SIGKILL, 0, 0, 0) != 0:
        error = ctypes.get_errno()
        raise ProcessContainmentError(f"prctl(PR_SET_PDEATHSIG) failed: {error}")


def _monitor_controller_pipe(death_fd: int, process_group: int) -> None:
    """Kill the command group when the controller-owned pipe reaches EOF.

    EOF is a kernel-held lifetime token: it cannot confuse PID reuse for the
    original controller and needs no Darwin-only process API.  The sentinel is
    forked only after this module has been exec'd as the private guard, so it
    cannot inherit CPython Popen's internal pre-exec error pipe.
    """
    try:
        while os.read(death_fd, 1):
            pass
    except OSError:
        pass
    try:
        os.killpg(process_group, _SIGKILL)
    except OSError:
        pass


def _close_sentinel_descriptors(death_fd: int) -> None:
    """Keep only the controller lifetime token in the non-execing sentinel."""
    for descriptor in (0, 1, 2):
        if descriptor != death_fd:
            try:
                os.close(descriptor)
            except OSError:
                pass
    try:
        maximum = int(os.sysconf("SC_OPEN_MAX"))
    except (OSError, ValueError):
        maximum = 256
    os.closerange(3, death_fd)
    os.closerange(death_fd + 1, maximum)


def _validate_posix_guard_context(death_fd: int) -> int:
    """Bind the private guard to its new session and inherited read pipe."""

    pid = os.getpid()
    try:
        process_group = os.getpgrp()
        session = os.getsid(0)
    except (AttributeError, OSError) as exc:
        raise ProcessContainmentError("POSIX guard could not verify its owned session") from exc
    if pid != process_group or pid != session:
        raise ProcessContainmentError("private POSIX guard is not its owned session leader")
    if death_fd < 0:
        raise ProcessContainmentError("private POSIX guard lacks a readable pipe")
    try:
        import fcntl

        descriptor = os.fstat(death_fd)
        flags = fcntl.fcntl(death_fd, fcntl.F_GETFL)
    except (ImportError, OSError) as exc:
        raise ProcessContainmentError("private POSIX guard lacks a readable pipe") from exc
    if not stat.S_ISFIFO(descriptor.st_mode) or (flags & os.O_ACCMODE) != os.O_RDONLY:
        raise ProcessContainmentError("private POSIX guard lacks a readable pipe")
    return process_group


def _install_posix_controller_death_guard(death_fd: int) -> None:
    """Install one private pipe sentinel, plus Linux's native fast path."""
    backend = _posix_controller_death_backend()
    if backend is None:
        raise ProcessContainmentError(f"POSIX controller-death backend unavailable on {sys.platform}")
    process_group = _validate_posix_guard_context(death_fd)
    try:
        monitor_pid = os.fork()
    except OSError as exc:
        raise ProcessContainmentError(f"controller-death sentinel fork failed: {exc}") from exc
    if monitor_pid == 0:
        try:
            _close_sentinel_descriptors(death_fd)
            _monitor_controller_pipe(death_fd, process_group)
        finally:
            os._exit(0)
    os.close(death_fd)
    if backend.startswith("linux-"):
        _set_linux_parent_death_signal()


def _posix_guard_argv(argv: Sequence[str], death_fd: int) -> list[str]:
    return [
        sys.executable,
        str(Path(__file__).resolve()),
        _POSIX_GUARD_FLAG,
        str(death_fd),
        "--",
        *argv,
    ]


def _run_posix_guard(arguments: Sequence[str]) -> int:
    """Become the requested command after installing the private sentinel."""
    if len(arguments) < 3 or arguments[1] != "--":
        raise ProcessContainmentError("internal POSIX guard arguments are invalid")
    try:
        death_fd = int(arguments[0])
    except ValueError as exc:
        raise ProcessContainmentError("internal POSIX guard descriptor is invalid") from exc
    command = [str(part) for part in arguments[2:]]
    if not command:
        raise ProcessContainmentError("internal POSIX guard command is empty")
    _validate_posix_guard_context(death_fd)
    _install_posix_controller_death_guard(death_fd)
    try:
        os.execvpe(command[0], command, os.environ)
    except OSError as exc:
        raise ProcessContainmentError(f"POSIX guarded exec failed: {exc}") from exc


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
        creationflags = (
            0x00000004  # CREATE_SUSPENDED
            | subprocess.CREATE_NEW_PROCESS_GROUP
            | subprocess.CREATE_NO_WINDOW
        )
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
        death_read_fd, death_write_fd = os.pipe()
        try:
            proc = subprocess.Popen(
                _posix_guard_argv(argv, death_read_fd),
                cwd=cwd, env=dict(env) if env is not None else None,
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, start_new_session=True,
                pass_fds=(death_read_fd,),
            )
        except Exception as exc:
            os.close(death_read_fd)
            os.close(death_write_fd)
            raise ProcessContainmentError(f"POSIX controller-death containment refused: {exc}") from exc
        os.close(death_read_fd)
        timed_out = False
        try:
            stdout, stderr = proc.communicate(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            timed_out = True
            self._kill_posix_group(proc.pid)
            stdout, stderr = proc.communicate(timeout=5)
        finally:
            if not timed_out:
                self._kill_posix_group(proc.pid)
            os.close(death_write_fd)
        return OwnedProcessResult(
            argv,
            proc.pid,
            timeout_s,
            "terminated" if timed_out else "completed",
            int(proc.returncode),
            stdout,
            stderr,
            "posix-process-group",
            True,
        )

    @staticmethod
    def _kill_posix_group(pid: int) -> None:
        try:
            os.killpg(pid, _SIGKILL)
        except ProcessLookupError:
            pass


def main() -> int:
    if sys.argv[1:2] == [_POSIX_GUARD_FLAG]:
        try:
            return _run_posix_guard(sys.argv[2:])
        except ProcessContainmentError as exc:
            print(f"OWNED_PROCESS_REFUSED: {exc}", file=sys.stderr)
            return 125
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
    command_parts = status.pop("command")
    status["command_argv_count"] = len(command_parts)
    status["command_sha256"] = hashlib.sha256("\0".join(command_parts).encode("utf-8")).hexdigest()
    print(f"OWNED_PROCESS_STATUS {json.dumps(status, sort_keys=True)}", file=sys.stderr)
    return 124 if result.status == "terminated" else result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
