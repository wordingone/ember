"""NC-K resident event-loop — closes #260, extended for C10 (#340).

Architecture:
  EventSource ABC  -> FileWatchSource, ScheduleSource, JobReceiptSource, MailSource, ConsoleSource
  dispatch loop    -> pull events, route through TOOL REGISTRY
  stub core        -> pure function event -> list[Action]; trivially swappable
  process supervision -> heartbeat touch every tick; crash-safe journal (state/nck-journal.jsonl)
  hook points      -> pre_action, post_action callable lists
  RSS cap          -> configurable rss_cap_mib; exit-on-breach (C10 §3)
  kill-switch      -> sentinel file kill_flag (config key); checked every tick (C10 §5)

Invariant config block (fail-closed):
  config must contain 'governor' (placeholder fields) and 'goal_file' (path).
  Loop refuses to start on missing/invalid config.

Stub status:
  MailSource         -> LIVE (issue #259: signal-file + sqlite wiring, ember identity)
  ConsoleSource      -> LIVE (issue #262: stdin thread + queue; WriteConsoleInput-compatible)
  stub_core          -> rule-based Python function, NO model, trivially swappable
  write_event_receipt -> per-event receipt tool; ticket=NCK-EVENT-DISPATCH (C10 §2)

Boot-checksum layer (issue #261):
  verify_at_boot() from scripts/nck/invariants.py is called in NCKEventLoop.__init__
  after validate_invariant_config().  Any protected-path mismatch -> SystemExit.
  The invariants import is guarded: if the module is absent, the loop fails closed
  (absent invariants layer = refuse to start).
"""

from __future__ import annotations

import abc
import json
import os
import queue
import sqlite3
import sys
import threading
import time
import hashlib

try:
    import psutil as _psutil
except ImportError:
    _psutil = None  # type: ignore[assignment]
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Iterator

# Boot-checksum layer — imported here so the import itself is a startup check.
# If invariants.py is absent, the ImportError propagates and the loop refuses to start.
try:
    from nck.invariants import verify_at_boot as _verify_at_boot
except ImportError:
    try:
        from invariants import verify_at_boot as _verify_at_boot  # type: ignore[no-redef]
    except ImportError as _exc:
        import sys
        raise SystemExit(
            f"INVARIANT_REFUSE: cannot import verify_at_boot from invariants module: {_exc}. "
            "The boot-checksum layer (issue #261) must be present. Boot refused."
        ) from _exc


# ---------------------------------------------------------------------------
# Timestamp helper
# ---------------------------------------------------------------------------

def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------

@dataclass
class Event:
    """An event delivered to the dispatch loop."""
    source: str          # e.g. "file_watch", "schedule", "job_receipt", "mail"
    kind: str            # e.g. "file_changed", "tick_due", "receipt_arrived"
    payload: dict[str, Any] = field(default_factory=dict)
    ts: str = field(default_factory=_ts)


@dataclass
class Action:
    """An action the stub core has decided to emit for an event."""
    verb: str                        # tool name — must be in TOOL REGISTRY
    args: dict[str, Any] = field(default_factory=dict)
    event_ref: Event | None = None   # traceability back to originating event


# ---------------------------------------------------------------------------
# Tool Registry
# ---------------------------------------------------------------------------

class ToolRegistry:
    """One uniform tool interface.  name -> callable + declared arg schema.
    Unknown verb -> refuse (no special execution paths).
    """

    def __init__(self) -> None:
        self._tools: dict[str, dict[str, Any]] = {}

    def register(self, name: str, fn: Callable[..., Any],
                 schema: dict[str, Any], *,
                 concurrency_safe: bool = False,
                 read_only: bool = False,
                 permission_class: str = "default") -> None:
        self._tools[name] = {
            "fn": fn,
            "schema": schema,
            "concurrency_safe": concurrency_safe,
            "read_only": read_only,
            "permission_class": permission_class,
        }

    def dispatch(self, action: Action) -> Any:
        """Dispatch an action.  Raises ValueError on unknown verb."""
        if action.verb not in self._tools:
            raise ValueError(
                f"REGISTRY_REFUSE: unknown verb '{action.verb}'. "
                f"Registered: {sorted(self._tools)}"
            )
        tool = self._tools[action.verb]
        return tool["fn"](**action.args)

    def known_verbs(self) -> list[str]:
        return sorted(self._tools)


# ---------------------------------------------------------------------------
# EventSource ABC
# ---------------------------------------------------------------------------

class EventSource(abc.ABC):
    """Abstract event source.  poll() yields zero or more Events per call."""

    @abc.abstractmethod
    def poll(self) -> Iterator[Event]:
        ...


# ---------------------------------------------------------------------------
# Concrete sources
# ---------------------------------------------------------------------------

class FileWatchSource(EventSource):
    """Poll a watched directory for new or changed files.
    Tracks mtime + size per path; emits 'file_changed' or 'file_new' events.
    """

    def __init__(self, watch_dir: str, glob_suffix: str = "") -> None:
        self.watch_dir = watch_dir
        self.glob_suffix = glob_suffix  # filter: only paths ending with this suffix
        self._seen: dict[str, tuple[float, int]] = {}  # path -> (mtime, size)

    def poll(self) -> Iterator[Event]:
        if not os.path.isdir(self.watch_dir):
            return
        for entry in os.scandir(self.watch_dir):
            if not entry.is_file(follow_symlinks=False):
                continue
            if self.glob_suffix and not entry.name.endswith(self.glob_suffix):
                continue
            stat = entry.stat()
            key = entry.path
            mtime_size = (stat.st_mtime, stat.st_size)
            prev = self._seen.get(key)
            if prev is None:
                kind = "file_new"
            elif prev != mtime_size:
                kind = "file_changed"
            else:
                continue
            self._seen[key] = mtime_size
            yield Event(
                source="file_watch",
                kind=kind,
                payload={"path": entry.path, "size": stat.st_size},
            )


class ScheduleSource(EventSource):
    """Cron-like due items from a schedule.json.
    Schema: list of {"id": str, "interval_s": int, "last_run_ts": str|null}
    Writes back updated last_run_ts after emitting.
    """

    def __init__(self, schedule_path: str) -> None:
        self.schedule_path = schedule_path

    def _load(self) -> list[dict[str, Any]]:
        if not os.path.isfile(self.schedule_path):
            return []
        with open(self.schedule_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _save(self, items: list[dict[str, Any]]) -> None:
        tmp = self.schedule_path + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            json.dump(items, f, indent=2, sort_keys=True)
            f.write("\n")
        os.replace(tmp, self.schedule_path)

    def poll(self) -> Iterator[Event]:
        items = self._load()
        now = time.time()
        changed = False
        for item in items:
            interval = item.get("interval_s", 0)
            last_raw = item.get("last_run_ts")
            if last_raw:
                try:
                    last = datetime.strptime(last_raw, "%Y%m%dT%H%M%SZ").replace(
                        tzinfo=timezone.utc
                    ).timestamp()
                except ValueError:
                    last = 0.0
            else:
                last = 0.0
            if interval > 0 and (now - last) >= interval:
                yield Event(
                    source="schedule",
                    kind="tick_due",
                    payload={"id": item["id"], "interval_s": interval},
                )
                item["last_run_ts"] = _ts()
                changed = True
        if changed:
            self._save(items)


class JobReceiptSource(EventSource):
    """Poll a receipts directory for new *.json files.
    Emits 'receipt_arrived' once per new file (tracks by filename).
    """

    def __init__(self, receipts_dir: str) -> None:
        self.receipts_dir = receipts_dir
        self._seen: set[str] = set()

    def poll(self) -> Iterator[Event]:
        if not os.path.isdir(self.receipts_dir):
            return
        for entry in os.scandir(self.receipts_dir):
            if not entry.is_file(follow_symlinks=False):
                continue
            if not entry.name.endswith(".json"):
                continue
            if entry.name in self._seen:
                continue
            self._seen.add(entry.name)
            try:
                with open(entry.path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except (OSError, json.JSONDecodeError) as exc:
                data = {"_parse_error": str(exc)}
            yield Event(
                source="job_receipt",
                kind="receipt_arrived",
                payload={"path": entry.path, "data": data},
            )


class MailSource(EventSource):
    """Poll the ember signal file and emit mail_arrived events from the mailbox DB.

    Implements issue #259: ember mailbox identity + founders.yaml signal wiring.
    Emits Event(source="mail", kind="mail_arrived", payload={id,from,subject,body,channel})
    per the frozen sp6 interface (docs/sp6-duty-battery-v0.md §Encoding half).

    signal_path  — path to the founder's signal file (written by mailbox binary on new mail)
    db_path      — path to mailbox.db (SQLite)
    identity     — founder identity string used as to_id filter (default "ember")
    """

    def __init__(
        self,
        signal_path: str,
        db_path: str,
        identity: str = "ember",
    ) -> None:
        self.signal_path = signal_path
        self.db_path = db_path
        self.identity = identity
        # D1: initialize cursor to the current max id so the first poll never
        # re-emits the entire broadcast history of a large DB.
        self._last_id: int = self._query_max_id()

    def _query_max_id(self) -> int:
        """Return MAX(id) for messages addressed to this identity (0 if DB absent)."""
        try:
            conn = sqlite3.connect(self.db_path)
            try:
                cur = conn.execute(
                    "SELECT COALESCE(MAX(id), 0) FROM messages "
                    "WHERE LOWER(to_id) = LOWER(?) OR to_id = 'all'",
                    (self.identity,),
                )
                return cur.fetchone()[0]
            finally:
                conn.close()
        except (OSError, sqlite3.DatabaseError):
            return 0

    def _read_signal(self) -> int:
        """Return signal value to compare against _last_id.

        - Absent or empty signal: 0 (no poll).
        - Integer content: the parsed id.
        - Non-integer content (D2: old-binary timestamp format): _last_id + 1,
          so signal_id > _last_id triggers the DB poll; _last_id deduplicates
          any messages already emitted.
        """
        try:
            with open(self.signal_path, "r", encoding="utf-8") as f:
                raw = f.read().strip()
        except OSError:
            return 0
        if not raw:
            return 0
        try:
            return int(raw)
        except ValueError:
            return self._last_id + 1

    def poll(self) -> Iterator[Event]:
        signal_id = self._read_signal()
        if signal_id <= self._last_id:
            return
        try:
            conn = sqlite3.connect(self.db_path)
            try:
                cur = conn.execute(
                    "SELECT id, from_id, subject, body, channel FROM messages "
                    "WHERE id > ? AND (LOWER(to_id) = LOWER(?) OR to_id = 'all') "
                    "ORDER BY id ASC",
                    (self._last_id, self.identity),
                )
                rows = cur.fetchall()
            finally:
                conn.close()
        except (OSError, sqlite3.DatabaseError):
            return
        for row in rows:
            msg_id, from_id, subject, body, channel = row
            yield Event(
                source="mail",
                kind="mail_arrived",
                payload={
                    "id": msg_id,
                    "from": from_id,
                    "subject": subject,
                    "body": body,
                    "channel": channel,
                },
            )
            if msg_id > self._last_id:
                self._last_id = msg_id


class ConsoleSource(EventSource):
    """Read text lines from stdin in a background thread; emit console_input events.

    Implements issue #262: CU console surface (sp-5 §4).

    The reader thread blocks on sys.stdin.readline(); the main poll() drains
    a thread-safe queue each tick — so the event loop never blocks on stdin.
    This is WriteConsoleInput-compatible: any process (CU, founder-poke) can
    inject lines into stdin and they arrive here as events.

    output_stream — where console_write tool sends output (default sys.stdout).
    stdin_stream  — injected in tests; default sys.stdin.
    """

    def __init__(
        self,
        output_stream=None,
        stdin_stream=None,
    ) -> None:
        self._out = output_stream or sys.stdout
        self._q: queue.Queue[str] = queue.Queue()
        self._stdin = stdin_stream or sys.stdin
        self._thread = threading.Thread(
            target=self._reader,
            daemon=True,
            name="nck-console-reader",
        )
        self._thread.start()

    def _reader(self) -> None:
        """Background thread: read lines from stdin and put them on the queue."""
        try:
            for line in self._stdin:
                self._q.put(line.rstrip("\n").rstrip("\r"))
        except (OSError, ValueError):
            pass

    def poll(self) -> Iterator[Event]:
        while True:
            try:
                line = self._q.get_nowait()
            except queue.Empty:
                break
            yield Event(
                source="console",
                kind="console_input",
                payload={"line": line},
            )

    def write(self, text: str) -> None:
        """Write text to the output stream (used by console_write tool)."""
        self._out.write(text)
        self._out.flush()


def _tool_console_write(console_source, text: str = "") -> dict[str, Any]:
    """Write text to the CU console output.  Registered as 'console_write' tool."""
    if console_source is None:
        return {"written": False, "reason": "no console source configured"}
    console_source.write(text)
    return {"written": True, "chars": len(text)}


# ---------------------------------------------------------------------------
# Stub core — pure function: event -> list[Action]
# Rule-based; NO model; trivially swappable for the real model core.
# ---------------------------------------------------------------------------

# Patterns that trigger gate-note actions
_RECEIPT_GATE_PATTERNS = (".json",)
_BROADCAST_IGNORE_PATTERNS = ("broadcast-",)


def stub_core(event: Event, registry: ToolRegistry) -> list[Action]:
    """Stub decision core.  Pure function; no I/O; no model.

    Rules (C10 §2 — each event class dispatched to write_event_receipt):
    1. Mail arrived -> write_event_receipt (mail class).
    2. Job receipt file arriving (.json) -> write_gate_note + write_event_receipt.
    3. File_watch: broadcast marker -> ignore (selectivity); other files -> write_event_receipt.
    4. Schedule tick_due -> write_gate_note + write_event_receipt.
    5. Console input -> console_write (echo) + write_event_receipt.

    This stub is the swappable boundary: replace this function with the
    real model-backed core without touching the loop machinery.
    """
    actions: list[Action] = []

    if event.source == "mail" and event.kind == "mail_arrived":
        mail_id = event.payload.get("id")
        from_id = event.payload.get("from", "")
        subject = event.payload.get("subject", "")
        if "write_event_receipt" in registry.known_verbs():
            actions.append(Action(
                verb="write_event_receipt",
                args={
                    "event_source": "mail",
                    "event_kind": "mail_arrived",
                    "event_id": mail_id,
                    "event_from": from_id,
                    "event_subject": subject,
                },
                event_ref=event,
            ))

    elif event.source == "job_receipt" and event.kind == "receipt_arrived":
        path = event.payload.get("path", "")
        if any(path.endswith(p) for p in _RECEIPT_GATE_PATTERNS):
            if "write_gate_note" in registry.known_verbs():
                actions.append(Action(
                    verb="write_gate_note",
                    args={"receipt_path": path, "event_ts": event.ts},
                    event_ref=event,
                ))
            if "write_event_receipt" in registry.known_verbs():
                actions.append(Action(
                    verb="write_event_receipt",
                    args={
                        "event_source": "job_receipt",
                        "event_kind": "receipt_arrived",
                        "event_path": path,
                    },
                    event_ref=event,
                ))

    elif event.source == "file_watch":
        path = event.payload.get("path", "")
        basename = os.path.basename(path)
        if any(basename.startswith(p) for p in _BROADCAST_IGNORE_PATTERNS):
            pass  # selective: broadcast files -> no action
        elif "write_event_receipt" in registry.known_verbs():
            actions.append(Action(
                verb="write_event_receipt",
                args={
                    "event_source": "file_watch",
                    "event_kind": event.kind,
                    "event_path": path,
                },
                event_ref=event,
            ))

    elif event.source == "schedule" and event.kind == "tick_due":
        sched_id = event.payload.get("id", "unknown")
        if "write_gate_note" in registry.known_verbs():
            actions.append(Action(
                verb="write_gate_note",
                args={"schedule_id": sched_id, "event_ts": event.ts},
                event_ref=event,
            ))
        if "write_event_receipt" in registry.known_verbs():
            actions.append(Action(
                verb="write_event_receipt",
                args={
                    "event_source": "schedule",
                    "event_kind": "tick_due",
                    "schedule_id": sched_id,
                },
                event_ref=event,
            ))

    elif event.source == "console" and event.kind == "console_input":
        line = event.payload.get("line", "")
        if "console_write" in registry.known_verbs():
            actions.append(Action(
                verb="console_write",
                args={"text": f"[ember] received: {line}\n"},
                event_ref=event,
            ))
        if "write_event_receipt" in registry.known_verbs():
            actions.append(Action(
                verb="write_event_receipt",
                args={
                    "event_source": "console",
                    "event_kind": "console_input",
                    "event_subject": line[:120],
                },
                event_ref=event,
            ))

    return actions


# ---------------------------------------------------------------------------
# Crash-safe journal (append-only JSONL, before/after markers)
# ---------------------------------------------------------------------------

class Journal:
    """Append-only crash-safe journal.

    Protocol (per action):
      1. Append BEFORE record (status="pending") BEFORE executing.
      2. Execute action.
      3. Append AFTER record (status="applied") AFTER executing.

    On restart: scan for pending records that have no matching applied record
    => skip those actions (idempotence: if applied marker missing, action
    may or may not have run; the loop re-queues only non-applied).
    A stricter approach (used here): pending without applied = re-execute
    is only safe if actions are idempotent. Since write_gate_note is
    idempotent (fixed path, same content), this is safe for this stub set.
    The real core must audit per-verb idempotence before relying on replay.
    """

    def __init__(self, path: str) -> None:
        self.path = path
        self._applied: set[str] = set()
        self._load_applied()

    def _load_applied(self) -> None:
        if not os.path.isfile(self.path):
            return
        with open(self.path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec.get("status") == "applied":
                    self._applied.add(rec.get("action_id", ""))

    def action_id(self, action: Action) -> str:
        """Stable ID for an action (content-hash of verb + stable args).

        event_ts is EXCLUDED: it is a wallclock timestamp that changes each
        time the same source file / schedule entry is polled after a restart,
        which would break exactly-once deduplication across process restarts.
        Stable identity = what (verb) + where/which (receipt_path, schedule_id,
        event_path, etc.) — NOT when it was triggered.
        """
        stable_args = {k: v for k, v in action.args.items() if k != "event_ts"}
        blob = json.dumps({
            "verb": action.verb,
            "args": stable_args,
        }, sort_keys=True)
        return hashlib.sha256(blob.encode()).hexdigest()[:16]

    def is_applied(self, action_id: str) -> bool:
        return action_id in self._applied

    def write_before(self, action: Action, action_id: str) -> None:
        self._append({
            "status": "pending",
            "action_id": action_id,
            "verb": action.verb,
            "args": action.args,
            "ts": _ts(),
        })

    def write_after(self, action: Action, action_id: str) -> None:
        self._append({
            "status": "applied",
            "action_id": action_id,
            "verb": action.verb,
            "ts": _ts(),
        })
        self._applied.add(action_id)

    def _append(self, record: dict[str, Any]) -> None:
        line = json.dumps(record, sort_keys=True) + "\n"
        with open(self.path, "a", encoding="utf-8", newline="\n") as f:
            f.write(line)
            f.flush()
            os.fsync(f.fileno())


# ---------------------------------------------------------------------------
# Invariant config validation (fail-closed)
# ---------------------------------------------------------------------------

_REQUIRED_GOVERNOR_KEYS = {"vram_fraction", "margin_gib_floor", "pace_s_per_step"}


def validate_invariant_config(config: dict[str, Any]) -> None:
    """Raise SystemExit if the invariant config block is missing or invalid.

    The loop refuses to start if:
      - 'governor' key absent or missing required fields
      - 'goal_file' key absent
    This is the fail-closed posture required by sp5 §5.
    """
    governor = config.get("governor")
    if not governor:
        raise SystemExit(
            "LOOP_REFUSE: 'governor' block absent from config. "
            "The loop will not start without governor params (sp5 §5 invariant)."
        )
    missing = _REQUIRED_GOVERNOR_KEYS - set(governor.keys())
    if missing:
        raise SystemExit(
            f"LOOP_REFUSE: governor block missing required keys: {sorted(missing)}. "
            "The loop will not start."
        )
    if not config.get("goal_file"):
        raise SystemExit(
            "LOOP_REFUSE: 'goal_file' path absent from config. "
            "The loop will not start without GOAL.md path (sp5 §5 invariant)."
        )


# ---------------------------------------------------------------------------
# Default tool implementations (stdlib-only, no model)
# ---------------------------------------------------------------------------

def _tool_write_gate_note(
    gate_notes_dir: str,
    receipt_path: str = "",
    schedule_id: str = "",
    event_ts: str = "",
) -> dict[str, Any]:
    """Write a gate-note JSONL line to gate_notes_dir/gate-notes.jsonl."""
    os.makedirs(gate_notes_dir, exist_ok=True)
    out_path = os.path.join(gate_notes_dir, "gate-notes.jsonl")
    record = {
        "ts": _ts(),
        "event_ts": event_ts,
        "receipt_path": receipt_path,
        "schedule_id": schedule_id,
    }
    line = json.dumps(record, sort_keys=True) + "\n"
    with open(out_path, "a", encoding="utf-8", newline="\n") as f:
        f.write(line)
        f.flush()
    return {"written": out_path}


def _tool_heartbeat_touch(heartbeat_path: str) -> dict[str, Any]:
    """Touch the heartbeat file (write current timestamp)."""
    os.makedirs(os.path.dirname(heartbeat_path) or ".", exist_ok=True)
    with open(heartbeat_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(_ts() + "\n")
    return {"heartbeat": heartbeat_path, "ts": _ts()}


def _tool_write_event_receipt(
    receipts_dir: str,
    event_source: str = "",
    event_kind: str = "",
    event_id: Any = None,
    event_from: str = "",
    event_subject: str = "",
    event_path: str = "",
    schedule_id: str = "",
) -> dict[str, Any]:
    """Write a per-event receipt JSON to receipts_dir (C10 §2 AC).

    ticket=NCK-EVENT-DISPATCH; required fields: ticket, ts (receipt_check-clean).
    One receipt per dispatched event; filename = nck-event-<source>-<ts>.json.
    Idempotent: if a receipt for the same event already exists (same stable key),
    returns the existing path without overwriting.
    """
    os.makedirs(receipts_dir, exist_ok=True)
    ts_now = _ts()
    # Stable key for idempotence: source + kind + event_id or path-basename or schedule_id.
    # Use basename only for paths — full paths contain colons/backslashes invalid in filenames.
    path_part = os.path.basename(event_path) if event_path else ""
    raw_key = str(event_id) if event_id is not None else (path_part or schedule_id or "nokey")
    # Strip any remaining chars invalid in Windows filenames
    safe_key = "".join(c if c.isalnum() or c in "-_." else "_" for c in raw_key)[:48]
    stable_key = f"{event_source}-{event_kind}-{safe_key}"
    filename = f"nck-event-{stable_key}-{ts_now}.json"
    out_path = os.path.join(receipts_dir, filename)
    receipt = {
        "ticket": "NCK-EVENT-DISPATCH",
        "ts": ts_now,
        "event_source": event_source,
        "event_kind": event_kind,
    }
    if event_id is not None:
        receipt["event_id"] = event_id
    if event_from:
        receipt["event_from"] = event_from
    if event_subject:
        receipt["event_subject"] = event_subject
    if event_path:
        receipt["event_path"] = event_path
    if schedule_id:
        receipt["schedule_id"] = schedule_id
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(receipt, f, indent=2)
    return {"written": out_path, "ticket": "NCK-EVENT-DISPATCH"}


# ---------------------------------------------------------------------------
# Event loop
# ---------------------------------------------------------------------------

class NCKEventLoop:
    """NC-K resident event-driven loop (skeleton).

    Config keys:
      governor         : {vram_fraction, margin_gib_floor, pace_s_per_step}  (placeholder)
      goal_file        : path to GOAL.md (boot-time invariant check)
      heartbeat_file   : path to touch every tick
      journal_path     : path to nck-journal.jsonl
      gate_notes_dir   : dir for write_gate_note output
      poll_interval_s  : seconds to sleep between poll rounds (default 1.0)

    Construct, add sources, add hooks, call run().
    """

    def __init__(self, config: dict[str, Any]) -> None:
        validate_invariant_config(config)
        # Boot-checksum layer (issue #261): verify protected-path checksums.
        # Fail-closed: any mismatch -> SystemExit naming the mismatched path.
        # skip_invariant_check is a test-only escape hatch (selftest fixtures use
        # temp dirs where the protected paths do not exist).
        if not config.get("_skip_invariant_check", False):
            _verify_at_boot()
        self.config = config
        self.registry = ToolRegistry()
        self.sources: list[EventSource] = []
        self.pre_action_hooks: list[Callable[[Action], None]] = []
        self.post_action_hooks: list[Callable[[Action, Any], None]] = []

        # Journal
        journal_path = config.get("journal_path", "state/nck-journal.jsonl")
        self.journal = Journal(journal_path)

        # Heartbeat
        self.heartbeat_file = config.get("heartbeat_file", "state/nck-heartbeat.txt")

        # Poll interval
        self.poll_interval_s = float(config.get("poll_interval_s", 1.0))

        # Register built-in tools
        gate_notes_dir = config.get("gate_notes_dir", "state/nck-gate-notes")
        self.registry.register(
            "write_gate_note",
            lambda **kw: _tool_write_gate_note(gate_notes_dir, **kw),
            schema={
                "receipt_path": {"type": "string", "default": ""},
                "schedule_id": {"type": "string", "default": ""},
                "event_ts": {"type": "string", "default": ""},
            },
            concurrency_safe=True,
            read_only=False,
            permission_class="default",
        )
        self.registry.register(
            "heartbeat_touch",
            lambda **kw: _tool_heartbeat_touch(self.heartbeat_file, **kw),
            schema={},
            concurrency_safe=True,
            read_only=False,
            permission_class="default",
        )

        # CU console (issue #262): registered always; effective when console source present.
        # _console_source is set by add_source() when a ConsoleSource is added.
        self._console_source: ConsoleSource | None = None
        self.registry.register(
            "console_write",
            lambda **kw: _tool_console_write(self._console_source, **kw),
            schema={"text": {"type": "string", "default": ""}},
            concurrency_safe=True,
            read_only=False,
            permission_class="default",
        )

        # write_event_receipt: per-event dispatch receipt (C10 §2 AC)
        event_receipts_dir = config.get("event_receipts_dir", "state/nck-event-receipts")
        self.registry.register(
            "write_event_receipt",
            lambda **kw: _tool_write_event_receipt(event_receipts_dir, **kw),
            schema={
                "event_source": {"type": "string", "default": ""},
                "event_kind": {"type": "string", "default": ""},
                "event_id": {"default": None},
                "event_from": {"type": "string", "default": ""},
                "event_subject": {"type": "string", "default": ""},
                "event_path": {"type": "string", "default": ""},
                "schedule_id": {"type": "string", "default": ""},
            },
            concurrency_safe=True,
            read_only=False,
            permission_class="default",
        )

    def add_source(self, source: EventSource) -> None:
        self.sources.append(source)
        if isinstance(source, ConsoleSource):
            self._console_source = source

    def run(self, max_ticks: int = 0) -> None:
        """Run the event loop.
        max_ticks=0 means run forever (perpetual resident).
        max_ticks>0 runs exactly that many poll rounds (for testing).

        C10 §3 — RSS cap: if rss_cap_mib is set in config and psutil is available,
        exit with code 2 when the process RSS exceeds the cap.
        C10 §5 — kill-switch: if kill_flag path is set and the file exists, exit cleanly.
        """
        rss_cap_bytes = int(self.config.get("rss_cap_mib", 0)) * 1024 * 1024
        kill_flag_path = self.config.get("kill_flag", "")

        tick = 0
        while True:
            tick += 1

            # Kill-switch check (C10 §5): sentinel file presence → clean exit
            if kill_flag_path and os.path.isfile(kill_flag_path):
                sys.exit(0)

            # RSS cap check (C10 §3): exit(2) on breach
            if rss_cap_bytes > 0 and _psutil is not None:
                rss = _psutil.Process().memory_info().rss
                if rss > rss_cap_bytes:
                    sys.exit(2)

            # Touch heartbeat every tick (fail-closed: if this raises, let it propagate)
            _tool_heartbeat_touch(self.heartbeat_file)

            # Poll all sources
            events: list[Event] = []
            for source in self.sources:
                try:
                    events.extend(source.poll())
                except NotImplementedError:
                    pass

            # For each event, run the stub core to get actions
            for event in events:
                actions = stub_core(event, self.registry)

                for action in actions:
                    action_id = self.journal.action_id(action)

                    # Resume from journal: skip already-applied actions
                    if self.journal.is_applied(action_id):
                        continue

                    # Pre-action hooks
                    for hook in self.pre_action_hooks:
                        hook(action)

                    # Write BEFORE marker (crash-safe: written before execution)
                    self.journal.write_before(action, action_id)

                    # Dispatch through registry (unknown verb -> ValueError)
                    try:
                        result = self.registry.dispatch(action)
                    except ValueError as exc:
                        # Unknown verb: refuse, write a refusal note, continue
                        refusal = {
                            "status": "refused",
                            "action_id": action_id,
                            "verb": action.verb,
                            "reason": str(exc),
                            "ts": _ts(),
                        }
                        self.journal._append(refusal)
                        continue

                    # Write AFTER marker (applied)
                    self.journal.write_after(action, action_id)

                    # Post-action hooks
                    for hook in self.post_action_hooks:
                        hook(action, result)

            if max_ticks > 0 and tick >= max_ticks:
                break

            if max_ticks == 0:
                time.sleep(self.poll_interval_s)
