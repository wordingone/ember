# 15 — Technical Report

## How to read this report

This is a snapshot tied to the totality board render current at the time
this anatomy set was authored:
`scripts/ember_totality/receipts-totality/ember-totality-20260801T052815Z.json`
(41 conditions: 14 GREEN / 23 RED / 1 UNEVALUABLE / 3 AUDIT-OK,
`pct_complete: 36.8`). To get a FRESH snapshot rather than trust this
report's numbers as they age, run the totality runner
(`scripts/ember_totality/ember_totality_spec.py`, see 11_TOTALITY_BOARD_CONDITIONS.md
and 13_RUNBOOK.md) and read its newest receipt directly — this report is a
map to that receipt, not a replacement for reading it.

## Condition status at snapshot time (by doc section, not exhaustive)

- Authority/provenance (01, 10): `C-AUTHORITY` GREEN, `C-CUSTODY` GREEN, `C-INV` RED (24 unstamped post-genesis receipts)
- Model/training (03, 04): `C-BASE` RED (checkpoint bytes not visible), `C(-1)` RED (a disclosed field-contract regression — 3 receipts landed post-fix still missing `api_spend_usd`)
- Growth/scaling (05): `C-GROW` GREEN, `C-SCALE` RED (no candidate yet at the non-toy operating point)
- Evaluation (06): `C1` RED (hash-verify gap), `C2`/`C3`/`C6` GREEN, `C4`/`C5` RED (harness-interface reachability), `C7`/`C8` RED
- Governance (07, 11): `C-PORT` GREEN
- Cockpit (12): `C-OBS` RED (receipt-visibility gap over real, existing adapter code), `C-IND` RED (depends on C-OBS)
- Roll-ups: `C-MANIFEST` GREEN (docs/ember-completeness.md enumerates all 81 rows), `C-TALLY` RED by definition (a 38-way conjunction roll-up — GREEN requires every other STATE-condition GREEN first; see `docs/spec/conditions-v1.md` §4.3)

## H4 — verifier-free judgment (honest status)

`docs/hardest-problems-register-v1.md`'s H4 entry ("O6: verifier-free
judgment") is explicit: **"Status: OPEN, untouched, honestly not on the S5
critical path... named so the deferral is a recorded decision, not drift."**
This anatomy set does not claim H4 is solved — it isn't. What this set does
is the honest, weaker thing the register itself models: it NAMES where H4's
risk actually bears in the current architecture (03_MODEL_ARCHITECTURE.md's
expert-routing "explicit local episode declaration" is a designed
alternative to a learned/verifier-scored router; 06_EVALUATION_AND_BENCHMARKS.md's
whole anti-gaming C1–C5 protocol exists precisely because Ember routes every
certifiable gain through an external verifier today, per H4's own problem
statement) rather than letting the gap drift unrecorded across an anatomy
set that otherwise looks complete. Anyone reading `C-ANAT` GREEN alongside
this report should read this section as the load-bearing caveat: verifier-free
judgment remains H4's open problem, tracked in
`docs/hardest-problems-register-v1.md`, not resolved by this doc set.

## Current gaps — honestly stated

This report, and the anatomy set it summarizes, describe real, on-disk state
as of the cited board render. They make no claim beyond that: not
completion, not checkpoint existence, not benchmark scores, not that H4 is
solved. See `docs/spec/conditions-v1.md` §4.3-4.4 for what "GOAL SATISFIED"
actually requires and how far the current board is from it.
