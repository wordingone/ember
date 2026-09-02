<!-- EMBER_ARTIFACT_CLASS=historical_only -->

# Ember Technical And Cognitive Debt Ledger (historical, execution denied)

This legacy control ledger is preserved as evidence. Its active commands,
tiny-model sequencing, terminal dispositions, and blocker routing have no
current execution, goal-selection, research, or completion authority.

Date: 2026-06-20
Status: Active control ledger. This is not a parking lot and not a scope reducer.

## Authority

This ledger supports repo `GOAL.md` as the single active goal file and its byte-identical an agent state mirror when present. It cannot override that goal file's `Authority And Precedence`, `Current Blocker Packet`, `Goal Injection Contract`, or `Goal Clear Condition` sections.

If this ledger conflicts with the goal file, the goal file wins and this ledger must be patched before the next nontrivial Ember action. If this ledger is stale, a goal-mode run may repair only the rows needed to preserve the current blocker packet, then must return to the blocker.

## Current Blocker Packet

1. **Current blocker:** Ember still lacks the non-killable RLM/iGRPO harness-native training organ and clean-room predecessor-CLI resident harness as one learned, executable, deletion-sensitive system. Non-Ember mechanisms still carry goal parsing, next-action selection, harness operation, and loop execution.
2. **Current executable command:** execute the resident-training gate attempt defined in `GOAL.md`. The attempt must read the stored RLM/iGRPO paper receipts, extract a mechanism-to-implementation map, inspect `scripts/train_multimodal_v0.py` as existing neural/multimodal training infrastructure, and create or run the adapter/gate runner. If the adapter is missing, implement the adapter and selftest as the first artifact; do not switch to benchmark/readiness work or write a parallel tiny neural runner before the train-multimodal decision receipt.
3. **Required receipt:** `<local-path><timestamp>.json` with source hashes, paper hashes, mechanism extraction, clean-room harness identity, A/B/C/deleted arms, commands, code-vs-docs metric, before/after rows, deletion result, and `resident_training_gate_status`.
4. **Kill/ablate test:** RLM, iGRPO, and the clean-room predecessor-CLI port are non-killable. Only candidate implementations may be ablated. Deleting native goal organ, recursive-query policy, verifier-conditioned update, or clean-room harness action channel must degrade or block a claimed C-arm pass.
5. **Next blocker if pass:** the immediate tiny BitNet/1.58-bit comparison required by `GOAL.md`, then benchmark discovery, past-Ember technique mining, and the first external heldout A/B/C loop using the resident-trained organ.
6. **Next blocker if fail:** the exact missing resident-training surface: paper mechanism extraction, clean-room harness parity, learned update, A/B/C evaluator, persistence, or deletion sensitivity.

## Active Rows

| ID | Class | Debt | Why It Matters | Required Receipt | Status |
| --- | --- | --- | --- | --- | --- |
| DEBT-001 | ACTIVE-BLOCKER | RLM harness-native training organ absent | Without it, Ember is still using non-Ember reasoning/control rather than learned resident recursion. Blocker re-verified at master 3b2a6456; the required gate receipt cannot be produced (gate selftest BLOCKED on floor_contract.deferral_section_missing) and a real one needs a learned neural update. Never-killable row. src/ember/governance/scripts/ember_totality/receipts-debt-ledger/BLOCKER-REVERIFICATION-20260802T032156Z.json | resident-training gate receipt with RLM primitive map, update step, A/B/C/deleted rows | OPEN |
| DEBT-002 | ACTIVE-BLOCKER | iGRPO verifier-conditioned refinement absent | Without it, verifier feedback remains an external scorer, not a learned improvement signal. Blocker re-verified at master 3b2a6456; same gate-receipt blocker, and the verifier-conditioned update is a training result, not a code artifact. Never-killable row. src/ember/governance/scripts/ember_totality/receipts-debt-ledger/BLOCKER-REVERIFICATION-20260802T032156Z.json | resident-training gate receipt with verifier-conditioned update and ablation | OPEN |
| DEBT-003 | ACTIVE-BLOCKER | clean-room predecessor-CLI resident harness absent | Without it, Ember has no local visible body for goals, receipts, tools, state, and bounded actions. Blocker re-verified at master 3b2a6456; this is the exact component the last real gate run blocked on, and its parity evidence needs observation of a real reference binary, unobtainable from repository bytes. Never-killable row. src/ember/governance/scripts/ember_totality/receipts-debt-ledger/BLOCKER-REVERIFICATION-20260802T032156Z.json | clean-room interface/parity/provenance receipt plus deletion-sensitive use | OPEN |
| DEBT-004 | ACTIVE-NEXT | Goal source split between local goal file and repo `GOAL.md` | A stale governing file can bypass the new gate. | `invalid_goal_source_split` resolved by byte/hash sync and git preservation | ARCHIVAL: src/ember/governance/scripts/ember_totality/receipts-debt-ledger/DEBT-004-archival-20260801T222935Z.json |
| DEBT-005 | ACTIVE-NEXT | Paper-source preflight can degrade into citation-only reading | RLM/iGRPO must become mechanisms, not slogans. Blocker re-verified at master 3b2a6456; the invalid_paper_to_spec_only marker is never emitted by the gate (token appears only in docs and in C0/C14 invalid-token lists), and the gate selftest is RED so a change to it cannot be shown green. src/ember/governance/scripts/ember_totality/receipts-debt-ledger/BLOCKER-REVERIFICATION-20260802T032156Z.json | mechanism-to-implementation map; citation-only pass marked `invalid_paper_to_spec_only` | OPEN |
| DEBT-006 | ACTIVE-NEXT | Resident-training A/B/C evaluator not yet implemented | Without fixed A/B/C/deleted arms, a pilot can become a toy success. | executable evaluator with A, B, C, Deleted definitions and per-row scores | DONE: src/ember/governance/scripts/ember_totality/receipts-debt-ledger/DEBT-006-done-20260802T032156Z.json |
| DEBT-007 | ACTIVE-NEXT | Code-vs-docs metric required for each progress window | This detects scaffolding drift before it masquerades as growth. | receipt field separating executable/test lines from docs/spec/receipt lines | DONE: src/ember/governance/scripts/ember_totality/receipts-debt-ledger/DEBT-007-done-20260802T032156Z.json |
| DEBT-008 | ACTIVE-BLOCKER | Existing `train_multimodal_v0.py` neural/multimodal training infrastructure not integrated into resident gate | The repo already has real neural training primitives; bypassing them with a tiny parallel runner repeats the scaffold/toy failure. Blocker re-verified at master 3b2a6456; the only receipts pinning this file pin a hash that has drifted from master, so the integration evidence no longer describes the tree. src/ember/governance/scripts/ember_totality/receipts-debt-ledger/BLOCKER-REVERIFICATION-20260802T032156Z.json | resident-training gate receipt with `scripts/train_multimodal_v0.py` hash, adapter path or exact blocked reason, and A/B/C/deleted neural evidence | OPEN |
| DEBT-009 | TRIGGER-GATED | Tiny BitNet/1.58-bit comparison missing after fp16 neural gate | BitNet was a debt item and must start immediately after the fp16 neural resident gate passes, before D3/Kaggle/readiness progress resumes. | `BITNET_BLOCKED` or comparison receipt with fp16 baseline, BitNet identity, quality/footprint/latency/memory rows, transfer, and deletion/revert evidence | TRIGGER-GATED: fires when resident_training_gate_status=PASS appears in a receipts/ember-resident-training-gate/ run receipt; not fired as of master 3b2a6456; scripts/ember_totality/receipts-debt-ledger/TRIGGER-FORMALIZATION-20260802T032156Z.json |
| DEBT-010 | ACTIVE-BLOCKER | Floor-contract and NC2 component contract not imported into resident gate | `docs/contracts/ember-floor-contract.md`, `nc2-own-technique-contract.md`, and the §6 action-log seam in `scripts/train_multimodal_v0.py` define real launch-vehicle machinery and trigger-gated rows; omitting them lets a narrow neural pass bypass Ember's floor. Blocker re-verified at master 3b2a6456; both pinned contract hashes have drifted, the nc2 path named at repository root no longer exists, and this row's own component is what the gate selftest currently fails on. src/ember/governance/scripts/ember_totality/receipts-debt-ledger/BLOCKER-REVERIFICATION-20260802T032156Z.json | resident-training gate receipt with floor/nc2 hashes, action-log seam evidence, launch-vehicle floor preservation map, and trigger-gated row accounting | OPEN |

## Trigger-Gated Rows

| ID | Trigger | Debt | Required Action When Trigger Fires | Status |
| --- | --- | --- | --- | --- |
| GATE-001 | `resident_training_gate_status=PASS` | benchmark discovery and docs/research/journal/world-rule dataset selection | produce exact source-backed benchmark discovery receipt | TRIGGER-GATED: fires when resident_training_gate_status=PASS appears in a receipts/ember-resident-training-gate/ run receipt; not fired as of master 3b2a6456; scripts/ember_totality/receipts-debt-ledger/TRIGGER-FORMALIZATION-20260802T032156Z.json |
| GATE-002 | `resident_training_gate_status=PASS` | past-Ember technique mining | combine original GOAL, STATE, issues, receipts, assistant-session history, and research notes into next-loop techniques | TRIGGER-GATED: fires when resident_training_gate_status=PASS appears in a receipts/ember-resident-training-gate/ run receipt; not fired as of master 3b2a6456; scripts/ember_totality/receipts-debt-ledger/TRIGGER-FORMALIZATION-20260802T032156Z.json |
| GATE-003 | resident-trained organ exists and benchmark selected | external heldout A/B/C loop | run equal-budget before/after positive-delta loop with deletion and reproducibility | TRIGGER-GATED: fires when resident_training_gate_status=PASS appears in a receipts/ember-resident-training-gate/ run receipt AND a GATE-001 benchmark-discovery receipt exists under receipts/; not fired as of master 3b2a6456; scripts/ember_totality/receipts-debt-ledger/TRIGGER-FORMALIZATION-20260802T032156Z.json |
| GATE-004 | field-level claim attempted | ML/AI field-level contribution proof | cite prior baseline, define material difference, ablate, transfer/reuse, publish reproducible recipe | TRIGGER-GATED: fires when any receipts/ JSON sets field_level_contribution_claimed=true; not fired as of master 3b2a6456; scripts/ember_totality/receipts-debt-ledger/TRIGGER-FORMALIZATION-20260802T032156Z.json |
| GATE-005 | duration scale-up proposed | 1h/3h/24h developmental duration | prove extra time is load-bearing and deletion-sensitive; otherwise mark `unearned_duration` | TRIGGER-GATED: fires when any receipts/ JSON sets duration_scale_up_proposed=true or declares planned_run_hours >= 1; not fired as of master 3b2a6456; scripts/ember_totality/receipts-debt-ledger/TRIGGER-FORMALIZATION-20260802T032156Z.json |
| GATE-006 | `resident_training_gate_status=PASS` | immediate tiny BitNet/1.58-bit comparison | run the post-fp16 BitNet comparison or write `BITNET_BLOCKED` before any benchmark/readiness/D3 continuation | TRIGGER-GATED: fires when resident_training_gate_status=PASS appears in a receipts/ember-resident-training-gate/ run receipt; not fired as of master 3b2a6456; scripts/ember_totality/receipts-debt-ledger/TRIGGER-FORMALIZATION-20260802T032156Z.json |

## Classification Law

`ARCHIVAL`, `KILLED`, and `EXCLUDED` are not hidden trashcans. A row may enter those states only when a receipt proves, at the physics/function level, that the work is contradictory to Ember's target, cannot affect self-growth under any plausible current path, or is strictly subsumed by a successor under the same clearance tests.

If that proof does not exist, the row remains `ACTIVE` or `TRIGGER-GATED`. RLM, iGRPO, and the clean-room predecessor-CLI port are never killable rows.

## Invalid Progress Patterns

- Paper summary without mechanism extraction: `invalid_paper_to_spec_only`.
- Benchmark/readiness/D3/Kaggle work before resident-training gate pass: `invalid_precondition_bypass`.
- Stale repo goal surface: `invalid_goal_source_split`.
- Pure simulation, fake task, prompt-only demo, no-update pilot, or hand-authored rule patch claimed as the gate: `precondition_scaffold_only`.
- Ignoring `scripts/train_multimodal_v0.py` and writing a tiny parallel neural runner without a blocked adapter receipt: `precondition_scaffold_only`.
- Ignoring `docs/contracts/ember-floor-contract.md`, `nc2-own-technique-contract.md`, QAT/Muon/QK-norm/governor launch-vehicle floors, or the §6 primitive action-log seam while claiming a resident-gate pass: `invalid_floor_contract_bypass`.
- Useful progress without ML/AI field-level proof: `progress_not_field_breakthrough`.
- Longer cycle without load-bearing need or ablation sensitivity: `unearned_duration`.
