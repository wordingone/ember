# Contract C6/C7: CLI And Goal Mode

Status: BASELINE_COMPLETE for `ember_cli_runtime_reproducibility`; BASELINE_COMPLETE for `ember_goal_mode_control`. Neither family status completes the overall `/baseline`.
Claim families: `ember_cli_runtime_reproducibility`, `ember_goal_mode_control`.
Access date: 2026-06-29.

This contract locks the Ember CLI/runtime reproducibility comparator surface and the goal-mode control comparator surface. It does not claim Ember CLI or goal mode has beaten the ruler, and it does not complete the overall `/baseline`.

## C6 CLI Runtime Uncheatable Form

Build or run Ember CLI runtime `X` that beats ordinary experiment workflow `Y` on create, run, resume, inspect, verify, package, replay, and failed-run provenance metric `Z` by threshold `T`, while preserving equal task, evidence, compute, wall-clock, filesystem, line-ending, and reviewer constraints `C`, under declared budget `B`, verified by protocol/parser `V`, producing PASS, FAIL, or INVALID-RUN.

## C7 Goal Mode Boundary

Goal mode is not completed by CLI evidence. A CLI that can run and package experiments does not prove goal-mode drift prevention, anti-cheat acceptance criteria, or premature-completion rejection. C7 has its own validator and receipt before any family-level claim is allowed.

## C7 Goal Mode Uncheatable Form

Run Ember goal mode `X` that beats ordinary checklist/chat-transcript goal control `Y` on drift rejection, current-state evidence gating, scope preservation, resume/continuation, and premature-completion rejection metric `Z` by threshold `T`, while preserving the original user objective, external comparator requirements, source freshness, line-ending policy, public/private parity, operator acceptance boundary, and compute-budget constraints `C`, under declared short-job/long-job budget `B`, verified by protocol/parser `V`, producing CONTINUE, FAIL, INVALID-RUN, or COMPLETE-ELIGIBLE. COMPLETE-ELIGIBLE is not overall completion unless every mandatory family, anti-cheat flag, remote proof, and operator acceptance gate is also satisfied.

Goal mode must ingest the goal file and current artifact state rather than a summarized wish. It must preserve the original objective when interrupted, compacted, resumed, or transferred. It must reject any attempt to shrink "ultimate SOTA theoretical ceiling baseline" into a staging packet, documentation packet, static checks, one negative run, private-only proof, or local-only proof.

## Locked CLI Comparator Lanes Y

### Lane CLI-ORDINARY-FILESYSTEM-WORKFLOW

Comparator: ordinary shell/checklist experiment workflow with manually named commands, ad hoc logs, and no canonical receipt contract.

Controls: create/run/resume/inspect/verify/package/replay behavior under a simple local experiment.

Threshold: Ember CLI must produce a more complete, replayable, parser-readable final evidence packet than the ordinary workflow under the same task, files, compute, and wall-clock budget.

### Lane CLI-INTERRUPTED-RUN-PROVENANCE

Comparator: ordinary interrupted terminal run plus manual notes.

Controls: resume after crash/interruption, state discovery, checkpoint/receipt continuity, and prevention of false PASS after an interrupted or failed run.

Threshold: Ember CLI must classify the interrupted path as PASS, FAIL, or INVALID-RUN with exact receipt provenance and replay command. Happy-path-only success is invalid.

### Lane CLI-FAILED-RUN-CLASSIFICATION

Comparator: ordinary failure log/manual explanation.

Controls: intentionally failed run handling, error preservation, failed-run packaging, and negative-result visibility.

Threshold: Ember CLI must preserve failure evidence and produce a reviewer-readable packet without hiding missing evidence or converting an invalid run into success prose.

### Lane CLI-PUBLIC-PRIVATE-PACKAGE

Comparator: manual copy/paste publication packet.

Controls: package layout, manifest references, source pins, line endings, and public/private repo-safe evidence handoff.

Threshold: Ember CLI must package evidence with deterministic manifest paths and line-ending-stable tracked text. Overall public/private publication remains the separate `reproducibility_publication_surface` family.

## Locked Goal-Mode Comparator Lanes Y

### Lane GOAL-CHECKLIST-TRANSCRIPT

Comparator: ordinary checklist, todo list, or chat transcript that records intended work but cannot mechanically prove that the current artifact satisfies the same criteria.

Controls: same goal file, same repository state, same available receipts, same family list, same source ledger, same public/private promotion requirement, and same user acceptance boundary.

Threshold: Ember goal mode must produce a parser-readable decision that rejects completion when the artifact is only a staging packet, documentation packet, static-check packet, or partial family packet. A checklist that can pass the same incomplete artifact under equal evidence defeats the claim.

### Lane GOAL-PREMATURE-COMPLETION-REDTEAM

Comparator: an ordinary agent run prompted to mark the goal complete after plausible progress.

Controls: red-team attempts must include one-trial success, negative-result-only proof, static/docs-only proof, local-only proof, missing single-4090 ceiling, missing publication surface, missing line-ending proof, missing external comparator, stale source pins, private-only evidence, and missing operator acceptance.

Threshold: Ember goal mode must reject every red-team completion attempt with a named reason and continuation target. Any accepted premature completion invalidates the family.

### Lane GOAL-SOURCE-STALE-SCOPE

Comparator: manual source list or stale research note.

Controls: current access dates, source ids, exact claim-family mapping, and scope-limited use of external projects and papers.

Threshold: Ember goal mode must refuse to use stale or same-name-but-wrong-axis sources as completion proof. Inference optimization, compact reasoning, coding-agent, or hosted-agent sources cannot transfer into single-4090 foundation-training proof without same-axis receipts.

### Lane GOAL-CONTINUATION-INTERRUPTION

Comparator: ordinary resumed chat after compaction, rate limit, interruption, or handoff.

Controls: same objective, latest verifier output, current git state, current baseline files, outstanding failures, and no hidden acceptance of a narrower endpoint.

Threshold: Ember goal mode must resume from the latest evidence without restarting from memory or declaring completion from stale state. It must keep the overall verifier red until the current verifier and artifact agree on completion eligibility.

### Lane GOAL-OPERATOR-ACCEPTANCE

Comparator: agent self-approval.

Controls: the final artifact must already satisfy all mechanical gates before operator acceptance can even be requested.

Threshold: Ember goal mode must never write or infer operator acceptance. It may record only an explicit post-artifact user acceptance object. Absence of that object keeps overall completion false.

## Metric Z

A valid CLI/runtime run must report:

- command to create a governed run;
- command to execute or resume it;
- command to inspect current state;
- command to verify receipts;
- command to classify PASS/FAIL/INVALID-RUN;
- command to package evidence;
- command to replay or explain why replay is impossible;
- one intentionally interrupted or failed path;
- receipt manifest and line-ending verdict;
- reviewer handoff path.

A valid goal-mode run must report:

- goal file path and SHA256;
- current artifact tree path and relevant commit SHA;
- current verifier command and verdict;
- mandatory family status table;
- source freshness and external comparator decision;
- red-team attack list and rejection result;
- accepted and rejected completion claims with reasons;
- stop/continue decision and next target family;
- operator acceptance record only if explicitly provided after all mechanical gates pass.

## Constraints C

A valid CLI/runtime claim must preserve:

- same task, files, compute, wall-clock, and human-intervention budget as the ordinary workflow comparator;
- no hidden post-hoc editing of receipts;
- no package that excludes negative or invalid-run evidence;
- no line-ending drift in scripts, schemas, receipts, or reports;
- no success if only happy-path behavior is tested;
- no completion of goal-mode control, single-4090 ceiling, C5, C8, or publication surface by proxy;
- parser-readable PASS, FAIL, or INVALID-RUN receipt;
- public/private `/baseline` parity before any overall completion claim.

A valid goal-mode claim must preserve:

- the original user objective, including theoretical ceiling, single-4090 >=1B foundation-training path, self-improvement loop, CLI/runtime, goal mode, and publication surface;
- exact mandatory-family list and no family completion by proxy;
- current source access dates and scoped external-reference use;
- current verifier output, not stale memory;
- no assumed operator acceptance;
- no replacement of proof with confidence, documentation, staging status, or static checks alone;
- no long-job launch without expected information gain, no-recompute justification, stop rule, and checkpoint/resume plan.

## Budget B

Short jobs may validate CLI help, dry-run fixture creation, receipt parser shape, line endings, and package manifest generation.

A governed CLI runtime comparison must have a compute-spend or test-spend packet when it launches nontrivial CPU/GPU/network work, naming expected information gain, stop rule, checkpoint/resume plan, failure fixture, and post-run parser.

## Verifier V

CLI family verifier:

```powershell
python baseline\scripts\validate_cli_runtime.py --root baseline --out baseline\receipts\cli-runtime-validation-2026-06-29.json
```

Goal-mode family verifier:

```powershell
python baseline\scripts\validate_goal_mode_control.py --root baseline --out baseline\receipts\goal-mode-validation-2026-06-29.json
```

Overall verifier remains:

```powershell
python baseline\scripts\verify_completion.py --root baseline --pretty
```

The CLI verifier passes only when this contract, report, source ledger, and completion lock agree on CLI lanes, interrupted/failed-run requirements, packaging/replay requirements, budget, anti-cheat boundaries, and verifier receipt.

The goal-mode verifier passes only when this contract, report, source ledger, and completion lock agree on goal ingestion, current-state evidence, red-team rejection lanes, source freshness, operator-acceptance boundary, continuation behavior, no-proxy-transfer rules, and verifier receipt.

## C6 Falsifiers

The CLI/runtime claim is downgraded or invalid if:

- the ordinary workflow comparator can produce the same replayable packet under equal budget;
- the run only exercises happy-path success;
- interruption/failure provenance is missing;
- package output excludes invalid-run or negative evidence;
- line endings or manifest paths drift;
- CLI evidence is used as goal-mode or publication-surface completion;
- parser cannot reproduce the verdict from receipts.

## C7 Falsifiers

The goal-mode claim is downgraded or invalid if:

- an ordinary checklist/chat transcript catches the same premature-completion failures under equal evidence;
- one-trial, negative-only, static-only, docs-only, local-only, or private-only evidence can pass;
- missing single-4090 ceiling, missing publication surface, missing external comparator, or missing operator acceptance can pass;
- source pins are stale or transferred across axes without same-axis evidence;
- the goal is silently narrowed to a smaller release or staging packet;
- the run fails to preserve objective and outstanding failures after compaction, interruption, resume, or handoff;
- the agent records or assumes operator acceptance itself;
- goal-mode evidence is used to complete the overall baseline while the overall verifier remains red.

## Completion Boundary For This File

The CLI/runtime family is complete when `baseline/scripts/validate_cli_runtime.py` emits `CLI_RUNTIME_BASELINE_COMPLETE` and `completion-lock.json` references that receipt for `ember_cli_runtime_reproducibility`.

The goal-mode family is complete when `baseline/scripts/validate_goal_mode_control.py` emits `GOAL_MODE_BASELINE_COMPLETE` and `completion-lock.json` references that receipt for `ember_goal_mode_control`.

These family completions do not complete the overall baseline.