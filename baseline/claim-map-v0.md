<!-- goal_id: EMBER-02 -->
<!-- workstream_id: EMBER-02A -->
<!-- next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember -->
# Ember Claim Map V0

Status: DRAFT Rung 2 projection, not a result.
Access date: 2026-06-29.

This file maps current Ember surfaces to external baseline claims. It exists to prevent proxy wins from spreading into unrelated claims.

## Current Ember Surfaces Observed

Evidence inspected:

- `<exec-tree>\README.md`: Ember is a local training/improvement substrate; every claimed gain must survive held-out eval, beat matched control, disappear under deletion, persist across process boundaries, and be proven by receipts.
- `<exec-tree>\GOAL.md`: current integrated goal spans cockpit, visible/steerable training, M10 CLI margin, research harness, repo legibility, signature surfaces, and hard-problem tracking. Completion requires fresh receipts, 100% tally, C8 field-level receipt, and C-SCALE receipt.
- `<exec-tree>\configs\v0-pretrain-config.json`: historical `ember-v0` c03 config, 368,354,304 base parameters excluding MTP plus 65,536,000 parameters in two independent auxiliary heads = 433,890,304 declared realized parameters; seq 1024, hidden 1024, 20 layers, 16 heads, bf16 base, QAT enabled, Muon/AdamW split, WSD schedule, 6.973B real tokens, historical 7.367B base-only token target, 4090-governed VRAM fraction 0.80.

> **[ACCOUNTING ERRATUM]** The heads are independent hidden-to-vocabulary projections, not DeepSeek sequential MTP and not a speculative drafter. See `docs/mtp-parameter-accounting-and-mechanism-identity-v1.md`. Live ownership and pricing proof remains #688.
- `<exec-tree>\configs\v0-multimodal-config.json`: multimodal extension with reserved ids 0-7, image soft-token path, 2D RoPE, qk_norm, vision embedder, and missing/build notes for `inputs_embeds` and bidirectional spans.

## Claim Families

| Claim ID | Ember surface | Implied claim | External comparator | Primary rejection criterion | Current status |
|---|---|---|---|---|---|
| C0-EFF | v0 pretraining efficiency | Ember's stack can train more efficiently than naive or older local LM practice. | Modded-NanoGPT for external speed ruler; AlgoPerf for time-to-result rules. | No PASS unless Ember reaches a locked loss/capability target under declared tokens/time/VRAM and beats or gives a pre-registered numeric tradeoff against comparator. | UNSATISFIED. Existing C-EFF history is not a fresh external-baseline PASS. |
| C1-4090-1B | Local foundation-model economics | A single 4090 can train a >=1B active-parameter foundation-model-scale system in days, not years, if all known optimizations are used. | RTX 4090 roofline plus scaling-law compute floor, then local throughput probe. | If sustained measured throughput cannot meet <=14 days for the declared token/capability target, the claim is FAIL or must use a stricter alternate training-type label. | UNSATISFIED. Historical v0 declares 433.9M realized parameters (368.4M base excluding MTP), below >=1B. |
| C2-SAMPLE | Sample efficiency | Ember's data, curriculum, architecture, or loop improves capability per token. | BabyLM 10M/100M word tracks. | No BabyLM/proxy win may imply 4090 >=1B or growth-law success. | UNLOCKED BUT NOT RUN. |
| C3-ARCH | Architecture/kernels | Nonstandard components such as QAT, MTP, Muon split, qk_norm, multimodal soft tokens, or attention/state changes produce measurable gains. | Component-specific ablations and external prior baselines; AlgoPerf style rule discipline. | A component only counts if ablation removes the gain under equal budget and preserved functionality. | PARTIAL PLUMBING ONLY. |
| C4-GROW | Growth law / keystone | Function-preserving growth and compounding beat fixed-size and random-growth controls. | Matched fixed-size, scratch, random-growth, and iso-FLOP controls. | Proxy, toy, or confounded growth runs cannot prove keystone. | UNSATISFIED; current GOAL describes C-GROW attempted but not earned. |
| C5-LOOP | Self-improvement loop | Ember can propose changes, run experiments, read receipts, update itself, and improve the next run better than a baseline loop. | MLE-bench, MLAgentBench, AI Scientist-style local equivalent. | Self-graded loop wins are invalid; must beat baseline under equal budget or produce a verified improvement baseline misses. | UNSATISFIED. |
| C6-CLI | Ember CLI/runtime | CLI can create, run, resume, inspect, verify, steer, and package governed experiments. | Mature experiment tooling standards plus intentionally failed/interrupted local protocol. | Happy-path success only is invalid. | PARTIAL surface receipts exist in GOAL; baseline protocol not passed. |
| C7-GOAL | Goal mode | Goal mode prevents drift, cheating, vague progress, and premature completion better than a checklist/chat transcript. | Ordinary checklist/chat transcript baseline plus independent verifier. | A neat checklist is not a pass unless it rejects at least one concrete premature-completion path. | UNSATISFIED. |
| C8-REPRO | Reproducibility/publication | Ember claims can survive skeptical external review. | Publication packet standard: methods, configs, receipts, negative results, replication. | No public claim without external anchor refresh, negative results, and replay path. | NOT READY. |

## First Concrete Baseline Task

Default first task: `B0-modnano-training-efficiency-ruler`.

Uncheatable form:

Build or run Ember training artifact `X` that is compared against Modded-NanoGPT `Y` on time/tokens to a locked language-model validation target `Z`, by a predeclared threshold or Pareto tradeoff `T`, preserving hardware/data/accounting constraints `C`, under a one-4090 budget `B`, verified by a parser `V`, producing PASS, FAIL, or INVALID-RUN.

Important boundary: this first task does not claim >=1B feasibility, BabyLM sample efficiency, growth law, self-improvement, CLI, or goal-mode success. Those get separate contracts.
## Inference-To-Training Boundary

The C3-ARCH family now has an explicit transfer filter: `protocols/inference-to-training-transfer-v0.md`.

This matters because DSpark/DeepSpec, DeepSeek-style MTP, MLA, speculative decoding, DeepGEMM, FlashMLA, DualPipe, DeepEP, EPLB, 3FS, TileKernels, and related infra are not one interchangeable bucket. An inference or speculative-decoding win can baseline sampler, draft-model, or agent-loop cost, but it cannot prove one-4090 pretraining speed, sample efficiency, or >=1B feasibility without a same-axis receipt.

The DSpark miss is itself recorded as a baseline coverage failure mode: the first search looked for a standalone repository and missed DSpark inside DeepSpec. Future frontier sweeps must search nested repo/config/paper/checkpoint surfaces, not only exact repo names.
## Data-Efficiency Boundary

Sapient HRM and modded-nanoTabPFN are now explicit data-efficiency frontier anchors. They correct a stale/shallow baseline shape that over-emphasized raw LM speedrun and general sample-efficiency anchors while under-representing least-compute capability claims.

They do not collapse into one generic foundation-model record. HRM is a compact recurrent reasoning/data-efficiency anchor; modded-nanoTabPFN is a tabular foundation-model pretraining speedrun anchor. Ember must beat them only on matching task axes, or name a pre-registered Pareto tradeoff that preserves task, data, hardware, and capability constraints.