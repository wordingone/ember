# Contract C5: Self-Improvement Loop

Status: BASELINE_COMPLETE for the `self_improvement_loop_sota` family only.
Claim family: `self_improvement_loop_sota`.
Access date: 2026-06-29.

This contract locks the self-improvement loop comparator surface for Ember. It does not claim Ember has beaten the ruler, and it does not complete the overall `/baseline`.

## Uncheatable Form

Build or run Ember loop `X` that beats baseline loop `Y` on external or source-derived ML/research task set `Z` by threshold `T`, while preserving equal tools, data, compute, wall-clock, receipt access, human-intervention, and negative-result constraints `C`, under declared budget `B`, verified by deterministic scorer, replay parser, or predeclared reviewer protocol `V`, producing verdict `PASS`, `FAIL`, or `INVALID-RUN`.

## Locked Comparator Lanes Y

The baseline has five self-improvement lanes. A future Ember result must name the lane before execution and cannot use a local smoke/static check as a loop-improvement win.

### Lane C5-MLE-BENCH

Comparator: `mle-bench` source row.

Controls: ML-engineering task success under competition-style scoring, data/credential constraints, and benchmark task discipline.

Threshold: Ember must beat a same-task baseline agent or published exact comparator on a preselected MLE-bench task score under identical data, tool, compute, wall-clock, and human-intervention budget. Full/lite MLE-bench execution requires a compute-spend packet before data/auth cost.

### Lane C5-MLAGENTBENCH-CLRS

Comparator: `mlagentbench` source row, selected task `CLRS`.

Controls: local ML-experimentation loop capability on generated algorithmic tasks with local scoring.

Threshold: Ember must beat unchanged upstream and deterministic scripted/search baselines on CLRS by a predeclared score delta. Admission `T0` wiring checks are not improvement claims; publication comparison requires `T1` or stricter from `protocols/c5-zero-spend-subset-v0.md`.

### Lane C5-AI-SCIENTIST-NANOGPT

Comparator: `ai-scientist` source row, selected task `nanoGPT_lite/shakespeare_char`.

Controls: local research-loop mechanics on a small LM experiment template without hosted-model judge dependency.

Threshold: Ember must generate, execute, and parse one or more code/parameter changes that beat unchanged `run_0` and deterministic scripted/search baselines on validation loss or a predeclared metric under matched budget. Data prep and smoke receipts are wiring evidence only.

### Lane C5-AI-SCIENTIST-V2

Comparator: `ai-scientist-v2` source row.

Controls: successor automated research-loop frontier. It blocks stale comparison against only the original AI Scientist when a newer public successor is known.

Threshold: Ember must either compare against a selected v2-derived local fixture under identical budget or record a sourced no-recompute reason and replace it with an equal-or-stronger local fixture before any Ember self-improvement claim.

### Lane C5-KOSMOS-SCIENTIFIC-DISCOVERY

Comparator: `kosmos-ai-scientist` source row.

Controls: broad autonomous data-driven scientific discovery loop claims, including multi-agent rollout scale, paper-reading/citation traceability, and independent review.

Threshold: Ember cannot claim field-level self-improvement or autonomous research-loop contribution unless it either beats a same-axis local scientific-discovery fixture, records a no-recompute exclusion, or scopes the Ember claim to ML-engineering/local-loop tasks only. Kosmos is a guardrail against overclaiming from small local C5-0 tasks.

## Metric Z

A valid self-improvement run must report:

- selected lane and task manifest;
- starting baseline score or artifact;
- generated change proposal, patch/config/data change, and transcript;
- executed experiment command and environment;
- final score, loss, or task metric;
- score delta versus unchanged baseline and deterministic/scripted baseline;
- valid experiment count and invalid/non-reproducible experiment count;
- receipt completeness and parser verdict;
- deletion, replay, or ablation check for the winning change;
- negative-result preservation.

## Constraints C

A valid self-improvement claim must preserve:

- equal tools, files, data, compute, wall-clock, cached receipts, and human-intervention budget across Ember and baselines;
- no self-graded victory;
- no paid/hosted judge as required authority when local deterministic scoring or human-authorized review can apply the rubric;
- no hidden human steering or private labels;
- no changing task, metric, or threshold after seeing Ember output;
- no counting prose insight as improvement without executed evidence;
- no local C5-0 task result transferred into broad scientific-discovery or field-level claims;
- LF-only tracked baseline files;
- parser-readable PASS, FAIL, or INVALID-RUN receipt;
- public/private `/baseline` parity before any overall completion claim.

## Budget B

Short jobs may validate static task availability, parser shape, data prep, smoke execution, line endings, and receipt generation.

A governed self-improvement comparison must have a compute-spend packet before launch, naming lane, expected information gain, maximum GPU/CPU hours, network/data/auth needs, stop rule, checkpoint/resume plan, negative-result policy, baseline arms, and post-run parser. Do not recompute external published baselines when their source fields are enough to lock comparator scope; recompute only when equal-budget scoring or local replay is required.

## Verifier V

Family verifier:

```powershell
python baseline\scripts\validate_self_improvement.py --root baseline --out baseline\receipts\self-improvement-validation-2026-06-29.json
```

Overall verifier remains:

```powershell
python baseline\scripts\verify_completion.py --root baseline --pretty
```

The family verifier passes only when this contract, C5 protocol, source ledger, and completion lock agree on comparator lanes, no-recompute boundaries, anti-cheat constraints, budget, verifier, and falsifiers.

## Falsifiers

The self-improvement claim is downgraded or invalid if:

- unchanged or deterministic scripted/search baseline matches or beats Ember;
- the winning change fails deletion, ablation, or replay;
- the result is a static check, data prep, smoke run, or one-off negative result only;
- a paid/hosted judge is required when local scoring is available;
- hidden human steering changes next actions;
- the run uses a stale comparator set omitting AI Scientist v2 or Kosmos guardrail;
- parser cannot reproduce the verdict from receipts;
- hidden compute, untracked data, or post-hoc threshold changes are found.

## Completion Boundary For This File

This family is complete when `baseline/scripts/validate_self_improvement.py` emits `SELF_IMPROVEMENT_BASELINE_COMPLETE` and `completion-lock.json` references that receipt for `self_improvement_loop_sota`.

This file's completion does not complete the overall baseline.