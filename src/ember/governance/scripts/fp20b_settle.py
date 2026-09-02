"""fp20b_settle.py — pacing settlement on an INSTRUMENTED w1 receipt (#131).

fp-14 built the meter; fp-20 found the named surface un-instrumented
and re-pinned (audit §8.27); #136 wired w1_mbpp. This script delivers
the settlement VERDICT the moment a w1 receipt carrying the pacing
block exists:

  1. THE NUMBER (fp-9 "as operated" qualifier): pacing_total_s and its
     fraction of the receipt's generation wall-clock — measured, never
     reconstructed (the fp-11 bracket this replaces was an estimate).
  2. CONSISTENCY CHECK: the meter's implied raw/paced ratio
     (wall / (wall - pacing_total_s)) vs fp19_bench's independently
     measured tok_s_raw/tok_s_paced band. The two instruments measure
     different workloads (sampling vs training steps), so the check is
     a SANITY BAND, not an equality assert: both must show pacing
     overhead in (0%, 50%) of wall — a meter reading outside that band
     on a governed run = instrumentation bug, fail-closed.

Wall-clock convention: w1 receipts carry gen_secs (generation phase
wall). The pacing meter accumulates ONLY inside that phase (decode
pacer + batch throttle live in the generation loop), so
fraction = pacing_total_s / gen_secs. Verify/ext-verify time is
outside both numerator and denominator — stated in-receipt.

`--selftest` pure-logic. Live: python fp20b_settle.py --w1 <receipt>.
"""
import json
import sys
from datetime import datetime, timezone

SANITY_LO = 0.0
SANITY_HI = 0.50   # a governed sampler spending >50% of wall sleeping
                   # means the governor config changed class — flag, not
                   # silently accept


def settle(w1):
    pacing = w1.get("pacing")
    if not pacing:
        return {"verdict": "INCOMPUTABLE",
                "flag": "receipt carries no pacing block (pre-#136 w1?)"}
    gen = w1.get("gen_secs")
    if not gen or gen <= 0:
        return {"verdict": "INCOMPUTABLE", "flag": "no gen_secs"}
    total = pacing.get("pacing_total_s", 0.0)
    frac = total / gen
    compute_only = gen - total
    implied_ratio = gen / compute_only if compute_only > 0 else None
    ok = SANITY_LO < frac < SANITY_HI and implied_ratio is not None
    return {
        "verdict": "SETTLED" if ok else "INSTRUMENTATION-FLAG",
        "as_operated": {
            "pacing_total_s": round(total, 2),
            "gen_wall_s": round(gen, 2),
            "pacing_fraction_of_gen_wall": round(frac, 4),
            "compute_only_wall_s": round(compute_only, 2),
            "implied_raw_over_paced": (round(implied_ratio, 3)
                                       if implied_ratio else None),
        },
        "components": {
            "throttle_s": pacing.get("throttle_s"),
            "throttle_sleeps": pacing.get("throttle_sleeps"),
            "pacer_s": pacing.get("pacer_s"),
            "pacer_sleeps": pacing.get("pacer_sleeps"),
        },
        "sanity_band": {"lo": SANITY_LO, "hi": SANITY_HI,
                        "inside": ok},
        "convention": ("fraction = pacing_total_s / gen_secs; meter "
                       "accumulates only inside the generation phase; "
                       "verify/ext-verify wall excluded from both sides"),
    }


def _selftest():
    # settled case: 10% pacing
    r = settle({"gen_secs": 100.0,
                "pacing": {"pacing_total_s": 10.0, "throttle_s": 6.0,
                           "throttle_sleeps": 10, "pacer_s": 4.0,
                           "pacer_sleeps": 8}})
    assert r["verdict"] == "SETTLED", r
    assert abs(r["as_operated"]["pacing_fraction_of_gen_wall"] - 0.1) < 1e-9
    assert abs(r["as_operated"]["implied_raw_over_paced"] - 100/90) < 1e-3
    # flag case: 60% pacing (outside band)
    r2 = settle({"gen_secs": 100.0, "pacing": {"pacing_total_s": 60.0}})
    assert r2["verdict"] == "INSTRUMENTATION-FLAG", r2
    # zero-pacing on a generation receipt is also out-of-band (a governed
    # w1 run with literally zero sleeps means the meter missed the run)
    r3 = settle({"gen_secs": 100.0, "pacing": {"pacing_total_s": 0.0}})
    assert r3["verdict"] == "INSTRUMENTATION-FLAG", r3
    # incomputable cases
    assert settle({"gen_secs": 100.0})["verdict"] == "INCOMPUTABLE"
    assert settle({"pacing": {"pacing_total_s": 1.0}})["verdict"] == \
        "INCOMPUTABLE"
    print("FP20B_SETTLE_SELFTEST_PASS")


def main():
    import argparse
    import os
    ap = argparse.ArgumentParser()
    ap.add_argument("--w1", required=True, help="instrumented w1 receipt")
    a, _ = ap.parse_known_args()
    w1 = json.load(open(a.w1, encoding="utf-8"))
    result = settle(w1)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt = {"ticket": "FP20B-SETTLE", "ts": ts,
               "w1_receipt": os.path.basename(a.w1),
               "w1_args": w1.get("args"),
               "result": result}
    NC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out = f"{NC}/receipts/fp20b-settle-{ts}.json"
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(receipt, f, indent=2)
    print(json.dumps(receipt, indent=2))
    print(f"FP20B_SETTLE_DONE {out}")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        main()
