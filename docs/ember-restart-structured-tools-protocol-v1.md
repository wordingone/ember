<!-- goal_id: EMBER-02 -->
<!-- workstream_id: EMBER-02C -->
<!-- next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember -->
# Ember Restart Structured-Tools Protocol v1

## Frozen source identity

- Evaluation source: `ShishirPatil/gorilla`, BFCL component
- Source commit: `6ea57973c7a6097fd7c5915698c54c17c5b1b6c8`
- Intended surface: executable function-call correctness through BFCL's local
  evaluator, not the public leaderboard.

## Target admission contract

1. Materialize the selected source and dataset only through
   `disk_budget_runner.py` with declared C/B write caps and receipts.
2. Freeze the BFCL task identifiers, dataset revision, function schemas,
   target tool-call serialization adapter, evaluator revision, and result-file
   schema before target inference.
3. Run the owned checkpoint using a local adapter that exposes only its own
   generated structured calls. Any API endpoint, hosted inference backend,
   borrowed model repair, retrieval, routing, or judge is excluded.
4. Preserve task inputs, tool schemas, raw target calls, parser outcomes,
   local executable/evaluator outcomes, and resource counters. Aggregate
   accuracy must retain per-task rows and uncertainty.
5. Run frozen open comparators with the identical task subset, adapter contract,
   and evaluator. Comparator outputs remain comparison evidence only.

## Explicit exclusions

- BFCL leaderboard submission, hosted model endpoints, and vendor scores.
- Any live/agentic category whose task outcome needs an external service or a
  non-pinned remote judge.
- Automatic syntax repair or model-based grading of target calls before the
  local evaluator observes them.

## Interpretation limits

This supplies the required structured-tool capability receipt when checkpoint
bound. It does not establish terminal, browser, SQL, image, audio, reasoning,
efficiency, retention, or deletion/ablation capability.
