# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
GOVERNANCE_SCRIPTS = ROOT / "src" / "ember" / "governance" / "scripts"
sys.path.insert(0, str(GOVERNANCE_SCRIPTS))

import owned_process  # noqa: E402


@pytest.mark.skipif(sys.platform != "win32", reason="Windows process flags are unavailable")
def test_windows_runner_forbids_a_console_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    class Completed:
        pid = 12345
        returncode = 0

        @staticmethod
        def poll() -> int:
            return 0

        @staticmethod
        def communicate(timeout: float) -> tuple[str, str]:
            return "done", ""

        @staticmethod
        def kill() -> None:
            raise AssertionError("completed process must not be killed")

        @staticmethod
        def wait(timeout: float) -> int:
            return 0

    class Job:
        def __enter__(self) -> "Job":
            return self

        def __exit__(self, *_: object) -> None:
            self.close()

        @staticmethod
        def assign_and_resume(_process: Completed) -> None:
            return None

        @staticmethod
        def close() -> None:
            return None

    def fake_popen(_argv: list[str], **kwargs: object) -> Completed:
        calls.append(kwargs)
        return Completed()

    monkeypatch.setattr(owned_process.subprocess, "Popen", fake_popen)

    result = owned_process.OwnedProcessRunner(
        windows_job_factory=Job
    )._run_windows(["command"], 1.0, cwd=None, env=None)

    assert result.status == "completed"
    assert len(calls) == 1
    flags = int(calls[0]["creationflags"])
    assert flags & 0x00000004  # CREATE_SUSPENDED
    assert flags & subprocess.CREATE_NEW_PROCESS_GROUP
    assert flags & subprocess.CREATE_NO_WINDOW


def _pid_alive(pid: int) -> bool:
    if sys.platform == "linux":
        try:
            state = Path(f"/proc/{pid}/stat").read_text(encoding="ascii").rsplit(")", 1)[1].split()[0]
            if state == "Z":
                return False
        except (OSError, IndexError):
            return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _wait_for_pid(path: Path, timeout_s: float = 5.0) -> int:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if path.exists() and path.read_text(encoding="utf-8").strip():
            return int(path.read_text(encoding="utf-8"))
        time.sleep(0.05)
    raise AssertionError(f"PID file was not written: {path}")


def test_posix_backend_has_controller_death_contract_for_linux_and_macos() -> None:
    assert owned_process._posix_controller_death_backend("linux") == (
        "linux-prctl-pdeathsig+process-group-sentinel"
    )
    assert owned_process._posix_controller_death_backend("darwin") == (
        "darwin-process-group-sentinel"
    )


def test_posix_runner_uses_exec_guard_without_preexec_fork(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[str], dict[str, object]]] = []

    class Completed:
        pid = 12345
        returncode = 0

        @staticmethod
        def communicate(timeout: float) -> tuple[str, str]:
            return "done", ""

    def fake_popen(argv: list[str], **kwargs: object) -> Completed:
        calls.append((argv, kwargs))
        return Completed()

    monkeypatch.setattr(owned_process.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(
        owned_process.OwnedProcessRunner,
        "_kill_posix_group",
        staticmethod(lambda _pid: None),
    )

    result = owned_process.OwnedProcessRunner()._run_posix(
        ["command", "arg"], 1.0, cwd=None, env=None
    )

    assert result.stdout == "done"
    assert len(calls) == 1
    guard_argv, kwargs = calls[0]
    assert guard_argv[-3:] == ["--", "command", "arg"]
    assert "preexec_fn" not in kwargs
    assert len(kwargs["pass_fds"]) == 1


def test_posix_timeout_kills_owned_group_once(monkeypatch: pytest.MonkeyPatch) -> None:
    class TimedOutProcess:
        pid = 12345
        returncode = -owned_process._SIGKILL
        communicate_calls = 0

        @classmethod
        def communicate(cls, timeout: float) -> tuple[str, str]:
            cls.communicate_calls += 1
            if cls.communicate_calls == 1:
                raise subprocess.TimeoutExpired(["command"], timeout)
            return "", ""

    monkeypatch.setattr(
        owned_process.subprocess,
        "Popen",
        lambda *_args, **_kwargs: TimedOutProcess(),
    )
    killed: list[int] = []

    def kill_once(pid: int) -> None:
        killed.append(pid)
        if len(killed) > 1:
            raise PermissionError("macOS refused the redundant group kill")

    monkeypatch.setattr(
        owned_process.OwnedProcessRunner,
        "_kill_posix_group",
        staticmethod(kill_once),
    )

    result = owned_process.OwnedProcessRunner()._run_posix(
        ["command"], 0.2, cwd=None, env=None
    )

    assert result.status == "terminated"
    assert killed == [12345]


def test_private_posix_guard_refuses_unowned_process_group_before_install(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(owned_process.os, "getpid", lambda: 101)
    monkeypatch.setattr(owned_process.os, "getpgrp", lambda: 202, raising=False)
    monkeypatch.setattr(owned_process.os, "getsid", lambda _pid: 202, raising=False)
    monkeypatch.setattr(
        owned_process,
        "_install_posix_controller_death_guard",
        lambda _fd: pytest.fail("unowned guard reached fork-capable installer"),
    )

    with pytest.raises(owned_process.ProcessContainmentError, match="session leader"):
        owned_process._run_posix_guard(["-1", "--", "command"])


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX descriptor validation")
def test_posix_guard_accepts_only_readable_controller_pipe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    pid = os.getpid()
    monkeypatch.setattr(owned_process.os, "getpgrp", lambda: pid)
    monkeypatch.setattr(owned_process.os, "getsid", lambda _pid: pid)
    read_fd, write_fd = os.pipe()
    regular = (tmp_path / "not-a-pipe").open("wb+")
    try:
        assert owned_process._validate_posix_guard_context(read_fd) == pid
        with pytest.raises(owned_process.ProcessContainmentError, match="readable pipe"):
            owned_process._validate_posix_guard_context(write_fd)
        with pytest.raises(owned_process.ProcessContainmentError, match="readable pipe"):
            owned_process._validate_posix_guard_context(regular.fileno())
    finally:
        regular.close()
        os.close(read_fd)
        os.close(write_fd)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX completion backend")
def test_posix_ordinary_completion_returns_promptly() -> None:
    started = time.monotonic()
    result = owned_process.OwnedProcessRunner().run(
        [sys.executable, "-c", "print('complete')"], timeout_s=5
    )
    assert result.returncode == 0
    assert result.stdout == "complete\n"
    assert time.monotonic() - started < 5


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX timeout backend")
def test_posix_timeout_returns_and_kills_command() -> None:
    started = time.monotonic()
    result = owned_process.OwnedProcessRunner().run(
        [sys.executable, "-c", "import time; time.sleep(60)"], timeout_s=0.2
    )
    assert result.status == "terminated"
    assert time.monotonic() - started < 5


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX controller-death backend")
def test_posix_controller_death_reaps_grandchild_before_runner_returns(tmp_path: Path) -> None:
    descendant_pid_path = tmp_path / "descendant.pid"
    scripts_dir = GOVERNANCE_SCRIPTS
    descendant_code = "import time; time.sleep(60)"
    parent_code = (
        "import pathlib, subprocess, sys, time; "
        f"p=subprocess.Popen([sys.executable, '-c', {descendant_code!r}], "
        "stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True); "
        f"pathlib.Path({str(descendant_pid_path)!r}).write_text(str(p.pid), encoding='utf-8'); "
        "time.sleep(60)"
    )
    controller_code = (
        "import sys; "
        f"sys.path.insert(0, {str(scripts_dir)!r}); "
        "from owned_process import OwnedProcessRunner; "
        f"OwnedProcessRunner().run([sys.executable, '-c', {parent_code!r}], timeout_s=60)"
    )
    controller = subprocess.Popen([sys.executable, "-c", controller_code])
    descendant_pid: int | None = None
    try:
        descendant_pid = _wait_for_pid(descendant_pid_path)
        controller.kill()
        controller.wait(timeout=5)
        deadline = time.monotonic() + 5
        while _pid_alive(descendant_pid) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert not _pid_alive(descendant_pid), "controller death left a POSIX grandchild alive"
    finally:
        if controller.poll() is None:
            controller.kill()
            controller.wait(timeout=5)
        if descendant_pid is not None and _pid_alive(descendant_pid):
            os.kill(descendant_pid, owned_process._SIGKILL)
