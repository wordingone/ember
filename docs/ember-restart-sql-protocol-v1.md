<!-- goal_id: EMBER-01 -->
<!-- workstream_id: EMBER-01A -->
<!-- next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember -->
# Ember Restart SQL Protocol v1

## Frozen source identity

- Evaluation source: `taoyds/spider`
- Source commit: `b7b5b8c890cd30e35427348bb9eb8c6d1350ca7c`
- Intended evidence: local exact-match and execution outcomes against frozen
  database snapshots; no remote evaluator, model judge, or leaderboard is an
  admissible scorer.

## Target admission contract

1. Materialize the selected Spider release only through `disk_budget_runner.py`
   with declared C and B write caps and a receipt.
2. Before target inference, freeze the question identifiers, database-file
   SHA-256 values, schema serialization, prompt template, SQL extraction
   policy, official scorer revision, execution-engine version, timeout, and
   deterministic database reset procedure.
3. Bind the target's generated SQL rows to an admitted owned checkpoint SHA-256
   and immutable lineage manifest. A text-only SQL answer is not an execution
   result until it is run in the frozen local sandbox.
4. Run the target and every frozen open comparator through the same schema
   serialization, extraction policy, database snapshots, execution limits, and
   scorer. Comparators remain comparison-only and may not route, repair, judge,
   or filter target outputs.
5. Preserve per-item predicted SQL, parse failures, execution errors, exact
   match, execution match, timeout/resource counters, and aggregate uncertainty.

## Failure and interpretation rules

- Missing, changed, or non-hashed database bytes fail admission rather than
  silently changing the benchmark.
- A query that executes but produces the wrong result remains a visible target
  failure; it must not be repaired by another model or heuristic before scoring.
- SQL establishes structured database tool use only. It does not substitute for
  the independent browser, terminal, image, audio, reasoning, efficiency,
  retention, or deletion/ablation surfaces.
