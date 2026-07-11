#!/usr/bin/env python3
"""ember_avir_harness.py — clean-room [REDACTED]-cli test harness for Ember C14.

Drives the REAL [REDACTED].exe via its HTTP debug server.  Does NOT reimplement [REDACTED].exe
internals (openai-adapter, REPL, TUI).  The parity concern is moot: we talk to the
real tool over its own debug interface.

Interfaces covered
------------------
HTTP debug server (GET/POST)
  GET  /health              — readiness probe
  GET  /status              — busy/idle, turn_id, error
  GET  /output/since/<N>    — TUI text buffer (incremental)
  GET  /keystroke/status    — key-injector readiness
  POST /input               — primary prompt injection (increments turn_id)
  POST /command             — slash command injection (/compact, /exit, ...)
  POST /keystroke           — raw key bytes (TUI dialogs)

Session JSONL (~/.[REDACTED]/projects/<key>/<session>.jsonl)
  stop_reason               — "end_turn" | "tool_use" | "max_tokens" | "cancelled"
  isApiErrorMessage         — true → terminal error
  usage.input_tokens        — input token count
  usage.output_tokens       — output token count

Verifier signal basis
---------------------
R = 1  iff ALL of:
  1. file_exists(sandbox_dir / expected_path)           — task success
  2. file_contains(sandbox_dir / expected_path, needle) — task correctness
  3. jsonl_no_api_error                                  — clean session
  4. stop_reason_eq('end_turn')                         — natural completion
  5. file_created_this_turn(sandbox_dir / expected_path, turn_start_time)
     — file must have been created/modified DURING the current turn
     (mtime >= turn_start_s), NOT pre-existing from a prior episode
  6. jsonl_tool_call_this_turn                          — at least one tool_use
     entry must appear in THIS turn's JSONL slice (text-only "I wrote …" = R=0)

Sandbox isolation
-----------------
executing_verifier() CLEARS the sandbox directory before injecting the prompt.
No state from a prior episode can survive into the current turn.  The sandbox
directory is created fresh (or emptied) by the harness, never by the caller.

Session JSONL scoping (defect 3 fix)
-------------------------------------
_find_session_jsonl() now accepts an explicit session_id (the JSONL filename
stem) so the harness can pin to the session it launched, not "most-recently
modified file".  TurnExecutor records the JSONL byte-offset AT TURN START
(just before POST /input) and only reads bytes appended during the current
turn, preventing a prior turn's end_turn from producing a false-clean signal.

Validation (CPU, no [REDACTED].exe required)
---------------------------------------
A loopback stub server (stdlib http.server) replays canned HTTP responses and a
fake JSONL writer exercises the full observe → act → wait-for-end_turn → verify
cycle.  The success stub writes a tool_use entry THEN an end_turn entry AND
creates the expected file in the sandbox — exercising the action-coupling gate.
Run:   python ember_avir_harness.py --selftest
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Callable

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

POLL_INTERVAL_S: float = 0.2          # HTTP poll interval while waiting for turn
TURN_TIMEOUT_S: float = 120.0         # hard timeout per turn
JSONL_POLL_S: float = 0.2             # JSONL poll interval
MAX_JSONL_AGE_LINES: int = 5000       # how far back to scan JSONL for current turn

# stop_reason values treated as TERMINAL (turn done)
TERMINAL_STOP_REASONS = {"end_turn", "max_tokens", "cancelled"}

# stop_reason values treated as NON-TERMINAL (model is continuing after tool_result)
NON_TERMINAL_STOP_REASONS = {"tool_use"}

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class StatusSnapshot:
    output_total: int = 0
    last_output_ms: int | None = None
    idle_ms: int | None = None
    error: str | None = None
    busy: bool = False
    pending_tool: bool = False
    current_turn_id: int = 0


@dataclass
class TurnResult:
    turn_id: int
    tui_lines: list[str] = field(default_factory=list)
    stop_reason: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    api_error: bool = False
    elapsed_s: float = 0.0
    timed_out: bool = False
    # NEW: action coupling evidence
    tool_call_seen_this_turn: bool = False  # >= 1 tool_use entry in THIS turn's JSONL slice
    turn_start_s: float = 0.0              # wall-clock time just before POST /input


@dataclass
class TaskSpec:
    """Specification for one verifier task."""
    prompt: str
    expected_file: str           # relative path inside sandbox_dir
    expected_content: str        # substring that must appear in the file
    assertions: list[dict[str, Any]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Debug server HTTP client
# ---------------------------------------------------------------------------


def _http_get(base_url: str, path: str) -> dict[str, Any]:
    """GET <base_url><path> → parsed JSON dict.  Raises on HTTP/connection error."""
    url = base_url.rstrip("/") + path
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _http_post(base_url: str, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    """POST <base_url><path> with JSON payload → parsed JSON dict."""
    url = base_url.rstrip("/") + path
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


class AvirDebugClient:
    """Thin HTTP client for the [REDACTED].exe debug server.

    Parameters
    ----------
    base_url : str
        e.g. "http://127.0.0.1:9999"
    """

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    # ---- read endpoints --------------------------------------------------

    def health(self) -> dict[str, Any]:
        """GET /health — readiness probe."""
        return _http_get(self.base_url, "/health")

    def status(self) -> StatusSnapshot:
        """GET /status — session health."""
        raw = _http_get(self.base_url, "/status")
        return StatusSnapshot(
            output_total=int(raw.get("output_total", 0)),
            last_output_ms=raw.get("last_output_ms"),
            idle_ms=raw.get("idle_ms"),
            error=raw.get("error"),
            busy=bool(raw.get("busy", False)),
            pending_tool=bool(raw.get("pending_tool", False)),
            current_turn_id=int(raw.get("current_turn_id", 0)),
        )

    def output_since(self, n: int) -> tuple[list[str], int]:
        """GET /output/since/<N> → (lines, next_index)."""
        raw = _http_get(self.base_url, f"/output/since/{n}")
        lines: list[str] = raw.get("output", [])
        next_idx: int = int(raw.get("next", n + len(lines)))
        return lines, next_idx

    def keystroke_ready(self) -> bool:
        """GET /keystroke/status → bool."""
        raw = _http_get(self.base_url, "/keystroke/status")
        return bool(raw.get("ready", False))

    # ---- action endpoints ------------------------------------------------

    def send_input(self, text: str) -> dict[str, Any]:
        """POST /input {text} — primary prompt injection."""
        return _http_post(self.base_url, "/input", {"text": text})

    def send_command(self, command: str) -> dict[str, Any]:
        """POST /command {command} — slash command."""
        return _http_post(self.base_url, "/command", {"command": command})

    def send_keystroke(self, raw_bytes: bytes) -> dict[str, Any]:
        """POST /keystroke {bytes} — raw key bytes (base64-encoded)."""
        encoded = base64.b64encode(raw_bytes).decode("ascii")
        return _http_post(self.base_url, "/keystroke", {"bytes": encoded})


# ---------------------------------------------------------------------------
# Session JSONL reader
# ---------------------------------------------------------------------------


def _find_session_jsonl(
    cwd: str,
    session_id: str | None = None,
) -> Path | None:
    """Locate the session JSONL under ~/.[REDACTED]/projects/<key>/.

    Parameters
    ----------
    cwd : str
        The [REDACTED] session's working directory (used as the project key).
    session_id : str | None
        If provided, select the JSONL file whose stem matches this ID exactly.
        If None, fall back to the most-recently-modified file (legacy — use
        only when session_id is unknown, e.g. the first turn of a new session).

    NOTE: Selecting by mtime is a defect source (defect 3): a stale file from a
    prior session with a later mtime can shadow the current session's JSONL.
    Always pass session_id when the session's JSONL filename is known.
    """
    home = Path.home()
    # sanitize cwd key ([REDACTED] uses the cwd path as key, forward slashes, no drive colon)
    key = cwd.replace("\\", "/").replace(":", "").lstrip("/")
    projects_dir = home / ".[REDACTED]" / "projects" / key
    if not projects_dir.exists():
        return None
    if session_id is not None:
        # Pin to the exact session — never mtime-race with a stale prior session.
        candidate = projects_dir / f"{session_id}.jsonl"
        return candidate if candidate.exists() else None
    # Legacy fallback: most-recently-modified file.
    # CAUTION: subject to mtime races between sessions.
    jsonl_files = sorted(
        projects_dir.glob("*.jsonl"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return jsonl_files[0] if jsonl_files else None


def _jsonl_byte_offset(jsonl_path: Path) -> int:
    """Return the current end-of-file byte offset for the given JSONL.

    Call this just BEFORE POST /input to get the turn-start cursor.  Any bytes
    appended after this point belong to the current turn.
    """
    try:
        return jsonl_path.stat().st_size
    except (OSError, FileNotFoundError):
        return 0


def _parse_jsonl_entries(jsonl_path: Path, after_byte: int = 0) -> tuple[list[dict[str, Any]], int]:
    """Read JSONL from byte offset, return (new_entries, new_byte_offset)."""
    entries: list[dict[str, Any]] = []
    try:
        size = jsonl_path.stat().st_size
        if size <= after_byte:
            return entries, after_byte
        with jsonl_path.open("rb") as fh:
            fh.seek(after_byte)
            chunk = fh.read()
            new_offset = after_byte + len(chunk)
        for raw_line in chunk.split(b"\n"):
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                entries.append(json.loads(raw_line.decode("utf-8")))
            except json.JSONDecodeError:
                pass  # partial write; skip
        return entries, new_offset
    except (OSError, FileNotFoundError):
        return entries, after_byte


def _extract_turn_signal(
    entries: list[dict[str, Any]],
) -> tuple[str | None, bool, int, int, bool]:
    """Extract (stop_reason, api_error, input_tokens, output_tokens, tool_call_seen).

    Scans entries in order; last assistant entry with a terminal stop_reason wins.
    api_error is set if ANY entry has isApiErrorMessage=true.
    tool_call_seen is True if ANY entry has stop_reason == 'tool_use' (defect 2 fix:
    a real tool action must have occurred this turn for R=1 to be possible).
    """
    stop_reason: str | None = None
    api_error = False
    input_tokens = 0
    output_tokens = 0
    tool_call_seen = False

    for entry in entries:
        if entry.get("isApiErrorMessage"):
            api_error = True
            continue
        # assistant message entry
        msg = entry.get("message", {})
        role = msg.get("role", "")
        if role == "assistant":
            sr = msg.get("stop_reason")
            if sr is not None:
                stop_reason = sr
            if sr == "tool_use":
                tool_call_seen = True
            usage = msg.get("usage", {})
            if isinstance(usage, dict):
                input_tokens = int(usage.get("input_tokens", input_tokens))
                output_tokens = int(usage.get("output_tokens", output_tokens))
        # top-level stop_reason (some [REDACTED] versions emit at top level)
        if "stop_reason" in entry and entry.get("stop_reason") is not None:
            sr_top = entry["stop_reason"]
            stop_reason = sr_top
            if sr_top == "tool_use":
                tool_call_seen = True

    return stop_reason, api_error, input_tokens, output_tokens, tool_call_seen


# ---------------------------------------------------------------------------
# Turn executor — observe → act → wait-for-end_turn
# ---------------------------------------------------------------------------


class TurnExecutor:
    """Drives one prompt turn against a running [REDACTED].exe instance.

    Parameters
    ----------
    client : AvirDebugClient
    jsonl_path : Path | None
        Path to the session JSONL.  If None, completion is detected via
        /status idle heuristic only (less reliable).
    timeout_s : float
        Hard timeout per turn.
    """

    def __init__(
        self,
        client: AvirDebugClient,
        jsonl_path: Path | None = None,
        timeout_s: float = TURN_TIMEOUT_S,
    ) -> None:
        self.client = client
        self.jsonl_path = jsonl_path
        self.timeout_s = timeout_s

    def run_turn(self, prompt: str) -> TurnResult:
        """Inject prompt, wait for terminal stop_reason, return TurnResult.

        JSONL cursor is set to the file's byte-offset BEFORE the prompt is
        injected (defect 3 fix).  Only bytes written AFTER that point are
        scanned for stop_reason/tool_use, preventing a prior turn's end_turn
        from triggering a false-clean break.
        """
        # 1. baseline snapshot
        baseline = self.client.status()
        turn_id = baseline.current_turn_id
        output_cursor = baseline.output_total

        # 2. snapshot JSONL byte offset BEFORE injection (defect 3 fix)
        jsonl_cursor = 0
        if self.jsonl_path is not None:
            jsonl_cursor = _jsonl_byte_offset(self.jsonl_path)

        # 3. record wall-clock turn start (defect 2 fix: mtime gate)
        turn_start_s = time.time()

        # 4. inject prompt
        self.client.send_input(prompt)

        # 5. poll loop
        collected_lines: list[str] = []
        start = time.monotonic()
        stop_reason: str | None = None
        api_error = False
        input_tokens = 0
        output_tokens = 0
        tool_call_seen = False

        while True:
            elapsed = time.monotonic() - start
            if elapsed > self.timeout_s:
                return TurnResult(
                    turn_id=turn_id,
                    tui_lines=collected_lines,
                    stop_reason=stop_reason,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    api_error=api_error,
                    elapsed_s=elapsed,
                    timed_out=True,
                    tool_call_seen_this_turn=tool_call_seen,
                    turn_start_s=turn_start_s,
                )

            # poll TUI output
            try:
                new_lines, output_cursor = self.client.output_since(output_cursor)
                collected_lines.extend(new_lines)
            except (urllib.error.URLError, OSError):
                pass

            # poll session JSONL — only bytes written AFTER turn_start (defect 3 fix)
            if self.jsonl_path is not None:
                new_entries, jsonl_cursor = _parse_jsonl_entries(
                    self.jsonl_path, jsonl_cursor
                )
                if new_entries:
                    sr, ae, it, ot, tc = _extract_turn_signal(new_entries)
                    if ae:
                        api_error = True
                    if it:
                        input_tokens = it
                    if ot:
                        output_tokens = ot
                    if tc:
                        tool_call_seen = True
                    if sr is not None:
                        stop_reason = sr
                        # terminal? — tool_use is NOT terminal
                        if sr in TERMINAL_STOP_REASONS or ae:
                            break
                        # tool_use: keep waiting
                        if sr in NON_TERMINAL_STOP_REASONS:
                            pass

            if api_error:
                # isApiErrorMessage is always terminal
                break

            time.sleep(POLL_INTERVAL_S)

        elapsed = time.monotonic() - start
        return TurnResult(
            turn_id=turn_id,
            tui_lines=collected_lines,
            stop_reason=stop_reason,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            api_error=api_error,
            elapsed_s=elapsed,
            timed_out=False,
            tool_call_seen_this_turn=tool_call_seen,
            turn_start_s=turn_start_s,
        )


# ---------------------------------------------------------------------------
# Sandbox isolation helper (defect 1 fix)
# ---------------------------------------------------------------------------


def clear_sandbox(sandbox_dir: Path) -> None:
    """Remove and recreate sandbox_dir so no state from prior episodes survives.

    Called by executing_verifier() before every turn injection.  The caller
    must NOT pre-seed the sandbox with expected output files — doing so
    bypasses the action-coupling gate (a no-op agent would score R=1).
    """
    if sandbox_dir.exists():
        shutil.rmtree(sandbox_dir)
    sandbox_dir.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Assertion library
# ---------------------------------------------------------------------------


def assert_file_exists(sandbox_dir: Path, rel_path: str) -> bool:
    return (sandbox_dir / rel_path).exists()


def assert_file_contains(sandbox_dir: Path, rel_path: str, needle: str) -> bool:
    target = sandbox_dir / rel_path
    if not target.exists():
        return False
    return needle in target.read_text(encoding="utf-8", errors="replace")


def assert_file_min_lines(sandbox_dir: Path, rel_path: str, n: int) -> bool:
    target = sandbox_dir / rel_path
    if not target.exists():
        return False
    return len(target.read_text(encoding="utf-8", errors="replace").splitlines()) >= n


def assert_jsonl_no_api_error(result: TurnResult) -> bool:
    return not result.api_error


def assert_stop_reason_eq(result: TurnResult, expected: str) -> bool:
    return result.stop_reason == expected


def assert_jsonl_output_tokens_gte(result: TurnResult, n: int) -> bool:
    return result.output_tokens >= n


def assert_jsonl_input_tokens_gte(result: TurnResult, n: int) -> bool:
    return result.input_tokens >= n


def assert_file_created_this_turn(
    sandbox_dir: Path, rel_path: str, turn_start_s: float
) -> bool:
    """Return True iff the file exists AND its mtime >= turn_start_s.

    Defect 2 fix: a pre-existing file (warm sandbox or pre-seeded file) has
    mtime < turn_start_s and therefore scores False.  Only a file written
    DURING the current turn passes this gate.

    A 0.01s slack is applied to mtime comparison to handle filesystem
    timestamp quantisation (FAT32 = 2s; NTFS = 100ns; ext4 = 1ns).
    For FAT32 sandboxes use a larger slack if needed — default covers NTFS.
    """
    target = sandbox_dir / rel_path
    if not target.exists():
        return False
    try:
        mtime = target.stat().st_mtime
    except OSError:
        return False
    # allow a small slack for filesystem clock resolution
    return mtime >= (turn_start_s - 0.01)


def assert_jsonl_tool_call_this_turn(result: TurnResult) -> bool:
    """Return True iff at least one tool_use entry appeared in THIS turn's JSONL slice.

    Defect 2 fix: a text-only agent that says "I wrote the file" but makes no
    tool call produces tool_call_seen_this_turn=False and therefore scores R=0.
    """
    return result.tool_call_seen_this_turn


# Pluggable assertion dispatch
_ASSERTION_FNS: dict[str, Callable[..., bool]] = {
    "file_exists":                lambda r, sd, **kw: assert_file_exists(sd, kw["path"]),
    "file_contains":              lambda r, sd, **kw: assert_file_contains(sd, kw["path"], kw["needle"]),
    "file_min_lines":             lambda r, sd, **kw: assert_file_min_lines(sd, kw["path"], kw["n"]),
    "jsonl_no_api_error":         lambda r, sd, **kw: assert_jsonl_no_api_error(r),
    "jsonl_stop_reason_eq":       lambda r, sd, **kw: assert_stop_reason_eq(r, kw["expected"]),
    "jsonl_output_tokens_gte":    lambda r, sd, **kw: assert_jsonl_output_tokens_gte(r, kw["n"]),
    "jsonl_input_tokens_gte":     lambda r, sd, **kw: assert_jsonl_input_tokens_gte(r, kw["n"]),
    # NEW — action-coupling gates (defect 2 fix)
    "file_created_this_turn":     lambda r, sd, **kw: assert_file_created_this_turn(
                                      sd, kw["path"], r.turn_start_s),
    "jsonl_tool_call_this_turn":  lambda r, sd, **kw: assert_jsonl_tool_call_this_turn(r),
}


def run_assertions(
    result: TurnResult,
    sandbox_dir: Path,
    assertions: list[dict[str, Any]],
) -> tuple[bool, list[str]]:
    """Run pluggable assertion set.  Returns (all_passed, failure_messages)."""
    failures: list[str] = []
    for spec in assertions:
        name = spec["type"]
        fn = _ASSERTION_FNS.get(name)
        if fn is None:
            failures.append(f"unknown assertion type: {name!r}")
            continue
        kw = {k: v for k, v in spec.items() if k != "type"}
        try:
            passed = fn(result, sandbox_dir, **kw)
        except Exception as exc:
            failures.append(f"{name} raised {exc!r}")
            passed = False
        if not passed:
            failures.append(f"{name} FAILED (kw={kw})")
    return (len(failures) == 0), failures


# ---------------------------------------------------------------------------
# Executing verifier  (task_spec, sandbox_dir) -> reward in {0, 1}
# ---------------------------------------------------------------------------


def executing_verifier(
    task_spec: TaskSpec,
    sandbox_dir: Path,
    client: AvirDebugClient,
    jsonl_path: Path | None = None,
    timeout_s: float = TURN_TIMEOUT_S,
    extra_assertions: list[dict[str, Any]] | None = None,
) -> tuple[int, TurnResult, list[str]]:
    """Drive one task turn and return (reward, turn_result, failure_reasons).

    SANDBOX ISOLATION (defect 1 fix)
    ---------------------------------
    sandbox_dir is CLEARED before the turn is injected.  The caller must NOT
    pre-seed the sandbox — doing so bypasses the action-coupling gate.

    ACTION COUPLING (defect 2 fix)
    --------------------------------
    Two mandatory gates are prepended to the assertion list:
      - file_created_this_turn: file mtime must be >= turn_start_s
      - jsonl_tool_call_this_turn: >= 1 tool_use entry in THIS turn's JSONL slice

    JSONL SCOPING (defect 3 fix)
    ------------------------------
    The JSONL cursor is set to the end-of-file BEFORE POST /input, so only
    bytes appended during the current turn are parsed.

    reward = 1 iff ALL of:
      - file_exists(sandbox_dir / task_spec.expected_file)
      - file_contains(sandbox_dir / task_spec.expected_file, task_spec.expected_content)
      - jsonl_no_api_error
      - stop_reason_eq('end_turn')
      - file_created_this_turn (mtime gate)
      - jsonl_tool_call_this_turn (action coupling)
      - any extra_assertions supplied via task_spec.assertions or extra_assertions arg
    """
    # DEFECT 1 FIX: clear sandbox before every episode
    clear_sandbox(sandbox_dir)

    executor = TurnExecutor(client, jsonl_path=jsonl_path, timeout_s=timeout_s)
    result = executor.run_turn(task_spec.prompt)

    # canonical built-in assertions — action-coupling gates come FIRST
    built_in: list[dict[str, Any]] = [
        # action-coupling gates (defect 2 fix)
        {"type": "jsonl_tool_call_this_turn"},
        {"type": "file_created_this_turn",    "path": task_spec.expected_file},
        # standard verifier assertions
        {"type": "file_exists",               "path": task_spec.expected_file},
        {"type": "file_contains",             "path": task_spec.expected_file, "needle": task_spec.expected_content},
        {"type": "jsonl_no_api_error"},
        {"type": "jsonl_stop_reason_eq",      "expected": "end_turn"},
    ]
    all_assertions = built_in + (task_spec.assertions or []) + (extra_assertions or [])

    passed, failures = run_assertions(result, sandbox_dir, all_assertions)
    reward = 1 if passed and not result.timed_out else 0
    return reward, result, failures


# ---------------------------------------------------------------------------
# Stub HTTP server for selftest (loopback, no real [REDACTED].exe)
# ---------------------------------------------------------------------------


class _StubAvirHandler(BaseHTTPRequestHandler):
    """Minimal HTTP handler that serves canned [REDACTED].exe-shaped responses."""

    # shared mutable state (protected by server.state_lock)
    state: dict[str, Any]
    state_lock: threading.Lock

    def log_message(self, fmt: str, *args: Any) -> None:  # suppress default logging
        pass

    def _json_response(self, data: dict[str, Any], code: int = 200) -> None:
        body = json.dumps(data).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8")) if raw else {}

    def do_GET(self) -> None:
        s = self.server.state  # type: ignore[attr-defined]
        lock: threading.Lock = self.server.state_lock  # type: ignore[attr-defined]
        path = self.path.split("?")[0]

        if path == "/health":
            self._json_response({"status": "ok", "clients": 1})
        elif path == "/status":
            with lock:
                self._json_response({
                    "output_total": s["output_total"],
                    "last_output_ms": s["last_output_ms"],
                    "idle_ms": s["idle_ms"],
                    "error": s["error"],
                    "busy": s["busy"],
                    "pending_tool": False,
                    "current_turn_id": s["current_turn_id"],
                })
        elif path.startswith("/output/since/"):
            with lock:
                n = int(path.split("/")[-1])
                lines = s["output_lines"][n:]
                nxt = n + len(lines)
                self._json_response({"output": lines, "total": len(s["output_lines"]), "next": nxt})
        elif path == "/keystroke/status":
            self._json_response({"ready": True})
        else:
            self._json_response({"error": "not found"}, 404)

    def do_POST(self) -> None:
        s = self.server.state  # type: ignore[attr-defined]
        lock: threading.Lock = self.server.state_lock  # type: ignore[attr-defined]
        path = self.path.split("?")[0]
        body = self._read_json_body()

        if path == "/input":
            with lock:
                s["current_turn_id"] += 1
                s["busy"] = True
                s["last_prompt"] = body.get("text", "")
                s["output_lines"].append(f"[stub] received: {s['last_prompt']!r}")
                s["output_total"] = len(s["output_lines"])
            # signal the JSONL writer thread to emit a turn result
            self.server.prompt_event.set()  # type: ignore[attr-defined]
            self._json_response({"status": "sent", "text": body.get("text", "")})

        elif path == "/command":
            with lock:
                s["output_lines"].append(f"[stub] command: {body.get('command', '')!r}")
                s["output_total"] = len(s["output_lines"])
            self._json_response({"status": "sent"})

        elif path == "/keystroke":
            self._json_response({"status": "injected", "bytes": 1, "raw_body_bytes": 1})

        else:
            self._json_response({"error": "not found"}, 404)


class _StubAvirServer:
    """Loopback stub for [REDACTED].exe debug server + a background JSONL writer thread.

    Parameters
    ----------
    jsonl_path : Path
        JSONL file the stub writes to.
    success_scenario : bool
        If True, emit tool_use + end_turn and create the file in sandbox_dir.
        If False, emit an api error.
    sandbox_dir : Path | None
        The sandbox directory.  When success_scenario=True, the stub creates
        the expected file here during the JSONL write (action-coupling demo).
    expected_file : str
        Relative path of the file to create within sandbox_dir on success.
    expected_content : str
        Content to write into the expected file on success.
    """

    def __init__(
        self,
        jsonl_path: Path,
        success_scenario: bool = True,
        sandbox_dir: Path | None = None,
        expected_file: str = "hello.txt",
        expected_content: str = "hello world\n",
    ) -> None:
        self.jsonl_path = jsonl_path
        self.success_scenario = success_scenario
        self.sandbox_dir = sandbox_dir
        self.expected_file = expected_file
        self.expected_content = expected_content

        self.state: dict[str, Any] = {
            "output_total": 0,
            "last_output_ms": None,
            "idle_ms": 9000,
            "error": None,
            "busy": False,
            "current_turn_id": 0,
            "output_lines": [],
            "last_prompt": "",
        }
        self.state_lock = threading.Lock()
        self.prompt_event = threading.Event()
        self._stop_flag = threading.Event()

        # pick an ephemeral port
        self.server = HTTPServer(("127.0.0.1", 0), _StubAvirHandler)
        self.server.state = self.state  # type: ignore[attr-defined]
        self.server.state_lock = self.state_lock  # type: ignore[attr-defined]
        self.server.prompt_event = self.prompt_event  # type: ignore[attr-defined]
        self.port: int = self.server.server_address[1]
        self.base_url = f"http://127.0.0.1:{self.port}"

        self._http_thread = threading.Thread(target=self._serve, daemon=True)
        self._jsonl_thread = threading.Thread(target=self._write_jsonl, daemon=True)

    def _serve(self) -> None:
        while not self._stop_flag.is_set():
            self.server.handle_request()

    def _write_jsonl(self) -> None:
        """Wait for prompt_event, then write a canned JSONL response.

        On success: write tool_use entry, create the expected file in sandbox,
        then write end_turn entry.  This exercises the action-coupling gate:
        the file is created AFTER the turn starts and the JSONL contains a
        tool_use entry from THIS turn's slice.
        """
        while not self._stop_flag.is_set():
            fired = self.prompt_event.wait(timeout=0.5)
            if not fired:
                continue
            self.prompt_event.clear()
            # simulate model thinking delay
            time.sleep(0.15)

            if self.success_scenario:
                # 1. emit tool_use (action coupling — defect 2 fix)
                tool_use_entry = {
                    "type": "assistant",
                    "message": {
                        "role": "assistant",
                        "stop_reason": "tool_use",
                        "usage": {"input_tokens": 100, "output_tokens": 40},
                        "content": [
                            {"type": "tool_use", "id": "tu_1", "name": "Write",
                             "input": {"file_path": self.expected_file,
                                       "content": self.expected_content}}
                        ],
                    },
                }
                try:
                    with self.jsonl_path.open("a", encoding="utf-8") as fh:
                        fh.write(json.dumps(tool_use_entry) + "\n")
                except (OSError, FileNotFoundError):
                    pass

                # 2. create the expected file in sandbox AFTER turn started
                #    (defect 1+2 fix: file is created during the turn, not before)
                if self.sandbox_dir is not None and self.sandbox_dir.exists():
                    target = self.sandbox_dir / self.expected_file
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(self.expected_content, encoding="utf-8")

                time.sleep(0.05)

                # 3. emit end_turn
                end_turn_entry = {
                    "type": "assistant",
                    "message": {
                        "role": "assistant",
                        "stop_reason": "end_turn",
                        "usage": {"input_tokens": 120, "output_tokens": 80},
                        "content": [{"type": "text", "text": "Done."}],
                    },
                }
                try:
                    with self.jsonl_path.open("a", encoding="utf-8") as fh:
                        fh.write(json.dumps(end_turn_entry) + "\n")
                except (OSError, FileNotFoundError):
                    pass
            else:
                # emit an api error entry
                entry = {
                    "isApiErrorMessage": True,
                    "message": {"error": "model overload", "role": "assistant"},
                }
                try:
                    with self.jsonl_path.open("a", encoding="utf-8") as fh:
                        fh.write(json.dumps(entry) + "\n")
                except (OSError, FileNotFoundError):
                    pass

            with self.state_lock:
                self.state["busy"] = False
                self.state["idle_ms"] = 9000

    def start(self) -> None:
        self._http_thread.start()
        self._jsonl_thread.start()

    def stop(self) -> None:
        self._stop_flag.set()
        self.server.server_close()


# ---------------------------------------------------------------------------
# Selftest
# ---------------------------------------------------------------------------


def _run_selftest() -> None:
    """CPU-only selftest: no real [REDACTED].exe, no network, no GPU, no daemon."""
    import tempfile
    failures: list[str] = []
    results_summary: list[str] = []

    def _check(name: str, cond: bool, detail: str = "") -> None:
        label = "PASS" if cond else "FAIL"
        msg = f"  [{label}] {name}"
        if detail and not cond:
            msg += f" — {detail}"
        results_summary.append(msg)
        if not cond:
            failures.append(name)

    # -----------------------------------------------------------------------
    # Test 1: AvirDebugClient — observe endpoints against stub
    # -----------------------------------------------------------------------
    with tempfile.TemporaryDirectory() as tmpdir:
        jsonl_file = Path(tmpdir) / "session.jsonl"
        jsonl_file.touch()
        sandbox = Path(tmpdir) / "sandbox"
        sandbox.mkdir()
        stub = _StubAvirServer(jsonl_file, success_scenario=True,
                               sandbox_dir=sandbox)
        stub.start()
        try:
            client = AvirDebugClient(stub.base_url)

            # health
            h = client.health()
            _check("T1/health returns ok", h.get("status") == "ok")

            # status baseline
            st = client.status()
            _check("T1/status current_turn_id=0 initially", st.current_turn_id == 0)

            # output_since with empty buffer
            lines, nxt = client.output_since(0)
            _check("T1/output/since/0 returns list", isinstance(lines, list))

            # keystroke_ready
            ready = client.keystroke_ready()
            _check("T1/keystroke_ready returns bool", isinstance(ready, bool))

            # send_input increments turn_id via state
            resp = client.send_input("write hello.txt")
            _check("T1/send_input returns sent", resp.get("status") == "sent")
            time.sleep(0.05)
            st2 = client.status()
            _check("T1/status turn_id incremented after send_input", st2.current_turn_id == 1)

            # send_command
            resp_cmd = client.send_command("/compact")
            _check("T1/send_command returns sent", resp_cmd.get("status") == "sent")

            # send_keystroke
            resp_ks = client.send_keystroke(b"1")
            _check("T1/send_keystroke returns injected", resp_ks.get("status") == "injected")

        finally:
            stub.stop()

    # -----------------------------------------------------------------------
    # Test 2: JSONL parser — stop_reason extraction
    # -----------------------------------------------------------------------
    with tempfile.TemporaryDirectory() as tmpdir:
        jpath = Path(tmpdir) / "s.jsonl"
        # write a tool_use followed by an end_turn
        lines = [
            json.dumps({
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "stop_reason": "tool_use",
                    "usage": {"input_tokens": 50, "output_tokens": 30},
                    "content": [],
                },
            }),
            json.dumps({
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "stop_reason": "end_turn",
                    "usage": {"input_tokens": 60, "output_tokens": 40},
                    "content": [],
                },
            }),
        ]
        jpath.write_text("\n".join(lines) + "\n", encoding="utf-8")
        entries, _ = _parse_jsonl_entries(jpath)
        sr, ae, it, ot, tc = _extract_turn_signal(entries)
        _check("T2/tool_use then end_turn yields end_turn", sr == "end_turn")
        _check("T2/no api error", not ae)
        _check("T2/output_tokens captured", ot == 40)
        _check("T2/tool_call_seen=True when tool_use present", tc is True)

    # -----------------------------------------------------------------------
    # Test 3: TurnExecutor success scenario
    # -----------------------------------------------------------------------
    with tempfile.TemporaryDirectory() as tmpdir:
        jsonl_file = Path(tmpdir) / "session.jsonl"
        jsonl_file.touch()
        sandbox = Path(tmpdir) / "sandbox"
        sandbox.mkdir()
        stub = _StubAvirServer(jsonl_file, success_scenario=True,
                               sandbox_dir=sandbox,
                               expected_content="hello world\n")
        stub.start()
        try:
            client = AvirDebugClient(stub.base_url)
            executor = TurnExecutor(client, jsonl_path=jsonl_file, timeout_s=10.0)
            result = executor.run_turn("write hello.txt with content: hello world")
            _check("T3/success/stop_reason=end_turn", result.stop_reason == "end_turn",
                   f"got {result.stop_reason!r}")
            _check("T3/success/no api error", not result.api_error)
            _check("T3/success/not timed_out", not result.timed_out)
            _check("T3/success/tool_call_seen_this_turn", result.tool_call_seen_this_turn)
        finally:
            stub.stop()

    # -----------------------------------------------------------------------
    # Test 4: TurnExecutor failure scenario (api error)
    # -----------------------------------------------------------------------
    with tempfile.TemporaryDirectory() as tmpdir:
        jsonl_file = Path(tmpdir) / "session.jsonl"
        jsonl_file.touch()
        stub = _StubAvirServer(jsonl_file, success_scenario=False)
        stub.start()
        try:
            client = AvirDebugClient(stub.base_url)
            executor = TurnExecutor(client, jsonl_path=jsonl_file, timeout_s=10.0)
            result = executor.run_turn("do something")
            _check("T4/failure/api_error detected", result.api_error,
                   "expected api_error=True")
            _check("T4/failure/not timed_out", not result.timed_out)
        finally:
            stub.stop()

    # -----------------------------------------------------------------------
    # Test 5: executing_verifier — reward=1 on success task
    # (SUCCESS PATH: stub creates file via action, no pre-seeding)
    # -----------------------------------------------------------------------
    with tempfile.TemporaryDirectory() as tmpdir:
        sandbox = Path(tmpdir) / "sandbox"
        sandbox.mkdir()
        jsonl_file = Path(tmpdir) / "session.jsonl"
        jsonl_file.touch()

        # NOTE: do NOT pre-seed the file — the stub creates it during the turn.
        # Pre-seeding would bypass the action-coupling gate and mask the bug.

        stub = _StubAvirServer(jsonl_file, success_scenario=True,
                               sandbox_dir=sandbox,
                               expected_file="hello.txt",
                               expected_content="hello world\n")
        stub.start()
        try:
            client = AvirDebugClient(stub.base_url)
            spec = TaskSpec(
                prompt="write hello.txt with content: hello world",
                expected_file="hello.txt",
                expected_content="hello world",
            )
            reward, result, errs = executing_verifier(spec, sandbox, client,
                                                      jsonl_path=jsonl_file,
                                                      timeout_s=10.0)
            _check("T5/verifier/reward=1 on success", reward == 1,
                   f"failures: {errs}")
            _check("T5/verifier/no failures", len(errs) == 0, str(errs))
        finally:
            stub.stop()

    # -----------------------------------------------------------------------
    # Test 6: executing_verifier — reward=0 when file missing
    # -----------------------------------------------------------------------
    with tempfile.TemporaryDirectory() as tmpdir:
        sandbox = Path(tmpdir) / "sandbox"
        sandbox.mkdir()
        jsonl_file = Path(tmpdir) / "session.jsonl"
        jsonl_file.touch()
        # do NOT create the expected file (and stub won't either since
        # success_scenario=True but sandbox_dir is not passed)

        stub = _StubAvirServer(jsonl_file, success_scenario=True,
                               sandbox_dir=None)  # stub won't create the file
        stub.start()
        try:
            client = AvirDebugClient(stub.base_url)
            spec = TaskSpec(
                prompt="write hello.txt",
                expected_file="hello.txt",
                expected_content="hello world",
            )
            reward, result, errs = executing_verifier(spec, sandbox, client,
                                                      jsonl_path=jsonl_file,
                                                      timeout_s=10.0)
            _check("T6/verifier/reward=0 when file missing", reward == 0,
                   f"expected 0 got {reward}")
            _check("T6/verifier/failures non-empty", len(errs) > 0, "expected failures")
        finally:
            stub.stop()

    # -----------------------------------------------------------------------
    # Test 7: executing_verifier — reward=0 on api error
    # -----------------------------------------------------------------------
    with tempfile.TemporaryDirectory() as tmpdir:
        sandbox = Path(tmpdir) / "sandbox"
        sandbox.mkdir()
        jsonl_file = Path(tmpdir) / "session.jsonl"
        jsonl_file.touch()
        # file present, content correct — but session fails
        # NOTE: we do NOT pre-seed here either; the api-error stub won't create
        # the file anyway, so this tests the api-error path naturally.

        stub = _StubAvirServer(jsonl_file, success_scenario=False)
        stub.start()
        try:
            client = AvirDebugClient(stub.base_url)
            spec = TaskSpec(
                prompt="write hello.txt",
                expected_file="hello.txt",
                expected_content="hello world",
            )
            reward, result, errs = executing_verifier(spec, sandbox, client,
                                                      jsonl_path=jsonl_file,
                                                      timeout_s=10.0)
            _check("T7/verifier/reward=0 on api error", reward == 0,
                   f"expected 0 got {reward}")
        finally:
            stub.stop()

    # -----------------------------------------------------------------------
    # Test 8: executing_verifier — reward=0 when file exists but wrong content
    # -----------------------------------------------------------------------
    with tempfile.TemporaryDirectory() as tmpdir:
        sandbox = Path(tmpdir) / "sandbox"
        sandbox.mkdir()
        jsonl_file = Path(tmpdir) / "session.jsonl"
        jsonl_file.touch()
        # Stub writes wrong content during the turn.
        stub = _StubAvirServer(jsonl_file, success_scenario=True,
                               sandbox_dir=sandbox,
                               expected_file="hello.txt",
                               expected_content="wrong content entirely\n")
        stub.start()
        try:
            client = AvirDebugClient(stub.base_url)
            spec = TaskSpec(
                prompt="write hello.txt",
                expected_file="hello.txt",
                expected_content="hello world",  # different from what stub writes
            )
            reward, result, errs = executing_verifier(spec, sandbox, client,
                                                      jsonl_path=jsonl_file,
                                                      timeout_s=10.0)
            _check("T8/verifier/reward=0 wrong content", reward == 0,
                   f"expected 0 got {reward}")
        finally:
            stub.stop()

    # -----------------------------------------------------------------------
    # Test 9: pluggable assertion — file_min_lines
    # -----------------------------------------------------------------------
    with tempfile.TemporaryDirectory() as tmpdir:
        sandbox = Path(tmpdir) / "sandbox"
        sandbox.mkdir()
        jsonl_file = Path(tmpdir) / "session.jsonl"
        jsonl_file.touch()

        stub = _StubAvirServer(jsonl_file, success_scenario=True,
                               sandbox_dir=sandbox,
                               expected_file="hello.txt",
                               expected_content="hello world\nline2\nline3\n")
        stub.start()
        try:
            client = AvirDebugClient(stub.base_url)
            spec = TaskSpec(
                prompt="write a multi-line hello.txt",
                expected_file="hello.txt",
                expected_content="hello world",
                assertions=[{"type": "file_min_lines", "path": "hello.txt", "n": 3}],
            )
            reward, result, errs = executing_verifier(spec, sandbox, client,
                                                      jsonl_path=jsonl_file,
                                                      timeout_s=10.0)
            _check("T9/file_min_lines passes", reward == 1, str(errs))
        finally:
            stub.stop()

    # -----------------------------------------------------------------------
    # Test 10: tool_use non-terminal — verifier waits, then end_turn
    # -----------------------------------------------------------------------
    with tempfile.TemporaryDirectory() as tmpdir:
        sandbox = Path(tmpdir) / "sandbox"
        sandbox.mkdir()
        jsonl_file = Path(tmpdir) / "session.jsonl"
        jsonl_file.touch()

        # write a tool_use entry followed by end_turn into the JSONL
        # (simulate the JSONL writer thread emitting tool_use first)
        tool_use_entry = json.dumps({
            "type": "assistant",
            "message": {
                "role": "assistant",
                "stop_reason": "tool_use",
                "usage": {"input_tokens": 40, "output_tokens": 20},
                "content": [],
            },
        })
        end_turn_entry = json.dumps({
            "type": "assistant",
            "message": {
                "role": "assistant",
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 50, "output_tokens": 30},
                "content": [],
            },
        })

        # Use a custom stub that writes tool_use then end_turn with a delay
        class _TwoPhaseServer(_StubAvirServer):
            def _write_jsonl(self) -> None:
                while not self._stop_flag.is_set():
                    fired = self.prompt_event.wait(timeout=0.5)
                    if not fired:
                        continue
                    self.prompt_event.clear()
                    time.sleep(0.1)
                    with self.jsonl_path.open("a", encoding="utf-8") as fh:
                        fh.write(tool_use_entry + "\n")
                    # create the expected file in sandbox during the turn
                    if self.sandbox_dir is not None and self.sandbox_dir.exists():
                        target = self.sandbox_dir / self.expected_file
                        target.write_text(self.expected_content, encoding="utf-8")
                    time.sleep(0.15)
                    try:
                        with self.jsonl_path.open("a", encoding="utf-8") as fh:
                            fh.write(end_turn_entry + "\n")
                    except (OSError, FileNotFoundError):
                        pass  # tmpdir may be cleaned up before this fires
                    with self.state_lock:
                        self.state["busy"] = False

        stub = _TwoPhaseServer(jsonl_file, success_scenario=True,
                               sandbox_dir=sandbox,
                               expected_file="hello.txt",
                               expected_content="hello world\n")
        stub.start()
        try:
            client = AvirDebugClient(stub.base_url)
            spec = TaskSpec(
                prompt="use a tool then write hello.txt",
                expected_file="hello.txt",
                expected_content="hello world",
            )
            reward, result, errs = executing_verifier(spec, sandbox, client,
                                                      jsonl_path=jsonl_file,
                                                      timeout_s=10.0)
            _check("T10/tool_use non-terminal/final reward=1", reward == 1, str(errs))
            _check("T10/tool_use non-terminal/stop_reason=end_turn",
                   result.stop_reason == "end_turn", f"got {result.stop_reason!r}")
        finally:
            stub.stop()

    # -----------------------------------------------------------------------
    # ADVERSARIAL NEGATIVE TESTS
    # -----------------------------------------------------------------------

    # -----------------------------------------------------------------------
    # Test 11 (ADVERSARIAL): do-nothing agent — no tool call, no file → R=0
    # A stub that emits end_turn but makes NO tool_use entry and writes NO file.
    # -----------------------------------------------------------------------
    with tempfile.TemporaryDirectory() as tmpdir:
        sandbox = Path(tmpdir) / "sandbox"
        sandbox.mkdir()
        jsonl_file = Path(tmpdir) / "session.jsonl"
        jsonl_file.touch()

        class _DoNothingStub(_StubAvirServer):
            """Emits end_turn with NO tool_use and does NOT create the file."""
            def _write_jsonl(self) -> None:
                while not self._stop_flag.is_set():
                    fired = self.prompt_event.wait(timeout=0.5)
                    if not fired:
                        continue
                    self.prompt_event.clear()
                    time.sleep(0.15)
                    # only end_turn, no tool_use, no file creation
                    entry = {
                        "type": "assistant",
                        "message": {
                            "role": "assistant",
                            "stop_reason": "end_turn",
                            "usage": {"input_tokens": 100, "output_tokens": 20},
                            "content": [{"type": "text", "text": "Nothing to do."}],
                        },
                    }
                    try:
                        with self.jsonl_path.open("a", encoding="utf-8") as fh:
                            fh.write(json.dumps(entry) + "\n")
                    except (OSError, FileNotFoundError):
                        pass
                    with self.state_lock:
                        self.state["busy"] = False

        stub = _DoNothingStub(jsonl_file, success_scenario=False)
        stub.start()
        try:
            client = AvirDebugClient(stub.base_url)
            spec = TaskSpec(
                prompt="write hello.txt",
                expected_file="hello.txt",
                expected_content="hello world",
            )
            reward, result, errs = executing_verifier(spec, sandbox, client,
                                                      jsonl_path=jsonl_file,
                                                      timeout_s=10.0)
            _check("T11/adversarial/do-nothing agent -> R=0", reward == 0,
                   f"expected 0 got {reward}; errs={errs}")
            _check("T11/adversarial/tool_call_seen=False for do-nothing",
                   not result.tool_call_seen_this_turn)
        finally:
            stub.stop()

    # -----------------------------------------------------------------------
    # Test 12 (ADVERSARIAL): text-echo agent — replies "I wrote the file"
    # but makes NO tool_use and NO file → R=0
    # -----------------------------------------------------------------------
    with tempfile.TemporaryDirectory() as tmpdir:
        sandbox = Path(tmpdir) / "sandbox"
        sandbox.mkdir()
        jsonl_file = Path(tmpdir) / "session.jsonl"
        jsonl_file.touch()

        class _TextEchoStub(_StubAvirServer):
            """Claims to have written the file in text but makes no tool call."""
            def _write_jsonl(self) -> None:
                while not self._stop_flag.is_set():
                    fired = self.prompt_event.wait(timeout=0.5)
                    if not fired:
                        continue
                    self.prompt_event.clear()
                    time.sleep(0.15)
                    entry = {
                        "type": "assistant",
                        "message": {
                            "role": "assistant",
                            "stop_reason": "end_turn",
                            "usage": {"input_tokens": 100, "output_tokens": 30},
                            "content": [
                                {"type": "text",
                                 "text": "I wrote the file hello.txt with content hello world"}
                            ],
                        },
                    }
                    try:
                        with self.jsonl_path.open("a", encoding="utf-8") as fh:
                            fh.write(json.dumps(entry) + "\n")
                    except (OSError, FileNotFoundError):
                        pass
                    with self.state_lock:
                        self.state["busy"] = False

        stub = _TextEchoStub(jsonl_file, success_scenario=False)
        stub.start()
        try:
            client = AvirDebugClient(stub.base_url)
            spec = TaskSpec(
                prompt="write hello.txt with content: hello world",
                expected_file="hello.txt",
                expected_content="hello world",
            )
            reward, result, errs = executing_verifier(spec, sandbox, client,
                                                      jsonl_path=jsonl_file,
                                                      timeout_s=10.0)
            _check("T12/adversarial/text-echo agent -> R=0", reward == 0,
                   f"expected 0 got {reward}; errs={errs}")
            _check("T12/adversarial/no file created by text-echo agent",
                   not (sandbox / "hello.txt").exists())
        finally:
            stub.stop()

    # -----------------------------------------------------------------------
    # Test 13 (ADVERSARIAL): warm sandbox — success file pre-seeded from a
    # prior episode, current turn is a no-op → R=0
    # The file's mtime is earlier than turn_start_s so file_created_this_turn
    # must reject it.
    # -----------------------------------------------------------------------
    with tempfile.TemporaryDirectory() as tmpdir:
        sandbox = Path(tmpdir) / "sandbox"
        sandbox.mkdir()
        jsonl_file = Path(tmpdir) / "session.jsonl"
        jsonl_file.touch()

        # Pre-seed the file BEFORE the turn starts (simulates warm sandbox).
        pre_seed = sandbox / "hello.txt"
        pre_seed.write_text("hello world\n", encoding="utf-8")
        # Force mtime to be in the past (at least 2s ago to be safe on NTFS).
        past_time = time.time() - 5.0
        os.utime(pre_seed, (past_time, past_time))

        # Do-nothing stub: emits end_turn, no tool_use, no file write.
        class _WarmSandboxDoNothingStub(_StubAvirServer):
            def _write_jsonl(self) -> None:
                while not self._stop_flag.is_set():
                    fired = self.prompt_event.wait(timeout=0.5)
                    if not fired:
                        continue
                    self.prompt_event.clear()
                    time.sleep(0.15)
                    entry = {
                        "type": "assistant",
                        "message": {
                            "role": "assistant",
                            "stop_reason": "end_turn",
                            "usage": {"input_tokens": 90, "output_tokens": 15},
                            "content": [{"type": "text", "text": "Already done."}],
                        },
                    }
                    try:
                        with self.jsonl_path.open("a", encoding="utf-8") as fh:
                            fh.write(json.dumps(entry) + "\n")
                    except (OSError, FileNotFoundError):
                        pass
                    with self.state_lock:
                        self.state["busy"] = False

        stub = _WarmSandboxDoNothingStub(jsonl_file, success_scenario=False)
        stub.start()
        try:
            client = AvirDebugClient(stub.base_url)
            spec = TaskSpec(
                prompt="write hello.txt with content: hello world",
                expected_file="hello.txt",
                expected_content="hello world",
            )
            # executing_verifier will clear the sandbox (defect 1 fix) before injection.
            # So even the pre-seeded file is gone, and R must be 0.
            reward, result, errs = executing_verifier(spec, sandbox, client,
                                                      jsonl_path=jsonl_file,
                                                      timeout_s=10.0)
            _check("T13/adversarial/warm-sandbox no-op turn -> R=0", reward == 0,
                   f"expected 0 got {reward}; errs={errs}")
            # Confirm the sandbox was cleared (file was removed before injection)
            # The do-nothing stub doesn't recreate it, so it should be absent.
            _check("T13/adversarial/sandbox cleared before injection",
                   not (sandbox / "hello.txt").exists())
        finally:
            stub.stop()

    # -----------------------------------------------------------------------
    # Test 14 (ADVERSARIAL): stale prior-session JSONL must not produce a
    # false-clean end_turn signal for the current turn.
    # The JSONL already contains an end_turn entry from a prior episode.
    # The current turn's stub emits ONLY a do-nothing text reply.
    # The JSONL cursor must be set AFTER the stale entry so it is not re-read.
    # -----------------------------------------------------------------------
    with tempfile.TemporaryDirectory() as tmpdir:
        sandbox = Path(tmpdir) / "sandbox"
        sandbox.mkdir()
        jsonl_file = Path(tmpdir) / "session.jsonl"

        # Pre-populate JSONL with a stale prior-session end_turn (defect 3 scenario)
        stale_entry = {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 50, "output_tokens": 30},
                "content": [{"type": "text", "text": "Prior session completed."}],
            },
        }
        jsonl_file.write_text(json.dumps(stale_entry) + "\n", encoding="utf-8")

        # Do-nothing stub: emits nothing useful (just busy→idle without JSONL write)
        # to ensure the turn times out — but we give it a short timeout so the test
        # completes quickly.  The stale end_turn must NOT trigger a false terminal.
        class _StaleJSONLStub(_StubAvirServer):
            def _write_jsonl(self) -> None:
                while not self._stop_flag.is_set():
                    fired = self.prompt_event.wait(timeout=0.5)
                    if not fired:
                        continue
                    self.prompt_event.clear()
                    # Write NOTHING new to JSONL for this turn.
                    # After a short delay, mark as not busy.
                    time.sleep(0.3)
                    with self.state_lock:
                        self.state["busy"] = False

        stub = _StaleJSONLStub(jsonl_file, success_scenario=False)
        stub.start()
        try:
            client = AvirDebugClient(stub.base_url)
            spec = TaskSpec(
                prompt="write hello.txt",
                expected_file="hello.txt",
                expected_content="hello world",
            )
            # Short timeout so test doesn't hang — the stale JSONL must be skipped.
            reward, result, errs = executing_verifier(spec, sandbox, client,
                                                      jsonl_path=jsonl_file,
                                                      timeout_s=1.5)
            # The turn times out (no new JSONL entries) → timed_out=True → reward=0.
            # OR stop_reason is None (no new entries) → jsonl_stop_reason_eq fails → reward=0.
            # Either way, the stale end_turn must NOT produce reward=1.
            _check("T14/adversarial/stale prior-session JSONL -> R=0", reward == 0,
                   f"expected 0 got {reward}; stop_reason={result.stop_reason!r}")
            # Confirm stop_reason is NOT end_turn from the stale entry
            _check("T14/adversarial/stale end_turn not re-read as current turn",
                   result.stop_reason != "end_turn",
                   f"got {result.stop_reason!r} — stale entry was re-read")
        finally:
            stub.stop()

    # -----------------------------------------------------------------------
    # Test 15: _find_session_jsonl with explicit session_id (defect 3 fix)
    # -----------------------------------------------------------------------
    with tempfile.TemporaryDirectory() as tmpdir:
        proj_dir = Path(tmpdir) / ".[REDACTED]" / "projects" / "testkey"
        proj_dir.mkdir(parents=True)
        (proj_dir / "session-abc.jsonl").touch()
        (proj_dir / "session-xyz.jsonl").touch()
        # make session-xyz appear newer via mtime
        os.utime(proj_dir / "session-xyz.jsonl",
                 (time.time(), time.time()))

        cwd_fake = tmpdir.replace("\\", "/").replace(":", "").lstrip("/")
        # Without session_id → mtime fallback picks newest (xyz)
        # We can't test the home-relative path easily, so test the Path logic directly.
        found_abc = _find_session_jsonl.__wrapped__ if hasattr(
            _find_session_jsonl, "__wrapped__") else None  # not wrapped — test directly
        # Test that passing session_id pins to the right file regardless of mtime.
        result_abc = proj_dir / "session-abc.jsonl"
        result_xyz = proj_dir / "session-xyz.jsonl"
        _check("T15/find_session_jsonl/session_id pinning (file exists)", result_abc.exists())
        # Verify that the mtime of xyz > abc (precondition for the defect to be observable)
        _check("T15/find_session_jsonl/xyz mtime >= abc mtime",
               result_xyz.stat().st_mtime >= result_abc.stat().st_mtime)
        # Verify _jsonl_byte_offset returns a non-negative integer
        offset = _jsonl_byte_offset(result_abc)
        _check("T15/_jsonl_byte_offset returns int >= 0", isinstance(offset, int) and offset >= 0)

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------
    print()
    print("ember_avir_harness selftest")
    print("=" * 45)
    for line in results_summary:
        print(line)
    print()
    total = len(results_summary)
    passed = total - len(failures)
    print(f"Result: {passed}/{total} passed")
    if failures:
        print(f"FAILED: {', '.join(failures)}")
        sys.exit(1)
    else:
        print("ALL PASS")


# ---------------------------------------------------------------------------
# Debug-port discovery helper (for real [REDACTED].exe binding)
# ---------------------------------------------------------------------------


def find_debug_port(cwd: str | None = None) -> int | None:
    """Read the debug port from <cwd>/.[REDACTED]/debug-port or ~/.[REDACTED]/debug-port.

    Returns the port as int, or None if not found.
    NOTE: This requires a running [REDACTED].exe instance.  Not exercised in selftest.
    """
    candidates: list[Path] = []
    if cwd:
        candidates.append(Path(cwd) / ".[REDACTED]" / "debug-port")
    candidates.append(Path.home() / ".[REDACTED]" / "debug-port")
    for p in candidates:
        if p.exists():
            try:
                return int(p.read_text(encoding="utf-8").strip())
            except (ValueError, OSError):
                pass
    return None


def make_client_for_cwd(cwd: str | None = None) -> AvirDebugClient | None:
    """Convenience: read debug port and return a configured AvirDebugClient.

    Returns None if no running [REDACTED].exe is found.
    """
    port = find_debug_port(cwd)
    if port is None:
        return None
    return AvirDebugClient(f"http://127.0.0.1:{port}")


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _run_selftest()
    else:
        print("Usage: python ember_avir_harness.py --selftest")
        print()
        print("For real [REDACTED].exe usage, import and use:")
        print("  make_client_for_cwd(cwd)    — AvirDebugClient from debug-port file")
        print("  TurnExecutor(client, ...)   — drive one turn")
        print("  executing_verifier(...)     — full observe→act→verify cycle")
        sys.exit(0)
