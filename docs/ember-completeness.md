# Ember completeness manifest (est. 2026-06-12, per user numeric-closure directive)

One row per planned/known piece of ember. The tally script
(`scripts/ember_tally.py`, issue pending — eng) walks this table, verifies
each receipt exists and passes its named check, and emits
`receipts/tally-<ts>.json` {total, implemented, pct, missing[]}. Status here
is advisory; the tally receipt is the authority. A planned piece missing
from this manifest is a gate violation — planning = manifest entry.

Statuses: DONE (receipt verified), PART (receipt exists, AC partially
covered), OPEN (no receipt), GATED:<trigger> (blocked on a named trigger).

| id | subgoal | piece | AC / test | receipt | status |
|----|---------|-------|-----------|---------|--------|
| C1 | S1 | from-scratch pretrain run (12c050e7 lineage) | run completes; checkpoints cadence receipts | checkpoint receipts | PART (run live, step-100000) |
| C2 | S1 | NC2-own component contract (QAT/ternary/sub-quadratic/MTP/small-core) | each component has an executed receipt or registry verdict | docs/technique-registry.md rows | PART |
| C3 | S1 | fused Muon NS5 kernel A/B | governed bench receipt; ns5_equiv_check PASS | pending #329 (MSVC install) | GATED:#329 |
| C4 | S2 | verified-episode ledger (L1) | episodes pass verifier; manifest sha-bound | l1 episode receipts | PART |
| C5 | S2 | three-test gain gate (transfer/control/deletion) | gate script + one full gated gain | fp-24/fp-24b receipts | PART |
| C6 | S2 | self-curriculum generator | dry-run on frozen L1/L2 grammar; manifest-sha conformance | ledger row 9 (Eli) | OPEN |
| C7 | S2 | 1B/2B/4B protocol verdict chain (fp-23/fp-29/fp-36) | dress-rehearsal receipt pre-1B | ledger row 2 (jude, mail 14830) | OPEN |
| C8 | S3 | avir-cli clean-room port = visible harness | NCK-E2E proof chain all-PASS | nck-e2e-proof-20260612T142318Z | PART (PR #332 at gate) |
| C9 | S3 | ember mailbox identity | founders.yaml entry; live mail consume | merged (#259) + #332 stage 3 | PART |
| C10 | S3 | resident event loop (mail/files/receipts/schedule) | resident runs; event→action receipts | — | OPEN |
| C11 | S3 | CU communicability (user+Leo can interact) | CU console echo stage + interactive session receipt | #332 stage 5 (echo only) | PART |
| C12 | S3 | self-editing harness behind invariant gate | harness-edit artifact: branch→receipts→promote; deletion test | — | OPEN |
| C13 | S4 | cross-session persistence of gains | yesterday's gain measurably load-bearing today (receipt) | — | OPEN |
| C14 | S5 | fp-33 paired-protocol freeze | protocol doc frozen pre-verdict | fp-33 | PART |
| C15 | S5 | E2B-in-ember-seat baseline | E2B swapped into same harness, same worlds, governed | — | GATED:C8,C10 |
| C16 | S5 | surpass receipts (both legs) | ember > E2B: ember-work + founder-likeness | — | GATED:C15 |
| C17 | S6 | five un-removable invariants in code | protected paths + boot-time checksum verify | #332 stage 1 (boot_checksum) | PART |
| C18 | S6 | resource governor on every job | VRAM frac + margin assert + pacer receipts | governed-launch receipts | DONE |
| C19 | S2 | probe-set reconciliation (seed23 vs checkpoint_probe) | decision note + seed23 ride receipt | ledger row 3 | OPEN |
| C20 | S6 | receipt hygiene: receipt_check green fleet-wide | sweep receipt, 0 failing (or grandfathered list) | PR #334 + jude triage 14849 | PART (at gate) |
| C21 | S7 | retrieval substrate (KG turboquant VDB) — S7 prerequisite | parity+compression receipts on real corpus queries; on-demand CLI | mira INFRA-5 proto receipts | PART |
| C22 | S7 | corpus: journals/papers/experiment-logs/letters (PD-first) | per-item URL-pin+sha+license; vault-style manifests | — | GATED:C21 |
| C23 | S7 | causal-chain extraction → synthetic reasoning/world-model datasets | extraction pipeline receipt; synthetic set passes verifier | — | GATED:C22 |

| C24 | S2 | fp-36b: frozen 1B INFO frame executed on the real probe receipt (#328) | verdict receipt via proven chain (#336) | — | GATED:1B-checkpoint |
| C25 | S5 | sp-6b: B3 replay-rig execution on both seats (#282) | replay receipts, both seats, same worlds/budgets | — | GATED:C8,C10 |
| C26 | S1 | fp-35: band prediction → allocation policy (#273) | policy doc + receipt vs measured bands | — | GATED:fp-34-prong-A |
| C27 | S1 | fp-32: GPU bottleneck ledger + one measured gain (#225) | ledger + before/after bench receipt | — | GATED:per-label |
| C28 | S2 | fp-24b: floor verdict on first real checkpoint probe receipts (#223) | fp24_verdict receipt on real probes | — | GATED:1B-checkpoint |
| C29 | S6 | sp-3b: 06-22 terminal audit run (#214) | every row receipted or gap named to user | — | GATED:2026-06-22 |
| C30 | S2 | sp-2b: first P-own-resume + D-round receipts vs sp-2 spec (#210) | gated receipts pair | — | GATED:trigger |
| C31 | S2 | fp-27b: round-1 execution verdicts on real owned-core round receipts (#205) | verdict receipts | — | GATED:round-1-dispatch |
| C32 | S6 | eng-35: P-gate live probe leg across daemon restart (#128) | boundary-pair receipt | — | GATED:Leo-dispatch-order (HOLD is mine to lift) |

## Coverage sweeps (the manifest is complete only when these are swept)

Enumeration sources still to sweep into rows — owner Leo, one sweep per
BUILD tick until exhausted; each sweep appends rows or records "no new
pieces" with the source named:

- [x] wordingone/ember OPEN issues — swept 2026-06-12T15:25Z: 10 open; #329→C3,
      #328→C24, #282→C25, #273→C26, #225→C27, #223→C28, #214→C29, #210→C30,
      #205→C31, #128→C32. CLOSED issues still to sweep (next line).
- [ ] wordingone/ember CLOSED issues (completed pieces whose receipts the tally should count)
- [ ] docs/technique-registry.md (every row → C2 sub-rows)
- [ ] STATE.md pending layers (≥2 always listed)
- [ ] fp-* / sp-* protocol docs (every standing obligation)
- [ ] GOAL.md reading notes (each binding clause → testable row)
- [ ] work-ahead-ledger rows (parents must map to rows here)

Tally script AC (to be minted as eng issue): parse this table; for each row
with a receipt pointer, locate + validate (receipt_check pass + named AC
fields); GATED rows count as not-implemented but listed separately; emit
receipts/tally-<ts>.json; selftest with synthetic manifest; exit nonzero on
parse drift so CI catches table rot.
