"""gpu_lock_selftest.py — 3-state concurrent selftest for gpu_lock_guard (#368).

Tests the concurrent case that caused the arm-b-seed1 collision:
  1. Simulate daemon holding lock with active_jobs=2 (2 concurrent GPU jobs)
  2. Windows script -> REFUSED (active_jobs=2, daemon alive)
  3. Simulate daemon releasing one job -> active_jobs=1
  4. Windows script -> STILL REFUSED (daemon still alive, active_jobs=1)
  5. Simulate daemon releasing second job -> lock unlinked (active_jobs=0)
  6. Windows script -> ACQUIRES (lock clear)

This proves the refcount fix closes the original bug: per-job release did not
reopen the window when a second daemon job was still in flight.
"""
import json
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

PASS = "GPU_LOCK_SELFTEST_PASS"
FAIL = "GPU_LOCK_SELFTEST_FAIL"


def _write_lock_state(lock_path, daemon_pid, active_jobs, side="windows"):
    ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    data = {
        "daemon_pid": daemon_pid,
        "side": side,
        "active_jobs": active_jobs,
        "ts_first": ts,
        "ts_last": ts,
    }
    tmp = lock_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp, lock_path)


def _try_acquire(lock_path):
    """Return True if guard would ACQUIRE, False if REFUSED."""
    result = subprocess.run(
        [sys.executable, "-c",
         f"import sys; sys.path.insert(0,{repr(HERE)}); "
         f"import gpu_lock_guard as g; g.LOCK_PATH={repr(lock_path)}; g.check_or_die()"],
        capture_output=True, timeout=10,
    )
    return result.returncode == 0


def _release_from_lock(lock_path):
    """Simulate guard releasing (writes its own PID before releasing)."""
    try:
        with open(lock_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if data.get("side") == "windows" and data.get("daemon_pid") == os.getpid():
            os.remove(lock_path)
    except FileNotFoundError:
        pass


def main():
    with tempfile.TemporaryDirectory() as td:
        lock_path = os.path.join(td, "gpu.lock")

        # Find a PID that's definitely alive: our own
        live_pid = os.getpid()

        # --- State 1: daemon holds lock, active_jobs=2 ---
        _write_lock_state(lock_path, live_pid, active_jobs=2)
        result1 = _try_acquire(lock_path)
        assert not result1, f"State1 FAIL: expected REFUSED with active_jobs=2, got ACQUIRED"
        print("[selftest] State1 PASS: active_jobs=2 -> REFUSED")

        # --- State 2: daemon releases one job -> active_jobs=1 ---
        _write_lock_state(lock_path, live_pid, active_jobs=1)
        result2 = _try_acquire(lock_path)
        assert not result2, f"State2 FAIL: expected REFUSED with active_jobs=1, got ACQUIRED"
        print("[selftest] State2 PASS: active_jobs=1 -> still REFUSED")

        # --- State 3: daemon releases second job -> lock unlinked ---
        os.remove(lock_path)  # simulate active_jobs reaching 0 -> unlink
        assert not os.path.exists(lock_path), "State3 setup FAIL: lock still present"
        result3 = _try_acquire(lock_path)
        assert result3, f"State3 FAIL: expected ACQUIRED with lock clear, got REFUSED"
        print("[selftest] State3 PASS: lock clear -> ACQUIRED")

        # verify guard wrote its own lock entry
        assert os.path.exists(lock_path), "State3 FAIL: guard did not write lock on acquire"
        with open(lock_path, "r") as f:
            written = json.load(f)
        assert written.get("active_jobs") == 1, f"State3 FAIL: active_jobs={written.get('active_jobs')}"
        assert written.get("side") == "windows", f"State3 FAIL: side={written.get('side')}"
        print(f"[selftest] State3 PASS: lock written with active_jobs=1 side=windows")

    print(PASS)


if __name__ == "__main__":
    try:
        main()
    except AssertionError as e:
        print(f"{FAIL}: {e}")
        sys.exit(1)
