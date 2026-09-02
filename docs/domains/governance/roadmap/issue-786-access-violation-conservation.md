# Issue #786 access-violation recurrence conservation ruling

Status: `SUPERSEDED_NOT_PLANNED` for the historical
`timeshare_pretrain.run_v0_segment` CPU-sanity defect carrier, conditional on
accepted transfers to EMBER-05/#1119 and Ember Lab/#898.

Source master: `87f9669c537715ff0008080c22002eff04040bba`.

Review packet SHA-256:
`4B58EA388CB411875697B0537200017BBB76521C05063670008C620CC6C9A6B0`.

## Canonical owner transfer placeholders

Scientific equivalence owner: EMBER-05/#1119. Crash, process, resource, and
terminal-receipt owner: Ember Lab/#898. Both transfers are required.

- accepted #1119 transfer: https://github.com/wordingone/ember/issues/1119#issuecomment-5224705827
- accepted #898 transfer: https://github.com/wordingone/ember/issues/898#issuecomment-5224705890
- bidirectional source link: https://github.com/wordingone/ember/issues/786; its terminal closure comment must link this carrier and both accepted transfers after merge
- version-controlled carrier gate: https://github.com/wordingone/ember/pull/1552; closure remains forbidden until its current public head is independently reviewed, green, and merged

## Historical-only retirement

Current `src/ember/governance/scripts/timeshare_pretrain.py` is blob
`edc0441920e9eeb582ea7d188712978683670078`, declares
`EMBER_ARTIFACT_CLASS=historical_only`, and exits before imports because every
sub-3B cbase importer is execution-denied. Rerunning the old crash matrix would
revive a prohibited path and is not an admissible cure.

The historical access violation, unsigned `3221225477` or signed
`-1073741819`, remains regime-bound negative evidence. This ruling does not
claim it was cured.

## Lossless surviving recurrence contract

- Flush crash-surviving commit telemetry before native failure can destroy it.
- Distinguish `ACCESS_VIOLATION`, `PYTHON_ERROR`, `RESOURCE_REFUSAL`, and
  `NO_CRASH`; do not label every nonzero exit a native crash.
- Bind Windows Event 1000 to exact worker PID and executable rather than every
  event after a timestamp.
- Bind exact source, config, seed, checkpoint, model, optimizer, corpus,
  process, lease, and executable identities.
- Use the same real receipt builder for schema probing and execution.
- Apply a real shape-aware optimizer-state pushforward; do not load unchanged
  narrow optimizer state into a widened model and call its error the target
  crash.
- Let an aggregate reducer identify a minimal interaction only from valid rows.
- A cure that changes the measured training object requires a dated equivalence
  argument; otherwise the cure must be measurement-neutral.
- Preserve every failed configuration, missing Event 1000 row, resource
  refusal, interruption, and rollback outcome.

## Exact falsifier and reopen rule

If an analogous current-3B path reproduces the crash, the defect is live under
#1119/#898 until a current-authority diagnosis and cure satisfy every clause
above. Missing crash telemetry or conflated outcomes is an apparatus failure,
not evidence of a cure.

## Credit boundary

- `completion_credit=false`
- `scientific_execution_credit=false`
- `acquisition_credit=false`
- `result_credit=false`
- `gpu_credit=false`
- `training_credit=false`
- `checkpoint_credit=false`
- `capability_credit=false`
- `milestone_credit=false`

Current Ember Lab, EMBER-05, and the existing process/resource/receipt spine
remain the sole authorities.

`NO_NEW_PARALLEL_AUTHORITY`
