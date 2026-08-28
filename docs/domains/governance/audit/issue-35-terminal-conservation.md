# Issue 35 terminal conservation

Status: **terminal historical-custody disposition; zero completion credit**.

The canonical 251-row authority crosswalk remains append-only evidence. It
contains the exact historical denominators: 102 audit mandates, 13 internal
defects, 26 unwatched mandates, seven documentation divergences, seven issue
#265 transfer rows, M1-M55, and 41 legacy conditions including C-MANIFEST and
C-MILE. Its 125 recoverable rows remain bound to hash-verified current evidence
or a named historical terminal. This carrier does not reinterpret them.

The remaining 126 rows are known slots whose operator-held wording was never
committed: all 102 audit mandates, one internal defect, 20 unwatched mandates,
and three documentation divergences. Missing wording cannot be reconstructed
truthfully. `issue-35-terminal-dispositions-v1.json` therefore carries one
closed disposition row for each exact `(source_registry, source_id)` pair. Each
row binds the original statement and evidence hashes, targets only
`HISTORICAL_ORPHANED`, grants no completion credit, and reopens on authentic
source recovery. The set must equal all 126 `CUSTODY_GAP` rows; omission,
duplication, substitution, target drift, or credit mutation fails closed.

This disposition closes the historical audit umbrella, not the underlying
current Ember work. All current D-row, roadmap-certificate, REOPEN, corpus,
training, evaluation, and custody obligations retain their existing owners.
No missing mandate is declared satisfied, no recovered evidence is invented,
and no scientific, corpus-quality, training, checkpoint, evaluation,
capability, milestone, or model-result credit is granted.

Rollback is exact: revert the terminal disposition packet, verifier, tests,
and this document together. If authentic source wording is recovered, reopen
#35 before changing the affected row, independently review the provenance, and
append a superseding row without deleting the historical disposition.

`NO_NEW_PARALLEL_AUTHORITY`.
