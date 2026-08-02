#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""native_crash_guard.py -- EMBER-01 C0 NATIVE_CRASH supervised-dispatch guard.

Cures the NATIVE_CRASH row in manifests/ember-01-custody/c0-failure-class-ledger.json
(conjunct-3, PR #1017, increment 2): "an unrecoverable native process death mid-run
invalidates the run and, without a crash-survival guard, silently loses training state."

Design: a supervised-dispatch wrapper. The risky work runs as a CHILD process; the
parent inspects the child's exit code for a native-layer crash signature (segfault/
abort/access-violation/illegal-instruction -- the process died from the OS tearing it
down, not from the program's own error handling) and, on a detected crash, writes a
fail-closed receipt (class, returncode, cmd, ts, crash_signature) to disk BEFORE any
caller can make a relaunch decision. A caller that relaunches without first checking
run_supervised()'s result is bypassing the guard, not using it correctly -- but the
guard itself never silently skips the receipt write on a detected crash.

Cross-platform exit-code representation (grounded empirically, not guessed):
  - POSIX: a child killed by a signal reports subprocess.returncode as NEGATIVE,
    == -signal_number (e.g. SIGSEGV=11 -> returncode -11). This is the actual
    Python/POSIX convention (Popen.returncode docs).
  - Windows: process exit codes are an unsigned 32-bit DWORD; subprocess.run reports
    the raw value as a non-negative Python int (verified: a child that calls
    ExitProcess(0xC0000005) reports returncode 3221225477 == 0xC0000005, not a
    negative POSIX-style code -- Windows subprocess does NOT do POSIX -signum
    conversion). Windows STATUS_* fault codes (access violation, stack overflow,
    illegal instruction, etc.) share the top-two-bits-set NTSTATUS severity=Error
    pattern (mask 0xC0000000) -- this is the SAME discriminator .NET's native crash
    handling and most Windows crash-triage tooling use, and is what classify_exit()
    checks rather than an incomplete enumerated list (an unnamed STATUS_* fault code
    still classifies as a crash; only the human-readable label falls back to
    "UNNAMED_NTSTATUS_0x...").
"""

from __future__ import annotations

import ctypes
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

WINDOWS_CRASH_MASK = 0xC0000000  # NTSTATUS severity bits: top two bits == 11 -> STATUS_SEVERITY_ERROR

# Standard glibc/Linux POSIX signal numbering (fixed table, NOT the host interpreter's
# live `signal` module). This matters: the live `signal.Signals` enum reflects the
# HOST platform's own numbering, which differs between OSes -- e.g. SIGABRT is signal
# 6 on Linux but 22 in the Windows CRT. classify_exit's platform= parameter selects a
# LOGICAL interpretation (POSIX-signal vs Windows-NTSTATUS), independent of whatever
# OS this guard module happens to be running on; a Windows dev box must classify a
# platform="linux" returncode using Linux's signal numbering, not Windows's, and vice
# versa. Names are receipt-labeling only -- an unrecognized number still classifies
# via the negative-returncode check below, labeled SIGnn.
POSIX_SIGNAL_NAMES = {
    1: "SIGHUP", 2: "SIGINT", 3: "SIGQUIT", 4: "SIGILL", 5: "SIGTRAP",
    6: "SIGABRT", 7: "SIGBUS", 8: "SIGFPE", 9: "SIGKILL", 10: "SIGUSR1",
    11: "SIGSEGV", 12: "SIGUSR2", 13: "SIGPIPE", 14: "SIGALRM", 15: "SIGTERM",
    16: "SIGSTKFLT", 17: "SIGCHLD", 18: "SIGCONT", 19: "SIGSTOP", 20: "SIGTSTP",
    21: "SIGTTIN", 22: "SIGTTOU", 23: "SIGURG", 24: "SIGXCPU", 25: "SIGXFSZ",
    26: "SIGVTALRM", 27: "SIGPROF", 28: "SIGWINCH", 29: "SIGIO", 30: "SIGPWR",
    31: "SIGSYS",
}

# Named NTSTATUS crash codes (richer receipt labeling only -- the mask check above is
# fail-closed and does NOT require a code to be named here; an unnamed fault-severity
# code still classifies as a crash, labeled UNNAMED_NTSTATUS_0x...).
KNOWN_WINDOWS_CRASH_CODES = {
    0xC0000005: "STATUS_ACCESS_VIOLATION",
    0xC0000409: "STATUS_STACK_BUFFER_OVERRUN",
    0xC000001D: "STATUS_ILLEGAL_INSTRUCTION",
    0xC0000094: "STATUS_INTEGER_DIVIDE_BY_ZERO",
    0xC00000FD: "STATUS_STACK_OVERFLOW",
}

REQUIRED_RECEIPT_FIELDS = {"ticket", "ts", "class", "cmd", "returncode", "crash_signature"}


def _utc_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def classify_exit(returncode: int, *, platform: str = sys.platform) -> Optional[dict]:
    """Pure logic, no I/O. Returns {"crash_signature": str, "detail": str} when
    returncode is a native-layer crash signature; None when the exit is CLEAN (0) or
    an ORDINARY application error exit (any other nonzero code that is not a
    recognized crash signature) -- not every nonzero exit is this class; a script's
    own sys.exit(1) on a handled error must NOT be misclassified as a native crash.

    platform is injectable so both branches are testable regardless of host OS
    (defaults to the real sys.platform of the caller)."""
    if not isinstance(returncode, int) or isinstance(returncode, bool):
        raise TypeError(f"classify_exit: returncode must be an int, got {returncode!r}")

    if platform == "win32":
        code = returncode & 0xFFFFFFFF  # normalize to the unsigned 32-bit DWORD Windows reports
        if code & WINDOWS_CRASH_MASK == WINDOWS_CRASH_MASK:
            name = KNOWN_WINDOWS_CRASH_CODES.get(code, f"UNNAMED_NTSTATUS_0x{code:08X}")
            return {
                "crash_signature": name,
                "detail": f"exit code 0x{code:08X} (NTSTATUS fault severity, mask 0x{WINDOWS_CRASH_MASK:08X})",
            }
        return None

    # POSIX: killed-by-signal is reported as returncode == -signal_number.
    if returncode < 0:
        signum = -returncode
        name = POSIX_SIGNAL_NAMES.get(signum, f"SIG{signum}")
        return {"crash_signature": name, "detail": f"terminated by signal {signum} ({name})"}
    return None


def run_supervised(
    cmd: list[str],
    *,
    receipt_dir,
    cwd: Optional[str] = None,
    env: Optional[dict] = None,
    timeout: Optional[float] = None,
    extra_receipt_fields: Optional[dict] = None,
) -> dict:
    """Run cmd as a supervised child. On a detected native-layer crash (per
    classify_exit), writes a fail-closed crash receipt to receipt_dir BEFORE
    returning -- the receipt exists on disk by the time this function returns, so a
    caller can never make a relaunch decision before the crash is recorded.

    A clean exit (returncode 0) or an ordinary nonzero application exit writes NO
    receipt (crashed=False) -- this guard is specifically the NATIVE_CRASH class,
    not a catch-all for every failing command.

    Returns {"crashed": bool, "returncode": int, "receipt_path": str | None,
    "crash_signature": str | None}."""
    proc = subprocess.run(
        cmd, cwd=cwd, env=env, timeout=timeout, capture_output=True, text=True
    )
    classification = classify_exit(proc.returncode)
    if classification is None:
        return {
            "crashed": False,
            "returncode": proc.returncode,
            "receipt_path": None,
            "crash_signature": None,
        }

    receipt = {
        "ticket": "NATIVE-CRASH-GUARD",
        "ts": _utc_ts(),
        "class": "NATIVE_CRASH",
        "cmd": list(cmd),
        "returncode": proc.returncode,
        "crash_signature": classification["crash_signature"],
        "detail": classification["detail"],
        "cwd": str(cwd) if cwd else None,
    }
    if extra_receipt_fields:
        receipt.update(extra_receipt_fields)

    receipt_dir = Path(receipt_dir)
    receipt_dir.mkdir(parents=True, exist_ok=True)
    path = receipt_dir / f"native-crash-{receipt['ts']}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(receipt, f, indent=2)

    # Checked write -- reload and confirm the schema before returning; an emitted
    # receipt missing a required field is never silently trusted.
    reloaded = json.loads(path.read_text(encoding="utf-8"))
    missing = REQUIRED_RECEIPT_FIELDS - reloaded.keys()
    if missing:
        raise RuntimeError(
            f"run_supervised: EMITTED CRASH RECEIPT MISSING FIELDS {sorted(missing)} "
            f"at {path} -- write is void, this must never be silently accepted"
        )

    return {
        "crashed": True,
        "returncode": proc.returncode,
        "receipt_path": str(path),
        "crash_signature": classification["crash_signature"],
    }


# ---- fixture helpers for genuinely crashing a child process (used by the test suite;
# not part of the guard's own load-bearing logic) --------------------------------------

def _posix_self_signal_child_code(signum: int = 11) -> str:
    """Python source for a child that delivers a REAL signal to itself (default
    SIGSEGV=11) -- a genuine process death, not a fabricated exit code."""
    return f"import os, signal; os.kill(os.getpid(), {signum})"


def _windows_exit_process_child_code(code: int = 0xC0000005) -> str:
    """Python source for a child that calls the real Win32 ExitProcess with an exact
    NTSTATUS-style code -- verified empirically to report back through
    subprocess.run as that exact unsigned DWORD (os._exit() cannot be used here: it
    takes a C int and overflows on values >= 2**31)."""
    return f"import ctypes; ctypes.windll.kernel32.ExitProcess({code})"


def spawn_and_supervise_real_crash(receipt_dir, *, code: Optional[int] = None) -> dict:
    """Spawns a REAL crashing child (platform-appropriate) through run_supervised()
    and returns its result. code: POSIX signal number (default SIGSEGV=11) or
    Windows NTSTATUS code (default 0xC0000005). This is the genuine end-to-end path
    the test suite's non-mocked crash test exercises."""
    if sys.platform == "win32":
        src = _windows_exit_process_child_code(code if code is not None else 0xC0000005)
    else:
        src = _posix_self_signal_child_code(code if code is not None else 11)
    return run_supervised([sys.executable, "-c", src], receipt_dir=receipt_dir)
