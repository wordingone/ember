# Data-Efficiency Frontier Protocol V0

Status: DRAFT FILTER, not a pass.
Created: 2026-06-29.

This protocol covers frontier claims where the main achievement is not raw cluster speed but extreme reduction in data, examples, synthetic datasets, or compute needed to reach useful capability.

## Pinned Frontier Anchors

| Anchor | Source | What it controls | Scope limit |
|---|---|---|---|
| Sapient HRM | `https://arxiv.org/abs/2506.21734` | Compact reasoning architecture and data efficiency: 27M parameters, 1000 training samples, no pretraining/CoT data, strong reported ARC/Sudoku/Maze-style results. | Not a broad language foundation-model pretraining result; must be compared on reasoning/problem-solving tasks with contamination and task-generation controls. |
| HRM critical follow-ups | `https://arxiv.org/abs/2601.10679`, `https://arxiv.org/abs/2603.22871`, `https://arxiv.org/abs/2510.00355` | Guardrails and successor frontier for tiny recurrent/latent-dynamics reasoning models. | Prevents treating the first HRM claim as settled; Ember must compare against the current compact-reasoning frontier, not the earliest headline. |
| Modded-nanoTabPFN | `https://arxiv.org/abs/2606.03681` | Tabular foundation-model pretraining speed/data-efficiency: one L40S, 0.92 minute current record, 81x speedup, 22x fewer synthetic datasets. | Tabular foundation-model task only; cannot substitute for LM pretraining, ARC reasoning, or Ember CLI/goal-mode claims. |

## Transfer Rules

1. A data-efficiency claim must name the unit reduced: examples, tokens, synthetic datasets, FLOPs, wall-clock, energy, or human/agent interventions.
2. A small-data reasoning result cannot prove broad foundation-model economics unless the downstream task family, train/eval split, contamination controls, and adaptation path are the same.
3. A tabular foundation-model speedrun cannot prove language-model pretraining speed; it can only constrain Ember if Ember claims tabular/meta-learning/data-efficiency transfer.
4. A raw speed record from a huge cluster and a data-efficiency record from a tiny model are different axes. The baseline must preserve both axes instead of collapsing them into one leaderboard.
5. Ember can claim a better data-efficiency tradeoff only with a pre-registered Pareto axis and numeric threshold.

## Required Receipt Fields

Any Ember data-efficiency run must report:

- training examples/tokens/synthetic datasets consumed;
- model parameters, active trainable parameters, and recurrent/iteration budget if applicable;
- hardware, wall-clock, FLOPs estimate, and energy method if claimed;
- exact train/eval generation process and leakage/contamination check;
- baseline comparator and threshold chosen before the run;
- one PASS/FAIL/INVALID-RUN verdict.

## Current Verdict

Sapient HRM and modded-nanoTabPFN are now required frontier anchors for data-efficiency-aware Ember claims. They are scope-limited anchors, not universal substitutes for single-4090 >=1B language pretraining.