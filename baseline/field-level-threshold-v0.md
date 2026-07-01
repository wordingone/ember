# Field-Level Contribution Threshold V1

Status: BASELINE_COMPLETE for the threshold-definition family only.
Claim family: `field_level_contribution_threshold`.
Access date: 2026-06-29.

This file does not claim Ember has beaten a baseline. It defines the exact standard that a future Ember result must satisfy before it can be called a field-level contribution candidate. The overall `/baseline` remains incomplete until every other mandatory family is complete, the final verifier passes in both remotes, and post-artifact operator acceptance exists.

## Decision Rule

A future Ember result is a field-level contribution candidate only if all of the following are true:

1. It beats the completed `/baseline` on at least one primary axis in the table below.
2. It preserves every constraint for that axis.
3. It does not regress reproducibility/publication requirements.
4. It survives the listed falsifiers.
5. It has dual-repo remote proof and operator acceptance after the final artifacts exist.

A result is local progress, not a field-level candidate, if it is a smoke run, one governed trial only, one negative result only, static/data-prep/source-ledger/docs-only evidence, a proxy transfer across families, an unpinned or stale comparator, or a result without exact hardware/wall-clock/token/FLOP/memory/capability accounting.

## Primary Axis Contracts

| Axis ID | Field-level claim candidate | Required comparator | Metric | Threshold | Constraints | Budget | Verifier | Falsifier |
|---|---|---|---|---|---|---|---|---|
| FL-4090-1B | Individual days-scale >=1B foundation-model or pretraining-equivalent training on one consumer GPU is possible with Ember's stack. | Strongest sourced one-RTX-4090 or theoretical 1B active/trainable-parameter ceiling in `4090-ceiling-v0.md`. | `days_to_declared_capability`, sustained training TFLOP/s, memory fit, tokens, and capability suite score. | Ember must meet the declared capability target within the locked days tier and beat the comparator's wall-clock/capability Pareto point without hidden compute. | One RTX 4090-class 24GB GPU, exact model/config, exact data, no hidden hosted compute, replayable receipts, source-pinned software. | Budget in `4090-ceiling-v0.md` contract, including setup, data prep, eval, restarts, and packaging. | `baseline/scripts/verify_completion.py` plus 4090 family receipts. | Equal-budget external comparator matches or beats; memory accounting omits activations/optimizer/offload; wall-clock excludes required time; capability target is vague or unreplayable. |
| FL-TRAIN-EFF | Ember materially improves training time/compute/energy to a declared LM target. | Modded-NanoGPT-family record or stronger current same-axis training-efficiency comparator. | Time-to-target, tokens, FLOPs, estimated energy/power, validation loss or capability score. | Ember must beat the comparator or a pre-registered Pareto threshold under matched accounting. | Same or normalized hardware/data/accounting; exact source pins; no benchmark substitution after seeing results. | Locked compute-spend packet for the family. | Training-efficiency protocol receipt and parser. | Comparator is stale; run uses easier target/data; hidden tuning budget; result is only a smoke/static check. |
| FL-DATA-EFF | Ember improves capability per token/example/compute against current data-efficiency frontier. | BabyLM, Sapient HRM-style compact reasoning, modded-nanoTabPFN, or stronger same-axis successor. | Capability per token/example, task score, data volume, compute. | Ember must beat the same-axis comparator or a pre-registered Pareto threshold without cross-task laundering. | Task/data axis preserved; contamination/dedupe recorded; source pins and eval versions locked. | Locked family budget. | Data-efficiency protocol receipt and parser. | Tabular/reasoning win is transferred to LM/multimodal claim; comparator not same-axis; data leakage. |
| FL-ARCH-GROW | Ember's architecture/growth/keystone mechanism causes a durable gain. | Fixed-size, scratch, random-growth, iso-FLOP, and same-axis external architecture/kernel comparators. | Capability/loss/efficiency delta and deletion-test effect. | Ember must beat controls and lose the gain when the claimed mechanism is deleted. | Matched data/compute/hardware; no confounded growth; transfer filter for inference-only mechanisms. | Locked architecture/growth budget. | Architecture/growth protocol receipt and deletion-test parser. | Deletion does not remove gain; inference-only optimization is credited as training improvement; random/fixed control matches result. |
| FL-SELF-IMPROVE | Ember's loop improves future runs better than external/local agentic ML research baselines. | MLE-bench, MLAgentBench, AI Scientist-style systems, Codex-class and external coding-agent-B-class loop references where legally/publicly safe. | Verified improvement discovered per budget, receipt quality, replay rate, negative-result handling. | Ember must produce a verified improvement a baseline misses, or beat equal-budget loop score under the locked rubric. | Equal budget; external scoring or deterministic local verifier; no self-graded wins; no hidden human intervention. | Locked self-improvement/local-agentic budget. | Self-improvement and local-agentic receipts. | Baseline loop finds same improvement; result is hand-authored without loop causality; receipt parser cannot replay. |
| FL-RUNTIME-GOV | Ember CLI and goal mode provide stronger governance/reproducibility than ordinary transcript/checklist control. | Mature experiment tooling plus ordinary checklist/chat-transcript baseline. | Create/run/resume/inspect/verify/package/replay success, interruption recovery, premature-completion rejection. | Ember must pass happy-path and adversarial premature-completion cases while preserving replay/provenance. | Public/private parity, line-ending stability, manifest hashes, exact receipts, no hidden dirty-tree dependence. | Locked runtime/governance budget. | CLI, goal-mode, line-ending, parity, and completion-lock verifiers. | Checklist baseline rejects same failures; replay impossible; docs and lock disagree; verifier only checks file presence. |

## Mandatory Downgrade Cases

The result must be described as local progress, not a field-level candidate, if any of these hold:

- only one governed trial exists;
- only one negative result exists;
- the evidence is static-only, smoke-only, data-prep-only, source-ledger-only, or docs-only;
- any primary family is absent, deferred, optional, or out of scope;
- the single-4090 >=1B theoretical ceiling is absent or stale;
- operator acceptance after final artifacts is absent;
- public/private remote proof is absent;
- line endings or manifest hashes are unstable;
- an equal-budget comparator matches or beats the result.

## Completion Boundary For This File

This threshold-definition family is complete when `baseline/scripts/validate_field_threshold.py` verifies that every axis above contains a comparator, metric, threshold, constraints, budget, verifier, and falsifier, and when the receipt is referenced by `completion-lock.json`.

This file's completion does not complete the overall baseline.
