# Issue 35 authority supersession crosswalk

Status: **custody recovery and fail-closed supersession map; no completion
credit**.

This document makes the historical denominators named by
[issue #35](https://github.com/wordingone/ember/issues/35) explicit without
inventing the operator-held 2026-07-03 audit transcript that was never
committed. The machine-readable authority is
`manifests/authority/issue-35-authority-supersession-crosswalk-v1.json`; the
verifier is `src/ember/governance/scripts/verify_authority_supersession_crosswalk.py`.

## Preserved denominators

- 102 historical mandate slots. Because the source transcript is absent, all
  102 remain explicit `CUSTODY_GAP` rows. Their existence is conserved; their
  wording and targets are not fabricated.
- 13 reported internal-defect slots. Twelve identifiers are recoverable from
  the issue body; the thirteenth remains an explicit custody gap.
- 26 reported unwatched-mandate slots. Six recoverable clusters or individual
  obligations are preserved from the historical reconstruction; twenty slots
  remain explicit custody gaps because the reconstruction itself says their
  per-mandate identities were never stored.
- Seven reported documentation-divergence slots. Four are recoverable from the
  issue body; three remain explicit custody gaps.
- M1 through M55 from `docs/domains/governance/contracts/ember-completeness.md`.
- Every legacy condition parsed from `docs/domains/governance/spec/conditions-v1.md`, including
  C-MANIFEST and C-MILE.

`CUSTODY_GAP` means “known to have existed, source identity or wording not
recoverable.” It has no target and can never grant completion credit.
`HISTORICAL_ORPHANED` preserves the legacy `ORPHANED-BY-REFOUND` distinction
and targets only the closed historical terminal. `SUPERSEDED` names at least
one current D-row or EMBER milestone, but still grants no completion credit.

## Recovered cited authority

The following public documents were restored from their original Git
objects because issue #35 still cited them while current master omitted them:

- `docs/domains/governance/spec/publishability-adjudication-v1.md` from `f2027c00`;
- `docs/audit/class2-unwatched-mandates-recon-20260704.md` from
  `852457d3`.

The two historical acting-operator ruling objects were recovered and verified
at Git blobs `2f32b35bd9d3fd0b6b84ffc26ce2875fbe3e94ff` and
`96873b51dfae608c61d30207ee6b78716289c455`. They remain reconstructible
from Git history but are not republished as current-tree receipts because they
predate the current authority-binding schema.

Restoration preserves provenance and reversibility. It does not revive the
legacy M/C denominator as execution authority and does not claim that any
model, capability, milestone, or current authority goal is complete.

## Current authority

The only legal current targets are the exact D identifiers in
`docs/domains/governance/authority/ember-authority-matrix.md`, the twelve version-controlled EMBER milestone
contracts, and `HISTORICAL_ORPHANED`. The verifier checks those target sets
against the live files, checks every evidence byte hash, requires exact
closed-world schemas, rejects missing or duplicate source rows, and recomputes
the canonical crosswalk digest.

This first recovery increment intentionally remains
`PASS_WITH_CUSTODY_GAPS`. Closing issue #35 still requires an honest
disposition of those gaps or stronger evidence proving that an explicit
supersession conserves their missing semantics, plus the remaining executable
consumer and documentation-freshness acceptance gates.
