# C5 Zero-Spend Self-Improvement Subset V0

Status: DRAFT LOCK CANDIDATE.
Access date: 2026-06-29.
Claim family: C5-LOOP.

## Purpose

This file converts the self-improvement anchors from vague candidates into a first local, zero-spend subset. It is not an Ember PASS claim. It defines the cheapest serious task set that can test whether an agent loop improves experiments/code under equal budget before paying the cost of full MLE-bench or hosted judges.

## Source Pins

| Source | Local inspection path | Commit | Decision |
|---|---|---|---|
| MLE-bench | `C:\tmp\ember-baseline-mle-bench` | `507f92e1138bb6e40dac5c6ee7a6758e6424bf97` | Not first-run subset. Lite split is documented, but still uses Kaggle competitions, credentials/consent, and large data; use later when compute/data budget is justified. |
| MLAgentBench | `C:\tmp\ember-baseline-mlagentbench` | `5d71205cc20a8e95d43aa7cb7120e89ca3323e31` | Primary local task source. Select CLRS because it is algorithmic, generated, scored by local scripts, and directly tests code/architecture improvement loops. |
| AI Scientist | `C:\tmp\ember-baseline-ai-scientist` | `1de1dbc1f4ee2c5f61e9c94348d55eb51d7fa2eb` | Secondary local task source. Select `nanoGPT_lite`/`shakespeare_char` baseline mechanics because it matches Ember's LM-training thread and has local experiment/plot artifacts. |

## Selected C5-0 Task Set

### C5-0A: MLAgentBench CLRS Local Improvement

Uncheatable shape:

Run Ember loop `X` against baseline agent/script `Y` on MLAgentBench CLRS `Z`, improving local evaluation score by threshold `T`, preserving the CLRS task interface and loadable baseline model constraints `C`, under wall-clock/tool/patch budget `B`, verified by MLAgentBench eval script plus receipt parser `V`.

Initial threshold candidate:

- `T0`: produce a valid code change and receipt that improves final score over unchanged baseline by any positive delta under one seed.
- `T1`: improve by >=2 percentage points mean score across three governed seeds.
- `T2`: improve by >=5 percentage points mean score across three governed seeds without increasing runtime >25%.

`T0` is only an admission smoke. Publication comparisons require `T1` or stricter.

Current execution readiness: INVALID-RUN until an isolated environment provides CLRS requirements including `chex`, `haiku`, `optax`, and `clrs`.

### C5-0B: AI Scientist nanoGPT_lite Local Research Loop

Uncheatable shape:

Run Ember loop `X` against baseline agent/script `Y` on AI Scientist `nanoGPT_lite`/`shakespeare_char` experiment `Z`, improving validation loss or a predeclared metric by threshold `T`, preserving the template output schema and local run budget `C`, under a short GPU/CPU budget `B`, verified by final JSON/log parser `V`.

Initial threshold candidate:

- `T0`: reproduce `run_0` and parse final metrics without using hosted model APIs.
- `T1`: generate and execute one code/parameter change that improves validation loss over `run_0` by >=1% under matched budget.
- `T2`: improve validation loss by >=3% across three governed seeds or produce a negative result with complete receipt and no cherry-picking.

`T0` is a wiring check only. `T1` or stricter is required for an improvement claim.

Current execution readiness: data prep PASS and CUDA baseline readiness PASS. Full baseline training still requires an updated compute-spend packet.

## Baselines

Each task must run against at least two baselines:

1. unchanged upstream baseline/run_0;
2. deterministic scripted search or simple patch baseline with the same compute budget;
3. agent baseline: Codex/Claude/Hermes-class replay only after C8 fixture is locked.

## Exclusions

- No Kaggle credential, paid API, hosted LLM judge, leaderboard submission, or paid hosted model may be required for C5-0.
- MLE-bench full/lite is not rejected as a source; it is deferred until the local subset produces a working loop protocol and a compute-spend packet justifies data/auth cost.
- AI Scientist paper-generation/review loop is not used as a judge because it commonly relies on hosted model APIs; only local experiment templates are eligible at this rung.

## Static Check Command

Before any baseline or Ember run, execute:

```powershell
python baseline\scripts\check_c5_subset_static.py --mlagentbench C:\tmp\ember-baseline-mlagentbench --ai-scientist C:\tmp\ember-baseline-ai-scientist --pretty
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

STATIC PASS AND C5-0B DATA PREP PASS, NOT BASELINE-RUN. The zero-spend subset is selected and static-checked; Tiny Shakespeare data prep for nanoGPT_lite has passed. No baseline training or Ember loop run has been executed under it.