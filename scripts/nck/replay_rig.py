#!/usr/bin/env python3
"""sp-6b replay rig — deterministic B3 episode replay + scoring (#282).

Instrument contract:
- load_battery() / load_encodings(): parse the frozen jsonl docs, join on id.
  Raises RigRefuse on any mismatch (missing id, count != 20).
- materialize(episode, sandbox_dir): write fixtures under sandbox_dir.
  mtime_offset_s applied relative to REPLAY_EPOCH (not wall-clock) for
  determinism. Refuses absolute relpaths or '..' traversal.
- build_events(episode, sandbox_dir): substitute '{root}' in all string
  payload values (recursively) with sandbox_dir; construct Event objects with
  the row's pinned ts VERBATIM. Asserts no '{root}' survives.
- replay_episode(episode, core, sandbox_dir) -> list[Action]: feeds each
  event to core(event, registry) in order; collects emitted Actions. Registry
  is fresh per episode with no-op recorders only (no live filesystem tools).
- score_episode(episode, actions) -> dict: deterministic pass/fail per the
  frozen pass rule (expected_verb + target_pattern).
- run_battery(core, write_receipt): replay all 20 in fresh per-episode
  tempdirs. Receipt written only when --run --write flags both present.
- verify_determinism(): two in-process runs produce identical streams+scores.

NEVER writes outside tempdirs unless --write is present on CLI.
"""
from __future__ import annotations

import inspect
import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

# ---------------------------------------------------------------------------
# Import the event-loop shapes from the sibling module
# ---------------------------------------------------------------------------
try:
    from nck.event_loop import Event, Action, ToolRegistry, stub_core
except ImportError:
    try:
        from event_loop import Event, Action, ToolRegistry, stub_core  # type: ignore[no-redef]
    except ImportError as _e:
        raise SystemExit(
            f"RIG_REFUSE: cannot import event_loop shapes: {_e}. "
            "scripts/nck/event_loop.py must be present."
        ) from _e

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BATTERY_PATH = REPO_ROOT / "docs" / "sp6-duty-battery.jsonl"
ENCODINGS_PATH = REPO_ROOT / "docs" / "sp6-duty-battery-encodings.jsonl"

# Fixed epoch for deterministic mtime_offset_s application.
# 2026-06-22T00:00:00Z — the Ember June-22 target date, before any episode ts.
REPLAY_EPOCH: float = datetime(2026, 6, 22, 0, 0, 0, tzinfo=timezone.utc).timestamp()

# Owner string used in target normalization
REPLAY_OWNER = "owner"

# Outward verbs — any of these in a silence episode = FAIL
OUTWARD_VERBS: frozenset[str] = frozenset({
    "reply", "ack-begin", "challenge", "clarify", "escalate",
    "report", "flag-missing", "repair-escalate", "gate-pass", "gate-fail",
    "execute-due", "gate-then-next", "clear-lock", "monitor",
})

# Silence verbs — episodes whose expected_verb is one of these and
# target_pattern == '^$' are silence episodes
SILENCE_VERBS: frozenset[str] = frozenset({
    "no-action", "heartbeat-only", "dedup", "clean",
})

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class RigRefuse(Exception):
    """Raised when the rig detects a contract violation and cannot proceed."""


# ---------------------------------------------------------------------------
# Battery + encodings loading
# ---------------------------------------------------------------------------


def load_battery() -> list[dict[str, Any]]:
    """Parse sp6-duty-battery.jsonl; return 20 episode rows.

    Raises RigRefuse if count != 20 or any row is missing 'id'.
    """
    raw = BATTERY_PATH.read_text(encoding="utf-8")
    rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
    if len(rows) != 20:
        raise RigRefuse(
            f"BATTERY_COUNT: expected 20 episodes, got {len(rows)}. "
            f"Battery may be corrupt or truncated."
        )
    for r in rows:
        if "id" not in r:
            raise RigRefuse(f"BATTERY_MISSING_ID: row has no 'id' field: {r!r}")
    return rows


def load_encodings() -> list[dict[str, Any]]:
    """Parse sp6-duty-battery-encodings.jsonl; return 20 encoding rows.

    Raises RigRefuse if count != 20 or any row is missing 'id'.
    """
    raw = ENCODINGS_PATH.read_text(encoding="utf-8")
    rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
    if len(rows) != 20:
        raise RigRefuse(
            f"ENCODINGS_COUNT: expected 20 encoding rows, got {len(rows)}. "
            f"Encodings file may be corrupt or truncated."
        )
    for r in rows:
        if "id" not in r:
            raise RigRefuse(f"ENCODINGS_MISSING_ID: row has no 'id' field: {r!r}")
    return rows


def join_battery_encodings() -> list[dict[str, Any]]:
    """Load and join battery + encodings on 'id'.

    Returns a list of 20 merged episode dicts:
      {**battery_row, 'events': [...], 'fixtures': [...], 'enc_notes': ...}

    Raises RigRefuse on id set mismatch.
    """
    battery = load_battery()
    encodings = load_encodings()

    bat_ids = {r["id"] for r in battery}
    enc_ids = {r["id"] for r in encodings}

    only_bat = sorted(bat_ids - enc_ids)
    only_enc = sorted(enc_ids - bat_ids)
    if only_bat or only_enc:
        raise RigRefuse(
            f"JOIN_MISMATCH: battery-only ids={only_bat}; encoding-only ids={only_enc}. "
            "Battery and encodings must have identical id sets."
        )

    enc_by_id = {r["id"]: r for r in encodings}
    merged: list[dict[str, Any]] = []
    for b in battery:
        e = enc_by_id[b["id"]]
        merged.append({
            **b,
            "events": e.get("events", []),
            "fixtures": e.get("fixtures", []),
            "enc_notes": e.get("notes", ""),
        })
    return merged


# ---------------------------------------------------------------------------
# Fixture materialization
# ---------------------------------------------------------------------------


def _check_safe_relpath(relpath: str) -> None:
    """Raise RigRefuse if relpath is absolute or contains '..'."""
    if os.path.isabs(relpath):
        raise RigRefuse(
            f"FIXTURE_ABSOLUTE: fixture relpath {relpath!r} is absolute. "
            "All fixture relpaths must be sandbox-relative."
        )
    parts = Path(relpath).parts
    if ".." in parts:
        raise RigRefuse(
            f"FIXTURE_TRAVERSAL: fixture relpath {relpath!r} contains '..'. "
            "Path traversal is not permitted."
        )


def materialize(episode: dict[str, Any], sandbox_dir: str) -> None:
    """Write all fixtures for an episode into sandbox_dir.

    - content_json: written as compact JSON (no trailing newline beyond what
      json.dumps produces — compact means no indent, separators=(',', ':')).
    - content_text: written verbatim (bytes as-is in UTF-8).
    - mtime: ALWAYS pinned to REPLAY_EPOCH + mtime_offset_s (offset 0 pins to
      the epoch itself). Wall-clock mtimes would leak nondeterminism into any
      seat prompt that renders file ages (sp-6c contract).

    Refuses absolute relpaths or '..' traversal (raises RigRefuse).
    """
    sandbox = Path(sandbox_dir)
    for fx in episode.get("fixtures", []):
        relpath: str = fx.get("relpath", "")
        _check_safe_relpath(relpath)
        dest = sandbox / relpath
        dest.parent.mkdir(parents=True, exist_ok=True)

        if "content_json" in fx:
            content = json.dumps(fx["content_json"], separators=(",", ":"))
            dest.write_text(content, encoding="utf-8")
        elif "content_text" in fx:
            dest.write_text(fx["content_text"], encoding="utf-8")
        else:
            raise RigRefuse(
                f"FIXTURE_NO_CONTENT: fixture {relpath!r} in episode {episode['id']!r} "
                "has neither content_json nor content_text."
            )

        offset: int = fx.get("mtime_offset_s", 0)
        target_mtime = REPLAY_EPOCH + offset
        os.utime(str(dest), (target_mtime, target_mtime))


# ---------------------------------------------------------------------------
# {root} substitution + Event construction
# ---------------------------------------------------------------------------


def _substitute_root(value: Any, sandbox_dir: str) -> Any:
    """Recursively substitute the literal '{root}' prefix with sandbox_dir
    in all string values within value (which may be a dict, list, or scalar).
    """
    if isinstance(value, str):
        return value.replace("{root}", sandbox_dir)
    if isinstance(value, dict):
        return {k: _substitute_root(v, sandbox_dir) for k, v in value.items()}
    if isinstance(value, list):
        return [_substitute_root(v, sandbox_dir) for v in value]
    return value


def _assert_no_root(value: Any, context: str) -> None:
    """Raise AssertionError if '{root}' survives anywhere in value."""
    dumped = json.dumps(value)
    if "{root}" in dumped:
        raise AssertionError(
            f"ROOT_REMAINS: literal '{{root}}' survives after substitution in {context}. "
            f"Payload fragment: {dumped[:200]!r}"
        )


def build_events(episode: dict[str, Any], sandbox_dir: str) -> list[Event]:
    """Substitute '{root}' in all string payload values and construct Events.

    - ts is taken VERBATIM from the encoding row (pinned synthetic timestamp).
    - After substitution, asserts no '{root}' remains anywhere in the payload.

    Returns list of Event objects in the row's original order.
    """
    events: list[Event] = []
    for ev_row in episode.get("events", []):
        payload = _substitute_root(ev_row.get("payload", {}), sandbox_dir)
        _assert_no_root(payload, f"episode {episode['id']!r} event payload")
        events.append(Event(
            source=ev_row["source"],
            kind=ev_row["kind"],
            payload=payload,
            ts=ev_row["ts"],  # VERBATIM — pinned synthetic timestamp
        ))
    return events


# ---------------------------------------------------------------------------
# No-op tool registry for replay isolation
# ---------------------------------------------------------------------------

# All verbs that any episode's expected_verb references, plus the
# stub_core's own write_gate_note. The recorder captures calls for
# scoring but never touches the real filesystem outside the sandbox.
_ALL_VERBS: list[str] = [
    "reply", "ack-begin", "challenge", "clarify", "escalate",
    "gate-pass", "gate-fail", "dedup", "execute-due", "heartbeat-only",
    "monitor", "gate-then-next", "clear-lock", "repair-escalate",
    "flag-missing", "report", "clean", "no-action",
    # stub_core internal
    "write_gate_note", "heartbeat_touch",
]


def _make_noop_registry() -> ToolRegistry:
    """Return a fresh ToolRegistry with no-op recorders for all known verbs.

    The recorders accept any keyword arguments (the dispatch protocol) and
    return an empty dict. They do NOT touch the filesystem.
    """
    registry = ToolRegistry()
    for verb in _ALL_VERBS:
        registry.register(
            verb,
            lambda **_kw: {},
            schema={},
            concurrency_safe=True,
            read_only=True,
            permission_class="noop",
        )
    return registry


# ---------------------------------------------------------------------------
# Episode replay
# ---------------------------------------------------------------------------


def _core_accepts_sandbox(core: Callable[..., Any]) -> bool:
    """True when core declares >=3 positional parameters (sp-6c seat-core
    protocol: core(event, registry, sandbox_dir)). 2-param cores (stub_core)
    keep the original call shape."""
    try:
        sig = inspect.signature(core)
    except (TypeError, ValueError):
        return False
    positional = [
        p for p in sig.parameters.values()
        if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
    ]
    return len(positional) >= 3


def replay_episode(
    episode: dict[str, Any],
    core: Callable[..., list[Action]],
    sandbox_dir: str,
) -> list[Action]:
    """Replay one episode: feed each event to core, collect emitted Actions.

    - Registry is fresh (no-op recorders) — no live filesystem outside sandbox.
    - Actions are returned in the order they were emitted across all events.
    - Cores declaring a third positional parameter receive sandbox_dir
      (sp-6c seat protocol — seats render world state from the sandbox).
    """
    registry = _make_noop_registry()
    events = build_events(episode, sandbox_dir)
    takes_sandbox = _core_accepts_sandbox(core)
    collected: list[Action] = []
    for event in events:
        actions = core(event, registry, sandbox_dir) if takes_sandbox \
            else core(event, registry)
        collected.extend(actions)
    return collected


# ---------------------------------------------------------------------------
# Target normalization
# ---------------------------------------------------------------------------


def _normalize_target(action: Action, event: Event, sandbox_dir: str) -> str:
    """Normalize an action's target per the pinned order:

    1. args['target'] — use verbatim.
    2. args['to']:
       - If equals event.payload['from'] → 'sender'
       - If the LITERAL string 'sender' without matching the event's actual
         sender → 'literal-sender' (deictic guard: a seat must name the real
         sender; emitting the word 'sender' must not match '^sender$')
       - If equals 'owner' or REPLAY_OWNER → 'owner'
       - Else → raw value
    3. args['path'] — path RELATIVE to sandbox_dir (forward slashes).
    4. '' — empty string.
    """
    args = action.args
    if "target" in args:
        return str(args["target"])
    if "to" in args:
        to_val = args["to"]
        evt_from = event.payload.get("from") if event else None
        if evt_from is not None and to_val == evt_from:
            return "sender"
        if to_val == "sender":
            return "literal-sender"
        if to_val == "owner" or to_val == REPLAY_OWNER:
            return "owner"
        return str(to_val)
    if "path" in args:
        raw_path = str(args["path"])
        sandbox_abs = os.path.abspath(sandbox_dir)
        abs_path = os.path.abspath(raw_path)
        try:
            rel = os.path.relpath(abs_path, sandbox_abs)
        except ValueError:
            # Windows: different drives — fall back to raw basename
            rel = os.path.basename(abs_path)
        return rel.replace("\\", "/")
    return ""


# ---------------------------------------------------------------------------
# Episode scoring
# ---------------------------------------------------------------------------


def score_episode(
    episode: dict[str, Any],
    actions: list[Action],
    sandbox_dir: str = "",
) -> dict[str, Any]:
    """Deterministic pass/fail per the frozen battery pass rule.

    Silence episodes (expected_verb in SILENCE_VERBS AND target_pattern == '^$'):
      PASS iff no action with an OUTWARD verb is emitted.
      Internal jsonl/heartbeat notes (non-outward verbs) do not fail silence.

    Action episodes:
      PASS iff at least one emitted action has verb == expected_verb AND
      its normalized target matches target_pattern (re.search).

    Returns {id, expected_verb, target_pattern, pass: bool, reason: str,
             emitted: [(verb, normalized_target), ...]}.
    """
    ep_id = episode["id"]
    expected_verb: str = episode["expected_verb"]
    target_pattern: str = episode["target_pattern"]

    # Build the originating event for normalization (first event in episode).
    # If there are no events, use a blank Event.
    raw_events = episode.get("events", [])
    if raw_events:
        # Reconstruct with root substituted if sandbox_dir given
        first_ev_row = raw_events[0]
        payload = (
            _substitute_root(first_ev_row.get("payload", {}), sandbox_dir)
            if sandbox_dir else first_ev_row.get("payload", {})
        )
        orig_event = Event(
            source=first_ev_row["source"],
            kind=first_ev_row["kind"],
            payload=payload,
            ts=first_ev_row["ts"],
        )
    else:
        orig_event = Event(source="", kind="", payload={}, ts="")

    emitted = [
        (a.verb, _normalize_target(a, orig_event, sandbox_dir))
        for a in actions
    ]

    is_silence = (expected_verb in SILENCE_VERBS and target_pattern == "^$")

    if is_silence:
        outward_emitted = [v for v, _ in emitted if v in OUTWARD_VERBS]
        passed = len(outward_emitted) == 0
        reason = (
            "PASS: no outward action emitted" if passed
            else f"FAIL: outward verbs emitted: {outward_emitted}"
        )
    else:
        # Action episode: at least one action must match verb + target
        pat = re.compile(target_pattern)
        matched = [
            (v, t) for v, t in emitted
            if v == expected_verb and pat.search(t)
        ]
        passed = len(matched) > 0
        reason = (
            f"PASS: matched {matched[0]}" if passed
            else (
                f"FAIL: expected verb={expected_verb!r} matching {target_pattern!r}; "
                f"emitted={emitted}"
            )
        )

    return {
        "id": ep_id,
        "expected_verb": expected_verb,
        "target_pattern": target_pattern,
        "pass": passed,
        "reason": reason,
        "emitted": emitted,
    }


# ---------------------------------------------------------------------------
# Determinism verification
# ---------------------------------------------------------------------------


def verify_determinism(
    core: Callable[[Event, ToolRegistry], list[Action]] = stub_core,
) -> bool:
    """Run the battery twice in-process; assert identical (verb, target) streams
    and identical scores. Returns True on success; raises AssertionError on mismatch.

    Uses fresh per-episode tempdirs on both passes (independence rule preserved).
    """
    run1 = _run_all(core)
    run2 = _run_all(core)

    for (id1, stream1, score1), (id2, stream2, score2) in zip(run1, run2):
        assert id1 == id2, f"DETERMINISM: episode id mismatch {id1!r} vs {id2!r}"
        assert stream1 == stream2, (
            f"DETERMINISM: episode {id1!r} action stream differs between runs.\n"
            f"  run1: {stream1}\n  run2: {stream2}"
        )
        assert score1["pass"] == score2["pass"], (
            f"DETERMINISM: episode {id1!r} score differs between runs."
        )
    return True


def _run_all(
    core: Callable[[Event, ToolRegistry], list[Action]],
) -> list[tuple[str, list[tuple[str, str]], dict[str, Any]]]:
    """Inner helper: replay all 20, return [(id, emitted_stream, score_dict)]."""
    episodes = join_battery_encodings()
    results = []
    for ep in episodes:
        with tempfile.TemporaryDirectory(prefix="sp6b-replay-") as tmpdir:
            materialize(ep, tmpdir)
            actions = replay_episode(ep, core, tmpdir)
            score = score_episode(ep, actions, sandbox_dir=tmpdir)
        stream = [(a.verb, _normalize_target(a, Event(source="", kind="", payload={}, ts=""), ""))
                  for a in actions]
        results.append((ep["id"], stream, score))
    return results


# ---------------------------------------------------------------------------
# Main battery runner
# ---------------------------------------------------------------------------


def run_battery(
    core: Callable[[Event, ToolRegistry], list[Action]] = stub_core,
    write_receipt: bool = False,
) -> list[dict[str, Any]]:
    """Replay all 20 episodes; return list of score dicts.

    Each episode runs in its own fresh tempdir (independence).
    Receipt written to receipts/sp6b-replay-rig-<ts>.json only when
    write_receipt=True AND the process was invoked with --run --write.

    Bare invocation (no --run) exits 1 with a STAGED line.
    """
    episodes = join_battery_encodings()
    results: list[dict[str, Any]] = []

    for ep in episodes:
        with tempfile.TemporaryDirectory(prefix="sp6b-ep-") as tmpdir:
            materialize(ep, tmpdir)
            actions = replay_episode(ep, core, tmpdir)
            score = score_episode(ep, actions, sandbox_dir=tmpdir)
        results.append(score)

    if write_receipt:
        _write_receipt(results)

    return results


def _write_receipt(results: list[dict[str, Any]]) -> None:
    """Write a receipt JSON to receipts/ directory."""
    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt_dir = REPO_ROOT / "receipts"
    receipt_dir.mkdir(exist_ok=True)
    fname = receipt_dir / f"sp6b-replay-rig-{ts}.json"

    n_pass = sum(1 for r in results if r["pass"])
    receipt = {
        "ticket": "SP6B-REPLAY-RIG",
        "ts": ts,
        "status": "complete",
        "metric": {
            "pass_count": n_pass,
            "total": len(results),
            "pass_pct": round(100.0 * n_pass / len(results), 1) if results else 0.0,
        },
        "episodes": results,
    }
    fname.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(f"RECEIPT: {fname}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    args = sys.argv[1:]

    if "--run" not in args:
        print(
            "STAGED: sp6b replay rig loaded but not triggered. "
            "Pass --run to execute the battery (and --write to record a receipt). "
            "This exit-1 is the evidence-promotion gate: bare invocation must not "
            "produce a receipt."
        )
        return 1

    write_receipt = "--write" in args
    results = run_battery(core=stub_core, write_receipt=write_receipt)

    n_pass = sum(1 for r in results if r["pass"])
    print(f"SP6B_REPLAY_RIG: {n_pass}/{len(results)} episodes PASS (stub_core baseline)")
    for r in results:
        status = "PASS" if r["pass"] else "FAIL"
        print(f"  {r['id']}: {status} — {r['reason']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
