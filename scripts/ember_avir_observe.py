#!/usr/bin/env python3
"""ember_avir_observe.py — first-hand [REDACTED].exe observation receipt for C14.

ATTACH-ONLY: this script does NOT launch [REDACTED].exe or llama-server.
The operator launches [REDACTED].exe separately (with --debug-server <port>).
This script attaches to a running debug port and captures the receipt.

Provenance: landed from stage dryrun-20260704T211712Z (ember issue #210 Tier 2)
with a portability fix -- EMBER_RUN_DIR and DEFAULT_SANDBOX_CWD carried
absolute drive-letter-rooted literals. EMBER_RUN_DIR pointed at an
operator-private tree outside this repo entirely (no repo-relative
equivalent -- genuinely external, same class as the SHARD_DIR/GOALFORGE_ROOT
fixes in families 2-3); switched to an EMBER_OBSERVE_RUN_DIR env var with a
repo-relative scratch/ fallback (a distinct name from the training scripts'
EMBER_RUN_DIR env var, which is a different concept -- checkpoint output,
not observation-receipt output). DEFAULT_SANDBOX_CWD is a fixed structural
sibling of the repo root (same class as the shards-v0/models junctions);
switched to a computed repo-relative default. See
receipts/ember-c-scale/land210i-*.

Usage
-----
  python ember_avir_observe.py --port <debug-port> --sandbox <cwd>

  --port       [REDACTED].exe debug port (required, or read from <cwd>/.[REDACTED]/debug-port)
  --sandbox    cwd that [REDACTED].exe was launched in (default: a repo-sibling sandbox dir; see DEFAULT_SANDBOX_CWD)
  --out        override output path (default: auto-timestamped in ember-run/)
  --turn1-prompt  first turn prompt (default: plain end_turn elicitor)
  --turn2-prompt  second turn prompt (default: tool-use elicitor asking to write a file)

Receipt written to
  EMBER_RUN_DIR/c14-[REDACTED]-firsthand-observation-receipt-<ts>.json (see EMBER_RUN_DIR below)

What is captured
----------------
Turn 1 (end_turn schema):
  - GET /status before injection  -> baseline snapshot
  - POST /input with turn1_prompt -> send
  - poll /output/since/<N> + session JSONL -> accumulate TUI lines + stop_reason
  - GET /status after             -> post-turn snapshot
  - session JSONL assistant entry with stop_reason + usage

Turn 2 (tool_use schema):
  - GET /status before
  - POST /input with turn2_prompt (explicitly asks the model to write a file)
  - poll /output/since/<N> + session JSONL -> capture the RAW tool_use JSONL entry
  - GET /status after
  - session JSONL tool_use entry (raw content block) + end_turn entry

The receipt JSON includes:
  - raw_status_before / raw_status_after (both turns)
  - tui_lines (both turns)
  - raw_jsonl_entries_this_turn (list of parsed JSONL dicts — the actual schema)
  - stop_reason, api_error, input_tokens, output_tokens
  - elapsed_s, turn_start_s
  - any tool_use content blocks found (raw, unmodified)
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent

# EMBER_RUN_DIR (this module's output dir for observation receipts) is
# distinct from the training scripts' EMBER_RUN_DIR env var (checkpoint
# output) -- do not conflate. No repo-relative equivalent for an
# operator-private tree, so this defaults to a repo-local scratch dir unless
# overridden.
EMBER_RUN_DIR = Path(os.environ.get(
    "EMBER_OBSERVE_RUN_DIR",
    str(_REPO / "scratch" / "ember-run"),
))
AVIR_HOME = Path.home() / ".[REDACTED]"
SETTINGS_PATH = AVIR_HOME / "settings.json"

# Default sandbox cwd — matches SANDBOX_BASE_CONFIG_KEY in [REDACTED] test
# harness. Fixed structural sibling of the repo root (same class as the
# shards-v0/models junctions), computed rather than hardcoded.
DEFAULT_SANDBOX_CWD = str(_REPO.parent / "sandbox-gpu-test")

# Default prompts
DEFAULT_TURN1_PROMPT = (
    "Say exactly one sentence describing what you are. End your response there."
)
DEFAULT_TURN2_PROMPT = (
    "Write a file named 'c14-probe.txt' in the current directory with the content: "
    "'avir_tool_use_verified'. Use the Write file tool to create it. "
    "Do not describe the action — just do it."
)

POLL_INTERVAL_S = 0.2
TURN_TIMEOUT_S = 180.0
TERMINAL_STOP_REASONS = {"end_turn", "max_tokens", "cancelled"}

# ---------------------------------------------------------------------------
# HTTP helpers (stdlib only)
# ---------------------------------------------------------------------------


def _get(url: str, timeout: float = 10.0) -> dict[str, Any]:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _post(url: str, payload: dict[str, Any], timeout: float = 10.0) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ---------------------------------------------------------------------------
# Debug-port discovery
# ---------------------------------------------------------------------------


def discover_port(explicit_port: int | None, sandbox_cwd: str) -> int:
    if explicit_port:
        return explicit_port
    candidates = [
        Path(sandbox_cwd) / ".[REDACTED]" / "debug-port",
        AVIR_HOME / "debug-port",
    ]
    for p in candidates:
        if p.exists():
            try:
                return int(p.read_text(encoding="utf-8").strip())
            except (ValueError, OSError):
                pass
    raise RuntimeError(
        f"No debug port found. Pass --port explicitly or ensure [REDACTED].exe has written "
        f"a debug-port file under {sandbox_cwd}/.[REDACTED]/ or {AVIR_HOME}/"
    )


# ---------------------------------------------------------------------------
# Session JSONL discovery
# ---------------------------------------------------------------------------


def find_session_jsonl(cwd: str) -> Path | None:
    key = cwd.replace("\\", "/").replace(":", "").lstrip("/")
    projects_dir = AVIR_HOME / "projects" / key
    if not projects_dir.exists():
        return None
    files = sorted(projects_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def jsonl_byte_offset(p: Path) -> int:
    try:
        return p.stat().st_size
    except (OSError, FileNotFoundError):
        return 0


def read_jsonl_since(p: Path, after_byte: int) -> tuple[list[dict[str, Any]], int]:
    entries: list[dict[str, Any]] = []
    try:
        size = p.stat().st_size
        if size <= after_byte:
            return entries, after_byte
        with p.open("rb") as fh:
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
                pass
        return entries, new_offset
    except (OSError, FileNotFoundError):
        return entries, after_byte


# ---------------------------------------------------------------------------
# Turn observation
# ---------------------------------------------------------------------------


def observe_turn(
    base_url: str,
    prompt: str,
    jsonl_path: Path | None,
    timeout_s: float = TURN_TIMEOUT_S,
    label: str = "turn",
) -> dict[str, Any]:
    """Drive one turn and return a receipt dict."""
    # 1. baseline status
    status_before = _get(f"{base_url}/status")
    output_cursor: int = int(status_before.get("output_total", 0))

    # 2. JSONL byte cursor BEFORE injection (defect-3 fix from ember_avir_harness.py)
    jsonl_cursor = 0
    if jsonl_path is not None:
        jsonl_cursor = jsonl_byte_offset(jsonl_path)

    turn_start_s = time.time()

    # 3. inject
    inject_resp = _post(f"{base_url}/input", {"text": prompt})

    # 4. poll loop
    tui_lines: list[str] = []
    all_jsonl_entries: list[dict[str, Any]] = []
    stop_reason: str | None = None
    api_error = False
    input_tokens = 0
    output_tokens = 0
    tool_call_seen = False
    tool_use_blocks: list[dict[str, Any]] = []

    start_mono = time.monotonic()
    timed_out = False

    while True:
        elapsed = time.monotonic() - start_mono
        if elapsed > timeout_s:
            timed_out = True
            break

        # poll TUI
        try:
            raw = _get(f"{base_url}/output/since/{output_cursor}")
            new_lines: list[str] = raw.get("output", [])
            output_cursor = int(raw.get("next", output_cursor + len(new_lines)))
            tui_lines.extend(new_lines)
        except (urllib.error.URLError, OSError):
            pass

        # poll JSONL
        if jsonl_path is not None:
            new_entries, jsonl_cursor = read_jsonl_since(jsonl_path, jsonl_cursor)
            if new_entries:
                all_jsonl_entries.extend(new_entries)
                for entry in new_entries:
                    if entry.get("isApiErrorMessage"):
                        api_error = True
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
                        # capture raw tool_use content blocks
                        for block in msg.get("content", []):
                            if isinstance(block, dict) and block.get("type") == "tool_use":
                                tool_use_blocks.append(block)

                if api_error or (stop_reason is not None and stop_reason in TERMINAL_STOP_REASONS):
                    break

        time.sleep(POLL_INTERVAL_S)

    elapsed_s = time.monotonic() - start_mono

    # 5. post-turn status
    try:
        status_after = _get(f"{base_url}/status")
    except (urllib.error.URLError, OSError):
        status_after = {}

    return {
        "label": label,
        "prompt": prompt,
        "inject_response": inject_resp,
        "raw_status_before": status_before,
        "raw_status_after": status_after,
        "tui_lines": tui_lines,
        "raw_jsonl_entries_this_turn": all_jsonl_entries,
        "stop_reason": stop_reason,
        "api_error": api_error,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "tool_call_seen_this_turn": tool_call_seen,
        "tool_use_content_blocks": tool_use_blocks,
        "elapsed_s": elapsed_s,
        "timed_out": timed_out,
        "turn_start_s": turn_start_s,
        "jsonl_path": str(jsonl_path) if jsonl_path else None,
    }


# ---------------------------------------------------------------------------
# Trust pre-seed
# ---------------------------------------------------------------------------


def preseed_trust(sandbox_cwd: str) -> bool:
    """Write hasTrustDialogAccepted: true for sandbox_cwd into ~/.[REDACTED]/settings.json.

    Mirrors ensureSandboxTrusted() in [REDACTED]-cli/tests/gpu/drivers/injectDriver.ts.
    Returns True if settings were updated, False if already trusted.
    """
    settings: dict[str, Any] = {}
    if SETTINGS_PATH.exists():
        try:
            settings = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            settings = {}

    projects = settings.get("projects", {})
    if isinstance(projects, dict) and projects.get(sandbox_cwd, {}).get("hasTrustDialogAccepted") is True:
        return False  # already trusted

    if "projects" not in settings:
        settings["projects"] = {}
    if sandbox_cwd not in settings["projects"]:
        settings["projects"][sandbox_cwd] = {}
    settings["projects"][sandbox_cwd]["hasTrustDialogAccepted"] = True
    SETTINGS_PATH.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Attach to a running [REDACTED].exe and capture C14 observation receipt."
    )
    parser.add_argument("--port", type=int, default=None,
                        help="[REDACTED].exe debug port (or reads from debug-port file)")
    parser.add_argument("--sandbox", default=DEFAULT_SANDBOX_CWD,
                        help=f"[REDACTED].exe sandbox cwd (default: {DEFAULT_SANDBOX_CWD})")
    parser.add_argument("--out", default=None,
                        help="Override output receipt path")
    parser.add_argument("--turn1-prompt", default=DEFAULT_TURN1_PROMPT,
                        help="Prompt for turn 1 (end_turn schema capture)")
    parser.add_argument("--turn2-prompt", default=DEFAULT_TURN2_PROMPT,
                        help="Prompt for turn 2 (tool_use schema capture)")
    parser.add_argument("--timeout", type=float, default=TURN_TIMEOUT_S,
                        help=f"Timeout per turn in seconds (default: {TURN_TIMEOUT_S})")
    parser.add_argument("--preseed-trust", action="store_true",
                        help="Write hasTrustDialogAccepted:true for sandbox cwd before attaching")
    parser.add_argument("--skip-turn2", action="store_true",
                        help="Capture turn 1 only (skip tool_use elicitor turn)")
    args = parser.parse_args()

    # 1. optionally pre-seed trust
    if args.preseed_trust:
        updated = preseed_trust(args.sandbox)
        print(f"[preseed-trust] {'written' if updated else 'already trusted'}: {args.sandbox}")

    # 2. discover debug port
    port = discover_port(args.port, args.sandbox)
    base_url = f"http://127.0.0.1:{port}"
    print(f"[attach] debug port={port} base_url={base_url}")

    # 3. readiness probe
    try:
        health = _get(f"{base_url}/health")
        print(f"[health] {health}")
    except Exception as exc:
        print(f"[ERROR] cannot reach [REDACTED].exe debug server at {base_url}: {exc}", file=sys.stderr)
        print("  -> Ensure [REDACTED].exe is running with --debug-server <port>", file=sys.stderr)
        sys.exit(1)

    # 4. find session JSONL
    jsonl_path = find_session_jsonl(args.sandbox)
    print(f"[jsonl] session JSONL: {jsonl_path}")

    # 5. capture turn 1 (end_turn schema)
    print(f"[turn1] injecting: {args.turn1_prompt!r}")
    turn1 = observe_turn(base_url, args.turn1_prompt, jsonl_path,
                         timeout_s=args.timeout, label="turn1_end_turn_schema")
    print(f"[turn1] stop_reason={turn1['stop_reason']} elapsed={turn1['elapsed_s']:.1f}s "
          f"timed_out={turn1['timed_out']} api_error={turn1['api_error']}")
    print(f"[turn1] tui_lines={len(turn1['tui_lines'])} jsonl_entries={len(turn1['raw_jsonl_entries_this_turn'])}")

    # 6. capture turn 2 (tool_use schema) unless skipped
    turn2: dict[str, Any] | None = None
    if not args.skip_turn2:
        print(f"[turn2] injecting: {args.turn2_prompt!r}")
        turn2 = observe_turn(base_url, args.turn2_prompt, jsonl_path,
                             timeout_s=args.timeout, label="turn2_tool_use_schema")
        print(f"[turn2] stop_reason={turn2['stop_reason']} elapsed={turn2['elapsed_s']:.1f}s "
              f"timed_out={turn2['timed_out']} api_error={turn2['api_error']}")
        print(f"[turn2] tool_call_seen={turn2['tool_call_seen_this_turn']} "
              f"tool_use_blocks={len(turn2['tool_use_content_blocks'])} "
              f"jsonl_entries={len(turn2['raw_jsonl_entries_this_turn'])}")

    # 7. assemble receipt
    ts = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    receipt: dict[str, Any] = {
        "receipt_schema_version": "c14-[REDACTED]-firsthand-v1",
        "captured_at_utc": ts,
        "debug_port": port,
        "sandbox_cwd": args.sandbox,
        "session_jsonl": str(jsonl_path) if jsonl_path else None,
        "base_url": base_url,
        "turn1": turn1,
        "turn2": turn2,
        # convenience: schema shape excerpts for quick inspection
        "_status_schema": {
            "doc": "Shape of GET /status response (from turn1 raw_status_before)",
            "sample": turn1["raw_status_before"],
        },
        "_jsonl_assistant_schema": {
            "doc": "Raw JSONL assistant entries from turn1 (end_turn schema)",
            "entries": turn1["raw_jsonl_entries_this_turn"],
        },
        "_jsonl_tool_use_schema": {
            "doc": "Raw JSONL entries from turn2 containing tool_use (may be empty if model declined)",
            "entries": turn2["raw_jsonl_entries_this_turn"] if turn2 else [],
            "tool_use_content_blocks": turn2["tool_use_content_blocks"] if turn2 else [],
        },
        "_output_since_schema": {
            "doc": "Shape of GET /output/since/N response (sample from turn1)",
            "sample": {
                "output": turn1["tui_lines"][:5],
                "total": int(turn1["raw_status_after"].get("output_total", 0)),
                "next": "(index after last delivered line)",
            },
        },
    }

    # 8. write receipt
    out_path: Path
    if args.out:
        out_path = Path(args.out)
    else:
        EMBER_RUN_DIR.mkdir(parents=True, exist_ok=True)
        out_path = EMBER_RUN_DIR / f"c14-[REDACTED]-firsthand-observation-receipt-{ts}.json"

    out_path.write_text(json.dumps(receipt, indent=2, default=str), encoding="utf-8")
    print(f"[receipt] written to: {out_path}")

    # 9. brief schema report
    print()
    print("=== Schema capture summary ===")
    print(f"  /status fields (turn1 before): {sorted(turn1['raw_status_before'].keys())}")
    print(f"  /output/since/N fields: output, total, next")
    print(f"  JSONL entries turn1: {len(turn1['raw_jsonl_entries_this_turn'])}")
    if turn2:
        print(f"  JSONL entries turn2: {len(turn2['raw_jsonl_entries_this_turn'])}")
        print(f"  tool_use blocks captured: {len(turn2['tool_use_content_blocks'])}")
    if turn1["raw_jsonl_entries_this_turn"]:
        first = turn1["raw_jsonl_entries_this_turn"][0]
        print(f"  sample JSONL entry keys: {sorted(first.keys())}")
    print(f"  stop_reason turn1: {turn1['stop_reason']}")
    if turn2:
        print(f"  stop_reason turn2: {turn2['stop_reason']}")

    # exit 0 if at least turn1 end_turn captured cleanly
    if turn1["stop_reason"] == "end_turn" and not turn1["api_error"]:
        print("\n[ok] turn1 end_turn captured cleanly.")
        sys.exit(0)
    else:
        print(f"\n[warn] turn1 did not end_turn cleanly: stop_reason={turn1['stop_reason']!r} api_error={turn1['api_error']}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
