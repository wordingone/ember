# Self-Improvement Loop Baseline V0

Status: DRAFT. No self-improvement claim is granted.
Claim family: C5-LOOP.

## Purpose

Test whether Ember's loop improves experiments, code, data, or architecture better than a baseline agent or scripted search under the same budget.

## External Anchor Families

- MLE-bench: ML-engineering tasks with competition-style scoring.
- MLAgentBench: agent ML-experimentation tasks.
- AI Scientist-style systems: automated idea, code, experiment, writeup, and review loops.

These anchors now have source pins. The first local zero-spend subset is selected in `protocols/c5-zero-spend-subset-v0.md`; governed runs still have not executed.

## Contract

Build or run Ember loop `X` that beats baseline loop `Y` on external ML task set `Z` by threshold `T`, preserving equal tool/data/compute/time/human-intervention constraints `C`, under budget `B`, verified by deterministic scorer or reviewer protocol `V`, producing PASS, FAIL, or INVALID-RUN.

## Baseline Loop Candidates

1. Fixed script/search baseline:
   - deterministic hyperparameter or patch search;
   - same task budget;
   - no natural-language planning advantage.

2. Ordinary agent/chat baseline:
   - same tools and wall-clock;
   - no Ember-specific receipt substrate;
   - transcript retained.

3. Prior external benchmark baseline:
   - only if source conditions are exact enough to avoid wasteful recomputation.

4. Frontier agent-loop baseline:
   - Codex, Claude Code, and Hermes-class systems are first-class comparators for research loops, goal mode, CLI operation, tool execution, and code-modification workflows;
   - hidden frontier self-training or successor-model claims remain hypotheses unless publicly sourced or locally receipted;
   - visible capabilities can still be measured through frozen replay suites with identical files, tools, budgets, receipts, and task statements.

## Required Metrics

- final score improvement over starting point;
- improvement over baseline loop;
- number of valid experiments;
- number of invalid or non-reproducible experiments;
- receipt completeness;
- whether the winning change survives deletion/ablation or replay checks;
- whether negative results are preserved.

## Anti-Cheat Gates

- no self-graded victory;
- no hosted paid judge as required authority;
- no private hidden labels in candidate path;
- no changing task or metric after seeing Ember output;
- no counting prose insight as improvement without executed evidence;
- no loop win unless the baseline had equal opportunity to find the improvement.

## Current Verdict

NOT RUN. The C5-0 zero-spend subset selects MLAgentBench CLRS and AI Scientist nanoGPT_lite/shakespeare_char as first local tasks, while deferring MLE-bench full/lite until a compute-spend packet justifies Kaggle/data cost. The next step is static environment checks and baseline-run receipts for those selected tasks.
