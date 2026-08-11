<!-- EMBER_CONSERVATION_V1
minimum_new_network_parameters=3000000000
destination_total_parameters=>27000000000
required_native_capabilities=text,image,audio,reasoning,structured_tool_use
borrowed_lineage=frozen_reference_only
mechanism_erasure=forbidden
-->

# Governance

## Authority

INVARIANT.md is the sole unamendable identity surface. GOAL.md is the highest
amendable authority. The named subordinate contracts listed in GOAL.md may
operationalize it but cannot reduce it. Receipts, ledgers, research notes,
configs, historical documents, issues, branches, and agent state are never goal
authority.

master is the canonical public branch. A worktree, mirror, backup, or deleted
branch cannot self-declare authority. Current state must name its commit and
custody boundary.

CONTINUITY.md records the current execution cursor and resume order; it is subordinate evidence, not authority.

## Change conservation

A governing change must pass scripts/verify_authority_conservation.py and its
mutation suite. INVARIANT.md bytes and hash remain unchanged. Goal edits and
evidence receipts do not share a commit.

Superseded material remains in Git history or an explicit historical class.
Research mechanisms, negative results, benchmark obligations, and provenance
are preserved. Repository hygiene cannot delete them merely because a current
configuration does not use them.

## Pull requests and artifacts

Every pull request states:

- Goal-ID
- Next-executed-outcome
- authority or artifact class
- verification commands
- evidence and custody boundary

Every experiment, config, receipt, and control artifact carries the same goal
and outcome binding. Merge and dispatch gates fail closed on absence or
disagreement.

Branches use type/slug where type is feat, fix, exp, chore, or docs. Commits are
small, reviewable, and evidence-backed. Issues can describe work but cannot
close an invariant or kill a research family.

## Provenance and privacy

Tracked public files contain no personal/operator names, credentials, machine-
specific absolute paths, or private-repository locations. Public evidence uses
repository-relative paths and redacted custody identifiers. Paper authorship is
handled by the release process without weakening repository privacy.

Borrowed models are frozen references only. External learned or evaluative
signals never enter an owned lineage.

## Repository hygiene (#488)

The totality board's working-set metric is the authoritative trend surface for
public repository hygiene. A reviewable, content-addressed reference scan is
required before any cleanup and must classify each path as retained evidence,
annex candidate, or deletion candidate.

- **HYGIENE_REFERENCE_SCAN**: scan tracked docs, scripts, receipts, on-disk
  untracked receipts, and Git pack bytes; record exact relative paths, sizes,
  hashes, and tracked references.
- **HYGIENE_PROTECTED_EVIDENCE**: preserve authority, claims, provenance,
  preregistrations, live consumers, and anything referenced by a tracked file.
- **HYGIENE_NO_PRIVATE_DELETE**: never delete private/user untracked bytes or
  mutate `.git` automatically.
- **HYGIENE_EXPLICIT_APPLY**: cleanup is an explicit reviewed manifest action;
  changed bytes, unlisted paths, and protected paths fail closed.
- **HYGIENE_MANIFEST_LAST**: publish before/after evidence only after the
  selected operation completes, with exact rollback bytes and no overwrite.
- **HYGIENE_PATH_FREE_RECEIPT**: public receipts contain repository-relative
  paths only and bind the source commit, manifest, working-set counts, and
  non-regression result.

The following cadence rules are part of the same closed law and are carried by
the current governance surface rather than by a second issue or cleanup
authority:

- **HYGIENE_DOC_SUPERSESSION**: every file under `docs/` declares the document
  or contract it supersedes or invalidates (the GOAL section-8 map pattern).
  A superseded document is deleted in the superseding reviewed PR; a
  versioned specification retains only the live version and frozen
  preregistrations cited by claims.
- **HYGIENE_RECEIPT_RETENTION**: board-, credibility-battery-, open-claim-,
  and frozen-prereg-cited receipts are protected. Uncited receipts older than
  30 days are classified for the `annex_attested` annex pattern in one
  quarterly reviewed sweep; the working receipts set remains readable
  end-to-end by a stranger.
- **HYGIENE_SCRIPT_TAXONOMY**: an unreferenced script is a deletion proposal,
  never an automatic delete. The scan records the last reference and every
  import, workflow, configuration, invariant-hash, receipt `harness_sha`, and
  path consumer is updated atomically with any taxonomy move.
- **HYGIENE_ISSUE_CADENCE**: an issue silent for more than 14 days receives
  one disposition comment: pointer to a carrier issue, parked-with-path in a
  floor contract, or operator-only kill. Consolidation is not a kill.
- **HYGIENE_TREND_WINCE**: the totality-board receipt appends tracked files,
  docs, scripts, tracked receipts, and open issues. Growth across a window
  without battery-grade movement is a named wince; growth must buy graded
  evidence or it is clutter.
- **HYGIENE_CARRIER_DISCIPLINE**: extend an existing carrier when work shares
  its track; opening a new issue is not a cleanup metric.
- **HYGIENE_ENG_SYNC_TALLY**: loose `eng-sync-*` and `tally-*` operational
  receipts are classified as protected, annexable history, or disposable
  duplicates before any move/annex/delete operation.
- **HYGIENE_RECEIPT_ATOMICITY**: loose-root receipts, the claims index, board
  readers, `receipt_check.py`, and path consumers change atomically; every
  receipt move/removal carries reconstruction evidence.
- **HYGIENE_LEDGER_ARCHIVE**: `receipts/ledger/` uses an explicit append-only
  convention; `.v1-archived` is retained only when the object is
  superseded/annexed with a reconstruction pointer, never by historical
  surgery.
- **HYGIENE_DISPATCH_EQUIVALENCE**: generated dispatcher stubs may be
  consolidated only after a data-driven runner reproduces their accepted
  commands and receipts; the reviewed deletion manifest, not a filename
  count, authorizes removal.

The first #488 pass is deliberately bounded: the manifest and receipt record
one reviewed, byte-identical public duplicate and transfer the remaining
retention cadence to this governance carrier under the accepted #248
absorption comment. Private/untracked custody, `.git`, and protected evidence
remain out of scope.
