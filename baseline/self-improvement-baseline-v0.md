# Self-Improvement Loop Baseline V1

Status: BASELINE_COMPLETE for the `self_improvement_loop_sota` family only. No Ember self-improvement win is granted.
Claim family: `self_improvement_loop_sota`.
Access date: 2026-06-29.

## Purpose

This file locks the outside ruler for Ember's self-improvement loop: proposing changes, running experiments, reading receipts, updating code/data/architecture, preserving negative results, and improving future runs under equal budget.

## External Anchor Families

- `mle-bench`: ML-engineering tasks with competition-style scoring and data/auth cost boundaries.
- `mlagentbench`: ML-experimentation tasks; CLRS is the first zero-spend local task source.
- `ai-scientist`: automated idea/code/experiment/writeup/review loop; only local `nanoGPT_lite/shakespeare_char` mechanics are used at C5-0.
- `ai-scientist-v2`: successor automated research-loop anchor that prevents stale comparison only to the original AI Scientist.
- `kosmos-ai-scientist`: broad autonomous scientific-discovery guardrail that prevents small local C5-0 tasks from being overclaimed as field-level autonomous science.

## Baseline Loop Arms

Every governed C5 run must compare Ember against:

1. unchanged upstream baseline/run_0;
2. deterministic scripted/search baseline with equal compute and wall-clock budget;
3. agent baseline only after C8 fixture is locked;
4. sourced no-recompute comparator where exact external conditions are sufficient and recomputation would waste budget.

## Required Metrics

- final score improvement over starting point;
- improvement over unchanged and deterministic/scripted baselines;
- number of valid experiments;
- number of invalid or non-reproducible experiments;
- receipt completeness;
- whether the winning change survives deletion/ablation or replay checks;
- whether negative results are preserved;
- whether the claim is scoped to local ML-engineering loop or broad scientific-discovery loop.

## Anti-Cheat Gates

- no self-graded victory;
- no hosted paid judge as required authority;
- no private hidden labels in candidate path;
- no changing task or metric after seeing Ember output;
- no counting prose insight as improvement without executed evidence;
- no loop win unless the baseline had equal opportunity to find the improvement;
- no transferring C5-0 local task success into broad scientific-discovery or field-level claims.

## Current Verdict

SELF_IMPROVEMENT_BASELINE_COMPLETE for the self-improvement comparator-family definition only. Existing C5-0 static/data-prep/smoke receipts remain wiring evidence, not an Ember improvement result and not overall `/baseline` completion.

C5 nanoGPT_lite deterministic patch comparator evidence exists in `receipts/c5-nanogpt-deterministic-patch-comparator-2026-06-30.json` with validation receipt `receipts/c5-nanogpt-deterministic-patch-comparator-validation-2026-06-30.json`. It gives the C5-0B lane a same-budget non-agent comparator that improved bounded validation loss by 4.834809830300841% over the upstream control. The public-safe Ember-vs-nanoGPT trial receipt in `receipts/c5-ember-vs-nanogpt-governed-trial-2026-06-30.json`, validated by `receipts/c5-ember-vs-nanogpt-trial-validation-2026-06-30.json`, is negative evidence: no governed Ember candidate receipt exists yet. An Ember candidate must beat this comparator under the same governed receipt contract before any C5-0B improvement claim.
