# Issue #1281 identity-less C-INV residual conservation ruling

Status: `SUPERSEDED_NOT_PLANNED`, conditional on the accepted #1114 transfer
and #1281 bridge remaining public, this carrier receiving independent exact-head
PASS, fresh required-green checks, and a clean merge. This status retires only
the duplicate issue carrier. It does not make C-INV green or cure any row.

Public-master basis: `8a4e2e46bc1d708bc3fd86ec7c42a10521cea988`.

Source: https://github.com/wordingone/ember/issues/1281

## Why a distinct carrier is required

Merged PR #1554 and
`docs/domains/governance/roadmap/issue-700-c-invariant-residual-conservation.md` already preserve
the exact nine rows and zero-uncovered law. #1281 additionally made the missing
stable identity and future audit/process-visibility emitter discipline its
explicit subject. A distinct additive carrier names that obligation rather
than silently treating the #700 document as if it had closed #1281.

## Accepted custody

- Accepted #1114 custody transfer:
  https://github.com/wordingone/ember/issues/1114#issuecomment-5226208385
- Bidirectional #1281 bridge:
  https://github.com/wordingone/ember/issues/1281#issuecomment-5226211894
- Existing accepted exact-row foundation:
  https://github.com/wordingone/ember/issues/1114#issuecomment-5224892973
- Existing merged carrier foundation:
  https://github.com/wordingone/ember/pull/1554

#1114 remains OPEN as the sole current owner. No evidence or completion state
is inherited from #700's closure.

## Exact current RED census derivation

The #700 carrier's direct basis result at
`c45ec200550a7d85264b8cae4d7c5cf622e9c90a` was
`1,131/294/153/101/31/0/9` for scanned/post-genesis/stamped/errata/
anti-laundering-superseded/uncovered-pre-cutoff/uncovered-post-cutoff.

From that basis to `8a4e2e46bc1d708bc3fd86ec7c42a10521cea988`, the only
new tracked receipt is
`receipts/hygiene/issue-488-first-cleanup-v1.json`; it has the exact invariant
stamp and stable ticket `EMBER-488-HYGIENE`. The C-INV probe, errata,
supersession authority, and nine residual rows are unchanged. The derived
current census is `1,132/295/154/101/31/0/9`.

A fresh read-only direct probe was executed against Git tree
`122a7070862fa689c72d189bbdefa72b580ea881`, shared exactly by the reviewed
carrier source tree and public master. Canonical `check_stamped_receipts()`
returned RED with `1,132/295/154/101/31/0/9` and zero skipped errata or
supersession rows. A fresh direct probe remains mandatory on the final reviewed
carrier head before terminal disposition; neither result is a C-INV completion
receipt.

## Exact nine unresolved rows

1. `receipts/ember-totality-audit/audit-20260710T001800Z.json`
2. `receipts/ember-totality-audit/audit-20260710T145200Z.json`
3. `receipts/ember-totality-audit/audit-20260710T203826Z.json`
4. `receipts/ember-totality-audit/audit-20260710T223333Z.json`
5. `receipts/ember-totality-audit/audit-20260711T012500Z.json`
6. `receipts/ember-totality-audit/audit-20260711T104500Z.json`
7. `receipts/process-visibility/process-visibility-20260710T005700Z.json`
8. `receipts/process-visibility/process-visibility-20260710T221000Z.json`
9. `receipts/process-visibility/process-visibility-20260711T102300Z.json`

All nine lack `ticket` and the `receipt_class`/`leg` identity pair recognized
by the current C-INV probe. Other descriptive keys are not substitutes.

## Lossless surviving executable contract

- C-INV remains RED until a fresh current-master probe reaches
  `uncovered_post_cutoff == 0`.
- Historical bytes are append-only and receive no retroactive identity.
- Lawful cures are limited to genuine stamped re-execution, supersession
  accepted by the existing anti-laundering checks, or an explicitly ruled and
  documented receipt class enforced by the current executable authority.
- Path, filename, timestamp, directory, content digest, prose, transfer, or
  issue closure cannot substitute for stable old/new leg/class identity.
- The probe cannot be weakened, bypassed, replaced by prose, or taught to
  accept a row merely because the row is named here.
- Missing target, invalid JSON object, incorrect invariant stamp, absent
  stable old/new identity, mismatched identity, and skipped/malformed
  errata/supersession authority remain failures.
- Audit and process-visibility emitters must use the existing
  invariant-stamping authority and write stable `ticket` or exact
  `receipt_class`/`leg` identity for future rows. This creates no new family.
- Any later qualifying unstamped or identity-less post-cutoff row immediately
  keeps or returns C-INV to RED.

## Exact falsifier and reopen law

Refuse disposition or reopen canonical work when any row remains uncovered;
any supersession is rejected or mismatched; authority is malformed, skipped,
stale, or foreign; coverage is weakened or bypassed; a fresh current probe is
missing; an emitter creates another qualifying unstamped/identity-less row; or
the accepted owner link, carrier, review, check, sole-authority, or no-credit
boundary is lost or narrowed.

## Closure boundary for #1281

#1281 may close only as `SUPERSEDED_NOT_PLANNED` after exact public owner and
source links, immutable base/head, independent PASS, fresh CI and guard
success, clean merge, and a terminal comment binding them. Closing #1281 does
not close #1114, make C-INV green, cure a receipt, or authorize a new identity
or exemption mechanism.

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

Current Ember governance and its existing receipt/invariant spine remain the
sole authority. This carrier creates no second invariant, probe, receipt,
identity, stamping, ledger, closure, or milestone authority.

`NO_NEW_PARALLEL_AUTHORITY`
