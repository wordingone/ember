#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""f2_schedule_generator.py -- C8 pre-launch obligation O4 (issue #582; spec: the
F1-F4 fill amendment on issue #123, comment 4928342201, section 3 "F2 -- criterion
(gated vs A-schedule, same operator)"). CPU-only, zero deps beyond hashlib/json.

INSTANCE COMMITMENT + VERIFIER (issue #629; frozen cure adopted from the
independent-audit disposition on issue #123, "Tighten-only clearance"
section, refs #582 #592):

Independent-audit finding (CONFIRMED, reproduced in
tests/test_f2_instance_commitment.py): the original `--commit` receipt binds
only `code_sha` + the convention TEXT -- an algorithm-family commitment, not
an instance commitment. `generate_schedule(k=1, phi_star=.10, C=1e21,
N=368000000)` and the same call with `phi_star=.40` both carry the IDENTICAL
`generator_code_sha`, so a single code-only precommitment receipt is
consistent with either schedule (config_hash 822f480... vs 12d9302...) --
`phi_star` could be selected or swapped AFTER the gated arm's output while
the receipt still reads "committed before launch".

Cure: `instance_closure_body()` / `commit_instance()` / `verify_instance()`
below bind `generator_code_sha` + `phi_star` + a placement-sweep RECEIPT
HASH (see f2_placement_sweep.py) + `C_claim` + `N` + `ARITHMETIC_REPRESENTATION`
+ `ROUNDING_CONVENTION` into one `instance_hash`. Only `k` remains unbound --
plugged in at gated completion per the existing check procedure (issue #123
comment: read k from the gated-arm receipts, run the committed generator,
assert the derived config_hash matches the pre-committed per-k fixture).
`verify_instance()` recomputes `instance_hash` from CLAIMED instantiation
values and REJECTS any mismatch on any bound field -- this is what closes
the .10/.40 collision: two different phi_star values now hash to two
different commitments, so a receipt committed at phi_star=.10 rejects a
later claim of phi_star=.40 (see tests/test_f2_instance_commitment.py
::TestVerifierRejectsUncommittedInputs).

`map_events_to_steps()` (issue #629 deliverable 4) converts the continuous
FLOP event targets this module already produces into exact integer
optimizer-step boundaries under a frozen ROUNDING_CONVENTION, and receipts
the realized budget error against the standing <=2% budget-match limit
(BUDGET_LIMIT_PCT) -- this is the field the audit named unresolved: "a
config hash does not yet identify the actual executable event schedule or
prove the standing <=2% budget match."

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
# Instance commitment + verifier (issue #629)
# ---------------------------------------------------------------------------

# Bound at instance-commit time (issue #629 deliverable 1) so a hostile
# reviewer cannot reinterpret the committed numbers under a different
# numeric representation or rounding scheme to manufacture a second schedule
# consistent with the same commitment.
ARITHMETIC_REPRESENTATION = (
    "IEEE-754 binary64 (Python float); canonical serialization via "
    "json.dumps(obj, sort_keys=True) using Python's default float repr "
    "(round-trip shortest-decimal, float.__repr__); no rounding is applied "
    "to phi_star/c_claim/N before hashing -- rounding only enters via "
    "ROUNDING_CONVENTION at the integer-step-boundary mapping stage."
)

# Bound at instance-commit time; governs map_events_to_steps() below.
ROUNDING_CONVENTION = "round-half-away-from-zero to the nearest integer optimizer step"

# Standing C8 budget-match limit (issue #123 fill amendment, "Preserved
# verbatim: budget <=2%"), reused here for the realized-vs-claimed check.
BUDGET_LIMIT_PCT = 2.0

# Instance-commit / instance-verify receipts must carry a sha256 whose
# digest byte-length matches this (defensive shape check on the
# sweep-receipt-hash input -- catches truncated/garbage hashes early).
_SHA256_HEXLEN = 64


def _round_half_away_from_zero(x: float) -> int:
    """The ROUNDING_CONVENTION, implemented explicitly (never Python's
    built-in round(), which is round-half-to-even/banker's rounding -- a
    DIFFERENT, unbound convention that would silently change results at the
    .5 boundary)."""
    import math
    if x >= 0:
        return int(math.floor(x + 0.5))
    return -int(math.floor(-x + 0.5))


def flops_per_step(param_count: int, batch: int, seq: int) -> float:
    """6*N*tokens/step -- the SAME dense-transformer FLOPs/step convention as
    src/ember/governance/scripts/cbase_grow_live.py::_flops_per_step (Kaplan et al. 2020 /
    Chinchilla fwd+bwd estimate). Reimplemented (not imported) rather than
    reused by import: cbase_grow_live.py pulls in timeshare_pretrain /
    cbase_grow_dryrun (the real training stack), which would break this
    module's standing zero-heavy-deps property (CPU-only, no torch import,
    no gated-arm reads). The formula itself is a one-line arithmetic
    identity -- reuse of the CONVENTION, cited, without the dependency."""
    return 6.0 * param_count * batch * seq


def map_events_to_steps(events, c_claim: float, flops_per_step_val: float) -> dict:
    """Issue #629 deliverable 4: convert continuous FLOP event targets (and
    the total claimed training budget C_claim) into exact integer
    optimizer-step boundaries under ROUNDING_CONVENTION, and receipt the
    realized budget error against BUDGET_LIMIT_PCT.

    Pure function, zero file I/O, deterministic (see
    tests/test_f2_instance_commitment.py::TestIntegerStepBoundaryBudgetCheck).
    """
    if not (flops_per_step_val > 0):
        raise ValueError(f"map_events_to_steps: flops_per_step_val must be > 0, got {flops_per_step_val!r}")
    if not (c_claim > 0):
        raise ValueError(f"map_events_to_steps: c_claim must be > 0, got {c_claim!r}")

    event_steps = [_round_half_away_from_zero(e / flops_per_step_val) for e in events]
    realized_event_flops = [s * flops_per_step_val for s in event_steps]
    total_steps = _round_half_away_from_zero(c_claim / flops_per_step_val)
    realized_c_claim = total_steps * flops_per_step_val
    budget_error_pct = abs(realized_c_claim - c_claim) / c_claim * 100.0

    return {
        "flops_per_step": flops_per_step_val,
        "rounding_convention": ROUNDING_CONVENTION,
        "event_steps": event_steps,
        "realized_event_flops": realized_event_flops,
        "total_steps": total_steps,
        "c_claim": c_claim,
        "realized_c_claim": realized_c_claim,
        "budget_error_pct": budget_error_pct,
        "budget_limit_pct": BUDGET_LIMIT_PCT,
        "budget_ok": budget_error_pct <= BUDGET_LIMIT_PCT,
    }


def instance_closure_body(phi_star: float, c_claim: float, N: int, sweep_receipt_sha256: str) -> dict:
    """The canonical, hashable instance-closure body: everything the frozen
    cure requires bound EXCEPT k -- generator_code_sha, phi_star,
    sweep_receipt_sha256, c_claim, N, arithmetic_representation,
    rounding_convention. Raises ValueError on any uncommitted/malformed
    input (this IS the "verifier rejects uncommitted inputs" floor: a
    receipt can only be produced from validated instantiation values)."""
    if not (0.0 <= phi_star < 1.0):
        raise ValueError(f"instance_closure_body: phi_star must be in [0, 1), got {phi_star!r}")
    if not (c_claim > 0):
        raise ValueError(f"instance_closure_body: c_claim must be > 0, got {c_claim!r}")
    if not isinstance(sweep_receipt_sha256, str) or len(sweep_receipt_sha256) != _SHA256_HEXLEN:
        raise ValueError(
            f"instance_closure_body: sweep_receipt_sha256 must be a {_SHA256_HEXLEN}-hex-char "
            f"sha256 digest, got {sweep_receipt_sha256!r}"
        )
    try:
        int(sweep_receipt_sha256, 16)
    except ValueError:
        raise ValueError(
            f"instance_closure_body: sweep_receipt_sha256 must be valid hex, got {sweep_receipt_sha256!r}"
        )

    body = {
        "generator_code_sha": CODE_SHA256,
        "phi_star": phi_star,
        "sweep_receipt_sha256": sweep_receipt_sha256,
        "c_claim": c_claim,
        "N": N,
        "arithmetic_representation": ARITHMETIC_REPRESENTATION,
        "rounding_convention": ROUNDING_CONVENTION,
    }
    canonical = json.dumps(body, sort_keys=True)
    instance_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    body["instance_hash"] = instance_hash
    return body


def commit_instance(phi_star: float, c_claim: float, N: int, sweep_receipt_sha256: str,
                     receipt_dir: str = "receipts/c8-prelaunch"):
    """Write the one-time INSTANCE commitment receipt -- binds code_sha,
    phi_star, sweep_receipt_sha256, C_claim, N, arithmetic representation,
    and rounding convention, leaving only k unbound. This is issued BEFORE
    the gated arm's run launches, same as the pre-existing code-only
    `--commit`, but additionally closes the .10/.40 collision (see module
    docstring)."""
    body = instance_closure_body(phi_star, c_claim, N, sweep_receipt_sha256)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    receipt = {
        "ticket": "C8-PRELAUNCH-O4-F2-INSTANCE-COMMIT",
        "ts": ts,
        "invariant_sha256": INVARIANT_SHA256,
        "sha_convention": SHA_CONVENTION,
        "issue": 629,
        "refs": [123, 582, 584],
        "committed_before_gated_launch": True,
        "unbound_field": "k (plugged in only after the gated run completes; "
                          "checked against the pre-committed per-k fixture)",
        **body,
    }
    fname = f"f2-instance-commit-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    os.makedirs(receipt_dir, exist_ok=True)
    out_path = os.path.join(receipt_dir, fname)
    checked_write(out_path, receipt)
    return out_path, receipt


def verify_instance(receipt_path_or_obj, claimed_phi_star, claimed_c_claim, claimed_N,
                     claimed_sweep_receipt_sha256):
    """Issue #629 deliverable 2: the verifier. Recomputes instance_hash from
    the CLAIMED instantiation values and requires an EXACT match against the
    pre-committed receipt. Rejects (returns False, reason) on: any bound
    field mismatch, a generator_code_sha mismatch (receipt committed under a
    different generator version), or malformed/uncommitted-shape claimed
    inputs (phi_star out of [0,1), bad sweep-hash shape, etc -- these raise
    inside instance_closure_body(), caught and reported as a REJECT here
    rather than propagating).

    Returns (ok: bool, reason: str).
    """
    if isinstance(receipt_path_or_obj, (str, Path)):
        with open(receipt_path_or_obj, "r", encoding="utf-8") as f:
            receipt = json.load(f)
    else:
        receipt = receipt_path_or_obj

    if receipt.get("generator_code_sha") != CODE_SHA256:
        return False, (
            "REJECT: generator_code_sha mismatch -- receipt was committed "
            "under a different generator version than the one running this verify"
        )

    try:
        recomputed = instance_closure_body(
            claimed_phi_star, claimed_c_claim, claimed_N, claimed_sweep_receipt_sha256,
        )
    except ValueError as e:
        return False, f"REJECT: uncommitted/invalid claimed input: {e}"

    if recomputed["instance_hash"] != receipt.get("instance_hash"):
        mismatches = [
            k for k in ("phi_star", "c_claim", "N", "sweep_receipt_sha256",
                        "arithmetic_representation", "rounding_convention")
            if recomputed.get(k) != receipt.get(k)
        ]
        return False, (
            f"REJECT: instance_hash mismatch (committed {receipt.get('instance_hash')!r} != "
            f"claimed {recomputed['instance_hash']!r}); differing bound field(s): {mismatches}"
        )

    return True, "ACCEPT: claimed instantiation matches the pre-committed instance closure"


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

    # === Issue #629: instance commitment + verifier ========================
    FAKE_SWEEP_SHA = "a" * 64

    # --- RED 4: the audit's .10/.40 collision, reproduced against the OLD
    # code-only commitment shape, still exists at the raw generator level
    # (this is the vulnerability's ground truth -- the fix lives in the
    # instance closure, not in generate_schedule itself). ---
    audit_a = generate_schedule(k=1, phi_star=0.10, c_claim=1.0e21, N=368_000_000)
    audit_b = generate_schedule(k=1, phi_star=0.40, c_claim=1.0e21, N=368_000_000)
    if audit_a["generator_code_sha"] != audit_b["generator_code_sha"]:
        failures.append("RED4 FAIL: generator_code_sha should be IDENTICAL across phi_star "
                         "(this is the code-only commitment's blind spot, not a bug in generate_schedule)")
    if audit_a["events"] != [1.0e20] or audit_b["events"] != [4.0e20]:
        failures.append(f"RED4 FAIL: audit fixture events drifted: a={audit_a['events']} b={audit_b['events']}")
    if audit_a["config_hash"] == audit_b["config_hash"]:
        failures.append("RED4 FAIL: materially different schedules must NOT share a config_hash")
    # NOTE: the literal config_hash values are NOT pinned here (unlike the
    # audit's own replay) because config_hash embeds generator_code_sha,
    # which changes with every edit to this file (including this cure) --
    # pinning the audit's exact hex digests would make this selftest fail on
    # the very commit that fixes the underlying issue. The audit's exact
    # digests are preserved as a receipted, byte-frozen artifact instead:
    # receipts/c8-prelaunch/f2-collision-repro-*.json (pre-cure git blob
    # e12494f5dd3eea288677416aa0829a0cc95b36e1).

    # --- RED 5: verify_instance REJECTS the .10/.40 collision under one
    # instance commitment -- the actual cure. ---
    with tempfile.TemporaryDirectory() as td:
        out_path, _ = commit_instance(phi_star=0.10, c_claim=1.0e21, N=368_000_000,
                                       sweep_receipt_sha256=FAKE_SWEEP_SHA, receipt_dir=td)
        ok_same, _ = verify_instance(out_path, claimed_phi_star=0.10, claimed_c_claim=1.0e21,
                                      claimed_N=368_000_000, claimed_sweep_receipt_sha256=FAKE_SWEEP_SHA)
        ok_collision, reason_collision = verify_instance(
            out_path, claimed_phi_star=0.40, claimed_c_claim=1.0e21,
            claimed_N=368_000_000, claimed_sweep_receipt_sha256=FAKE_SWEEP_SHA,
        )
        if ok_same is not True:
            failures.append("RED5 FAIL: matching instantiation must be ACCEPTed")
        if ok_collision is not False:
            failures.append("RED5 FAIL: the .10/.40 collision must be REJECTed post-cure")
        if "REJECT" not in reason_collision:
            failures.append(f"RED5 FAIL: rejection reason malformed: {reason_collision!r}")

    # --- RED 6: verify_instance rejects malformed/uncommitted claimed input ---
    try:
        verify_instance({"generator_code_sha": CODE_SHA256, "instance_hash": "0" * 64},
                         claimed_phi_star=1.5, claimed_c_claim=1.0e21,
                         claimed_N=1, claimed_sweep_receipt_sha256=FAKE_SWEEP_SHA)
        ok6, reason6 = verify_instance(
            {"generator_code_sha": CODE_SHA256, "instance_hash": "0" * 64},
            claimed_phi_star=1.5, claimed_c_claim=1.0e21, claimed_N=1,
            claimed_sweep_receipt_sha256=FAKE_SWEEP_SHA,
        )
        if ok6 is not False or "REJECT" not in reason6:
            failures.append("RED6 FAIL: out-of-domain phi_star must be REJECTed, not raise/pass")
    except Exception as e:
        failures.append(f"RED6 FAIL: verify_instance must reject, not raise: {e!r}")

    # --- GREEN: instance closure binds all required fields, excludes k ---
    body = instance_closure_body(phi_star=0.10, c_claim=1.0e21, N=368_000_000,
                                  sweep_receipt_sha256=FAKE_SWEEP_SHA)
    for field in ("generator_code_sha", "phi_star", "sweep_receipt_sha256", "c_claim",
                  "N", "arithmetic_representation", "rounding_convention", "instance_hash"):
        if field not in body:
            failures.append(f"GREEN FAIL: instance closure missing bound field {field!r}")
    if "k" in body:
        failures.append("GREEN FAIL: k must remain UNBOUND in the instance closure")

    # --- GREEN: integer step-boundary mapping + budget check (hand-computed) ---
    steps = map_events_to_steps([1.0e20, 4.0e20], c_claim=1.0e21, flops_per_step_val=1.0e18)
    if steps["event_steps"] != [100, 400]:
        failures.append(f"GREEN FAIL: event_steps expected [100, 400], got {steps['event_steps']}")
    if steps["total_steps"] != 1000:
        failures.append(f"GREEN FAIL: total_steps expected 1000, got {steps['total_steps']}")
    if abs(steps["budget_error_pct"]) > 1e-9:
        failures.append(f"GREEN FAIL: exact-division budget_error_pct expected ~0, got {steps['budget_error_pct']}")
    if steps["budget_ok"] is not True:
        failures.append("GREEN FAIL: exact-division case should be budget_ok")

    # c_claim/flops_per_step = 10.5 exactly -> rounds to 11 steps (round-half-
    # away-from-zero), realized = 11/10.5 * c_claim => ~4.76% over budget.
    coarse_fps = 1.0e21 / 10.5
    steps_over = map_events_to_steps([1.0e20], c_claim=1.0e21, flops_per_step_val=coarse_fps)
    if steps_over["total_steps"] != 11:
        failures.append(f"GREEN FAIL: coarse-step total_steps expected 11, got {steps_over['total_steps']}")
    if steps_over["budget_ok"] is not False or steps_over["budget_error_pct"] <= 2.0:
        failures.append(f"GREEN FAIL: coarse-step case should exceed the 2% budget limit, "
                         f"got budget_error_pct={steps_over['budget_error_pct']}, budget_ok={steps_over['budget_ok']}")

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
    ap.add_argument("--commit", action="store_true", help="write the one-time pre-commitment receipt (code-only; superseded for instance-level use by --commit-instance, issue #629)")
    ap.add_argument("--commit-instance", action="store_true",
                     help="write the instance-closure commitment receipt (issue #629): binds "
                          "code_sha + phi_star + sweep-receipt hash + C_claim + N + arithmetic "
                          "representation + rounding convention; only k stays unbound")
    ap.add_argument("--sweep-receipt-sha256", help="sha256 of the placement-sweep receipt (required with --commit-instance)")
    ap.add_argument("--verify-instance", metavar="RECEIPT_PATH",
                     help="verify a claimed (phi_star, C_claim, N, sweep-receipt-sha256) against "
                          "a pre-committed instance-closure receipt; rejects any mismatch")
    ap.add_argument("--map-steps", action="store_true",
                     help="map --k's generated events (or a bare --c-claim) to integer optimizer-step "
                          "boundaries and receipt the realized budget error; requires --flops-per-step")
    ap.add_argument("--flops-per-step", type=float, help="FLOPs/optimizer-step for --map-steps")
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

    if args.commit_instance:
        if args.phi_star is None or args.c_claim is None or args.sweep_receipt_sha256 is None:
            ap.error("--commit-instance requires --phi-star, --c-claim, --sweep-receipt-sha256")
        out_path, receipt = commit_instance(
            phi_star=args.phi_star, c_claim=args.c_claim, N=args.N,
            sweep_receipt_sha256=args.sweep_receipt_sha256, receipt_dir=args.receipt_dir,
        )
        print(json.dumps(receipt, indent=2))
        print(f"F2_INSTANCE_COMMIT_DONE {out_path}")
        sys.exit(0)

    if args.verify_instance:
        if args.phi_star is None or args.c_claim is None or args.sweep_receipt_sha256 is None:
            ap.error("--verify-instance requires --phi-star, --c-claim, --N, --sweep-receipt-sha256 (the CLAIMED values)")
        ok, reason = verify_instance(
            args.verify_instance, claimed_phi_star=args.phi_star, claimed_c_claim=args.c_claim,
            claimed_N=args.N, claimed_sweep_receipt_sha256=args.sweep_receipt_sha256,
        )
        print(reason)
        print(f"F2_VERIFY_INSTANCE_{'ACCEPT' if ok else 'REJECT'}")
        sys.exit(0 if ok else 1)

    if args.map_steps:
        if args.flops_per_step is None or args.c_claim is None:
            ap.error("--map-steps requires --flops-per-step and --c-claim")
        if args.k is not None and args.phi_star is not None:
            events = generate_schedule(args.k, args.phi_star, args.c_claim, args.N)["events"]
        else:
            events = []
        result = map_events_to_steps(events, c_claim=args.c_claim, flops_per_step_val=args.flops_per_step)
        print(json.dumps(result, indent=2))
        sys.exit(0)

    if args.k is None or args.phi_star is None or args.c_claim is None:
        ap.error("--k, --phi-star, --c-claim are required unless --commit/--commit-instance/--verify-instance/--selftest")

    cfg = generate_schedule(args.k, args.phi_star, args.c_claim, args.N)
    print(json.dumps(cfg, indent=2))


if __name__ == "__main__":
    main()
