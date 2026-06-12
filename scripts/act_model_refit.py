#!/usr/bin/env python
"""act_model_refit.py - leg-2 pre-stage (fp-39): refit the activation-memory
model against MEASURED OOM/fit rows after fp38-l9 falsified the grid's
20 B/unit assumption.

Model: act_noflash(B) = a*B*S*h*d + scores(B); act_flash(B) = a*B*S*h*d,
scores(B) = 2 bytes * B*heads*S^2*d * 2 (scores+probs, bf16 - grid model).
Solve the feasible interval for `a` (bytes per B*S*h unit per layer) from
every receipted observation; emit which pending cells narrow it and the
per-(B, mode) decision table. Consumes new receipts by re-run + re-emit.
"""
import argparse, json, time

GIB = 2 ** 30
C = {
    # geometry (c03, receipt-pinned in c04-grid)
    "h": 1024, "d": 20, "heads": 16, "S": 1024,
    # budget (governor receipts): 24*0.80 - 1.5 margin - static(weights+grads+opt)
    "gov_cap_gib": 24.0 * 0.80, "margin_gib": 1.5,
    "static_gib": 2.41,   # 4B*(P) w+g + muon 4B*core + adamw 8B*emb (c04_grid formulas)
    # observations: (B, flash, outcome) - outcome FIT|OOM, each receipt-pinned
    "obs": [
        (4,  False, "FIT",  "12c050e7 ran no-ckpt B=4 (configs/v0-pretrain-config.json)"),
        (16, False, "OOM",  "fp32-step-econ-20260612T213856Z b16-nockpt SKIPPED-OOM"),
        (26, True,  "OOM",  "fp38-l9-flash-ab-20260612T223639Z b26-nockpt-flash"),
        (33, True,  "OOM",  "fp38-l9-flash-ab-20260612T223639Z b33-nockpt-flash"),
        (39, True,  "OOM",  "fp38-l9-flash-ab-20260612T223639Z b39-nockpt-flash"),
    ],
    "pending_cells": [(16, True), (8, True)],   # eli completion cells (mail 15078)
}

def budget_bytes():
    return (C["gov_cap_gib"] - C["margin_gib"] - C["static_gib"]) * GIB

def units(B):
    return B * C["S"] * C["h"] * C["d"]

def scores_bytes(B):
    return 2.0 * B * C["heads"] * C["S"] ** 2 * C["d"] * 2

def interval():
    """Feasible (a_lo, a_hi) in bytes/unit from all observations."""
    lo, hi, rows = 0.0, float("inf"), []
    for B, flash, outcome, src in C["obs"]:
        thresh = (budget_bytes() - (0 if flash else scores_bytes(B))) / units(B)
        if outcome == "OOM":   # act > budget  ->  a > thresh
            lo = max(lo, thresh)
        else:                  # a <= thresh
            hi = min(hi, thresh)
        rows.append({"B": B, "flash": flash, "outcome": outcome,
                     "a_threshold": round(thresh, 1), "src": src})
    return lo, hi, rows

def decisions(lo, hi):
    out = []
    for B, flash in C["pending_cells"]:
        t = (budget_bytes() - (0 if flash else scores_bytes(B))) / units(B)
        if t < lo:    verdict = "PREDICT-OOM (threshold below feasible interval)"
        elif t > hi:  verdict = "PREDICT-FIT"
        else:         verdict = "DECISIVE - outcome splits the interval at a=%.1f" % t
        out.append({"B": B, "flash": flash, "a_threshold": round(t, 1),
                    "verdict": verdict})
    return out

def selftest():
    lo, hi, _ = interval()
    # b26-flash OOM forces a > ~30 (vs the falsified 20 B/unit grid constant)
    assert 29.0 < lo < 32.0, lo
    assert lo > 20.0, "grid constant 20 B/unit must be OUTSIDE the interval"
    # b4-noflash FIT gives the (weak) upper bound ~134
    assert 120.0 < hi < 150.0, hi
    d = decisions(lo, hi)
    b16 = next(x for x in d if x["B"] == 16)
    assert "DECISIVE" in b16["verdict"], b16   # b16-flash splits the interval
    print("ACT_REFIT_SELFTEST_PASS  (a in (%.1f, %.1f) B/unit; grid's 20 excluded; "
          "b16-flash decisive)" % (lo, hi))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--emit", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        selftest(); return
    lo, hi, rows = interval()
    out = {"ticket": "FP-39-ACT-REFIT", "ts": time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()),
           "issue": 359, "constants": C, "budget_gib": round(budget_bytes() / GIB, 2),
           "a_interval_bytes_per_unit": [round(lo, 1), round(hi, 1)],
           "grid_constant_falsified": 20.0,
           "observation_rows": rows, "pending_cell_decisions": decisions(lo, hi),
           "reading": ("no-ckpt knee for ANY candidate = solve a*units(B) <= budget at the "
                       "refit a; until b16/b8-flash land, use a_lo (optimistic bound) and "
                       "label knees PROVISIONAL")}
    s = json.dumps(out, indent=1)
    print(s[:1500])
    if a.emit:
        p = "receipts/act-refit-%s.json" % out["ts"]
        open(p, "w").write(s)
        print("RECEIPT:", p)

if __name__ == "__main__":
    main()
