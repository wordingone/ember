"""fp23_probe_prereg.py — v0 checkpoint-probe analysis + curriculum
generator spec, FROZEN BEFORE PRETRAIN STEP 0 (#135).

Same discipline as fp-15: the analysis that will judge the owned core's
checkpoints is frozen before any checkpoint exists, so it can never be
fitted to the receipts it judges. fp-22 (research/fp22-corpus-world.md
§2–§3) named the world and the floor bar; this file pins the generator
grammar, the held-out split construction, the verifier semantics, the
receipt schema, and the PASS/RETRY/KILL decision procedure as
executable constants.

FROZEN CONSTANTS — changing any after the v0 pretrain dispatches is a
deviation (audit-§6 registry).

Curriculum L1 (deterministic transforms; exact-output verification):
  ops: reverse, sort_asc, sort_desc, filter_even, filter_odd, sum_fold,
       min_fold, max_fold, dedup_stable, count_distinct  (10 ops)
  inputs: int lists, len 4–12, values 0–99 (generator seed pins below)
  prompt rendering: fixed NL template per op (no paraphrase pool at L1 —
       paraphrase robustness is NOT what the floor measures)
  verification: reference implementation executes; candidate program
       output must EXACT-match (string-normalized repr); per-candidate
       timeout 5s; sandbox = the t1_probe harness discipline.

Curriculum L2: composition of 2–3 L1 ops, same verification.

Held-out split (no leakage by construction): an instance's bucket =
sha1(op_name + repr(input)) mod 100. PROBE buckets = 0–9 (10%);
training-time generation may only materialize buckets 10–99. The probe
set for a checkpoint = first 100 instances of buckets 0–9 under
generator seed 23, materialized once and sha-stamped.

Floor bar (fp-22 §3, verbatim): by the 2B-token checkpoint the core
must produce >= 1.0 verified L1 episode per governed GPU-minute at
k <= 16. One pre-registered retry at the 4B checkpoint. Second FAIL ->
rung-kill (core scale -> user escalation per NC2-own). Rate convention:
verified episodes / governed wall-clock minutes of the probe run,
pacing INCLUDED (fp-14 convention: governed wall = compute + pacing).

`--selftest` is pure-logic. main() without a checkpoint receipt prints
the STAGED sentinel; fp-24 executes the verdicts on real checkpoint
receipts — running the analysis early would un-freeze the spec.
"""
import hashlib
import json
import sys
from datetime import datetime, timezone

# ---- frozen pins ----------------------------------------------------
L1_OPS = ("reverse", "sort_asc", "sort_desc", "filter_even",
          "filter_odd", "sum_fold", "min_fold", "max_fold",
          "dedup_stable", "count_distinct")
INPUT_LEN = (4, 12)
INPUT_VAL = (0, 99)
PROBE_BUCKETS = range(0, 10)        # held-out 10%
TRAIN_BUCKETS = range(10, 100)
GENERATOR_SEED = 23
PROBE_N = 100                        # tasks per probe
PROBE_K = 16                         # candidates per task, max
FLOOR_RATE = 1.0                     # verified L1 episodes / governed minute
FLOOR_CHECKPOINT = "2B"
RETRY_CHECKPOINT = "4B"
CANDIDATE_TIMEOUT_S = 5
CHECKPOINTS = ("1B", "2B", "4B")

RECEIPT_REQUIRED_FIELDS = (
    "checkpoint_tokens", "step", "tokenizer_sha256",
    "corpus_manifest_sha256", "adapter_none_assert", "pacing",
    "governor", "probe_seed", "probe_set_sha256",
    "l1_verified_episodes", "l1_governed_minutes",
    "l1_tasks_any_verified", "l1_tasks_total",
    "l2_verified_episodes", "mbpp43_verified_samples",
)


def bucket(op, input_repr):
    """Held-out split function — sha1, deterministic across platforms."""
    h = hashlib.sha1(f"{op}{input_repr}".encode("utf-8")).hexdigest()
    return int(h, 16) % 100


def wilson_ci(s, n, z=1.96):
    """Wilson interval on the task-level any-verified proportion —
    quoted in probe receipts alongside the binding rate."""
    if n == 0:
        return (0.0, 1.0)
    p = s / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = (z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def floor_rate(verified_episodes, governed_minutes):
    if governed_minutes <= 0:
        return None
    return verified_episodes / governed_minutes


def decide(checkpoint, rate, prior_fail_at_2b=False):
    """PASS / RETRY-AT-4B / KILL / INFO — the frozen decision procedure.

    - 1B: information only (no bar).
    - 2B: rate >= FLOOR_RATE -> PASS; else RETRY-AT-4B (the one
      pre-registered retry).
    - 4B: rate >= FLOOR_RATE -> PASS (late-onset branch); else, if the
      2B leg already failed -> KILL (rung-kill fires, user escalation);
      a 4B fail WITHOUT a 2B fail is out-of-protocol (the 2B probe is
      mandatory) -> PROTOCOL-VIOLATION.
    """
    if rate is None:
        return {"verdict": "INCOMPUTABLE", "flag": "no governed minutes"}
    if checkpoint == "1B":
        return {"verdict": "INFO", "rate": rate, "bar": None}
    if checkpoint == "2B":
        if rate >= FLOOR_RATE:
            return {"verdict": "PASS", "rate": rate, "bar": FLOOR_RATE}
        return {"verdict": "RETRY-AT-4B", "rate": rate, "bar": FLOOR_RATE,
                "note": "the single pre-registered retry; no bar change"}
    if checkpoint == "4B":
        if rate >= FLOOR_RATE:
            return {"verdict": "PASS", "rate": rate, "bar": FLOOR_RATE,
                    "note": "late-onset branch"}
        if prior_fail_at_2b:
            return {"verdict": "KILL", "rate": rate, "bar": FLOOR_RATE,
                    "note": "rung-kill: core scale -> user escalation "
                            "(NC2-own); no third retry, no bar movement"}
        return {"verdict": "PROTOCOL-VIOLATION",
                "note": "4B fail without a recorded 2B leg"}
    return {"verdict": "PROTOCOL-VIOLATION", "note": f"unknown {checkpoint}"}


def validate_receipt(rec):
    """Schema floor: every required field present, else the probe is
    not a probe. Returns sorted missing-field list (empty = valid)."""
    return sorted(f for f in RECEIPT_REQUIRED_FIELDS if f not in rec)


def _selftest():
    # bucket determinism + split disjointness on a sample
    bs = {bucket("reverse", repr([1, 2, 3, 4])) for _ in range(3)}
    assert len(bs) == 1
    probe = sum(1 for op in L1_OPS for i in range(200)
                if bucket(op, repr(list(range(i, i + 5)))) < 10)
    total = len(L1_OPS) * 200
    assert 0.05 < probe / total < 0.15, probe / total  # ~10%
    # decision branches
    assert decide("1B", 0.2)["verdict"] == "INFO"
    assert decide("2B", 1.4)["verdict"] == "PASS"
    assert decide("2B", 0.6)["verdict"] == "RETRY-AT-4B"
    assert decide("4B", 1.1, prior_fail_at_2b=True)["verdict"] == "PASS"
    assert decide("4B", 0.3, prior_fail_at_2b=True)["verdict"] == "KILL"
    assert decide("4B", 0.3)["verdict"] == "PROTOCOL-VIOLATION"
    assert decide("2B", None)["verdict"] == "INCOMPUTABLE"
    # wilson sanity: 50/100 -> CI straddles 0.5, width sane
    lo, hi = wilson_ci(50, 100)
    assert lo < 0.5 < hi and hi - lo < 0.25
    # schema floor
    missing = validate_receipt({"checkpoint_tokens": 1})
    assert "pacing" in missing and "tokenizer_sha256" in missing
    assert validate_receipt({f: 1 for f in RECEIPT_REQUIRED_FIELDS}) == []
    print("FP23_PROBE_PREREG_SELFTEST_PASS")


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint-receipt")
    a, _ = ap.parse_known_args()
    if not a.checkpoint_receipt:
        print("FP23_PROBE_PREREG_STAGED (no checkpoint receipt exists yet; "
              "prereg frozen in this file — fp-24 runs the verdicts)")
        return
    raise SystemExit("fp-24 executes the verdicts on real checkpoint "
                     "receipts; running before then would un-freeze "
                     "the spec")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        main()
