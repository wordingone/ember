# C5 Zero-Spend Self-Improvement Subset V0

Status: DRAFT LOCK CANDIDATE.
Access date: 2026-06-29.
Claim family: C5-LOOP.

## Purpose

This file converts the self-improvement anchors from vague candidates into a first local, zero-spend subset. It is not an Ember PASS claim. It defines the cheapest serious task set that can test whether an agent loop improves experiments/code under equal budget before paying the cost of full MLE-bench or hosted judges.

## Source Pins

| Source | Replay handle | Commit | Decision |
|---|---|---|---|
| MLE-bench | external clone at pinned commit | `507f92e1138bb6e40dac5c6ee7a6758e6424bf97` | Not first-run subset. Lite split is documented, but still uses Kaggle competitions, credentials/consent, and large data; use later when compute/data budget is justified. |
| MLAgentBench | external clone at pinned commit | `5d71205cc20a8e95d43aa7cb7120e89ca3323e31` | Primary local task source. Select CLRS because it is algorithmic, generated, scored by local scripts, and directly tests code/architecture improvement loops. |
| AI Scientist | external clone at pinned commit | `1de1dbc1f4ee2c5f61e9c94348d55eb51d7fa2eb` | Secondary local task source. Select `nanoGPT_lite`/`shakespeare_char` baseline mechanics because it matches Ember's LM-training thread and has local experiment/plot artifacts. |

## Selected C5-0 Task Set

### C5-0A: MLAgentBench CLRS Local Improvement

Uncheatable shape:

Run Ember loop `X` against baseline agent/script `Y` on MLAgentBench CLRS `Z`, improving local evaluation score by threshold `T`, preserving the CLRS task interface and loadable baseline model constraints `C`, under wall-clock/tool/patch budget `B`, verified by MLAgentBench eval script plus receipt parser `V`.

Initial threshold candidate:

- `T0`: produce a valid code change and receipt that improves final score over unchanged baseline by any positive delta under one seed.
- `T1`: improve by >=2 percentage points mean score across three governed seeds.
- `T2`: improve by >=5 percentage points mean score across three governed seeds without increasing runtime >25%.

`T0` is only an admission smoke. Publication comparisons require `T1` or stricter. T0 is only an admission smoke.

Current execution readiness: PASS for import/readiness under the isolated CLRS environment; CLRS executable smoke PASS in `receipts/c5-mlagentbench-clrs-smoke-2026-06-30.json`; three-seed upstream-baseline comparator PASS in `receipts/c5-mlagentbench-clrs-governed-baseline-2026-06-30.json`; equal-budget deterministic patch comparator PASS in `receipts/c5-mlagentbench-clrs-deterministic-patch-comparator-2026-06-30.json`; and owned engine candidate FAIL in `receipts/owned-engine-tool-loop-2026-06-30.json`. This is not an Ember governed improvement trial.

### C5-0B: AI Scientist nanoGPT_lite Local Research Loop

Uncheatable shape:

Run Ember loop `X` against baseline agent/script `Y` on AI Scientist `nanoGPT_lite`/`shakespeare_char` experiment `Z`, improving validation loss or a predeclared metric by threshold `T`, preserving the template output schema and local run budget `C`, under a short GPU/CPU budget `B`, verified by final JSON/log parser `V`.

Initial threshold candidate:

- `T0`: reproduce `run_0` and parse final metrics without using hosted model APIs.
- `T1`: generate and execute one code/parameter change that improves validation loss over `run_0` by >=1% under matched budget.
- `T2`: improve validation loss by >=3% across three governed seeds or produce a negative result with complete receipt and no cherry-picking.

`T0` is a wiring check only. `T1` or stricter is required for an improvement claim.

Current execution readiness: data prep PASS, CUDA baseline readiness PASS, governed upstream bounded control PASS, nanoGPT_lite deterministic patch comparator PASS / same-budget deterministic patch comparator PASS in `receipts/c5-nanogpt-deterministic-patch-comparator-2026-06-30.json`, and public-safe negative Ember-vs-nanoGPT trial validated in `receipts/c5-ember-vs-nanogpt-trial-validation-2026-06-30.json`. This is not an Ember governed improvement win; the trial currently fails because no governed Ember candidate receipt exists.

## Baselines

Each task must run against at least two baselines:

1. unchanged upstream baseline/run_0;
2. deterministic scripted search or simple patch baseline with the same compute budget;
3. agent baseline: Codex/external coding agent B/Hermes-class replay only after C8 fixture is locked.

## Exclusions

- No Kaggle credential, paid API, hosted LLM judge, leaderboard submission, or paid hosted model may be required for C5-0.
- MLE-bench full/lite is not rejected as a source; it is deferred until the local subset produces a working loop protocol and a compute-spend packet justifies data/auth cost.
- AI Scientist paper-generation/review loop is not used as a judge because it commonly relies on hosted model APIs; only local experiment templates are eligible at this rung.

## Static Check Command

Before any baseline or Ember run, execute:

```powershell
python baseline\scripts\check_c5_subset_static.py --mlagentbench <external-mlagentbench-clone> --ai-scientist <external-ai-scientist-clone> --pretty
```

Current staged receipt: `receipts/c5-subset-static-check-2026-06-29.json`, verdict PASS.

## Required Receipts

- source pin receipt;
- C5 baseline readiness receipt;
- C5 nanoGPT_lite data-prep receipt;
- environment/static-check receipt;
- baseline run receipt;
- Ember loop transcript/patch receipt;
- baseline agent/script transcript/patch receipt;
- score parser output with PASS/FAIL/INVALID-RUN;
- deletion/replay receipt for any claimed improvement.

## Current Verdict

STATIC PASS, C5-0A CLRS EXECUTABLE SMOKE PASS, C5-0A THREE-SEED UPSTREAM BASELINE PASS, C5-0A EQUAL-BUDGET DETERMINISTIC PATCH COMPARATOR PASS, AND C5-0B DATA PREP PASS, NOT EMBER IMPROVEMENT. The zero-spend subset is selected and static-checked; Tiny Shakespeare data prep for nanoGPT_lite has passed; MLAgentBench CLRS/floyd_warshall now has a one-step smoke, a three-seed upstream-baseline comparator, and a three-seed deterministic learning-rate patch comparator with checkpoint hashes and numeric scores. No Ember governed C5 improvement trial has been executed under it as a passing improvement claim. No Ember governed C5 improvement trial has passed under it. The nanoGPT_lite deterministic patch comparator has executed and is a stronger non-agent comparator, not an Ember result; the public-safe Ember-vs-nanoGPT trial receipt is validated negative evidence because the Ember candidate receipt is missing.