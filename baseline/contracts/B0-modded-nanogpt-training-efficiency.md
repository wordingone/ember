# Contract B0: Modded-NanoGPT Training-Efficiency Ruler

Status: BASELINE_COMPLETE for the `training_efficiency_sota` family only.
Claim family: `training_efficiency_sota`.
Access date: 2026-06-29.

This contract locks the external training-efficiency ruler. It does not claim Ember has beaten the ruler, and it does not complete the overall `/baseline`.

## Uncheatable Form

Build or run Ember training artifact `X` that beats external Modded-NanoGPT comparator `Y` on language-model train-to-validation-target metric `Z` by threshold `T`, while preserving hardware, data, accounting, reproducibility, and publication constraints `C`, under declared compute budget `B`, verified by parser/protocol `V`, producing verdict `PASS`, `FAIL`, or `INVALID-RUN`.

## Locked Comparator Y

B0 source refresh validated by `receipts/b0-modded-nanogpt-source-refresh-validation-2026-06-30.json`; this confirms the current public README still matches the locked record-84 comparator and does not constitute an Ember run.

## Locked Comparator Y

Primary comparator: `modded-nanogpt` source row in `baseline/sources.jsonl`.

Required pinned source facts:

- repository: `https://github.com/KellerJordan/modded-nanogpt`;
- commit: `54c192a77bd0e3d2572a891e0a8a1b0ceeb957d7`;
- record ID: `84`;
- checked log path: `records/track_1_short/2026-05-19_FP8MLPUpProj/this_record/008bb79d-d5bc-4205-bd4e-5e4ae82e658c.txt`;
- hardware: `8x NVIDIA H100`;
- target validation loss: `3.28` FineWeb validation cross entropy;
- observed final validation loss: `3.2802`;
- published record time: `1.32` minutes;
- checked log train time: `83855` ms;
- access date: `2026-06-29`.

Protocol-discipline comparator: `mlcommons-algoperf` source row in `baseline/sources.jsonl`, used for time-to-result accounting, fixed-target discipline, tuning-budget inclusion, and reproducibility fields. It is not a direct language-model quality comparator.

## Metric Z

A valid future Ember comparison must report, before verdict parsing:

- validation target reached or missed, with evaluator version and dataset split;
- wall-clock train time in milliseconds and minutes;
- full included time boundary: setup excluded or included must be declared before the run, while tuning/search time must be separately reported;
- hardware model/count, GPU power limit, driver, CUDA, framework, precision path, compile/fused-kernel path;
- token count, sequence length, batch/global batch, optimizer, schedule, and data preprocessing hash;
- model parameter count and active trainable parameter count;
- energy or average-power estimate if any energy claim is made;
- parser command and receipt path.

## Threshold T

The baseline locks two separate lanes. They must not be merged.

### Lane TE-RAW-SOTA

A raw training-speed claim passes only if Ember reaches the same target validation loss under an equal-or-stronger same-axis task and beats `83855` ms under comparable or stricter accounting on the same 8x-H100-class condition, or a stronger current successor discovered by source refresh.

### Lane TE-4090-PARETO

A one-RTX-4090 Ember claim cannot be represented as beating the raw 8x-H100 record by wall-clock. It may only claim a 4090 Pareto win if it beats a pre-registered same-hardware or hardware-normalized threshold that cites this raw record, the single-4090 ceiling module, and the measured local 4090 throughput receipt. This lane is invalid until `single_4090_ge_1b_foundation_ceiling` is complete.

## Constraints C

A valid run must preserve:

- no hidden hosted compute;
- no post-hoc target change;
- no benchmark substitution after seeing results;
- no transfer from tabular/reasoning/data-efficiency axes into LM speed;
- no one-smoke-run completion;
- no source-ledger/static-check-only completion;
- exact source pins and access dates;
- LF-only line endings for tracked baseline files;
- parser-readable PASS, FAIL, or INVALID-RUN receipt;
- public/private `/baseline` parity before any overall completion claim.

## Budget B

Short jobs may validate parser shape, source rows, receipt writing, line endings, and local throughput probes.

A long governed training comparison must have a compute-spend packet before launch, naming expected information gain, maximum GPU hours, stop rule, checkpoint/resume path, energy/power method, and post-run parser. Recomputing Modded-NanoGPT on 8x H100 is not justified for the current baseline because the external record already publishes the exact comparator fields needed here.

## Verifier V

Family verifier:

```powershell
python baseline\scripts\validate_training_efficiency.py --root baseline --out baseline\receipts\training-efficiency-validation-2026-06-29.json
```

Overall verifier remains:

```powershell
python baseline\scripts\verify_completion.py --root baseline --pretty
```

The family verifier passes only when this contract, source ledger, and completion lock agree on the exact comparator, metric, threshold lanes, constraints, budget, verifier, and falsifiers.

## Falsifiers

The training-efficiency claim is downgraded or invalid if:

- a stronger current training-speed successor exists and is not added before final overall completion;
- the run uses a different target, dataset, or evaluator without pre-registered normalization;
- the run omits tuning/search cost while making an end-to-end efficiency claim;
- the parser cannot reproduce the verdict from receipts;
- a one-4090 result is claimed as a raw win against the 8x-H100 record without a same-hardware or normalized threshold;
- a smoke/data-prep/static/source-ledger check is used as the training result;
- hidden compute, untracked data, or post-hoc threshold changes are found.

## Completion Boundary For This File

This family is complete when `baseline/scripts/validate_training_efficiency.py` emits `TRAINING_EFFICIENCY_BASELINE_COMPLETE` and `completion-lock.json` references that receipt for `training_efficiency_sota`.

This file's completion does not complete the overall baseline.