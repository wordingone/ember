#!/usr/bin/env python
"""c04_pick_rehearsal.py - verdict-chain dress rehearsal (ledger standing
class): the c04-pick-decision-table-v1 routing as EXECUTABLE logic, tested
against synthetic receipt fixtures BEFORE live receipts land. Eli's verdict
script imports route() so the doc and the code cannot drift.

Cells quote docs/c04-pick-decision-table-v1.md @0524545 verbatim-class.
"""
import argparse, json, time

ANCHOR_TOK_S = 19228.0          # fp39b b16-ckpt-compile-prod (receipted)
GOV_DAY_S = 86400
CURATED_BUDGET = (2.0e9, 2.5e9) # fp-38 c03-class curated band
BULK_BUDGET = 5.69e9            # Chinchilla-default at c03-class P (ESTIMATE flag inherited)

def l10_tok_s(l10):
    """Projected tok/s by L10 outcome (decision-table axis 1)."""
    return {"FULL": (25600.0, 28800.0), "PART": (22300.0, 22300.0),
            "FAIL": (ANCHOR_TOK_S, ANCHOR_TOK_S)}[l10]

def route(l10, density, budget_hi=None):
    """(L10 outcome, density verdict) -> decision cell. Mirrors the table.
    budget_hi overrides the curated band's top end (the PASS cell's internal
    budget cap — corner finding below)."""
    lo_ts, hi_ts = l10_tok_s(l10)
    budget = CURATED_BUDGET if density == "D-CONF" else (BULK_BUDGET, BULK_BUDGET)
    if budget_hi is not None:
        budget = (budget[0], budget_hi)
    # governed days at the WORST end of the projection band (honest side)
    days = budget[1] / (lo_ts * GOV_DAY_S)
    if density == "D-BELOW":
        return {"cell": "FAIL->4.5-residual", "days": round(days, 2),
                "action": "present priced residual (2nd GPU / cloud burst / priced waiver); never relax silently"}
    if l10 == "FULL" and days <= 1.05:   # 1.0d cell, 5% measurement tolerance
        return {"cell": "PASS", "days": round(days, 2),
                "action": "c03-class x curated budget -> #3 receipt -> gate-9 -> pretrain dispatches"}
    return {"cell": "MARGINAL->user-fraction-call", "days": round(days, 2),
            "action": "present wall-day fraction to the user; only he relaxes the <=1-day bar"}

def selftest():
    # CORNER FINDING (the rehearsal's first catch, pre-live-receipts): at the
    # band's worst corner (2.5B budget / 25.6k tok/s) L10-FULL x D-CONF is
    # 1.13d = MARGINAL, not PASS. The table's "~1.0 day" PASS cell carries an
    # INTERNAL BUDGET CAP: budget <= 1.05 x measured tok/s x 86400 (=2.2B at
    # the low end). Decision table v1.1 records this; verdict scripts must
    # apply the cap, not the band top.
    corner = route("FULL", "D-CONF")
    assert corner["cell"].startswith("MARGINAL") and corner["days"] == 1.13, corner
    capped = route("FULL", "D-CONF", budget_hi=2.2e9)
    assert capped["cell"] == "PASS" and capped["days"] <= 1.05, capped
    assert route("PART", "D-CONF")["cell"].startswith("MARGINAL")
    assert route("FAIL", "D-CONF")["cell"].startswith("MARGINAL")
    for l10 in ("FULL", "PART", "FAIL"):
        assert route(l10, "D-BELOW")["cell"] == "FAIL->4.5-residual"
    # residual days at bulk budget vs anchor ~= 3.4d (table's FAIL row)
    assert 3.3 < route("FAIL", "D-BELOW")["days"] < 3.5
    print("C04_PICK_REHEARSAL_PASS — corner finding: PASS cell needs budget<=2.2B "
          "if L10 lands at the low end (25.6k); table amended")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--emit", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        selftest(); return
    out = {"ticket": "C04-PICK-REHEARSAL", "ts": time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()),
           "routes": {f"{l}x{d}": route(l, d) for l in ("FULL", "PART", "FAIL")
                      for d in ("D-CONF", "D-BELOW")},
           "corner_finding": "PASS at L10-FULL-low (25.6k tok/s) requires budget<=2.2B; "
                             "at 2.5B it is 1.13d = MARGINAL — decision table v1.1 records this"}
    s = json.dumps(out, indent=1)
    print(s[:1200])
    if a.emit:
        p = "receipts/c04-pick-rehearsal-%s.json" % out["ts"]
        open(p, "w").write(s)
        print("RECEIPT:", p)

if __name__ == "__main__":
    main()
