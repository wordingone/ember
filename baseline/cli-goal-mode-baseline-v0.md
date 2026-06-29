# CLI And Goal-Mode Baseline V0

Status: DRAFT. No CLI or goal-mode claim is granted.
Claim families: C6-CLI and C7-GOAL.

## Purpose

Test whether Ember's CLI and goal mode create a better final evidence state than an ordinary checklist or chat transcript on the same governed task.

## CLI Contract

Build or run Ember CLI flow `X` that beats baseline experiment workflow `Y` on create/resume/inspect/verify/package metric `Z` by threshold `T`, preserving reproducibility, failure provenance, and compute constraints `C`, under budget `B`, verified by protocol `V`, producing PASS, FAIL, or INVALID-RUN.

## Goal-Mode Contract

Build or run Ember goal mode `X` that beats ordinary checklist/chat transcript `Y` on drift-prevention and premature-completion rejection metric `Z` by threshold `T`, preserving same task, evidence, time, and reviewer constraints `C`, under budget `B`, verified by independent deterministic checker or reviewer protocol `V`, producing PASS, FAIL, or INVALID-RUN.

## Required CLI Flow

The protocol must include:

1. create a governed run;
2. resume after interruption;
3. inspect current state;
4. verify receipts;
5. classify PASS/FAIL/INVALID-RUN;
6. package evidence for another reviewer;
7. handle at least one intentionally failed run correctly.

## Required Goal-Mode Evidence

Goal mode must reject at least one concrete premature-completion path, such as:

- missing external comparator;
- stale source pin;
- near-miss result framed as PASS;
- local-only baseline claimed as complete;
- private-only evidence used for public claim;
- no line-ending verification for scripts or schemas.

## Metrics

- completeness of final evidence packet;
- number of invalid claims correctly rejected;
- reproducibility from a clean checkout;
- time to resume after interruption;
- whether failure is explained without hiding missing evidence;
- whether parser emits one canonical verdict.

## Current Verdict

NOT RUN. The CLI and goal-mode surfaces remain unsatisfied until this protocol runs and produces a governed verdict.
