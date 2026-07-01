# Data-Efficiency Frontier Contract V1

Status: BASELINE_COMPLETE for the `data_efficiency_sota` family only.
Claim family: `data_efficiency_sota`.
Access date: 2026-06-29.

This contract locks the data-efficiency frontier ruler for Ember. It does not claim Ember has beaten the ruler, and it does not complete the overall `/baseline`.

## Uncheatable Form

Build or run Ember artifact `X` that beats external/theoretical data-efficiency comparator `Y` on capability-per-token, capability-per-example, or capability-per-synthetic-dataset metric `Z` by threshold `T`, while preserving task family, data budget, contamination controls, hardware/accounting, and evaluation constraints `C`, under declared budget `B`, verified by protocol/parser `V`, producing verdict `PASS`, `FAIL`, or `INVALID-RUN`.

## Locked Comparator Lanes Y

The baseline has three non-transferable lanes. A future Ember result may beat one lane only on that lane's task axis; it cannot transfer the win into another mandatory family.

### Lane DE-LM-BABYLM

Comparator: `babylm-2026` source row.

Controls: fixed-data language-model pretraining and downstream evaluation under BabyLM-style sample budgets.

Locked source facts:

- official site: `https://babylm.github.io/`;
- official 2026 leaderboard: `https://huggingface.co/spaces/BabyLM-community/BabyLM-Leaderboard-2026`;
- site commit: `2142c4c2b222b392cdc5c576d7ceede987453725`;
- evaluator repository: `https://github.com/babylm-org/babylm-eval`;
- evaluator commit: `02b56cbc8185de1462da195b54877b4be153fbfe`;
- strict-small data budget: `10000000` words;
- strict data budget: `100000000` words;
- epoch limit: `10`.

Threshold: Ember must beat the frozen same-track leaderboard or a stronger current fixed-data LM sample-efficiency successor on the selected metric suite. The selected BabyLM track, metric set, leaderboard snapshot hash or export, evaluator command, and contamination policy must be recorded before an Ember run.

### Lane DE-REASON-HRM

Comparator: `sapient-hrm` plus `hrm-critical-frontier` source rows.

Controls: compact reasoning/data-efficiency claims on ARC/Sudoku/Maze-style problem-solving axes.

Locked source facts:

- HRM source: `https://arxiv.org/abs/2506.21734`;
- HRM reported scope in the source ledger: 27M parameters, 1000 training samples, no pretraining/CoT data, ARC/Sudoku/Maze reasoning;
- critical/successor guardrail source: `https://arxiv.org/abs/2601.10679`;
- guardrail status: the first HRM headline is not treated as settled frontier without critical/successor comparison.

Threshold: Ember must beat the current compact-reasoning Pareto point on the same generated/evaluated reasoning task family, using examples/training samples, model size, recurrent or iteration budget, compute, and held-out task score. If the HRM claim is revised or superseded, the stronger same-axis successor becomes the comparator.

### Lane DE-TABULAR-NANOTABPFN

Comparator: `modded-nanotabpfn` source row.

Controls: tabular foundation-model pretraining speed/data efficiency.

Locked source facts:

- paper: `https://arxiv.org/abs/2606.03681`;
- repo: `https://github.com/borawhocodess/modded-nanotabpfn`;
- repo commit: `687cfd9b5777bd6b1139fb7a3448417de4021497`;
- upstream repo: `https://github.com/automl/nanoTabPFN`;
- upstream commit: `07a5fb75a9894f4ac2818315b0ca1b60a97e7cb5`;
- reported condition: one NVIDIA L40S;
- reported record: 0.92 minutes to the fixed downstream ROC AUC target;
- reported speedup: 81x over 74.32 minute baseline;
- reported synthetic-data reduction: 22x fewer synthetic datasets.

Threshold: Ember must beat the tabular foundation-model Pareto point on the same downstream target and same accounting axis, or beat a stronger current tabular successor. This lane cannot prove language-model pretraining, compact reasoning, single-4090 >=1B feasibility, CLI, goal-mode, or self-improvement claims.

## Metric Z

A valid data-efficiency run must report at least one lane-specific metric bundle:

- examples, tokens, words, or synthetic datasets consumed;
- model parameters and active trainable parameters;
- recurrent/iteration budget where applicable;
- hardware, wall-clock, FLOPs estimate, and energy method if claimed;
- exact train/eval generation and split policy;
- contamination/leakage check;
- task score and target metric;
- comparator lane and threshold chosen before the run;
- parser command and receipt path.

## Constraints C

A valid data-efficiency claim must preserve:

- same task family and evaluation axis;
- source pins and access dates;
- no benchmark substitution after seeing results;
- no cross-lane transfer without a separate same-axis receipt;
- no conversion of data-efficiency into raw training-speed or 4090 >=1B feasibility;
- no smoke-only, static-only, source-ledger-only, or data-prep-only completion;
- LF-only tracked baseline files;
- parser-readable PASS, FAIL, or INVALID-RUN receipt;
- public/private `/baseline` parity before any overall completion claim.

## Budget B

Short jobs may validate parser shape, source rows, dataset/evaluator availability, line endings, and receipt generation.

A long data-efficiency comparison must have a compute-spend packet before launch, naming lane, expected information gain, maximum GPU/CPU hours, stop rule, checkpoint/resume plan, energy/power method when claimed, and post-run parser. Do not recompute external anchors when their published fields already satisfy the comparator lock; recompute only for same-hardware normalization, missing fields, variance, or parser fixtures.

## Verifier V

Family verifier:

```powershell
python baseline\scripts\validate_data_efficiency.py --root baseline --out baseline\receipts\data-efficiency-validation-2026-06-29.json
```

Overall verifier remains:

```powershell
python baseline\scripts\verify_completion.py --root baseline --pretty
```

The family verifier passes only when this contract, protocol, source ledger, and completion lock agree on all three lanes, their scope limits, threshold rules, constraints, budget, verifier, and falsifiers.

## Falsifiers

The data-efficiency claim is downgraded or invalid if:

- a stronger current same-axis successor is known but omitted;
- BabyLM, HRM, or nanoTabPFN evidence is transferred across task families;
- a tabular or compact-reasoning win is presented as language-model pretraining or single-4090 >=1B evidence;
- train/eval generation, split, or contamination policy is missing;
- threshold or selected metric changes after seeing results;
- parser cannot reproduce the verdict from receipts;
- hidden compute, untracked data, or post-hoc threshold changes are found.

## Completion Boundary For This File

This family is complete when `baseline/scripts/validate_data_efficiency.py` emits `DATA_EFFICIENCY_BASELINE_COMPLETE` and `completion-lock.json` references that receipt for `data_efficiency_sota`.

This file's completion does not complete the overall baseline.