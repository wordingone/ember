# Ember Baseline Report V0

Status: NOT COMPLETE.

## Abstract Claim

No Ember field-level baseline claim is established yet. This report is a staging draft for the eventual dual-repo `/baseline` packet.

## Current Evidence

- External anchors have been identified and first source pins have been recorded for Modded-NanoGPT, BabyLM, AlgoPerf, RTX 4090, MLE-bench, MLAgentBench, AI Scientist, Codex, Claude Code, and a Hermes-class NeMo Agent Toolkit placeholder.
- Ember claim families have been mapped.
- A 4090 ceiling draft separates compute floor, memory feasibility, and capability target.
- Self-improvement, CLI, and goal-mode draft protocols exist; C5 zero-spend task subset has a static PASS receipt, C5-0B nanoGPT_lite data-prep PASS receipt, and C5-0B bounded smoke PASS receipt.
- DSpark/DeepSpec has been corrected and pinned: DSpark is a DeepSpec speculative-decoding draft-model algorithm at `deepseek-ai/DeepSpec`, not a direct single-4090 foundation-training proof. `protocols/inference-to-training-transfer-v0.md` now blocks free transfer.
- Sapient HRM and modded-nanoTabPFN have been added as extreme data-efficiency anchors; `protocols/data-efficiency-frontier-v0.md` prevents cross-task laundering.
- Verdict, line-ending, manifest, source-ledger, reference-extraction, C5 static-check, C5 baseline-readiness, and promotion-readiness scripts exist.

## Missing Before Completion

- full baseline-run receipts and exact thresholds for the selected C5 zero-spend subset; C5-0A still needs isolated CLRS dependencies before baseline execution, while C5-0B has only a smoke-reduced PASS receipt;
- locked numeric thresholds for each active claim family;
- governed Ember-vs-baseline trial;
- parser output for real receipts;
- public/private `/baseline` promotion and remote refs or PR URLs;
- manifest hashes and line-ending receipts in both repos.

## Latest Mechanical Checks

- Source ledger validation receipt: `receipts/source-ledger-validation-2026-06-29.json`; current verdict PASS.
- Promotion readiness receipt: `receipts/promotion-readiness-2026-06-29.json`; current verdict INVALID-RUN because the packet is not yet ready for dual-repo publication.
- C5 static subset receipt: `receipts/c5-subset-static-check-2026-06-29.json`; current verdict PASS for task-file/static-hook presence only, not an improvement run.
- C5 baseline readiness receipt: `receipts/c5-baseline-readiness-2026-06-29.json`; current verdict INVALID-RUN because C5-0A lacks CLRS dependencies, while C5-0B is baseline-ready on the local RTX 4090.
- C5 nanoGPT_lite data-prep receipt: `receipts/c5-nanogpt-lite-data-prep-2026-06-29.json`; current verdict PASS.
- C5 nanoGPT_lite smoke receipt: `receipts/c5-nanogpt-lite-smoke-2026-06-29.json`; current verdict PASS for a deliberately reduced 3-iteration smoke, not a baseline score.
- DSpark/DeepSpec resolution receipt: `receipts/deepseek-dspark-resolution-2026-06-29.json`; current verdict RESOLVED_SOURCE_IDENTITY_SCOPE_LIMITED.
- Sapient HRM data-efficiency receipt: `receipts/sapient-hrm-data-efficiency-frontier-2026-06-29.json`; current verdict SOURCE_PINNED_SCOPE_LIMITED_NEEDS_RECORD_ADJUDICATION.

## Current Verdict

NOT COMPLETE. Local staging files cannot satisfy the goal.