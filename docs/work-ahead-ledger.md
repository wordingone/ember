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
| 1 | ~~NC-K e2e live proof~~ DISCHARGED | PR #332 open awaiting Leo gate (boot-checksum→mail→seat→CU→bound NCK-E2E receipt, all stages PASS) | Eli | sp-5/#257 |
| 2 | ~~2B-verdict-chain dress rehearsal~~ DISCHARGED | jude receipt fp24-rehearsal-20260612T143500Z + PR #336 merged (all 6 chains PASS) | jude + Eli | #223/#328 |
| 3 | ~~#208 probe-set reconciliation~~ DISCHARGED | PR #338 merged (closes #208): checkpoint_probe keeps 105fd370, seed23 rides 1B as separate fp28 coverage pass | Leo decide / Eli stage | #208 |
| 4 | ~~fp-36 Band-A pre-stage~~ DISCHARGED | plumbing dry-run = #336 chains B/E (merged); dispatch template = docs/band-a-4b-dispatch-template.md | Leo | #328 |
| 5 | ~~sp-6b designation-window tooling dry-run~~ DISCHARGED | receipts/sp6b-tooling-dryrun-20260612T155736Z.json (Haiku agent, Leo-gated @97418ec): selftest 7/7, synthetic dry-run exit 0, b-run-designation-* naming matches audit row 12; sp6b-b-run-* comes from replay_rig at B3 time | Leo | #282 |
| 6 | sp-3b audit tightenings before 06-20 (standing until window) | first tightening landed @97418ec: selftest tracks row-8 RECEIPTED (kai flag 14869); further gaps found pre-window land the same way | Leo | #214 |
| 7 | ~~Registry PARK revival configs staged~~ DISCHARGED | fp8-revival-next-width-v1.json at repo30/ledger/; revival cond: K≥4096 sites → next-width config A/B; registry row PARK quoted. Receipt: ledger-row7-row10-20260612T140836Z.json | Eli | registry |
| 8 | ~~Receipt hygiene~~ DISCHARGED | PR #334 merged (LEGACY_EXEMPT 9 + sp6c fix; jude adversarial verify PASS; clean-tree repro 260/9/0) | Eli + jude | R2 |
| 9 | ~~fp-29 synthesis-window prep~~ DISCHARGED | PR #333 merged (sha 25a51c14… reproduced at gate) | Eli (Leo gated) | fp-29/#200 |
| 11 | manifest closed-issues coverage sweep | every closed ember issue mapped to a manifest row or recorded no-new-piece; tally credits receipted DONE rows | Leo | numeric closure |
| 12 | manifest pointer fixes from jude's sweep | every PART/DONE row pointer resolves to a file (jude receipt pending, mail 14863) | Leo | numeric closure |
| 10 | ~~Eli loop: cron turn-generator~~ DISCHARGED | cron-tick-prompt.md written at eli/state/; CronCreate :26 (GATE) + :56 (BUILD) wired; receipt: ledger-row7-row10-20260612T140836Z.json | Eli | loop-eng doc |

Standing row classes (refill sources when the table runs low): verdict-chain
dress rehearsals for any upcoming trigger; window prep for any dated item;
audit harness tightenings; registry revival staging; receipt hygiene;
founder-loop hardening. If all are exhausted, the (c)-receipt must say which
class was checked and why it yielded nothing.
