#!/usr/bin/env python3
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

Lifecycle exercised (all via subprocess + independent `tasklist` process-
table checks -- never trusting the Python subprocess handle alone):

  1. launch            -- start instance A, wait for its ready heartbeat,
                           independently verify it is alive.
  2. teardown           -- signal instance A to stop gracefully (writes a
                           stop-marker file the worker polls for -- this
                           repo's existing planned-outage.json marker
                           convention, applied here), wait for exit,
                           independently verify (tasklist) NO process with
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

Platform note: process verification here uses Windows `tasklist` (this
producer was executed on the operator's Windows machine). test_c_ind.py
itself performs no re-execution -- it only inspects the already-written
receipt JSON -- so this platform dependency affects producer re-runs only,
never the board's CI check.

Run:  PYTHONIOENCODING=utf-8 python ind3_operate_producer.py
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent            # scripts/ember_totality
REPO_ROOT = HERE.parent.parent                     # ember worktree root
sys.path.insert(0, str(REPO_ROOT))
from scripts.lib.invariant import stamp as _stamp_invariant, verify as _verify_invariant  # noqa: E402 -- gh #625 point 1

# receipt_check.py's R2 rule requires any *sha256*-named field to carry a
# disclosed sha_convention; matches exactly what scripts/lib/invariant.py's
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


def _tasklist_rows(pid: int) -> list[str]:
    """Independent OS-level process-table check via `tasklist`, never trusting
    the Python subprocess handle alone. Returns the raw CSV rows matching pid
    (empty list = no such process is running)."""
    proc = subprocess.run(
        ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
        capture_output=True, text=True, timeout=15,
    )
    lines = [ln for ln in (proc.stdout or "").splitlines() if ln.strip()]
    return [ln for ln in lines if f'"{pid}"' in ln or f",{pid}," in ln.replace('"', "")]


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
    proc = subprocess.Popen(
        [BUN, "run", str(WORKER), str(channel), str(heartbeat), str(stopmarker)],
        cwd=str(REPO_ROOT), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    return proc, channel, heartbeat, stopmarker


def _graceful_stop(proc: subprocess.Popen, pid: int, heartbeat: Path, stopmarker: Path, timeout: float = 15.0) -> dict:
    """Signals graceful stop, then waits on BOTH the real worker pid (the
    authoritative check -- `bun run` spawns a launcher whose own Popen pid is
    NOT the same OS process as the one that actually runs the script and
    reports its own `process.pid` in the heartbeat; confirmed by direct
    observation: the two pids differ every run) and the Python-tracked Popen
    handle (best-effort reap only, never the source of truth)."""
    stopmarker.write_text("{}", encoding="utf-8")
    deadline = time.time() + timeout
    while time.time() < deadline and _tasklist_rows(pid):
        time.sleep(0.2)
    try:
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        pass  # the launcher wrapper process is not the authoritative signal; see above
    hb = json.loads(heartbeat.read_text(encoding="utf-8"))
    return {"exit_code": proc.returncode, "final_heartbeat": hb}


def build_launch_receipt() -> tuple[dict, subprocess.Popen, int, Path, Path, Path]:
    proc, channel, heartbeat, stopmarker = _launch_worker("a-launch")
    hb = _wait_heartbeat_status(heartbeat, "ready")
    pid = hb["pid"]
    alive_rows = _tasklist_rows(pid)
    receipt = {
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
        "verified_alive_via": "tasklist /FI \"PID eq <pid>\" /FO CSV /NH",
        "verified_alive": bool(alive_rows),
        "doc_pointer": "docs/operator/operate.md",
        "ts": _now_ts(),
    }
    return receipt, proc, pid, channel, heartbeat, stopmarker


def build_teardown_receipt(proc: subprocess.Popen, pid: int, heartbeat: Path, stopmarker: Path) -> dict:
    result = _graceful_stop(proc, pid, heartbeat, stopmarker)
    post_rows = _tasklist_rows(pid)
    receipt = {
        "receipt_class": "IND-3",
        "leg": "teardown",
        "producer": "ind3_operate_producer.py",
        "torn_down_pid": pid,
        "stop_method": "graceful marker-file stop (stopmarker written, worker calls handle.stop() and exits 0)",
        "exit_code": result["exit_code"],
        "final_heartbeat": result["final_heartbeat"],
        "post_stop_process_table": {
            "checked_pid": pid,
            "method": "tasklist /FI \"PID eq <pid>\" /FO CSV /NH",
            "survivors": [],
            "orphaned_gpu_state": False,
            "note": "no GPU or model server is touched anywhere in this leg; orphaned_gpu_state is trivially false",
        },
        "doc_pointer": "docs/operator/operate.md",
        "ts": _now_ts(),
    }
    if post_rows:
        # Honest failure shape -- never silently claim a clean teardown.
        receipt["post_stop_process_table"]["survivors"] = post_rows
    return receipt


def build_interrupted_resume_receipt() -> dict:
    # Instance B: launch, then kill it UNGRACEFULLY (no marker file).
    proc_b, channel_b, heartbeat_b, stopmarker_b = _launch_worker("b-interrupt")
    hb_b = _wait_heartbeat_status(heartbeat_b, "ready")
    pid_b = hb_b["pid"]  # the real worker pid, as reported by the worker itself

    # Tree-kill the LAUNCHER pid (proc_b.pid), not just the worker's own pid.
    # First attempt used only the worker pid and left the `bun run` launcher
    # process itself running as an orphan (confirmed by direct observation:
    # tasklist still showed a bun.exe whose cmdline matched this instance
    # after the worker pid was gone) -- an ungraceful kill must take down the
    # whole process tree, matching what an operator closing a terminal
    # window / Ctrl+C'ing a process GROUP actually does.
    kill_proc = subprocess.run(
        ["taskkill", "/F", "/T", "/PID", str(proc_b.pid)],
        capture_output=True, text=True, timeout=15,
    )
    try:
        proc_b.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass
    time.sleep(0.5)
    dead_rows_b = _tasklist_rows(pid_b)
    dead_rows_launcher_b = _tasklist_rows(proc_b.pid)

    # Resume: launch instance C fresh and confirm it reaches ready.
    proc_c, channel_c, heartbeat_c, stopmarker_c = _launch_worker("c-resume")
    hb_c = _wait_heartbeat_status(heartbeat_c, "ready")
    pid_c = hb_c["pid"]
    alive_rows_c = _tasklist_rows(pid_c)

    # Clean up instance C so this producer leaves nothing running.
    cleanup = _graceful_stop(proc_c, pid_c, heartbeat_c, stopmarker_c)
    post_rows_c = _tasklist_rows(pid_c)

    receipt = {
        "receipt_class": "IND-3",
        "leg": "interrupted_resume",
        "producer": "ind3_operate_producer.py",
        "interrupted_pid": pid_b,
        "interrupted_launcher_pid": proc_b.pid,
        "interrupt_method": "taskkill /F /T /PID <launcher pid> (hard, ungraceful tree-kill -- no stop-marker file, simulating an unplanned crash of the whole process group)",
        "interrupt_command_exit_code": kill_proc.returncode,
        "verified_dead_via": "tasklist /FI \"PID eq <pid>\" /FO CSV /NH, checked for both the worker pid and the launcher pid",
        "interrupted_pid_verified_dead": not dead_rows_b,
        "interrupted_launcher_pid_verified_dead": not dead_rows_launcher_b,
        "resumed_pid": pid_c,
        "resumed_ready_heartbeat": hb_c,
        "resumed_verified_alive": bool(alive_rows_c),
        "final_cleanup": {
            "cleaned_pid": pid_c,
            "exit_code": cleanup["exit_code"],
            "post_stop_survivors": post_rows_c,
        },
        "doc_pointer": "docs/operator/operate.md",
        "ts": _now_ts(),
    }
    return receipt


def main() -> int:
    # gh #625 point 1, fail-closed: verify BEFORE any process is launched or
    # any receipt is written -- verify() raises (FileNotFoundError/ValueError)
    # if INVARIANT.md is missing or doesn't hash correctly, which must abort
    # this whole producer, never emit a partial unstamped set.
    _verify_invariant(str(REPO_ROOT))

    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    RECEIPTS_OUT_DIR.mkdir(parents=True, exist_ok=True)

    launch_receipt, proc_a, pid_a, channel_a, heartbeat_a, stopmarker_a = build_launch_receipt()
    _stamp_invariant(launch_receipt, repo_root=str(REPO_ROOT))
    launch_receipt["sha_convention"] = INVARIANT_SHA_CONVENTION
    launch_out = RECEIPTS_OUT_DIR / f"ind3-launch-{launch_receipt['ts']}.json"
    launch_out.write_text(json.dumps(launch_receipt, indent=2), encoding="utf-8")
    print(f"launch: wrote {_relpath(launch_out)} (pid={launch_receipt['pid']}, verified_alive={launch_receipt['verified_alive']})")

    teardown_receipt = build_teardown_receipt(proc_a, pid_a, heartbeat_a, stopmarker_a)
    _stamp_invariant(teardown_receipt, repo_root=str(REPO_ROOT))
    teardown_receipt["sha_convention"] = INVARIANT_SHA_CONVENTION
    teardown_out = RECEIPTS_OUT_DIR / f"ind3-teardown-{teardown_receipt['ts']}.json"
    teardown_out.write_text(json.dumps(teardown_receipt, indent=2), encoding="utf-8")
    print(f"teardown: wrote {_relpath(teardown_out)} (survivors={teardown_receipt['post_stop_process_table']['survivors']})")

    interrupted_receipt = build_interrupted_resume_receipt()
    _stamp_invariant(interrupted_receipt, repo_root=str(REPO_ROOT))
    interrupted_receipt["sha_convention"] = INVARIANT_SHA_CONVENTION
    interrupted_out = RECEIPTS_OUT_DIR / f"ind3-interrupted-resume-{interrupted_receipt['ts']}.json"
    interrupted_out.write_text(json.dumps(interrupted_receipt, indent=2), encoding="utf-8")
    print(
        f"interrupted_resume: wrote {_relpath(interrupted_out)} "
        f"(interrupted_pid_verified_dead={interrupted_receipt['interrupted_pid_verified_dead']}, "
        f"resumed_verified_alive={interrupted_receipt['resumed_verified_alive']})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
