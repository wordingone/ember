"""selftest_cu_console.py — CU console surface selftest (Closes #262).

Cases:
  (a) console_source_emits      — injected lines appear as console_input events
  (b) console_write_tool        — console_write tool writes to output stream
  (c) stub_core_routes_console  — stub_core emits console_write action for console_input
  (d) loop_roundtrip            — NCKEventLoop routes injected line → echo output
  (e) poke_proven               — WriteConsoleInput-compatible: inject >=2 lines, all echoed

Prints: NCK_CU_CONSOLE_SELFTEST PASS (cases: a b c d e) or FAIL with case name.
"""

from __future__ import annotations

import io
import os
import sys
import tempfile
import time
import threading

_THIS = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS = os.path.dirname(_THIS)
for _p in (_THIS, _SCRIPTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nck.event_loop import (
    Action,
    ConsoleSource,
    Event,
    NCKEventLoop,
    ToolRegistry,
    stub_core,
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
        "_skip_invariant_check": True,
    }


def _make_stdin(lines: list[str]) -> io.StringIO:
    return io.StringIO("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# Case (a): ConsoleSource emits console_input events for injected lines
# ---------------------------------------------------------------------------

def case_a_console_source_emits() -> str | None:
    stdin = _make_stdin(["hello", "world"])
    out = io.StringIO()
    src = ConsoleSource(output_stream=out, stdin_stream=stdin)
    # Give reader thread time to drain stdin
    time.sleep(0.05)
    events = list(src.poll())
    if len(events) != 2:
        return f"expected 2 events, got {len(events)}"
    if events[0].source != "console" or events[0].kind != "console_input":
        return f"wrong event shape: {events[0]}"
    if events[0].payload.get("line") != "hello":
        return f"wrong payload: {events[0].payload}"
    if events[1].payload.get("line") != "world":
        return f"wrong second payload: {events[1].payload}"
    return None


# ---------------------------------------------------------------------------
# Case (b): console_write tool writes to output stream
# ---------------------------------------------------------------------------

def case_b_console_write_tool() -> str | None:
    out = io.StringIO()
    src = ConsoleSource(output_stream=out, stdin_stream=io.StringIO(""))
    src.write("test output\n")
    val = out.getvalue()
    if val != "test output\n":
        return f"expected 'test output\\n', got {val!r}"
    return None


# ---------------------------------------------------------------------------
# Case (c): stub_core routes console_input to console_write action
# ---------------------------------------------------------------------------

def case_c_stub_core_routes_console() -> str | None:
    registry = ToolRegistry()
    registry.register(
        "console_write",
        lambda **kw: None,
        schema={"text": {"type": "string", "default": ""}},
    )
    event = Event(source="console", kind="console_input", payload={"line": "ping"})
    actions = stub_core(event, registry)
    if len(actions) != 1:
        return f"expected 1 action, got {len(actions)}"
    if actions[0].verb != "console_write":
        return f"expected console_write, got {actions[0].verb}"
    text = actions[0].args.get("text", "")
    if "ping" not in text:
        return f"echoed text should contain 'ping', got {text!r}"
    return None


# ---------------------------------------------------------------------------
# Case (d): NCKEventLoop routes injected line → echo output (full roundtrip)
# ---------------------------------------------------------------------------

def case_d_loop_roundtrip() -> str | None:
    with tempfile.TemporaryDirectory() as tmp:
        config = _base_config(tmp)
        loop = NCKEventLoop(config)

        out = io.StringIO()
        stdin = _make_stdin(["roundtrip_test"])
        src = ConsoleSource(output_stream=out, stdin_stream=stdin)
        loop.add_source(src)

        # Verify _console_source is wired
        if loop._console_source is not src:
            return "_console_source not set after add_source"

        # Give reader thread time to queue the line
        time.sleep(0.05)

        # Run exactly 1 tick
        loop.run(max_ticks=1)

        written = out.getvalue()
        if "roundtrip_test" not in written:
            return f"expected 'roundtrip_test' in output, got {written!r}"
    return None


# ---------------------------------------------------------------------------
# Case (e): poke_proven — >=2 injected lines, all echoed (WriteConsoleInput analog)
# ---------------------------------------------------------------------------

def case_e_poke_proven() -> str | None:
    lines = ["poke-alpha", "poke-beta", "poke-gamma"]
    stdin = _make_stdin(lines)
    out = io.StringIO()
    src = ConsoleSource(output_stream=out, stdin_stream=stdin)

    with tempfile.TemporaryDirectory() as tmp:
        config = _base_config(tmp)
        loop = NCKEventLoop(config)
        loop.add_source(src)

        time.sleep(0.05)
        loop.run(max_ticks=1)

        written = out.getvalue()
        for line in lines:
            if line not in written:
                return f"line {line!r} not echoed; output: {written!r}"
    return None


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def main() -> int:
    cases = [
        ("a", "console_source_emits",     case_a_console_source_emits),
        ("b", "console_write_tool",        case_b_console_write_tool),
        ("c", "stub_core_routes_console",  case_c_stub_core_routes_console),
        ("d", "loop_roundtrip",            case_d_loop_roundtrip),
        ("e", "poke_proven",               case_e_poke_proven),
    ]
    failures = []
    for label, name, fn in cases:
        err = fn()
        if err:
            failures.append(f"  ({label}) {name}: {err}")

    if failures:
        print("NCK_CU_CONSOLE_SELFTEST FAIL")
        for f in failures:
            print(f)
        return 1

    passed = " ".join(label for label, _, _ in cases)
    print(f"NCK_CU_CONSOLE_SELFTEST PASS (cases: {passed})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
