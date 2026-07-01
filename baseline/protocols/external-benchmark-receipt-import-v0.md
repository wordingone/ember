# External Benchmark Receipt Import Protocol V0

Status: SUPPORTING EVIDENCE, NOT COMPLETION.

This protocol imports prior Ember benchmark/access receipts from the `codex/ember-real-benchmark-next` branch into `/baseline` so the baseline cannot falsely treat prior Ember external benchmark work as absent.

## Rules

- Imported receipts must be copied into `receipts/external-benchmark-imports/` so the public/private `/baseline` artifact is self-contained.
- Every imported receipt must record source branch, source commit, source path, import path, SHA-256, classification, verdict, and scope limit.
- Executed public-test, frozen-heldout, or external-heldout receipts may prove that prior external benchmark plumbing ran.
- Blocked official MLE, Kaggle auth, or prepare receipts may prove access/setup gaps only and must stay in the separate gap ledger, not in completed-family evidence receipts.
- No imported receipt can complete an Ember-vs-baseline claim unless a family validator explicitly binds it to a frozen comparator, metric, budget, and threshold.

## Current Import

The current import ledger is `receipts/external-benchmark-receipt-index-2026-06-30.json`. Its validator is `scripts/validate_external_benchmark_receipts.py`.
