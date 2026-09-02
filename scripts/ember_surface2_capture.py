#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""ember_surface2_capture.py -- Surface-2 capture harness (Phase A, issue #22;
live mode added per issue #140, "replay provenance is the named defect").

Two modes, selected by `--mode {replay,live}` (default: replay, kept for
history/back-compat only -- see the REPLAY MODE IS INVALID note below):

REPLAY MODE (original, Phase A): read-only w.r.t. the live GPU training
process. Reads a REAL COMPLETED run's material (attempt-13's live receipt +
console log + a checkpoint-eval dry-run receipt, all under
receipts/ember-c14-owned-run/), converts the real step telemetry into the
telemetry-watch.ts event schema, and replays it through the REAL render path:
a separate ember-cured.exe cockpit process, spawned in a visible ConPTY (never
headless), pointed at a REPLAY-ONLY channel file via EMBER_TELEMETRY_PATH so
the live channel (state/ember-telemetry.jsonl) is never touched.

REPLAY MODE IS INVALID FOR THE C-SURFACE2 BOARD (do not use it to try to clear
that condition). Confirmed two ways: (1) issue #140 (filed by the repo
maintainer, not an agent): "the condition demands a CURRENTLY-LIVE process
receipt", replay receipts get invalid_surface2_non_live_provenance;
(2) src/ember/governance/scripts/ember_totality/test_surface2.py's own CHK, cure #3 (issue #97),
already hard-rejects any receipt whose `provenance` is in
NON_LIVE_PROVENANCE_MARKERS (which includes `replay_of_completed_run`, this
mode's own provenance value) or whose `live_process_touched` is `False` (which
this mode always sets). Every replay-mode receipt this script writes now
self-stamps `board_valid: false` with an `invalid_reason` pointing at both, so
the artifact is unmistakable even read in isolation. Kept only so the
Phase A capture technique (hydrate real console-log progress -> replay
JSONL -> real render path -> real /finetune command) is not lost; do not wire
it into any board-clearing workflow.

LIVE MODE (issue #140's prescribed cure -- "instrument, don't fabricate"):
never replays anything. `find_active_live_run()` tails the REAL live
telemetry channel (state/ember-telemetry.jsonl, same path + 30s active-run TTL
as tools/ember-cli/src/services/telemetry-watch.ts's ACTIVE_RUN_TTL_MS) for a
`train_step` event fresh enough to prove a governed run is running RIGHT NOW.
If none is found, live mode REFUSES (nonzero exit, no receipt written, no
process spawned) rather than ever inventing a live_run receipt -- proved by
`--selftest` (stubbed-absent and stubbed-stale cases both refuse; a stubbed-
fresh case is correctly detected). If an active run IS found, live mode spawns
ember-cured.exe with NO EMBER_TELEMETRY_PATH override (so it watches the real
live channel), fires one real `/finetune pause <runId>` followed by one real
`/finetune resume <runId>` against that run's real runId through the real
registered slash command (commands/finetune.ts -> services/finetune-control.ts
-> validateControlCmd/emitControlCmd, schema-checked, non-fabricated -- pause
immediately followed by resume so a real capture leaves the run's state
unchanged), and stamps `provenance: "live_run"`, `live_process_touched: true`.
metrics_delta is the real observed step advance between the pre- and post-
capture live-channel reads; if that delta is not a real positive number, live
mode reports the GAP and refuses to write a receipt rather than fabricate one.

This file's own CLI execution is scoped to `--selftest` only (stubbed
tempdir fixtures, no live run, no exe, no ConPTY) -- landing a code-only
capability per issue #140's "CPU-preparable: the capture harness; execution
rides the next governed run." Nothing in this PR claims a real live capture
happened.

Usage: python ember_surface2_capture.py --mode live [--dry-run]
       python ember_surface2_capture.py --mode replay [--dry-run]   # invalid for the board, see above
       python ember_surface2_capture.py --selftest

Provenance: landed from stage dryrun-20260704T211712Z (ember issue #210 Tier 2)
with a portability fix over the staged original -- EXEC_ROOT carried an
absolute drive-letter-rooted literal, which tripped the repo's leak-gate on
the path shape and was non-functional off the export machine either way. Now
computes from __file__ (functionally identical: this file's grandparent
directory is the repo root). No other lines changed.
See receipts/ember-c-scale/land210f-*. Live mode added per issue #140.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

EXEC_ROOT = str(Path(__file__).resolve().parent.parent)
C14_DIR = os.path.join(EXEC_ROOT, "receipts", "ember-c14-owned-run")
SURFACE_DIR = os.path.join(EXEC_ROOT, "receipts", "ember-surface2-telemetry")
EMBER_CLI_SRC = os.path.join(EXEC_ROOT, "tools", "ember-cli", "src")
EMBER_EXE = os.path.join(EMBER_CLI_SRC, "ember-cured.exe")
PTY_DRIVER = os.path.join(EXEC_ROOT, "scripts", "ember_surface2_pty_driver.cjs")

LIVE_RECEIPT = os.path.join(C14_DIR, "live-20260703T053114Z.json")
CONSOLE_LOG = os.path.join(C14_DIR, "attempt13-console.log")
DRYRUN_RECEIPT = os.path.join(C14_DIR, "dry-run-20260703T054201Z.json")

# --- live mode -----------------------------------------------------------
# Same path + freshness window tools/ember-cli/src/services/telemetry-watch.ts
# uses to decide a run is "active" (DEFAULT_CHANNEL_PATH, ACTIVE_RUN_TTL_MS):
# repo-root-relative "state/ember-telemetry.jsonl", written by the real
# training-side runner (scripts/run_vertical_slice.py's --telemetry-path arg),
# 30s TTL. Reusing the exact path + window means "is a run active" answers the
# identical question the cockpit's own watcher answers, not a second drifting
# copy of that judgment.
LIVE_CHANNEL_PATH = os.path.join(EXEC_ROOT, "state", "ember-telemetry.jsonl")
ACTIVE_RUN_TTL_S = 30.0

NON_LIVE_PROVENANCE_MARKERS = {
    "replay_of_completed_run", "replay", "reconstructed", "backfilled",
    "synthetic_replay", "post_hoc_replay",
}

# Short, non-identifying default: ConPTY transcripts wrap long paths across
# render columns, defeating substring redaction -- a short neutral working
# root means the transcript never contains anything identifying to redact.
SCRATCH_ROOT = os.environ.get(
    "EMBER_SURFACE2_SCRATCH", os.path.join(EXEC_ROOT, "scratch", "s2cap")
)
# node-pty resolution is env-only (no default path baked into the tree).
NODE_PTY_MODULE = os.environ.get("EMBER_PTY_MODULE", "")

REPLAY_RUN_ID = "c14-attempt13-replay"

PROGRESS_RE = re.compile(
    r"\[live progress\]\s+steps_completed=(\d+)\s+last_step_wall_s=([\d.]+)\s+median_s_per_step=([\d.]+)"
)


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def dash_ts(dt):
    # matches the sibling receipt-dir naming convention: 2026-06-28T04-08-08Z
    return dt.strftime("%Y-%m-%dT%H-%M-%S") + "Z"


def _parse_event_ts(ts):
    """Parse a telemetry event's `ts` (ISO8601, 'Z' or offset suffix) to an
    aware datetime, or None if unparseable/absent. Never raises."""
    if not isinstance(ts, str) or not ts.strip():
        return None
    s = ts.strip()
    try:
        s2 = s[:-1] + "+00:00" if s.endswith("Z") else s
        dt = datetime.fromisoformat(s2)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def find_active_live_run(channel_path, ttl_s=ACTIVE_RUN_TTL_S, now=None):
    """Tails `channel_path` (telemetry-watch.ts JSONL schema: {ts, kind,
    source, payload}) for the newest `train_step` event and reports whether it
    is fresh enough to prove a governed run is running RIGHT NOW.

    Returns {"run_id": str, "step": int|None, "ts": str} for the newest
    train_step event if `now - ts <= ttl_s`, else None -- covers: channel
    missing, channel empty, no train_step events, newest train_step event
    stale, or a malformed run_id. NEVER raises; a read/parse failure on any
    one line is skipped, not fatal (mirrors telemetry-watch.ts tolerating
    partial/corrupt lines from a live writer). Reads the whole file (this
    channel is capped in practice by the training loop's own cadence; no
    tail-by-byte-offset optimization needed for a one-shot capture check)."""
    if not os.path.isfile(channel_path):
        return None
    now = now or datetime.now(timezone.utc)
    newest = None  # (dt, run_id, step)
    try:
        with open(channel_path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except Exception:
                    continue
                if not isinstance(ev, dict) or ev.get("kind") != "train_step":
                    continue
                dt = _parse_event_ts(ev.get("ts"))
                if dt is None:
                    continue
                payload = ev.get("payload")
                run_id = payload.get("run_id") if isinstance(payload, dict) else None
                if not isinstance(run_id, str) or not run_id:
                    continue
                step = payload.get("step") if isinstance(payload, dict) else None
                if newest is None or dt > newest[0]:
                    newest = (dt, run_id, step)
    except OSError:
        return None
    if newest is None:
        return None
    dt, run_id, step = newest
    age_s = (now - dt).total_seconds()
    if age_s < 0 or age_s > ttl_s:
        return None
    return {"run_id": run_id, "step": step, "ts": dt.isoformat().replace("+00:00", "Z")}


def parse_console_progress(path):
    """Extracts real [live progress] step lines from attempt13-console.log.
    Returns list of dict(steps_completed, last_step_wall_s, median_s_per_step)
    in file order -- these are REAL numbers reported by the real GPU training
    run, not fabricated."""
    rows = []
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            m = PROGRESS_RE.search(line)
            if m:
                rows.append({
                    "steps_completed": int(m.group(1)),
                    "last_step_wall_s": float(m.group(2)),
                    "median_s_per_step": float(m.group(3)),
                })
    return rows


def build_replay_channel(progress_rows, out_path):
    """Writes telemetry-watch.ts-schema JSONL events for each real console-log
    progress line. kind=train_step, payload={run_id, step, step_ms}; no loss/
    total_steps fields since the source console log carries neither (never
    fabricated). Returns the list of event dicts written."""
    events = []
    base = datetime.now(timezone.utc)
    for i, row in enumerate(progress_rows):
        ev = {
            "ts": (base + timedelta(milliseconds=i)).isoformat().replace("+00:00", "Z"),
            "kind": "train_step",
            "source": "ember_surface2_capture_replay",
            "payload": {
                "run_id": REPLAY_RUN_ID,
                "step": row["steps_completed"],
                "step_ms": round(row["last_step_wall_s"] * 1000, 1),
            },
        }
        events.append(ev)
    with open(out_path, "w", encoding="utf-8") as fh:
        for ev in events:
            fh.write(json.dumps(ev) + "\n")
    return events


def strip_ansi(s):
    return re.sub(r"\x1b\[[0-9;?]*[a-zA-Z]|\x1b\][^\x07]*\x07", "", s)


def _redact(text):
    """Replace the session scratchpad root (environment-assigned absolute path,
    which embeds session/founder-identifying directory names) with a neutral
    token in anything written into a receipt. Paths stay fully real on disk
    and in the console; only the receipt's persisted copies are redacted."""
    if isinstance(text, str):
        out = text.replace(SCRATCH_ROOT, "<scratchpad>").replace(SCRATCH_ROOT.replace("\\", "/"), "<scratchpad>")
        # ConPTY transcripts wrap long paths across render columns, breaking
        # the exact-substring match above -- additionally redact the
        # session-identifying tokens wherever they survive intact.
        # Session directory names under the OS temp root follow
        # <mangled-project-dir> + <uuid>; both are session-identifying.
        out = re.sub(r"B--M-[A-Za-z0-9-]+", "<session>", out)
        out = re.sub(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", "<session>", out)
        return out
    if isinstance(text, list):
        return [_redact(x) for x in text]
    if isinstance(text, dict):
        return {k: _redact(v) for k, v in text.items()}
    return text


def run_replay_capture(args):
    """Phase A replay capture. INVALID FOR THE C-SURFACE2 BOARD -- see module
    docstring. Kept for the historical technique only; every receipt it
    writes self-stamps board_valid=false."""
    if not os.path.isfile(EMBER_EXE):
        print(f"GAP: {EMBER_EXE} not found -- binary would need building, which this harness is forbidden from doing. Aborting.")
        sys.exit(1)

    os.makedirs(SCRATCH_ROOT, exist_ok=True)
    cwd_dir = os.path.join(SCRATCH_ROOT, "cwd")
    outdir = os.path.join(SCRATCH_ROOT, "driver-out")
    os.makedirs(cwd_dir, exist_ok=True)
    os.makedirs(outdir, exist_ok=True)
    # emitControlCmd() uses fs.appendFile on a CWD-relative path and does NOT create
    # missing parent dirs -- pre-create it or the real /finetune command errors ENOENT
    # (found empirically: first capture attempt hit exactly this).
    os.makedirs(os.path.join(cwd_dir, "state"), exist_ok=True)

    # --- provenance: sha256 of the three real source files -------------------
    source_run = {
        "provenance": "replay_of_completed_run",
        "attempt": "attempt13",
        "sources": {
            "live_receipt": {
                "path": os.path.relpath(LIVE_RECEIPT, EXEC_ROOT).replace(os.sep, "/"),
                "sha256": sha256_of(LIVE_RECEIPT),
            },
            "console_log": {
                "path": os.path.relpath(CONSOLE_LOG, EXEC_ROOT).replace(os.sep, "/"),
                "sha256": sha256_of(CONSOLE_LOG),
            },
            "checkpoint_eval_dry_run_receipt": {
                "path": os.path.relpath(DRYRUN_RECEIPT, EXEC_ROOT).replace(os.sep, "/"),
                "sha256": sha256_of(DRYRUN_RECEIPT),
            },
        },
    }

    with open(DRYRUN_RECEIPT, "r", encoding="utf-8") as fh:
        dryrun_data = json.load(fh)

    progress_rows = parse_console_progress(CONSOLE_LOG)
    print(f"[capture] parsed {len(progress_rows)} real [live progress] lines from attempt13-console.log")
    for r in progress_rows:
        print(f"  steps_completed={r['steps_completed']} last_step_wall_s={r['last_step_wall_s']} median_s_per_step={r['median_s_per_step']}")

    replay_channel_path = os.path.join(SCRATCH_ROOT, "replay-telemetry-channel.jsonl")
    events = build_replay_channel(progress_rows, replay_channel_path)
    final_step = progress_rows[-1]["steps_completed"] if progress_rows else 0
    print(f"[capture] wrote {len(events)} replay train_step events to {replay_channel_path} (final step={final_step})")

    checkpoint_evals = dryrun_data.get("checkpoint_evals", [])
    metrics_delta = final_step  # real steps_completed delta (0 -> final_step) from the replayed attempt-13 run

    if args.dry_run:
        print("[capture] --dry-run: skipping PTY capture")
        driver_result = {"skipped": True}
        transcript_clean = ""
        control_events = []
    else:
        cr = "\r"
        ctrl_c = "\x03"
        scenario = {
            "exe": EMBER_EXE,
            "args": [],
            "env": {
                "EMBER_MODEL_URL": "http://127.0.0.1:9",  # unreachable -- no GPU inference spawn
                "EMBER_TELEMETRY_PATH": replay_channel_path,
            },
            "outdir": outdir,
            "cwd": cwd_dir,
            "name": "surface2-replay-capture",
            "cols": 100,
            "rows": 30,
            "deadline_ms": 13000,
            "steps": [
                {"at_ms": 5000, "input": f"/finetune pause {REPLAY_RUN_ID}"},
                {"at_ms": 5400, "input": cr},
                # explicit-path form (AC3): bare "/watch" falls back to watch.ts's own
                # DEFAULT_CHANNEL_PATH reference (the LIVE channel), NOT the
                # EMBER_TELEMETRY_PATH override -- found empirically on the first capture
                # attempt. Pass the replay channel path explicitly so the singleton
                # watcher stays pointed at replay data, never the live training channel.
                {"at_ms": 7500, "input": f"/watch {replay_channel_path}"},
                {"at_ms": 7900, "input": cr},
                {"at_ms": 10500, "input": ctrl_c},
                {"at_ms": 12000, "input": ctrl_c},
            ],
        }
        scenario_path = os.path.join(SCRATCH_ROOT, "scenario.json")
        with open(scenario_path, "w", encoding="utf-8") as fh:
            json.dump(scenario, fh, indent=1)

        print("[capture] side effect: opening a visible ConPTY window running ember-cured.exe for ~14s (replay capture, no GPU, dead model endpoint) -- will close cleanly")
        env = dict(os.environ)
        if not NODE_PTY_MODULE:
            raise SystemExit("EMBER_PTY_MODULE env var is required (no default baked in)")
        env["EMBER_PTY_MODULE"] = NODE_PTY_MODULE
        proc = subprocess.run(
            ["node", PTY_DRIVER, scenario_path],
            cwd=SCRATCH_ROOT, env=env, capture_output=True, text=True, timeout=60,
        )
        print("[capture] driver stdout:", proc.stdout.strip())
        if proc.returncode != 0:
            print("[capture] driver stderr:", proc.stderr.strip())
            print(f"GAP: pty driver exited {proc.returncode}, aborting capture")
            sys.exit(1)

        driver_receipt_path = os.path.join(outdir, "surface2-replay-capture.driver-receipt.json")
        with open(driver_receipt_path, "r", encoding="utf-8") as fh:
            driver_result = json.load(fh)

        raw_path = os.path.join(outdir, "surface2-replay-capture.raw")
        with open(raw_path, "r", encoding="utf-8", errors="replace") as fh:
            raw = fh.read()
        transcript_clean = strip_ansi(raw)

        control_path = os.path.join(cwd_dir, "state", "ember-finetune-control.jsonl")
        control_events = []
        if os.path.isfile(control_path):
            with open(control_path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        control_events.append(json.loads(line))
                    except Exception:
                        pass
        print(f"[capture] control channel ({control_path}): {len(control_events)} event(s): {control_events}")

    # --- render-verified evidence ---------------------------------------------
    # The EXACT label telemetry-watch.ts's memo-key logic would produce for our
    # replayed active-run state (screens/repl.ts _telemetryMemoKey, "mirrors
    # status-bar formatTelemetryLabel"): "train r=<runId> step <final_step>"
    # (no VRAM segment -- this capture emits no governor event).
    expected_status_bar_label = f"train r={REPLAY_RUN_ID} step {final_step}"
    telemetry_status_bar_rendered = expected_status_bar_label in transcript_clean
    ack_rendered = "pause" in transcript_clean and f"run={REPLAY_RUN_ID}" in transcript_clean
    watching_rendered = "watching" in transcript_clean

    # KNOWN GAP (found empirically, source-verified -- not a probe-CHK requirement,
    # but load-bearing for anyone reading this receipt as "render proven"):
    # tools/ember-cli/src/screens/repl.ts polls the real telemetry-watch service
    # (startTelemetryWatch() on mount, getState() every 500ms into React state,
    # lines ~399-411) but NEVER passes that state to <StatusLine>: components/
    # status-bar.ts's StatusLineProps has no `telemetry` field, and the actual
    # React.createElement(StatusLine, {...}) call at repl.ts:771 only passes
    # permissionMode/interrupt/taskPanel/modelMetrics. The real ingest+poll+parse
    # code path genuinely runs against the replay channel (verified: the process
    # was launched with EMBER_TELEMETRY_PATH set to our replay file and
    # startTelemetryWatch() unconditionally starts on mount per the source read
    # this session), but there is no visible confirmation of it in the ConPTY
    # output and no external way to query getState() from outside the process.
    # This is a currently-existing wiring gap in ember-cli's TS source, not
    # something this harness can fix without a TS edit + exe rebuild (forbidden
    # by this harness's rails) -- reported as a gap, not routed around.
    known_gap_statusline_telemetry_unwired = not telemetry_status_bar_rendered

    events_ingest_attempted = len(events)  # written to the replay channel before boot; the real
    # telemetry-watch poll+parse path is unconditionally started (source-verified), so ingestion
    # was attempted against all of them, but see known_gap above for what could NOT be visually
    # confirmed.
    events_rendered = len(events) if telemetry_status_bar_rendered else 0

    render_evidence = {
        "expected_status_bar_label": expected_status_bar_label,
        "telemetry_status_bar_rendered": telemetry_status_bar_rendered,
        "finetune_pause_ack_in_transcript": ack_rendered,
        "watch_ack_in_transcript": watching_rendered,
    }

    # --- assemble control-channel sibling (clause b) --------------------------
    pause_event = None
    for ev in control_events:
        if ev.get("verb") == "pause" and ev.get("runId") == REPLAY_RUN_ID:
            pause_event = ev
            break

    now_final = datetime.now(timezone.utc)
    receipt_dirname = dash_ts(now_final)
    receipt_dir = os.path.join(SURFACE_DIR, receipt_dirname)
    os.makedirs(receipt_dir, exist_ok=True)

    control_sibling = None
    if pause_event is not None:
        control_sibling = dict(pause_event)
        # redundancy: independently CHK-passable if this sibling file, rather than
        # receipt.json, were ever picked as "newest" by the probe's ts comparison.
        control_sibling["metrics_delta"] = metrics_delta
        control_sibling_path = os.path.join(receipt_dir, "finetune-control-event.json")
        with open(control_sibling_path, "w", encoding="utf-8") as fh:
            json.dump(control_sibling, fh, indent=1)
        print(f"[capture] wrote control-channel sibling: {control_sibling_path}")
    else:
        print("GAP: no real pause control-channel event captured for runId="
              f"{REPLAY_RUN_ID} -- clause (b) will not be satisfiable without it")

    receipt = {
        "ts": now_final.isoformat().replace("+00:00", "Z"),
        "surface": "C-SURFACE2",
        "provenance": source_run["provenance"],
        "source_run": source_run,
        "replay_run_id": REPLAY_RUN_ID,
        "replay_channel_events": events,
        "events_ingest_attempted": events_ingest_attempted,
        "events_rendered": events_rendered,
        "render_evidence": render_evidence,
        "known_gap_statusline_telemetry_unwired": known_gap_statusline_telemetry_unwired,
        "known_gap_detail": (
            "tools/ember-cli/src/screens/repl.ts polls the real telemetry-watch "
            "service into React state (startTelemetryWatch() on mount + getState() "
            "every 500ms, ~lines 399-411) but never passes it to <StatusLine>: "
            "components/status-bar.ts's StatusLineProps has no `telemetry` field "
            "and the real React.createElement(StatusLine, {...}) call at "
            "repl.ts:771 omits it. Ingest is real and unconditionally started; "
            "visual confirmation of it is not currently possible through this "
            "binary. Not fixed here -- fixing requires a TS source edit + exe "
            "rebuild, outside this harness's rails (no binary rebuild)."
        ) if known_gap_statusline_telemetry_unwired else None,
        "checkpoint_evals_from_source": checkpoint_evals,
        "control_channel_event": control_sibling,
        "metrics_delta": metrics_delta,
        "metrics_delta_semantics": (
            "Real steps_completed delta (0 -> "
            f"{final_step}) parsed from attempt13-console.log's [live progress] lines "
            "of the REAL completed C14 attempt-13 GPU training run. This is a replay "
            "capture (no live model call happens during rendering), so this is NOT a "
            "live tokens_predicted delta -- it is the real, measured progress of the "
            "real training run being replayed, distinct from a canned/fixture marker."
        ),
        "render_path": {
            "binary": os.path.relpath(EMBER_EXE, EXEC_ROOT).replace(os.sep, "/"),
            "binary_sha256": sha256_of(EMBER_EXE),
            "cockpit": "visible ConPTY (useConpty:true), never headless",
            "telemetry_ingest": "tools/ember-cli/src/services/telemetry-watch.ts startTelemetryWatch()/getState(), auto-mounted in screens/repl.ts, channel overridden via EMBER_TELEMETRY_PATH env var pointed at the replay-only channel file (never the live state/ember-telemetry.jsonl)",
            "control_channel_writer": "tools/ember-cli/src/services/finetune-control.ts emitControlCmd() via the real registered /finetune slash command (commands/finetune.ts), schema-checked (validateControlCmd), not fabricated",
            "replay_channel_path": _redact(replay_channel_path),
        },
        "live_process_touched": False,
        "gpu_used": False,
        "driver_result": driver_result,
        "board_valid": False,
        "invalid_reason": (
            "REPLAY MODE IS INVALID FOR C-SURFACE2 (issue #140: 'the condition "
            "demands a CURRENTLY-LIVE process receipt'; scripts/ember_totality/"
            "test_surface2.py cure #3 hard-rejects provenance="
            "'replay_of_completed_run' via NON_LIVE_PROVENANCE_MARKERS and "
            "live_process_touched=false). This receipt proves the Phase A replay "
            "technique still works, nothing else. Use --mode live once a "
            "governed run is active."
        ),
    }

    receipt_path = os.path.join(receipt_dir, "receipt.json")
    with open(receipt_path, "w", encoding="utf-8") as fh:
        json.dump(_redact(receipt), fh, indent=1)
    print(f"[capture] wrote receipt: {receipt_path}")

    if not args.dry_run:
        transcript_path = os.path.join(receipt_dir, "terminal-transcript-clean.txt")
        with open(transcript_path, "w", encoding="utf-8") as fh:
            fh.write(_redact(transcript_clean))
        print(f"[capture] wrote transcript: {transcript_path}")

    print(json.dumps({
        "receipt_dir": receipt_dir,
        "receipt_path": receipt_path,
        "control_sibling_present": control_sibling is not None,
        "metrics_delta": metrics_delta,
        "events_rendered": events_rendered,
        "render_evidence": render_evidence,
    }, indent=1))
    return 0


def run_live_capture(args, live_channel_path=None, exec_root=None, surface_dir=None,
                      ember_exe=None, scratch_root=None):
    """Live mode per issue #140: instrument a REAL currently-running governed
    run, never replay one. Fail-closed at every step -- refuses (prints why,
    writes nothing, spawns nothing) rather than ever inventing a provenance=
    'live_run' receipt. Params after `args` are injection points for
    --selftest; production callers (main()) leave them at their EXEC_ROOT-
    derived defaults."""
    live_channel_path = live_channel_path or LIVE_CHANNEL_PATH
    exec_root = exec_root or EXEC_ROOT
    surface_dir = surface_dir or SURFACE_DIR
    ember_exe = ember_exe or EMBER_EXE
    scratch_root = scratch_root or SCRATCH_ROOT

    active = find_active_live_run(live_channel_path)
    if active is None:
        print(
            "REFUSED: no live governed run detected on "
            f"{os.path.relpath(live_channel_path, exec_root).replace(os.sep, '/')} "
            f"(no train_step event within {ACTIVE_RUN_TTL_S:.0f}s). Refusing to "
            "fabricate a provenance='live_run' receipt -- issue #140: 'instrument, "
            "don't fabricate'. Re-run once a governed run is active."
        )
        return 2

    print(f"[live] active run detected: run_id={active['run_id']!r} step={active['step']!r} ts={active['ts']}")

    if not os.path.isfile(ember_exe):
        print(f"GAP: {ember_exe} not found -- binary would need building, which this harness is forbidden from doing. Aborting.")
        return 1

    run_id = active["run_id"]
    pre_step = active["step"]

    cwd_dir = exec_root  # real repo root: state/ember-telemetry.jsonl and
    # state/ember-finetune-control.jsonl resolve to the REAL live paths here,
    # not a scratch copy -- this is the point of live mode.
    outdir = os.path.join(scratch_root, "live-driver-out")
    os.makedirs(outdir, exist_ok=True)

    if args.dry_run:
        print("[live] --dry-run: skipping PTY capture (no steer verb fired, no receipt written)")
        return 0

    cr = "\r"
    ctrl_c = "\x03"
    scenario = {
        "exe": ember_exe,
        "args": [],
        "env": {},  # deliberately no EMBER_MODEL_URL / EMBER_TELEMETRY_PATH override --
        # live mode watches the REAL channels at their real default paths.
        "outdir": outdir,
        "cwd": cwd_dir,
        "name": "surface2-live-capture",
        "cols": 100,
        "rows": 30,
        "deadline_ms": 13000,
        "steps": [
            {"at_ms": 3000, "input": f"/finetune pause {run_id}"},
            {"at_ms": 3400, "input": cr},
            {"at_ms": 5500, "input": "/watch"},
            {"at_ms": 5900, "input": cr},
            {"at_ms": 8000, "input": f"/finetune resume {run_id}"},
            {"at_ms": 8400, "input": cr},
            {"at_ms": 10500, "input": ctrl_c},
            {"at_ms": 12000, "input": ctrl_c},
        ],
    }
    scenario_path = os.path.join(scratch_root, "live-scenario.json")
    os.makedirs(scratch_root, exist_ok=True)
    with open(scenario_path, "w", encoding="utf-8") as fh:
        json.dump(scenario, fh, indent=1)

    print(f"[live] side effect: opening a visible ConPTY window running ember-cured.exe for ~14s against run_id={run_id!r} (pause immediately followed by resume) -- will close cleanly")
    env = dict(os.environ)
    if not NODE_PTY_MODULE:
        print("GAP: EMBER_PTY_MODULE env var is required (no default baked in). Aborting.")
        return 1
    env["EMBER_PTY_MODULE"] = NODE_PTY_MODULE
    proc = subprocess.run(
        ["node", PTY_DRIVER, scenario_path],
        cwd=scratch_root, env=env, capture_output=True, text=True, timeout=60,
    )
    print("[live] driver stdout:", proc.stdout.strip())
    if proc.returncode != 0:
        print("[live] driver stderr:", proc.stderr.strip())
        print(f"GAP: pty driver exited {proc.returncode}, aborting capture")
        return 1

    driver_receipt_path = os.path.join(outdir, "surface2-live-capture.driver-receipt.json")
    with open(driver_receipt_path, "r", encoding="utf-8") as fh:
        driver_result = json.load(fh)

    raw_path = os.path.join(outdir, "surface2-live-capture.raw")
    with open(raw_path, "r", encoding="utf-8", errors="replace") as fh:
        transcript_clean = strip_ansi(fh.read())

    control_path = os.path.join(cwd_dir, "state", "ember-finetune-control.jsonl")
    control_events = []
    if os.path.isfile(control_path):
        with open(control_path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    control_events.append(json.loads(line))
                except Exception:
                    pass
    print(f"[live] control channel ({control_path}): {len(control_events)} event(s) since capture start")

    pause_event = None
    for ev in control_events:
        if ev.get("verb") == "pause" and ev.get("runId") == run_id:
            pause_event = ev
    resume_event = None
    for ev in control_events:
        if ev.get("verb") == "resume" and ev.get("runId") == run_id:
            resume_event = ev

    if pause_event is None:
        print(f"GAP: no real pause control-channel event captured for runId={run_id!r} -- refusing to write a receipt")
        return 1

    # --- real observed step delta, never fabricated ---------------------
    post_active = find_active_live_run(live_channel_path)
    post_step = post_active["step"] if post_active is not None else None
    metrics_delta = None
    if isinstance(pre_step, (int, float)) and isinstance(post_step, (int, float)) \
            and not isinstance(pre_step, bool) and not isinstance(post_step, bool):
        metrics_delta = post_step - pre_step
    if not (isinstance(metrics_delta, (int, float)) and metrics_delta > 0):
        print(
            f"GAP: observed metrics_delta={metrics_delta!r} (pre_step={pre_step!r}, "
            f"post_step={post_step!r}) is not a real positive number -- refusing to "
            "write a fabricated or zero-value receipt. This is expected if the run "
            "made no progress during the ~14s capture window; re-run during a window "
            "with active step progress."
        )
        return 1

    expected_status_bar_label = f"train r={run_id} step {post_step}"
    telemetry_status_bar_rendered = expected_status_bar_label in transcript_clean
    ack_rendered = "pause" in transcript_clean and f"run={run_id}" in transcript_clean
    render_evidence = {
        "expected_status_bar_label": expected_status_bar_label,
        "telemetry_status_bar_rendered": telemetry_status_bar_rendered,
        "finetune_pause_ack_in_transcript": ack_rendered,
        "watch_ack_in_transcript": "watching" in transcript_clean,
    }
    events_rendered = 1 if telemetry_status_bar_rendered else 0

    now_final = datetime.now(timezone.utc)
    receipt_dirname = dash_ts(now_final)
    receipt_dir = os.path.join(surface_dir, receipt_dirname)
    os.makedirs(receipt_dir, exist_ok=True)

    control_sibling = dict(pause_event)
    control_sibling["metrics_delta"] = metrics_delta
    control_sibling_path = os.path.join(receipt_dir, "finetune-control-event.json")
    with open(control_sibling_path, "w", encoding="utf-8") as fh:
        json.dump(control_sibling, fh, indent=1)
    print(f"[live] wrote control-channel sibling: {control_sibling_path}")

    receipt = {
        "ts": now_final.isoformat().replace("+00:00", "Z"),
        "surface": "C-SURFACE2",
        "provenance": "live_run",
        "run_id": run_id,
        "pre_capture_step": pre_step,
        "post_capture_step": post_step,
        "metrics_delta": metrics_delta,
        "metrics_delta_semantics": (
            "Real observed step advance on the REAL live telemetry channel "
            f"({os.path.relpath(live_channel_path, exec_root).replace(os.sep, '/')}) "
            "between the pre-capture and post-capture reads of the same "
            "currently-active governed run -- not a replay, not a fixture."
        ),
        "control_channel_event": control_sibling,
        "control_channel_resume_event": resume_event,
        "render_evidence": render_evidence,
        "events_rendered": events_rendered,
        "render_path": {
            "binary": os.path.relpath(ember_exe, exec_root).replace(os.sep, "/"),
            "binary_sha256": sha256_of(ember_exe),
            "cockpit": "visible ConPTY (useConpty:true), never headless",
            "telemetry_ingest": "tools/ember-cli/src/services/telemetry-watch.ts startTelemetryWatch()/getState(), auto-mounted in screens/repl.ts, DEFAULT_CHANNEL_PATH (state/ember-telemetry.jsonl) -- no override, the real live channel",
            "control_channel_writer": "tools/ember-cli/src/services/finetune-control.ts emitControlCmd() via the real registered /finetune slash command (commands/finetune.ts), schema-checked (validateControlCmd), not fabricated -- targets the real live runId",
        },
        "live_process_touched": True,
        "gpu_used": False,
        "driver_result": driver_result,
        "board_valid": True,
    }

    receipt_path = os.path.join(receipt_dir, "receipt.json")
    with open(receipt_path, "w", encoding="utf-8") as fh:
        json.dump(_redact(receipt), fh, indent=1)
    print(f"[live] wrote receipt: {receipt_path}")

    transcript_path = os.path.join(receipt_dir, "terminal-transcript-clean.txt")
    with open(transcript_path, "w", encoding="utf-8") as fh:
        fh.write(_redact(transcript_clean))
    print(f"[live] wrote transcript: {transcript_path}")

    print(json.dumps({
        "receipt_dir": receipt_dir,
        "receipt_path": receipt_path,
        "run_id": run_id,
        "metrics_delta": metrics_delta,
        "events_rendered": events_rendered,
        "render_evidence": render_evidence,
    }, indent=1))
    return 0


def run_selftest():
    """--selftest: proves find_active_live_run()'s three real branches and
    run_live_capture()'s fail-closed refusal, entirely against a tempdir --
    no live run, no exe, no ConPTY, no network. This is the "execution" this
    PR claims: a fixture-only proof of the refusal logic, never a live
    capture."""
    import tempfile
    import unittest

    class SelfTest(unittest.TestCase):
        def test_absent_channel_is_no_active_run(self):
            with tempfile.TemporaryDirectory() as d:
                self.assertIsNone(find_active_live_run(os.path.join(d, "nope.jsonl")))

        def test_empty_channel_is_no_active_run(self):
            with tempfile.TemporaryDirectory() as d:
                p = os.path.join(d, "ember-telemetry.jsonl")
                with open(p, "w", encoding="utf-8"):
                    pass
                self.assertIsNone(find_active_live_run(p))

        def test_stale_event_is_no_active_run(self):
            with tempfile.TemporaryDirectory() as d:
                p = os.path.join(d, "ember-telemetry.jsonl")
                now = datetime.now(timezone.utc)
                stale_ts = (now - timedelta(seconds=ACTIVE_RUN_TTL_S + 5)).isoformat().replace("+00:00", "Z")
                with open(p, "w", encoding="utf-8") as fh:
                    fh.write(json.dumps({
                        "ts": stale_ts, "kind": "train_step", "source": "selftest",
                        "payload": {"run_id": "selftest-stale", "step": 7},
                    }) + "\n")
                self.assertIsNone(find_active_live_run(p, now=now))

        def test_fresh_event_is_active_run(self):
            with tempfile.TemporaryDirectory() as d:
                p = os.path.join(d, "ember-telemetry.jsonl")
                now = datetime.now(timezone.utc)
                fresh_ts = (now - timedelta(seconds=5)).isoformat().replace("+00:00", "Z")
                with open(p, "w", encoding="utf-8") as fh:
                    fh.write(json.dumps({
                        "ts": fresh_ts, "kind": "train_step", "source": "selftest",
                        "payload": {"run_id": "selftest-fresh", "step": 42},
                    }) + "\n")
                active = find_active_live_run(p, now=now)
                self.assertIsNotNone(active)
                self.assertEqual(active["run_id"], "selftest-fresh")
                self.assertEqual(active["step"], 42)

        def test_non_train_step_events_ignored(self):
            with tempfile.TemporaryDirectory() as d:
                p = os.path.join(d, "ember-telemetry.jsonl")
                now = datetime.now(timezone.utc)
                fresh_ts = (now - timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
                with open(p, "w", encoding="utf-8") as fh:
                    fh.write(json.dumps({"ts": fresh_ts, "kind": "governor", "source": "selftest", "payload": {}}) + "\n")
                self.assertIsNone(find_active_live_run(p, now=now))

        def test_malformed_lines_are_skipped_not_fatal(self):
            with tempfile.TemporaryDirectory() as d:
                p = os.path.join(d, "ember-telemetry.jsonl")
                now = datetime.now(timezone.utc)
                fresh_ts = (now - timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
                with open(p, "w", encoding="utf-8") as fh:
                    fh.write("{not json\n")
                    fh.write(json.dumps({
                        "ts": fresh_ts, "kind": "train_step", "source": "selftest",
                        "payload": {"run_id": "selftest-recover", "step": 3},
                    }) + "\n")
                active = find_active_live_run(p, now=now)
                self.assertIsNotNone(active)
                self.assertEqual(active["run_id"], "selftest-recover")

        def test_live_capture_refuses_with_no_active_run_no_receipt_no_exe_touch(self):
            with tempfile.TemporaryDirectory() as d:
                channel = os.path.join(d, "state", "ember-telemetry.jsonl")
                surface_dir = os.path.join(d, "receipts", "ember-surface2-telemetry")
                fake_exe = os.path.join(d, "nonexistent-ember-cured.exe")

                class Args:
                    dry_run = False

                rc = run_live_capture(
                    Args(), live_channel_path=channel, exec_root=d,
                    surface_dir=surface_dir, ember_exe=fake_exe, scratch_root=os.path.join(d, "scratch"),
                )
                self.assertNotEqual(rc, 0)
                self.assertFalse(os.path.isdir(surface_dir), "refusal must never create the receipt dir")

        def test_live_capture_refuses_when_exe_missing_even_with_active_run(self):
            with tempfile.TemporaryDirectory() as d:
                channel = os.path.join(d, "state", "ember-telemetry.jsonl")
                os.makedirs(os.path.dirname(channel), exist_ok=True)
                now = datetime.now(timezone.utc)
                fresh_ts = (now - timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
                with open(channel, "w", encoding="utf-8") as fh:
                    fh.write(json.dumps({
                        "ts": fresh_ts, "kind": "train_step", "source": "selftest",
                        "payload": {"run_id": "selftest-active", "step": 9},
                    }) + "\n")
                surface_dir = os.path.join(d, "receipts", "ember-surface2-telemetry")
                fake_exe = os.path.join(d, "nonexistent-ember-cured.exe")

                class Args:
                    dry_run = False

                rc = run_live_capture(
                    Args(), live_channel_path=channel, exec_root=d,
                    surface_dir=surface_dir, ember_exe=fake_exe, scratch_root=os.path.join(d, "scratch"),
                )
                self.assertNotEqual(rc, 0)
                self.assertFalse(os.path.isdir(surface_dir), "an active run without a built exe must still refuse, never fabricate")

    suite = unittest.TestLoader().loadTestsFromTestCase(SelfTest)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return result.wasSuccessful()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="build/detect only, skip PTY capture")
    ap.add_argument("--mode", choices=["replay", "live"], default="replay",
                     help="'live' (issue #140's prescribed cure) instruments a real running governed run; "
                          "'replay' (default, kept for history) is INVALID for the C-SURFACE2 board -- see module docstring")
    ap.add_argument("--selftest", action="store_true", help="run fixture-only refusal/detection proofs, no live run, no exe, no network")
    args = ap.parse_args()

    if args.selftest:
        ok = run_selftest()
        sys.exit(0 if ok else 1)

    if args.mode == "live":
        sys.exit(run_live_capture(args))

    sys.exit(run_replay_capture(args))


if __name__ == "__main__":
    main()
