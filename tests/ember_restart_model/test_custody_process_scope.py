# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Cross-PROCESS regression coverage for the #934 custody ledger writer lock.

Ported (bounded, repo-shaped, not burst-shaped) from two ad-hoc attack
harnesses executed 5+ rounds each this session and REUSED here rather than
reinvented:

  - fburst-proclock/tools/ember-restart-3b/zzz_proc_attack.py + zzz_worker.py
    -> test_exactly_once_across_processes, test_kill_mid_write_converges
  - fburst-unlinkwin/tools/ember-restart-3b/zzz_unlink_attack.py +
    zzz_unlink_worker.py
    -> test_unlink_window_kill_recovery, test_unlink_window_live_race

Deviations from the source harnesses (each named + justified so a reviewer
never has to diff the two by hand):

  1. Rounds cut way down (5/8-process race -> 2 rounds; 5x3 unlink rounds ->
     1 round per test) and hold durations shrunk (5000ms torn-write hold ->
     800ms; 300s unlink-window hold -> 20s ceiling, released by an
     immediate kill once the window marker lands) so the whole module stays
     under the wall-clock budget while keeping every race window real.
  2. The session-side external kill-receipt ledger append is replaced by an
     in-tmp_path receipt list. Kill discipline (receipt
     before kill, exact spawned PID, JSON serializer) is preserved in full;
     only the destination changes, because repo tests cannot depend on any
     machine-local ledger being present or writable — that discipline is a
     session rail, not a repo contract.
  3. Worker processes are consolidated into one reusable module,
     tools/ember-restart-3b/custody_process_scope_worker.py, with "race" and
     "unlink" subcommands standing in for zzz_worker.py /
     zzz_unlink_worker.py so the repo carries one helper instead of two.
  4. All scratch custody directories live under pytest's tmp_path, never a
     hand-picked scratch root.

All four legs exercise Windows-specific machinery in
run_vertical_slice._custody_ledger_write_lock (the named machine-wide mutex
+ WAIT_ABANDONED-tolerant acquire). They skip cleanly on non-Windows; a
POSIX flock twin (the module's fcntl.flock branch) is a cheap follow-up but
is not implemented here.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TOOLS_DIR = ROOT / "tools" / "ember-restart-3b"
WORKER = TOOLS_DIR / "custody_process_scope_worker.py"

sys.path.insert(0, str(TOOLS_DIR))

import run_vertical_slice as m  # noqa: E402

pytestmark = pytest.mark.skipif(
    os.name != "nt",
    reason=(
        "custody ledger cross-process lock uses a Windows named mutex "
        "(_windows_custody_ledger_mutex); the POSIX fcntl.flock branch is "
        "real inter-process locking too but is not exercised by this "
        "regression yet -- tracked as a follow-up, not reproduced here."
    ),
)

POINTER = ".checkpoint-quarantine/candidate-" + ("a" * 64) + ".json"


# --------------------------------------------------------------------------
# shared helpers
# --------------------------------------------------------------------------

def _write_kill_receipt(receipts_path: Path, pid: int, script: str) -> None:
    """Kill-discipline receipt (JSON serializer, exact PID) written BEFORE
    the kill -- destination is tmp_path, never the live vigil ledger."""
    receipt = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "script": script,
        "pids": [pid],
        "match_rule": "subprocess spawned by this test, exact pid",
        "survivors_expected": "none",
    }
    with receipts_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(receipt) + "\n")


def _fresh_custody_dir(base: Path, tag: str) -> Path:
    d = base / f"custody-{tag}"
    (d / ".checkpoint-quarantine").mkdir(parents=True)
    (d / ".checkpoint-quarantine" / f"candidate-{'a' * 64}.json").write_bytes(b"victim-byte")
    return d


def _spawn_race(parent: Path, go: Path, result: Path, *, hold_ms: int = 0) -> subprocess.Popen:
    cmd = [sys.executable, str(WORKER), "race", str(parent), POINTER, str(go), str(result)]
    if hold_ms:
        cmd += ["--hold-ms", str(hold_ms)]
    return subprocess.Popen(cmd, cwd=str(TOOLS_DIR))


def _spawn_unlink(parent: Path, mode: str, result: Path, tag: str, *, hold_s: float = 0.0) -> subprocess.Popen:
    cmd = [sys.executable, str(WORKER), "unlink", str(parent), mode, str(result), tag]
    if hold_s:
        cmd += ["--hold-s", str(hold_s)]
    return subprocess.Popen(cmd, cwd=str(TOOLS_DIR))


def _read_ledger_prepared_count(parent: Path) -> int:
    _, events = m._custody_ledger_snapshot(parent)
    m._validate_custody_ledger_frame_chain(events)  # raises if chain corrupt
    return sum(
        1 for e in events
        if isinstance(e, dict)
        and e.get("schema_version") == m._CUSTODY_LEDGER_SCHEMA
        and e.get("event") == "PREPARED"
    )


def _snapshot(parent: Path) -> dict:
    ledger = parent / m._CUSTODY_LEDGER
    events: list = []
    if ledger.exists():
        for line in ledger.read_bytes().splitlines():
            if line.strip():
                events.append(json.loads(line))
    return {"events": events, "n": len(events)}


def _committed_pointers(events: list) -> list:
    return [e.get("pointer") for e in events
            if e.get("event") == "COMMITTED"
            and e.get("schema_version") == m._CUSTODY_LEDGER_SCHEMA]


def _wait_window_marker(marker: Path, timeout: float = 10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if marker.exists():
            return json.loads(marker.read_text())
        time.sleep(0.02)
    return None


# --------------------------------------------------------------------------
# Leg A -- exactly-once across 8 processes
# --------------------------------------------------------------------------

def test_exactly_once_across_processes(tmp_path: Path) -> None:
    n = 8
    rounds = 2
    for r in range(rounds):
        parent = _fresh_custody_dir(tmp_path, f"a{r}")
        go = parent / "GO"
        results = [parent / f"res-{i}.json" for i in range(n)]
        procs = [_spawn_race(parent, go, results[i]) for i in range(n)]
        time.sleep(0.15)  # let every worker reach the barrier
        go.write_text("go")
        for p in procs:
            assert p.wait(timeout=30) is not None

        outcomes = [json.loads(res.read_text()) for res in results]
        won = [o for o in outcomes if o["result"] == "WON"]
        lost = [o for o in outcomes if o["result"] == "LOST"]
        defined = all("already exists" in (o.get("exc_msg") or "") for o in lost)

        assert len(won) == 1, f"round {r}: expected exactly one winner, got {outcomes}"
        assert len(lost) == n - 1, f"round {r}: expected {n - 1} losers, got {outcomes}"
        assert defined, f"round {r}: a loser failed on an undefined exception: {lost}"
        assert _read_ledger_prepared_count(parent) == 1


# --------------------------------------------------------------------------
# Leg B -- kill mid-write (torn state), fresh process converges
# --------------------------------------------------------------------------

def test_kill_mid_write_converges(tmp_path: Path) -> None:
    receipts = tmp_path / "kill-receipts.jsonl"
    parent = _fresh_custody_dir(tmp_path, "b0")
    go = parent / "GO"
    res = parent / "res-hold.json"

    p = _spawn_race(parent, go, res, hold_ms=800)
    time.sleep(0.15)
    go.write_text("go")

    hold_marker = parent / "HOLD_REACHED"
    deadline = time.time() + 5
    while not hold_marker.exists() and time.time() < deadline:
        time.sleep(0.02)
    hold_reached = hold_marker.exists()
    ledger_path = parent / m._CUSTODY_LEDGER
    ledger_bytes_at_kill = ledger_path.exists() and ledger_path.stat().st_size > 0

    assert hold_reached, "worker never signalled it was holding mid-write"
    assert ledger_bytes_at_kill, "ledger bytes had not landed before the kill window"

    _write_kill_receipt(receipts, p.pid, "test_kill_mid_write_converges")
    p.kill()
    p.wait(timeout=15)
    assert p.poll() is not None, "killed worker still alive"

    # Fresh process converges over the same target.
    res2 = parent / "res-fresh.json"
    go2 = parent / "GO2"
    go2.write_text("go")  # pre-set so the fresh worker proceeds immediately
    p2 = _spawn_race(parent, go2, res2)
    try:
        p2.wait(timeout=30)
    except subprocess.TimeoutExpired:
        p2.kill()
        pytest.fail("fresh process WEDGED after kill-mid-write (lock never released)")

    fresh = json.loads(res2.read_text())
    assert fresh["result"] in ("WON", "LOST")

    prepared = _read_ledger_prepared_count(parent)  # raises if chain corrupt
    assert prepared == 1, "expected exactly one PREPARED frame, never a double frame"


# --------------------------------------------------------------------------
# Leg C -- unlink-window (PREPARE -> unlink -> COMMIT) kill + recovery
# --------------------------------------------------------------------------

def test_unlink_window_kill_recovery(tmp_path: Path) -> None:
    receipts = tmp_path / "kill-receipts.jsonl"
    parent = tmp_path / "cust_c"
    parent.mkdir()
    for i in range(3):
        m._write_bounded_quarantine_evidence(parent, f"seed{i}", {"seed": i})

    marker = tmp_path / "WINDOW_REACHED.json"
    r_held = tmp_path / "held.json"
    p_held = _spawn_unlink(parent, "held", r_held, "held", hold_s=20)

    mark = _wait_window_marker(marker, timeout=10)
    assert mark is not None, "held worker never reached the unlink window"

    _write_kill_receipt(receipts, p_held.pid, "test_unlink_window_kill_recovery")
    subprocess.run(["taskkill", "/PID", str(p_held.pid), "/F"],
                    capture_output=True, check=False)
    p_held.wait(timeout=10)
    assert p_held.poll() is not None, "held worker still alive after kill"

    pre = _snapshot(parent)
    prepared_orphans = [e["pointer"] for e in pre["events"]
                        if e.get("event") == "PREPARED"
                        and e.get("schema_version") == m._CUSTODY_LEDGER_SCHEMA
                        and not (parent / e["pointer"]).exists()]
    assert prepared_orphans, "expected a torn PREPARED-with-file-gone orphan before recovery"

    # Recovery leg: fresh process resolves the orphaned PREPARED frame.
    r_rec = tmp_path / "rec.json"
    p_rec = _spawn_unlink(parent, "recover", r_rec, "rec")
    p_rec.wait(timeout=20)
    rec = json.loads(r_rec.read_text()) if r_rec.exists() else {"result": "NO_FILE"}
    assert rec["result"] == "OK", f"recovery worker did not converge: {rec}"

    post = _snapshot(parent)
    ptrs = _committed_pointers(post["events"])
    dup = [p for p in set(ptrs) if ptrs.count(p) > 1]
    resurrected = [e["pointer"] for e in post["events"]
                   if e.get("event") == "PREPARED"
                   and e.get("schema_version") == m._CUSTODY_LEDGER_SCHEMA
                   and not any(c.get("pointer") == e["pointer"] and c.get("event") == "COMMITTED"
                               for c in post["events"] if isinstance(c, dict))]

    m._validate_custody_ledger_frame_chain(post["events"])  # raises if corrupt
    assert not dup, f"double-commit detected: {dup}"
    assert not resurrected, f"unresolved PREPARED survived recovery: {resurrected}"

    # Lock is usable after -- one more evidence write must not raise.
    m._write_bounded_quarantine_evidence(parent, "postcheck", {"z": 1})


def test_unlink_window_live_race(tmp_path: Path) -> None:
    receipts = tmp_path / "kill-receipts.jsonl"
    parent = tmp_path / "cust_d"
    parent.mkdir()
    for i in range(3):
        m._write_bounded_quarantine_evidence(parent, f"seed{i}", {"seed": i})

    marker = tmp_path / "WINDOW_REACHED.json"
    r_held = tmp_path / "held.json"
    p_held = _spawn_unlink(parent, "held", r_held, "held", hold_s=20)

    mark = _wait_window_marker(marker, timeout=10)
    assert mark is not None, "held worker never reached the unlink window"

    # Second fresh process races on the SAME custody dir while worker 1 is held.
    r_race = tmp_path / "race.json"
    p_race = _spawn_unlink(parent, "recover", r_race, "race")
    time.sleep(0.4)
    race_alive_during_hold = p_race.poll() is None
    assert race_alive_during_hold, "racing process should still be blocked on the held mutex"

    _write_kill_receipt(receipts, p_held.pid, "test_unlink_window_live_race")
    subprocess.run(["taskkill", "/PID", str(p_held.pid), "/F"],
                    capture_output=True, check=False)
    p_held.wait(timeout=10)
    p_race.wait(timeout=20)

    race_res = json.loads(r_race.read_text()) if r_race.exists() else {"result": "NO_FILE"}
    assert race_res["result"] in ("OK", "RAISED"), f"racing process gave an undefined outcome: {race_res}"

    post = _snapshot(parent)
    ptrs = _committed_pointers(post["events"])
    dup = [p for p in set(ptrs) if ptrs.count(p) > 1]
    resurrected = [e["pointer"] for e in post["events"]
                   if e.get("event") == "PREPARED"
                   and e.get("schema_version") == m._CUSTODY_LEDGER_SCHEMA
                   and not any(c.get("pointer") == e["pointer"] and c.get("event") == "COMMITTED"
                               for c in post["events"] if isinstance(c, dict))]

    m._validate_custody_ledger_frame_chain(post["events"])  # raises if corrupt
    assert not dup, f"double-commit detected under live race: {dup}"
    assert not resurrected, f"unresolved PREPARED survived the live race: {resurrected}"
