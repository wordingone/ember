# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""gpu_lock_guard.py — Windows-side pre-CUDA guard for cross-boundary GPU serialization (#368).

Lockfile: set EMBER_GPU_LOCK_PATH to the shared lock file — shared between
Windows-side scripts (this module, side="windows") and the WSL2 train daemon
(server.py, side="wsl2"). Both sides must resolve to the SAME file; because
Windows and WSL2 address it by different strings (drive letter vs /mnt mount),
the path cannot be a committed constant and each side exports its own view.

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

LOCK_PATH_ENV = "EMBER_GPU_LOCK_PATH"


def _configured_lock_path():
    raw = os.environ.get(LOCK_PATH_ENV, "").strip()
    return os.path.normpath(raw) if raw else ""


# Empty when unconfigured; every caller fails closed rather than guessing a
# path, because a wrong guess would give each side of the boundary a different
# lock file and silently defeat the serialization this module exists for.
# Rebindable at module level on purpose -- gpu_lock_selftest.py injects a
# temp path by assigning gpu_lock_guard.LOCK_PATH.
LOCK_PATH = _configured_lock_path()


def _require_lock_path():
    """Return the configured lock path, or refuse. Reads the module global so a
    caller that rebinds gpu_lock_guard.LOCK_PATH still wins."""
    if not LOCK_PATH:
        print(
            f"[gpu_lock_guard] REFUSED — {LOCK_PATH_ENV} is unset, so CUDA access "
            "cannot be serialized against the WSL2 train daemon",
            file=sys.stderr,
        )
        sys.exit(1)
    return LOCK_PATH


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
    path = _require_lock_path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except (json.JSONDecodeError, OSError):
        return {}  # corrupt/unreadable → fail-closed (treat as held)


def _write_lock(script=None):
    path = _require_lock_path()
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    data = {
        "daemon_pid": os.getpid(),
        "side": "windows",
        "active_jobs": 1,
        "script": script or os.path.basename(sys.argv[0]),
        "ts_first": ts,
        "ts_last": ts,
    }
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp, path)  # atomic on Windows


def _release_lock():
    # Releasing an unconfigured lock is a no-op, not a refusal: there is
    # nothing held, and exiting here would turn cleanup into a hard failure.
    if not LOCK_PATH:
        return
    try:
        lock = _read_lock()
        if (lock and lock.get("daemon_pid") == os.getpid()
                and lock.get("side") == "windows"):
            os.remove(LOCK_PATH)
    except Exception:
        pass


def check_or_die(script=None):
    """Acquire GPU lock or exit(1) if held by a live process with active jobs."""
    path = _require_lock_path()
    lock = _read_lock()
    if lock is not None:
        if not lock:
            # corrupt / empty dict — fail-closed
            print(
                f"[gpu_lock_guard] HELD (corrupt lock at {path}) — refusing CUDA init",
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
            os.remove(path)
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
