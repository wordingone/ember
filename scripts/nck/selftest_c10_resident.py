"""C10 resident selftest — closes #340 AC §2.

Proves all 4 event classes produce NCK-EVENT-DISPATCH receipts:
  (a) mail        — MailSource -> receipt with event_source=mail
  (b) file_watch  — FileWatchSource -> receipt with event_source=file_watch
  (c) job_receipt — JobReceiptSource -> receipt with event_source=job_receipt
  (d) schedule    — ScheduleSource -> receipt with event_source=schedule

Also verifies:
  (e) rss_cap     — loop exits(2) when rss_cap_mib exceeded (mock psutil)
  (f) kill_switch — loop exits(0) when kill_flag file present

Prints: C10_RESIDENT_SELFTEST PASS / FAIL with case names.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import time
import types

_THIS = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS = os.path.dirname(_THIS)
for _p in (_THIS, _SCRIPTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import nck.event_loop as _el
from nck.event_loop import (
    FileWatchSource,
    JobReceiptSource,
    MailSource,
    NCKEventLoop,
    ScheduleSource,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _base_config(tmp: str) -> dict:
    return {
        "governor": {
            "vram_fraction": 0.7,
            "margin_gib_floor": 1.0,
            "pace_s_per_step": 0.05,
        },
        "goal_file": os.path.join(tmp, "GOAL.md"),
        "heartbeat_file": os.path.join(tmp, "nck-heartbeat.txt"),
        "journal_path": os.path.join(tmp, "nck-journal.jsonl"),
        "gate_notes_dir": os.path.join(tmp, "gate-notes"),
        "event_receipts_dir": os.path.join(tmp, "event-receipts"),
        "poll_interval_s": 0,
        "_skip_invariant_check": True,
    }


def _touch_goal(tmp: str) -> None:
    with open(os.path.join(tmp, "GOAL.md"), "w") as f:
        f.write("GOAL placeholder\n")


def _list_event_receipts(receipts_dir: str) -> list[dict]:
    result = []
    if not os.path.isdir(receipts_dir):
        return result
    for name in os.listdir(receipts_dir):
        if not name.endswith(".json"):
            continue
        path = os.path.join(receipts_dir, name)
        try:
            with open(path, encoding="utf-8") as f:
                result.append(json.load(f))
        except (OSError, json.JSONDecodeError):
            pass
    return result


def _make_mailbox(tmp: str, messages: list[dict]) -> tuple[str, str, str]:
    """Create a mailbox DB + signal file with the given messages. Returns (db_path, signal_path, identity)."""
    db_path = os.path.join(tmp, "mailbox.db")
    signal_path = os.path.join(tmp, "signal_ember")
    identity = "ember"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE messages "
        "(id INTEGER PRIMARY KEY AUTOINCREMENT, from_id TEXT, to_id TEXT, "
        "subject TEXT, body TEXT, channel TEXT, sent_at TEXT)"
    )
    for m in messages:
        conn.execute(
            "INSERT INTO messages (from_id, to_id, subject, body, channel, sent_at) "
            "VALUES (?,?,?,?,?,?)",
            (m["from_id"], m["to_id"], m["subject"], m.get("body", ""), m.get("channel", "mail"), m.get("sent_at", "2026-01-01T00:00:00+00:00")),
        )
    conn.commit()
    conn.close()
    # Write signal: max message id for ember
    conn2 = sqlite3.connect(db_path)
    row = conn2.execute(
        "SELECT MAX(id) FROM messages WHERE LOWER(to_id) = LOWER(?)", (identity,)
    ).fetchone()
    conn2.close()
    max_id = row[0] or 0
    with open(signal_path, "w") as f:
        f.write(str(max_id))
    return db_path, signal_path, identity


# ---------------------------------------------------------------------------
# Case (a): mail
# ---------------------------------------------------------------------------

def case_a_mail(tmp: str) -> tuple[bool, str]:
    # Set up mailbox with 0 pre-existing messages so MailSource starts at 0
    db_path = os.path.join(tmp, "mailbox.db")
    signal_path = os.path.join(tmp, "signal_ember")
    identity = "ember"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE messages "
        "(id INTEGER PRIMARY KEY AUTOINCREMENT, from_id TEXT, to_id TEXT, "
        "subject TEXT, body TEXT, channel TEXT, sent_at TEXT)"
    )
    conn.commit()
    conn.close()

    # Insert a new message and write signal AFTER source construction
    config = _base_config(tmp)
    _touch_goal(tmp)
    loop = NCKEventLoop(config)
    mail_src = MailSource(signal_path=signal_path, db_path=db_path, identity=identity)
    loop.add_source(mail_src)

    # Now inject mail
    conn2 = sqlite3.connect(db_path)
    conn2.execute(
        "INSERT INTO messages (from_id, to_id, subject, body, channel, sent_at) VALUES (?,?,?,?,?,?)",
        ("eli", "ember", "test mail", "hello", "mail", "2026-06-12T00:00:00+00:00"),
    )
    conn2.commit()
    row = conn2.execute("SELECT MAX(id) FROM messages WHERE LOWER(to_id)=LOWER(?)", (identity,)).fetchone()
    conn2.close()
    with open(signal_path, "w") as f:
        f.write(str(row[0]))

    loop.run(max_ticks=1)

    receipts = _list_event_receipts(config["event_receipts_dir"])
    mail_receipts = [r for r in receipts if r.get("event_source") == "mail"]
    if not mail_receipts:
        return False, f"no mail receipt found; receipts={receipts}"
    r = mail_receipts[0]
    if r.get("ticket") != "NCK-EVENT-DISPATCH":
        return False, f"wrong ticket: {r}"
    if not r.get("ts"):
        return False, f"missing ts: {r}"
    return True, f"mail receipt: {r}"


# ---------------------------------------------------------------------------
# Case (b): file_watch
# ---------------------------------------------------------------------------

def case_b_file_watch(tmp: str) -> tuple[bool, str]:
    watch_dir = os.path.join(tmp, "watched")
    os.makedirs(watch_dir, exist_ok=True)

    config = _base_config(tmp)
    _touch_goal(tmp)
    loop = NCKEventLoop(config)
    loop.add_source(FileWatchSource(watch_dir=watch_dir, glob_suffix=".json"))

    # Drop a file before run
    with open(os.path.join(watch_dir, "evt-001.json"), "w") as f:
        json.dump({"x": 1}, f)

    loop.run(max_ticks=1)

    receipts = _list_event_receipts(config["event_receipts_dir"])
    fw_receipts = [r for r in receipts if r.get("event_source") == "file_watch"]
    if not fw_receipts:
        return False, f"no file_watch receipt found; receipts={receipts}"
    r = fw_receipts[0]
    if r.get("ticket") != "NCK-EVENT-DISPATCH":
        return False, f"wrong ticket: {r}"
    if not r.get("ts"):
        return False, f"missing ts: {r}"
    return True, f"file_watch receipt: {r}"


# ---------------------------------------------------------------------------
# Case (c): job_receipt
# ---------------------------------------------------------------------------

def case_c_job_receipt(tmp: str) -> tuple[bool, str]:
    receipts_dir = os.path.join(tmp, "job-receipts")
    os.makedirs(receipts_dir, exist_ok=True)

    config = _base_config(tmp)
    _touch_goal(tmp)
    loop = NCKEventLoop(config)
    loop.add_source(JobReceiptSource(receipts_dir=receipts_dir))

    with open(os.path.join(receipts_dir, "job-001.json"), "w") as f:
        json.dump({"ticket": "TEST", "ts": "20260101T000000Z"}, f)

    loop.run(max_ticks=1)

    receipts = _list_event_receipts(config["event_receipts_dir"])
    jr_receipts = [r for r in receipts if r.get("event_source") == "job_receipt"]
    if not jr_receipts:
        return False, f"no job_receipt receipt found; receipts={receipts}"
    r = jr_receipts[0]
    if r.get("ticket") != "NCK-EVENT-DISPATCH":
        return False, f"wrong ticket: {r}"
    if not r.get("ts"):
        return False, f"missing ts: {r}"
    return True, f"job_receipt receipt: {r}"


# ---------------------------------------------------------------------------
# Case (d): schedule
# ---------------------------------------------------------------------------

def case_d_schedule(tmp: str) -> tuple[bool, str]:
    schedule_path = os.path.join(tmp, "schedule.json")
    # interval=1, last_run=None → due immediately
    with open(schedule_path, "w") as f:
        json.dump([{"id": "test-tick", "interval_s": 1, "last_run_ts": None}], f)

    config = _base_config(tmp)
    _touch_goal(tmp)
    loop = NCKEventLoop(config)
    loop.add_source(ScheduleSource(schedule_path=schedule_path))

    loop.run(max_ticks=1)

    receipts = _list_event_receipts(config["event_receipts_dir"])
    sched_receipts = [r for r in receipts if r.get("event_source") == "schedule"]
    if not sched_receipts:
        return False, f"no schedule receipt found; receipts={receipts}"
    r = sched_receipts[0]
    if r.get("ticket") != "NCK-EVENT-DISPATCH":
        return False, f"wrong ticket: {r}"
    if not r.get("ts"):
        return False, f"missing ts: {r}"
    return True, f"schedule receipt: {r}"


# ---------------------------------------------------------------------------
# Case (e): rss_cap exit(2)
# ---------------------------------------------------------------------------

def case_e_rss_cap(tmp: str) -> tuple[bool, str]:
    config = _base_config(tmp)
    config["rss_cap_mib"] = 1  # 1 MiB — will always be exceeded
    _touch_goal(tmp)

    # Patch psutil in the event_loop module to return a mock
    class _FakeMemInfo:
        rss = 1024 * 1024 * 1024  # 1 GiB

    class _FakeProcess:
        def memory_info(self):
            return _FakeMemInfo()

    class _FakePsutil:
        def Process(self):
            return _FakeProcess()

    orig_psutil = _el._psutil
    _el._psutil = _FakePsutil()
    try:
        loop = NCKEventLoop(config)
        exit_code = None
        try:
            loop.run(max_ticks=5)
        except SystemExit as exc:
            exit_code = exc.code
    finally:
        _el._psutil = orig_psutil

    if exit_code != 2:
        return False, f"expected exit(2) on RSS breach, got exit_code={exit_code}"
    return True, f"rss_cap: exit(2) on breach"


# ---------------------------------------------------------------------------
# Case (f): kill-switch exit(0)
# ---------------------------------------------------------------------------

def case_f_kill_switch(tmp: str) -> tuple[bool, str]:
    kill_flag = os.path.join(tmp, "nck-kill")
    config = _base_config(tmp)
    config["kill_flag"] = kill_flag
    _touch_goal(tmp)

    # Create the sentinel before run
    with open(kill_flag, "w") as f:
        f.write("kill\n")

    loop = NCKEventLoop(config)
    exit_code = None
    try:
        loop.run(max_ticks=5)
    except SystemExit as exc:
        exit_code = exc.code

    if exit_code != 0:
        return False, f"expected exit(0) on kill-switch, got exit_code={exit_code}"
    return True, "kill-switch: exit(0) on sentinel"


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

_CASES = [
    ("a_mail", case_a_mail),
    ("b_file_watch", case_b_file_watch),
    ("c_job_receipt", case_c_job_receipt),
    ("d_schedule", case_d_schedule),
    ("e_rss_cap", case_e_rss_cap),
    ("f_kill_switch", case_f_kill_switch),
]


def main() -> int:
    failures = []
    for name, fn in _CASES:
        with tempfile.TemporaryDirectory(prefix="nck_c10_") as tmp:
            try:
                ok, msg = fn(tmp)
            except Exception as exc:
                import traceback
                ok, msg = False, f"EXCEPTION: {exc}\n{traceback.format_exc()}"
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {name}: {msg}")
        if not ok:
            failures.append(name)

    if failures:
        print(f"C10_RESIDENT_SELFTEST FAIL")
        return 1
    print("C10_RESIDENT_SELFTEST PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
