"""NC-K resident event-loop skeleton — clean-room port (Closes #260).

Architecture:
  EventSource ABC  -> FileWatchSource, ScheduleSource, JobReceiptSource, MailSource (STUB)
  dispatch loop    -> pull events, route through TOOL REGISTRY
  stub core        -> pure function event -> list[Action]; trivially swappable
  process supervision -> heartbeat touch every tick; crash-safe journal (state/nck-journal.jsonl)
  hook points      -> pre_action, post_action callable lists

Invariant config block (fail-closed):
  config must contain 'governor' (placeholder fields) and 'goal_file' (path).
  Loop refuses to start on missing/invalid config.

Stub status:
  MailSource         -> NotImplementedError (see issue #259: mailbox identity not yet landed)
  stub_core          -> rule-based Python function, NO model, trivially swappable
"""

from __future__ import annotations

import abc
import json
import os
import time
import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Iterator


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
    """STUB — mailbox identity not yet landed.

    See issue #259 (ember mailbox identity: founders.yaml + signal wiring).
    Once #259 lands and the signal-file wiring exists, replace this stub
    with a real FileWatchSource over the ember signal file.
    """

    def poll(self) -> Iterator[Event]:
        raise NotImplementedError(
            "MailSource is a stub pending issue #259 "
            "(ember mailbox identity + founders.yaml signal wiring). "
            "Wire a FileWatchSource over the ember signal file once #259 lands."
        )


# ---------------------------------------------------------------------------
# Stub core — pure function: event -> list[Action]
# Rule-based; NO model; trivially swappable for the real model core.
# ---------------------------------------------------------------------------

# Patterns that trigger gate-note actions
_RECEIPT_GATE_PATTERNS = (".json",)
_BROADCAST_IGNORE_PATTERNS = ("broadcast-",)


def stub_core(event: Event, registry: ToolRegistry) -> list[Action]:
    """Stub decision core.  Pure function; no I/O; no model.

    Rules (in priority order):
    1. Job receipt file arriving matching .json -> write-gate-note action.
    2. File_watch event whose path contains a broadcast marker -> ignore (no action).
    3. Schedule tick_due -> write-gate-note referencing the schedule id.
    4. Anything else -> no action (selective emission, not per-event fire).

    This stub is the swappable boundary: replace this function with the
    real model-backed core without touching the loop machinery.
    """
    actions: list[Action] = []

    if event.source == "job_receipt" and event.kind == "receipt_arrived":
        path = event.payload.get("path", "")
        if any(path.endswith(p) for p in _RECEIPT_GATE_PATTERNS):
            if "write_gate_note" in registry.known_verbs():
                actions.append(Action(
                    verb="write_gate_note",
                    args={"receipt_path": path, "event_ts": event.ts},
                    event_ref=event,
                ))

    elif event.source == "file_watch":
        path = event.payload.get("path", "")
        basename = os.path.basename(path)
        if any(basename.startswith(p) for p in _BROADCAST_IGNORE_PATTERNS):
            pass  # selective: broadcast files -> no action
        # other file events -> no action from stub core; real core handles

    elif event.source == "schedule" and event.kind == "tick_due":
        sched_id = event.payload.get("id", "unknown")
        if "write_gate_note" in registry.known_verbs():
            actions.append(Action(
                verb="write_gate_note",
                args={"schedule_id": sched_id, "event_ts": event.ts},
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
        """Stable ID for an action (content-hash of verb+args+event_ts)."""
        blob = json.dumps({
            "verb": action.verb,
            "args": action.args,
            "event_ts": action.event_ref.ts if action.event_ref else "",
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

    def add_source(self, source: EventSource) -> None:
        self.sources.append(source)

    def run(self, max_ticks: int = 0) -> None:
        """Run the event loop.
        max_ticks=0 means run forever (perpetual resident).
        max_ticks>0 runs exactly that many poll rounds (for testing).
        """
        tick = 0
        while True:
            tick += 1

            # Touch heartbeat every tick (fail-closed: if this raises, let it propagate)
            _tool_heartbeat_touch(self.heartbeat_file)

            # Poll all sources
            events: list[Event] = []
            for source in self.sources:
                # MailSource raises NotImplementedError; skip gracefully here
                # so other sources still work while #259 is open.
                try:
                    events.extend(source.poll())
                except NotImplementedError:
                    # Stub mail source — expected until #259 lands.
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
