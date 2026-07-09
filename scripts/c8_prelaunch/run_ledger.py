#!/usr/bin/env python3
"""run_ledger.py -- C8 pre-launch obligation O5 (issue #582; spec: the F1-F4 fill
amendment on issue #123, comment 4928342201, section 1 "Anti-abort-button clause"
and section 9 item 5). CPU-only, stdlib only.

Appender helper for the public governed-run ledger: state/c8-run-ledger.jsonl.
Append-only, never mutated in place -- every state change (launch, later an
exclusion finding) is its OWN appended row, keyed by run_id. This mirrors the
repo's other ledgers (e.g. ledger_dedup.py's sidecar views): the file is a log,
not a table you edit.

Two row shapes, distinguished by the "event" field. Only "launch" is required
by O5's AC; "exclusion" is the extension that satisfies the amendment's
"exclusion validity + repeat-inadmissible disclosure" clause (section 1):

  event = "launch"   (the O5 AC schema, verbatim, plus "event"):
    {
      "event": "launch",
      "run_id": <str>,                  # unique identifier for this governed run
      "arm": <str>,                     # one of ARMS below
      "launch_ts": <str ISO8601>,       # when the run launched
      "config_sha": <str>,              # sha256 of the run's config at launch
      "admissibility_commit_sha": <str> # sha256 of the admissibility-receipt
                                         # bundle, hash-committed BEFORE the
                                         # terminal eval is scored/unblinded
                                         # (the "anti-abort-button" invariant)
    }
    One row appended AT LAUNCH, per governed run. run_id must be unique across
    every "launch" row ever appended (append_launch_row refuses a duplicate).

  event = "exclusion" (amendment section 1: "exclusion is valid only for a
    precondition failure receipted before the run's first post-launch eval"):
    {
      "event": "exclusion",
      "run_id": <str>,                  # must reference an existing launch row
      "arm": <str>,
      "precondition": <str>,            # which admissibility precondition failed
                                         # (A1, A3, Q6, F4-per-event, F3-instrument, ...)
      "exclusion_reason": <str>,
      "receipted_ts": <str ISO8601>,    # when the exclusion was receipted
      "first_post_launch_eval_ts": <str ISO8601 | null>,
      "valid": <bool | null>            # True iff receipted_ts < first_post_launch_eval_ts;
                                         # null if first_post_launch_eval_ts is not yet known
                                         # (the run has had no post-launch eval yet, which is
                                         # the common/expected case for a timely exclusion)
    }

Two-or-more INADMISSIBLE (excluded) governed runs of the SAME arm trigger the
amendment's "mandatory disclosure in the terminal receipt" clause --
count_inadmissible_for_arm() computes that count + the disclosure flag from
the ledger itself, so a caller never has to hand-count JSONL rows.

Rows are appended one JSON object per line, UTF-8, LF-only (newline="\\n",
matching the repo's byte-stability convention -- sha_convention: "bytes on
disk as-is, no line-ending normalization").

USAGE (as a library -- this ledger has no interesting CLI beyond --selftest;
callers import append_launch_row / append_exclusion_row / count_inadmissible_for_arm
directly from the governed-run tooling that knows a launch/exclusion happened):

    python run_ledger.py --selftest
"""
import json
import os
import sys
import tempfile
from pathlib import Path

ARMS = frozenset({"gated-grown", "A-scratch", "A-schedule"})

_LAUNCH_FIELDS = ("event", "run_id", "arm", "launch_ts", "config_sha", "admissibility_commit_sha")
_EXCLUSION_FIELDS = ("event", "run_id", "arm", "precondition", "exclusion_reason",
                     "receipted_ts", "first_post_launch_eval_ts", "valid")


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
    """Append the O5 AC launch row. Refuses an unknown arm or a duplicate run_id
    (fail-closed -- a double-launch entry for the same run_id would corrupt the
    ledger's one-row-per-governed-run invariant)."""
    if arm not in ARMS:
        raise ValueError(f"append_launch_row: unknown arm {arm!r}, must be one of {sorted(ARMS)}")

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

    valid = receipted_ts < first_post_launch_eval_ts, if the latter is known;
    otherwise valid = None (undetermined -- there is no post-launch eval yet
    for the ordering to violate, which is the common/expected case for a
    timely exclusion filed right after the precondition failure is found).
    """
    existing = _load_rows(ledger_path)
    launch_rows = {r["run_id"] for r in existing if r.get("event") == "launch"}
    if run_id not in launch_rows:
        raise ValueError(f"append_exclusion_row: run_id {run_id!r} has no launch row -- refusing orphan exclusion")

    arm = next(r["arm"] for r in existing if r.get("event") == "launch" and r["run_id"] == run_id)

    if first_post_launch_eval_ts is not None:
        valid = receipted_ts < first_post_launch_eval_ts
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
    """Count exclusion rows for a given arm. Returns
    {"count": int, "mandatory_disclosure": bool} -- mandatory_disclosure is
    True iff count >= 2, per the amendment's "two or more INADMISSIBLE
    governed runs of the same arm => mandatory disclosure in the terminal
    receipt" clause."""
    rows = _load_rows(ledger_path)
    count = sum(1 for r in rows if r.get("event") == "exclusion" and r.get("arm") == arm)
    return {"count": count, "mandatory_disclosure": count >= 2}


# ---------------------------------------------------------------------------
# Selftest
# ---------------------------------------------------------------------------

def _selftest() -> int:
    failures = []

    # --- RED 1: unknown arm rejected, no row written ---
    with tempfile.TemporaryDirectory() as td:
        ledger = os.path.join(td, "ledger.jsonl")
        try:
            append_launch_row(ledger, "run-1", "not-a-real-arm", "2026-07-09T00:00:00Z", "abc", "def")
            failures.append("RED1 FAIL: unknown arm should raise ValueError")
        except ValueError:
            pass
        if os.path.exists(ledger):
            failures.append("RED1 FAIL: no ledger file should be created on a rejected append")

    # --- RED 2: duplicate run_id launch row rejected ---
    with tempfile.TemporaryDirectory() as td:
        ledger = os.path.join(td, "ledger.jsonl")
        append_launch_row(ledger, "run-2", "A-scratch", "2026-07-09T00:00:00Z", "abc", "def")
        try:
            append_launch_row(ledger, "run-2", "A-scratch", "2026-07-09T01:00:00Z", "xyz", "uvw")
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
            append_exclusion_row(ledger, "ghost-run", "A1", "no freeze hash", "2026-07-09T00:00:00Z")
            failures.append("RED3 FAIL: orphan exclusion row should raise ValueError")
        except ValueError:
            pass

    # --- GREEN 1: launch row read-back matches exactly, LF-only bytes ---
    with tempfile.TemporaryDirectory() as td:
        ledger = os.path.join(td, "ledger.jsonl")
        row = append_launch_row(ledger, "run-3", "gated-grown", "2026-07-09T02:00:00Z", "sha_c", "sha_a")
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
        append_launch_row(ledger, "run-4", "A-schedule", "2026-07-09T00:00:00Z", "c1", "a1")
        append_launch_row(ledger, "run-5", "A-schedule", "2026-07-09T00:00:00Z", "c2", "a2")

        valid_row = append_exclusion_row(
            ledger, "run-4", "Q6", "contamination_recheck != 0",
            receipted_ts="2026-07-09T01:00:00Z",
            first_post_launch_eval_ts="2026-07-09T02:00:00Z",
        )
        if valid_row["valid"] is not True:
            failures.append(f"GREEN2 FAIL: exclusion receipted before eval should be valid=True, got {valid_row['valid']}")

        invalid_row = append_exclusion_row(
            ledger, "run-5", "A3", "tuning receipts asymmetric",
            receipted_ts="2026-07-09T03:00:00Z",
            first_post_launch_eval_ts="2026-07-09T02:00:00Z",
        )
        if invalid_row["valid"] is not False:
            failures.append(f"GREEN2 FAIL: exclusion receipted after eval should be valid=False, got {invalid_row['valid']}")

        # --- GREEN 3: repeat-inadmissible disclosure -- 2 exclusions on same arm => mandatory ---
        disclosure = count_inadmissible_for_arm(ledger, "A-schedule")
        if disclosure != {"count": 2, "mandatory_disclosure": True}:
            failures.append(f"GREEN3 FAIL: expected count=2/mandatory_disclosure=True, got {disclosure}")

        # A different arm with zero exclusions must not trigger disclosure
        no_disclosure = count_inadmissible_for_arm(ledger, "A-scratch")
        if no_disclosure != {"count": 0, "mandatory_disclosure": False}:
            failures.append(f"GREEN3b FAIL: expected count=0/mandatory_disclosure=False, got {no_disclosure}")

    # --- GREEN 4: exclusion with unknown post-launch-eval ordering => valid=None ---
    with tempfile.TemporaryDirectory() as td:
        ledger = os.path.join(td, "ledger.jsonl")
        append_launch_row(ledger, "run-6", "gated-grown", "2026-07-09T00:00:00Z", "c", "a")
        row = append_exclusion_row(ledger, "run-6", "F4-per-event", "R_c below floor",
                                    receipted_ts="2026-07-09T01:00:00Z")
        if row["valid"] is not None:
            failures.append(f"GREEN4 FAIL: expected valid=None with no eval ts, got {row['valid']}")

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
