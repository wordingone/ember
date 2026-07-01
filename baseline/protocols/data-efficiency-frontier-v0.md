# Data-Efficiency Frontier Protocol V1

Status: BASELINE_COMPLETE for the `data_efficiency_sota` family only.
Created: 2026-06-29.

This protocol covers frontier claims where the main achievement is reduction in data, examples, synthetic datasets, or compute needed to reach useful capability. It is a lane-selection and anti-transfer protocol, not an Ember win receipt.

## Pinned Frontier Lanes

| Lane | Source rows | What it controls | Scope limit |
|---|---|---|---|
| DE-LM-BABYLM | `babylm-2026` | Fixed-data language-model sample efficiency under strict-small 10M-word and strict 100M-word BabyLM-style budgets, evaluator commit `02b56cbc8185de1462da195b54877b4be153fbfe`, and epoch limit 10. | LM/sample-efficiency only; leaderboard snapshot and selected metric suite must be frozen before Ember runs. |
| DE-REASON-HRM | `sapient-hrm`, `hrm-critical-frontier` | Compact reasoning/data-efficiency: HRM-style 27M parameter, 1000-sample, no-pretraining/CoT ARC/Sudoku/Maze axis with critical/successor guardrails. | Reasoning/problem-solving tasks only; not broad LM pretraining or 4090 foundation-model economics. |
| DE-TABULAR-NANOTABPFN | `modded-nanotabpfn` | Tabular foundation-model pretraining speed/data efficiency: one L40S, 0.92 minute record, 81x speedup, 22x fewer synthetic datasets. | Tabular foundation-model task only; cannot substitute for LM pretraining, ARC reasoning, Ember CLI, goal mode, or self-improvement. |

## Transfer Rules

1. A data-efficiency claim must name the unit reduced: examples, words, tokens, synthetic datasets, FLOPs, wall-clock, energy, or human/agent interventions.
2. Each result is lane-local unless a separate same-axis receipt proves transfer.
3. A BabyLM/fixed-data LM win cannot prove tabular foundation-model pretraining or compact reasoning.
4. A compact-reasoning win cannot prove broad language foundation-model economics unless the downstream task family, train/eval split, contamination controls, and adaptation path are the same.
5. A tabular foundation-model speedrun cannot prove language-model pretraining speed.
6. A raw cluster-speed record and a data-efficiency record from a small or task-specialized model are different axes. The baseline must preserve both axes instead of collapsing them into one leaderboard.
7. Ember can claim a better data-efficiency tradeoff only with a pre-registered Pareto axis and numeric threshold.

## Required Receipt Fields

Any Ember data-efficiency run must report:

- selected lane and comparator source rows;
- selected metric suite and threshold frozen before execution;
- training examples, words, tokens, or synthetic datasets consumed;
- model parameters, active trainable parameters, and recurrent/iteration budget if applicable;
- hardware, wall-clock, FLOPs estimate, and energy method if claimed;
- exact train/eval generation process and leakage/contamination check;
- baseline comparator and threshold chosen before the run;
- parser command;
- one PASS/FAIL/INVALID-RUN verdict.

## Current Verdict

DATA_EFFICIENCY_BASELINE_COMPLETE for the data-efficiency comparator-family definition only. It is not an Ember result, not a training-speed result, not a 4090 >=1B ceiling result, and not overall `/baseline` completion.