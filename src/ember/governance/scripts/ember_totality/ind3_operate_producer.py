#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""ind3_operate_producer.py -- C-IND, IND-3 OPERATE producer (DG-W2g board
pass, refs C-IND legs).

Produces the three receipts test_c_ind.py's _validate_ind3() requires
(leg="launch", leg="teardown", leg="interrupted_resume"), each from an
EXECUTED run against a real, CPU-only ember operator surface -- no
hand-crafted JSON, no GPU, no model server.

The operate-able subject is scratch/ind3-operate-worker/telemetry-watch-
worker.ts: a thin OS-process wrapper around the REAL, unmodified
tools/ember-cli/src/services/telemetry-watch.ts service -- the exact
mechanism the live `/watch` slash command uses. Wrapping it in its own
process (rather than calling it as an in-process function) is what makes it
genuinely launchable / tearable-down / interruptible, which an in-process
call is not.

Lifecycle exercised (all via subprocess + independent Windows kernel process-
table checks -- never trusting the Python subprocess handle alone):

  1. launch            -- start instance A, wait for its ready heartbeat,
                           independently verify it is alive.
  2. teardown           -- signal instance A to stop gracefully (writes a
                           stop-marker file the worker polls for -- this
                           repo's existing planned-outage.json marker
                           convention, applied here), wait for exit,
                           independently verify (OpenProcess/GetExitCodeProcess) NO process with
                           that PID survives. orphaned_gpu_state is
                           trivially false -- this whole leg never touches a
                           GPU.
  3. interrupted_resume -- start instance B, wait ready, then
                           UNGRACEFULLY kill it (`taskkill /F`, simulating an
                           unplanned crash -- no marker file, no graceful
                           handler), independently verify it is dead, then
                           RESUME by launching instance C fresh and
                           confirming it reaches ready state -- i.e. the
                           system survives an interrupted stop and can be
                           relaunched. Instance C is then torn down
                           gracefully too (disclosed under
                           final_cleanup) so this producer leaves nothing
                           running.

Platform note: process verification here uses Windows kernel process handles (this
producer was executed on the operator's Windows machine). test_c_ind.py
itself performs no re-execution -- it only inspects the already-written
receipt JSON -- so this platform dependency affects producer re-runs only,
never the board's CI check.

Run:  PYTHONIOENCODING=utf-8 python ind3_operate_producer.py
"""
from __future__ import annotations

import ctypes
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent            # scripts/ember_totality
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', '..', '..'))                     # ember worktree root
sys.path.insert(0, str(REPO_ROOT))
# issue2015 exact-local-import:src/ember/governance/scripts/lib/invariant.py
import importlib.util as _ember_2560a87c017c05b0_importlib
import sys as _ember_2560a87c017c05b0_sys
from pathlib import Path as _ember_2560a87c017c05b0_Path
_ember_2560a87c017c05b0_path = _ember_2560a87c017c05b0_Path(__file__).resolve().parents[5].joinpath('src', 'ember', 'governance', 'scripts', 'lib', 'invariant.py')
if not _ember_2560a87c017c05b0_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/lib/invariant.py')
_ember_2560a87c017c05b0_aliases = ('_ember_issue2015_2560a87c017c05b0', 'invariant', 'scripts.lib.invariant')
_ember_2560a87c017c05b0_existing = []
for _ember_2560a87c017c05b0_alias in _ember_2560a87c017c05b0_aliases:
    _ember_2560a87c017c05b0_candidate = _ember_2560a87c017c05b0_sys.modules.get(_ember_2560a87c017c05b0_alias)
    if _ember_2560a87c017c05b0_candidate is not None and all(_ember_2560a87c017c05b0_candidate is not item for item in _ember_2560a87c017c05b0_existing):
        _ember_2560a87c017c05b0_existing.append(_ember_2560a87c017c05b0_candidate)
if len(_ember_2560a87c017c05b0_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/lib/invariant.py')
if _ember_2560a87c017c05b0_existing:
    _ember_2560a87c017c05b0_module = _ember_2560a87c017c05b0_existing[0]
    _ember_2560a87c017c05b0_observed = getattr(_ember_2560a87c017c05b0_module, '__file__', None)
    if _ember_2560a87c017c05b0_observed is None or _ember_2560a87c017c05b0_Path(_ember_2560a87c017c05b0_observed).resolve() != _ember_2560a87c017c05b0_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/lib/invariant.py')
else:
    _ember_2560a87c017c05b0_spec = _ember_2560a87c017c05b0_importlib.spec_from_file_location('_ember_issue2015_2560a87c017c05b0', _ember_2560a87c017c05b0_path)
    if _ember_2560a87c017c05b0_spec is None or _ember_2560a87c017c05b0_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/lib/invariant.py')
    _ember_2560a87c017c05b0_module = _ember_2560a87c017c05b0_importlib.module_from_spec(_ember_2560a87c017c05b0_spec)
    for _ember_2560a87c017c05b0_alias in _ember_2560a87c017c05b0_aliases:
        _ember_2560a87c017c05b0_prior = _ember_2560a87c017c05b0_sys.modules.get(_ember_2560a87c017c05b0_alias)
        if _ember_2560a87c017c05b0_prior is not None and _ember_2560a87c017c05b0_prior is not _ember_2560a87c017c05b0_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/lib/invariant.py')
        _ember_2560a87c017c05b0_sys.modules[_ember_2560a87c017c05b0_alias] = _ember_2560a87c017c05b0_module
    try:
        _ember_2560a87c017c05b0_spec.loader.exec_module(_ember_2560a87c017c05b0_module)
    except BaseException:
        for _ember_2560a87c017c05b0_alias in _ember_2560a87c017c05b0_aliases:
            if _ember_2560a87c017c05b0_sys.modules.get(_ember_2560a87c017c05b0_alias) is _ember_2560a87c017c05b0_module:
                _ember_2560a87c017c05b0_sys.modules.pop(_ember_2560a87c017c05b0_alias, None)
        raise
for _ember_2560a87c017c05b0_alias in _ember_2560a87c017c05b0_aliases:
    _ember_2560a87c017c05b0_prior = _ember_2560a87c017c05b0_sys.modules.get(_ember_2560a87c017c05b0_alias)
    if _ember_2560a87c017c05b0_prior is not None and _ember_2560a87c017c05b0_prior is not _ember_2560a87c017c05b0_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/lib/invariant.py')
    _ember_2560a87c017c05b0_sys.modules[_ember_2560a87c017c05b0_alias] = _ember_2560a87c017c05b0_module
_stamp_invariant = getattr(_ember_2560a87c017c05b0_module, 'stamp')
_verify_invariant = getattr(_ember_2560a87c017c05b0_module, 'verify')
# issue2015 exact-local-import-end:src/ember/governance/scripts/lib/invariant.py  # noqa: E402 -- gh #625 point 1

# receipt_check.py's R2 rule requires any *sha256*-named field to carry a
# disclosed sha_convention; matches exactly what src/ember/governance/scripts/lib/invariant.py's
# stamp() does (Path.read_bytes() + sha256, no normalization).
INVARIANT_SHA_CONVENTION = "bytes on disk as-is (binary read, no line-ending normalization)"
WORKER = REPO_ROOT / "scratch" / "ind3-operate-worker" / "telemetry-watch-worker.ts"
RUNTIME_DIR = REPO_ROOT / "scratch" / "ind3-operate-runtime"
RECEIPTS_OUT_DIR = REPO_ROOT / "receipts" / "ind3-operate"

BUN = shutil.which("bun") or "bun"


def _relpath(p: Path) -> str:
    return p.relative_to(REPO_ROOT).as_posix()


def _sanitize(text: str) -> str:
    root_str = str(REPO_ROOT)
    out = text.replace(root_str.replace("/", "\\"), ".").replace(root_str, ".")
    return out.replace("\\", "/")


def _now_ts() -> str:
    return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())


def _pid_is_alive(pid: int) -> bool:
    """Query the Windows kernel for PID liveness without trusting the child
    handle or a best-effort command whose failure could be mistaken for death.

    ERROR_INVALID_PARAMETER is Windows' absent-PID result. Every other probe
    failure is terminal: access denied or an unreadable exit code is unknown
    evidence, never evidence that a process is dead.
    """
    if os.name != "nt":
        raise RuntimeError("IND-3 process verification requires Windows")
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    open_process = kernel32.OpenProcess
    open_process.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    open_process.restype = ctypes.c_void_p
    get_exit_code = kernel32.GetExitCodeProcess
    get_exit_code.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
    get_exit_code.restype = ctypes.c_int
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [ctypes.c_void_p]
    close_handle.restype = ctypes.c_int

    handle = open_process(0x1000, 0, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        error = ctypes.get_last_error()
        if error == 87:  # ERROR_INVALID_PARAMETER: no process owns this PID.
            return False
        raise OSError(error, f"OpenProcess failed for pid {pid}")
    try:
        exit_code = ctypes.c_uint32()
        if not get_exit_code(handle, ctypes.byref(exit_code)):
            error = ctypes.get_last_error()
            raise OSError(error, f"GetExitCodeProcess failed for pid {pid}")
        return exit_code.value == 259  # STILL_ACTIVE
    finally:
        close_handle(handle)

def _terminate_pid(pid: int, timeout_ms: int = 5000) -> None:
    """Hard-stop one exact PID through an owned Windows process handle."""
    if os.name != "nt":
        raise RuntimeError("IND-3 process termination requires Windows")
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    open_process = kernel32.OpenProcess
    open_process.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    open_process.restype = ctypes.c_void_p
    terminate_process = kernel32.TerminateProcess
    terminate_process.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    terminate_process.restype = ctypes.c_int
    wait_for_single_object = kernel32.WaitForSingleObject
    wait_for_single_object.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    wait_for_single_object.restype = ctypes.c_uint32
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [ctypes.c_void_p]
    close_handle.restype = ctypes.c_int

    handle = open_process(0x00100001, 0, pid)  # SYNCHRONIZE | PROCESS_TERMINATE
    if not handle:
        error = ctypes.get_last_error()
        raise OSError(error, f"OpenProcess terminate access failed for pid {pid}")
    try:
        if not terminate_process(handle, 137):
            error = ctypes.get_last_error()
            raise OSError(error, f"TerminateProcess failed for pid {pid}")
        wait_result = wait_for_single_object(handle, timeout_ms)
        if wait_result != 0:  # WAIT_OBJECT_0
            raise TimeoutError(f"pid {pid} did not terminate; wait_result={wait_result}")
    finally:
        close_handle(handle)
def _wait_heartbeat_status(path: Path, want_status: str, timeout: float = 15.0) -> dict:
    deadline = time.time() + timeout
    last: dict | None = None
    while time.time() < deadline:
        if path.is_file():
            try:
                obj = json.loads(path.read_text(encoding="utf-8"))
                last = obj
                if obj.get("status") == want_status:
                    return obj
            except (OSError, json.JSONDecodeError):
                pass
        time.sleep(0.2)
    raise TimeoutError(f"heartbeat at {path} never reached status={want_status!r}; last seen: {last}")


def _launch_worker(tag: str) -> tuple[subprocess.Popen, Path, Path, Path]:
    channel = RUNTIME_DIR / f"channel-{tag}.jsonl"
    heartbeat = RUNTIME_DIR / f"heartbeat-{tag}.json"
    stopmarker = RUNTIME_DIR / f"stopmarker-{tag}.json"
    for stale in (channel, heartbeat, stopmarker):
        stale.unlink(missing_ok=True)
    proc = subprocess.Popen(
        [BUN, "run", str(WORKER), str(channel), str(heartbeat), str(stopmarker)],
        cwd=str(REPO_ROOT), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    return proc, channel, heartbeat, stopmarker


def _graceful_stop(proc: subprocess.Popen, pid: int, heartbeat: Path, stopmarker: Path, timeout: float = 15.0) -> dict:
    """Signal graceful stop and independently prove the worker PID exited."""
    stopmarker.write_text("{}", encoding="utf-8")
    deadline = time.time() + timeout
    while time.time() < deadline and _pid_is_alive(pid):
        time.sleep(0.2)
    try:
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        pass
    if _pid_is_alive(pid):
        raise TimeoutError(f"worker pid {pid} survived graceful-stop deadline")
    hb = json.loads(heartbeat.read_text(encoding="utf-8"))
    return {"exit_code": proc.returncode, "final_heartbeat": hb}

def build_launch_receipt() -> tuple[dict, subprocess.Popen, int, Path, Path, Path]:
    proc, channel, heartbeat, stopmarker = _launch_worker("a-launch")
    hb = _wait_heartbeat_status(heartbeat, "ready")
    pid = hb["pid"]
    if not _pid_is_alive(pid):
        raise RuntimeError(f"ready heartbeat pid {pid} is not alive")
    receipt = {
        "ticket": "EMBER-700",
        "goal_id": "EMBER-02",
        "workstream_id": "EMBER-02A",
        "next_executed_outcome": "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember",
        "receipt_class": "IND-3",
        "leg": "launch",
        "producer": "ind3_operate_producer.py",
        "worker_script": _relpath(WORKER),
        "underlying_service": "tools/ember-cli/src/services/telemetry-watch.ts (startTelemetryWatch, unmodified -- the real /watch mechanism)",
        "launch_command": f"bun run {_relpath(WORKER)} {_relpath(channel)} {_relpath(heartbeat)} {_relpath(stopmarker)}",
        "pid": pid,
        "launcher_process_pid_note": (
            "the `bun run` invocation's own subprocess handle reports a DIFFERENT "
            "pid than the one the worker script itself observes via process.pid and "
            "writes to its heartbeat -- bun run launches a wrapper distinct from the "
            "runtime that executes the script. `pid` here, and every process-table "
            "check in this producer, uses the heartbeat-reported (real, executing) pid."
        ),
        "heartbeat_ready": hb,
        "verified_alive_via": "Windows OpenProcess + GetExitCodeProcess (PROCESS_QUERY_LIMITED_INFORMATION)",
        "verified_alive": True,
        "doc_pointer": "docs/domains/governance/operator/operate.md",
        "ts": _now_ts(),
    }
    return receipt, proc, pid, channel, heartbeat, stopmarker

def build_teardown_receipt(proc: subprocess.Popen, pid: int, heartbeat: Path, stopmarker: Path) -> dict:
    result = _graceful_stop(proc, pid, heartbeat, stopmarker)
    post_alive = _pid_is_alive(pid)
    receipt = {
        "ticket": "EMBER-700",
        "goal_id": "EMBER-02",
        "workstream_id": "EMBER-02A",
        "next_executed_outcome": "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember",
        "receipt_class": "IND-3",
        "leg": "teardown",
        "producer": "ind3_operate_producer.py",
        "torn_down_pid": pid,
        "stop_method": "graceful marker-file stop (stopmarker written, worker calls handle.stop() and exits 0)",
        "exit_code": result["exit_code"],
        "final_heartbeat": result["final_heartbeat"],
        "post_stop_process_table": {
            "checked_pid": pid,
            "method": "Windows OpenProcess + GetExitCodeProcess (PROCESS_QUERY_LIMITED_INFORMATION)",
            "survivors": ([{"pid": pid, "state": "STILL_ACTIVE"}] if post_alive else []),
            "orphaned_gpu_state": False,
            "note": "no GPU or model server is touched anywhere in this leg; orphaned_gpu_state is trivially false",
        },
        "doc_pointer": "docs/domains/governance/operator/operate.md",
        "ts": _now_ts(),
    }
    return receipt

def build_interrupted_resume_receipt() -> dict:
    proc_b, _channel_b, heartbeat_b, _stopmarker_b = _launch_worker("b-interrupt")
    hb_b = _wait_heartbeat_status(heartbeat_b, "ready")
    pid_b = hb_b["pid"]
    if not _pid_is_alive(pid_b):
        raise RuntimeError(f"interruption target pid {pid_b} is not alive")

    # This producer owns both exact PIDs. A kernel TerminateProcess call models
    # an ungraceful crash without depending on taskkill, whose access-denied
    # output was previously misread as successful evidence.
    terminated_pids: list[int] = []
    _terminate_pid(pid_b)
    terminated_pids.append(pid_b)
    if _pid_is_alive(proc_b.pid):
        _terminate_pid(proc_b.pid)
        terminated_pids.append(proc_b.pid)
    try:
        proc_b.wait(timeout=10)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("owned launcher handle did not observe hard stop") from exc
    worker_b_alive = _pid_is_alive(pid_b)
    launcher_b_alive = _pid_is_alive(proc_b.pid)
    if worker_b_alive or launcher_b_alive:
        raise RuntimeError(
            "hard interruption was not proved: "
            f"worker_alive={worker_b_alive}, launcher_alive={launcher_b_alive}"
        )

    proc_c, _channel_c, heartbeat_c, stopmarker_c = _launch_worker("c-resume")
    hb_c = _wait_heartbeat_status(heartbeat_c, "ready")
    pid_c = hb_c["pid"]
    if not _pid_is_alive(pid_c):
        raise RuntimeError(f"resumed ready heartbeat pid {pid_c} is not alive")

    cleanup = _graceful_stop(proc_c, pid_c, heartbeat_c, stopmarker_c)
    post_alive_c = _pid_is_alive(pid_c)

    return {
        "ticket": "EMBER-700",
        "goal_id": "EMBER-02",
        "workstream_id": "EMBER-02A",
        "next_executed_outcome": "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember",
        "receipt_class": "IND-3",
        "leg": "interrupted_resume",
        "producer": "ind3_operate_producer.py",
        "interrupted_pid": pid_b,
        "interrupted_launcher_pid": proc_b.pid,
        "interrupt_method": "Windows TerminateProcess on exact producer-owned worker PID and live launcher PID (hard, ungraceful; no stop marker)",
        "interrupt_command_exit_code": 0,
        "terminated_pids": terminated_pids,
        "verified_dead_via": "Windows OpenProcess + GetExitCodeProcess for worker and launcher PIDs",
        "interrupted_pid_verified_dead": True,
        "interrupted_launcher_pid_verified_dead": True,
        "resumed_pid": pid_c,
        "resumed_ready_heartbeat": hb_c,
        "resumed_verified_alive": True,
        "final_cleanup": {
            "cleaned_pid": pid_c,
            "exit_code": cleanup["exit_code"],
            "post_stop_survivors": ([{"pid": pid_c, "state": "STILL_ACTIVE"}] if post_alive_c else []),
        },
        "doc_pointer": "docs/domains/governance/operator/operate.md",
        "ts": _now_ts(),
    }

def _write_receipt_json(output: Path, receipt: dict) -> None:
    with output.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(receipt, handle, indent=2)
        handle.write("\n")

def main() -> int:
    # Verify authority before any process is launched or receipt is written.
    _verify_invariant(str(REPO_ROOT))

    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    RECEIPTS_OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Complete the entire lifecycle before publishing any receipt. A failed
    # interruption/resume must not leave a partial set that looks authoritative.
    launch_receipt, proc_a, pid_a, _channel_a, heartbeat_a, stopmarker_a = build_launch_receipt()
    teardown_receipt = build_teardown_receipt(proc_a, pid_a, heartbeat_a, stopmarker_a)
    interrupted_receipt = build_interrupted_resume_receipt()
    receipts = [launch_receipt, teardown_receipt, interrupted_receipt]
    for receipt in receipts:
        _stamp_invariant(receipt, repo_root=str(REPO_ROOT))
        receipt["sha_convention"] = INVARIANT_SHA_CONVENTION

    outputs = [
        RECEIPTS_OUT_DIR / f"ind3-launch-{launch_receipt['ts']}.json",
        RECEIPTS_OUT_DIR / f"ind3-teardown-{teardown_receipt['ts']}.json",
        RECEIPTS_OUT_DIR / f"ind3-interrupted-resume-{interrupted_receipt['ts']}.json",
    ]
    for output, receipt in zip(outputs, receipts):
        _write_receipt_json(output, receipt)

    print(f"launch: wrote {_relpath(outputs[0])} (pid={launch_receipt['pid']}, verified_alive=True)")
    print(f"teardown: wrote {_relpath(outputs[1])} (survivors=[])")
    print(
        f"interrupted_resume: wrote {_relpath(outputs[2])} "
        f"(interrupted_pid_verified_dead=True, resumed_verified_alive=True)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
