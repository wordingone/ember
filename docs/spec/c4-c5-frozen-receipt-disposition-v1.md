# C4/C5 frozen-receipt evidence disposition v1

Status: CURRENT / SHIPPED governance disposition for issue #1267.

## Decision

The repository does **not** attach an overlay, erratum, supersession, filename
search, or retroactive `ember-content-locator-v1` object to
`receipts/ember-resident-training-gate/resident-training-gate-20260704T065507Z-intree-issue70-redacted-edition.json`.
The frozen receipt remains byte-identical at SHA-256
`21841a3eae9992470b7c44b7ed1bee84a2998bb51159b19286bb32c40c2727f7`.
Consequently C4 and C5 remain RED on that receipt at `ARTIFACT REACHABILITY`.
Only a genuinely fresh governed resident-training-gate event may emit a new
receipt whose locators are present at creation time and whose evidence is
independently reviewable.

This is a zero-credit disposition. It neither repairs nor re-attests the
historical event, and it grants no capability, resident-training, C4, C5, or
goal-completion credit.

## Row-level disposition

| Evidence class | Rows | Disposition |
|---|---:|---|
| clean in-tree byte match | 3 | Useful recovery information only. Do not retrofit locators into the frozen attestation. A fresh event may cite these bytes if they are still canonical at its own freeze time. |
| same-name content mismatch | 3 | Unverifiable for the historical event. Do not substitute current bytes. A fresh event must capture and hash its own exact bytes. |
| private-split artifact absent from the public tree | 4 | Unverifiable by this public-tree checker. A future governed run must provide an admissible closed public evidence identity or remain RED; no corpus receipt is inferred. |
| mutable debt-ledger citation | 1 | Historical raw-byte identity is not recoverable from the live document. A fresh receipt must bind an immutable snapshot or content-addressed revision, never the later live bytes. |

The 11 rows above exhaust the redacted/unresolved path/hash pairs described by
#1267. None is silently dropped, and none receives completion credit.

## Consumer and rollback contract

Consumers `scripts/ember_totality/test_c4.py` and
`scripts/ember_totality/test_c5.py` continue to read the frozen receipt
directly and call `_lane14_common.check_path_sha_pairs`. They must not load or
merge an issue-1267 overlay. The existing closed content-locator schema remains
available only for evidence written into a receipt at creation time.

The canonical board explanations already match this disposition and therefore
need no semantic rewrite: `docs/domains/governance/anatomy/06_EVALUATION_AND_BENCHMARKS.md` and
`docs/domains/governance/anatomy/15_TECHNICAL_REPORT.md` both record C4/C5 as RED specifically on
artifact reachability. The contract test binds those exact current statements;
if either document stops disclosing that RED, this disposition is no longer
complete and issue #1267 must reopen.

Rollback is removal of this disposition and its contract test. Rollback does
not modify the frozen receipt or make C4/C5 GREEN; it reopens #1267 because the
row-level decision would again be absent.

## Reopen and falsifier conditions

Reopen this disposition if any consumer merges supplemental evidence into the
frozen candidate block, if the frozen receipt hash changes, if any of the 11
rows is credited without a fresh governed event, or if C4/C5 become GREEN on
the historical receipt without independently reviewable in-receipt evidence.
