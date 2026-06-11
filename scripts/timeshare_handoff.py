"""timeshare_handoff.py — handoff state machine for GPU timeshare (#123, eng-33).

Implements the serialization rule from research/june22-critical-path.md §3:
  pretrain holds the GPU by default; round windows checkpoint it out, run,
  then resume — NEVER concurrent. One model at a time.

State machine (fail-closed on any out-of-order transition):

  PRETRAIN_HOLDS_GPU
       |
       | checkpoint_out(segment_id, ckpt_dir)
       v
  CHECKPOINT_OUT
       |
       | open_window(round_id)
       v
  WINDOW_OPEN   <-- round sampling / train / eval jobs registered here
       |
       | close_window(round_id)  [requires all registered jobs terminal]
       v
  WINDOW_CLOSED
       |
       | resume_pretrain(segment_id, ckpt_dir)
       v
  PRETRAIN_HOLDS_GPU  (next segment)

Never-concurrent assertion:
  - WINDOW_OPEN requires a completed CHECKPOINT_OUT record.
  - RESUME requires WINDOW_CLOSED with zero in-flight jobs.
  - A second window may not open while one is already WINDOW_OPEN.

Each transition appends a receipt-grade record (segment id, wall clock,
tokens/steps so far, pacing block per the fp-14 meter pattern) to the
state file.

Dispatch-side interlock (complement of #105 guard):
  The #105 guard (train-daemon) refuses eval/export while a train job is
  live unless allow_during_train=true (HTTP 409, default-closed). This module
  is the complement: round windows must only dispatch AFTER CHECKPOINT_OUT,
  and pretrain resume must only fire AFTER WINDOW_CLOSED. The assertions here
  are state-machine checks (no HTTP calls), enforced at handoff time.

LAUNCH INTERLOCK (default-closed):
  Any code path that would actually start a GPU job is blocked unless
  EMBER_GATE_AUTHORIZED=1 AND --live. Selftests are 100% CPU-local.

Selftest: python timeshare_handoff.py --selftest
  Pure-logic, CPU only, < 30 s.
  Marker: TIMESHARE_HANDOFF_SELFTEST_PASS
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import shutil
import time
from datetime import datetime, timezone
from typing import Any


# ---------------------------------------------------------------------------
# State constants
# ---------------------------------------------------------------------------

STATE_PRETRAIN_HOLDS = "PRETRAIN_HOLDS_GPU"
STATE_CHECKPOINT_OUT = "CHECKPOINT_OUT"
STATE_WINDOW_OPEN    = "WINDOW_OPEN"
STATE_WINDOW_CLOSED  = "WINDOW_CLOSED"

_VALID_TRANSITIONS = {
    STATE_PRETRAIN_HOLDS: STATE_CHECKPOINT_OUT,
    STATE_CHECKPOINT_OUT: STATE_WINDOW_OPEN,
    STATE_WINDOW_OPEN:    STATE_WINDOW_CLOSED,
    STATE_WINDOW_CLOSED:  STATE_PRETRAIN_HOLDS,
}


# ---------------------------------------------------------------------------
# Launch interlock
# ---------------------------------------------------------------------------

def _check_launch_interlock(*, live: bool) -> None:
    """Refuse any GPU-touching path unless EMBER_GATE_AUTHORIZED=1 AND --live."""
    authorized = os.environ.get("EMBER_GATE_AUTHORIZED", "") == "1"
    if not (authorized and live):
        msg = (
            "TIMESHARE_LAUNCH_INTERLOCK_REFUSED: GPU path blocked in handoff. "
            "Requires EMBER_GATE_AUTHORIZED=1 (env) AND --live (flag). "
            "Real v0 pretrain fires only on fp-22's gate. "
            f"[authorized={authorized}, live={live}]"
        )
        print(msg)
        raise SystemExit(msg)


# ---------------------------------------------------------------------------
# Pacing block (fp-14 meter pattern)
# ---------------------------------------------------------------------------

def _pacing_block(
    tokens_so_far: int = 0,
    steps_so_far: int = 0,
    wall_s: float = 0.0,
) -> dict[str, Any]:
    """Build a pacing block per the fp-14 meter pattern."""
    return {
        "tokens_so_far": tokens_so_far,
        "steps_so_far": steps_so_far,
        "wall_s": round(wall_s, 3),
        "tok_per_s": round(tokens_so_far / wall_s, 1) if wall_s > 0 else None,
        "convention": (
            "pacing_total_s = wall time in governor/pacing sleeps; "
            "compute-only wall = elapsed - pacing_total_s"
        ),
    }


# ---------------------------------------------------------------------------
# HandoffMachine
# ---------------------------------------------------------------------------

class HandoffMachine:
    """Fail-closed timeshare handoff state machine.

    State is persisted to <state_dir>/handoff-state.json on every transition.
    All writes use sorted keys + fixed separators for byte-stable output.

    Usage::
        hm = HandoffMachine(state_dir)
        hm.checkpoint_out("seg-A", "/path/to/ckpt")
        hm.open_window("round-2")
        hm.register_job("round-2", "job-abc123")
        hm.mark_job_terminal("round-2", "job-abc123")
        hm.close_window("round-2")
        hm.resume_pretrain("seg-A", "/path/to/ckpt")
    """

    def __init__(self, state_dir: str) -> None:
        self.state_dir = state_dir
        self._state_file = os.path.join(state_dir, "handoff-state.json")
        os.makedirs(state_dir, exist_ok=True)
        if os.path.exists(self._state_file):
            with open(self._state_file, "r", encoding="utf-8") as f:
                self._state: dict[str, Any] = json.load(f)
        else:
            self._state = {
                "ticket": "TIMESHARE-HANDOFF",
                "sha_convention": (
                    "sha256 over on-disk raw bytes "
                    "(binary read, no line-ending normalization)"
                ),
                "current_state": STATE_PRETRAIN_HOLDS,
                "segment_id": None,
                "ckpt_dir": None,
                "round_id": None,
                "jobs": {},
                "transitions": [],
            }
            self._persist()

    # --- Core state accessors ---

    @property
    def current_state(self) -> str:
        return self._state["current_state"]

    def _ts(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    def _persist(self) -> None:
        """Write state atomically."""
        tmp = self._state_file + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            json.dump(self._state, f, sort_keys=True, separators=(",", ": "), indent=2)
        if os.path.exists(self._state_file):
            os.replace(tmp, self._state_file)
        else:
            os.rename(tmp, self._state_file)

    def _transition(
        self,
        expected_from: str,
        to: str,
        record: dict[str, Any],
    ) -> None:
        """Fail-closed transition guard. Raises ValueError on any violation."""
        current = self._state["current_state"]
        if current != expected_from:
            raise ValueError(
                f"TIMESHARE_HANDOFF_ILLEGAL_TRANSITION: "
                f"expected state={expected_from!r}, actual={current!r}. "
                f"Attempted transition → {to!r}. "
                f"Fail-closed: state not advanced."
            )
        expected_next = _VALID_TRANSITIONS.get(expected_from)
        if expected_next != to:
            raise ValueError(
                f"TIMESHARE_HANDOFF_ILLEGAL_TRANSITION: "
                f"from {expected_from!r} the only valid next state is "
                f"{expected_next!r}, not {to!r}."
            )
        record.update({"from": expected_from, "to": to, "ts": self._ts()})
        self._state["current_state"] = to
        self._state["transitions"].append(record)
        self._persist()

    # --- Transition methods ---

    def checkpoint_out(
        self,
        segment_id: str,
        ckpt_dir: str,
        *,
        tokens_so_far: int = 0,
        steps_so_far: int = 0,
        wall_s: float = 0.0,
        ckpt_files: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """PRETRAIN_HOLDS_GPU → CHECKPOINT_OUT.

        Records that the pretrain has written a checkpoint and released the GPU.
        Round windows may only open after this transition completes.
        ckpt_files: per-file sha256 map from the checkpoint manifest — carried
        in the transition record so the handoff receipt names the artifact by
        path AND hash, not path alone.
        """
        record: dict[str, Any] = {
            "event": "checkpoint_out",
            "segment_id": segment_id,
            "ckpt_dir": ckpt_dir,
            "ckpt_files": ckpt_files,
            "pacing": _pacing_block(tokens_so_far, steps_so_far, wall_s),
        }
        self._transition(STATE_PRETRAIN_HOLDS, STATE_CHECKPOINT_OUT, record)
        self._state["segment_id"] = segment_id
        self._state["ckpt_dir"] = ckpt_dir
        self._persist()
        return dict(record)

    def open_window(
        self,
        round_id: str,
        *,
        tokens_so_far: int = 0,
        steps_so_far: int = 0,
        wall_s: float = 0.0,
    ) -> dict[str, Any]:
        """CHECKPOINT_OUT → WINDOW_OPEN.

        Requires a completed CHECKPOINT_OUT (enforced by state machine).
        A second window may not open while one is already open.
        """
        # Extra guard: no open round already (concurrency check).
        if self._state.get("round_id") is not None:
            raise ValueError(
                f"TIMESHARE_HANDOFF_CONCURRENT_WINDOW: "
                f"round {self._state['round_id']!r} is already registered. "
                f"Close the current window before opening a new one."
            )
        record: dict[str, Any] = {
            "event": "open_window",
            "round_id": round_id,
            "pacing": _pacing_block(tokens_so_far, steps_so_far, wall_s),
        }
        self._transition(STATE_CHECKPOINT_OUT, STATE_WINDOW_OPEN, record)
        self._state["round_id"] = round_id
        self._state["jobs"] = {}
        self._persist()
        return dict(record)

    def register_job(self, round_id: str, job_id: str) -> None:
        """Register a job within the current WINDOW_OPEN round."""
        if self.current_state != STATE_WINDOW_OPEN:
            raise ValueError(
                f"TIMESHARE_HANDOFF_JOB_REGISTER_INVALID: "
                f"can only register jobs in WINDOW_OPEN, "
                f"current state={self.current_state!r}")
        if self._state.get("round_id") != round_id:
            raise ValueError(
                f"TIMESHARE_HANDOFF_JOB_ROUND_MISMATCH: "
                f"registered round={self._state.get('round_id')!r}, "
                f"got round_id={round_id!r}")
        self._state["jobs"][job_id] = {"status": "in_flight", "ts": self._ts()}
        self._persist()

    def mark_job_terminal(self, round_id: str, job_id: str, status: str = "completed") -> None:
        """Mark a job as terminal (completed / failed / cancelled)."""
        if self.current_state != STATE_WINDOW_OPEN:
            raise ValueError(
                f"TIMESHARE_HANDOFF_JOB_TERMINAL_INVALID: "
                f"can only mark jobs terminal in WINDOW_OPEN, "
                f"current state={self.current_state!r}")
        if job_id not in self._state["jobs"]:
            raise ValueError(
                f"TIMESHARE_HANDOFF_JOB_UNKNOWN: job_id={job_id!r} not registered")
        self._state["jobs"][job_id] = {"status": status, "ts": self._ts()}
        self._persist()

    def close_window(
        self,
        round_id: str,
        *,
        tokens_so_far: int = 0,
        steps_so_far: int = 0,
        wall_s: float = 0.0,
    ) -> dict[str, Any]:
        """WINDOW_OPEN → WINDOW_CLOSED.

        Requires ALL registered jobs to be terminal (not in_flight).
        Fail-closed: refuses if any job is still in_flight.
        """
        in_flight = [
            jid for jid, jrec in self._state.get("jobs", {}).items()
            if jrec["status"] == "in_flight"
        ]
        if in_flight:
            raise ValueError(
                f"TIMESHARE_HANDOFF_JOBS_IN_FLIGHT: "
                f"cannot close window {round_id!r} — "
                f"{len(in_flight)} job(s) still in_flight: {in_flight}. "
                f"Fail-closed: window not closed."
            )
        record: dict[str, Any] = {
            "event": "close_window",
            "round_id": round_id,
            "jobs_terminal": list(self._state.get("jobs", {}).keys()),
            "pacing": _pacing_block(tokens_so_far, steps_so_far, wall_s),
        }
        self._transition(STATE_WINDOW_OPEN, STATE_WINDOW_CLOSED, record)
        return dict(record)

    def resume_pretrain(
        self,
        segment_id: str,
        ckpt_dir: str,
        *,
        tokens_so_far: int = 0,
        steps_so_far: int = 0,
        wall_s: float = 0.0,
        live: bool = False,
        ckpt_files: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """WINDOW_CLOSED → PRETRAIN_HOLDS_GPU (resume).

        Requires WINDOW_CLOSED with zero in-flight jobs (enforced by transition
        guard + pre-check). If live=True, also validates the launch interlock.
        ckpt_files: per-file sha256 map of the checkpoint being resumed from
        (verified by load_checkpoint) — the checkpoint-in record carries the
        artifact path AND hashes.
        """
        # Extra check: confirm zero in-flight (belt + suspenders).
        in_flight = [
            jid for jid, jrec in self._state.get("jobs", {}).items()
            if jrec["status"] == "in_flight"
        ]
        if in_flight:
            raise ValueError(
                f"TIMESHARE_HANDOFF_RESUME_BLOCKED: "
                f"{len(in_flight)} job(s) still in_flight at resume time: "
                f"{in_flight}. Fail-closed."
            )
        if live:
            _check_launch_interlock(live=True)
        record: dict[str, Any] = {
            "event": "resume_pretrain",
            "segment_id": segment_id,
            "ckpt_dir": ckpt_dir,
            "ckpt_files": ckpt_files,
            "pacing": _pacing_block(tokens_so_far, steps_so_far, wall_s),
        }
        self._transition(STATE_WINDOW_CLOSED, STATE_PRETRAIN_HOLDS, record)
        self._state["segment_id"] = segment_id
        self._state["ckpt_dir"] = ckpt_dir
        self._state["round_id"] = None
        self._state["jobs"] = {}
        self._persist()
        return dict(record)

    def receipt_snapshot(self) -> dict[str, Any]:
        """Return a receipt-grade snapshot of the current state."""
        return {
            "ticket": "TIMESHARE-HANDOFF-SNAPSHOT",
            "ts": self._ts(),
            "issue": "wordingone/ember#123",
            "scope": "handoff state machine snapshot",
            "sha_convention": self._state["sha_convention"],
            "current_state": self._state["current_state"],
            "segment_id": self._state.get("segment_id"),
            "ckpt_dir": self._state.get("ckpt_dir"),
            "round_id": self._state.get("round_id"),
            "n_transitions": len(self._state.get("transitions", [])),
            "transitions": self._state.get("transitions", []),
            "jobs": self._state.get("jobs", {}),
            "pass": True,
            "verdict": "HANDOFF_SNAPSHOT_OK",
        }


# ---------------------------------------------------------------------------
# Selftest
# ---------------------------------------------------------------------------

def _selftest() -> None:
    """Drive the full legal transition sequence + three illegal-transition FAIL
    branches:
      1. Window open without checkpoint-out (wrong source state).
      2. Resume while a window job still in-flight.
      3. Concurrent second window (second open_window before close_window).

    All CPU, no GPU, no daemon, < 30 s.
    Marker: TIMESHARE_HANDOFF_SELFTEST_PASS
    """
    tmpdir = tempfile.mkdtemp(prefix="timeshare_handoff_test_")
    try:
        # ---- PASS branch: full legal sequence ----
        hm = HandoffMachine(os.path.join(tmpdir, "state-pass"))
        assert hm.current_state == STATE_PRETRAIN_HOLDS, hm.current_state

        fake_hashes = {"model.pt": "a" * 64, "optimizer.pt": "b" * 64, "rng.pt": "c" * 64}
        hm.checkpoint_out("seg-A", "/fake/ckpt/step-00000050",
                          tokens_so_far=1000, steps_so_far=50, wall_s=10.0,
                          ckpt_files=fake_hashes)
        assert hm.current_state == STATE_CHECKPOINT_OUT, hm.current_state

        hm.open_window("round-2",
                       tokens_so_far=1000, steps_so_far=50, wall_s=10.1)
        assert hm.current_state == STATE_WINDOW_OPEN, hm.current_state

        hm.register_job("round-2", "job-sampling-01")
        hm.register_job("round-2", "job-train-01")
        hm.mark_job_terminal("round-2", "job-sampling-01", "completed")
        hm.mark_job_terminal("round-2", "job-train-01", "completed")

        hm.close_window("round-2",
                        tokens_so_far=1000, steps_so_far=50, wall_s=15.0)
        assert hm.current_state == STATE_WINDOW_CLOSED, hm.current_state

        hm.resume_pretrain("seg-A", "/fake/ckpt/step-00000050",
                           tokens_so_far=1000, steps_so_far=50, wall_s=15.5,
                           ckpt_files=fake_hashes)
        assert hm.current_state == STATE_PRETRAIN_HOLDS, hm.current_state

        # Receipt snapshot after full cycle.
        snap = hm.receipt_snapshot()
        assert snap["pass"], snap
        assert snap["n_transitions"] == 4, snap["n_transitions"]
        # Checkpoint-out and checkpoint-in records carry artifact path + hashes.
        co_rec = snap["transitions"][0]
        rp_rec = snap["transitions"][3]
        assert co_rec["event"] == "checkpoint_out" and co_rec["ckpt_files"] == fake_hashes, co_rec
        assert rp_rec["event"] == "resume_pretrain" and rp_rec["ckpt_files"] == fake_hashes, rp_rec

        # ---- FAIL branch 1: window open without checkpoint-out ----
        hm_f1 = HandoffMachine(os.path.join(tmpdir, "state-fail1"))
        assert hm_f1.current_state == STATE_PRETRAIN_HOLDS
        try:
            hm_f1.open_window("round-bad")
            assert False, "FAIL: open_window should have raised (no checkpoint_out)"
        except ValueError as e:
            assert "ILLEGAL_TRANSITION" in str(e) or "expected state" in str(e).lower() or "CHECKPOINT_OUT" in str(e), str(e)
        # State must not have advanced.
        assert hm_f1.current_state == STATE_PRETRAIN_HOLDS, (
            f"State advanced on illegal transition: {hm_f1.current_state}")

        # ---- FAIL branch 2: resume while a window job still in-flight ----
        hm_f2 = HandoffMachine(os.path.join(tmpdir, "state-fail2"))
        hm_f2.checkpoint_out("seg-B", "/fake/ckpt/step-00000010")
        hm_f2.open_window("round-2b")
        hm_f2.register_job("round-2b", "job-inflight")
        # Do NOT mark job terminal — try to close_window.
        try:
            hm_f2.close_window("round-2b")
            assert False, "FAIL: close_window should have raised (in-flight job)"
        except ValueError as e:
            assert "in_flight" in str(e).lower() or "IN_FLIGHT" in str(e), str(e)
        # Now try resume_pretrain directly (still WINDOW_OPEN).
        try:
            hm_f2.resume_pretrain("seg-B", "/fake/ckpt/step-00000010")
            assert False, "FAIL: resume_pretrain should have raised (wrong state)"
        except ValueError as e:
            assert ("ILLEGAL_TRANSITION" in str(e) or
                    "WINDOW_CLOSED" in str(e) or
                    "in_flight" in str(e).lower()), str(e)

        # ---- FAIL branch 3: concurrent second window ----
        hm_f3 = HandoffMachine(os.path.join(tmpdir, "state-fail3"))
        hm_f3.checkpoint_out("seg-C", "/fake/ckpt/step-00000020")
        hm_f3.open_window("round-3a")
        hm_f3.register_job("round-3a", "job-x")
        hm_f3.mark_job_terminal("round-3a", "job-x", "completed")
        # Do NOT close window — try to open a second one.
        # First: transition to WINDOW_CLOSED requires close_window.
        # Trying open_window again from WINDOW_OPEN → ILLEGAL_TRANSITION.
        try:
            hm_f3.open_window("round-3b")
            assert False, "FAIL: second open_window should have raised"
        except ValueError as e:
            assert ("ILLEGAL_TRANSITION" in str(e) or
                    "CONCURRENT_WINDOW" in str(e) or
                    "WINDOW_OPEN" in str(e)), str(e)

        print("TIMESHARE_HANDOFF_SELFTEST_PASS")

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--selftest", action="store_true",
                    help="Run pure-logic CPU selftest (< 30 s)")
    ap.add_argument("--state-dir", default=None,
                    help="Directory for handoff state file")
    ap.add_argument("--snapshot", action="store_true",
                    help="Print receipt snapshot of current state and exit")
    args = ap.parse_args(argv)

    if args.selftest:
        _selftest()
        return

    state_dir = args.state_dir or tempfile.mkdtemp(prefix="timeshare_handoff_")
    hm = HandoffMachine(state_dir)

    if args.snapshot:
        print(json.dumps(hm.receipt_snapshot(), indent=2, sort_keys=True))
        return

    print(json.dumps(hm.receipt_snapshot(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
