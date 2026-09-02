# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Tests for gpu_lock_guard's EMBER_GPU_LOCK_PATH resolution.

The lock file is addressed by different strings on either side of the
Windows/WSL2 boundary, so it cannot be a committed constant -- and the
constant it used to be was a redaction placeholder that made the guard
refuse unconditionally. These tests pin both halves of the replacement:
refuse when unconfigured, and actually work when configured.

Every case drives the real module functions against a real file on disk.
Nothing here stubs the filesystem or the resolver.
"""
import importlib
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _fresh_module(monkeypatch, lock_path):
    """Import gpu_lock_guard with the env var set (or cleared) at import time."""
    if lock_path is None:
        monkeypatch.delenv("EMBER_GPU_LOCK_PATH", raising=False)
    else:
        monkeypatch.setenv("EMBER_GPU_LOCK_PATH", str(lock_path))
    import gpu_lock_guard
    return importlib.reload(gpu_lock_guard)


def test_unset_env_refuses_rather_than_guessing(monkeypatch, capsys):
    guard = _fresh_module(monkeypatch, None)
    assert guard.LOCK_PATH == ""

    with pytest.raises(SystemExit) as exc:
        guard.check_or_die()
    assert exc.value.code == 1
    assert "EMBER_GPU_LOCK_PATH is unset" in capsys.readouterr().err


def test_blank_env_is_treated_as_unset(monkeypatch):
    guard = _fresh_module(monkeypatch, "   ")
    assert guard.LOCK_PATH == ""
    with pytest.raises(SystemExit):
        guard.check_or_die()


def test_configured_path_acquires_and_releases_real_file(monkeypatch, tmp_path):
    lock = tmp_path / "nested" / "gpu.lock"
    guard = _fresh_module(monkeypatch, lock)
    assert guard.LOCK_PATH == os.path.normpath(str(lock))

    guard.check_or_die(script="unit-test")
    assert lock.exists(), "acquire must create the lock file, parent dirs included"

    payload = json.loads(lock.read_text(encoding="utf-8"))
    assert payload["daemon_pid"] == os.getpid()
    assert payload["side"] == "windows"
    assert payload["active_jobs"] == 1
    assert payload["script"] == "unit-test"

    guard.release()
    assert not lock.exists(), "release must remove a lock this process owns"


def test_acquire_context_manager_releases_on_exception(monkeypatch, tmp_path):
    lock = tmp_path / "gpu.lock"
    guard = _fresh_module(monkeypatch, lock)

    with pytest.raises(RuntimeError):
        with guard.acquire(script="unit-test"):
            assert lock.exists()
            raise RuntimeError("boom")

    assert not lock.exists(), "lock must not survive an exception in the body"


def test_live_holder_with_active_jobs_is_refused(monkeypatch, tmp_path, capsys):
    lock = tmp_path / "gpu.lock"
    guard = _fresh_module(monkeypatch, lock)

    # This PID is alive by construction, so the guard must treat it as held.
    lock.write_text(json.dumps({
        "daemon_pid": os.getpid(), "side": "windows", "active_jobs": 1,
        "ts_first": "20260813T000000Z", "ts_last": "20260813T000000Z",
    }), encoding="utf-8")

    with pytest.raises(SystemExit) as exc:
        guard.check_or_die()
    assert exc.value.code == 1
    assert "HELD" in capsys.readouterr().err


def test_corrupt_lock_is_refused_not_overwritten(monkeypatch, tmp_path, capsys):
    lock = tmp_path / "gpu.lock"
    guard = _fresh_module(monkeypatch, lock)
    lock.write_text("{not json", encoding="utf-8")

    with pytest.raises(SystemExit) as exc:
        guard.check_or_die()
    assert exc.value.code == 1
    assert "corrupt lock" in capsys.readouterr().err
    assert lock.read_text(encoding="utf-8") == "{not json"


def test_module_level_rebind_still_wins(monkeypatch, tmp_path):
    """gpu_lock_selftest.py injects a path by assigning gpu_lock_guard.LOCK_PATH.

    That override predates this change and must keep working, so the resolver
    reads the module global rather than re-reading the environment.
    """
    guard = _fresh_module(monkeypatch, None)
    assert guard.LOCK_PATH == ""

    injected = tmp_path / "injected.lock"
    guard.LOCK_PATH = str(injected)
    guard.check_or_die(script="unit-test")
    assert injected.exists()

    guard.release()
    assert not injected.exists()


def test_release_without_configuration_is_a_noop(monkeypatch):
    guard = _fresh_module(monkeypatch, None)
    guard.release()  # must not raise, must not SystemExit
