#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import ctypes
from pathlib import Path

import ember_gate_process_supervision as gate
import owned_process


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _pid_alive(pid: int) -> bool:
    if sys.platform == "win32":
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            if not ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return False
            return exit_code.value == 259
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _stop_pid(pid: int) -> None:
    if not _pid_alive(pid):
        return
    if sys.platform == "win32":
        handle = ctypes.windll.kernel32.OpenProcess(0x0001, False, pid)
        if handle:
            try:
                ctypes.windll.kernel32.TerminateProcess(handle, 1)
            finally:
                ctypes.windll.kernel32.CloseHandle(handle)
    else:
        os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + 5
    while _pid_alive(pid) and time.monotonic() < deadline:
        time.sleep(0.05)


def _wait_for_pid(path: Path, timeout_s: float = 5) -> int:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if path.exists() and path.read_text(encoding="utf-8").strip():
            return int(path.read_text(encoding="utf-8"))
        time.sleep(0.05)
    raise AssertionError(f"PID file was not written: {path.name}")


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        launch = repo / "receipts" / "ember-preloop-resident-gate" / "launch.json"
        out = repo / "process.json"
        _write(launch, json.dumps({"ticket": "EMBER-GATE-LAUNCH-PACKAGING", "verdict": "LAUNCH_PACKAGING_GATE_PASS"}))
        receipt = gate.build_receipt(repo=repo, launch_receipt=launch, out=out)
        assert receipt["verdict"] == "PROCESS_SUPERVISION_GATE_PASS"
        assert receipt["verification"]["checks"]["child_process_spawned_and_tracked"] is True
        assert receipt["verification"]["checks"]["timeout_terminated_child"] is True
        assert receipt["verification"]["checks"]["survivor_detection_clean"] is True
        assert receipt["verification"]["checks"]["background_lifecycle_accounted"] is True
        assert receipt["deletion_ablation"]["supervisor_deleted_blocks_spawn_and_tracking"] is True
        assert receipt["deletion_ablation"]["manual_taskkill_insufficient"] is True

        normal = owned_process.OwnedProcessRunner().run(
            [sys.executable, "-c", "import sys; print('owned-out'); print('owned-err', file=sys.stderr); raise SystemExit(7)"],
            timeout_s=5,
        )
        assert normal.status == "completed"
        assert normal.returncode == 7
        assert normal.stdout == "owned-out\n"
        assert normal.stderr == "owned-err\n"
        assert normal.cleanup_verified is True

        descendant_pid_path = repo / "descendant.pid"
        descendant_code = "import time; time.sleep(60)"
        parent_code = (
            "import pathlib, subprocess, sys, time; "
            f"p=subprocess.Popen([sys.executable, '-c', {descendant_code!r}], "
            "stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True); "
            f"pathlib.Path({str(descendant_pid_path)!r}).write_text(str(p.pid), encoding='utf-8'); "
            "time.sleep(60)"
        )
        supervisor = gate.ResidentProcessSupervisor()
        descendant_pid = None
        try:
            record = supervisor.run_with_timeout([sys.executable, "-c", parent_code], timeout_s=0.5)
            assert record.status == "terminated"
            assert descendant_pid_path.exists(), "parent did not publish descendant PID before timeout"
            descendant_pid = int(descendant_pid_path.read_text(encoding="utf-8"))
            deadline = time.monotonic() + 5
            while _pid_alive(descendant_pid) and time.monotonic() < deadline:
                time.sleep(0.05)
            assert not _pid_alive(descendant_pid), "timeout left a descendant process alive"
        finally:
            if descendant_pid is not None:
                _stop_pid(descendant_pid)

        if sys.platform == "win32":
            refused_marker = repo / "containment-refused-work.txt"

            class _RefusingJob:
                def __enter__(self):
                    return self

                def __exit__(self, *_):
                    self.close()

                def assign_and_resume(self, _proc):
                    raise owned_process.ProcessContainmentError("synthetic assignment refusal")

                def close(self):
                    return None

            refused = False
            try:
                owned_process.OwnedProcessRunner(windows_job_factory=_RefusingJob).run(
                    [sys.executable, "-c", f"from pathlib import Path; Path({str(refused_marker)!r}).write_text('ran')"],
                    timeout_s=5,
                )
            except owned_process.ProcessContainmentError:
                refused = True
            assert refused is True
            assert not refused_marker.exists(), "useful work ran before containment was established"

            crash_pid_path = repo / "crash-descendant.pid"
            scripts_dir = Path(__file__).resolve().parent
            crash_child_code = (
                "import pathlib, sys, time; "
                f"pathlib.Path({str(crash_pid_path)!r}).write_text(str(__import__('os').getpid()), encoding='utf-8'); "
                "time.sleep(60)"
            )
            controller_code = (
                "import sys; "
                f"sys.path.insert(0, {str(scripts_dir)!r}); "
                "from owned_process import OwnedProcessRunner; "
                f"OwnedProcessRunner().run([sys.executable, '-c', {crash_child_code!r}], timeout_s=60)"
            )
            controller = subprocess.Popen([sys.executable, "-c", controller_code])
            crash_descendant_pid = None
            try:
                crash_descendant_pid = _wait_for_pid(crash_pid_path)
                controller.kill()
                controller.wait(timeout=5)
                deadline = time.monotonic() + 5
                while _pid_alive(crash_descendant_pid) and time.monotonic() < deadline:
                    time.sleep(0.05)
                assert not _pid_alive(crash_descendant_pid), "controller exit left its Job Object descendant alive"
            finally:
                if controller.poll() is None:
                    controller.kill()
                    controller.wait(timeout=5)
                if crash_descendant_pid is not None:
                    _stop_pid(crash_descendant_pid)
    print("EMBER_GATE_PROCESS_SUPERVISION_SELFTEST_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
