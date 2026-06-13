"""gpu_lock_guard.py — Windows-side pre-CUDA guard for cross-boundary GPU serialization (#368).

Lockfile: B:/M/avir/infra/vigil/gpu.lock — shared between Windows-side scripts (this
module, side="windows") and WSL2 train daemon (server.py, side="wsl2").

Lockfile format (refcounted — daemon may hold while running multiple concurrent jobs):
  {"daemon_pid": int, "side": "wsl2"|"windows", "active_jobs": int,
   "ts_first": "...", "ts_last": "..."}

Fail-closed: held by live process with active_jobs>0 → exit(1).
Corrupt/unreadable lock → exit(1). Fix-forward-on-headroom-violation ban applies.

Usage (context manager):
    from gpu_lock_guard import acquire
    with acquire():
        import torch  # CUDA init here — safe while lock held

Usage (inline at script top):
    import gpu_lock_guard; gpu_lock_guard.check_or_die()
"""
import contextlib
import json
import os
import subprocess
import sys
import time

LOCK_PATH = os.path.normpath("B:/M/avir/infra/vigil/gpu.lock")


def _is_pid_alive(pid, side):
    """Check whether the lock-holder PID is still alive."""
    if side == "windows":
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True, text=True, timeout=5,
            )
            return str(pid) in result.stdout
        except Exception:
            return True   # conservative on error
    elif side == "wsl2":
        try:
            result = subprocess.run(
                ["wsl", "--", "kill", "-0", str(pid)],
                capture_output=True, timeout=5,
            )
            return result.returncode == 0
        except Exception:
            return True   # conservative: WSL2 check failed, assume alive
    return True  # unknown side → conservative


def _read_lock():
    try:
        with open(LOCK_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except (json.JSONDecodeError, OSError):
        return {}  # corrupt/unreadable → fail-closed (treat as held)


def _write_lock(script=None):
    os.makedirs(os.path.dirname(LOCK_PATH), exist_ok=True)
    ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    data = {
        "daemon_pid": os.getpid(),
        "side": "windows",
        "active_jobs": 1,
        "script": script or os.path.basename(sys.argv[0]),
        "ts_first": ts,
        "ts_last": ts,
    }
    tmp = LOCK_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp, LOCK_PATH)  # atomic on Windows


def _release_lock():
    try:
        lock = _read_lock()
        if (lock and lock.get("daemon_pid") == os.getpid()
                and lock.get("side") == "windows"):
            os.remove(LOCK_PATH)
    except Exception:
        pass


def check_or_die(script=None):
    """Acquire GPU lock or exit(1) if held by a live process with active jobs."""
    lock = _read_lock()
    if lock is not None:
        if not lock:
            # corrupt / empty dict — fail-closed
            print(
                f"[gpu_lock_guard] HELD (corrupt lock at {LOCK_PATH}) — refusing CUDA init",
                file=sys.stderr,
            )
            sys.exit(1)

        pid = lock.get("daemon_pid") or lock.get("pid")  # backward-compat with v1 format
        side = lock.get("side", "windows")
        active_jobs = lock.get("active_jobs", 1)

        if pid and _is_pid_alive(pid, side) and active_jobs > 0:
            print(
                f"[gpu_lock_guard] HELD — {side} PID {pid}, active_jobs={active_jobs}, "
                f"ts_last={lock.get('ts_last', '?')}",
                file=sys.stderr,
            )
            print("[gpu_lock_guard] REFUSED — fix-forward-on-headroom-violation ban applies.",
                  file=sys.stderr)
            sys.exit(1)

        # stale lock (holder PID dead or active_jobs=0)
        print(f"[gpu_lock_guard] stale lock (PID {pid} dead or jobs=0) — clearing",
              file=sys.stderr)
        try:
            os.remove(LOCK_PATH)
        except FileNotFoundError:
            pass

    _write_lock(script)


def release():
    """Release the lock if held by this process."""
    _release_lock()


@contextlib.contextmanager
def acquire(script=None):
    """Context manager: acquire lock on enter, release on exit (including exceptions)."""
    check_or_die(script)
    try:
        yield
    finally:
        release()
