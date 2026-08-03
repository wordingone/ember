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
  not an in-place rewrite. The single permitted in-place amendment is
  adding or extending `related_class_ids` / `supersedes` on an existing
  row so a newly filed sibling class is reachable from both ends; no
  substantive field (`class_id`, `first_occurrence_ts`, `mechanism`,
  `kill_mechanism`, `receipt_refs`) may be rewritten that way.

## Schema (per class)

Each entry is a receipt (JSON), one file per class, filed under this
directory. Fields:

- `class_id` — stable identifier for the failure mechanism (used to detect
  repeats).
- `first_occurrence_ts` — timestamp of the run/rung where the class was
  first observed. Always read off a real receipt or run artifact, never
  estimated; where the originating artifact has since been superseded
  (live-receipt roots are overwritten per run), the row states the instant
  it did use and where that instant comes from, in `receipt_refs`.
- `mechanism` — what actually failed and why, in enough detail that a
  future dispatch can check for the same precondition.
- `kill_mechanism` — the kill criterion, guard, or check that now catches
  this class before/during dispatch.
- `receipt_refs` — paths to the supporting receipt(s) (kill receipt,
  anomaly receipt, falsifier pivot receipt) that evidence the class, plus
  any provenance note the row's own timestamps require.
- `related_class_ids` — *optional* list of `class_id` values for classes
  that share a root invariant with this one (typically the same wrong
  assumption re-derived at another layer). Contractual, not decorative:
  the pre-dispatch consult traverses these links, so filing a sibling
  class means linking it from both ends — the "where else is this
  invariant assumed?" sweep is only as good as the edges it can follow.
  Absent or empty means no known sibling, not "not yet checked".
- `supersedes` — *optional* list of `class_id` values this row replaces
  when a class is reclassified. The superseded row stays on disk (the
  library is append-only); this field is how a reader knows it is no
  longer the live classification.

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
