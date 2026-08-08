# Issue #705 capability-measurement conservation ruling

Status: `SUPERSEDED_NOT_PLANNED` for the standalone metric tracker,
conditional on accepted transfer to EMBER-02/#1116.

Source master: `87f9669c537715ff0008080c22002eff04040bba`.

Review packet SHA-256:
`4B58EA388CB411875697B0537200017BBB76521C05063670008C620CC6C9A6B0`.

## Canonical owner transfer placeholders

Canonical owner: EMBER-02/#1116. Publish in the capability-measurement group
with #703 and #782 while retaining this independent metric contract.

- `[PENDING_ACCEPTED_705_TRANSFER_ON_1116]`
- `[PENDING_BIDIRECTIONAL_LINK_FROM_705]`
- `[PENDING_VERSION_CONTROLLED_CARRIER_MERGE]`

## Retired metric

Raw score divided by tokens is prohibited: it mechanically falls during
healthy bounded learning and changes under arbitrary affine score origins.
Historical raw quotients grant no capability-per-token evidence.

## Lossless surviving contract

Only three metric families are admissible:

1. paired fixed-token capability delta;
2. sustained tokens-to-target or FLOPs-to-target with explicit censoring;
3. normalized capability-versus-log-token AUC.

Every result binds exact checkpoint, evaluation set, scorer, contamination
status, total tokens, unique clean tokens, and comparison identity. Family 3
also requires external common per-task anchors frozen before any arm,
task-first normalization, frozen task weights, a common clean-token domain,
and either a common checkpoint grid or a frozen log-space interpolation rule.

Missing comparison history is `NONCOMPARABLE_HISTORICAL`. Missing tasks or
checkpoints are refused, never imputed. Fixtures retain pair ordering when a
third arm is added, affine score-and-anchor invariance, and missing-input
refusal.

## Exact falsifier and reopen rule

A raw quotient, per-arm normalization, cohort-derived anchors, changed task
weights, non-common token domains, unstated interpolation, unbound identities,
imputation, or missing censoring refuses the measurement. No metric instrument
alone demonstrates capability or training quality.

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

Current Ember Lab, EMBER-02, and the existing checkpoint/evaluation/custody
spine remain the sole authorities.

`NO_NEW_PARALLEL_AUTHORITY`
