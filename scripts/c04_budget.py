#!/usr/bin/env python
"""c04_budget.py - fp-38 (#355): c04-v0 required token budget vs the
<=1-governed-day criterion - the budget half of the joint constraint.

Consumes the fp-37 grid receipt (receipt-chained, not re-derived). For each
flash/no-ckpt candidate it prices the budget side: what the criterion AFFORDS
in one governed day, what the bulk default (Chinchilla-class) would DEMAND,
and the curated-density multiplier required to close the gap. Every constant
is receipt-pinned or ESTIMATE-flagged. Recalibrates on the measured L9 F via
--f-sustained (fp-39 consumes that).
"""
import argparse, json, os, time

CONSTANTS = {
    # receipt-pinned
    "grid_receipt": "receipts/c04-grid-20260612T220829Z.json",
    "owned_stream_tokens": 6_977_868_758,   # token-shards-v0-20260611T170047Z.json total_stream_tokens
    "governed_day_s": 86400,
    "mde_pp": {                              # power-helper receipts, p0=2%, alpha .05, power .8
        100: 0.101634,                       # power-helper-20260612T210637Z.json
        400: 0.03846,                        # power-helper-20260612T210645Z.json
    },
    # ESTIMATE-flagged (literature defaults; no local receipt exists)
    "chinchilla_tok_per_param": 20.0,        # ESTIMATE - Hoffmann et al. 2022 compute-optimal ratio
    "max_fresh_epochs": 4.0,                 # ESTIMATE - Muennighoff et al. data-constrained scaling
    # empirical floor anchor (the only local density datapoint, negative):
    # c03-class run at ~3B bulk-weighted tokens produced W-code floors of
    # 0-2/100 successes (H2 register; q15 round-1 0.0% all arms). Bulk
    # density at that budget is FLOOR-MARGINAL - the multiplier column below
    # is therefore an obligation, not an optimization.
}

def load_rows(path):
    d = json.load(open(path))
    rows = [r for r in d["grid_flash"] if r["mode"] == "nockpt"]
    return rows, d["sustained_flops_anchor"]

def price(rows, f_scale=1.0):
    c = CONSTANTS
    out = []
    for r in rows:
        p = r["params_m"] * 1e6
        tok_s = r["proj_tok_s"] * f_scale
        afford_1d = tok_s * c["governed_day_s"]
        chin = c["chinchilla_tok_per_param"] * p
        out.append({
            "h": r["h"], "d": r["d"], "params_m": r["params_m"],
            "B_knee": r["B_knee"], "proj_tok_s": round(tok_s),
            "afford_1day_b": round(afford_1d / 1e9, 3),
            "tok_per_param_1day": round(afford_1d / p, 1),
            "chinchilla_b": round(chin / 1e9, 2),
            "density_mult_required": round(chin / afford_1d, 2),
            "days_at_chinchilla": round(chin / afford_1d, 2),  # = mult, since afford_1d is 1 day
            "epochs_of_owned_at_1day": round(afford_1d / c["owned_stream_tokens"], 3),
        })
    return out

def selftest():
    rows, F = load_rows(CONSTANTS["grid_receipt"])
    t = price(rows)
    c03 = next(x for x in t if x["h"] == 1024)
    assert abs(c03["afford_1day_b"] - 3.51) < 0.02, c03
    assert abs(c03["chinchilla_b"] - 5.69) < 0.02, c03
    assert abs(c03["density_mult_required"] - 1.62) < 0.03, c03
    h2048 = next(x for x in t if x["h"] == 2048 and x["d"] == 12)
    assert abs(h2048["density_mult_required"] - 8.98) < 0.1, h2048
    # multiplier grows with params (the joint constraint tightens as P grows)
    mults = [x["density_mult_required"] for x in sorted(t, key=lambda x: x["params_m"])]
    assert mults == sorted(mults), mults
    # data side never binds before compute side (all <4 fresh epochs)
    assert all(x["epochs_of_owned_at_1day"] < CONSTANTS["max_fresh_epochs"] for x in t)
    print("C04_BUDGET_SELFTEST_PASS  (c03: afford=%.2fB mult=%.2f; h2048d12 mult=%.2f)"
          % (c03["afford_1day_b"], c03["density_mult_required"], h2048["density_mult_required"]))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--emit", action="store_true")
    ap.add_argument("--f-sustained", type=float, default=None,
                    help="override sustained FLOPS (measured L9 F) - scales all tok/s")
    a = ap.parse_args()
    if a.selftest:
        selftest(); return
    rows, F = load_rows(CONSTANTS["grid_receipt"])
    scale = (a.f_sustained / F) if a.f_sustained else 1.0
    out = {"ticket": "FP-38", "ts": time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()),
           "issue": 355, "constants": {k: v for k, v in CONSTANTS.items()},
           "f_sustained_used": F * scale, "f_scale": scale,
           "table": price(rows, scale),
           "reading": ("density_mult_required = Chinchilla-default tokens / 1-day affordable "
                       "tokens. The empirical anchor (3B bulk tokens -> floor-marginal) means "
                       "the multiplier is an OBLIGATION on curriculum density, receipt-checkable "
                       "only by a density A/B (curated vs bulk at matched FLOPs)")}
    s = json.dumps(out, indent=1)
    print(s[:1800])
    if a.emit:
        p = "receipts/c04-budget-%s.json" % out["ts"]
        open(p, "w").write(s)
        print("RECEIPT:", p)

if __name__ == "__main__":
    main()
