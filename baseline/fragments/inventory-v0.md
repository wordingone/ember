# Ember Baseline Fragment Inventory V0

Status: DISCOVERY DRAFT.
Created: 2026-06-29.

This file records baseline-related fragments found across current Ember checkouts. It exists because the final `/baseline` directory must absorb prior Ember evidence and plans without laundering proxy, blocked, or historical fragments into new PASS claims.

## Search Scope

Checked on 2026-06-29:

- `<exec-tree>`
- `<public-tree>`

Search terms included:

- `baseline`, `SOTA`, `state of the art`, `NanoGPT`, `modded`, `BabyLM`, `AlgoPerf`, `MLE-bench`, `MLAgentBench`, `AI Scientist`;
- `4090`, `RTX`, `single GPU`, `single-4090`;
- `keystone`, `C-EFF`, `C-GROW`, `C-SCALE`, `field-level`, `external comparator`, `external baseline`, `leaderboard`, `benchmark`.

Excluded broad generated or dependency directories where practical: `.git`, `node_modules`, `models`, `results`, `scratchpad`.

This is not yet a complete proof sweep. It is the first absorption inventory.

## Fragment Classes

| Class | Meaning | Promotion rule |
|---|---|---|
| External comparator | A source outside Ember that can reject an Ember claim. | May enter `/baseline/sources.jsonl` and contracts after exact source pin, metric row, and no-recompute decision. |
| Local control baseline | An Ember A/B/control arm, before/after row, random policy, plain SFT arm, or backprop reference. | May enter protocols and negative-results context. Cannot prove external SOTA alone. |
| Proxy baseline | A deliberately small or fixture benchmark used to test mechanics. | Must remain proxy-scoped. Cannot transfer to >=1B, keystone, self-improvement, or field-level claims. |
| Ceiling/economics fragment | Existing 4090, throughput, token, wall-clock, or roofline analysis. | May inform `4090-ceiling-v0.md`, but must retain receipt boundary and stale-date notes. |
| Goal/proof rule | Existing no-paid, no-premature-completion, field-level, deletion, or benchmark-discovery rule. | Must constrain `/baseline` acceptance criteria. |
| Integrity baseline | Hash, invariant, line-ending, or manifest baseline. | Useful for `/baseline` verifier mechanics, but not a neural/research comparator. |
| Blocked/historical evidence | Prior attempted benchmark or baseline work that explicitly failed, blocked, or was fixture-only. | Must be preserved as negative evidence; cannot be silently upgraded. |

## High-Signal Fragments

| ID | Class | Location | What it contributes | Absorption action |
|---|---|---|---|---|
| F01 | Goal/proof rule | `<public-tree>\docs\formalization-v0.md` | States the formal content is not a SOTA claim until a comparative literature sweep confirms novelty versus known technique. | Add to `/baseline/reports` as prior anti-SOTA guard. |
| F02 | Ceiling/economics fragment | `<public-tree>\docs\compute-ceiling-program-v1.md` | Existing local ceiling program: measured c03 production throughput, 7B token day estimates, 4090 bottleneck framing, C-EFF shatter criterion, receipt-derived lever stack. | Absorb into `4090-ceiling-v0.md` as local historical ceiling evidence, with stale/current verification required. |
| F03 | Local control baseline | `<public-tree>\docs\dt3-scale-probe-prereg.md` and `docs\delta-rule-diagnostic-prereg.md` | Equal-4090-wall-clock backprop reference for owned delta-rule/local update scaling; frozen scale ladder and PASS/FAIL bands. | Add a separate contract for owned-update-vs-backprop scaling if this becomes active. Not a Modded-NanoGPT substitute. |
| F04 | Blocked/historical evidence | `<public-tree>\docs\ember-mvp-cycle-spine-status.md` | MLE-bench micro harness, A/B/C wheel contract, fixture-vs-real benchmark distinctions, and many blocked official grading receipts. | Use as self-improvement-loop background and negative evidence; do not treat fixture or blocked receipts as external benchmark success. |
| F05 | Goal/proof rule | `<public-tree>\GOAL.md` | Requires field-level breakthrough over named prior, broader external/disjoint benchmark, zero-cost verification, deletion/revert sensitivity, and no paid leaderboard/API authority. | Mirror into self-improvement and publication contracts. |
| F06 | External/proxy benchmark fragment | `<public-tree>\docs\ember-debt-ledger.md` | Gates for benchmark discovery, external heldout A/B/C loop, BitNet comparison, and field-level proof. | Use as checklist for missing contracts; keep trigger-gated status. |
| F07 | Proxy baseline | `<public-tree>\scripts\proxy_speedrun.py` and `receipts/proxy-speedrun-baseline-*` | Local proxy-speedrun baseline and frozen target mechanics. | Useful parser/control pattern; explicitly proxy-only. |
| F08 | Local control baseline | `<public-tree>\scripts\arcade.py`, `docs\arcade-floor-prereg.md`, `receipts\arcade-random-smoke-*` | Random-policy matched baseline and arcade admission floor. | Use only for control-arm examples, not neural pretraining baseline. |
| F09 | Local control baseline | `<public-tree>\scripts\train_delta_rule_dt1.py` | Equal-wall-clock CUDA benchmark against backprop baseline under 4090 gate. | Candidate contract for architecture/update-rule claim. |
| F10 | Integrity baseline | `<public-tree>\config\nck-baseline\`, `scripts\nck\invariants.py`, `scripts\nck\activation_receipt.py` | Manifest-vs-baseline boot protection and pre/post activation throughput baseline patterns. | Reuse concepts for `/baseline` manifest and line-ending verifier, not for neural SOTA. |
| F11 | Local training baseline | `<public-tree>\scripts\r2_arms.py`, `scripts\t2_r2_sft.py` | Plain SFT baseline arm for round-2. | Candidate local control for loop/adapter claims. |
| F12 | Existing 4090 receipts | `<public-tree>\receipts\t0-preflight.json`, `configs\v0-pretrain-config.json`, `scripts\v0_pretrain_launch_gate.py` | RTX 4090 device evidence, 24GB-class local training rails, 0.368B v0 config. | Support single-4090 evidence boundary; cannot satisfy >=1B. |
| F13 | Completion/coverage map | `<public-tree>\docs\ember-completeness.md` | Lists C15 E2B baseline, C38 proxy-speedrun harness, C47 arcade floor, and status flags. | Use as cross-reference for missing contracts and prior fragments. |
| F14 | Public/private divergence signal | `<exec-tree>` vs `<public-tree>` search results | Private checkout has more current dirty receipts and GOAL state; public repo has scrubbed/deleted placeholders and different current blocker text. | Final `/baseline` must include parity report and public-safe substitutes for private-only evidence. |
| F15 | Agent-loop baseline | `<public-tree>\GOAL.md`, `docs\goal-archive.md`, `scripts\ember_gate_full_parity_harness.py`, `<exec-tree>\tools\ember-cli\CLEANROOM-PROTOCOL.md` | Codex goal mode, Claude Code/upstream-org-cli behavior, and Hermes-class agents are comparator substrates for goal execution, CLI parity, tool use, and self-improvement loops. | Absorb into `agent-loop-baselines-v0.md` and `contracts/C8-agent-loop-baselines.md`; keep hidden weight/tool self-edit claims as hypotheses unless sourced. |
| F16 | Inference-to-training transfer filter | `<exec-tree>\research\nc2-technique-survey-2026-06.md`, `<exec-tree>\research\gpu-math-multiplier-table-v2-2026-06-11.json`, `<exec-tree>\nc2-own-technique-contract.md`, `<exec-tree>\receipts\ns-chain-roofline-4090-adjudication-20260623T171500Z.json`, `https://github.com/deepseek-ai/DeepSpec` | Existing Ember thread translates DeepSeek/MTP/MLA/speculative-decode/kernel claims into small-scale one-4090 training relevance. DSpark is now resolved as DeepSpec speculative-decoding draft-model work. | Absorb into `protocols/inference-to-training-transfer-v0.md`; require same-axis receipts before any inference multiplier enters a training claim. |

## Modded-NanoGPT Comparator Row

Primary source inspected:

- clone: `C:\tmp\modded-nanogpt-baseline-source`
- repository: `https://github.com/KellerJordan/modded-nanogpt`
- commit: `54c192a77bd0e3d2572a891e0a8a1b0ceeb957d7`

Pinned facts from README/log:

- task: train a neural network to <=3.28 cross-entropy loss on FineWeb validation;
- hardware: official records timed on 8 NVIDIA H100 GPUs;
- run command: `torchrun --standalone --nproc_per_node=8 train_gpt.py` through `./run.sh`;
- current record row in README: `#84`, `1.320 minutes`, dated `05/21/26`, log `records/track_1_short/2026-05-19_FP8MLPUpProj/this_record/008bb79d-d5bc-4205-bd4e-5e4ae82e658c.txt`, PR `#306`;
- checked log final line: `step:1485/1485 val_loss:3.2802 train_time:83855ms step_avg:56.47ms`;
- README-level data claim: under 400M tokens;
- validation tokens in checked hyperparameters: `10485760`.

Absorption:

- this is the first external training-efficiency comparator row for `B0-MODNANO-TRAINING-EFFICIENCY-RULER`;
- it is not same-hardware with Ember's single-4090 claim;
- local recomputation is not justified unless a contract requires same-hardware normalization or parser validation.

## BabyLM Comparator Row

Primary source inspected:

- site: `https://babylm.github.io/`
- site source HEAD checked by `git ls-remote`: `2142c4c2b222b392cdc5c576d7ceede987453725`

Pinned facts from site:

- BabyLM 2026 is the fourth year of the challenge;
- core goal: sample-efficient pretraining under human-scale data budgets;
- Strict dataset: detoxified 100M words;
- Strict-Small dataset: detoxified 10M words;
- MultiLingual track focuses on English, Dutch, and Chinese with custom mixture totaling 100M tokens;
- compute/epoch limit: competition entries may not conduct more than 10 epochs over training data;
- evaluation pipeline: `https://github.com/babylm-org/babylm-eval`;
- official leaderboard: `https://huggingface.co/spaces/BabyLM-community/BabyLM-Leaderboard-2026`.

Absorption:

- BabyLM is the sample-efficiency anchor, not a substitute for Modded-NanoGPT speed, >=1B 4090 feasibility, growth law, CLI, or goal-mode claims.
- Final `/baseline` must pin evaluator commit and selected track before any Ember run.

## Required Follow-Up

1. Create one source-metadata receipt per high-signal fragment class.
2. Add contracts for local update-rule scaling and proxy-speedrun only if they become active claim families.
3. Refresh current private dirty receipts for C-EFF/C-GROW before using any private-only claim.
4. Update public/private parity report so scrubbed public evidence and private dirty evidence are not confused.
5. Before promotion, rerun this search and store a machine-readable fragment index.
6. Pin Codex, Claude Code, and Hermes-class versions/sources before any C8 run.
7. Resolve DSpark as DeepSpec/DSpark before any C3/C8 run, and keep it scoped to speculative decoding unless same-axis training receipts prove transfer.
