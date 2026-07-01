# Ember Baseline Report V1

Status: OVERALL INCOMPLETE PENDING OPERATOR ACCEPTANCE.

## Abstract Claim

The `/baseline` directory now defines the mandatory external/theoretical comparator families for Ember and publishes them through the shared public/private branch. It is still not a completed goal because explicit post-artifact operator acceptance is absent and Ember has not beaten these baselines.

## Current Evidence

- External anchors and source pins are recorded in `sources.jsonl` with access dates.
- The 4090 ceiling report records the days-scale theoretical envelope for >=1B active/trainable parameters on one RTX 4090-class GPU.
- Training-efficiency, data-efficiency, architecture/growth, self-improvement, local-agentic research, CLI runtime, goal-mode, 4090 ceiling, publication-surface, and field-level-threshold families each have a contract and validator or audit receipt.
- DSpark/DeepSpec is scoped as speculative-decoding/draft-model infrastructure, not free training-speed proof.
- Sapient HRM and modded-nanoTabPFN are included as data-efficiency anchors with scope limits.

## Latest Mechanical Checks

- Source ledger validation receipt: `receipts/source-ledger-validation-2026-06-29.json`; current verdict PASS with the current source ledger row count.
- Line-ending validation receipt: `receipts/line-endings-validation-2026-06-29.json`; current verdict PASS.
- 4090 ceiling calculation receipt: `receipts/4090-ceiling-calculation-2026-06-29.json`; current verdict CALCULATION_RECEIPT_NOT_COMPLETION.
- 4090 throughput probe receipt: `receipts/4090-throughput-probe-2026-06-29.json`; current verdict THROUGHPUT_PROBE_NOT_COMPLETION, with local fp16 matmul 154.74 TFLOP/s and tiny bf16 transformer-step estimate 9.97 TFLOP/s.
- 4090 ceiling validation receipt: `receipts/4090-ceiling-validation-2026-06-29.json`; current verdict SINGLE_4090_ENGINEERING_BASELINE_SURFACE_READY for the single-4090 engineering/theoretical comparator family only.
- Training-efficiency validation receipt: `receipts/training-efficiency-validation-2026-06-29.json`; current verdict TRAINING_EFFICIENCY_BASELINE_COMPLETE for the training-efficiency comparator family only.
- Data-efficiency validation receipt: `receipts/data-efficiency-validation-2026-06-29.json`; current verdict DATA_EFFICIENCY_BASELINE_COMPLETE for the data-efficiency comparator family only.
- Architecture/growth validation receipt: `receipts/architecture-growth-validation-2026-06-29.json`; current verdict ARCHITECTURE_GROWTH_BASELINE_COMPLETE for the architecture/growth comparator family only.
- Self-improvement validation receipt: `receipts/self-improvement-validation-2026-06-29.json`; current verdict SELF_IMPROVEMENT_BASELINE_COMPLETE for the self-improvement comparator family only.
- Local-agentic research validation receipt: `receipts/local-agentic-research-validation-2026-06-29.json`; current verdict LOCAL_AGENTIC_RESEARCH_BASELINE_COMPLETE for the local-agentic research comparator family only.
- CLI runtime validation receipt: `receipts/cli-runtime-validation-2026-06-29.json`; current verdict CLI_RUNTIME_BASELINE_COMPLETE for the CLI/runtime comparator family only.
- Goal-mode validation receipt: `receipts/goal-mode-validation-2026-06-29.json`; current verdict GOAL_MODE_BASELINE_COMPLETE for the goal-mode comparator family only.
- Field-level threshold validation receipt: `receipts/field-threshold-validation-2026-06-29.json`; current verdict FIELD_THRESHOLD_BASELINE_COMPLETE for the threshold-definition family only.
- Publication-surface validation receipt: `receipts/publication-surface-validation-2026-06-29.json`; current verdict PUBLICATION_SURFACE_BASELINE_COMPLETE for the publication/parity family only.

## Current Verdict

OVERALL INCOMPLETE PENDING OPERATOR ACCEPTANCE. The artifact is not complete until the strict verifier passes and the operator explicitly accepts this exact `/baseline` artifact as the requested ultimate SOTA/theoretical-ceiling baseline.
Benchmark/data readiness is mechanically checked by `scripts/validate_benchmark_data_readiness.py` with receipt `receipts/benchmark-data-readiness-2026-06-30.json`: it verifies pinned benchmark/data substrate, records the MLAgentBench CLRS executable smoke plus upstream and deterministic patch comparators, requires the public-safe negative Ember-vs-nanoGPT trial validation, and preserves remaining MLE-bench/auth and missing Ember candidate gaps without treating readiness as an Ember win.

Additional 4090/native evidence: `receipts/4090-native-kernel-probe-from-scratch.json` and `receipts/4090-native-kernel-probe-from-scratch-parse.json` record bounded Triton/native GEMM telemetry. PyTorch tuned matmul beat the simple Triton kernel on the tested C1 shapes; this is native ceiling evidence, not proof that all lower-level paths are exhausted.

Prior external benchmark evidence: `receipts/external-benchmark-import-validation-2026-06-30.json` verifies imported prior Ember benchmark/access receipts. It records three executed external/public/heldout delta receipts and three blocked/access-gap receipts, preserving both real benchmark work and remaining MLE/Kaggle execution gaps.

Additional C1 LM-loss evidence: `receipts/4090-full-stack-lm-loss-probe-from-scratch.json` and `receipts/4090-full-stack-lm-loss-probe-pretraining-equivalent.json` validate representative all-layer language-model loss steps. They observed about 29.6 lower-bound TFLOP/s, below the locked 50.98 TFLOP/s days-scale requirement, and remain non-completion telemetry.

Additional C1 data evidence: `receipts/4090-data-governance-2026-06-30.json` validates public-safe token-substrate provenance. It supports the 5B pretraining-equivalent token floor while preserving the 10B from-scratch token shortfall and other data-governance gaps.

Additional C1 data-hygiene evidence: `receipts/4090-data-hygiene-audit-2026-06-30.json` and `receipts/4090-data-hygiene-validation-2026-06-30.json` validate an explicit blocking-gap audit. The audit preserves existing source-pin and task-local duplicate evidence while refusing to treat it as corpus-wide dedupe or contamination completion.

Additional C1 exact-dedupe evidence: `receipts/4090-exact-dedupe-scan-2026-06-30.json` and `receipts/4090-exact-dedupe-validation-2026-06-30.json` scan the full pinned token-document stream and validate zero exact duplicate documents. This is not a near-duplicate or contamination pass.

Additional C1 data-hygiene policy evidence: `receipts/4090-data-hygiene-policy-thresholds-2026-06-30.json` and `receipts/4090-data-hygiene-policy-validation-2026-06-30.json` lock scan thresholds before remaining C1 hygiene scans run.

Additional C1 contamination evidence: `receipts/4090-local-heldout-contamination-scan-2026-06-30.json` and `receipts/4090-local-heldout-contamination-validation-2026-06-30.json` validate zero exact 32-token overlaps for the local Ember heldout task file against the full pinned token stream. Full eval-suite and normalized-span contamination remain open.

Additional C5 baseline-executability evidence: `receipts/c5-mlagentbench-clrs-smoke-2026-06-30.json` and `receipts/c5-mlagentbench-clrs-smoke-validation-2026-06-30.json` validate that the pinned MLAgentBench CLRS/floyd_warshall upstream baseline can execute a one-step smoke with checkpoint hashes and a numeric test score under an isolated CLRS environment. `receipts/c5-mlagentbench-clrs-governed-baseline-2026-06-30.json` and `receipts/c5-mlagentbench-clrs-governed-baseline-validation-2026-06-30.json` extend this to a three-seed upstream-baseline comparator with mean test score 0.01531982421875. `receipts/c5-mlagentbench-clrs-deterministic-patch-comparator-2026-06-30.json` and `receipts/c5-mlagentbench-clrs-deterministic-patch-comparator-validation-2026-06-30.json` add an equal-budget deterministic learning-rate patch comparator with mean test score 0.0179290771484375. This is not an Ember improvement and not an Ember governed C5 trial.

Additional real-Ember candidate evidence: `receipts/owned-engine-tool-loop-2026-06-30.json` records a bounded run of the owned checkpoint through the tool loop. The run failed: the model emitted no valid tool calls across the bounded turns and did not create the required output. This is negative candidate evidence and does not count as an Ember improvement or baseline completion.

Additional architecture/growth evidence: `receipts/growth-refutation-import-2026-06-30.json` imports the existing growth-law GPU receipts. It records v4 as a 12-round growth-arm run with four growth events and an insufficient-seed verdict, plus v3 as an eight-round matched-control packet under the earlier jam calibration. This preserves hard negative/partial evidence and prevents recomputing completed rows, but it is not an architecture-growth win.

Additional owned-engine SFT evidence: `receipts/owned-engine-sft-tool-loop-2026-06-30.json` and `receipts/owned-engine-sft-tool-loop-validation-2026-06-30.json` record a 700-step bounded SFT run and heldout tool-loop probe. The trained checkpoint produced six parsed tool observations and created the output file, but wrote empty content instead of the expected count, so the task remains FAIL. This is capability movement, not an external benchmark win.

Additional owned-engine SFT repair-attempt evidence: receipts/owned-engine-sft-v2-tool-loop-2026-06-30.json through receipts/owned-engine-sft-v6-observation-copy-tool-loop-2026-06-30.json plus receipts/owned-engine-sft-repair-attempts-validation-2026-06-30.json record five bounded root-cause repair probes. The sequence moved from no correct output to a normalized loop that can reach the correct COUNT observation of 470, but it still cannot reliably copy that live observation into WRITE. This is a narrowed engineering boundary, not an external benchmark win.

Additional C1 near-duplicate sample evidence: `receipts/4090-near-duplicate-minhash-sample-2026-06-30.json` and `receipts/4090-near-duplicate-minhash-sample-validation-2026-06-30.json` validate a bounded deterministic 50,000-document MinHash sample over the pinned shard stream. It found 25 above-threshold crossing pairs, with max exact Jaccard 0.914169. This is negative/problem evidence and keeps C1 data hygiene incomplete until full-corpus near-duplicate remediation and PASS receipts exist.

Additional C1 near-duplicate sample remediation evidence: `receipts/4090-near-duplicate-sample-remediation-2026-06-30.json` and `receipts/4090-near-duplicate-sample-remediation-validation-2026-06-30.json` turn the 25 above-threshold sample crossing pairs into 4 deterministic clusters and 24 sample-document exclusions covering at least 38,772 tokens. This is problem-reduction evidence only; C1 remains incomplete until the full corpus is scanned, remediated, and validated with PASS receipts.

Additional C1 targeted near-duplicate expansion evidence: `receipts/4090-near-duplicate-targeted-expansion-2026-06-30.json` and `receipts/4090-near-duplicate-targeted-expansion-validation-2026-06-30.json` rescan the full pinned shard stream and expand the discovered sample clusters to 1,668 exclusion documents covering at least 2,949,980 tokens. This is a stronger remediation packet for known clusters, not an all-pairs near-duplicate pass and not C1 completion.

Additional C5 nanoGPT deterministic comparator evidence: `receipts/c5-nanogpt-deterministic-patch-comparator-2026-06-30.json` and `receipts/c5-nanogpt-deterministic-patch-comparator-validation-2026-06-30.json` validate a governed same-budget deterministic patch comparator for AI Scientist nanoGPT_lite/shakespeare_char. The comparator changed learning rate and dropout under the same bounded two-seed budget and improved best validation loss by 4.834809830300841% versus the upstream bounded control. `receipts/c5-ember-vs-nanogpt-governed-trial-2026-06-30.json` and `receipts/c5-ember-vs-nanogpt-trial-validation-2026-06-30.json` now bind that comparator to a public-safe Ember-vs-external trial receipt; the trial is validated negative evidence because the governed Ember candidate receipt is missing. This is not an Ember improvement and not overall completion.
