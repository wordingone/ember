# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Bounded wait on the repo-wide lifecycle lock.

The pre-push and pre-commit hooks run the lifecycle audit under one repo-wide lock, so a
fail-fast acquire turned every concurrent push or worktree op from another seat into a
LIFECYCLE_LOCKED refusal. These tests drive RepositoryLock directly (through the class,
never the CLI, so the tool's own self-integrity refusal is not in play) against a lock
held by a SEPARATE PROCESS -- in-process re-locking would not exercise the cross-process
byte lock at all.
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest


REPO_ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / "pyproject.toml").is_file())
SCRIPT = REPO_ROOT / "src" / "ember" / "governance" / "scripts" / "worktree_lifecycle.py"

HOLDER_SOURCE = """
import importlib.util, sys, time
from pathlib import Path
script, lock_path, marker, hold = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3]), float(sys.argv[4])
spec = importlib.util.spec_from_file_location("lifecycle_lock_holder", script)
module = importlib.util.module_from_spec(spec)
sys.modules["lifecycle_lock_holder"] = module
spec.loader.exec_module(module)
with module.RepositoryLock(lock_path, wait_seconds=0, backoff_seconds=0):
    marker.write_text("held", encoding="utf-8")
    time.sleep(hold)
"""


def load_module():
    name = "worktree_lifecycle_lock_under_test"
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # Registered BEFORE exec: @dataclass resolves annotations through sys.modules.
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def start_holder(tmp_path: Path, lock_path: Path, hold_seconds: float) -> subprocess.Popen[bytes]:
    """Start a process that holds the lock for hold_seconds; return once it HOLDS it."""
    helper = tmp_path / "hold_lock.py"
    helper.write_text(HOLDER_SOURCE, encoding="utf-8")
    marker = tmp_path / "held.marker"
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    proc = subprocess.Popen(
        [sys.executable, str(helper), str(SCRIPT), str(lock_path), str(marker), str(hold_seconds)],
        env=env,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    deadline = time.monotonic() + 30
    while not marker.exists():
        if proc.poll() is not None:
            raise AssertionError(f"holder exited early with {proc.returncode}")
        if time.monotonic() > deadline:
            proc.kill()
            raise AssertionError("holder never acquired the lock")
        time.sleep(0.05)
    return proc


def test_waits_for_a_second_process_then_acquires(tmp_path: Path) -> None:
    module = load_module()
    lock_path = tmp_path / "ember-worktree-lifecycle.lock"
    holder = start_holder(tmp_path, lock_path, hold_seconds=5)
    lines: list[str] = []
    try:
        started = time.monotonic()
        with module.RepositoryLock(
            lock_path, wait_seconds=30, backoff_seconds=0.2, notify=lines.append
        ) as lock:
            waited = time.monotonic() - started
            # Our own record replaced the holder's on acquire.
            assert f"pid={os.getpid()} " in lock.holder()
        assert holder.wait(timeout=30) == 0
    finally:
        if holder.poll() is None:
            holder.kill()
    assert 2.0 <= waited <= 25.0, waited
    # Exactly ONE line, naming the other process as the holder.
    assert len(lines) == 1
    assert lines[0].startswith(f"waiting for lifecycle lock held by pid={holder.pid} acquired=")
    # Released cleanly: byte 0 still the lock byte, holder record truncated away.
    assert lock_path.read_bytes() == b"0"


def test_timeout_raises_locked_with_the_recorded_holder(tmp_path: Path) -> None:
    module = load_module()
    lock_path = tmp_path / "ember-worktree-lifecycle.lock"
    holder = start_holder(tmp_path, lock_path, hold_seconds=6)
    lines: list[str] = []
    try:
        started = time.monotonic()
        with pytest.raises(module.LifecycleError) as caught:
            with module.RepositoryLock(
                lock_path, wait_seconds=1, backoff_seconds=0.2, notify=lines.append
            ):
                raise AssertionError("acquired a lock another process holds")  # fail-closed
        elapsed = time.monotonic() - started
    finally:
        holder.wait(timeout=30)
    assert caught.value.code == "LIFECYCLE_LOCKED"
    assert f"held by pid={holder.pid} acquired=" in str(caught.value)
    assert "after waiting 1s" in str(caught.value)
    assert 0.9 <= elapsed <= 5.0, elapsed
    assert len(lines) == 1
    assert lines[0].startswith(f"waiting for lifecycle lock held by pid={holder.pid} acquired=")


def test_uncontended_acquire_prints_nothing_and_keeps_byte_zero(tmp_path: Path) -> None:
    module = load_module()
    lock_path = tmp_path / "ember-worktree-lifecycle.lock"
    lines: list[str] = []
    with module.RepositoryLock(lock_path, wait_seconds=0, notify=lines.append) as lock:
        assert lock.holder().startswith(f"pid={os.getpid()} acquired=")
    assert lines == []
    assert lock_path.read_bytes() == b"0"


def test_pre_change_lock_file_reads_as_unknown_holder(tmp_path: Path) -> None:
    """A seat on the old tool leaves the bare single byte; the reader must degrade, not crash."""
    module = load_module()
    lock_path = tmp_path / "ember-worktree-lifecycle.lock"
    lock_path.write_bytes(b"0")
    assert module.RepositoryLock(lock_path, wait_seconds=0).holder() == "unknown"


def test_timing_comes_from_environment_and_refuses_garbage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_module()
    lock_path = tmp_path / "ember-worktree-lifecycle.lock"
    monkeypatch.setenv("EMBER_LIFECYCLE_LOCK_WAIT_SECONDS", "7")
    monkeypatch.setenv("EMBER_LIFECYCLE_LOCK_BACKOFF_SECONDS", "0.5")
    lock = module.RepositoryLock(lock_path)
    assert (lock.wait_seconds, lock.backoff_seconds) == (7.0, 0.5)
    # An explicit argument outranks the environment.
    assert module.RepositoryLock(lock_path, wait_seconds=3).wait_seconds == 3.0
    monkeypatch.delenv("EMBER_LIFECYCLE_LOCK_WAIT_SECONDS")
    monkeypatch.delenv("EMBER_LIFECYCLE_LOCK_BACKOFF_SECONDS")
    lock = module.RepositoryLock(lock_path)
    assert (lock.wait_seconds, lock.backoff_seconds) == (120.0, 2.0)
    for bad in ("soon", "-1", "nan", "inf"):
        monkeypatch.setenv("EMBER_LIFECYCLE_LOCK_WAIT_SECONDS", bad)
        with pytest.raises(module.LifecycleError) as caught:
            module.RepositoryLock(lock_path)
        assert caught.value.code == "LIFECYCLE_LOCK_CONFIG"
