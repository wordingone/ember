# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Process identity beyond a bare PID (review-pr1310.md MEDIUM-2).

A bare PID is not a stable identity: OSes (Windows especially) reuse PIDs
aggressively, so "is this PID alive" can silently answer about a completely
different, unrelated process that happened to reuse the number after the
original owner died. That makes a mutex holder or a RUNNING node's lock
wedge closed forever (mutex) or read as healthy when it is actually dead
(stale-scan false negative) -- exactly the two failure modes review-pr1310.md
identified.

The fix: record process creation time alongside owner_pid, and require both
to match. Where creation time cannot be determined (platform without a
readable process-start-time source), this degrades gracefully to PID-only
liveness -- but records which mode was used, so a caller (or a human reading
a lock file) can see the degradation instead of silently trusting a bare PID.
"""

from __future__ import annotations

import ctypes
import os
import sys
from typing import Any

MODE_PID_AND_CREATION_TIME = "pid+creation_time"
MODE_PID_ONLY = "pid_only"

# Two identities are considered the same process if their creation times are
# within this many seconds -- filesystem/clock-tick rounding, not a real
# tolerance for "close enough is a different process."
_CREATION_TIME_TOLERANCE_SECONDS = 2.0


def _is_pid_alive_windows(pid: int) -> bool:
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    try:
        exit_code = ctypes.c_ulong()
        STILL_ACTIVE = 259
        if not ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return False
        return exit_code.value == STILL_ACTIVE
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def _is_pid_alive_posix(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # process exists, just owned by someone else
    return True


def is_pid_alive(pid: int) -> bool:
    """Cross-platform bare-PID liveness check without shelling out or new deps."""
    if pid <= 0:
        return False
    if sys.platform == "win32":
        return _is_pid_alive_windows(pid)
    return _is_pid_alive_posix(pid)


def _creation_time_windows(pid: int) -> float | None:
    import ctypes.wintypes as wintypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        creation = wintypes.FILETIME()
        exit_time = wintypes.FILETIME()
        kernel_time = wintypes.FILETIME()
        user_time = wintypes.FILETIME()
        ok = ctypes.windll.kernel32.GetProcessTimes(
            handle, ctypes.byref(creation), ctypes.byref(exit_time), ctypes.byref(kernel_time), ctypes.byref(user_time)
        )
        if not ok:
            return None
        value = (creation.dwHighDateTime << 32) | creation.dwLowDateTime
        if value == 0:
            return None
        # FILETIME: 100-ns intervals since 1601-01-01. Convert to Unix epoch.
        windows_epoch_offset_seconds = 11644473600
        return value / 10_000_000 - windows_epoch_offset_seconds
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def _creation_time_procfs(pid: int) -> float | None:
    """Linux /proc fallback -- no psutil dependency. Returns None (not an
    error) on any platform/permission mismatch so callers degrade to
    PID-only rather than raising."""
    try:
        with open(f"/proc/{pid}/stat", "r", encoding="utf-8") as handle:
            stat_line = handle.read()
        # comm (field 2) can itself contain spaces/parens, so split on the
        # LAST ')' -- everything after it is fields 3.. in order.
        after_comm = stat_line.rsplit(")", 1)[1].split()
        starttime_ticks = int(after_comm[19])  # field 22 (starttime) == after_comm[22-3]
        with open("/proc/stat", "r", encoding="utf-8") as handle:
            boot_time = None
            for line in handle:
                if line.startswith("btime "):
                    boot_time = int(line.split()[1])
                    break
        if boot_time is None:
            return None
        clock_ticks_per_second = os.sysconf("SC_CLK_TCK")
        return boot_time + starttime_ticks / clock_ticks_per_second
    except (OSError, IndexError, ValueError):
        return None


def creation_time(pid: int) -> float | None:
    """Best-effort process creation time as Unix epoch seconds, or None if
    unavailable on this platform."""
    if sys.platform == "win32":
        return _creation_time_windows(pid)
    if sys.platform.startswith("linux"):
        return _creation_time_procfs(pid)
    return None


def current_identity(pid: int) -> dict[str, Any]:
    """Build the identity record to store in a lock: PID plus creation time
    when available, with an explicit `mode` recording which was used."""
    ct = creation_time(pid)
    if ct is not None:
        return {"pid": pid, "creation_time": ct, "mode": MODE_PID_AND_CREATION_TIME}
    return {"pid": pid, "creation_time": None, "mode": MODE_PID_ONLY}


def is_same_process_alive(identity: dict[str, Any]) -> bool:
    """True iff the process recorded in `identity` (a dict as returned by
    current_identity, or reconstructed from a persisted lock's fields) is
    still running. In pid+creation_time mode this also confirms the live
    process at that PID is the SAME process that acquired the lock -- not a
    different process that reused the PID after the original died."""
    pid = identity.get("pid")
    if pid is None:
        return False
    pid = int(pid)
    if not is_pid_alive(pid):
        return False

    if identity.get("mode") != MODE_PID_AND_CREATION_TIME or identity.get("creation_time") is None:
        return True  # PID-only mode: this is the most this platform can tell us.

    current_ct = creation_time(pid)
    if current_ct is None:
        return True  # lost the ability to verify further; don't regress below PID-only.

    return abs(current_ct - identity["creation_time"]) < _CREATION_TIME_TOLERANCE_SECONDS
