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
| C4 | S2 | verified-episode ledger (L1) | episodes pass verifier; manifest sha-bound | MISSING — L1-episode-verification receipt to mint (jude 14866) | PART |
| C5 | S2 | three-test gain gate (transfer/control/deletion) | gate script + one full gated gain | fp-verdict-chain-rehearsal-20260612T144614Z | PART |
| C6 | S2 | self-curriculum generator | dry-run on frozen L1/L2 grammar; manifest-sha conformance | fp29-curriculum-dryrun-20260612T143048Z | DONE |
| C7 | S2 | 1B/2B/4B protocol verdict chain (fp-23/fp-29/fp-36) | dress-rehearsal receipt pre-1B | fp-verdict-chain-rehearsal-20260612T144614Z | DONE |
| C8 | S3 | avir-cli clean-room port = visible harness | NCK-E2E proof chain all-PASS | nck-e2e-proof-20260612T142318Z (PR #332 merged, 5/5 stages incl. live-mailbox leg) | DONE |
| C9 | S3 | ember mailbox identity | founders.yaml entry; live mail consume | #259 merged + nck-e2e-proof-20260612T142318Z stage-2b/3 (live mail consumed) | DONE |
| C10 | S3 | resident event loop (mail/files/receipts/schedule) | resident runs; event→action receipts | #342 merged @0f66f96 (4 event classes, RSS cap, kill-switch; selftests 6/6 reproduced at gate) — live-resident receipt outstanding | PART |
| C11 | S3 | CU communicability (user+Leo can interact) | CU console echo stage + interactive session receipt | #332 stage 5 (echo only) | PART |
| C12 | S3 | self-editing harness behind invariant gate | harness-edit artifact: branch→receipts→promote; deletion test | — | OPEN |
| C13 | S4 | cross-session persistence of gains | yesterday's gain measurably load-bearing today (receipt) | — | OPEN |
| C14 | S5 | fp-33 paired-protocol freeze (#255: E1-E5 engine + envelope) | protocol doc frozen pre-verdict | fp33-e1-open-base-inventory-20260612T033709Z | PART |
| C15 | S5 | E2B-in-ember-seat baseline (#307 seat contract; #311 E2B SHAKEDOWN; #313 ember SHAKEDOWN; #268 GSM8K leg) | full paired battery, same worlds, governed | seat shakedown receipts | PART |
| C16 | S5 | surpass receipts (both legs) | ember > E2B: ember-work + founder-likeness | — | GATED:C15 |
| C17 | S6 | five un-removable invariants in code | protected paths + boot-time checksum verify | #332 stage 1 (boot_checksum) | PART |
| C18 | S6 | resource governor on every job | VRAM frac + margin assert + pacer receipts | v0-launch-gate-20260611T075419Z | DONE |
| C19 | S2 | probe-set reconciliation (seed23 vs checkpoint_probe) | decision note + seed23 ride receipt | fp28b-probe-reconciliation-prestage-20260612T150202Z | DONE |
| C20 | S6 | receipt hygiene: receipt_check green fleet-wide | sweep receipt, 0 failing (or grandfathered list) | receipt-hygiene-row8-20260612T143802Z | DONE |
| C21 | S7 | retrieval substrate (KG turboquant VDB) — S7 prerequisite | parity+compression receipts on real corpus queries; on-demand CLI | mira/state/infra5-proto (outside tree — in-tree receipt due at v1) | PART |
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
| C33 | S1 | v0 corpus + tokenizer freeze + token shards (#130/#160/#185/#195) | license-clean mix receipts; freeze interlock; TOKEN-SHARDS-V0; launch gate 7/7 GREEN | eng36-assembly-20260611T052337Z (+ tokenizer-freeze, token-shards-v0 receipts) | DONE |
| C34 | S6 | fail-closed launch-rail stack (#181/#183/#186/#190/#192) | gate enforces prereg premises + shards byte-scan + live interlock | v0-launch-gate-20260611T075419Z (live 7/7); per-issue receipt mapping MISSING (jude R2) | PART |
| C35 | S2 | verify-path soundness hardening (#76/#86/#92) | strict comparator adopted + object-graph reachability guard on all verify surfaces | #76=fp8-vgate-20260611T001730Z; #86=v-soundness-probe-20260611T011439Z; #92=eng24-w1strict-20260611T014609Z + eng24-extstrict-20260611T014818Z (jude coverage verdict 14889) | DONE |
| C36 | S4 | D/P persistence-gates harness (#114/#175/#186; sp-2 #201) | gates fail-closed; real owned-core receipts ride sp-2b (#210=C30) | p-gate-20260611T081931Z + d-gate-adapter_model-20260611T070448Z (#175/#201 receipts not found) | PART |
| C37 | S2 | protocol freezes pre-data (#135 fp-23; #198 fp-27; #220 fp-31; #326 fp-36) | each frozen BEFORE its data window | fp27-prereg-20260611T155902Z; fp-23/31/36 frozen as docs only — composite freeze receipt (doc-sha + git-date) to mint (jude) | PART |
| C38 | S1 | technique registry + dispatch-gate wiring (#256/#271) | registry_gate.py as dispatch precondition; proxy-speedrun harness | proxy-speedrun-baseline-20260612T054435Z; registry-gate.jsonl lacks ticket field (fails receipt_check — fix named) | PART |
| C39 | S1 | zero-cloud loop receipt (#212) | one full round config-only + loop-path locality manifest | round-local-loop-20260612T094223Z (sp3 row 8a binds it) | DONE |
| C40 | S1 | GPU efficiency registry execution (#284/#289/#294/#296/#298/#301/#305) | fp8 width-conditional dispatch, recompute NONE adoption, cuda-graph A/B — each receipted | 6/7 verified; #298 MISSING-CONFIRMED (jude 14889: figures inline in PR #300 body, no receipt file) — Eli to mint none-arm receipt | PART |
| C41 | S1 | technique-registry verdict closure | zero CANDIDATE/WATCH rows left in technique-registry.jsonl: each reaches TESTED/ADOPT/KILL via the speedrun proxy protocol, per-row receipts bound; tally walks the jsonl as a sub-manifest | technique-registry.jsonl rows | PART (4 ADOPT in v0; 11 CANDIDATE + 1 WATCH open) |
| C42 | S2 | round-1 verdict on the small core (t2 train → t4 four-arm chain) | verdict receipt: floor measured or fallback verdict (q15 floor-unmeasurable receipted; 3B fallback chain c9b26f8e) | t1-smoke-20260610T115140Z + q15 verdict receipts; 3B chain receipts pending | PART |
| C43 | S2 | round-2 SELF-GENERATED episodes round (STATE: REQUIRED for goal) | ALL r2-prereg.md phases receipted (doc = sub-manifest: S sampling/top-up/calibration/ingest; T arms MTP/control-MTP/plain-SFT; E G1+t5+HumanEval-probe; verdict cell named) | r2-prereg.md phases | GATED:round-1-verdict |
| C44 | S6 | contamination probe executed (t1c, active core) | continuation-membership signal ≤5pp and zero ID-recall hits, receipted | staged (t1c_run_q15.py) | GATED:idle-window-post-r1 |
| C45 | S2 | W-code second world admission (w1 floor → w2 ingest → w4 heldout gate) | w1 floor receipt F>0; ingest receipt; w4 paired deltas | chain BUILT + unit-checked; floor receipt pending | GATED:w1-floor-receipt |
| C46 | S3 | NC-K kernel v1.0 freeze | freeze per docs/kernel-v1-freeze-spec.md; replay + schema receipts | kernel_replay 20/20 both verdicts; ledger-schema-v3 spec'd | GATED:round-1-verdict+schema-review |
| C47 | S2 | additional worlds (NC1c IFC, NC1d ARC-3 policy) | admission floor per formalization §7; NC1d instrument = arcade-floor-prereg.md as sub-manifest (generation/execution/baseline/admission/ledger-ingest/candidate-pool receipts) | arcade-floor-prereg.md | GATED:NC0-verdict |
| C48 | S2 | gate-stats correctness (exact methods for zero-inflated n=100; power notes) | Wilson/Newcombe-paired adopted; round-2 sized BEFORE launch; receipted review | — | OPEN |
| C49 | S2 | teacher-admission probe (feed-per-GPU-hour, sampler provenance) | admission receipt per teacher-system §7b | — | GATED:C45+feed-math |
| C50 | S1 | SDEK as ember's operating system (goal clause) | SDEK layer named in the component contract + an executed receipt showing SDEK-mediated operation | — | OPEN |
| C51 | S1 | multimodal-unified core (goal clause) | modality plan in NC2-own contract + first multimodal episode verified | — | GATED:C2-contract-row |
| C52 | S3 | scaffolding-off residency test (goal terminal clause: founders/cloud off, mind persists + improves) | scripted: all founder/cloud scaffolding halted, ember runs N events + 1 verified gain solo, receipted | spec FROZEN docs/c52-scaffold-off-test-v1.md (120-min window, A1-A3 attestations, 12-episode sp6b-class battery, own-r1 gain leg, content-hash bound) | GATED:C10,C13 |
| C53 | S1 | fp-34 owned-band chain (fp34-owned-band-prereg-v1.md = sub-manifest) | band-freeze receipt + selftest; prong-A yield+verdict (GATED:round-2-sampling); prong-B (GATED:prong-A-PREDICTIVE) | fp34_band_owned.py receipts | OPEN (freeze+selftest pre-stageable) |
| C54 | S5 | fp-33 B-leg instruments (B1 mail round-trip, B2 agency battery, B4 evals-through-harness) | each leg's paired receipt per fp33-surpass-prereg-v1.md bars (B1 ≥4/5 + >E2B; B2 ≥4/5 + >E2B; B4 dispatch both sides) | — | GATED:C15 |
| C55 | S5 | surpass pre-stage pair: GSM8K-200 greedy harness (A3-ii) + B3 duty-battery spec frozen BEFORE first B-run | harness selftest receipt; duty-battery spec doc (20 episodes + expected-verb table) committed pre-execution | — | OPEN (pre-stageable NOW) |

## Coverage sweeps (the manifest is complete only when these are swept)

Enumeration sources still to sweep into rows — owner Leo, one sweep per
BUILD tick until exhausted; each sweep appends rows or records "no new
pieces" with the source named:

- [x] wordingone/ember OPEN issues — swept 2026-06-12T15:25Z: 10 open; #329→C3,
      #328→C24, #282→C25, #273→C26, #225→C27, #223→C28, #214→C29, #210→C30,
      #205→C31, #128→C32. CLOSED issues still to sweep (next line).
- [x] wordingone/ember CLOSED issues — swept 2026-06-12T15:5xZ via Haiku enumeration (143 closed, #1-#337): credit rows C33-C40 added; C14/C15 upgraded (seat shakedowns); research-era eng-1..17/fp-1..25 pieces already embodied in C4/C5/C18/C35 — no new rows. Enumeration: docs/closed-issues-enumeration.txt
- [x] docs/technique-registry.md — swept 2026-06-12T15:55Z: registry is
      machine-readable (technique-registry.jsonl), so one closure row C41
      covers all 16 seed entries as a sub-manifest (tally walks the jsonl);
      C3 (fused-muon) and C40 (executed rows) already pin the receipted ones.
      No per-technique manifest rows — the registry IS the row source.
- [x] STATE.md pending layers + branch registry — swept 2026-06-12T16:35Z:
      rows C42-C49 added (round-1 verdict, round-2 self-gen [goal-REQUIRED],
      t1c contamination, W-code world, kernel freeze, NC1c/d, gate-stats,
      teacher admission). No-new-piece: 7B retained evals (review 06-17 kill
      candidate), HF upload (standing), release-scan/DiffusionGemma
      (standing exteroception, not completion-bound), config rollout
      (user-gated, not an ember piece).
- [x] fp-*/sp-* protocol docs — swept 2026-06-12T16:42Z (Haiku agent, 63K
      tok, gated): r2-prereg/arcade-floor/fp34 obligations folded as
      SUB-MANIFESTS into C43/C47/C53 (one row per round, doc carries the
      phases — C41 pattern); fp-33 B-legs → C54; pre-stageable successors
      (GSM8K harness + duty-battery spec freeze) → C55. ALL SEVEN
      enumeration sources now swept — the denominator is fully enumerated;
      only receipts (or new planning) move the tally from here.
- [x] GOAL.md reading notes — swept 2026-06-12T16:38Z: C50 (SDEK-as-OS),
      C51 (multimodal-unified), C52 (scaffolding-off residency test) added;
      deletion-test/persistence/both-legs/receipts-only clauses already
      rowed (C5/C13/C16/C20). C53 added (fp-34 prong A was a named gate
      with no row).
- [x] work-ahead-ledger rows — swept 2026-06-12T16:38Z: open rows 5 (#282
      → C25) and 6 (#214 → C29) both map; discharged rows map via their
      merged PRs (C6/C7/C19/C20). No unmapped parents.

Tally script AC (to be minted as eng issue): parse this table; for each row
with a receipt pointer, locate + validate (receipt_check pass + named AC
fields); GATED rows count as not-implemented but listed separately; emit
receipts/tally-<ts>.json; selftest with synthetic manifest; exit nonzero on
parse drift so CI catches table rot.
