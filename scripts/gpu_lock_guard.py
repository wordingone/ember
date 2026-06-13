"""gpu_lock_guard.py — Windows-side pre-CUDA guard for cross-boundary GPU serialization (#368).

Usage (context manager):
    from gpu_lock_guard import acquire
    with acquire():
        import torch  # CUDA init happens here — safe while lock held

Usage (inline at script top):
    import gpu_lock_guard; gpu_lock_guard.check_or_die()

Lockfile: B:/M/avir/infra/vigil/gpu.lock — shared between Windows-side scripts (this
module, side="windows") and WSL2 train daemon (server.py, side="wsl2").
Fail-closed: if lock state is uncertain, refuses CUDA init.  Fix-forward-on-headroom-
violation ban applies — never bypass.
"""
import contextlib
import json
import os
import subprocess
import sys
import time

LOCK_PATH = os.path.normpath("B:/M/avir/infra/vigil/gpu.lock")


def _is_pid_alive(pid, side):
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
    except json.JSONDecodeError:
        return {}  # corrupt file → treat as held (fail-closed)


def _write_lock(script=None):
    os.makedirs(os.path.dirname(LOCK_PATH), exist_ok=True)
    data = {
        "pid": os.getpid(),
        "side": "windows",
        "script": script or os.path.basename(sys.argv[0]),
        "ts": time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()),
    }
    tmp = LOCK_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp, LOCK_PATH)   # atomic on Windows


def _release_lock():
    try:
        lock = _read_lock()
        if lock and lock.get("pid") == os.getpid() and lock.get("side") == "windows":
            os.remove(LOCK_PATH)
    except Exception:
        pass


def check_or_die(script=None):
    """Acquire GPU lock or exit(1) if held by a live process."""
    lock = _read_lock()
    if lock is not None:
        pid = lock.get("pid")
        side = lock.get("side", "windows")
        if not pid:
            # corrupt/empty lock — fail-closed
            print(
                f"[gpu_lock_guard] HELD (corrupt lock at {LOCK_PATH}) — refusing CUDA init",
                file=sys.stderr,
            )
            sys.exit(1)
        if _is_pid_alive(pid, side):
            print(
                f"[gpu_lock_guard] HELD — {side} PID {pid} "
                f"({lock.get('script', '?')}) acquired at {lock.get('ts', '?')}",
                file=sys.stderr,
            )
            print("[gpu_lock_guard] REFUSED — fix-forward-on-headroom-violation ban applies.",
                  file=sys.stderr)
            sys.exit(1)
        # stale lock (PID dead)
        print(f"[gpu_lock_guard] stale lock (PID {pid} dead) — clearing", file=sys.stderr)
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
