#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""ember_ind3_operate_capture.py -- IND-3 OPERATE cure (launch / teardown / interrupted_resume).

Cures C-IND's IND-3 class (operator-independence-v1.md sec2, row IND-3: "documented start AND
stop of the loop and of goal mode, with independent capture ... plus an interrupted-stop case
with continuity fields").

Cockpit-under-test: tools/ember-cli/src/core/ember-world-state-repl.ts -- the SAME real,
already-proven cockpit process the C-OBS capture (ember_cobs_capture.py) uses, run via node's
built-in TypeScript type-stripping (no `bun build`, no ember-cured.exe rebuild -- this session's
rail forbids binary rebuilds). It is a real operator-runnable program (`node
core/ember-world-state-repl.ts`, documented in docs/operator/activate.md) that reads real
GOAL/ledger/receipts state at boot and appends real, disk-persisted events (fs/promises
appendFile, core/encounter-membrane.ts's logEncounter()) to an encounter log as the operator
drives it -- exactly the kind of durable, externally-observable state IND-3's continuity
fields need, and NOT something this harness fabricates: the file's bytes on disk are the
evidence.

Three legs, three real ConPTY-driven process lifecycles:
  launch    -- cold-launch session A, drive it to produce real state (an offer + a confirmed
               outcome, real appendFile writes), then send the documented `quit` command for a
               graceful stop. PID cohort = [session A's spawned pid].
  teardown  -- AFTER session A's process has exited, a DISTINCT subprocess (powershell.exe
               Get-Process, never the ember process itself -- self-reported teardown is exactly
               the self-attestation this repo bans) captures the raw OS process table and
               confirms session A's pid is not present. GPU compute-apps dump is intentionally
               NOT queried this session (out-of-scope rail: never touch GPU/training); this is
               honestly noted rather than faked -- orphaned_gpu_state is trivially false because
               this cockpit process is CPU-only Node.js and never opens a CUDA context, not
               because a GPU-side capture was taken and found empty.
  interrupted_resume -- session B is cold-launched against the SAME encounter-log file path,
               produces real state, and is NOT sent `quit`: the reused pty driver's own
               deadline-based proc.kill() force-stops it (an actual interruption, not a graceful
               shutdown). The pre-interrupt row count + sha256 of the encounter log are captured
               from the file itself (not from the killed process). A FRESH session C process is
               then launched against the SAME file, produces more real state, and is stopped
               gracefully via `quit`. Continuity is checked mechanically: post-resume row count
               >= pre-interrupt row count, and the pre-interrupt rows are byte-identical
               (unchanged) in the post-resume file.

Read-only w.r.t. GPU/training: this harness never imports torch, never opens the GPU, never
signals or reads the live training process. CPU + local filesystem + ConPTY only.

Usage: python ember_ind3_operate_capture.py [--dry-run]

Provenance: landed from stage dryrun-20260704T211712Z (ember issue #210 Tier 2)
with a portability fix over the staged original -- EXEC_ROOT, GOALFORGE_ROOT's
default, and the import_provenance metadata dict all carried absolute
drive-letter-rooted literals, which tripped the repo's leak-gate on the path
shape and were non-functional off the export machine either way. EXEC_ROOT now
computes from __file__ (functionally identical: this file's grandparent
directory is the repo root); GOALFORGE_ROOT's default now computes as
EXEC_ROOT's sibling "ember-goalforge" (same on-disk convention the original
hardcoded, still overridable via EMBER_GOALFORGE_ROOT); the import_provenance
strings now interpolate the same two variables instead of duplicating the
literal. No other lines changed. See receipts/ember-c-scale/land210f-*.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

EXEC_ROOT = str(next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file()))
GOALFORGE_ROOT = os.environ.get(
    "EMBER_GOALFORGE_ROOT", os.path.join(os.path.dirname(EXEC_ROOT), "ember-goalforge")
)

EMBER_CLI_SRC = os.path.join(EXEC_ROOT, "tools", "ember-cli", "src")
CORE_DIR = os.path.join(EMBER_CLI_SRC, "core")
REPL_SCRIPT = os.path.join(CORE_DIR, "ember-world-state-repl.ts")
PTY_DRIVER = os.path.join(EXEC_ROOT, "scripts", "ember_surface2_pty_driver.cjs")
THIS_SCRIPT = os.path.abspath(__file__)

SCRATCH_ROOT = os.environ.get("EMBER_IND3_SCRATCH", os.path.join(EXEC_ROOT, "scratch", "ind3"))
NODE_PTY_MODULE = os.environ.get("EMBER_PTY_MODULE", "")
NODE_EXE = os.environ.get("EMBER_NODE_EXE", "C:/nvm4w/nodejs/node.exe")
POWERSHELL_EXE = os.environ.get("EMBER_POWERSHELL_EXE", "powershell.exe")

EXEC_RECEIPTS_DIR = os.path.join(EXEC_ROOT, "receipts", "ind3-operate-cure")
GOALFORGE_RECEIPTS_DIR = os.path.join(GOALFORGE_ROOT, "receipts", "ind3-operate-cure")
TICKET = "EMBER-C-IND-IND3-OPERATE-CURE"


def sha256_of(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_of_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def strip_ansi(s: str) -> str:
    return re.sub(r"\x1b\[[0-9;?]*[a-zA-Z]|\x1b\][^\x07]*\x07", "", s)


def git_head(repo_dir: str):
    try:
        sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_dir, capture_output=True, text=True, timeout=10).stdout.strip()
        subj = subprocess.run(["git", "log", "-1", "--format=%s"], cwd=repo_dir, capture_output=True, text=True, timeout=10).stdout.strip()
        return sha, subj
    except Exception as exc:
        return None, str(exc)


def _redact(value):
    if isinstance(value, str):
        out = value.replace(SCRATCH_ROOT, "<scratchpad>").replace(SCRATCH_ROOT.replace("\\", "/"), "<scratchpad>")
        out = re.sub(r"B--M-[A-Za-z0-9-]+", "<session>", out)
        out = re.sub(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", "<session>", out)
        return out
    if isinstance(value, list):
        return [_redact(v) for v in value]
    if isinstance(value, dict):
        return {k: _redact(v) for k, v in value.items()}
    return value


def read_jsonl(path):
    if not os.path.isfile(path):
        return []
    rows = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                pass
    return rows


def powershell_process_snapshot(pid: int):
    """Distinct capture command (NEVER the ember process itself): asks the OS, via a
    separate powershell.exe subprocess, whether `pid` (and any node.exe process at all,
    for a broader orphan sweep) is currently alive. Returns (raw_stdout, survivors_list)."""
    ps_cmd = (
        f"$byPid = Get-Process -Id {pid} -ErrorAction SilentlyContinue | "
        "Select-Object Id,ProcessName,StartTime | ConvertTo-Json -Compress; "
        "$allNode = Get-Process -Name node -ErrorAction SilentlyContinue | "
        "Select-Object Id,ProcessName | ConvertTo-Json -Compress; "
        "Write-Output \"BYPID_START\"; Write-Output $byPid; Write-Output \"BYPID_END\"; "
        "Write-Output \"ALLNODE_START\"; Write-Output $allNode; Write-Output \"ALLNODE_END\""
    )
    proc = subprocess.run(
        [POWERSHELL_EXE, "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
        capture_output=True, text=True, timeout=30,
    )
    raw = proc.stdout
    survivors = []
    m = re.search(r"BYPID_START\s*(.*?)\s*BYPID_END", raw, re.DOTALL)
    by_pid_json = m.group(1).strip() if m else ""
    if by_pid_json:
        try:
            obj = json.loads(by_pid_json)
            if obj:
                survivors.append(obj)
        except Exception:
            pass
    return raw, survivors


def run_repl_session(name, cwd_dir, outdir, encounter_log, snapshot_path, steps, deadline_ms, env_extra=None):
    env_overrides = {
        "EMBER_GOALFORGE_ROOT": GOALFORGE_ROOT,
        "EMBER_COBS_WORLDSTATE_SNAPSHOT": snapshot_path,
        "EMBER_COBS_ENCOUNTER_LOG": encounter_log,
    }
    if env_extra:
        env_overrides.update(env_extra)
    scenario = {
        "exe": NODE_EXE,
        "args": [REPL_SCRIPT],
        "env": env_overrides,
        "cwd": cwd_dir,
        "outdir": outdir,
        "name": name,
        "cols": 100,
        "rows": 30,
        "deadline_ms": deadline_ms,
        "steps": steps,
    }
    scenario_path = os.path.join(SCRATCH_ROOT, f"scenario-{name}.json")
    with open(scenario_path, "w", encoding="utf-8") as fh:
        json.dump(scenario, fh, indent=1)

    env = dict(os.environ)
    if not NODE_PTY_MODULE:
        raise SystemExit("EMBER_PTY_MODULE env var is required (no default baked in)")
    env["EMBER_PTY_MODULE"] = NODE_PTY_MODULE

    start_ts = datetime.now(timezone.utc)
    proc = subprocess.run(
        [NODE_EXE, PTY_DRIVER, scenario_path],
        cwd=SCRATCH_ROOT, env=env, capture_output=True, text=True, timeout=60,
    )
    print(f"[ind3:{name}] driver stdout:", proc.stdout.strip())
    if proc.returncode != 0:
        print(f"[ind3:{name}] driver stderr:", proc.stderr.strip())

    driver_receipt_path = os.path.join(outdir, f"{name}.driver-receipt.json")
    with open(driver_receipt_path, "r", encoding="utf-8") as fh:
        driver_result = json.load(fh)
    end_ts = datetime.now(timezone.utc)

    raw_path = os.path.join(outdir, f"{name}.raw")
    transcript_clean = ""
    if os.path.isfile(raw_path):
        with open(raw_path, "r", encoding="utf-8", errors="replace") as fh:
            transcript_clean = strip_ansi(fh.read())

    return {
        "name": name,
        "pid": driver_result.get("pid"),
        "driver_result": driver_result,
        "start_ts": start_ts.isoformat().replace("+00:00", "Z"),
        "end_ts": end_ts.isoformat().replace("+00:00", "Z"),
        "transcript_clean": transcript_clean,
        "outdir": outdir,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    for required in (REPL_SCRIPT, PTY_DRIVER):
        if not os.path.isfile(required):
            print(f"GAP: {required} not found -- aborting.")
            return 1

    os.makedirs(SCRATCH_ROOT, exist_ok=True)
    state_dir = os.path.join(SCRATCH_ROOT, "state")
    os.makedirs(state_dir, exist_ok=True)

    if args.dry_run:
        print("[ind3] --dry-run: preconditions OK, skipping capture")
        return 0

    now = datetime.now(timezone.utc)
    ts_compact = now.strftime("%Y%m%dT%H%M%S") + "Z"
    cr = "\r"

    # =====================================================================
    # LEG 1+2: LAUNCH (session A) + graceful stop -> TEARDOWN capture
    # =====================================================================
    enc_a = os.path.join(state_dir, "encounters-a.jsonl")
    snap_a = os.path.join(state_dir, "snapshot-a.json")
    if os.path.isfile(enc_a):
        os.remove(enc_a)
    cwd_a = os.path.join(SCRATCH_ROOT, "cwd-a")
    outdir_a = os.path.join(SCRATCH_ROOT, "driver-out-a")

    steps_a = [
        {"at_ms": 1500, "input": "monitor"}, {"at_ms": 1900, "input": cr},
        {"at_ms": 3000, "input": "understand"}, {"at_ms": 3400, "input": cr},
        {"at_ms": 4500, "input": "interact"}, {"at_ms": 4900, "input": cr},
        {"at_ms": 6000, "input": "act interact 0"}, {"at_ms": 6400, "input": cr},
        {"at_ms": 7500, "input": "confirm off-1"}, {"at_ms": 7900, "input": cr},
        {"at_ms": 9000, "input": "quit"}, {"at_ms": 9400, "input": cr},
    ]
    print("[ind3] side effect: LEG launch -- opening a visible ConPTY window running "
          "node core/ember-world-state-repl.ts for ~11s (no GPU, no training process touched), "
          "graceful `quit`-driven stop")
    session_a = run_repl_session("ind3-session-a-launch", cwd_a, outdir_a, enc_a, snap_a, steps_a, 11000)
    pid_a = session_a["pid"]
    exit_a = session_a["driver_result"].get("exit")
    launch_clean_exit = exit_a is not None and exit_a.get("exitCode") == 0 and not session_a["driver_result"].get("killed_at_deadline")

    encounters_a = read_jsonl(enc_a)
    real_state_produced = os.path.isfile(snap_a) and len(encounters_a) >= 2  # offer + confirmed outcome

    # --- distinct, independent teardown capture: AFTER session A's process has exited ---
    # small settle delay so the OS has definitely reaped the process before we query it
    time.sleep(1.5)
    teardown_capture_ts = datetime.now(timezone.utc)
    raw_ps, survivors = powershell_process_snapshot(pid_a) if pid_a else ("no pid recorded", [])

    launch_receipt = {
        "receipt_class": "IND-3",
        "leg": "launch",
        "ticket": TICKET,
        "ts": now.isoformat().replace("+00:00", "Z"),
        "verb": "activate",
        "doc_pointer": "docs/operator/activate.md",
        "documented_boot_command": "cd tools/ember-cli/src && node core/ember-world-state-repl.ts",
        "cockpit_process": "node core/ember-world-state-repl.ts (standalone, node-type-stripped, no exe rebuild -- same proven process as the C-OBS capture)",
        "pid_cohort": [pid_a],
        "clean_exit": launch_clean_exit,
        "real_state_produced": {
            "world_state_snapshot_written": os.path.isfile(snap_a),
            "encounter_log_row_count": len(encounters_a),
            "encounter_log_rows": encounters_a,
            "produced_via_documented_commands": ["monitor", "understand", "interact", "act interact 0", "confirm off-1"],
        },
        "rendered_frame_evidence": {
            "transcript_excerpt": session_a["transcript_clean"][-800:] if session_a["transcript_clean"] else None,
        },
        "documented_stop_command": "quit  (or: exit -- both registered, graceful readline close -> process.exit(0))",
        "driver_result": session_a["driver_result"],
        "live_process_touched": False,
        "gpu_used": False,
    }

    teardown_receipt = {
        "receipt_class": "IND-3",
        "leg": "teardown",
        "ticket": TICKET,
        "ts": teardown_capture_ts.isoformat().replace("+00:00", "Z"),
        "verb": "deactivate",
        "doc_pointer": "docs/operator/activate.md",
        "capture_command": "powershell.exe -NoProfile -NonInteractive -Command \"Get-Process -Id <pid> ... ; Get-Process -Name node ...\" (a DISTINCT process, invoked by this harness script -- never the ember cockpit process itself, matching the falsifier invalid_teardown_self_reported)",
        "capture_is_distinct_process": True,
        "capture_ts_after_stop_exit_ts": {
            "stop_exit_ts": session_a["end_ts"],
            "capture_ts": teardown_capture_ts.isoformat().replace("+00:00", "Z"),
            "capture_strictly_after_exit": True,
        },
        "target_pid": pid_a,
        "post_stop_process_table": {
            "survivors": survivors,
            "orphaned_gpu_state": False,
            "orphaned_gpu_state_note": (
                "Trivially false, not GPU-inspected-and-found-empty: this cockpit process is "
                "CPU-only Node.js (core/ember-world-state-repl.ts never imports a CUDA/torch "
                "binding), so it cannot orphan GPU state. A live nvidia-smi compute-apps dump "
                "was deliberately NOT taken this session -- this task's scope rail is "
                "CPU/ConPTY-only and forbids touching the GPU or the concurrent training "
                "process, and nvidia-smi would surface that unrelated job's PID, which this "
                "receipt has no business reporting on."
            ),
            "raw_capture": raw_ps.strip(),
        },
        "driver_result_of_stopped_session": session_a["driver_result"],
        "live_process_touched": False,
        "gpu_used": False,
    }

    # =====================================================================
    # LEG 3: INTERRUPTED_RESUME -- session B (hard-killed) then session C (resume, same log)
    # =====================================================================
    enc_b = os.path.join(state_dir, "encounters-interrupt-resume.jsonl")
    if os.path.isfile(enc_b):
        os.remove(enc_b)
    snap_b1 = os.path.join(state_dir, "snapshot-b1.json")
    snap_b2 = os.path.join(state_dir, "snapshot-b2.json")
    cwd_b1 = os.path.join(SCRATCH_ROOT, "cwd-b1")
    outdir_b1 = os.path.join(SCRATCH_ROOT, "driver-out-b1")
    cwd_b2 = os.path.join(SCRATCH_ROOT, "cwd-b2")
    outdir_b2 = os.path.join(SCRATCH_ROOT, "driver-out-b2")

    # Session B: deliberately NO "quit" step -- the deadline elapses and the reused pty
    # driver's own proc.kill() force-stops it. This IS the interruption (not a graceful
    # shutdown): confirmed below via killed_at_deadline=true / non-zero-signal exit.
    steps_b1 = [
        {"at_ms": 1500, "input": "monitor"}, {"at_ms": 1900, "input": cr},
        {"at_ms": 3000, "input": "interact"}, {"at_ms": 3400, "input": cr},
        {"at_ms": 4500, "input": "act interact 0"}, {"at_ms": 4900, "input": cr},
        {"at_ms": 6000, "input": "confirm off-1"}, {"at_ms": 6400, "input": cr},
    ]
    print("[ind3] side effect: LEG interrupted_resume/session-B -- opening a visible ConPTY "
          "window running node core/ember-world-state-repl.ts for ~7.5s, deliberately force-"
          "killed at deadline (no graceful quit) to simulate an interruption (no GPU touched)")
    session_b = run_repl_session("ind3-session-b-interrupt", cwd_b1, outdir_b1, enc_b, snap_b1, steps_b1, 7500)
    interrupted = bool(session_b["driver_result"].get("killed_at_deadline"))

    # settle so the OS + filesystem are quiescent before reading the "pre-interrupt" state
    time.sleep(1.0)
    pre_rows = read_jsonl(enc_b)
    with open(enc_b, "rb") as fh:
        pre_bytes = fh.read()
    pre_interrupt_row_count = len(pre_rows)
    pre_interrupt_checkpoint_hash = sha256_of_bytes(pre_bytes)

    # settle so the interrupted process's PID is fully reaped before the distinct capture
    time.sleep(1.0)
    raw_ps_b, survivors_b = powershell_process_snapshot(session_b["pid"]) if session_b["pid"] else ("no pid recorded", [])

    # Session C: fresh process, SAME encounter-log file path -- the resume leg.
    steps_c = [
        {"at_ms": 1500, "input": "interact"}, {"at_ms": 1900, "input": cr},
        {"at_ms": 3000, "input": "act interact 0"}, {"at_ms": 3400, "input": cr},
        {"at_ms": 4500, "input": "confirm off-1"}, {"at_ms": 4900, "input": cr},
        {"at_ms": 6000, "input": "quit"}, {"at_ms": 6400, "input": cr},
    ]
    print("[ind3] side effect: LEG interrupted_resume/session-C -- relaunching node "
          "core/ember-world-state-repl.ts pointed at the SAME encounter log file to prove "
          "state continuity across the interrupt, then a graceful `quit`")
    session_c = run_repl_session("ind3-session-c-resume", cwd_b2, outdir_b2, enc_b, snap_b2, steps_c, 8000)

    post_rows = read_jsonl(enc_b)
    with open(enc_b, "rb") as fh:
        post_bytes = fh.read()
    post_resume_row_count = len(post_rows)
    prefix_identical = post_bytes[:len(pre_bytes)] == pre_bytes
    no_gap = post_resume_row_count >= pre_interrupt_row_count

    interrupted_resume_receipt = {
        "receipt_class": "IND-3",
        "leg": "interrupted_resume",
        "ticket": TICKET,
        "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "verb": "activate + deactivate (interrupted case)",
        "doc_pointer": "docs/operator/activate.md",
        "interrupt_mechanism": {
            "summary": "session B received NO documented `quit` command; the reused pty driver's own deadline-based proc.kill() force-stopped it -- a real interruption, not a graceful shutdown.",
            "killed_at_deadline": interrupted,
            "driver_exit": session_b["driver_result"].get("exit"),
            "pid": session_b["pid"],
            "post_interrupt_process_table": {
                "survivors": survivors_b,
                "raw_capture": raw_ps_b.strip(),
            },
        },
        "pre_interrupt_checkpoint": {
            "encounter_log_path": os.path.relpath(enc_b, EXEC_ROOT).replace(os.sep, "/"),
            "row_count": pre_interrupt_row_count,
            "sha256_of_bytes_on_disk_at_capture": pre_interrupt_checkpoint_hash,
            "captured_from": "the persisted file on disk, read AFTER the hard-kill by this harness script -- not self-reported by the killed process",
        },
        "resume_mechanism": {
            "summary": "a FRESH node core/ember-world-state-repl.ts process, pointed at the SAME EMBER_COBS_ENCOUNTER_LOG file path, produces additional real appendFile-written rows, then a graceful `quit`.",
            "resumed_pid": session_c["pid"],
            "resumed_clean_exit": session_c["driver_result"].get("exit", {}).get("exitCode") == 0 and not session_c["driver_result"].get("killed_at_deadline"),
        },
        "post_resume_state": {
            "row_count": post_resume_row_count,
            "no_gap": no_gap,
            "prefix_identical_to_pre_interrupt": prefix_identical,
            "continuity_verified": bool(no_gap and prefix_identical and post_resume_row_count > pre_interrupt_row_count),
        },
        "live_process_touched": False,
        "gpu_used": False,
    }

    # =====================================================================
    # Assemble + write receipts (execution tree, then import-editions into goalforge)
    # =====================================================================
    exec_head_sha, exec_head_subj = git_head(EXEC_ROOT)
    goalforge_head_sha, goalforge_head_subj = git_head(GOALFORGE_ROOT)

    exec_receipt_dir = os.path.join(EXEC_RECEIPTS_DIR, ts_compact)
    os.makedirs(exec_receipt_dir, exist_ok=True)

    all_three = {
        "launch": launch_receipt,
        "teardown": teardown_receipt,
        "interrupted_resume": interrupted_resume_receipt,
    }

    written_paths = {}
    for leg_name, receipt in all_three.items():
        receipt["generator"] = {"path": "src/ember/governance/scripts/ember_ind3_operate_capture.py", "sha256": sha256_of(THIS_SCRIPT)}
        receipt["sha_convention"] = "bytes on disk as-is (binary read, no line-ending normalization)"
        p = os.path.join(exec_receipt_dir, f"{leg_name}.json")
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(_redact(receipt), fh, indent=1)
        written_paths[leg_name] = p
        print(f"[ind3] wrote execution-tree {leg_name} receipt: {p}")

    # copy supporting artifacts (encounter logs, snapshots, transcripts) into the exec receipt dir
    for src_name, src_path in [
        ("encounters-a.jsonl", enc_a), ("snapshot-a.json", snap_a),
        ("encounters-interrupt-resume.jsonl", enc_b),
        ("snapshot-b1.json", snap_b1), ("snapshot-b2.json", snap_b2),
    ]:
        if os.path.isfile(src_path):
            shutil.copyfile(src_path, os.path.join(exec_receipt_dir, src_name))

    for sess in (session_a, session_b, session_c):
        tpath = os.path.join(exec_receipt_dir, f"terminal-transcript-{sess['name']}.txt")
        with open(tpath, "w", encoding="utf-8") as fh:
            fh.write(_redact(sess["transcript_clean"]))

    # --- import-editions into goalforge (byte-preserved original + import_provenance) ---
    goalforge_dirname = ts_compact + "-import-edition"
    goalforge_receipt_dir = os.path.join(GOALFORGE_RECEIPTS_DIR, goalforge_dirname)
    os.makedirs(goalforge_receipt_dir, exist_ok=True)

    import_paths = {}
    for leg_name, exec_path in written_paths.items():
        original_sha256 = sha256_of(exec_path)
        with open(exec_path, "r", encoding="utf-8") as fh:
            original_obj = json.load(fh)
        import_edition = dict(original_obj)
        import_edition["import_provenance"] = {
            "imported_into": f"{GOALFORGE_ROOT} (contract tree)",
            "source_tree": f"{EXEC_ROOT} (execution tree)",
            "source_commit_sha": exec_head_sha,
            "source_commit_subject": exec_head_subj,
            "goalforge_head_at_import": goalforge_head_sha,
            "goalforge_head_subject_at_import": goalforge_head_subj,
            "original_receipt_path": os.path.relpath(exec_path, EXEC_ROOT).replace(os.sep, "/"),
            "original_receipt_sha256": original_sha256,
            "copy_method": "byte-identical copy of the receipt JSON content -- every original key/value unchanged; only 'import_provenance' added as a new top-level key",
            "original_receipt_edited": False,
            "note": f"Original source file at {EXEC_ROOT} was NOT edited (read-only per task rail); this is a new file in the goalforge tree.",
        }
        goalforge_path = os.path.join(goalforge_receipt_dir, f"{leg_name}.json")
        with open(goalforge_path, "w", encoding="utf-8") as fh:
            json.dump(import_edition, fh, indent=1)
        import_paths[leg_name] = goalforge_path
        print(f"[ind3] wrote goalforge import-edition {leg_name} receipt: {goalforge_path}")

        # flat single-file convention (matches ind1's flat placement + the c-port precedent)
        flat_path = os.path.join(GOALFORGE_ROOT, "receipts", f"ind3-{leg_name}-{ts_compact}-import-edition.json")
        with open(flat_path, "w", encoding="utf-8") as fh:
            json.dump(import_edition, fh, indent=1)
        print(f"[ind3] wrote flat import-edition: {flat_path}")

    for src_name, src_path in [
        ("encounters-a.jsonl", enc_a), ("snapshot-a.json", snap_a),
        ("encounters-interrupt-resume.jsonl", enc_b),
    ]:
        if os.path.isfile(src_path):
            shutil.copyfile(src_path, os.path.join(goalforge_receipt_dir, src_name))

    summary = {
        "launch_clean_exit": launch_clean_exit,
        "real_state_produced": real_state_produced,
        "teardown_survivors": survivors,
        "interrupted": interrupted,
        "continuity_verified": interrupted_resume_receipt["post_resume_state"]["continuity_verified"],
        "written": written_paths,
        "imported": import_paths,
    }
    print(json.dumps(summary, indent=1, default=str))

    ok = (
        launch_clean_exit and real_state_produced and not survivors and interrupted
        and interrupted_resume_receipt["post_resume_state"]["continuity_verified"]
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
