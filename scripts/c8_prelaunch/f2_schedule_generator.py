#!/usr/bin/env python3
"""f2_schedule_generator.py -- C8 pre-launch obligation O4 (issue #582; spec: the
F1-F4 fill amendment on issue #123, comment 4928342201, section 3 "F2 -- criterion
(gated vs A-schedule, same operator)"). CPU-only, zero deps beyond hashlib/json.

Pure function (k, phi_star, C_claim, N) -> the complete A-schedule arm growth-
event config. This is the "placement rule" the amendment closes the v1 gap with:
schedule event times must be a frozen pure function of PUBLIC quantities only,
hash-committed BEFORE the gated arm's run launches. When the gated run completes
and its real event count k is known, k is plugged into this SAME function and the
derived config hash is checked against the pre-commitment -- a hostile reviewer
can reproduce every event time from placement_fn_sha + public (N, C_claim) +
receipted k, with zero access to anything the gated run produced beyond that
integer.

ENDPOINT CONVENTION (frozen here, this commit)
-----------------------------------------------
    t_1        = phi_star * C_claim                      (first growth event)
    remaining  = C_claim - t_1 = (1 - phi_star) * C_claim
    segment    = remaining / k
    event_i    = t_1 + (i - 1) * segment,  for i = 2 .. k  (uniform spacing)

    events = [t_1, t_1 + segment, t_1 + 2*segment, ..., t_1 + (k-1)*segment]

k=1 degenerates to events = [t_1] (matches the amendment: "at rung-2 the design
is single-event so it degenerates to confirming k=1"). The k-1 remainder events
divide the interval (t_1, C_claim) into k equal-width segments and land strictly
inside it (the last event is exactly one segment before C_claim; C_claim itself
is the training budget, not a growth event).

N is carried through the emitted config as provenance/identification metadata
ONLY -- it plays NO role in the event-time formula above, which is a function of
(k, phi_star, C_claim) alone. This keeps the placement rule usable across any N.

ZERO GATED-ARM READS
---------------------
generate_schedule() takes k, phi_star, C_claim, N as plain numeric arguments and
performs NO file I/O of any kind -- it never opens, reads, or globs any path.
The CLI wrapper (main()) likewise takes these as plain --k/--phi-star/--c-claim
/--N numeric flags; there is deliberately no flag that accepts a gated-arm
artifact path. The RED selftest enforces this mechanically by monkeypatching
builtins.open to raise during a call to generate_schedule().

DETERMINISM
-----------
generate_schedule() is a pure function: two calls with identical arguments
produce byte-identical JSON (json.dumps(cfg, sort_keys=True)) and identical
sha256 of that serialization (config_hash in the returned dict). Verified by
the GREEN selftest (two independent calls, same hash) and the RED-adjacent
nondeterminism guard (asserts the hash never changes across repeated calls).

USAGE
-----
    python f2_schedule_generator.py --k K --phi-star P --c-claim C --N N
    python f2_schedule_generator.py --commit [--receipt-dir DIR]
    python f2_schedule_generator.py --selftest
"""
import argparse
import hashlib
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SCRIPTS = _HERE.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from receipt_write import checked_write  # noqa: E402

INVARIANT_SHA256 = "08a0eb7418c09a8088be4658e10785107abbb7507fc2dbcdc789936aa54e02a6"
SHA_CONVENTION = "bytes on disk as-is (binary read, no line-ending normalization)"

CONVENTION_TEXT = (
    "t_1 = phi_star * C_claim; remaining = C_claim - t_1; segment = remaining / k; "
    "event_i = t_1 + (i-1)*segment for i=1..k (uniform spacing of the k-1 "
    "remainder events across the remaining FLOP interval, strictly before "
    "C_claim). k=1 degenerates to events=[t_1]. N is provenance-only metadata, "
    "not used in the event-time formula."
)


def _code_sha256() -> str:
    with open(__file__, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


# Computed ONCE at module import time so generate_schedule() -- the pure
# function under the zero-file-I/O RED selftest -- never opens a file itself;
# it only ever reads this already-materialized constant.
CODE_SHA256 = _code_sha256()


def generate_schedule(k: int, phi_star: float, c_claim: float, N: int) -> dict:
    """Pure function: (k, phi_star, C_claim, N) -> A-schedule arm config.

    Performs NO file I/O. Deterministic: identical args -> identical output
    (including config_hash, computed over the canonical sorted-key JSON of
    every field EXCEPT config_hash itself).
    """
    if not isinstance(k, int) or k < 1:
        raise ValueError(f"generate_schedule: k must be a positive int, got {k!r}")
    if not (0.0 <= phi_star < 1.0):
        raise ValueError(f"generate_schedule: phi_star must be in [0, 1), got {phi_star!r}")
    if not (c_claim > 0):
        raise ValueError(f"generate_schedule: C_claim must be > 0, got {c_claim!r}")

    t_1 = phi_star * c_claim
    remaining = c_claim - t_1
    segment = remaining / k
    events = [t_1 + i * segment for i in range(k)]

    body = {
        "k": k,
        "phi_star": phi_star,
        "c_claim": c_claim,
        "N": N,
        "convention": CONVENTION_TEXT,
        "events": events,
        "generator_code_sha": CODE_SHA256,
    }
    canonical = json.dumps(body, sort_keys=True)
    config_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    body["config_hash"] = config_hash
    return body


# ---------------------------------------------------------------------------
# Selftest
# ---------------------------------------------------------------------------

def _selftest() -> int:
    failures = []

    # --- RED 1: zero file I/O -- generate_schedule must never call open() ---
    import builtins
    original_open = builtins.open

    def _guard(*a, **kw):
        raise AssertionError("f2 generator performed file I/O -- gated-arm dependency beyond k")

    builtins.open = _guard
    try:
        generate_schedule(k=3, phi_star=0.10, c_claim=1.0e21, N=500_000_000)
    except AssertionError as e:
        failures.append(f"RED1 FAIL: {e}")
    except Exception as e:
        failures.append(f"RED1 FAIL: unexpected exception under open() guard: {e}")
    finally:
        builtins.open = original_open

    # --- RED 2: invalid k (non-int, zero, negative) is rejected, never silently coerced ---
    for bad_k in (0, -1, 1.5, "3"):
        try:
            generate_schedule(k=bad_k, phi_star=0.1, c_claim=1e21, N=1)
            failures.append(f"RED2 FAIL: k={bad_k!r} should raise ValueError, did not")
        except ValueError:
            pass
        except Exception as e:
            failures.append(f"RED2 FAIL: k={bad_k!r} raised wrong exception type: {type(e).__name__}")

    # --- RED 3: nondeterminism guard -- repeated calls never diverge ---
    hashes = {generate_schedule(k=3, phi_star=0.1, c_claim=1e21, N=1)["config_hash"] for _ in range(5)}
    if len(hashes) != 1:
        failures.append(f"RED3 FAIL: config_hash varied across repeated calls: {hashes}")

    # --- GREEN: k=1 hand-computed ---
    cfg1 = generate_schedule(k=1, phi_star=0.10, c_claim=1.0e21, N=1)
    expected_events_1 = [1.0e20]  # t_1 = 0.10 * 1e21 = 1e20; k=1 -> events=[t_1]
    if cfg1["events"] != expected_events_1:
        failures.append(f"GREEN FAIL: k=1 events expected {expected_events_1}, got {cfg1['events']}")

    # --- GREEN: k=3 hand-computed ---
    # t_1 = 0.10 * 1e21 = 1e20; remaining = 9e20; segment = 3e20
    # events = [1e20, 4e20, 7e20]
    cfg3 = generate_schedule(k=3, phi_star=0.10, c_claim=1.0e21, N=1)
    expected_events_3 = [1.0e20, 4.0e20, 7.0e20]
    if cfg3["events"] != expected_events_3:
        failures.append(f"GREEN FAIL: k=3 events expected {expected_events_3}, got {cfg3['events']}")

    # --- GREEN: two independent runs byte-identical (config_hash stable) ---
    cfg3_again = generate_schedule(k=3, phi_star=0.10, c_claim=1.0e21, N=1)
    if cfg3["config_hash"] != cfg3_again["config_hash"]:
        failures.append("GREEN FAIL: config_hash not stable across independent calls")
    canon_a = json.dumps(cfg3, sort_keys=True)
    canon_b = json.dumps(cfg3_again, sort_keys=True)
    if canon_a != canon_b:
        failures.append("GREEN FAIL: canonical JSON not byte-identical across independent calls")

    # --- GREEN: N is carried but does not affect events/config_hash for the placement math ---
    cfg3_diffN_events = generate_schedule(k=3, phi_star=0.10, c_claim=1.0e21, N=999)["events"]
    if cfg3_diffN_events != expected_events_3:
        failures.append("GREEN FAIL: N must not affect the event-time formula")

    if failures:
        for f in failures:
            print(f"SELFTEST: {f}")
        return 1

    print("F2_SCHEDULE_GENERATOR_SELFTEST_PASS")
    return 0


def _commit(receipt_dir: str):
    """Write the one-time pre-commitment receipt: this generator's code_sha +
    convention, committed BEFORE any gated-arm run launches. This is a
    commitment to the LOGIC, not to any (k, phi_star, C_claim, N) instance --
    those are supplied later, once k is known from the completed gated run.
    """
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    receipt = {
        "ticket": "C8-PRELAUNCH-O4-F2-GENERATOR-COMMIT",
        "ts": ts,
        "invariant_sha256": INVARIANT_SHA256,
        "sha_convention": SHA_CONVENTION,
        "issue": 582,
        "refs": [123, 487, 449],
        "code_sha": CODE_SHA256,
        "convention": CONVENTION_TEXT,
        "committed_before_gated_launch": True,
    }
    fname = f"f2-generator-commit-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    os.makedirs(receipt_dir, exist_ok=True)
    out_path = os.path.join(receipt_dir, fname)
    checked_write(out_path, receipt)
    return out_path, receipt


def main():
    ap = argparse.ArgumentParser(description="C8 pre-launch O4: F2 A-schedule config generator.")
    ap.add_argument("--k", type=int)
    ap.add_argument("--phi-star", type=float)
    ap.add_argument("--c-claim", type=float)
    ap.add_argument("--N", type=int, default=0)
    ap.add_argument("--commit", action="store_true", help="write the one-time pre-commitment receipt")
    ap.add_argument("--receipt-dir", default="receipts/c8-prelaunch")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        sys.exit(_selftest())

    if args.commit:
        out_path, receipt = _commit(args.receipt_dir)
        print(json.dumps(receipt, indent=2))
        print(f"F2_GENERATOR_COMMIT_DONE {out_path}")
        sys.exit(0)

    if args.k is None or args.phi_star is None or args.c_claim is None:
        ap.error("--k, --phi-star, --c-claim are required unless --commit or --selftest")

    cfg = generate_schedule(args.k, args.phi_star, args.c_claim, args.N)
    print(json.dumps(cfg, indent=2))


if __name__ == "__main__":
    main()
