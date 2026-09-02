# 10 — Receipts and Provenance

## The schema floor: src/ember/governance/scripts/receipt_check.py

`src/ember/governance/scripts/receipt_check.py` validates every `receipts/*.json` file against a
minimum schema floor (eng #103):

- **R1 required fields**: `ticket`, `ts` must be present.
- **R2 sha-convention rule**: any field name matching `sha256`/`sha_256`
  (recursive up to depth 3) requires a `sha_convention` field to be present
  in the same receipt. The standing convention text is `"bytes on disk as-is
  (binary read, no line-ending normalization)"`.
- **R3 integer rule**: fields matching `^(n_|.*_count$|guard_flips$|rows$)`
  (plus counters inside a `flips` array) must be JSON integers, not strings.
- **R4 post-genesis invariant rule**: any receipt whose `ts` is at/after
  `GENESIS_TS = "2026-07-06T14:13:23-07:00"` (the committer date of commit
  `9c89f7f66`, tag `invariant-genesis`, "genesis: entrench constitutional
  invariant (#281)") must carry `invariant_sha256 ==
  "08a0eb7418c09a8088be4658e10785107abbb7507fc2dbcdc789936aa54e02a6"` exactly.
  Pre-genesis receipts are exempt.

Modes: `--all` (report-only over every receipt, exit 0 always — legacy
pre-R1 receipts are silently skipped via a `LEGACY_EXEMPT` frozenset, each
entry commented with its exemption reason), `--file X` (fail-closed on one
receipt, non-zero exit on any finding), `--selftest`.

## Atomic, quarantine-never-delete writes: src/ember/governance/scripts/receipt_write.py

`checked_write(path, obj)` stages JSON bytes (UTF-8, LF, indent=2) in the
destination directory, flushes and `fsync`s them, validates via
`receipt_check.validate_receipt()`, then publishes with a same-volume
`os.replace()` — so a partial write is never observable at the canonical
path. A schema-invalid candidate is moved to `<path>.INVALID.quarantine`
rather than deleted; the existing canonical receipt (if any) is left
untouched. The module's own docstring cites the reason this matters: eng
#702 (2026-07-11) — a prior delete-on-finding behavior destroyed the ONLY
copy of two separate full-compute runs' results (a 434M-cpu microbench and a
52-minute 2.2B GPU continuation rerun) because the *receipt-write step*
failed schema validation after real compute had already completed. "Both
runs completed their full compute; only the receipt-write step failed; the
deletion — not the schema defect — is what actually destroyed the results."

## Directory convention

Receipts live under `receipts/`, generally namespaced by subsystem
(`receipts/ember-anatomy/`, `receipts/ember-restart-3b/`,
`receipts/process-visibility/`, `receipts/ember-totality-audit/`, etc.) with
filenames carrying a compact UTC timestamp suffix
(`<name>-<YYYYMMDDTHHMMSSZ>.json`). `src/ember/governance/scripts/ember_totality/receipts-totality/`
is a special-cased sibling directory holding the totality board's own
receipts (excluded from the generic receipts/ scan to avoid the board
recursively citing itself — see 11_TOTALITY_BOARD_CONDITIONS.md).

## Current gaps — honestly stated

Condition `C-CUSTODY` (receipts git-tracked, parseable, cited paths exist)
was GREEN on the last board render. Condition `C-INV` (invariant-sha256
stamping coverage across the whole receipts/ tree) was RED: 24 post-genesis
receipts scanned as missing/mismatched the stamp and not errata-covered, out
of 1076 receipts scanned. This doc describes the contract; it does not claim
100% stamping coverage.
