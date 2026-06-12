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
        (16, True,  "OOM",  "fp38c-l9-eager-20260612T231505Z b16-nockpt-flash-eager (decisive row, consumed)"),
        (8,  True,  "FIT",  "fp38c-l9-eager-20260612T231505Z b8-nockpt-flash-eager OK 27894.6 tok/s (bench-path)"),
    ],
    "pending_cells": [(8, True)],   # production-stack b8-flash (MTP activations) — mail 15082 rider
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
    # v2 (fp38c rows consumed): b16-flash OOM is the binding lower bound ~48.9
    # (the row the v1 emission predicted DECISIVE at 45.6 — confirmed, OOM side);
    # b8-flash FIT is the binding upper bound ~97.9. Grid's 20 B/unit excluded.
    assert 47.0 < lo < 51.0, lo
    assert lo > 20.0, "grid constant 20 B/unit must be OUTSIDE the interval"
    assert 95.0 < hi < 100.0, hi
    assert lo < hi, (lo, hi)   # observations stay mutually consistent
    # no-ckpt knee at the refit interval: B=8 fits, B=16 does not -> knee in [8,16)
    assert decisions(lo, hi), "pending production-b8 cell must be enumerated"
    print("ACT_REFIT_SELFTEST_PASS  (a in (%.1f, %.1f) B/unit; grid's 20 excluded; "
          "v1 decisive-cell prediction confirmed by fp38c)" % (lo, hi))

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
