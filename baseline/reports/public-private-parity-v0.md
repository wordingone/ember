# Public/Private Baseline Parity V1

Status: BASELINE_COMPLETE for `reproducibility_publication_surface` only. Overall baseline completion remains gated on operator acceptance and the strict completion lock.
Created: 2026-06-29.
Branch: `codex/ember-baseline-repaired-goal-20260629`.
Public repo: `https://github.com/wordingone/ember`.
Private repo: `https://github.com/wordingone/ember-backup`.

## What This Proves

This report proves the publication surface family has a replayable top-level `/baseline` packet in both Ember remotes, with source-ledger validation, line-ending validation, remote-content checks, and a completion-lock row for the publication family.

It does not prove operator acceptance. It does not by itself mean Ember has beaten any baseline family.

## Required Files

Both repos must expose at least:

- `baseline/README.md`
- `baseline/completion-lock.json`
- `baseline/sources.jsonl`
- `baseline/4090-ceiling-v0.md`
- `baseline/field-level-threshold-v0.md`
- `baseline/contracts/`
- `baseline/protocols/`
- `baseline/scripts/verify_completion.py`
- `baseline/scripts/validate_publication_surface.py`
- `baseline/receipts/`
- `baseline/reports/report-v0.md`
- `baseline/reports/public-private-parity-v0.md`

## Mechanical Receipts

- Source ledger: `receipts/source-ledger-validation-2026-06-29.json`.
- Line endings: `receipts/line-endings-validation-2026-06-29.json`.
- Remote proof: `receipts/remote-proof-2026-06-29.json`.
- Publication validator: `receipts/publication-surface-validation-2026-06-29.json`.

## Boundaries

Private-only evidence cannot become the sole basis of a public field-level claim. The remote proof receipt checks both repos and records the served refs after push. The completion lock remains the machine-readable source for overall state.

## Current Verdict

PUBLICATION_SURFACE_BASELINE_COMPLETE for the publication-surface comparator family only. Overall goal completion still requires strict verifier PASS and explicit operator acceptance.