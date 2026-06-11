"""fp24_verdict.py — execute the FROZEN fp-23 checkpoint-probe verdicts on
REAL v0 checkpoint receipts (#139, successor to fp-23 #135).

fp-23 (scripts/fp23_probe_prereg.py) froze, BEFORE pretrain step 0:
  - the L1 curriculum grammar + held-out split,
  - the 16-field probe receipt schema,
  - the PASS / RETRY-AT-4B / KILL / PROTOCOL-VIOLATION decision procedure
    (decide()), and the floor bar (>=1.0 verified L1 episode / governed
    GPU-minute at the 2B checkpoint, one retry at 4B, then rung-kill).

fp-23's own main() REFUSES to run a verdict on a real receipt ("running
before then would un-freeze the spec") and names THIS file as the
executor. fp-24 consumes fp-23's frozen functions — it adds NO new
decision logic, only the plumbing from a real checkpoint receipt to the
frozen decide(): validate the schema floor, compute the rate via the
frozen floor_rate(), resolve the prior-2B outcome for a 4B leg, call
decide(), and emit a verdict receipt. The single source of truth for the
bar, the schema, and the branches is fp23_probe_prereg — imported, never
re-implemented.

KILL handling: a KILL verdict is the rung-kill firing (core scale ->
user escalation per NC2-own). This script SURFACES that verdict in the
receipt with the escalation framing; it does NOT auto-escalate and does
NOT move the bar (gate-discipline: tighten on failure, never relax).

`--selftest` pure-logic (synthetic receipts pin every branch).
Live: python fp24_verdict.py --checkpoint 2B --receipt <probe.json>
      python fp24_verdict.py --checkpoint 4B --receipt <probe.json> \
             --prior-2b-verdict <2b-fp24-verdict.json>
"""
import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

# Single source of truth — the frozen prereg. No decision logic is
# re-implemented here.
import fp23_probe_prereg as fp23  # noqa: E402

# token tolerance when cross-checking the receipt's checkpoint_tokens
# against the named checkpoint (the dispatcher names the checkpoint; the
# receipt's count must be in the right decade — a coarse sanity guard,
# not a re-derivation of the bar).
_CHECKPOINT_TOKENS = {"1B": 1_000_000_000, "2B": 2_000_000_000,
                      "4B": 4_000_000_000}
_TOKEN_TOL = 0.25  # +/-25% of the named checkpoint's nominal token count


def _prior_fail_at_2b(prior_2b_verdict):
    """fp-23 semantics: a 2B leg that misses the bar returns
    RETRY-AT-4B. So prior_fail_at_2b is true iff the recorded 2B verdict
    was RETRY-AT-4B. PASS at 2B never reaches a 4B floor leg."""
    return prior_2b_verdict == "RETRY-AT-4B"


def run_verdict(checkpoint, receipt, prior_2b_verdict=None):
    """Plumb a real checkpoint receipt into the frozen fp-23 decide().

    Returns the verdict dict augmented with provenance, the schema-floor
    result, the rate, and a task-level Wilson CI. Never alters the bar."""
    if checkpoint not in fp23.CHECKPOINTS:
        return {"verdict": "PROTOCOL-VIOLATION",
                "flag": f"unknown checkpoint {checkpoint!r}; "
                        f"fp-23 pins {fp23.CHECKPOINTS}"}

    # schema floor — a receipt missing any required field is not a probe.
    missing = fp23.validate_receipt(receipt)
    if missing:
        return {"verdict": "INVALID-RECEIPT",
                "missing_fields": missing,
                "flag": "fp-23 schema floor: every required field present "
                        "or the probe is not a probe"}

    # adapter-none assertion is load-bearing (the owned core is judged on
    # ITS OWN weights, never an adapter's lift).
    if not receipt.get("adapter_none_assert"):
        return {"verdict": "INVALID-RECEIPT",
                "flag": "adapter_none_assert is false/absent — a probe with "
                        "an adapter loaded does not measure the core"}

    # coarse token sanity (named checkpoint vs receipt's count)
    nominal = _CHECKPOINT_TOKENS[checkpoint]
    tok = receipt.get("checkpoint_tokens", 0)
    token_ok = abs(tok - nominal) <= _TOKEN_TOL * nominal

    verified = receipt.get("l1_verified_episodes", 0)
    minutes = receipt.get("l1_governed_minutes", 0)
    rate = fp23.floor_rate(verified, minutes)

    prior_fail = _prior_fail_at_2b(prior_2b_verdict)
    # a 4B leg with no recorded 2B outcome is out-of-protocol: the 2B probe
    # is mandatory before a 4B floor decision. Surface it rather than
    # silently treating "no prior" as "2B passed".
    if checkpoint == fp23.RETRY_CHECKPOINT and prior_2b_verdict is None \
            and rate is not None and rate < fp23.FLOOR_RATE:
        return {"verdict": "PROTOCOL-VIOLATION",
                "rate": rate, "bar": fp23.FLOOR_RATE,
                "flag": "4B floor leg without a recorded 2B verdict; the 2B "
                        "probe is mandatory (fp-23 decide() requires the "
                        "prior-2B outcome for the KILL branch)"}

    decision = fp23.decide(checkpoint, rate, prior_fail_at_2b=prior_fail)

    tasks_any = receipt.get("l1_tasks_any_verified", 0)
    tasks_total = receipt.get("l1_tasks_total", 0)
    wlo, whi = fp23.wilson_ci(tasks_any, tasks_total)

    out = dict(decision)
    out.update({
        "checkpoint": checkpoint,
        "rate_verified_per_governed_minute": rate,
        "floor_bar": fp23.FLOOR_RATE,
        "l1_verified_episodes": verified,
        "l1_governed_minutes": minutes,
        "task_any_verified": [tasks_any, tasks_total],
        "task_any_verified_wilson95": [round(wlo, 4), round(whi, 4)],
        "prior_2b_verdict": prior_2b_verdict,
        "prior_fail_at_2b": prior_fail,
        "checkpoint_tokens": tok,
        "token_sanity_ok": token_ok,
        "provenance": {
            "tokenizer_sha256": receipt.get("tokenizer_sha256"),
            "corpus_manifest_sha256": receipt.get("corpus_manifest_sha256"),
            "probe_set_sha256": receipt.get("probe_set_sha256"),
            "probe_seed": receipt.get("probe_seed"),
            "step": receipt.get("step"),
        },
    })
    if out.get("verdict") == "KILL":
        out["escalation"] = (
            "rung-kill fired: the blocker is owned-core SCALE. Escalate to "
            "the user per NC2-own rung-kill (his call: hardware/money vs "
            "0.1B-class fallback at ~19x margin vs world redesign). No third "
            "retry, no bar movement. The NC0 loop result stands either way.")
    return out


def _selftest():
    full = {f: 1 for f in fp23.RECEIPT_REQUIRED_FIELDS}
    full["adapter_none_assert"] = True
    full["checkpoint_tokens"] = 2_000_000_000
    full["l1_tasks_any_verified"] = 50
    full["l1_tasks_total"] = 100

    def rec(**kw):
        r = dict(full)
        r.update(kw)
        return r

    # 1B = INFO regardless of rate
    r = run_verdict("1B", rec(checkpoint_tokens=1_000_000_000,
                              l1_verified_episodes=2, l1_governed_minutes=10))
    assert r["verdict"] == "INFO", r

    # 2B PASS (rate >= 1.0)
    r = run_verdict("2B", rec(l1_verified_episodes=30, l1_governed_minutes=20))
    assert r["verdict"] == "PASS", r
    assert abs(r["rate_verified_per_governed_minute"] - 1.5) < 1e-9

    # 2B RETRY (rate < 1.0)
    r = run_verdict("2B", rec(l1_verified_episodes=10, l1_governed_minutes=20))
    assert r["verdict"] == "RETRY-AT-4B", r

    # 4B PASS (late-onset) — prior 2B failed
    r = run_verdict("4B", rec(checkpoint_tokens=4_000_000_000,
                              l1_verified_episodes=22, l1_governed_minutes=20),
                    prior_2b_verdict="RETRY-AT-4B")
    assert r["verdict"] == "PASS", r

    # 4B KILL — prior 2B failed AND 4B fails -> rung-kill + escalation text
    r = run_verdict("4B", rec(checkpoint_tokens=4_000_000_000,
                              l1_verified_episodes=4, l1_governed_minutes=20),
                    prior_2b_verdict="RETRY-AT-4B")
    assert r["verdict"] == "KILL", r
    assert "escalation" in r and "NC2-own" in r["escalation"]

    # 4B fail WITHOUT a recorded 2B verdict -> PROTOCOL-VIOLATION (mandatory
    # 2B probe), caught before decide()
    r = run_verdict("4B", rec(checkpoint_tokens=4_000_000_000,
                              l1_verified_episodes=4, l1_governed_minutes=20))
    assert r["verdict"] == "PROTOCOL-VIOLATION", r

    # schema floor: a missing field is INVALID-RECEIPT
    bad = rec()
    del bad["tokenizer_sha256"]
    r = run_verdict("2B", bad)
    assert r["verdict"] == "INVALID-RECEIPT" and \
        "tokenizer_sha256" in r["missing_fields"], r

    # adapter loaded -> INVALID-RECEIPT (core not measured)
    r = run_verdict("2B", rec(adapter_none_assert=False,
                              l1_verified_episodes=30, l1_governed_minutes=20))
    assert r["verdict"] == "INVALID-RECEIPT", r

    # zero governed minutes -> INCOMPUTABLE (via frozen decide())
    r = run_verdict("2B", rec(l1_verified_episodes=5, l1_governed_minutes=0))
    assert r["verdict"] == "INCOMPUTABLE", r

    # token sanity flag trips when the count is in the wrong decade
    r = run_verdict("2B", rec(checkpoint_tokens=10_000_000_000,
                              l1_verified_episodes=30, l1_governed_minutes=20))
    assert r["token_sanity_ok"] is False, r

    print("FP24_VERDICT_SELFTEST_PASS")


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint", required=True,
                    choices=list(fp23.CHECKPOINTS))
    ap.add_argument("--receipt", required=True,
                    help="real v0 checkpoint-probe receipt (fp-23 schema)")
    ap.add_argument("--prior-2b-verdict",
                    help="path to the 2B fp24-verdict receipt (required for a "
                         "4B floor decision; carries the prior-2B outcome)")
    a, _ = ap.parse_known_args()

    receipt = json.load(open(a.receipt, encoding="utf-8"))
    prior = None
    if a.prior_2b_verdict:
        pv = json.load(open(a.prior_2b_verdict, encoding="utf-8"))
        prior = pv.get("result", pv).get("verdict")

    result = run_verdict(a.checkpoint, receipt, prior_2b_verdict=prior)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_receipt = {"ticket": "FP24-VERDICT", "ts": ts,
                   "checkpoint": a.checkpoint,
                   "checkpoint_receipt": os.path.basename(a.receipt),
                   "prior_2b_verdict_source": (
                       os.path.basename(a.prior_2b_verdict)
                       if a.prior_2b_verdict else None),
                   "source_of_truth": "fp23_probe_prereg (frozen #135)",
                   "result": result}
    NC = os.path.dirname(HERE)
    out = f"{NC}/receipts/fp24-verdict-{a.checkpoint}-{ts}.json"
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out_receipt, f, indent=2)
    print(json.dumps(out_receipt, indent=2))
    print(f"FP24_VERDICT_DONE {out}")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        main()
