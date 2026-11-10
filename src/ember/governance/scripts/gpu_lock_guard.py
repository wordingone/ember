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

Fail-closed: held by live process with active_jobs>0 → exit(1) once the wait budget is spent.
Corrupt/unreadable lock → exit(1) after a short budget. Fix-forward-on-headroom-violation ban applies.

Waiting (lead ruling 82032 E1): a live holder is a queue, not a refusal. acquire() waits with a bounded, logged
backoff (EMBER_GPU_LOCK_WAIT_SECONDS, default 3600 s; 0 = refuse at once) and then proceeds; the wait is a covariate,
available from last_wait() for the caller's receipt. check_or_die() keeps the immediate refusal. The check/clear/write
step is serialized by an O_EXCL mutex file beside the lock, so two waiters can never both take a freed fence.

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
WAIT_ENV = "EMBER_GPU_LOCK_WAIT_SECONDS"
DEFAULT_WAIT_SECONDS = 3600.0
CORRUPT_WAIT_SECONDS = 30.0     # an unreadable lock is usually a replace in flight; a lasting one is a refusal
BACKOFF_SECONDS = (1, 2, 4, 8, 16, 30)
MUTEX_STALE_SECONDS = 30.0      # the mutex guards milliseconds of work; an older file is a dead owner's
MUTEX_WAIT_SECONDS = 10.0


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
            f"[gpu_lock_guard] REFUSED - {LOCK_PATH_ENV} is unset, so CUDA access "
            "cannot be serialized against the WSL2 train daemon",
            file=sys.stderr,
        )
        sys.exit(1)
    return LOCK_PATH


def _hidden_process_kwargs():
    flags = {'shell': False}
    if os.name == 'nt':
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = subprocess.SW_HIDE
        flags.update(creationflags=subprocess.CREATE_NO_WINDOW, startupinfo=startup)
    return flags


def _is_pid_alive(pid, side):
    """Check whether the lock-holder PID is still alive."""
    if side == "windows":
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True, text=True, timeout=5,
                **_hidden_process_kwargs(),
            )
            if result.returncode != 0 or not result.stdout.strip():
                return True  # an unavailable process query does not prove the holder exited
            return str(pid) in result.stdout
        except Exception:
            return True   # conservative on error
    elif side == "wsl2":
        try:
            result = subprocess.run(
                ["wsl", "--", "kill", "-0", str(pid)],
                capture_output=True, timeout=5,
                **_hidden_process_kwargs(),
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


_LAST_WAIT = None


def _wait_budget(wait_seconds):
    """Seconds a caller may wait for a live holder: the argument, else EMBER_GPU_LOCK_WAIT_SECONDS, else the default.
    A malformed or negative value refuses (a typo must never become an unbounded or silent immediate path)."""
    if wait_seconds is None:
        raw = os.environ.get(WAIT_ENV, "").strip()
        if not raw:
            return DEFAULT_WAIT_SECONDS
        wait_seconds = raw
    try:
        value = float(wait_seconds)
    except (TypeError, ValueError):
        value = -1.0
    if not (value >= 0.0) or value == float("inf"):
        print(f"[gpu_lock_guard] REFUSED - {WAIT_ENV} must be a finite number of seconds >= 0, got {wait_seconds!r}",
              file=sys.stderr)
        sys.exit(1)
    return value


@contextlib.contextmanager
def _mutex(path):
    """Serialize the read-decide-write step across processes on this side of the boundary.

    An O_EXCL file beside the lock, never held across a sleep. A file older than MUTEX_STALE_SECONDS belongs to a dead
    owner and is removed; two processes racing to remove the same stale file is a window of microseconds once per crash."""
    mutex_path = path + ".mutex"
    parent = os.path.dirname(mutex_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    deadline = time.monotonic() + MUTEX_WAIT_SECONDS
    while True:
        try:
            fd = os.open(mutex_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except (FileExistsError, PermissionError):
            try:
                age = time.time() - os.path.getmtime(mutex_path)
            except OSError:
                continue            # it vanished between the open and the stat: retry at once
            if age > MUTEX_STALE_SECONDS:
                try:
                    os.remove(mutex_path)
                except OSError:
                    pass
                continue
            if time.monotonic() >= deadline:
                print(f"[gpu_lock_guard] REFUSED - could not take {mutex_path} within {MUTEX_WAIT_SECONDS:.0f}s",
                      file=sys.stderr)
                sys.exit(1)
            time.sleep(0.05)
            continue
        break
    try:
        os.write(fd, str(os.getpid()).encode("ascii"))
        os.close(fd)
        yield
    finally:
        try:
            os.remove(mutex_path)
        except OSError:
            pass


def _try_take(script):
    """One acquisition attempt under the mutex. Returns ('acquired', None), ('held', lock) or ('corrupt', None)."""
    path = _require_lock_path()
    with _mutex(path):
        lock = _read_lock()
        if lock is not None:
            if not lock:
                return "corrupt", None
            pid = lock.get("daemon_pid") or lock.get("pid")  # backward-compat with v1 format
            side = lock.get("side", "windows")
            active_jobs = lock.get("active_jobs", 1)
            if pid and _is_pid_alive(pid, side) and active_jobs > 0:
                return "held", lock
            # stale lock (holder PID dead or active_jobs=0)
            print(f"[gpu_lock_guard] stale lock (PID {pid} dead or jobs=0) - clearing", file=sys.stderr)
            try:
                os.remove(path)
            except FileNotFoundError:
                pass
        _write_lock(script)
        return "acquired", None


def _log_wait(event):
    print(json.dumps(event, sort_keys=True), file=sys.stderr, flush=True)


def _acquire(script, wait_seconds, sleep, clock, log):
    global _LAST_WAIT
    path = _require_lock_path()
    budget = _wait_budget(wait_seconds)
    started = clock()
    attempts, holders = 0, []
    while True:
        state, lock = _try_take(script)
        if state == "acquired":
            break
        waited = clock() - started
        limit = min(budget, CORRUPT_WAIT_SECONDS) if state == "corrupt" else budget
        if state == "held":
            holder = {"pid": lock.get("daemon_pid") or lock.get("pid"), "side": lock.get("side", "windows"),
                      "script": lock.get("script"), "ts_first": lock.get("ts_first")}
            if holder not in holders:
                holders.append(holder)
        if waited >= limit:
            if state == "corrupt":
                print(f"[gpu_lock_guard] HELD (corrupt lock at {path}) - refusing CUDA init", file=sys.stderr)
            else:
                print(f"[gpu_lock_guard] HELD - {lock.get('side', 'windows')} PID {lock.get('daemon_pid') or lock.get('pid')}, "
                      f"active_jobs={lock.get('active_jobs', 1)}, ts_last={lock.get('ts_last', '?')}", file=sys.stderr)
                print("[gpu_lock_guard] REFUSED - fix-forward-on-headroom-violation ban applies."
                      + (f" Waited {waited:.0f}s of {budget:.0f}s." if budget > 0 else ""), file=sys.stderr)
            sys.exit(1)
        attempts += 1
        delay = min(BACKOFF_SECONDS[min(attempts - 1, len(BACKOFF_SECONDS) - 1)], limit - waited)
        log({"event": "GPU_FENCE_WAIT", "attempt": attempts, "state": state, "waited_seconds": round(waited, 3),
             "next_sleep_seconds": delay, "budget_seconds": budget, "holders": holders})
        sleep(delay)
    _LAST_WAIT = {"waited_seconds": round(clock() - started, 3), "attempts": attempts, "budget_seconds": budget,
                  "holders": holders, "acquired_utc": time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())}


def check_or_die(script=None):
    """Acquire GPU lock or exit(1) at once if held by a live process with active jobs (no waiting)."""
    _acquire(script, 0.0, time.sleep, time.monotonic, _log_wait)


def last_wait():
    """The wait of this process's latest successful acquisition (waited_seconds, attempts, budget_seconds, holders), else None.
    Callers record it in their receipt: queueing behind another tenant is a covariate of the run, never hidden."""
    return dict(_LAST_WAIT) if _LAST_WAIT else None


def holder_pid():
    """The live Windows-side pid holding the fence right now, else None. Read-only: lets a pre-fence census exempt the tenant
    the caller is about to wait for (the census inside the fence stays the harm check)."""
    if not LOCK_PATH:
        return None
    lock = _read_lock()
    if not lock:
        return None
    pid = lock.get("daemon_pid") or lock.get("pid")
    if (pid and lock.get("side", "windows") == "windows" and lock.get("active_jobs", 1) > 0
            and _is_pid_alive(pid, "windows")):
        return int(pid)
    return None


def release():
    """Release the lock if held by this process."""
    _release_lock()


@contextlib.contextmanager
def acquire(script=None, wait_seconds=None, sleep=time.sleep, clock=time.monotonic, log=_log_wait):
    """Context manager: wait (bounded, logged backoff) for the fence, hold it for the body, release on exit (including exceptions)."""
    _acquire(script, wait_seconds, sleep, clock, log)
    try:
        yield
    finally:
        release()
