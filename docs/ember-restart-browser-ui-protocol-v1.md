<!-- goal_id: EMBER-02 -->
<!-- workstream_id: EMBER-02C -->
<!-- next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember -->
# Ember Restart Browser/UI Protocol v1

## Frozen source identity

- Framework source: `ServiceNow/BrowserGym`
- Source commit: `9e779f087de9a65668b6974d11f9ce9816026e96`
- Source materialization: disk-budget receipt with C cap `0.50 GiB`, B cap
  `0.01 GiB`, exit `0`, and checkout equal to the commit above.

## Initial admissible surface

The first browser/UI score uses BrowserGym's MiniWoB task family. It has a
local browser task loop and task completion signal. Before a target score, the
exact task identifiers, BrowserGym dependency lock, Chromium revision, target
action schema, task reset procedure, and scorer version must be frozen in the
checkpoint-bound manifest.

For each task, preserve the initial observation, every action, final browser
state, terminal/reward signal, and time/resource counters. Aggregate success
must retain per-task rows and uncertainty; a rendered browser session or agent
self-report is not a score.

## Explicit exclusion

BrowserGym's WebArena integration documentation warns that some WebArena
evaluations call GPT-4 for fuzzy matching. That path is excluded from Ember
credit because it introduces a hosted borrowed judge. It may become eligible
only with an independently pinned, local exact evaluator for the selected
tasks. The BrowserGym demo agent is also excluded because its documented
backend uses an external model API.

## Target admission

1. Admit the exact owned checkpoint through the restart evaluation contract.
2. Materialize the local browser dependencies through `disk_budget_runner.py`
   with an explicit resource cap and receipt.
3. Freeze the MiniWoB task list before target inference.
4. Run the owned target and each frozen comparator through the identical local
   action adapter and reset sequence.
5. Publish success, failures, traces, environment hashes, and uncertainty.
