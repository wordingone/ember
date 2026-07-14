<!-- goal_id: EMBER-02 -->
<!-- workstream_id: EMBER-02C -->
<!-- next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember -->
# Ember Restart Terminal-Bench Protocol v1

## Frozen source identity

- Benchmark source: `harbor-framework/terminal-bench-2`
- Source commit: `2fd12b88aafdd04a52c298e3940bcb189f9766d6`
- Dataset selector: `terminal-bench@2.0`
- Official runner family: Harbor
- Source materialization receipt: local disk-budget receipt, C cap `0.50 GiB`,
  B cap `0.01 GiB`, exit `0`; source checkout resolved to the source commit
  above.

The source README identifies `harbor run --dataset terminal-bench@2.0` as the
task-outcome runner. Its illustrated hosted-agent commands are not Ember
evidence and must not be used for an owned-checkpoint score.

## Target admission contract

The Terminal-Bench score is admissible only when all of the following exist:

1. A contract-admitted owned checkpoint manifest, including immutable file
   hashes and complete lineage.
2. A local target adapter that sends the owned checkpoint's tool decisions to
   Harbor without a borrowed model, remote model endpoint, or borrowed judge.
3. A pinned Harbor source/version, task subset, task-image digests, and target
   tool schema hash.
4. A declared concurrency, wall-clock cap, disk cap, and resulting
   `disk_budget_runner.py` receipt.
5. Per-task task-outcome records plus aggregate success and uncertainty; no
   self-report or text-only proxy is a substitute.

## Preflight sequence

1. Run the official oracle only as a local harness-installation and task-image
   health check. It is never a comparator score.
2. Freeze the exact task identifiers after the oracle health check and before
   the target checkpoint is loaded.
3. Run the owned checkpoint once with the frozen tool policy, preserving
   transcripts, commands, exit status, and task verdicts.
4. Run a frozen open comparator under the same task list and policy only after
   its immutable revision and adapter configuration are recorded.

## Prohibited substitutions

- Hosted or paid agent calls, API keys, remote judge models, and leaderboard
  submissions.
- Borrowed model output in target prompts, tools, routing, filtering, or
  labels.
- A Terminal-Bench preparation or oracle pass represented as target capability.
