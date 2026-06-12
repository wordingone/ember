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
| 6 | sp-3b audit tightenings before 06-20 (standing until window) | landed: @97418ec (row-8 tracking, kai flag 14869); #344 @0295667 (row-12 battery_sha256 field pin — spec-v1 content-hash binding enforced; row-10 gains spec-v1 doc); further gaps land the same way | Leo | #214 |
| 7 | ~~Registry PARK revival configs staged~~ DISCHARGED | fp8-revival-next-width-v1.json at repo30/ledger/; revival cond: K≥4096 sites → next-width config A/B; registry row PARK quoted. Receipt: ledger-row7-row10-20260612T140836Z.json | Eli | registry |
| 8 | ~~Receipt hygiene~~ DISCHARGED | PR #334 merged (LEGACY_EXEMPT 9 + sp6c fix; jude adversarial verify PASS; clean-tree repro 260/9/0) | Eli + jude | R2 |
| 9 | ~~fp-29 synthesis-window prep~~ DISCHARGED | PR #333 merged (sha 25a51c14… reproduced at gate) | Eli (Leo gated) | fp-29/#200 |
| 11 | ~~manifest closed-issues coverage sweep~~ DISCHARGED | C33-C40 credited; all 7 enumeration sources swept by 16:42Z — manifest denominator FULLY ENUMERATED (53→55 rows) | Leo | numeric closure |
| 12 | ~~manifest pointer fixes from jude's sweep~~ DISCHARGED | R1+R2 applied @e4d27ef/@de9e88e; jude receipt-minting round in flight (14886) | Leo | numeric closure |
| 13 | ~~B3 duty-battery spec freeze~~ DISCHARGED | docs/sp6b-duty-battery-spec-v1.md FROZEN (20 episodes, 6 verb classes, decoy guards, content-hash binding); jude adversarial pass queued pre-first-run | Leo | C55/#fp-33 |
| 14 | ~~GSM8K-200 harness issue~~ DISCHARGED (minted #341) | AC in issue: greedy determinism check, receipt schema, selftest fixtures, pinned data, governed; rides Eli queue after #340 | Leo mint / Eli build | C55/#fp-33 |
| 15 | ~~fp34 pre-stage~~ HALF-DISCHARGED: selftest PASS (Leo-run 16:48Z); freeze HELD — daemon check 16:55Z: NO 3B chain in flight (q3 chain COMPLETED 06-10, verdict all-zero on ARC, world moved to W-code; STATE line 146). Per fp34 prereg the freeze input = OWNED-core round-1 per-task stats, which exist only post-1B-checkpoint | trigger: owned-core-round-1-stats-receipt | Leo | C53 |
| 16 | ~~C52 scaffolding-off test spec freeze~~ DISCHARGED | docs/c52-scaffold-off-test-v1.md FROZEN: window bounds, scaffold-off attestations (founder-process + zero-cloud audit), scripted event injection reusing sp6b verb classes, 1 verified-gain micro-round via own-r1 receipt class, content-hash binding; jude adversarial pass before first run | Leo | C52 (GATED:C10,C13) |
| 10 | ~~Eli loop: cron turn-generator~~ DISCHARGED | cron-tick-prompt.md written at eli/state/; CronCreate :26 (GATE) + :56 (BUILD) wired; receipt: ledger-row7-row10-20260612T140836Z.json | Eli | loop-eng doc |

Standing row classes (refill sources when the table runs low): verdict-chain
dress rehearsals for any upcoming trigger; window prep for any dated item;
audit harness tightenings; registry revival staging; receipt hygiene;
founder-loop hardening. If all are exhausted, the (c)-receipt must say which
class was checked and why it yielded nothing.
