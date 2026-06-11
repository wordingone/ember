"""fp29_kill_synthesis_gate.py — kill-rule curriculum-synthesis
precondition gate (#200): reconcile the fp-26 kill wording with the
frozen fp-23 decide() protocol.

The gap (two frozen artifacts, one un-receipted clause):

- fp-26 kill rule (decision sha pinned below): "if the v0 owned core
  cannot clear a K1-equivalent verify floor in the fp-22 world EVEN WITH
  CURRICULUM SYNTHESIS (the NC2-own rung-level kill), DEMOTE to
  fallback (a)". The clause descends verbatim from the NC2-own
  pre-registration (STATE.md ladder section).
- fp-23 decide() (frozen pre-step-0): KILL = 2B fail + 4B fail, with
  the RETRY-AT-4B leg PASSIVE — nothing in the protocol requires a
  curriculum-synthesis attempt before the kill fires.

Unreconciled, the kill (user escalation + fallback demotion) could fire
without its own named precondition ever being exercised or receipted.
That is escalation-as-exit-ramp in mechanical form: the wall-breaking
step (shape the training mix toward the floor's world) must be receipted
BEFORE the escalation can leave the protocol.

Resolution (TIGHTEN-ONLY — composes, never mutates the frozen files):

- "Curriculum synthesis" is pinned to mean: L1/L2-grammar-shaped
  episodes (fp-23 ops, TRAIN buckets 10-99 only) mixed into the
  continued pretrain inside the 2B->4B retry window, receipted with the
  fields below. The probe buckets 0-9 stay untouched (leakage guard).
- A KILL verdict (fp-24 output) is VALID only when accompanied by a
  well-formed synthesis receipt. KILL without one ->
  KILL-REFUSED-SYNTHESIS-UNRECEIPTED: the rung-kill cannot escalate;
  the protocol's next step is to RUN the synthesis attempt, not to
  hand the work back.
- Every non-KILL branch passes through UNCHANGED. The bar (1.0),
  the mandatory 2B leg, and the single retry are untouched — the
  amendment only adds a validity precondition to the kill path, i.e.
  killing gets HARDER, the floor never relaxes.

fp-27 (round-1 prereg, #198) references this gate + receipt shape; the
synthesis receipt's EMITTER is the continued-pretrain harness (eng
track) — the shape is frozen here so the emitter binds to it, not the
reverse.

`--selftest` proves: pin integrity, branch outcomes (pass-through /
refused-unreceipted / refused-malformed / valid), tighten-only (frozen
constants unchanged; no new PASS path), and the emitted receipt is
receipt_check-clean. `--emit` writes the reconciliation receipt
(fail-closed on pin drift).
"""
import argparse
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

# ---- pins (drift = refuse) ------------------------------------------
FP26_DECISION = "research/fp26-round3-shape-decision.md"
FP26_DECISION_SHA = ("5ef7cc20f22168878f139af00e6ac9a75d43c758"
                     "ffd2b3eb181372c50081c939")
# the frozen protocol constants this gate must never move
FROZEN_PROTOCOL = {"FLOOR_RATE": 1.0, "FLOOR_CHECKPOINT": "2B",
                   "RETRY_CHECKPOINT": "4B"}
SHA_CONVENTION = ("file shas = sha256 over the exact on-disk raw bytes, no "
                  "normalization")

# ---- the synthesis receipt shape (frozen HERE; emitter binds to it) --
SYNTHESIS_REQUIRED_FIELDS = (
    "ticket",                       # CURRICULUM-SYNTHESIS-2B4B
    "ts",
    "window",                       # must be exactly "2B->4B"
    "episodes_generated",           # int > 0
    "bucket_range_assert",          # true: every instance in buckets 10-99
    "ops_in_grammar_assert",        # true: ops subset of fp-23 L1/L2 grammar
    "probe_buckets_untouched_assert",  # true: no bucket 0-9 materialized
    "ingestion_manifest_sha256",    # trainer data-manifest proving ingestion
)


def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _check_pins(nc=NC):
    """Empty list = pins hold. Fail-closed inputs to every public mode."""
    v = []
    dp = f"{nc}/{FP26_DECISION}"
    if not os.path.exists(dp):
        v.append(f"fp-26 decision missing: {FP26_DECISION}")
    elif _sha(dp) != FP26_DECISION_SHA:
        v.append(f"fp-26 decision sha drift: {_sha(dp)[:12]} != "
                 f"{FP26_DECISION_SHA[:12]}")
    for name, want in FROZEN_PROTOCOL.items():
        got = getattr(fp23, name, None)
        if got != want:
            v.append(f"fp-23 frozen constant moved: {name} {got!r} != {want!r}")
    return v


def validate_synthesis_receipt(sr):
    """Findings list (empty = well-formed synthesis attempt)."""
    f = []
    for field in SYNTHESIS_REQUIRED_FIELDS:
        if field not in sr:
            f.append(f"missing field: {field}")
    if f:
        return f
    if sr["window"] != "2B->4B":
        f.append(f"window must be '2B->4B', got {sr['window']!r}")
    ep = sr["episodes_generated"]
    if not isinstance(ep, int) or ep <= 0:
        f.append(f"episodes_generated must be int > 0, got {ep!r}")
    for a in ("bucket_range_assert", "ops_in_grammar_assert",
              "probe_buckets_untouched_assert"):
        if sr[a] is not True:
            f.append(f"{a} must be literally true, got {sr[a]!r}")
    return f


def validate_kill(verdict_receipt, synthesis_receipt=None):
    """The gate. Binds ONLY the KILL path; everything else passes through.

    Returns a dict with 'gate' in:
      PASS-THROUGH                      (verdict is not KILL — untouched)
      KILL-REFUSED-SYNTHESIS-UNRECEIPTED (kill cannot escalate; run the
                                          synthesis attempt first)
      KILL-REFUSED-SYNTHESIS-MALFORMED   (attempt claimed, receipt fails
                                          the frozen shape — findings named)
      KILL-VALID                         (precondition exercised + receipted)
    """
    verdict = verdict_receipt.get("verdict")
    if verdict != "KILL":
        return {"gate": "PASS-THROUGH", "verdict": verdict,
                "note": "gate binds only the kill path (tighten-only)"}
    if synthesis_receipt is None:
        return {"gate": "KILL-REFUSED-SYNTHESIS-UNRECEIPTED",
                "verdict": "KILL",
                "note": ("fp-26 kill clause 'even with curriculum synthesis' "
                         "never exercised: no synthesis receipt for the "
                         "2B->4B window. The rung-kill cannot escalate; the "
                         "next protocol step is the synthesis attempt, not "
                         "the escalation.")}
    findings = validate_synthesis_receipt(synthesis_receipt)
    if findings:
        return {"gate": "KILL-REFUSED-SYNTHESIS-MALFORMED",
                "verdict": "KILL", "findings": findings}
    return {"gate": "KILL-VALID", "verdict": "KILL",
            "synthesis_ticket": synthesis_receipt["ticket"],
            "ingestion_manifest_sha256":
                synthesis_receipt["ingestion_manifest_sha256"],
            "note": ("precondition exercised + receipted; the rung-kill may "
                     "surface to the user (fp-24 escalation framing)")}


def _demo_branches():
    """The four branch outcomes, demonstrated on synthetic fixtures."""
    good_sr = {"ticket": "CURRICULUM-SYNTHESIS-2B4B",
               "ts": "20260101T000000Z", "window": "2B->4B",
               "episodes_generated": 500, "bucket_range_assert": True,
               "ops_in_grammar_assert": True,
               "probe_buckets_untouched_assert": True,
               "ingestion_manifest_sha256": "0" * 64,
               "sha_convention": SHA_CONVENTION}
    bad_sr = dict(good_sr, episodes_generated=0)
    return {
        "pass_through": validate_kill({"verdict": "RETRY-AT-4B"}),
        "kill_unreceipted": validate_kill({"verdict": "KILL"}),
        "kill_malformed": validate_kill({"verdict": "KILL"}, bad_sr),
        "kill_valid": validate_kill({"verdict": "KILL"}, good_sr),
    }


def build_receipt(ts, branches):
    return {
        "ticket": "FP29-KILL-SYNTHESIS-GATE",
        "ts": ts,
        "issue": 200,
        "reconciliation": ("fp-26 'even with curriculum synthesis' is now a "
                           "RECEIPTED VALIDITY PRECONDITION on fp-23/fp-24 "
                           "KILL verdicts; composes around the frozen files, "
                           "mutates neither"),
        "synthesis_definition": ("L1/L2-grammar episodes (fp-23 ops, TRAIN "
                                 "buckets 10-99 only) mixed into the "
                                 "continued pretrain inside the 2B->4B "
                                 "retry window; probe buckets 0-9 untouched"),
        "synthesis_required_fields": list(SYNTHESIS_REQUIRED_FIELDS),
        "tighten_only": {"floor_rate": FROZEN_PROTOCOL["FLOOR_RATE"],
                         "floor_checkpoint":
                             FROZEN_PROTOCOL["FLOOR_CHECKPOINT"],
                         "retry_checkpoint":
                             FROZEN_PROTOCOL["RETRY_CHECKPOINT"],
                         "bar_moved": False,
                         "new_pass_path": False,
                         "kill_gains_precondition": True},
        "pins": {"fp26_decision": {"path": FP26_DECISION,
                                   "sha256": FP26_DECISION_SHA},
                 "fp23_frozen_constants": FROZEN_PROTOCOL},
        "gate_branches": branches,
        "result": {"verdict": "RECONCILED",
                   "kill_requires_synthesis_receipt": True},
        "sha_convention": SHA_CONVENTION,
        "no_gpu": True,
    }


def _selftest():
    v = _check_pins()
    assert v == [], v
    b = _demo_branches()
    # branch outcomes
    assert b["pass_through"]["gate"] == "PASS-THROUGH", b["pass_through"]
    assert b["kill_unreceipted"]["gate"] == \
        "KILL-REFUSED-SYNTHESIS-UNRECEIPTED", b["kill_unreceipted"]
    assert b["kill_malformed"]["gate"] == "KILL-REFUSED-SYNTHESIS-MALFORMED", \
        b["kill_malformed"]
    assert any("episodes_generated" in x
               for x in b["kill_malformed"]["findings"])
    assert b["kill_valid"]["gate"] == "KILL-VALID", b["kill_valid"]
    # tighten-only: every non-KILL decide() outcome passes through unchanged
    for verdict in ("PASS", "RETRY-AT-4B", "INFO", "PROTOCOL-VIOLATION",
                    "INVALID-RECEIPT", "INCOMPUTABLE"):
        assert validate_kill({"verdict": verdict})["gate"] == "PASS-THROUGH"
    # tighten-only: the frozen bar itself is untouched and still enforced
    assert fp23.decide("2B", 1.0)["verdict"] == "PASS"
    assert fp23.decide("2B", 0.99)["verdict"] == "RETRY-AT-4B"
    assert fp23.decide("4B", 0.5, prior_fail_at_2b=True)["verdict"] == "KILL"
    # a window other than 2B->4B is malformed (no synthesis credit outside
    # the retry window)
    sr = {k: v for k, v in {
        "ticket": "x", "ts": "x", "window": "1B->2B",
        "episodes_generated": 5, "bucket_range_assert": True,
        "ops_in_grammar_assert": True,
        "probe_buckets_untouched_assert": True,
        "ingestion_manifest_sha256": "0" * 64}.items()}
    assert validate_kill({"verdict": "KILL"}, sr)["gate"] == \
        "KILL-REFUSED-SYNTHESIS-MALFORMED"
    # emitted receipt is receipt_check-clean
    r = build_receipt("20260101T000000Z", b)
    assert validate_receipt(r) == [], validate_receipt(r)
    print("FP29_KILL_SYNTHESIS_GATE_SELFTEST_PASS")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--emit", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        _selftest()
        return
    v = _check_pins()
    if v:
        for x in v:
            print(f"PIN VIOLATION: {x}")
        raise SystemExit("fp29 gate REFUSED — pins do not hold")
    if not a.emit:
        print("FP29_KILL_SYNTHESIS_GATE_STAGED (pass --emit for the "
              "reconciliation receipt; validate_kill() is the live gate)")
        return
    branches = _demo_branches()
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt = build_receipt(ts, branches)
    out = f"{NC}/receipts/fp29-kill-gate-{ts}.json"
    checked_write(out, receipt)
    reloaded = json.load(open(out, encoding="utf-8"))
    f = validate_receipt(reloaded)
    if f:
        raise SystemExit(f"emitted fp29 receipt FAILS receipt_check: {f}")
    print(json.dumps(receipt["result"], indent=2))
    print(f"FP29_KILL_GATE_RECONCILED {os.path.relpath(out, NC)}")


if __name__ == "__main__":
    main()
