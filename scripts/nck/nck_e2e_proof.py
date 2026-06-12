#!/usr/bin/env python3
"""sp-7: NC-K harness END-TO-END live proof (Closes #331).

Proves the avir-cli port has a functioning e2e chain by exercising six
consecutive stages with the ember mailbox identity:

  Stage 1:  boot-checksum       verify_at_boot() succeeds; records verified file shas
  Stage 2a: mail-consume-fix    MailSource reads a fixture DB; D1/D2 guards verified
  Stage 2b: mail-consume-live   MailSource reads a REAL mail from the production
                                 mailbox DB (B:/M/avir/mailbox/mailbox.db) using the
                                 real signals/ember file; sent via mailbox binary
  Stage 3:  seat dispatch       mail event routed through seat_adapter.make_seat_core;
                                 stub generate_fn produces a completion; dispatch confirmed
  Stage 4:  CU console verb     ConsoleSource injected line echoes through registry;
                                 console_write tool confirmed dispatched
  Stage 5:  terminal receipt    NCK-E2E receipt binds stage receipts by sha256

AC:
1. boot-checksum stage passes (real verify_at_boot, no _skip_invariant_check)
2. MailSource emits mail_arrived for test message; D1 cold-start no-flood proven;
   D2 non-integer signal format triggers DB poll
2b. MailSource emits mail_arrived for a REAL mail sent to ember via the production
    mailbox binary; DB path = B:/M/avir/mailbox/mailbox.db; signal path = signals/ember
3. seat_adapter.make_seat_core routes event; stub generate_fn returns a completion;
   parse_actions returns list (empty = valid mute baseline)
4. console_write dispatched for injected console line; echo confirmed in output
5. Terminal NCK-E2E receipt: ticket=NCK-E2E-PROOF; all stage_receipts bound by sha

CLI:
  --run        required to execute (staged guard)
  --write      write receipt to receipts/nck-e2e-proof-<ts>.json
  --selftest   run internal component selftests only (no --run required)
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

# Production mailbox paths — Stage 2b (live-mailbox leg)
_MAILBOX_BIN = Path("B:/M/avir/infra/mailbox/target/release/mailbox.exe")
_MAILBOX_PROD_DB = "B:/M/avir/mailbox/mailbox.db"
_MAILBOX_SIGNAL_DIR = "B:/M/avir/infra/mailbox/signals"

from nck.event_loop import (
    ConsoleSource,
    Event,
    MailSource,
    NCKEventLoop,
    ToolRegistry,
    stub_core,
)
from nck.invariants import MANIFEST_PATH, _sha256_file, verify_at_boot
from nck.replay_rig import REPO_ROOT, build_events, join_battery_encodings, materialize
from nck.seat_adapter import TEMPLATE_HASH, make_seat_core

_STAGED_MSG = (
    "STAGED: nck_e2e_proof loaded but not triggered. "
    "Pass --run to execute the e2e proof chain and emit a receipt. "
    "Pass --write to record the receipt to receipts/. "
    "Pass --selftest to run internal component selftests only. "
    "Exit-1 is the evidence-promotion gate."
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sha256_dict(d: dict) -> str:
    return hashlib.sha256(
        json.dumps(d, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _get_commit_sha() -> str:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, cwd=str(REPO_ROOT),
        )
        return r.stdout.strip()
    except Exception:
        return "unknown"


def _send_mail_via_binary(
    from_id: str, to: str, subject: str, body: str, channel: str = "direct"
) -> dict:
    """Send mail by piping a JSON-RPC tools/call to mailbox.exe stdin.

    The binary reads JSON-RPC lines from stdin and exits cleanly when stdin
    closes (subprocess.run EOF).  Returns the parsed tool result dict
    (contains {id, sent_at} on success).  Raises RuntimeError on failure.
    """
    request = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "mail_send",
            "arguments": {
                "to": to,
                "subject": subject,
                "body": body,
                "channel": channel,
            },
        },
    })
    result = subprocess.run(
        [str(_MAILBOX_BIN), "--identity", from_id],
        input=request + "\n",
        capture_output=True,
        text=True,
        timeout=15,
    )
    if result.returncode not in (0, 1):
        raise RuntimeError(
            f"mailbox.exe exited {result.returncode}: {result.stderr.strip()}"
        )
    stdout = result.stdout.strip()
    if not stdout:
        raise RuntimeError(
            f"mailbox.exe returned no output (stderr: {result.stderr.strip()!r})"
        )
    response = json.loads(stdout)
    content_text = (
        response.get("result", {})
                .get("content", [{}])[0]
                .get("text", "{}")
    )
    parsed = json.loads(content_text)
    if "isError" in response.get("result", {}) or "isError" in parsed:
        raise RuntimeError(f"mailbox send error: {content_text}")
    return parsed


# ---------------------------------------------------------------------------
# Stage 1: Boot-checksum
# ---------------------------------------------------------------------------

def stage_boot_checksum() -> dict:
    """Call the real verify_at_boot(). Records each protected path + sha256.

    No _skip_invariant_check — this is the actual boot gate.
    Raises SystemExit on any checksum mismatch (fail-closed).
    """
    verify_at_boot()

    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    entries = manifest.get("protected_paths", [])
    verified = []
    for entry in entries:
        rel = entry.get("path", "")
        label = entry.get("label", rel)
        expected = entry.get("sha256", "")
        if expected == "SELF":
            verified.append({
                "path": rel, "label": label,
                "sha256": "SELF", "note": "baseline-comparison",
            })
            continue
        abs_path = os.path.join(str(REPO_ROOT), rel)
        actual = _sha256_file(abs_path) if os.path.isfile(abs_path) else "NOT_FOUND"
        verified.append({
            "path": rel, "label": label,
            "sha256": actual, "match": actual == expected,
        })

    return {
        "stage": "boot_checksum",
        "pass": True,
        "manifest_path": MANIFEST_PATH,
        "entries_checked": len(entries),
        "verified": verified,
    }


# ---------------------------------------------------------------------------
# Stage 2: Mail consume
# ---------------------------------------------------------------------------

def _make_fixture_db(db_path: str, pre_rows: int = 1) -> int:
    """Create a fixture mailbox DB with `pre_rows` pre-existing messages.
    Returns the id of the last pre-existing message.
    """
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS messages "
        "(id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "from_id TEXT, to_id TEXT, subject TEXT, body TEXT, channel TEXT)"
    )
    for i in range(pre_rows):
        conn.execute(
            "INSERT INTO messages (from_id, to_id, subject, body, channel) "
            "VALUES (?, ?, ?, ?, ?)",
            ("leo", "ember", f"pre-existing-{i}", f"body-{i}", "direct"),
        )
    conn.commit()
    cur = conn.execute("SELECT COALESCE(MAX(id), 0) FROM messages")
    pre_max = cur.fetchone()[0]
    conn.close()
    return pre_max


def stage_mail_consume(tmp_dir: str) -> dict:
    """Exercise MailSource with a fixture DB + signal file.

    D1: MailSource initializes _last_id to the current DB max before the new
    message arrives, so cold-start never re-emits the pre-existing row.
    D2: signal file written with a non-integer timestamp string; MailSource
    converts it to _last_id + 1 to trigger the DB poll.
    """
    db_path = os.path.join(tmp_dir, "mailbox.db")
    signal_path = os.path.join(tmp_dir, "signal-ember")

    # Pre-populate DB with 1 existing message (D1 flood target)
    pre_max = _make_fixture_db(db_path, pre_rows=1)

    # Construct MailSource AFTER the pre-existing row — D1 guard fires here
    src = MailSource(signal_path=signal_path, db_path=db_path, identity="ember")
    d1_last_id = src._last_id
    assert d1_last_id == pre_max, (
        f"D1 fail: _last_id={d1_last_id}, expected pre_max={pre_max}"
    )

    # Confirm no events before signal is written
    events_before = list(src.poll())
    assert len(events_before) == 0, (
        f"D1 fail: {len(events_before)} events emitted without signal"
    )

    # Insert new message (arrives after MailSource was constructed)
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO messages (from_id, to_id, subject, body, channel) "
        "VALUES (?, ?, ?, ?, ?)",
        ("leo", "ember", "nck-e2e-proof-mail", "NCK e2e proof mail body", "direct"),
    )
    conn.commit()
    cur = conn.execute("SELECT MAX(id) FROM messages")
    new_id = cur.fetchone()[0]
    conn.close()

    # Write signal in D2 timestamp format (non-integer → _last_id + 1 in _read_signal)
    with open(signal_path, "w", encoding="utf-8") as f:
        f.write("2026-06-12T09:41:00Z")

    events = list(src.poll())
    assert len(events) == 1, f"Expected 1 event, got {len(events)}: {events}"
    ev = events[0]
    assert ev.source == "mail", f"source mismatch: {ev.source!r}"
    assert ev.kind == "mail_arrived", f"kind mismatch: {ev.kind!r}"
    assert ev.payload.get("from") == "leo", f"from mismatch: {ev.payload}"
    assert ev.payload.get("subject") == "nck-e2e-proof-mail", (
        f"subject mismatch: {ev.payload}"
    )
    assert src._last_id == new_id, (
        f"_last_id not advanced: {src._last_id} vs {new_id}"
    )

    return {
        "stage": "mail_consume",
        "pass": True,
        "d1_no_flood": True,
        "d2_timestamp_path": True,
        "event_id": ev.payload.get("id"),
        "event_from": ev.payload.get("from"),
        "event_subject": ev.payload.get("subject"),
        "event_kind": ev.kind,
        "last_id_advanced": True,
        "mail_event_payload_keys": sorted(ev.payload.keys()),
    }


# ---------------------------------------------------------------------------
# Stage 2b: Mail consume — live production mailbox
# ---------------------------------------------------------------------------

def stage_mail_consume_live() -> dict:
    """Stage-2b: MailSource reads a REAL mail from the production mailbox DB.

    Sends a test mail to ember via the mailbox binary (JSON-RPC stdin),
    then verifies MailSource detects and emits the mail_arrived event using
    the production DB (B:/M/avir/mailbox/mailbox.db) and real signal file
    (B:/M/avir/infra/mailbox/signals/ember).

    Fails closed: any assertion failure → exception → stage FAIL.
    """
    signal_path = os.path.join(_MAILBOX_SIGNAL_DIR, "ember")

    # Construct MailSource BEFORE sending — anchors _last_id to current max.
    # Any events already pending in the signal drain first so the baseline is clean.
    src = MailSource(
        signal_path=signal_path,
        db_path=_MAILBOX_PROD_DB,
        identity="ember",
    )
    # Drain stale signal (empty or stale value pointing past _last_id).
    _ = list(src.poll())
    pre_send_last_id = src._last_id

    # Send a real test mail to ember via the production mailbox binary.
    unique_subject = f"nck-e2e-live-probe-{int(time.time())}"
    sent = _send_mail_via_binary(
        from_id="eli",
        to="ember",
        subject=unique_subject,
        body="NCK e2e live-mailbox leg proof — automated test",
    )
    sent_id: int = sent.get("id", -1)
    assert sent_id > 0, f"mailbox send returned unexpected id: {sent}"

    # Binary writes signal file synchronously; brief yield for filesystem flush.
    time.sleep(0.3)

    # Poll — signal should now contain sent_id > pre_send_last_id.
    events = list(src.poll())

    # Filter to our specific test mail by unique subject (guards against concurrent
    # 'all' broadcasts or other ember-targeted mail arriving at the same instant).
    our_events = [e for e in events if e.payload.get("subject") == unique_subject]
    assert len(our_events) == 1, (
        f"Expected exactly 1 event for subject={unique_subject!r}, "
        f"got {len(our_events)}: {[(e.payload.get('id'), e.payload.get('subject')) for e in events]}"
    )
    ev = our_events[0]
    assert ev.source == "mail", f"source mismatch: {ev.source!r}"
    assert ev.kind == "mail_arrived", f"kind mismatch: {ev.kind!r}"
    assert ev.payload.get("id") == sent_id, (
        f"id mismatch: event.id={ev.payload.get('id')} sent_id={sent_id}"
    )

    return {
        "stage": "mail_consume_live",
        "pass": True,
        "db_path": _MAILBOX_PROD_DB,
        "signal_path": signal_path,
        "identity": "ember",
        "pre_send_last_id": pre_send_last_id,
        "sent_mail_id": sent_id,
        "sent_subject": unique_subject,
        "event_id": ev.payload.get("id"),
        "event_from": ev.payload.get("from"),
        "event_kind": ev.kind,
        "note": "live mailbox leg — real mail to ember via production DB + signal file",
    }


# ---------------------------------------------------------------------------
# Stage 3: Seat dispatch
# ---------------------------------------------------------------------------

def stage_seat_dispatch() -> dict:
    """Route a battery episode event through seat_adapter.make_seat_core.

    Uses a stub generate_fn that returns "no-action" — mute output IS the
    valid baseline for a raw pretrain core and does not signal a plumbing
    failure. The proof is that the chain completes without error.
    """
    def _stub_generate(prompt: str) -> str:
        return "no-action"

    core = make_seat_core(_stub_generate)

    episodes = join_battery_encodings()
    ep = episodes[0]

    with tempfile.TemporaryDirectory(prefix="nck-e2e-seat-") as seat_tmp:
        materialize(ep, seat_tmp)
        evs = build_events(ep, seat_tmp)
        ev = evs[0]

        # Minimal registry — seat_core ignores it but the protocol requires it
        registry = ToolRegistry()
        registry.register(
            "console_write",
            lambda **kw: {"written": True},
            schema={"text": {"type": "string", "default": ""}},
        )
        registry.register(
            "write_gate_note",
            lambda **kw: {"written": "mock"},
            schema={
                "receipt_path": {"type": "string", "default": ""},
                "schedule_id": {"type": "string", "default": ""},
                "event_ts": {"type": "string", "default": ""},
            },
        )

        actions = core(ev, registry, seat_tmp)

    assert isinstance(actions, list), (
        f"seat_core must return list, got {type(actions).__name__}"
    )

    return {
        "stage": "seat_dispatch",
        "pass": True,
        "template_hash": TEMPLATE_HASH,
        "episode_id": ep["id"],
        "event_kind": ev.kind,
        "actions_returned": len(actions),
        "generate_fn": "stub (returns 'no-action')",
        "note": "mute/no-action output is baseline datum for raw pretrain core",
    }


# ---------------------------------------------------------------------------
# Stage 4: CU console verb
# ---------------------------------------------------------------------------

def stage_cu_console() -> dict:
    """Inject a line via ConsoleSource; verify console_write dispatched.

    Uses NCKEventLoop with _skip_invariant_check=True (tmp dir — not real repo).
    The proof is that the full path fires:
      ConsoleSource.poll() → stub_core emits console_write → registry dispatches
      → output stream contains the echoed probe line.
    """
    probe_line = "nck-e2e-proof-console-poke"
    stdin = io.StringIO(probe_line + "\n")
    out = io.StringIO()

    with tempfile.TemporaryDirectory(prefix="nck-e2e-cu-") as tmp:
        config = {
            "governor": {
                "vram_fraction": 0.7,
                "margin_gib_floor": 1.0,
                "pace_s_per_step": 0.05,
            },
            "goal_file": os.path.join(tmp, "GOAL.md"),
            "heartbeat_file": os.path.join(tmp, "nck-heartbeat.txt"),
            "journal_path": os.path.join(tmp, "nck-journal.jsonl"),
            "gate_notes_dir": os.path.join(tmp, "gate-notes"),
            "_skip_invariant_check": True,
        }
        loop = NCKEventLoop(config)
        src = ConsoleSource(output_stream=out, stdin_stream=stdin)
        loop.add_source(src)

        time.sleep(0.05)  # allow reader thread to queue the line
        loop.run(max_ticks=1)

    written = out.getvalue()
    assert probe_line in written, (
        f"probe_line {probe_line!r} not in output {written!r}"
    )

    return {
        "stage": "cu_console",
        "pass": True,
        "probe_line": probe_line,
        "echo_confirmed": True,
        "output_len": len(written),
        "tool_dispatched": "console_write",
    }


# ---------------------------------------------------------------------------
# Internal selftests (--selftest mode, no --run required)
# ---------------------------------------------------------------------------

def run_selftest() -> int:
    """Component-level selftests for the proof harness itself."""
    failures: list[str] = []

    # (a) _sha256_dict determinism
    d = {"x": 1, "y": "hello"}
    if _sha256_dict(d) != _sha256_dict(d):
        failures.append("(a) _sha256_dict non-deterministic")

    # (b) _make_fixture_db: pre_max == number of pre-rows
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "mb.db")
        pm = _make_fixture_db(db, pre_rows=2)
        if pm != 2:
            failures.append(f"(b) fixture DB pre_max expected 2, got {pm}")

    # (c) D1 guard: MailSource._last_id initialized to pre_max after _make_fixture_db
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "mb.db")
        sig = os.path.join(tmp, "sig")
        pm = _make_fixture_db(db, pre_rows=1)
        src = MailSource(signal_path=sig, db_path=db, identity="ember")
        if src._last_id != pm:
            failures.append(f"(c) D1 _last_id={src._last_id}, expected {pm}")
        evs = list(src.poll())
        if evs:
            failures.append(f"(c) D1 emitted {len(evs)} events without signal")

    # (d) make_seat_core + stub: returns list, no exception
    def _stub(p: str) -> str:
        return "no-action"
    core = make_seat_core(_stub)
    eps = join_battery_encodings()
    with tempfile.TemporaryDirectory() as tmp:
        materialize(eps[0], tmp)
        evs2 = build_events(eps[0], tmp)
        registry = ToolRegistry()
        registry.register(
            "console_write", lambda **kw: None,
            schema={"text": {"type": "string", "default": ""}},
        )
        registry.register(
            "write_gate_note", lambda **kw: None,
            schema={
                "receipt_path": {"type": "string", "default": ""},
                "schedule_id": {"type": "string", "default": ""},
                "event_ts": {"type": "string", "default": ""},
            },
        )
        try:
            acts = core(evs2[0], registry, tmp)
            if not isinstance(acts, list):
                failures.append(f"(d) seat_core returned {type(acts).__name__}, expected list")
        except Exception as exc:
            failures.append(f"(d) seat_core raised: {exc}")

    # (e) ConsoleSource echo round-trip
    probe = "selftest-echo-poke"
    stdin = io.StringIO(probe + "\n")
    out = io.StringIO()
    src2 = ConsoleSource(output_stream=out, stdin_stream=stdin)
    with tempfile.TemporaryDirectory() as tmp:
        config = {
            "governor": {"vram_fraction": 0.7, "margin_gib_floor": 1.0, "pace_s_per_step": 0.05},
            "goal_file": os.path.join(tmp, "GOAL.md"),
            "heartbeat_file": os.path.join(tmp, "hb.txt"),
            "journal_path": os.path.join(tmp, "j.jsonl"),
            "gate_notes_dir": os.path.join(tmp, "gn"),
            "_skip_invariant_check": True,
        }
        loop = NCKEventLoop(config)
        loop.add_source(src2)
        time.sleep(0.05)
        loop.run(max_ticks=1)
    written = out.getvalue()
    if probe not in written:
        failures.append(f"(e) echo: {probe!r} not in {written!r}")

    # (f) Live-mailbox leg infrastructure: binary present + prod DB exists
    if not _MAILBOX_BIN.is_file():
        failures.append(f"(f) mailbox binary not found: {_MAILBOX_BIN}")
    if not os.path.isfile(_MAILBOX_PROD_DB):
        failures.append(f"(f) production DB not found: {_MAILBOX_PROD_DB}")

    if failures:
        print("NCK_E2E_PROOF_SELFTEST FAIL")
        for f in failures:
            print(f"  {f}")
        return 1

    print("NCK_E2E_PROOF_SELFTEST PASS (cases: a b c d e f)")
    return 0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    args = sys.argv[1:]

    if "--selftest" in args:
        return run_selftest()

    if "--run" not in args:
        print(_STAGED_MSG)
        return 1

    write = "--write" in args

    print("=== NCK-E2E proof chain (#331) ===")
    commit_sha = _get_commit_sha()
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    stage_receipts: dict[str, dict] = {}

    # Stage 1: Boot-checksum (real verify_at_boot)
    print("\n[1/5] Boot-checksum (real verify_at_boot — no skip flag)...")
    try:
        s1 = stage_boot_checksum()
        stage_receipts["boot_checksum"] = s1
        print(f"  PASS: {s1['entries_checked']} entries verified")
    except SystemExit as exc:
        print(f"  FAIL: {exc}")
        return 1

    with tempfile.TemporaryDirectory(prefix="nck-e2e-mail-") as mail_tmp:

        # Stage 2a: Mail consume (fixture — D1/D2 proof)
        print("\n[2/5] Mail consume fixture (D1 flood-guard + D2 timestamp path)...")
        try:
            s2 = stage_mail_consume(mail_tmp)
            stage_receipts["mail_consume"] = s2
            print(
                f"  PASS: event_id={s2['event_id']}, "
                f"D1={s2['d1_no_flood']}, D2={s2['d2_timestamp_path']}"
            )
        except (AssertionError, Exception) as exc:
            print(f"  FAIL: {exc}")
            return 1

    # Stage 2b: Mail consume live (production mailbox DB + real signal file)
    print("\n[3/5] Mail consume live (production DB -> MailSource -> mail_arrived)...")
    try:
        s2b = stage_mail_consume_live()
        stage_receipts["mail_consume_live"] = s2b
        print(
            f"  PASS: sent_id={s2b['sent_mail_id']}, "
            f"event_id={s2b['event_id']}, from={s2b['event_from']!r}"
        )
    except (AssertionError, Exception) as exc:
        print(f"  FAIL: {exc}")
        return 1

    # Stage 3: Seat dispatch
    print("\n[4/5] Seat dispatch (stub generate_fn via seat_adapter)...")
    try:
        s3 = stage_seat_dispatch()
        stage_receipts["seat_dispatch"] = s3
        print(
            f"  PASS: template_hash={s3['template_hash'][:16]}..., "
            f"actions={s3['actions_returned']}, episode={s3['episode_id']}"
        )
    except (AssertionError, Exception) as exc:
        print(f"  FAIL: {exc}")
        return 1

    # Stage 4: CU console
    print("\n[5/5] CU console verb (ConsoleSource + console_write dispatch)...")
    try:
        s4 = stage_cu_console()
        stage_receipts["cu_console"] = s4
        print(
            f"  PASS: echo_confirmed={s4['echo_confirmed']}, "
            f"tool={s4['tool_dispatched']}"
        )
    except (AssertionError, Exception) as exc:
        print(f"  FAIL: {exc}")
        return 1

    # Terminal receipt: bind all stage receipts by sha256
    all_pass = all(r.get("pass", False) for r in stage_receipts.values())

    stage_receipt_shas = {
        stage: _sha256_dict(receipt)
        for stage, receipt in stage_receipts.items()
    }

    receipt = {
        "ticket": "NCK-E2E-PROOF",
        "label": "NCK-E2E-PROOF-BOUND-CHAIN",
        "ts": ts,
        "commit_sha": commit_sha,
        "identity": "ember",
        "chain": [
            "boot_checksum",
            "mail_consume",
            "mail_consume_live",
            "seat_dispatch",
            "cu_console",
        ],
        "all_stages_pass": all_pass,
        "stage_receipts": stage_receipts,
        "stage_receipt_shas": stage_receipt_shas,
        "flags": [
            "boot-checksum: real verify_at_boot() — no _skip_invariant_check",
            "mail-consume: fixture SQLite DB + signal file; D1 cold-start no-flood + D2 timestamp path",
            "mail-consume-live: REAL mail to ember via production mailbox binary; "
            "DB=B:/M/avir/mailbox/mailbox.db; signal=signals/ember",
            "seat-dispatch: stub generate_fn; mute output is valid baseline for raw pretrain core",
            "cu-console: ConsoleSource injected line → stub_core console_write → dispatched",
            "live run 12c050e7 NOT touched",
            "no GPU dispatch — CPU/idle-only proof of plumbing",
        ],
        "live_run_untouched": "12c050e7",
        "sha_convention": (
            "stage_receipt_shas: sha256 over UTF-8 JSON (sort_keys=True); "
            "file hashes in boot_checksum: sha256 over on-disk raw bytes (binary read)"
        ),
    }

    if write:
        receipt_dir = REPO_ROOT / "receipts"
        receipt_dir.mkdir(exist_ok=True)
        fname = receipt_dir / f"nck-e2e-proof-{ts}.json"
        fname.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        print(f"\nRECEIPT: {fname}")
    else:
        print("\n(dry-run: pass --write to save receipt)")
        print(json.dumps({
            "all_stages_pass": all_pass,
            "chain": receipt["chain"],
            "stage_receipt_shas": {k: v[:16] + "..." for k, v in stage_receipt_shas.items()},
            "commit_sha": commit_sha[:12] + "...",
        }, indent=2))

    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
