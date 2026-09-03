# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Subprocess worker for the cross-process custody ledger regression suite
(tests/ember_restart_model/domain-governance/test_custody_process_scope.py).

Ported from the two ad-hoc negative-test harnesses run this session
(fburst-proclock zzz_worker.py, fburst-unlinkwin zzz_unlink_worker.py) into a
single reusable worker with two subcommands so the repo test only needs one
helper module.

race    -- barrier on a go-file, then race ONE PREPARED custody-ledger
           transition against N siblings on the same pointer. Optional
           --hold-ms injects a torn-state window AFTER the ledger bytes
           land (post _atomic_bytes) but BEFORE the external receipt
           commits: the worker writes a HOLD_REACHED marker, then BLOCKS
           polling for a RELEASE file that the kill path never creates,
           bounded by --hold-ms as a max-wait ceiling. A coordinator that
           observes the marker is provably killing a still-blocked
           process, never one free-running on a fixed sleep; a run that
           is never killed and never released exits nonzero (97) once
           the ceiling elapses, instead of completing or hanging.

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

# issue2015 exact-local-import:src/ember/infrastructure/tools/ember-restart-3b/run_vertical_slice.py
import importlib.util as _ember_58a9db1b1610c537_importlib
import sys as _ember_58a9db1b1610c537_sys
from pathlib import Path as _ember_58a9db1b1610c537_Path
_ember_58a9db1b1610c537_path = _ember_58a9db1b1610c537_Path(__file__).resolve().parent.joinpath('run_vertical_slice.py')
if not _ember_58a9db1b1610c537_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/infrastructure/tools/ember-restart-3b/run_vertical_slice.py')
_ember_58a9db1b1610c537_aliases = ('_ember_issue2015_58a9db1b1610c537', 'run_vertical_slice', 'src.ember.infrastructure.tools.ember-restart-3b.run_vertical_slice')
_ember_58a9db1b1610c537_existing = []
for _ember_58a9db1b1610c537_alias in _ember_58a9db1b1610c537_aliases:
    _ember_58a9db1b1610c537_candidate = _ember_58a9db1b1610c537_sys.modules.get(_ember_58a9db1b1610c537_alias)
    if _ember_58a9db1b1610c537_candidate is not None and all(_ember_58a9db1b1610c537_candidate is not item for item in _ember_58a9db1b1610c537_existing):
        _ember_58a9db1b1610c537_existing.append(_ember_58a9db1b1610c537_candidate)
if len(_ember_58a9db1b1610c537_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/infrastructure/tools/ember-restart-3b/run_vertical_slice.py')
if _ember_58a9db1b1610c537_existing:
    _ember_58a9db1b1610c537_module = _ember_58a9db1b1610c537_existing[0]
    _ember_58a9db1b1610c537_observed = getattr(_ember_58a9db1b1610c537_module, '__file__', None)
    if _ember_58a9db1b1610c537_observed is None or _ember_58a9db1b1610c537_Path(_ember_58a9db1b1610c537_observed).resolve() != _ember_58a9db1b1610c537_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/infrastructure/tools/ember-restart-3b/run_vertical_slice.py')
else:
    _ember_58a9db1b1610c537_spec = _ember_58a9db1b1610c537_importlib.spec_from_file_location('_ember_issue2015_58a9db1b1610c537', _ember_58a9db1b1610c537_path)
    if _ember_58a9db1b1610c537_spec is None or _ember_58a9db1b1610c537_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/infrastructure/tools/ember-restart-3b/run_vertical_slice.py')
    _ember_58a9db1b1610c537_module = _ember_58a9db1b1610c537_importlib.module_from_spec(_ember_58a9db1b1610c537_spec)
    for _ember_58a9db1b1610c537_alias in _ember_58a9db1b1610c537_aliases:
        _ember_58a9db1b1610c537_prior = _ember_58a9db1b1610c537_sys.modules.get(_ember_58a9db1b1610c537_alias)
        if _ember_58a9db1b1610c537_prior is not None and _ember_58a9db1b1610c537_prior is not _ember_58a9db1b1610c537_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/infrastructure/tools/ember-restart-3b/run_vertical_slice.py')
        _ember_58a9db1b1610c537_sys.modules[_ember_58a9db1b1610c537_alias] = _ember_58a9db1b1610c537_module
    try:
        _ember_58a9db1b1610c537_spec.loader.exec_module(_ember_58a9db1b1610c537_module)
    except BaseException:
        for _ember_58a9db1b1610c537_alias in _ember_58a9db1b1610c537_aliases:
            if _ember_58a9db1b1610c537_sys.modules.get(_ember_58a9db1b1610c537_alias) is _ember_58a9db1b1610c537_module:
                _ember_58a9db1b1610c537_sys.modules.pop(_ember_58a9db1b1610c537_alias, None)
        raise
for _ember_58a9db1b1610c537_alias in _ember_58a9db1b1610c537_aliases:
    _ember_58a9db1b1610c537_prior = _ember_58a9db1b1610c537_sys.modules.get(_ember_58a9db1b1610c537_alias)
    if _ember_58a9db1b1610c537_prior is not None and _ember_58a9db1b1610c537_prior is not _ember_58a9db1b1610c537_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/infrastructure/tools/ember-restart-3b/run_vertical_slice.py')
    _ember_58a9db1b1610c537_sys.modules[_ember_58a9db1b1610c537_alias] = _ember_58a9db1b1610c537_module
m = _ember_58a9db1b1610c537_module
# issue2015 exact-local-import-end:src/ember/infrastructure/tools/ember-restart-3b/run_vertical_slice.py


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
        "reason": "process-race negative test",
    }

    while not go_file.exists():
        time.sleep(0.0005)

    outcome: dict[str, object] = {"pid": os.getpid()}
    try:
        if hold_ms > 0:
            original = m._atomic_bytes
            release_file = parent / "RELEASE"

            def slow_atomic_bytes(path, payload):
                original(path, payload)
                if str(path).endswith(m._CUSTODY_LEDGER):
                    (parent / "HOLD_REACHED").write_text(str(os.getpid()))
                    deadline = time.time() + (hold_ms / 1000.0)
                    while not release_file.exists():
                        if time.time() >= deadline:
                            # Ceiling reached with no release and no kill:
                            # the sync window closed on its own, which is a
                            # broken invariant for this worker mode -- never
                            # a silent success. Exit nonzero without writing
                            # an outcome file.
                            sys.exit(97)
                        time.sleep(0.01)

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
            parent, "probe", {"tag": tag, "pid": os.getpid()})
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
