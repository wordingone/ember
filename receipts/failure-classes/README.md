# Failure-class library

<!-- goal_id: EMBER-02 -->
<!-- workstream_id: EMBER-02A -->
<!-- next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember -->

Cited by `docs/spec/ember02-preregistration-v1.md:42` ("classed under
`receipts/failure-classes/` so no failure class repeats") and independently
mandated by the training-failure class-kill law: every training-failure
class gets exactly one receipt here, and no class is ever allowed to repeat
once its receipt exists.

## Contract

- **One receipt per training-failure class.** A class is a distinct
  mechanism of failure (anomaly, kill-fire, or falsifier), not a distinct
  occurrence — if the same mechanism recurs, that is itself a violation to
  be surfaced, not a new file to add.
- **Filed before the next dispatch that could repeat it.** Per §3's rung
  ladder, a failure-library entry is one of the two mandatory closing
  receipts for every rung; the library is consulted before any training
  dispatch so a previously-killed class cannot recur unnoticed.
- **Append-only.** Existing rows are never edited or deleted; a
  reclassification is a new row that supersedes an old one by reference,
  not an in-place rewrite.

## Schema (per class)

Each entry is a receipt (JSON), one file per class, filed under this
directory. Fields:

- `class_id` — stable identifier for the failure mechanism (used to detect
  repeats).
- `first_occurrence_ts` — timestamp of the run/rung where the class was
  first observed.
- `mechanism` — what actually failed and why, in enough detail that a
  future dispatch can check for the same precondition.
- `kill_mechanism` — the kill criterion, guard, or check that now catches
  this class before/during dispatch.
- `receipt_refs` — paths to the supporting receipt(s) (kill receipt,
  anomaly receipt, falsifier pivot receipt) that evidence the class.

## Receipt stamping

Rows in this library are receipts, not free-form notes: they carry the
standard receipt stamps enforced by `scripts/receipt_check.py` (`ticket`,
`ts`, and, for any sha-bearing row, `sha_convention` plus the
constitutional `invariant_sha256`). This README is documentation about the
library, not itself a receipt, and is not subject to that schema.

## Why this directory exists as its own root

This library is distinct from the per-incident `state/failure-classes/`
notes used elsewhere in this codebase (documentation of specific bugs found
during development). `receipts/failure-classes/` is the constitutional,
receipted registry the pre-registration rung ladder and the class-kill law
both bind to — it is consulted before dispatch, not read after the fact.
