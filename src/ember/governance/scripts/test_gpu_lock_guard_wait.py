# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Reds for the fence's bounded wait (lead ruling 82032 E1).

A press that finds an eval-shaped tenant on the fence WAITS with a logged backoff and then proceeds; a wait that never
clears ends in a named refusal; the wait is a covariate the caller can read; two waiters never hold the fence together.
Real files and real child processes; only the clock and the pid probe are injected where time or process state is the input.
"""
import importlib
import json
import os
import subprocess
import sys
import time

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def _fresh_module(monkeypatch, lock_path):
    if lock_path is None:
        monkeypatch.delenv("EMBER_GPU_LOCK_PATH", raising=False)
    else:
        monkeypatch.setenv("EMBER_GPU_LOCK_PATH", str(lock_path))
    monkeypatch.delenv("EMBER_GPU_LOCK_WAIT_SECONDS", raising=False)
    import gpu_lock_guard
    return importlib.reload(gpu_lock_guard)


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []
        self.on_sleep = None

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds
        if self.on_sleep is not None:
            self.on_sleep(len(self.sleeps))


def _held(lock, pid=987654, side="windows", script="eval.py"):
    lock.write_text(json.dumps({"daemon_pid": pid, "side": side, "active_jobs": 1, "script": script,
                                "ts_first": "20261109T040000Z", "ts_last": "20261109T040000Z"}), encoding="utf-8")


def test_live_holder_that_releases_mid_wait_lets_the_press_proceed_with_a_recorded_wait(monkeypatch, tmp_path):
    lock = tmp_path / "gpu.lock"
    guard = _fresh_module(monkeypatch, lock)
    _held(lock)
    monkeypatch.setattr(guard, "_is_pid_alive", lambda pid, side: True)
    clock, events = FakeClock(), []
    clock.on_sleep = lambda n: lock.unlink() if n == 3 else None       # the tenant ends during the third backoff
    with guard.acquire(script="press", sleep=clock.sleep, clock=clock, log=events.append):
        payload = json.loads(lock.read_text(encoding="utf-8"))
        assert payload["daemon_pid"] == os.getpid() and payload["script"] == "press"
    assert not lock.exists()
    assert clock.sleeps == [1, 2, 4]
    waited = guard.last_wait()
    assert (waited["waited_seconds"], waited["attempts"], waited["budget_seconds"]) == (7.0, 3, 3600.0)
    assert waited["holders"] == [{"pid": 987654, "side": "windows", "script": "eval.py", "ts_first": "20261109T040000Z"}]
    assert [e["attempt"] for e in events] == [1, 2, 3] and all(e["event"] == "GPU_FENCE_WAIT" for e in events)


def test_a_wait_that_never_clears_ends_in_a_named_refusal_and_leaves_the_holder_untouched(monkeypatch, tmp_path, capsys):
    lock = tmp_path / "gpu.lock"
    guard = _fresh_module(monkeypatch, lock)
    _held(lock)
    original = lock.read_bytes()
    monkeypatch.setattr(guard, "_is_pid_alive", lambda pid, side: True)
    clock = FakeClock()
    with pytest.raises(SystemExit) as exc:
        with guard.acquire(wait_seconds=10, sleep=clock.sleep, clock=clock, log=lambda event: None):
            pytest.fail("the fence was taken from a live holder")
    assert exc.value.code == 1
    assert clock.sleeps == [1, 2, 4, 3]                 # capped to the budget, never past it
    err = capsys.readouterr().err
    assert "HELD" in err and "REFUSED" in err and "Waited 10s of 10s" in err
    assert lock.read_bytes() == original
    assert guard.last_wait() is None


def test_zero_budget_is_the_immediate_refusal(monkeypatch, tmp_path):
    lock = tmp_path / "gpu.lock"
    guard = _fresh_module(monkeypatch, lock)
    _held(lock)
    monkeypatch.setattr(guard, "_is_pid_alive", lambda pid, side: True)
    clock = FakeClock()
    with pytest.raises(SystemExit):
        with guard.acquire(wait_seconds=0, sleep=clock.sleep, clock=clock):
            pass
    assert clock.sleeps == []


def test_env_budget_is_read_and_a_malformed_one_refuses(monkeypatch, tmp_path, capsys):
    lock = tmp_path / "gpu.lock"
    guard = _fresh_module(monkeypatch, lock)
    _held(lock)
    monkeypatch.setattr(guard, "_is_pid_alive", lambda pid, side: True)
    monkeypatch.setenv("EMBER_GPU_LOCK_WAIT_SECONDS", "0")
    clock = FakeClock()
    with pytest.raises(SystemExit):
        with guard.acquire(sleep=clock.sleep, clock=clock):
            pass
    assert clock.sleeps == []
    for bad in ("abc", "-1", "nan", "inf"):
        monkeypatch.setenv("EMBER_GPU_LOCK_WAIT_SECONDS", bad)
        with pytest.raises(SystemExit):
            with guard.acquire(sleep=clock.sleep, clock=clock):
                pass
        assert "must be a finite number of seconds" in capsys.readouterr().err


def test_a_corrupt_lock_is_refused_after_the_short_budget_and_never_overwritten(monkeypatch, tmp_path):
    lock = tmp_path / "gpu.lock"
    guard = _fresh_module(monkeypatch, lock)
    lock.write_text("{not json", encoding="utf-8")
    clock = FakeClock()
    with pytest.raises(SystemExit):
        with guard.acquire(sleep=clock.sleep, clock=clock, log=lambda event: None):
            pass
    assert sum(clock.sleeps) == guard.CORRUPT_WAIT_SECONDS
    assert lock.read_text(encoding="utf-8") == "{not json"


def test_a_dead_holder_is_cleared_without_waiting(monkeypatch, tmp_path):
    lock = tmp_path / "gpu.lock"
    guard = _fresh_module(monkeypatch, lock)
    _held(lock)
    monkeypatch.setattr(guard, "_is_pid_alive", lambda pid, side: False)
    clock = FakeClock()
    with guard.acquire(sleep=clock.sleep, clock=clock):
        assert json.loads(lock.read_text(encoding="utf-8"))["daemon_pid"] == os.getpid()
    assert clock.sleeps == [] and guard.last_wait()["attempts"] == 0


def test_the_default_and_log_line_shape(monkeypatch, tmp_path, capsys):
    lock = tmp_path / "gpu.lock"
    guard = _fresh_module(monkeypatch, lock)
    _held(lock)
    monkeypatch.setattr(guard, "_is_pid_alive", lambda pid, side: True)
    clock = FakeClock()
    clock.on_sleep = lambda n: lock.unlink()
    with guard.acquire(sleep=clock.sleep, clock=clock):
        pass
    line = json.loads(capsys.readouterr().err.strip().splitlines()[-1])
    assert line["event"] == "GPU_FENCE_WAIT" and line["budget_seconds"] == guard.DEFAULT_WAIT_SECONDS == 3600.0
    assert line["holders"][0]["pid"] == 987654


def test_holder_pid_reports_only_a_live_windows_holder(monkeypatch, tmp_path):
    lock = tmp_path / "gpu.lock"
    guard = _fresh_module(monkeypatch, lock)
    assert guard.holder_pid() is None
    _held(lock)
    monkeypatch.setattr(guard, "_is_pid_alive", lambda pid, side: True)
    assert guard.holder_pid() == 987654
    monkeypatch.setattr(guard, "_is_pid_alive", lambda pid, side: False)
    assert guard.holder_pid() is None
    monkeypatch.setattr(guard, "_is_pid_alive", lambda pid, side: True)
    _held(lock, side="wsl2")
    assert guard.holder_pid() is None                      # a WSL2 pid is not a Windows process row
    lock.write_text("{not json", encoding="utf-8")
    assert guard.holder_pid() is None
    monkeypatch.setattr(guard, "LOCK_PATH", "")
    assert guard.holder_pid() is None


def test_a_fresh_mutex_blocks_and_a_stale_one_is_cleared(monkeypatch, tmp_path):
    lock = tmp_path / "gpu.lock"
    guard = _fresh_module(monkeypatch, lock)
    mutex = tmp_path / "gpu.lock.mutex"
    mutex.write_text("1", encoding="ascii")
    monkeypatch.setattr(guard, "MUTEX_WAIT_SECONDS", 0.2)
    with pytest.raises(SystemExit):
        guard.check_or_die(script="blocked")
    assert not lock.exists()
    old = time.time() - guard.MUTEX_STALE_SECONDS - 5
    os.utime(mutex, (old, old))
    guard.check_or_die(script="cleared")
    assert lock.exists() and not mutex.exists()
    guard.release()


WORKER = r"""
import os, sys, time, json
sys.path.insert(0, sys.argv[1])
import gpu_lock_guard as g
log, hold = sys.argv[2], float(sys.argv[3])
with g.acquire(script='worker', wait_seconds=120):
    with open(log, 'a', encoding='utf-8') as f:
        f.write(json.dumps(['in', os.getpid(), time.time()]) + '\n')
    time.sleep(hold)
    with open(log, 'a', encoding='utf-8') as f:
        f.write(json.dumps(['out', os.getpid(), time.time()]) + '\n')
w = g.last_wait()
with open(log, 'a', encoding='utf-8') as f:
    f.write(json.dumps(['wait', os.getpid(), w['waited_seconds'], w['attempts']]) + '\n')
"""


def test_churn_real_processes_take_the_fence_one_at_a_time_and_the_later_ones_wait(tmp_path):
    lock, log, worker = tmp_path / "gpu.lock", tmp_path / "events.jsonl", tmp_path / "worker.py"
    worker.write_text(WORKER, encoding="utf-8")
    env = dict(os.environ, EMBER_GPU_LOCK_PATH=str(lock))
    env.pop("EMBER_GPU_LOCK_WAIT_SECONDS", None)
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    children = [subprocess.Popen([sys.executable, "-B", str(worker), HERE, str(log), "1.5"], env=env,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, creationflags=flags)
                for _ in range(3)]
    errors = [child.communicate(timeout=120)[1].decode("utf-8", "replace") for child in children]
    assert [child.returncode for child in children] == [0, 0, 0], errors
    rows = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    spans = {}
    for row in rows:
        if row[0] in ("in", "out"):
            spans.setdefault(row[1], {})[row[0]] = row[2]
    ordered = sorted(spans.values(), key=lambda span: span["in"])
    assert len(ordered) == 3
    for earlier, later in zip(ordered, ordered[1:]):
        assert earlier["out"] <= later["in"], "two processes held the fence together"
    waits = sorted(row[2] for row in rows if row[0] == "wait")
    assert waits[0] < 1.0 and waits[-1] >= 1.5               # the first walked in; the last queued behind the others
    assert not lock.exists() and not (tmp_path / "gpu.lock.mutex").exists()
    assert any("GPU_FENCE_WAIT" in text for text in errors)
