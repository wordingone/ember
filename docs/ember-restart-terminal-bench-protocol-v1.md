<!-- goal_id: EMBER-02 -->
<!-- workstream_id: EMBER-02C -->
<!-- next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember -->
# Ember Restart Terminal-Bench Protocol v1

## Frozen source identity

- Benchmark source: `harbor-framework/terminal-bench-2`
- Source commit: `2fd12b88aafdd04a52c298e3940bcb189f9766d6`
- Source Git tree: `ec7c02c7f0b59ce8ed2f7c88d1e70cda7427edfa`
- License: Apache-2.0; exact `LICENSE` SHA-256:
  `c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4`
- Dataset selector: `terminal-bench@2.0`
- Official runner family: Harbor
- Evaluator cache disposition: exact source checkout verified read-only for
  evaluation. Task content and any run outputs remain outside the public
  repository and target-training lineage.

The source README identifies `harbor run --dataset terminal-bench@2.0` as the
task-outcome runner. The scorer accepts only the freezer-produced
`ember-restart-terminal-bench-freeze-v2` manifest; handwritten legacy manifests are
rejected before any Harbor outcome is considered. Its illustrated hosted-agent
commands are not Ember evidence and must not be used for an owned-checkpoint score.

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

## Current cache eligibility audit

The disk-budgeted source cache contains 89 task metadata records. The exact
preflight audit found 0 digest-pinned image references, 0 tasks with
`allow_internet = false`, and therefore 0 eligible offline tasks. Every cached
record uses a mutable image tag and enables network access. The custody manifest
records this as `PREFLIGHT_ONLY_NO_ELIGIBLE_OFFLINE_DIGEST_PINNED_TASK`; no
Terminal-Bench task outcome is a target capability score.
