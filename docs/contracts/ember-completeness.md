<!-- EMBER_ARTIFACT_CLASS=historical_only -->

# Legacy Ember completeness manifest (preserved, execution denied)

This six-column M/C manifest remains byte-readable by the legacy tally and
condition probes so none of its obligations or evidence is erased. It is
historical diagnostic input under EMBER-00, not current completion authority.
The current D-001-through-D-062 authority matrix is
`docs/authority/ember-authority-matrix.md`.

## Preserved historical content

# Ember completeness manifest (est. 2026-06-12, per user numeric-closure directive)

One row per planned/known piece of ember. The tally script
(`src/ember/governance/scripts/ember_tally.py`, issue pending — eng) walks this table, verifies
each receipt exists and passes its named check, and emits
`receipts/tally-<ts>.json` {total, implemented, pct, missing[]}. Status here
is advisory; the tally receipt is the authority. A planned piece missing
from this manifest is a gate violation — planning = manifest entry.

Statuses: DONE (receipt verified), PART (receipt exists, AC partially
covered), OPEN (no receipt), GATED:<trigger> (blocked on a named trigger).

| id | subgoal | piece | AC / test | receipt | status |
|----|---------|-------|-----------|---------|--------|
| M1 | S1 | from-scratch pretrain run (12c050e7 lineage) | run completes; checkpoints cadence receipts | checkpoint receipts | PART (run live, step-100000) |
| M2 | S1 | NC2-own component contract (QAT/ternary/sub-quadratic/MTP/small-core) | each component has an executed receipt or registry verdict | docs/technique-registry.md rows | PART |
| M3 | S1 | fused Muon NS5 kernel A/B | governed bench receipt; ns5_equiv_check PASS | pending #329 (MSVC install) | GATED:#329 |
| M4 | S2 | verified-episode ledger (L1) | episodes pass verifier; manifest sha-bound | receipts/ledger/episodes.jsonl (3143 entries, sha256 d825d719...) verified and solved | PART |
| M5 | S2 | three-test gain gate (transfer/control/deletion) | gate script + one full gated gain | fp-verdict-chain-rehearsal-20260612T144614Z | PART |
| M6 | S2 | self-curriculum generator | dry-run on frozen L1/L2 grammar; manifest-sha conformance | fp29-curriculum-dryrun-20260612T143048Z | DONE |
| M7 | S2 | 1B/2B/4B protocol verdict chain (fp-23/fp-29/fp-36) | dress-rehearsal receipt pre-1B | fp-verdict-chain-rehearsal-20260612T144614Z | DONE |
| M8 | S3 | predecessor-CLI clean-room port = visible harness | NCK-E2E proof chain all-PASS | nck-e2e-proof-20260612T142318Z (PR #332 merged, 5/5 stages incl. live-mailbox leg) | DONE |
| M9 | S3 | ember mailbox identity | founders.yaml entry; live mail consume | #259 merged + nck-e2e-proof-20260612T142318Z stage-2b/3 (live mail consumed) | DONE |
| M10 | S3 | resident event loop (mail/files/receipts/schedule) | resident runs; event→action receipts | #342 merged @0f66f96 (selftests 6/6) + live-resident receipt c10-resident-live-20260612T213133Z (pid 58996, ≥30min, 304 event receipts incl. real mail event, zero GPU; the lead independent probe 21:31Z) | DONE |
| M11 | S3 | CU communicability (user+the lead can interact) | CU console echo stage + interactive session receipt | #332 stage 5 (echo only) | PART |
| M12 | S3 | self-editing harness behind invariant gate | harness-edit artifact: branch→receipts→promote; deletion test | BLOCKED — deletion test requires harness implementation (not implemented as of C11 completion); clean-room gate in progress, not architectural precondition | GATED:harness-implementation |
| M13 | S4 | cross-session persistence of gains | yesterday's gain measurably load-bearing today (receipt) | receipts/ember-preloop-resident-gate/state-persistence-20260621T232600Z.json covers system state; gains-specific receipt BLOCKED on live training with cross-session measurements | GATED:round-1-verified-gain |
| M14 | S5 | fp-33 paired-protocol freeze (#255: E1-E5 engine + envelope) | protocol doc frozen pre-verdict | fp33-e1-open-base-inventory-20260612T033709Z | PART |
| M15 | S5 | E2B-in-ember-seat baseline (#307 seat contract; #311 E2B SHAKEDOWN; #313 ember SHAKEDOWN; #268 GSM8K leg) | full paired battery, same worlds, governed | seat shakedown receipts | PART |
| M16 | S5 | surpass receipts (both legs) | ember > E2B: ember-work + founder-likeness | verdict machine staged: scripts/fp33_surpass_verdict.py (A1..B4 conjunction, McNemar + paired-bootstrap 10k, selftest 17/17) + docs/research/fp33-surpass-verdict-gate.md; emits the surpass receipt on leg data | GATED:M15 |
| M17 | S6 | five un-removable invariants in code | protected paths + boot-time checksum verify | #332 stage 1 (boot_checksum) | PART |
| M18 | S6 | resource governor on every job | VRAM frac + margin assert + pacer receipts | v0-launch-gate-20260611T075419Z | DONE |
| M19 | S2 | probe-set reconciliation (seed23 vs checkpoint_probe) | decision note + seed23 ride receipt | fp28b-probe-reconciliation-prestage-20260612T150202Z | DONE |
| M20 | S6 | receipt hygiene: receipt_check green fleet-wide | sweep receipt, 0 failing (or grandfathered list) | receipt-hygiene-row8-20260612T143802Z | DONE |
| M21 | S7 | retrieval substrate (KG turboquant VDB) — S7 prerequisite | parity+compression receipts on real corpus queries; on-demand CLI | an agent/state/infra5-proto (outside tree — in-tree receipt due at v1) | PART |
| M22 | S7 | corpus: journals/papers/experiment-logs/letters (PD-first) | per-item URL-pin+sha+license; vault-style manifests | — | GATED:M21 |
| M23 | S7 | causal-chain extraction → synthetic reasoning/world-model datasets | extraction pipeline receipt; synthetic set passes verifier | — | GATED:M22 |

| M24 | S2 | fp-36b: frozen 1B INFO frame executed on the real probe receipt (#328) | verdict receipt via proven chain (#336) | — | GATED:1B-checkpoint |
| M25 | S5 | sp-6b: B3 replay-rig execution on both seats (#282) | replay receipts, both seats, same worlds/budgets | — | GATED:M8,M10 |
| M26 | S1 | fp-35: band prediction → allocation policy (#273) | policy doc + receipt vs measured bands | — | GATED:fp-34-prong-A |
| M27 | S1 | fp-32: GPU bottleneck ledger + one measured gain (#225) | ledger + before/after bench receipt | — | GATED:per-label |
| M28 | S2 | fp-24b: floor verdict on first real checkpoint probe receipts (#223) | fp24_verdict receipt on real probes | — | GATED:1B-checkpoint |
| M29 | S6 | sp-3b: 06-22 terminal audit run (#214) | every row receipted or gap named to user | — | GATED:2026-06-22 |
| M30 | S2 | sp-2b: first P-own-resume + D-round receipts vs sp-2 spec (#210) | gated receipts pair | — | GATED:trigger |
| M31 | S2 | fp-27b: round-1 execution verdicts on real owned-core round receipts (#205) | verdict receipts | — | GATED:round-1-dispatch |
| M32 | S6 | eng-35: P-gate live probe leg across daemon restart (#128) | boundary-pair receipt | — | GATED:the lead-dispatch-order (HOLD is mine to lift) |
| M33 | S1 | v0 corpus + tokenizer freeze + token shards (#130/#160/#185/#195) | license-clean mix receipts; freeze interlock; TOKEN-SHARDS-V0; launch gate 7/7 GREEN | eng36-assembly-20260611T052337Z (+ tokenizer-freeze, token-shards-v0 receipts) | DONE |
| M34 | S6 | fail-closed launch-rail stack (#181/#183/#186/#190/#192) | gate enforces prereg premises + shards byte-scan + live interlock | v0-launch-gate-20260611T075419Z (live 7/7) + c34-launch-rail-issue-mapping-20260705T125847Z.json (per-issue mapping: all 7 landed) | DONE |
| M35 | S2 | verify-path soundness hardening (#76/#86/#92) | strict comparator adopted + object-graph reachability guard on all verify surfaces | #76=fp8-vgate-20260611T001730Z; #86=v-soundness-probe-20260611T011439Z; #92=eng24-w1strict-20260611T014609Z + eng24-extstrict-20260611T014818Z (an agent coverage verdict 14889) | DONE |
| M36 | S4 | D/P persistence-gates harness (#114/#175/#186; sp-2 #201) | gates fail-closed; real owned-core receipts ride sp-2b (#210=M30) | p-gate-20260611T081931Z + d-gate-adapter_model-20260611T070448Z (core gates landed); #175/#201 referenced receipts not located in corpus — likely stale cross-repo references | PART |
| M37 | S2 | protocol freezes pre-data (#135 fp-23; #198 fp-27; #220 fp-31; #326 fp-36) | each frozen BEFORE its data window | fp27-prereg-20260611T155902Z + prereg-freeze-proof-20260612T163204Z (fp-23 @affcbb5, fp-31 @7204f97, fp-36 @8b38bd7; doc-sha + freeze-commit bound; an agent-minted, the lead-gated) | DONE |
| M38 | S1 | technique registry + dispatch-gate wiring (#256/#271) | registry_gate.py as dispatch precondition; proxy-speedrun harness | proxy-speedrun-baseline-20260612T054435Z; registry-gate.jsonl lacks ticket field (fails receipt_check — fix named) | PART |
| M39 | S1 | zero-cloud loop receipt (#212) | one full round config-only + loop-path locality manifest | round-local-loop-20260612T094223Z (sp3 row 8a binds it) | DONE |
| M40 | S1 | GPU efficiency registry execution (#284/#289/#294/#296/#298/#301/#305) | fp8 width-conditional dispatch, recompute NONE adoption, cuda-graph A/B — each receipted | 7/7: none-arm-298-20260612T174042Z closes the #298 gap (binds PR #300 merge 1b6454f, SHA verified vs GitHub at gate; margin figures + A/B context receipt bound) | DONE |
| M41 | S1 | technique-registry verdict closure | zero CANDIDATE/WATCH rows left in technique-registry.jsonl: each reaches TESTED/ADOPT/KILL via the speedrun proxy protocol, per-row receipts bound; tally walks the jsonl as a sub-manifest | technique-registry.jsonl rows | PART (4 ADOPT in v0; 11 CANDIDATE + 1 WATCH open) |
| M42 | S2 | round-1 verdict on the small core (t2 train → t4 four-arm chain) | verdict receipt: floor measured or fallback verdict (q15 floor-unmeasurable receipted; 3B fallback chain c9b26f8e) | t1-smoke-20260610T115140Z + q15 verdict receipts available; 3B chain receipts blocked on #29 (job completion) | GATED:#29 |
| M43 | S2 | round-2 SELF-GENERATED episodes round (STATE: REQUIRED for goal) | ALL r2-prereg.md phases receipted (doc = sub-manifest: S sampling/top-up/calibration/ingest; T arms MTP/control-MTP/plain-SFT; E G1+t5+HumanEval-probe; verdict cell named) | r2-prereg.md phases | GATED:round-1-verdict |
| M44 | S6 | contamination probe executed (t1c, active core) | continuation-membership signal ≤5pp and zero ID-recall hits, receipted | staged (t1c_run_q15.py) | GATED:idle-window-post-r1 |
| M45 | S2 | W-code second world admission (w1 floor → w2 ingest → w4 heldout gate) | w1 floor receipt F>0; ingest receipt; w4 paired deltas | chain BUILT + unit-checked; floor receipt pending | GATED:w1-floor-receipt |
| M46 | S3 | NC-K kernel v1.0 freeze | freeze per docs/kernel-v1-freeze-spec.md; replay + schema receipts | kernel_replay 20/20 both verdicts; ledger-schema-v3 spec'd | GATED:round-1-verdict+schema-review |
| M47 | S2 | additional worlds (NC1c IFC, NC1d ARC-3 policy) | admission floor per formalization §7; NC1d instrument = arcade-floor-prereg.md as sub-manifest (generation/execution/baseline/admission/ledger-ingest/candidate-pool receipts) | arcade-floor-prereg.md | GATED:NC0-verdict |
| M48 | S2 | gate-stats correctness (exact methods for zero-inflated n=100; power notes) | Wilson/Newcombe-paired adopted; round-2 sized BEFORE launch; receipted review | c48-gate-stats-review-20260613T042018Z (consolidates gate-stats-346 review + r2-power-prereg-20260611T021546Z #29 sizing + g1_r2w_verdict→power.newcombe_paired_delta adoption) | DONE |
| M49 | S2 | teacher-admission probe (feed-per-GPU-hour, sampler provenance) | admission receipt per teacher-system §7b | — | GATED:M45+feed-math |
| M50 | S1 | SDEK as ember's operating system (goal clause) | SDEK layer named in the component contract + an executed receipt showing SDEK-mediated operation | ember-floor-contract.md row-52 (SDEK/GDN-Jet middle-timescale substrate NAMED: gated delta-rule SSM, the lead-spec/the engineer-run, ADOPT-pilot, promote=GSM-Infinite-delta / kill=null→LoRA-sleep) — clause-1 MET; clause-2 (executed SDEK receipt) GATED on 340M GDN pilot, post-launch wait-window | PART |
| M51 | S1 | multimodal-unified core (goal clause) | modality plan in NC2-own contract + first multimodal episode verified | — | GATED:M2-contract-row |
| M52 | S3 | scaffolding-off residency test (goal terminal clause: founders/cloud off, mind persists + improves) | scripted: all founder/cloud scaffolding halted, ember runs N events + 1 verified gain solo, receipted | spec FROZEN docs/c52-scaffold-off-test-v1.md (120-min window, A1-A3 attestations, 12-episode sp6b-class battery, own-r1 gain leg, content-hash bound) | GATED:M10,M13 |
| M53 | S1 | fp-34 owned-band chain (fp34-owned-band-prereg-v1.md = sub-manifest) | band-freeze receipt + selftest; prong-A yield+verdict (GATED:round-2-sampling); prong-B (GATED:prong-A-PREDICTIVE) | c53-fp34-band-freeze-prestage-20260705T125847Z.json (predicate frozen, selftest ready) | PART (pre-stageable, full freeze GATED:round-1-receipt) |
| M54 | S5 | fp-33 B-leg instruments (B1 mail round-trip, B2 agency battery, B4 evals-through-harness) | each leg's paired receipt per fp33-surpass-prereg-v1.md bars (B1 ≥4/5 + >E2B; B2 ≥4/5 + >E2B; B4 dispatch both sides) | — | GATED:M15 |
| M55 | S5 | surpass pre-stage pair: GSM8K-200 greedy harness (A3-ii) + B3 duty-battery spec frozen BEFORE first B-run | harness selftest receipt; duty-battery spec doc (20 episodes + expected-verb table) committed pre-execution | c55-surpass-prestage-20260613T042503Z (GSM8K_EVAL_SELFTEST PASS @380254f #343 + docs/sp6b-duty-battery-spec-v1.md frozen @d2147eb, PR #345 merged a961c24) | DONE |

## Coverage sweeps (the manifest is complete only when these are swept)

Enumeration sources still to sweep into rows — owner the lead, one sweep per
BUILD tick until exhausted; each sweep appends rows or records "no new
pieces" with the source named:

- [x] wordingone/ember OPEN issues — swept 2026-06-12T15:25Z: 10 open; #329→M3,
      #328→M24, #282→M25, #273→M26, #225→M27, #223→M28, #214→M29, #210→M30,
      #205→M31, #128→M32. CLOSED issues still to sweep (next line).
- [x] wordingone/ember CLOSED issues — swept 2026-06-12T15:5xZ via Haiku enumeration (143 closed, #1-#337): credit rows M33-M40 added; M14/M15 upgraded (seat shakedowns); research-era eng-1..17/fp-1..25 pieces already embodied in M4/M5/M18/M35 — no new rows. Enumeration: docs/closed-issues-enumeration.txt
- [x] docs/technique-registry.md — swept 2026-06-12T15:55Z: registry is
      machine-readable (technique-registry.jsonl), so one closure row M41
      covers all 16 seed entries as a sub-manifest (tally walks the jsonl);
      M3 (fused-muon) and M40 (executed rows) already pin the receipted ones.
      No per-technique manifest rows — the registry IS the row source.
- [x] STATE.md pending layers + branch registry — swept 2026-06-12T16:35Z:
      rows M42-M49 added (round-1 verdict, round-2 self-gen [goal-REQUIRED],
      t1c contamination, W-code world, kernel freeze, NC1c/d, gate-stats,
      teacher admission). No-new-piece: 7B retained evals (review 06-17 kill
      candidate), HF upload (standing), release-scan/DiffusionGemma
      (standing exteroception, not completion-bound), config rollout
      (user-gated, not an ember piece).
- [x] fp-*/sp-* protocol docs — swept 2026-06-12T16:42Z (Haiku agent, 63K
      tok, gated): r2-prereg/arcade-floor/fp34 obligations folded as
      SUB-MANIFESTS into M43/M47/M53 (one row per round, doc carries the
      phases — M41 pattern); fp-33 B-legs → M54; pre-stageable successors
      (GSM8K harness + duty-battery spec freeze) → M55. ALL SEVEN
      enumeration sources now swept — the denominator is fully enumerated;
      only receipts (or new planning) move the tally from here.
- [x] GOAL.md reading notes — swept 2026-06-12T16:38Z: M50 (SDEK-as-OS),
      M51 (multimodal-unified), M52 (scaffolding-off residency test) added;
      deletion-test/persistence/both-legs/receipts-only clauses already
      rowed (M5/M13/M16/M20). M53 added (fp-34 prong A was a named gate
      with no row).
- [x] work-ahead-ledger rows — swept 2026-06-12T16:38Z: open rows 5 (#282
      → M25) and 6 (#214 → M29) both map; discharged rows map via their
      merged PRs (M6/M7/M19/M20). No unmapped parents.

## Additional condition rows (added 2026-07-06 enumeration sweep)

| id | subgoal | piece | AC / test | receipt | status |
|----|---------|-------|-----------|---------|--------|
| C-INV | S6 | Constitutional invariant persisted and chained | INVARIANT.md exists and hashes correctly; board receipts chain by predecessor hash | invariant verification receipts | planned |
| C-EFF | S1 | Efficiency keystone measured and closed | Efficiency closure receipt with measured throughput, MFU, token projection | efficiency-closure receipts | planned |
| C-BASE | S1 | Owned growable seed exists (not frozen) | From-scratch owned pilot checkpoint with growth operator interface | checkpoint-seed receipts | planned |
| C(−1) | S7 | Spend annex — 4 receipts missing api_spend_usd | Spend declarations for missing receipts | spend-annex documentation | planned |
| C0 | S6 | Process invariant: freshness contract | CONTINUITY state-as-of marker matches actual state | freshness monitoring receipts | planned |
| C-PORT | S3 | Predecessor-CLI port complete | Clean-room port with NCK-E2E proofs | port verification receipts | planned |
| C-FED | S3 | Federation surface (inter-founder coordination) | Mailbox routing and coordination surface | federation routing receipts | planned |
| C-GROW | S1 | Growth operator executes function-preserving transforms | Growth chain receipts and verification | growth chain receipts | planned |
| C-ORGANISM | S3 | Self-improvement loop closure | Complete loop: experience → train → improve → verify → use | organism-loop-closure receipts | planned |
| C-OBS | S3 | Observability and monitoring | Activity feed, telemetry, and inspection surface | observability receipts | planned |
| C-ANAT | S3 | Anatomy: component registry and interfaces | Complete component catalog with interface specifications | component registry receipts | planned |
| C-SCALE | S4 | Foundation-model-scale training on one-GPU budget | Scaled training receipts with verified results | scale training receipts | planned |
| C-E2B | S5 | Paired measured-distance protocol against frozen reference | E2B paired protocol execution receipts | e2b protocol receipts | planned |
| C-IND | S6 | Independence: operator-minimal operations | Operator decision receipts for necessary-only cases | independence operation receipts | planned |
| C-PROC | S6 | Process integrity: execution gate stack | Landing gates and pre-commit hooks enforced | process gate execution receipts | planned |
| C-SURFACE2 | S6 | Live surface: CLI/TUI operational in real time | Live session receipts with user interaction | surface operation receipts | planned |
| C-LEGIB | S6 | Repository legibility and documentation | Entry map, cold-read reprobe, citation gate all passing | legibility verification receipts | planned |
| C-ENF | S6 | Enforcement layer execution integrity | All registered checkers execute with correct verdicts | enforcement checker receipts | planned |
| C-MILE | S6 | Milestone reconciliation | Milestone mapping and reconciliation passing | milestone reconciliation receipts | planned |
| C-DISC | S6 | Disconfirmation: falsifiability gates | D-gate and P-gate results falsifiable and recorded | disconfirmation gate receipts | planned |
| C-LADM | S6 | Ladder administration: autonomy relinquishment tracking | Autonomy-ladder-state.json consistent and versioned | ladder state receipts | planned |
| C-AUTO | S6 | Autonomy-ladder-state faithfulness | Ladder state file valid with proper provenance | autonomy state verification receipts | planned |
| C-CUSTODY | S6 | Receipts custody and integrity | Every receipt is git-tracked, parseable JSON, all cited paths exist | custody verification receipts | planned |
| C-AUTHORITY | S6 | EMBER-00 authority and totality conservation bridge | Seven-leg verifier, mutation suite, selector binding, and independent clean-checkout receipt pass | external EMBER-00 completion receipt bound to exact commit | PART |
| C-MANIFEST | S6 | Completeness manifest enumerates every planned piece | docs/contracts/ember-completeness.md rows cover every §4 goal condition (id+subgoal+AC+receipt+status); an absent piece is a gate violation (does-NOT-count) | scripts/ember_totality/receipts-totality/ember-totality-20260710T150632Z.json (C-MANIFEST row, evaluated by src/ember/governance/scripts/ember_totality/test_c_manifest.py) | DONE |
| C-TALLY | S6 | Tally script walks the manifest and emits the completion receipt | src/ember/governance/scripts/ember_tally.py verifies each row's receipt exists and passes its named check, emits receipts/tally-<ts>.json {total, implemented, pct, missing[]}; the tally receipt is the only completion authority | receipts/tally-20260708T065530Z.json (real src/ember/governance/scripts/ember_tally.py output) | DONE |

Tally script AC (to be minted as eng issue): parse this table; for each row
with a receipt pointer, locate + validate (receipt_check pass + named AC
fields); GATED rows count as not-implemented but listed separately; emit
receipts/tally-<ts>.json; selftest with synthetic manifest; exit nonzero on
parse drift so CI catches table rot.

## Legacy ID mapping (2026-07-05 namespace rename)

**Manifest rows renamed C1-C55 → M1-M55** to resolve namespace collision with board conditions C0-C15 (issue #169). Historical receipts and tally files referencing C-numbered manifest rows remain valid unchanged. The mapping below is for reference when interpreting old receipts:

| Legacy ID | Current ID |
|-----------|-----------|
| C1 | M1 |
| C2 | M2 |
| C3 | M3 |
| C4 | M4 |
| C5 | M5 |
| C6 | M6 |
| C7 | M7 |
| C8 | M8 |
| C9 | M9 |
| C10 | M10 |
| C11 | M11 |
| C12 | M12 |
| C13 | M13 |
| C14 | M14 |
| C15 | M15 |
| C16 | M16 |
| C17 | M17 |
| C18 | M18 |
| C19 | M19 |
| C20 | M20 |
| C21 | M21 |
| C22 | M22 |
| C23 | M23 |
| C24 | M24 |
| C25 | M25 |
| C26 | M26 |
| C27 | M27 |
| C28 | M28 |
| C29 | M29 |
| C30 | M30 |
| C31 | M31 |
| C32 | M32 |
| C33 | M33 |
| C34 | M34 |
| C35 | M35 |
| C36 | M36 |
| C37 | M37 |
| C38 | M38 |
| C39 | M39 |
| C40 | M40 |
| C41 | M41 |
| C42 | M42 |
| C43 | M43 |
| C44 | M44 |
| C45 | M45 |
| C46 | M46 |
| C47 | M47 |
| C48 | M48 |
| C49 | M49 |
| C50 | M50 |
| C51 | M51 |
| C52 | M52 |
| C53 | M53 |
| C54 | M54 |
| C55 | M55 |

## Board history — the honest floor

2026-07-05: 82.9% C-surface GREEN reported via self-attesting probes (receipts/completeness-sweep). 2026-07-06: 2.9% C-surface GREEN after execution-binding hardening landed (receipts/c-enforcement, c-milestone, c-legibility checkers); old green conditions were self-attestation-only, not receipt-binding. 2026-07-07: 8.3-13.9% C-surface honest floor (receipts/spend-annex-20260707T030421Z.json, receipts/cold-read-reprobe/2026-07-06T01Z.json, receipts/completeness-sweep/c34-launch-rail-issue-mapping-20260705T125847Z.json) — receipts re-earning green with true property measurement, not deferred hardening.
