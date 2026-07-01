# CLI And Goal-Mode Baseline V1

Status: BASELINE_COMPLETE for `ember_cli_runtime_reproducibility`; BASELINE_COMPLETE for `ember_goal_mode_control`. Neither status completes the overall `/baseline`.
Claim families: `ember_cli_runtime_reproducibility`, `ember_goal_mode_control`.
Access date: 2026-06-29.

## Purpose

This file separates Ember CLI/runtime reproducibility from goal-mode anti-cheat control.

CLI/runtime asks whether an experiment interface can create, run, resume, inspect, verify, classify, package, and replay governed runs better than an ordinary experiment workflow.

Goal mode asks whether a control loop rejects drift, missing evidence, stale sources, scope shrinkage, and premature completion better than a checklist/chat transcript. Goal mode is not completed by the CLI family.

## C6 CLI Runtime Baseline

Build or run Ember CLI flow `X` that beats baseline experiment workflow `Y` on create/resume/inspect/verify/package/replay metric `Z` by threshold `T`, preserving reproducibility, failure provenance, line endings, and compute constraints `C`, under budget `B`, verified by protocol `V`, producing PASS, FAIL, or INVALID-RUN.

### Required CLI Flow

1. create a governed run;
2. execute or resume it after interruption;
3. inspect current state;
4. verify receipts;
5. classify PASS/FAIL/INVALID-RUN;
6. package evidence for another reviewer;
7. replay or explain replay impossibility;
8. handle at least one intentionally failed or interrupted run correctly.

### Required CLI Evidence

- command transcript or fixture manifest;
- receipt manifest;
- interrupted/failed-run provenance;
- negative or invalid-run evidence preservation;
- line-ending verifier result;
- package/handoff path;
- parser verdict.

## C7 Goal-Mode Baseline

Build or run Ember goal mode `X` that beats ordinary checklist/chat-transcript goal control `Y` on current-state evidence, drift rejection, source freshness, red-team premature-completion rejection, continuation/resume behavior, and operator-acceptance boundary metric `Z`, preserving the original theoretical-ceiling baseline objective and all mandatory family gates.

### Required Goal-Mode Flow

1. ingest the goal file path and SHA256;
2. inspect current artifact tree, commit state, verifier output, and family statuses;
3. compare the current artifact against all mandatory families rather than a narrowed release;
4. refresh or reject stale external source pins before using them as evidence;
5. classify each completion claim as rejected, continue, invalid-run, or complete-eligible;
6. preserve original objective after interruption, compaction, resume, or handoff;
7. record next target family instead of treating a blocker as permission to stop;
8. refuse to write, infer, or simulate operator acceptance.

### Required Goal-Mode Red-Team Rejections

Goal mode must reject all of these premature-completion attempts with named reasons:

- one-trial success;
- negative-result-only proof;
- static/docs-only proof;
- local-only proof;
- private-only proof used for a public claim;
- missing external comparator;
- stale source pin;
- same-name source transferred across the wrong axis;
- near-miss framed as PASS;
- missing line-ending verification for scripts, schemas, receipts, or reports;
- missing single-4090 ceiling;
- missing publication surface;
- missing operator acceptance.

### Required Goal-Mode Evidence

- goal file path and SHA256;
- current verifier command and verdict;
- mandatory family table;
- red-team attack list and rejection receipt;
- source freshness summary;
- continuation target;
- explicit note that operator acceptance is absent unless the user has provided a post-artifact acceptance object.

## Current Verdict

CLI_RUNTIME_BASELINE_COMPLETE for the CLI/runtime comparator-family definition only.

GOAL_MODE_BASELINE_COMPLETE for the goal-mode comparator-family definition only.

No Ember CLI or goal-mode run has beaten the baselines yet, operator acceptance is absent, and this is not overall `/baseline` completion.