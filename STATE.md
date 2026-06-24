# State

Single position ledger for `ember`. Current state only; short by design. Not an
append log, not duplicated by commit messages or `receipts/`. See `GOVERNANCE.md`
for why.

## Position (2026-06-24)

The repository is under **structural consolidation**. The prior `STATE.md` was an
append-only narration log carrying operator names and absolute local paths; it has
been replaced by this current-state-only ledger (names/paths removed from the tip;
a history pass is tracked separately).

- **Canonical branch:** `master`.
- **Goal document:** `GOAL.md` (the single standing goal + its reading notes).
- **Evidence:** `receipts/` (executed-job JSON only).
- **Governance:** `GOVERNANCE.md` (ownership, lifecycle, naming, privacy).

Project status claims are made from receipts, not from this file's prose. When the
goal and its verification surface are re-established on a single canonical footing,
the current position is recorded here in one short block — replacing, not appending.
