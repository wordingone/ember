# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Subprocess worker for the cross-process custody ledger regression suite
(tests/ember_restart_model/test_custody_process_scope.py).

Ported from the two ad-hoc attack harnesses run this session (fburst-proclock
zzz_worker.py, fburst-unlinkwin zzz_unlink_worker.py) into a single reusable
worker with two subcommands so the repo test only needs one helper module.

race    -- barrier on a go-file, then race ONE PREPARED custody-ledger
           transition against N siblings on the same pointer. Optional
           --hold-ms injects a torn-state window: sleep AFTER the ledger
           bytes land (post _atomic_bytes) but BEFORE the external receipt
           commits, so a coordinator can kill this process mid-write.

unlink  -- drive a REAL bounded-quarantine eviction
           (PREPARE -> unlink victim -> COMMIT). In "held" mode, freezes
           right after the victim file is unlinked and right before the
           COMMITTED ledger frame is appended (the unlink window), writing
           a WINDOW_REACHED marker so a coordinator can kill it there.
           "recover" mode runs the same call cleanly and reports what
           happened (fresh win, defined loser, or idempotent recovery).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import run_vertical_slice as m


def _write_outcome(result_file: Path, outcome: dict[str, object]) -> None:
    result_file.write_text(json.dumps(outcome), encoding="utf-8")


EXPECTED_VICTIM_BYTES = b"victim-byte"


def cmd_race(args: argparse.Namespace) -> None:
    parent = Path(args.parent)
    pointer = args.pointer
    go_file = Path(args.go_file)
    result_file = Path(args.result_file)
    hold_ms = args.hold_ms

    # The bytes and hash minted here must be exactly the bytes the test fixture
    # wrote to disk (_fresh_custody_dir) -- verified below BEFORE the race
    # starts so a fixture drift shows up as a loud assertion, not a silently
    # mismatched ledger event.
    victim_path = parent / pointer
    on_disk = victim_path.read_bytes()
    assert on_disk == EXPECTED_VICTIM_BYTES, (
        f"fixture drift: on-disk victim bytes {on_disk!r} != expected {EXPECTED_VICTIM_BYTES!r}"
    )

    event = {
        "schema_version": m._CUSTODY_LEDGER_SCHEMA,
        "event": "PREPARED",
        "pointer": pointer,
        "bytes": len(EXPECTED_VICTIM_BYTES),
        "sha256": hashlib.sha256(EXPECTED_VICTIM_BYTES).hexdigest(),
        "reason": "process-race attack",
    }

    while not go_file.exists():
        time.sleep(0.0005)

    outcome: dict[str, object] = {"pid": os.getpid()}
    try:
        if hold_ms > 0:
            original = m._atomic_bytes

            def slow_atomic_bytes(path, payload):
                original(path, payload)
                if str(path).endswith(m._CUSTODY_LEDGER):
                    (parent / "HOLD_REACHED").write_text(str(os.getpid()))
                time.sleep(hold_ms / 1000.0)

            m._atomic_bytes = slow_atomic_bytes
        m._append_custody_ledger_transition(parent, event)
        outcome["result"] = "WON"
    except Exception as exc:  # noqa: BLE001 - classify the loser outcome
        outcome["result"] = "LOST"
        outcome["exc_type"] = type(exc).__name__
        outcome["exc_msg"] = str(exc)[:200]
    _write_outcome(result_file, outcome)


def cmd_unlink(args: argparse.Namespace) -> None:
    parent = Path(args.parent)
    mode = args.mode
    result_file = Path(args.result_file)
    tag = args.tag
    hold_s = args.hold_s

    outcome: dict[str, object] = {"pid": os.getpid(), "mode": mode}
    if mode == "held":
        m._MAX_QUARANTINE_FILES = 1  # force eviction of seeded evidence
        original_append = m._append_custody_ledger_transition
        state = {"held": False}

        def holding_append(p, event, **kw):
            if (not state["held"] and event.get("event") == "COMMITTED"
                    and event.get("reason") == "bounded evidence retention"):
                state["held"] = True
                victim = Path(p) / str(event["pointer"])
                marker = {
                    "pid": os.getpid(),
                    "pointer": event["pointer"],
                    "victim_exists_at_window": victim.exists(),
                }
                (parent.parent / "WINDOW_REACHED.json").write_text(
                    json.dumps(marker), encoding="utf-8")
                time.sleep(hold_s)  # killed here, or expires for the race leg
            return original_append(p, event, **kw)

        m._append_custody_ledger_transition = holding_append

    try:
        path = m._write_bounded_quarantine_evidence(
            parent, "attack", {"tag": tag, "pid": os.getpid()})
        outcome["result"] = "OK"
        outcome["evidence"] = path.name
    except Exception as exc:  # noqa: BLE001 - classify the outcome
        outcome["result"] = "RAISED"
        outcome["exc_type"] = type(exc).__name__
        outcome["exc_msg"] = str(exc)[:300]
    _write_outcome(result_file, outcome)


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    race_p = sub.add_parser("race")
    race_p.add_argument("parent")
    race_p.add_argument("pointer")
    race_p.add_argument("go_file")
    race_p.add_argument("result_file")
    race_p.add_argument("--hold-ms", type=int, default=0)
    race_p.set_defaults(func=cmd_race)

    unlink_p = sub.add_parser("unlink")
    unlink_p.add_argument("parent")
    unlink_p.add_argument("mode", choices=["held", "recover"])
    unlink_p.add_argument("result_file")
    unlink_p.add_argument("tag")
    unlink_p.add_argument("--hold-s", type=float, default=300.0)
    unlink_p.set_defaults(func=cmd_unlink)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
