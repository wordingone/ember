"""fp20c_stability.py — pacing-fraction STABILITY band, FROZEN BEFORE the
round-3 sampling receipt exists (#146, successor to fp-20b #131).

fp-20b SETTLED the as-operated pacing fraction on the FIRST instrumented
w1 receipt: 0.2535 (36.5s/144.0s gen wall, all decode-pacer). eng-37/#136
wired the meter into w1_mbpp, so the fraction is now a free field on
EVERY instrumented w1 receipt. fp-20c asks the next question: is that
fraction STABLE across runs, or does it drift?

A drifting fraction is a GOVERNOR-CONFIG-CHANGED-CLASS DETECTOR. The
resource governor (VRAM-fraction cap + margin assert + decode pacer) is
mandatory, frozen policy. If the as-operated pacing fraction on the
round-3 sampling receipt moves materially off the fp-20b baseline, the
governor changed class — and if it changed WITHOUT a deviation record
(audit-§6 registry), that silent change is itself the finding. If it
holds, fp-9's "as operated" qualifier is receipted as a STABLE constant,
not a one-shot, and the multiplier-table pacing assumption is backed.

Same discipline as fp-15 / fp-23: the band that judges the round-3
receipt is FROZEN here, before that receipt exists, so it can never be
fitted to the number it judges.

FROZEN CONSTANTS — changing any after the round-3 sampling receipt
exists is a deviation (audit-§6 registry).

Band rationale (frozen, pre-data):
  - BASELINE = 0.2535 — fp-20b's SETTLED fraction on the same surface
    (sampling-generation wall), pinned verbatim, never recomputed.
  - STABILITY_BAND_ABS = 0.10 — |frac_r3 - BASELINE| <= 0.10 -> STABLE.
    The decode pacer fires on a per-token cadence, so the FRACTION is
    roughly invariant to task-mix and generated-length variation
    (more tokens -> proportionally more pacer sleeps -> ~same fraction).
    0.10 absolute (~40% relative) absorbs that run-to-run mix variation
    while still catching a governor CLASS change (pacer rate-target
    change, VRAM-fraction change forcing a batch-size change, pacer
    disabled), which moves the fraction by far more than 0.10.
  - SANITY band 0.0 < frac < 0.50 inherited from fp-20b: a governed
    sampler at literally 0% or >50% sleeping is an instrumentation fault
    regardless of the baseline.

Decision (frozen):
  - frac outside (0.0, 0.50)            -> INSTRUMENTATION-FLAG (fp-20b
                                           sanity floor; meter fault).
  - |frac - BASELINE| <= BAND           -> STABLE (governor constant;
                                           fp-9 qualifier receipted stable).
  - |frac - BASELINE| >  BAND           -> DRIFT-FLAG: reconcile against
                                           the governor config diff. A
                                           drift with a RECORDED config
                                           change is benign-explained; an
                                           UNEXPLAINED drift escalates as
                                           an approach-change deviation
                                           (silent governor change = gate
                                           violation, break-the-wall floor).

`--selftest` is pure-logic. main() without a round-3 receipt prints the
STAGED sentinel — running the verdict before the receipt exists would
un-freeze the band. fp-20c executes the verdict on the real round-3
sampling receipt.
"""
import json
import os
import sys
from datetime import datetime, timezone

# ---- frozen pins ----------------------------------------------------
BASELINE = 0.2535          # fp-20b SETTLED fraction (same surface), pinned
STABILITY_BAND_ABS = 0.10  # |frac - BASELINE| <= this -> STABLE
SANITY_LO = 0.0            # inherited from fp-20b
SANITY_HI = 0.50


def fraction_of(w1):
    """Pacing fraction on the SAME convention as fp20b_settle.settle():
    pacing_total_s / gen_secs, meter accumulating only inside the
    generation phase. Returns (frac, flag) — frac is None when the
    receipt cannot yield one."""
    pacing = w1.get("pacing")
    if not pacing:
        return None, "receipt carries no pacing block (pre-#136 w1?)"
    gen = w1.get("gen_secs")
    if not gen or gen <= 0:
        return None, "no gen_secs"
    total = pacing.get("pacing_total_s", 0.0)
    return total / gen, None


def decide(frac):
    """STABLE / DRIFT-FLAG / INSTRUMENTATION-FLAG — the frozen procedure."""
    if frac is None:
        return {"verdict": "INCOMPUTABLE", "flag": "no fraction"}
    if not (SANITY_LO < frac < SANITY_HI):
        return {"verdict": "INSTRUMENTATION-FLAG",
                "frac": round(frac, 4),
                "flag": f"outside sanity band ({SANITY_LO},{SANITY_HI})"}
    delta = abs(frac - BASELINE)
    if delta <= STABILITY_BAND_ABS:
        return {"verdict": "STABLE", "frac": round(frac, 4),
                "baseline": BASELINE, "delta_abs": round(delta, 4),
                "band_abs": STABILITY_BAND_ABS,
                "note": ("governor constant across runs; fp-9 as-operated "
                         "qualifier receipted as a stable constant")}
    return {"verdict": "DRIFT-FLAG", "frac": round(frac, 4),
            "baseline": BASELINE, "delta_abs": round(delta, 4),
            "band_abs": STABILITY_BAND_ABS,
            "note": ("fraction drifted off baseline beyond band; reconcile "
                     "against the governor config diff. RECORDED config "
                     "change -> benign-explained; UNEXPLAINED -> escalate "
                     "as an approach-change deviation (silent governor "
                     "change = gate violation)")}


def _selftest():
    # exact baseline -> STABLE
    assert decide(0.2535)["verdict"] == "STABLE", decide(0.2535)
    # within band (edge inside) -> STABLE
    assert decide(BASELINE + 0.099)["verdict"] == "STABLE"
    assert decide(BASELINE - 0.099)["verdict"] == "STABLE"
    # just outside band -> DRIFT-FLAG (and still inside sanity)
    d = decide(BASELINE + 0.12)
    assert d["verdict"] == "DRIFT-FLAG", d
    assert SANITY_LO < d["frac"] < SANITY_HI
    # governor class-change: pacer disabled -> ~0 -> INSTRUMENTATION-FLAG
    assert decide(0.0)["verdict"] == "INSTRUMENTATION-FLAG"
    # >50% sleeping -> INSTRUMENTATION-FLAG (precedes drift check)
    assert decide(0.62)["verdict"] == "INSTRUMENTATION-FLAG"
    # incomputable
    assert decide(None)["verdict"] == "INCOMPUTABLE"
    # fraction extraction mirrors fp20b convention
    f, flag = fraction_of({"gen_secs": 144.0,
                           "pacing": {"pacing_total_s": 36.5}})
    assert flag is None and abs(f - 0.2535) < 1e-3, (f, flag)
    f2, flag2 = fraction_of({"gen_secs": 100.0})
    assert f2 is None and "pacing" in flag2
    # cross-check: re-deciding fp-20b's own number is STABLE by construction
    assert decide(fraction_of({"gen_secs": 144.0,
                  "pacing": {"pacing_total_s": 36.5}})[0])["verdict"] == \
        "STABLE"
    print("FP20C_STABILITY_SELFTEST_PASS")


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--w1", help="round-3 instrumented w1/sampling receipt")
    a, _ = ap.parse_known_args()
    if not a.w1:
        print("FP20C_STABILITY_STAGED (no round-3 sampling receipt exists "
              "yet; band frozen in this file — fp-20c runs the verdict when "
              "the round-3 instrumented receipt lands)")
        return
    w1 = json.load(open(a.w1, encoding="utf-8"))
    frac, flag = fraction_of(w1)
    result = decide(frac)
    if flag:
        result.setdefault("flag", flag)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt = {"ticket": "FP20C-STABILITY", "ts": ts,
               "w1_receipt": os.path.basename(a.w1),
               "baseline_source": "fp-20b SETTLED (fp20b-settle-*, 0.2535)",
               "result": result}
    NC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out = f"{NC}/receipts/fp20c-stability-{ts}.json"
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(receipt, f, indent=2)
    print(json.dumps(receipt, indent=2))
    print(f"FP20C_STABILITY_DONE {out}")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        main()
