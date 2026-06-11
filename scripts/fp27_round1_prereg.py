"""fp27_round1_prereg.py — owned-core accumulation ROUND-1 prereg,
FROZEN BEFORE CHECKPOINT-1 EXISTS (#198).

fp-26 froze the round-3 SHAPE: (b) owned-core in-dist accumulation.
This file freezes the ROUND itself — same discipline as fp-15/fp-23:
the constants that will shape and judge the first accumulation round on
ember-v0 are pinned before any checkpoint exists, so the round can never
be fitted to the core it trains.

SPLIT DISCIPLINE (the load-bearing design; all inside fp-23's frozen
bucket envelope, tighten-only):
  fp-23 froze: PROBE buckets 0-9 (floor surface, untouchable);
  training-time generation may only materialize buckets 10-99.
  This prereg PARTITIONS the train range:
    TRAIN materialization  = buckets 10-89  (sampling + episodes)
    ROUND-GATE eval        = buckets 90-99  (in-dist by construction —
                             same generator, same grammar, same
                             distribution — instance-disjoint by the
                             sha1 bucket function)
  Nothing trains on 90-99; nothing evals on 10-89; 0-9 stays the
  floor's. This IS the (b) shape's eval==train distribution with
  mechanical instance-level held-out.

KILL/ESCALATION WIRING (composes fp-23/fp-24/fp-29):
  - The FLOOR protocol is untouched: fp-23 decide() bar 1.0 at 2B,
    single retry at 4B, fp-24 executes, fp-29 gates the KILL.
  - MANDATORY-IN-WINDOW SYNTHESIS: if the 2B probe returns RETRY-AT-4B,
    the continued pretrain MUST include a receipted curriculum-synthesis
    mix (fp-29 SYNTHESIS_REQUIRED_FIELDS shape) inside the 2B->4B
    window. This binding prevents the fp-29 refusal deadlock: fp-22
    forbids a third retry, so a KILL refused for an un-receipted
    synthesis is an EXECUTION-DISCIPLINE violation surfaced to the user
    — never an authorization for a third probe.
  - A flat/negative ROUND result is DATA (feeds round-2 design), not a
    rung-kill. Only the floor protocol escalates.

`--selftest` pure-logic. `--freeze` emits fp27-prereg-<ts>.json
(prereg_frozen:true) and REFUSES if any pinned premise drifted or if a
real ember-v0 checkpoint receipt already exists (the freeze must beat
checkpoint-1 to disk — that is the whole point).
"""
import argparse
import glob
import hashlib
import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
NC = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from receipt_write import checked_write               # noqa: E402
from receipt_check import validate_receipt             # noqa: E402
import fp23_probe_prereg as fp23                       # noqa: E402
from fp29_kill_synthesis_gate import (                 # noqa: E402
    SYNTHESIS_REQUIRED_FIELDS, validate_kill)

# ---- pinned premises (drift = refuse) --------------------------------
FP26_DECISION = "research/fp26-round3-shape-decision.md"
FP26_DECISION_SHA = ("5ef7cc20f22168878f139af00e6ac9a75d43c758"
                     "ffd2b3eb181372c50081c939")
FP26_PREREG_GLOB = "receipts/fp26-prereg-*.json"       # must exist + frozen
# checkpoint receipts that would mean we froze too late (probe receipts
# carry the fp-23 16-field schema; the trainer's checkpoint receipts are
# v0-checkpoint-*; either on disk = freeze REFUSED)
CHECKPOINT_RECEIPT_GLOBS = ("receipts/v0-checkpoint-*.json",
                            "receipts/fp24-verdict-*.json")

# ---- frozen round-1 constants ----------------------------------------
ROUND = "own-r1"
BASE_POLICY = {
    "primary": ("terminal v0 checkpoint (full frozen token budget "
                "6,973,632,296), identified by the trainer's terminal "
                "receipt sha"),
    "calendar_fallback": ("if the terminal receipt is not on disk by "
                          "2026-06-18T00:00Z, base = the highest-token "
                          "checkpoint with a PASS floor verdict (fp-24), "
                          "token count >= 4B, AND verdict-receipt ts < "
                          "2026-06-18T00:00Z — the ts bound makes the "
                          "lookup TIME-INVARIANT (same answer whenever "
                          "evaluated; adversarial-panel fix). The chosen "
                          "base's receipt sha is recorded in the round-1 "
                          "dispatch receipt and is immutable thereafter."),
    "floor_precondition": ("round-1 dispatches ONLY after a PASS floor "
                           "verdict on the base checkpoint (fp-23 bar via "
                           "fp-24; KILL path gated by fp-29)"),
}
# split partition (inside fp-23's frozen envelope — see docstring)
TRAIN_BUCKETS = (10, 89)             # inclusive; sampling + episodes
ROUNDGATE_BUCKETS = (90, 99)         # inclusive; eval only, never trained
ROUNDGATE_N = 100                    # instances materialized for the gate
# sampling pins (frozen NOW, before any owned-core sampling exists)
SAMPLING = {
    "n_tasks_l1": 200,
    "n_tasks_l2": 56,
    "k": 8,
    "seed": 31,                       # never used before (16, 23, 3407 burned)
    "temperature": 0.8,
    "top_p": 0.95,
    "max_new_tokens": 512,
    "pacing": "fp-14 convention — governed wall = compute + pacing; the "
              "pacing block in the sampling receipt carries the "
              "retargeted fp-20c (#146) re-check",
}
# accumulation + arms
ACCUMULATION = {
    "ingest": ("verified episodes append to the owned ledger; retrain "
               "FROM BASE on the full ledger each round (GOAL "
               "replay-buffer convention — pays compute to sidestep "
               "forgetting; valid v0)"),
    "binding_arm": "sft",
    "information_arms": ("mtp / grpo legs only if governed windows "
                         "allow; information-only, no bar"),
}
# round gate (G1-equivalent, in-dist instance-held-out)
ROUND_GATE = {
    "surface": f"buckets {ROUNDGATE_BUCKETS[0]}-{ROUNDGATE_BUCKETS[1]}, "
               f"N={ROUNDGATE_N}, generator seed {fp23.GENERATOR_SEED}",
    "stats": "stats_exact paired vs base, per-task pass-any + per-sample",
    "d_gate": "round adapter quarantine vs owned base (sp-2 #201 instance)",
    "p_gate": "boundary pair across any daemon restart (sp-2 #201 instance)",
    "verdict_vocabulary": ("FROZEN — the round receipt's verdict is "
                           "mechanical from the paired CI on the binding "
                           "arm: GAIN (CI excludes 0, positive) / FLAT "
                           "(CI contains 0) / NEGATIVE (CI excludes 0, "
                           "negative). No other verdict words for round "
                           "outcomes (adversarial-panel fix: kills "
                           "post-hoc reframing)."),
    "round_failure_semantics": ("FLAT/NEGATIVE round = DATA for round-2 "
                                "design; never a rung-kill; only the floor "
                                "protocol escalates"),
}
SHA_CONVENTION = ("file shas = sha256 over the exact on-disk raw bytes, no "
                  "normalization")


def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def check_premises(nc=NC):
    """Empty = freeze may proceed. Fail-closed on drift AND on lateness."""
    v = []
    dp = f"{nc}/{FP26_DECISION}"
    if not os.path.exists(dp):
        v.append(f"fp-26 decision missing: {FP26_DECISION}")
    elif _sha(dp) != FP26_DECISION_SHA:
        v.append(f"fp-26 decision sha drift: {_sha(dp)[:12]} != "
                 f"{FP26_DECISION_SHA[:12]}")
    frozen = []
    for p in glob.glob(f"{nc}/{FP26_PREREG_GLOB}"):
        try:
            d = json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
        if d.get("prereg_frozen") and not validate_receipt(d):
            frozen.append(os.path.basename(p))
    if not frozen:
        v.append("no frozen fp-26 prereg receipt on disk")
    # the freeze must beat checkpoint-1 to disk
    for g in CHECKPOINT_RECEIPT_GLOBS:
        hits = glob.glob(f"{nc}/{g}")
        if hits:
            v.append(f"TOO LATE: checkpoint-era receipt(s) already exist "
                     f"({os.path.basename(hits[0])}) — a round-1 prereg "
                     f"frozen after checkpoint-1 is not a prereg")
    # split partition must sit inside fp-23's frozen envelope
    t0, t1 = TRAIN_BUCKETS
    g0, g1 = ROUNDGATE_BUCKETS
    if not (min(fp23.TRAIN_BUCKETS) <= t0 and
            g1 <= max(fp23.TRAIN_BUCKETS) and t1 + 1 == g0):
        v.append("bucket partition violates fp-23 frozen envelope")
    if set(range(t0, t1 + 1)) & set(fp23.PROBE_BUCKETS) or \
       set(range(g0, g1 + 1)) & set(fp23.PROBE_BUCKETS):
        v.append("partition touches the frozen probe buckets 0-9")
    return v


def build_receipt(ts, premises_frozen_prereg):
    return {
        "ticket": "FP27-ROUND1-PREREG",
        "ts": ts,
        "issue": 198,
        "round": ROUND,
        "prereg_frozen": True,
        "base_policy": BASE_POLICY,
        "split": {
            "probe_buckets": "0-9 (fp-23 frozen, untouchable)",
            "train_buckets": f"{TRAIN_BUCKETS[0]}-{TRAIN_BUCKETS[1]}",
            "roundgate_buckets": f"{ROUNDGATE_BUCKETS[0]}-"
                                 f"{ROUNDGATE_BUCKETS[1]}",
            "roundgate_n": ROUNDGATE_N,
            "in_dist_by_construction": True,
        },
        "sampling": SAMPLING,
        "accumulation": ACCUMULATION,
        "round_gate": ROUND_GATE,
        "kill_wiring": {
            "floor_protocol": "fp-23 decide() via fp-24; bar untouched",
            "kill_gate": "fp-29 validate_kill — KILL valid only with a "
                         "receipted 2B->4B synthesis attempt",
            "mandatory_in_window_synthesis": (
                "RETRY-AT-4B at 2B OBLIGATES a receipted synthesis mix in "
                "the continued pretrain before the 4B leg (fp-29 shape: "
                + ", ".join(SYNTHESIS_REQUIRED_FIELDS) + ")"),
            "refusal_semantics": ("an un-receipted KILL refusal = "
                                  "execution-discipline violation surfaced "
                                  "to the user; NEVER a third probe (fp-22: "
                                  "no third retry)"),
            "synthesis_audit_obligation": (
                "gate-time auditor re-derives bucket membership + episode "
                "count from the episodes manifest (eng-53 byte-scan "
                "pattern) — the boolean asserts are the emitter's claim, "
                "never the verdict's evidence"),
        },
        "premises": {
            "fp26_decision": {"path": FP26_DECISION,
                              "sha256": FP26_DECISION_SHA},
            "fp26_prereg_receipts": premises_frozen_prereg,
        },
        "result": {"verdict": "FROZEN", "round": ROUND},
        "sha_convention": SHA_CONVENTION,
        "no_gpu": True,
    }


def _selftest():
    v = check_premises()
    assert v == [], v
    # partition arithmetic: disjoint, exhaustive over 10-99, probe untouched
    t = set(range(TRAIN_BUCKETS[0], TRAIN_BUCKETS[1] + 1))
    g = set(range(ROUNDGATE_BUCKETS[0], ROUNDGATE_BUCKETS[1] + 1))
    assert not (t & g)
    assert t | g == set(fp23.TRAIN_BUCKETS)
    assert not (t | g) & set(fp23.PROBE_BUCKETS)
    # the bucket function actually routes instances to all three regions
    seen = {"probe": 0, "train": 0, "gate": 0}
    for i in range(500):
        b = fp23.bucket("reverse", repr(list(range(i % 7 + 4))) + str(i))
        if b in fp23.PROBE_BUCKETS:
            seen["probe"] += 1
        elif b in t:
            seen["train"] += 1
        elif b in g:
            seen["gate"] += 1
    assert all(c > 0 for c in seen.values()), seen
    # seed 31 is virgin (burned: 16 probe/coverage, 23 fp25b fresh, 3407 trl)
    assert SAMPLING["seed"] not in (16, 23, 3407)
    # kill wiring composes: fp-29 gate refuses an unreceipted KILL
    assert validate_kill({"verdict": "KILL"})["gate"] == \
        "KILL-REFUSED-SYNTHESIS-UNRECEIPTED"
    # receipt clean
    r = build_receipt("20260101T000000Z", ["fp26-prereg-x.json"])
    assert r["prereg_frozen"] is True
    assert validate_receipt(r) == [], validate_receipt(r)
    print("FP27_ROUND1_PREREG_SELFTEST_PASS")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--freeze", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        _selftest()
        return
    if not a.freeze:
        print("FP27_ROUND1_PREREG_STAGED (pass --freeze to emit; refuses "
              "after checkpoint-1 exists)")
        return
    v = check_premises()
    if v:
        for x in v:
            print(f"PREMISE VIOLATION: {x}")
        raise SystemExit("fp27 prereg REFUSED")
    frozen = [os.path.basename(p)
              for p in glob.glob(f"{NC}/{FP26_PREREG_GLOB}")]
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt = build_receipt(ts, frozen)
    out = f"{NC}/receipts/fp27-prereg-{ts}.json"
    checked_write(out, receipt)
    reloaded = json.load(open(out, encoding="utf-8"))
    f = validate_receipt(reloaded)
    if f:
        raise SystemExit(f"emitted fp27 prereg FAILS receipt_check: {f}")
    print(json.dumps(receipt["result"], indent=2))
    print(f"FP27_ROUND1_PREREG_FROZEN {os.path.relpath(out, NC)}")


if __name__ == "__main__":
    main()
