#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""run_ledger.py -- C8 pre-launch obligation O5 (issue #582; spec: the F1-F4 fill
amendment on issue #123, comment 4928342201, section 1 "Anti-abort-button clause"
and section 9 item 5). Hardening pass: issue #630 (independent-audit disposition,
accepted; cure adopted per #123's disposition). CPU-only, stdlib only.

Appender helper for the public governed-run ledger: state/c8-run-ledger.jsonl.
Append-only, never mutated in place -- every state change (launch, later an
exclusion finding) is its OWN appended row, keyed by run_id. This mirrors the
repo's other ledgers (e.g. ledger_dedup.py's sidecar views): the file is a log,
not a table you edit. Landed rows are never edited retroactively; hardening in
this file changes the WRITING path (validation, timezone handling, locking,
counting) and future rows only.

Two row shapes, distinguished by the "event" field. Only "launch" is required
by O5's AC; "exclusion" is the extension that satisfies the amendment's
"exclusion validity + repeat-inadmissible disclosure" clause (section 1):

  event = "launch"   (the O5 AC schema, verbatim, plus "event"):
    {
      "event": "launch",
      "run_id": <str>,                  # unique identifier for this governed run
      "arm": <str>,                     # one of ARMS below
      "launch_ts": <str ISO8601, timezone-aware>,  # when the run launched
      "config_sha": <str, 64-char lowercase hex sha256>,
      "admissibility_commit_sha": <str, 64-char lowercase hex sha256>
                                         # sha256 of the admissibility-receipt
                                         # bundle, hash-committed BEFORE the
                                         # terminal eval is scored/unblinded
                                         # (the "anti-abort-button" invariant)
    }
    One row appended AT LAUNCH, per governed run. run_id must be unique across
    every "launch" row ever appended (append_launch_row refuses a duplicate).
    launch_ts must be a timezone-aware ISO8601 timestamp; config_sha and
    admissibility_commit_sha must each be a 64-char lowercase hex sha256
    digest -- all three are validated (issue #630: previously a bare string
    was accepted, including 'not-a-timestamp' / 'not-a-sha').

  event = "exclusion" (amendment section 1: "exclusion is valid only for a
    precondition failure receipted before the run's first post-launch eval"):
    {
      "event": "exclusion",
      "run_id": <str>,                  # must reference an existing launch row
      "arm": <str>,
      "precondition": <str>,            # which admissibility precondition failed
                                         # (A1, A3, Q6, F4-per-event, F3-instrument, ...)
      "exclusion_reason": <str>,
      "receipted_ts": <str ISO8601, timezone-aware>,  # when the exclusion was receipted
      "first_post_launch_eval_ts": <str ISO8601, timezone-aware | null>,
      "valid": <bool | null>            # True iff receipted_ts instant < first_post_launch_eval_ts
                                         # instant, comparing timezone-NORMALIZED instants
                                         # (issue #630: a raw string compare puts a
                                         # +05:00-offset receipt that is actually EARLIER
                                         # than a UTC eval on the wrong side); null if
                                         # first_post_launch_eval_ts is not yet known (the
                                         # run has had no post-launch eval yet, which is the
                                         # common/expected case for a timely exclusion)
    }
    At most ONE exclusion row per run_id is accepted (issue #630: "reject/dedupe
    duplicate exclusion rows per run") -- append_exclusion_row refuses a second
    exclusion row for a run_id that already has one, mirroring the existing
    duplicate-launch-row refusal below.

Two-or-more INADMISSIBLE (excluded) governed runs of the SAME arm trigger the
amendment's "mandatory disclosure in the terminal receipt" clause --
count_inadmissible_for_arm() computes that count + the disclosure flag from
the ledger itself, so a caller never has to hand-count JSONL rows. Per issue
#630's frozen cure, this counts unique run_ids with valid == True ONLY
(explicit resolution for unknown validity: a run_id whose only exclusion row
has valid=False or valid=None is NOT counted as inadmissible -- an untimely
or unresolved exclusion claim does not excuse a run under the anti-abort-
button clause) -- never a raw row count (a duplicate/legacy pair of rows for
one run_id must not double-count that run).

Rows are appended one JSON object per line, UTF-8, LF-only (newline="\\n",
matching the repo's byte-stability convention -- sha_convention: "bytes on
disk as-is, no line-ending normalization").

Append is lock-guarded (issue #630: "atomic/locked append") -- the entire
check-then-append critical section (read existing rows, validate, decide,
write) runs under an exclusive advisory lock scoped to a `<ledger_path>.lock`
sidecar file, never the ledger's own bytes, closing the TOCTOU race a bare
read-then-append leaves open under concurrent launchers (two callers racing
append_launch_row for the same run_id, or two exclusion filings racing the
same run_id).

Launcher binding (issue #630: "integrate into the actual launcher BEFORE
first training/eval with append failure blocking launch"):
governed_run_launcher.py is the canonical C8 command launcher. It reads and
hashes exact repository-confined config/admissibility bytes, calls
assert_launch_recorded BEFORE process creation, and passes private snapshots
of those same bytes to the child. A failed append (bad hash, bad timestamp,
unknown arm, duplicate run_id, lock timeout, disk I/O failure) raises
SystemExit -- the launch is REFUSED, never best-effort logged-and-continued.

USAGE (as a library -- this ledger has no interesting CLI beyond --selftest;
callers import append_launch_row / append_exclusion_row / count_inadmissible_for_arm
/ assert_launch_recorded directly from the governed-run tooling that knows a
launch/exclusion happened):

    python run_ledger.py --selftest
"""
import contextlib
import json
import os
import re
import sys
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path

try:
    import msvcrt  # Windows advisory record locking
    _HAS_MSVCRT = True
except ImportError:  # pragma: no cover - platform-specific
    _HAS_MSVCRT = False

try:
    import fcntl  # POSIX advisory locking
    _HAS_FCNTL = True
except ImportError:  # pragma: no cover - platform-specific
    _HAS_FCNTL = False

ARMS = frozenset({"gated-grown", "A-scratch", "A-schedule"})

_LAUNCH_FIELDS = ("event", "run_id", "arm", "launch_ts", "config_sha", "admissibility_commit_sha")
_EXCLUSION_FIELDS = ("event", "run_id", "arm", "precondition", "exclusion_reason",
                     "receipted_ts", "first_post_launch_eval_ts", "valid")

_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")


# ---------------------------------------------------------------------------
# Strict validation (issue #630 C1: fake hashes / non-timestamps were accepted)
# ---------------------------------------------------------------------------

def _validate_sha256(value, field_name: str) -> str:
    """Strict 64-char lowercase hex sha256 digest validation. Raises ValueError
    on anything else (wrong length, uppercase, non-hex, non-string) -- fail
    closed, never a best-effort accept of a malformed hash."""
    if not isinstance(value, str) or not _SHA256_HEX_RE.match(value):
        raise ValueError(
            f"{field_name} must be a 64-character lowercase hex sha256 digest, "
            f"got {value!r}")
    return value


def _parse_iso8601_aware(value, field_name: str) -> datetime:
    """Timezone-aware ISO8601 parse (issue #630 C2: a raw string compare of
    ISO timestamps with different UTC offsets does not track real time
    order). Accepts a trailing 'Z' (normalized to '+00:00' for
    datetime.fromisoformat, which does not accept 'Z' on this interpreter).
    Raises ValueError on anything unparseable OR on a naive timestamp (no
    offset) -- a naive instant cannot be safely normalized/compared, so it is
    rejected rather than silently assumed to be UTC."""
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be an ISO8601 string, got {value!r}")
    s = value.strip()
    normalized = s[:-1] + "+00:00" if s.endswith("Z") else s
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError as e:
        raise ValueError(f"{field_name} is not a valid ISO8601 timestamp: {value!r} ({e})") from e
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        raise ValueError(
            f"{field_name} must be timezone-aware (explicit UTC offset or 'Z' "
            f"suffix required for instant comparison), got {value!r}")
    return dt


# ---------------------------------------------------------------------------
# Locked, atomic append (issue #630: "atomic/locked append")
# ---------------------------------------------------------------------------

@contextlib.contextmanager
def _ledger_lock(ledger_path: str, timeout_s: float = 30.0):
    """Cross-platform advisory exclusive lock scoped to one ledger file, held
    across the ENTIRE check-then-append critical section (read existing rows,
    validate, decide, write) -- closes the TOCTOU race a bare
    read-then-append leaves open under concurrent callers (two launches
    racing the same run_id, or two exclusion filings racing the same
    run_id). Uses a dedicated `<ledger_path>.lock` sidecar file, never the
    ledger's own bytes, so lock acquisition/release never touches append-only
    ledger content. Falls back to unlocked (disclosed via no-op, not a false
    atomicity claim) only if neither msvcrt nor fcntl is importable."""
    d = os.path.dirname(ledger_path)
    if d:
        os.makedirs(d, exist_ok=True)
    lock_path = ledger_path + ".lock"
    lock_file = open(lock_path, "a+b")
    locked = False
    try:
        deadline = time.monotonic() + timeout_s
        while True:
            try:
                if _HAS_MSVCRT:
                    lock_file.seek(0)
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                    locked = True
                elif _HAS_FCNTL:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    locked = True
                else:  # pragma: no cover - no OS lock primitive on this platform
                    locked = False
                break
            except OSError:
                if time.monotonic() > deadline:
                    raise TimeoutError(
                        f"_ledger_lock: could not acquire exclusive lock on "
                        f"{lock_path!r} within {timeout_s}s")
                time.sleep(0.05)
        yield
    finally:
        if locked:
            try:
                if _HAS_MSVCRT:
                    lock_file.seek(0)
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
                elif _HAS_FCNTL:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            except OSError:  # pragma: no cover - best-effort unlock only
                pass
        lock_file.close()


def _load_rows(ledger_path: str) -> list:
    if not os.path.exists(ledger_path):
        return []
    rows = []
    with open(ledger_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _append_row(ledger_path: str, row: dict) -> None:
    d = os.path.dirname(ledger_path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(ledger_path, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(row) + "\n")


def append_launch_row(ledger_path: str, run_id: str, arm: str, launch_ts: str,
                       config_sha: str, admissibility_commit_sha: str) -> dict:
    """Append the O5 AC launch row. Refuses (ValueError, fail-closed, no row
    written) on: an unknown arm; a launch_ts that is not a timezone-aware
    ISO8601 timestamp; a config_sha or admissibility_commit_sha that is not a
    64-char lowercase hex sha256 digest; or a duplicate run_id (a
    double-launch entry for the same run_id would corrupt the ledger's
    one-row-per-governed-run invariant). The check-then-append sequence runs
    under _ledger_lock so a concurrent duplicate-run_id race cannot slip two
    launch rows past the check."""
    if arm not in ARMS:
        raise ValueError(f"append_launch_row: unknown arm {arm!r}, must be one of {sorted(ARMS)}")
    _parse_iso8601_aware(launch_ts, "launch_ts")
    _validate_sha256(config_sha, "config_sha")
    _validate_sha256(admissibility_commit_sha, "admissibility_commit_sha")

    with _ledger_lock(ledger_path):
        existing = _load_rows(ledger_path)
        for r in existing:
            if r.get("event") == "launch" and r.get("run_id") == run_id:
                raise ValueError(f"append_launch_row: run_id {run_id!r} already has a launch row -- refusing duplicate")

        row = {
            "event": "launch",
            "run_id": run_id,
            "arm": arm,
            "launch_ts": launch_ts,
            "config_sha": config_sha,
            "admissibility_commit_sha": admissibility_commit_sha,
        }
        _append_row(ledger_path, row)
    return row


def append_exclusion_row(ledger_path: str, run_id: str, precondition: str,
                          exclusion_reason: str, receipted_ts: str,
                          first_post_launch_eval_ts=None) -> dict:
    """Append an exclusion row for an already-launched run_id.

    valid = receipted instant < first_post_launch_eval instant, if the latter
    is known -- both parsed as timezone-aware datetimes and compared as
    instants (never a raw string compare, which mis-orders timestamps that
    use different UTC offsets); otherwise valid = None (undetermined -- there
    is no post-launch eval yet for the ordering to violate, which is the
    common/expected case for a timely exclusion filed right after the
    precondition failure is found).

    Refuses (ValueError, no row written) on: an orphan run_id (no launch
    row); a receipted_ts or first_post_launch_eval_ts that is not a
    timezone-aware ISO8601 timestamp; or a SECOND exclusion row for a run_id
    that already has one (issue #630: "reject/dedupe duplicate exclusion
    rows per run" -- at most one exclusion row per run_id is admitted, so
    count_inadmissible_for_arm's per-run_id counting can never be
    ambiguous). The check-then-append sequence runs under _ledger_lock.
    """
    _parse_iso8601_aware(receipted_ts, "receipted_ts")
    if first_post_launch_eval_ts is not None:
        _parse_iso8601_aware(first_post_launch_eval_ts, "first_post_launch_eval_ts")

    with _ledger_lock(ledger_path):
        existing = _load_rows(ledger_path)
        launch_rows = {r["run_id"] for r in existing if r.get("event") == "launch"}
        if run_id not in launch_rows:
            raise ValueError(f"append_exclusion_row: run_id {run_id!r} has no launch row -- refusing orphan exclusion")

        if any(r.get("event") == "exclusion" and r.get("run_id") == run_id for r in existing):
            raise ValueError(
                f"append_exclusion_row: run_id {run_id!r} already has an exclusion row -- "
                f"refusing duplicate (issue #630: at most one exclusion row per run)")

        arm = next(r["arm"] for r in existing if r.get("event") == "launch" and r["run_id"] == run_id)

        if first_post_launch_eval_ts is not None:
            receipted_dt = _parse_iso8601_aware(receipted_ts, "receipted_ts")
            eval_dt = _parse_iso8601_aware(first_post_launch_eval_ts, "first_post_launch_eval_ts")
            valid = receipted_dt < eval_dt
        else:
            valid = None

        row = {
            "event": "exclusion",
            "run_id": run_id,
            "arm": arm,
            "precondition": precondition,
            "exclusion_reason": exclusion_reason,
            "receipted_ts": receipted_ts,
            "first_post_launch_eval_ts": first_post_launch_eval_ts,
            "valid": valid,
        }
        _append_row(ledger_path, row)
    return row


def count_inadmissible_for_arm(ledger_path: str, arm: str) -> dict:
    """Count INADMISSIBLE governed RUNS (unique run_ids), not exclusion rows,
    for a given arm. Returns {"count": int, "mandatory_disclosure": bool} --
    mandatory_disclosure is True iff count >= 2, per the amendment's "two or
    more INADMISSIBLE governed runs of the same arm => mandatory disclosure
    in the terminal receipt" clause.

    Issue #630 hardening: a run_id counts toward inadmissibility iff it has
    at least one exclusion row for this arm with valid == True (explicit
    resolution for unknown validity -- a run_id whose only exclusion rows
    have valid=False or valid=None is NOT counted: an untimely exclusion
    claim, or one whose timing is still unresolved, does not excuse a run
    under the anti-abort-button clause). Deduplicated by run_id, so a
    duplicate/legacy pair of exclusion rows for one run_id counts that run
    exactly once -- append_exclusion_row already refuses a second exclusion
    row per run_id going forward, but this counting is defense-in-depth
    against any rows already on disk."""
    rows = _load_rows(ledger_path)
    inadmissible_run_ids = {
        r["run_id"] for r in rows
        if r.get("event") == "exclusion" and r.get("arm") == arm and r.get("valid") is True
    }
    count = len(inadmissible_run_ids)
    return {"count": count, "mandatory_disclosure": count >= 2}


# ---------------------------------------------------------------------------
# Launcher binding (issue #630 C4: "no caller exists ... nothing enforces
# append-at-launch or fail-closed launch on append failure")
# ---------------------------------------------------------------------------

def assert_launch_recorded(*, ledger_path: str, run_id: str, arm: str, launch_ts: str,
                            config_sha: str, admissibility_commit_sha: str) -> dict:
    """Fail-closed pre-launch hook. Call this BEFORE building/launching any
    governed-run arm (before first training/eval) -- it is the launcher-
    binding artifact issue #630 requires. Appends the O5 launch row; if the
    append fails for ANY reason (unknown arm, malformed sha/timestamp,
    duplicate run_id, lock timeout, disk I/O failure), this raises
    SystemExit and the caller MUST NOT proceed to launch -- never a
    best-effort log-and-continue.

    src/ember/governance/scripts/c8_prelaunch/governed_run_launcher.py calls this hook before
    creating the child process. Other callers must preserve that ordering.
    """
    try:
        return append_launch_row(ledger_path, run_id, arm, launch_ts,
                                  config_sha, admissibility_commit_sha)
    except (ValueError, OSError, TimeoutError) as e:
        raise SystemExit(
            f"O5_RUN_LEDGER_LAUNCH_REFUSED: {type(e).__name__}: {e} -- "
            f"launch BLOCKED, run_id={run_id!r} arm={arm!r} NOT recorded"
        ) from e


# ---------------------------------------------------------------------------
# Selftest
# ---------------------------------------------------------------------------

def _selftest() -> int:
    failures = []

    # --- RED 1: unknown arm rejected, no row written ---
    with tempfile.TemporaryDirectory() as td:
        ledger = os.path.join(td, "ledger.jsonl")
        try:
            append_launch_row(ledger, "run-1", "not-a-real-arm", "2026-07-09T00:00:00+00:00", "a" * 64, "b" * 64)
            failures.append("RED1 FAIL: unknown arm should raise ValueError")
        except ValueError:
            pass
        if os.path.exists(ledger):
            failures.append("RED1 FAIL: no ledger file should be created on a rejected append")

    # --- RED 2: duplicate run_id launch row rejected ---
    with tempfile.TemporaryDirectory() as td:
        ledger = os.path.join(td, "ledger.jsonl")
        append_launch_row(ledger, "run-2", "A-scratch", "2026-07-09T00:00:00+00:00", "a" * 64, "b" * 64)
        try:
            append_launch_row(ledger, "run-2", "A-scratch", "2026-07-09T01:00:00+00:00", "c" * 64, "d" * 64)
            failures.append("RED2 FAIL: duplicate run_id launch row should raise ValueError")
        except ValueError:
            pass
        rows = _load_rows(ledger)
        if len(rows) != 1:
            failures.append(f"RED2 FAIL: exactly 1 row expected after rejected duplicate, got {len(rows)}")

    # --- RED 3: exclusion row for a run_id with no launch row is refused ---
    with tempfile.TemporaryDirectory() as td:
        ledger = os.path.join(td, "ledger.jsonl")
        try:
            append_exclusion_row(ledger, "ghost-run", "A1", "no freeze hash", "2026-07-09T00:00:00+00:00")
            failures.append("RED3 FAIL: orphan exclusion row should raise ValueError")
        except ValueError:
            pass

    # --- GREEN 1: launch row read-back matches exactly, LF-only bytes ---
    with tempfile.TemporaryDirectory() as td:
        ledger = os.path.join(td, "ledger.jsonl")
        row = append_launch_row(ledger, "run-3", "gated-grown", "2026-07-09T02:00:00+00:00", "c" * 64, "a" * 64)
        rows = _load_rows(ledger)
        if rows != [row]:
            failures.append(f"GREEN1 FAIL: read-back row mismatch: {rows} != [{row}]")
        with open(ledger, "rb") as f:
            raw = f.read()
        if b"\r\n" in raw:
            failures.append("GREEN1 FAIL: ledger contains CRLF, expected LF-only")
        if not raw.endswith(b"\n"):
            failures.append("GREEN1 FAIL: ledger row should end with a newline")

    # --- GREEN 2: exclusion validity -- before eval => valid True, after => valid False ---
    with tempfile.TemporaryDirectory() as td:
        ledger = os.path.join(td, "ledger.jsonl")
        append_launch_row(ledger, "run-4", "A-schedule", "2026-07-09T00:00:00+00:00", "c" * 64, "a" * 64)
        append_launch_row(ledger, "run-5", "A-schedule", "2026-07-09T00:00:00+00:00", "e" * 64, "f" * 64)

        valid_row = append_exclusion_row(
            ledger, "run-4", "Q6", "contamination_recheck != 0",
            receipted_ts="2026-07-09T01:00:00+00:00",
            first_post_launch_eval_ts="2026-07-09T02:00:00+00:00",
        )
        if valid_row["valid"] is not True:
            failures.append(f"GREEN2 FAIL: exclusion receipted before eval should be valid=True, got {valid_row['valid']}")

        invalid_row = append_exclusion_row(
            ledger, "run-5", "A3", "tuning receipts asymmetric",
            receipted_ts="2026-07-09T03:00:00+00:00",
            first_post_launch_eval_ts="2026-07-09T02:00:00+00:00",
        )
        if invalid_row["valid"] is not False:
            failures.append(f"GREEN2 FAIL: exclusion receipted after eval should be valid=False, got {invalid_row['valid']}")

        # --- GREEN 3 (issue #630 semantics): only valid=True exclusions
        # count toward inadmissibility. run-4 is valid=True (1 so far);
        # run-5 is valid=False (untimely -- does NOT count). So after just
        # these two, count=1, mandatory_disclosure=False.
        disclosure = count_inadmissible_for_arm(ledger, "A-schedule")
        if disclosure != {"count": 1, "mandatory_disclosure": False}:
            failures.append(
                f"GREEN3 FAIL: expected count=1/mandatory_disclosure=False (only run-4's "
                f"valid=True exclusion counts; run-5's valid=False does not), got {disclosure}")

        # A different arm with zero exclusions must not trigger disclosure
        no_disclosure = count_inadmissible_for_arm(ledger, "A-scratch")
        if no_disclosure != {"count": 0, "mandatory_disclosure": False}:
            failures.append(f"GREEN3b FAIL: expected count=0/mandatory_disclosure=False, got {no_disclosure}")

        # --- GREEN 3c: a SECOND distinct run_id on A-schedule, also
        # valid=True, tips count to 2 => mandatory_disclosure flips True
        # (the genuine "two-or-more INADMISSIBLE governed runs of the same
        # arm" positive case, with distinct run_ids so it cannot be confused
        # with the row-vs-run dedup bug covered separately below).
        append_launch_row(ledger, "run-4c", "A-schedule", "2026-07-09T00:00:00+00:00", "1" * 64, "2" * 64)
        append_exclusion_row(ledger, "run-4c", "Q6", "contamination_recheck != 0",
                              receipted_ts="2026-07-09T01:00:00+00:00",
                              first_post_launch_eval_ts="2026-07-09T02:00:00+00:00")
        disclosure2 = count_inadmissible_for_arm(ledger, "A-schedule")
        if disclosure2 != {"count": 2, "mandatory_disclosure": True}:
            failures.append(
                f"GREEN3c FAIL: expected count=2/mandatory_disclosure=True after a second "
                f"distinct valid=True exclusion on the same arm, got {disclosure2}")

    # --- GREEN 4: exclusion with unknown post-launch-eval ordering => valid=None ---
    with tempfile.TemporaryDirectory() as td:
        ledger = os.path.join(td, "ledger.jsonl")
        append_launch_row(ledger, "run-6", "gated-grown", "2026-07-09T00:00:00+00:00", "c" * 64, "a" * 64)
        row = append_exclusion_row(ledger, "run-6", "F4-per-event", "R_c below floor",
                                    receipted_ts="2026-07-09T01:00:00+00:00")
        if row["valid"] is not None:
            failures.append(f"GREEN4 FAIL: expected valid=None with no eval ts, got {row['valid']}")

    # =========================================================================
    # Issue #630 hardening: the four named counterexamples, RED-then-GREEN.
    # =========================================================================

    # --- RED 4 / C1: fake hash + non-timestamp launch fields rejected ---
    with tempfile.TemporaryDirectory() as td:
        ledger = os.path.join(td, "ledger.jsonl")
        for bad_kwargs, label in [
            (dict(launch_ts="not-a-timestamp", config_sha="a" * 64, admissibility_commit_sha="b" * 64), "bad launch_ts"),
            (dict(launch_ts="2026-07-09T00:00:00+00:00", config_sha="not-a-sha", admissibility_commit_sha="b" * 64), "bad config_sha"),
            (dict(launch_ts="2026-07-09T00:00:00+00:00", config_sha="a" * 64, admissibility_commit_sha="not-a-sha"), "bad admissibility_commit_sha"),
            (dict(launch_ts="2026-07-09T00:00:00+00:00", config_sha="A" * 64, admissibility_commit_sha="b" * 64), "uppercase-hex config_sha"),
            (dict(launch_ts="2026-07-09T00:00:00", config_sha="a" * 64, admissibility_commit_sha="b" * 64), "tz-naive launch_ts"),
        ]:
            try:
                append_launch_row(ledger, f"run-c1-{label}", "A-scratch", **bad_kwargs)
                failures.append(f"RED4(#630 C1) FAIL: {label!r} should raise ValueError but was accepted")
            except ValueError:
                pass
        if os.path.exists(ledger) and _load_rows(ledger):
            failures.append("RED4(#630 C1) FAIL: no row should have been written for any rejected launch")

    # --- GREEN 5 / C1: well-formed sha256 + tz-aware timestamp accepted ---
    with tempfile.TemporaryDirectory() as td:
        ledger = os.path.join(td, "ledger.jsonl")
        row = append_launch_row(ledger, "run-c1-ok", "A-scratch",
                                 "2026-07-09T00:00:00Z", "a" * 64, "b" * 64)
        if row["config_sha"] != "a" * 64:
            failures.append("GREEN5(#630 C1) FAIL: valid config_sha round-trip mismatch")

    # --- RED 5 / C2: tz-offset instant compare (the exact issue example) ---
    with tempfile.TemporaryDirectory() as td:
        ledger = os.path.join(td, "ledger.jsonl")
        append_launch_row(ledger, "run-c2", "A-scratch", "2026-07-09T00:00:00+00:00", "a" * 64, "b" * 64)
        # receipted_ts real instant = 2026-07-09T00:00:00Z; eval real instant
        # = 2026-07-09T02:00:00Z. receipted is strictly BEFORE eval, but the
        # receipted string sorts LEXICALLY AFTER the eval string ("05" > "02")
        # -- exactly the issue's counterexample shape.
        row = append_exclusion_row(
            ledger, "run-c2", "A1", "tz-offset ordering probe",
            receipted_ts="2026-07-09T05:00:00+05:00",
            first_post_launch_eval_ts="2026-07-09T02:00:00+00:00",
        )
        if row["valid"] is not True:
            failures.append(
                f"RED5(#630 C2) FAIL: +05:00-offset receipt chronologically BEFORE "
                f"the eval compared as valid={row['valid']!r}, expected True "
                f"(tz-naive raw-string compare bug reproduced)")

    # --- RED 6 / C3: row-vs-run counting on a ledger with a duplicate-row
    # shape (constructed via raw JSONL to isolate the COUNTING function from
    # append_exclusion_row's own now-enforced one-exclusion-per-run refusal;
    # defense-in-depth against any pre-existing ledger with such rows) ---
    with tempfile.TemporaryDirectory() as td:
        ledger = os.path.join(td, "ledger.jsonl")
        append_launch_row(ledger, "run-c3", "A-schedule", "2026-07-09T00:00:00+00:00", "a" * 64, "b" * 64)
        with open(ledger, "a", encoding="utf-8", newline="\n") as f:
            for i in range(2):
                f.write(json.dumps({
                    "event": "exclusion", "run_id": "run-c3", "arm": "A-schedule",
                    "precondition": "A1", "exclusion_reason": f"dup filing {i}",
                    "receipted_ts": "2026-07-09T01:00:00+00:00",
                    "first_post_launch_eval_ts": None, "valid": True,
                }) + "\n")
        disclosure = count_inadmissible_for_arm(ledger, "A-schedule")
        if disclosure != {"count": 1, "mandatory_disclosure": False}:
            failures.append(
                f"RED6(#630 C3) FAIL: two exclusion ROWS for ONE run_id produced "
                f"{disclosure}, expected count=1/mandatory_disclosure=False "
                f"(must count unique inadmissible RUNS, not rows)")

    # --- GREEN 6 / C3: valid=False / valid=None exclusions do not count ---
    with tempfile.TemporaryDirectory() as td:
        ledger = os.path.join(td, "ledger.jsonl")
        append_launch_row(ledger, "run-c3b-unresolved", "A-schedule", "2026-07-09T00:00:00+00:00", "a" * 64, "b" * 64)
        append_launch_row(ledger, "run-c3b-untimely", "A-schedule", "2026-07-09T00:00:00+00:00", "c" * 64, "d" * 64)
        append_exclusion_row(ledger, "run-c3b-unresolved", "A1", "not yet resolved",
                              receipted_ts="2026-07-09T01:00:00+00:00")  # valid=None
        append_exclusion_row(ledger, "run-c3b-untimely", "A1", "receipted after eval",
                              receipted_ts="2026-07-09T03:00:00+00:00",
                              first_post_launch_eval_ts="2026-07-09T02:00:00+00:00")  # valid=False
        disclosure = count_inadmissible_for_arm(ledger, "A-schedule")
        if disclosure != {"count": 0, "mandatory_disclosure": False}:
            failures.append(
                f"GREEN6(#630 C3) FAIL: valid=None and valid=False exclusions should "
                f"not count toward mandatory_disclosure, got {disclosure}")

    # --- RED 7 / C3(append-guard): duplicate exclusion row per run refused ---
    with tempfile.TemporaryDirectory() as td:
        ledger = os.path.join(td, "ledger.jsonl")
        append_launch_row(ledger, "run-c3c", "A-scratch", "2026-07-09T00:00:00+00:00", "a" * 64, "b" * 64)
        append_exclusion_row(ledger, "run-c3c", "A1", "first filing",
                              receipted_ts="2026-07-09T01:00:00+00:00")
        try:
            append_exclusion_row(ledger, "run-c3c", "A1", "second filing (amendment attempt)",
                                  receipted_ts="2026-07-09T01:30:00+00:00")
            failures.append("RED7(#630 C3-append-guard) FAIL: second exclusion row for the "
                             "same run_id should raise ValueError")
        except ValueError:
            pass
        exclusion_rows = [r for r in _load_rows(ledger) if r.get("event") == "exclusion"]
        if len(exclusion_rows) != 1:
            failures.append(f"RED7(#630 C3-append-guard) FAIL: expected exactly 1 exclusion "
                             f"row after the rejected duplicate, got {len(exclusion_rows)}")

    # --- RED 8 / C4: launcher-binding hook exists and is fail-closed ---
    if not hasattr(sys.modules[__name__], "assert_launch_recorded"):
        failures.append("RED8(#630 C4) FAIL: assert_launch_recorded launcher-binding hook is missing")
    else:
        with tempfile.TemporaryDirectory() as td:
            ledger = os.path.join(td, "ledger.jsonl")
            try:
                assert_launch_recorded(ledger_path=ledger, run_id="run-c4-bad", arm="not-a-real-arm",
                                        launch_ts="2026-07-09T00:00:00+00:00",
                                        config_sha="a" * 64, admissibility_commit_sha="b" * 64)
                failures.append("RED8(#630 C4) FAIL: assert_launch_recorded should refuse an invalid-arm launch")
            except SystemExit:
                pass
            if os.path.exists(ledger) and _load_rows(ledger):
                failures.append("RED8(#630 C4) FAIL: a refused launch must not leave any row in the ledger")

    # --- GREEN 7 / C4: launcher-binding hook records a valid launch exactly once ---
    with tempfile.TemporaryDirectory() as td:
        ledger = os.path.join(td, "ledger.jsonl")
        row = assert_launch_recorded(ledger_path=ledger, run_id="run-c4-ok", arm="gated-grown",
                                      launch_ts="2026-07-09T00:00:00Z",
                                      config_sha="a" * 64, admissibility_commit_sha="b" * 64)
        rows = _load_rows(ledger)
        if rows != [row] or row["event"] != "launch" or row["run_id"] != "run-c4-ok":
            failures.append(f"GREEN7(#630 C4) FAIL: expected exactly one recorded launch row, got {rows}")

    # --- GREEN 8 / atomic-locked-append: N threads race append_launch_row
    # for the SAME run_id; _ledger_lock must serialize the check-then-write
    # critical section so exactly one wins and every other thread observes
    # the duplicate-run_id refusal -- never two launch rows for one run_id.
    # (Receipted defense-in-depth: the SAME probe against the pre-hardening
    # module reproducibly wrote 5-10 duplicate rows out of 24 racing
    # threads; see PR body.)
    with tempfile.TemporaryDirectory() as td:
        ledger = os.path.join(td, "ledger.jsonl")
        n_threads = 24
        outcomes = []
        outcomes_lock = threading.Lock()

        def _racer():
            try:
                append_launch_row(ledger, "race-run", "A-scratch",
                                   "2026-07-09T00:00:00+00:00", "a" * 64, "b" * 64)
                outcome = "WON"
            except ValueError:
                outcome = "REFUSED_DUPLICATE"
            except Exception as e:  # pragma: no cover
                outcome = f"UNEXPECTED_{type(e).__name__}"
            with outcomes_lock:
                outcomes.append(outcome)

        threads = [threading.Thread(target=_racer) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        launch_rows = [r for r in _load_rows(ledger)
                       if r.get("event") == "launch" and r.get("run_id") == "race-run"]
        n_won = outcomes.count("WON")
        n_refused = outcomes.count("REFUSED_DUPLICATE")
        if not (n_won == 1 and n_refused == n_threads - 1 and len(launch_rows) == 1):
            failures.append(
                f"GREEN8(#630 atomic-locked-append) FAIL: {n_threads} threads racing "
                f"append_launch_row for one run_id produced won={n_won} "
                f"refused={n_refused} launch_rows_on_disk={len(launch_rows)}, expected "
                f"won=1 refused={n_threads - 1} launch_rows_on_disk=1")

    if failures:
        for f in failures:
            print(f"SELFTEST: {f}")
        return 1

    print("RUN_LEDGER_SELFTEST_PASS")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    print(__doc__)
