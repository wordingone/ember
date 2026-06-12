# Work-ahead ledger — pre-stageable work while triggers wait (est. 2026-06-12)

Per user directive 2026-06-12: the fleet never idles while planned work
exists. Every trigger-gated item has a pre-stageable half; this ledger
enumerates it as dispatchable units. The Leo BUILD tick (:41) consumes rows
top-down; each row names artifact + AC + owner. A row is removed when its
artifact merges (or its parent trigger fires and supersedes it). An empty
ledger is the only valid "nothing to build" — and emptying it is itself a
red flag to re-derive.

Posture (user, verbatim class): never "holding, stopping, because X" —
always "X is happening, moving on to Y while X happens."

| # | Row | Artifact + AC | Owner | Parent |
|---|-----|---------------|-------|--------|
| 1 | NC-K e2e live proof — avir-cli port has ZERO end-to-end receipt | #331: boot-checksum → mail consume → seat dispatch → CU verb → bound NCK-E2E receipt chain | Eli (Leo gates) | sp-5/#257 |
| 2 | 2B-verdict-chain dress rehearsal | synthetic 1B/2B probe receipts driven through fp24_verdict → fp29 gate → fp36b runbook end-to-end on a scratch receipts dir; receipt + any wiring break fixed BEFORE the real 1B (~step 244k, ~1 day) | Leo | #223/#328 |
| 3 | #208 probe-set reconciliation — fp-28b binds l1-probe-set-seed23 (91170123…) but checkpoint_probe uses its own frozen set (105fd370…) | decision note + Eli pre-stage: seed23 coverage eval RIDES the 1B checkpoint as a separate receipt; checkpoint_probe keeps 105fd370 for trajectory comparability | Leo decide / Eli stage | #208 |
| 4 | fp-36 Band-A pre-stage (both pre-protocol points are mute → Band A is the live branch) | 4B-leg logistics: probe dispatch template + RETRY-AT-4B plumbing dry-run receipt | Leo | #328 |
| 5 | sp-6b designation-window tooling dry-run (window 06-20..21) | b_run_designation.py + selftest exercised on synthetic inputs; receipts/sp6b-b-run-* naming convention verified vs sp-3 row 12 | Leo | #282 |
| 6 | sp-3b audit tightenings before 06-20 | any sp-3 harness gap found during rows 1-5 lands as a tightening PR pre-window | Leo | #214 |
| 7 | Registry PARK revival configs staged | fp35d K=4096 VIABLE → next-width config file staged (not wired); revival condition quoted from registry row | Eli | registry |
| 8 | Receipt hygiene: 10 receipts failing receipt_check sweep (legacy missing ticket/ts; sp6c-ember-shakedown-082026Z missing sha_convention) | triage: pre-R2 legacy = grandfather list in receipt_check; post-R2 = fix + re-emit | Leo | R2 |
| 9 | fp-29 synthesis-window prep (fires only on 2B RETRY, but the generator must exist BEFORE the window) | curriculum-generator dry-run on frozen L1/L2 grammar; episodes_manifest_sha256 shape conformance receipt | Eli (Leo gates) | fp-29/#200 |
| 10 | Eli loop: cron turn-generator (:26/:56 role-alternating) + WAIT-expiry re-derivation | his settings/loop config + a first build-tick receipt | Eli | loop-eng doc |

Standing row classes (refill sources when the table runs low): verdict-chain
dress rehearsals for any upcoming trigger; window prep for any dated item;
audit harness tightenings; registry revival staging; receipt hygiene;
founder-loop hardening. If all are exhausted, the (c)-receipt must say which
class was checked and why it yielded nothing.
