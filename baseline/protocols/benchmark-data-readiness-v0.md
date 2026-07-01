# Benchmark And Data Readiness Protocol V0

Status: BENCHMARK_DATA_READINESS_BASELINE_READY when `baseline/scripts/validate_benchmark_data_readiness.py` passes.
Created: 2026-06-30.

This protocol answers whether Ember has enough pinned benchmark and dataset substrate to run proper governed baseline comparisons. It is not an Ember win receipt and not a substitute for full benchmark execution.

## Readiness Classes

- `SOURCE_PINNED`: external benchmark, paper, repo, or leaderboard source exists in `sources.jsonl` with access date, commit/version where available, and scope limits.
- `DATA_PREP_PASS`: local data artifacts exist with hashes and token/example counts.
- `SMOKE_PASS`: short run proves import/runtime/output shape only.
- `BASELINE_RUN_READY`: full baseline run may be launched under a compute-spend packet.
- `REQUIRES_ISOLATED_ENV`: source is pinned but the current Python environment is not the right execution environment.
- `AUTH_AND_DATA_GOVERNANCE_REQUIRED`: source is pinned but credentials, consent, storage, or dataset download policy must be settled before execution.

## Current Benchmark/Data Substrate

- BabyLM 2026 is source-pinned for fixed-data LM sample-efficiency lanes. The exact track, metric suite, and leaderboard snapshot must be frozen before an Ember run.
- Sapient HRM and HRM-critical successor/guardrail sources are pinned for compact reasoning/data-efficiency lanes.
- modded-nanoTabPFN is pinned for tabular foundation-model pretraining efficiency, scoped away from broad LM pretraining.
- modded-nanoGPT and MLCommons AlgoPerf are pinned for training-efficiency/time-to-result discipline.
- AI Scientist `nanoGPT_lite/shakespeare_char` has local data-prep PASS and CUDA readiness PASS.
- MLAgentBench CLRS is source-pinned, isolated-env readiness PASS, has a one-step executable smoke receipt, a three-seed upstream-baseline comparator receipt, and an equal-budget deterministic patch comparator receipt with checkpoint hashes and numeric test scores. It is still not an Ember governed improvement trial.
- MLE-bench is source-pinned but requires auth/data governance and a compute packet before execution.

## Required Command

```powershell
python baseline\scripts\validate_benchmark_data_readiness.py --root baseline --out baseline\receipts\benchmark-data-readiness-2026-06-30.json --pretty
```

## Completion Limit

A PASS here means the benchmark/data substrate is sufficient to define proper governed comparisons and that known execution gaps are explicit. It does not mean Ember has run or beaten those benchmarks.
