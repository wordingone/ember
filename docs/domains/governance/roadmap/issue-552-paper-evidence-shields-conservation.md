# Issue #552 paper-evidence shields conservation

Status: `SUPERSEDED_NOT_PLANNED` only after this exact carrier receives an
independent exact-head PASS, fresh required checks are green, and the carrier
merges. This document does not claim Components A, B, or C executed.

## Historical subject retired

Issue #552 grouped three CPU/file evidence shields and the freeze mechanics
they feed: contamination scanning, corpus provenance, per-run compute ledgers,
and the later benchmark freeze declaration. The old v0/cbase/timeshare vehicle
and historical training-config subjects are execution-denied provenance only.
They are not current Ember training, evaluation, paper, or receipt authority.

Draft PR #1518 at historical head
`4596764d381b3bae16b07c19e7e4deb4dce6543e` remains unmerged apparatus. It
does not close #552, authorize a current run, or replace the accepted owner
comments below. Current `src/ember/governance/scripts/paper/contamination_scan.py`,
`scripts/paper/provenance_manifest.py`, and `src/ember/governance/scripts/paper/compute_ledger.py`
are non-authoritative helpers until consumed by current gates.

## Accepted current owners

- Component D freeze mechanics remain accepted on OPEN #123:
  https://github.com/wordingone/ember/issues/123#issuecomment-5217502317
- Components A/B and current scientific use of C are accepted on OPEN
  EMBER-02/#1116:
  https://github.com/wordingone/ember/issues/1116#issuecomment-5225164877
- Paper/release reproducibility, quarantine disclosure, provenance counts, and
  the tracked compute table are accepted on OPEN EMBER-11/#1125:
  https://github.com/wordingone/ember/issues/1125#issuecomment-5225164932
- The reachable governed compute-ledger producer and process/resource/receipt
  custody are accepted on OPEN Ember Lab/#898:
  https://github.com/wordingone/ember/issues/898#issuecomment-5225164990
- #552 bidirectional bridge:
  https://github.com/wordingone/ember/issues/552#issuecomment-5225168871

These owners are independent and complementary. No owner inherits evidence
from another owner, and none is closed by this carrier.

## Component A — current contamination admission

The current gate remains model-free and deterministic. It consumes the exact
current corpus/shard identities and frozen evaluation-suite bytes, normalizes
whitespace/case under a frozen rule, and computes:

1. exact 13-gram collision evidence; and
2. 128-permutation MinHash Jaccard with shingle size 13.

An exact collision requires an **ordered contiguous shard window** matching at
least three consecutive evaluation 13-grams. Counting consecutive eval grams
merely because each gram appears independently somewhere in the shard is not
admissible. Any exact collision or Jaccard >=0.5 flags the item
`CONTAMINATED_CANDIDATE`; flagged items are listed and quarantined from
claim-bearing evaluation, never silently dropped.

The receipt binds suite, corpus/config, every referenced shard, normalization,
thresholds, per-item maxima, worst shard, mode, and source bytes. Admission
requires a current-corpus run over at least ten evaluation items plus planted
duplicate, separated-match, reordered-match, and clean controls. No network or
learned model participates.

## Component B — current provenance admission

Every shard referenced by every current training config remains represented.
Each row binds path-free shard identity, SHA-256, source URL/identifier or
explicit `UNKNOWN`, fetch date or `UNKNOWN`, `model_in_loop=false`, and an
ordered transform chain containing step, script, input hash, and output hash.

Where source or transform bytes remain readable, the current gate reopens and
recomputes the chain. Missing evidence remains `UNKNOWN` or `UNVERIFIABLE` and
is counted in the summary; no shard or broken link may be omitted, inferred,
or promoted by prose. A synthetic fixture alone is not all-current-config
coverage.

## Component C — current compute-ledger producer and table

Only the existing Ember Lab/governed-runner authority may emit the current
claim-bearing compute block. It binds exact source, config, checkpoint, run,
process/resource, completion, and receipt identity and includes:

- `tokens_seen`;
- `optimizer_steps`;
- `wall_seconds`;
- `sec_per_step_mean`;
- `tflops_est` with formula and exact inputs stated in-field;
- `peak_vram_gib`, including memmap/offload accounting semantics; and
- `watts_series_ref`, or explicit null if no governed watts series exists.

The producer is reachable from the current nonhistorical runner, writes
receipt-first, survives interruption, and refuses missing, malformed, foreign,
stale, partial, duplicate, or unreachable evidence. The execution-denied
historical timeshare hook and a silent import-failure fallback cannot satisfy
this clause.

A tracked paper/release backfill table contains only values derived from exact
receipts. Every unavailable field is `UNKNOWN`; no estimate is silently
substituted. Historical 60-step/88.095-second rows remain provenance only.

## Component D — freeze declaration

The existing #123 acceptance remains exact:

1. coordinator freeze identity is `{commit_hash, suite_manifest_sha256, ts}`;
2. every pre-freeze number is labeled as development appendix evidence;
3. one never-before-run heldout evaluation is chosen by a published mechanical
   rule seeded by the freeze commit hash; and
4. human selection and pre-freeze capability claims are forbidden.

The freeze does not cure A, B, or C, and those components do not self-authorize
the freeze.

## Negatives, interruption, and rollback

- Missing, unreadable, mutated, foreign, stale, partial, or duplicated evidence
  fails closed.
- `UNKNOWN`, `UNVERIFIABLE`, and quarantined rows remain visible.
- No old config, historical trainer, helper script, selftest, synthetic fixture,
  backfill estimate, or draft PR becomes current evidence by citation.
- No hidden estimate, silent dropped item, missing shard, or unavailable
  transform is permitted.
- Interrupted production preserves receipt-first evidence and cannot authorize
  a paper row or training claim.
- Rollback is ordinary Git revert of this carrier plus reopening #552 while all
  accepted owner comments remain append-only public custody.

## Terminal falsifier and reopen rule

#552 may close as scientific completion only when current authority produces:

1. the ordered-contiguous 13-gram plus 128-permutation MinHash receipt on the
   exact current corpus and >=10-item suite with planted/separated/reordered/
   clean controls;
2. an all-current-config provenance manifest reopening every available
   transform chain while retaining all unknown/unverifiable rows;
3. a fresh reachable current Ember Lab training receipt with the complete
   compute block plus a tracked claim-bearing backfill table; and
4. the already accepted freeze mechanics.

This carrier instead permits only `SUPERSEDED_NOT_PLANNED`: every clause stays
open on #123/#1116/#1125/#898. Removing or narrowing an accepted comment,
carrier byte, owner link, threshold, identity, negative, rollback, or falsifier
reopens #552. A current implementation change without fresh re-verification
also reopens the affected owner obligation.

## Credit and authority boundary

- `completion_credit=false`
- `scientific_execution_credit=false`
- `acquisition_credit=false`
- `result_credit=false`
- `gpu_credit=false`
- `training_credit=false`
- `checkpoint_credit=false`
- `capability_credit=false`
- `milestone_credit=false`

Current Ember Lab/governed runner/custody, EMBER-02, EMBER-11, and #123 remain
the sole authorities in their accepted scopes.

`NO_NEW_PARALLEL_AUTHORITY`
