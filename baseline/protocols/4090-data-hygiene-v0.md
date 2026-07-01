# C1 4090 Data Hygiene Protocol V0

Status: GAP AUDIT, NOT COMPLETION.

This protocol prevents source pins, tokenizer/shard hashes, or task-specific heldout receipts from being laundered into a C1 corpus-wide dedupe or contamination pass.

## Required For C1 Completion

- Corpus-wide exact duplicate scan over the token/text substrate.
- Corpus-wide near-duplicate or MinHash-style scan with thresholds.
- Evaluation-suite contamination scan against every C1 capability target/eval surface.
- Recorded dedupe and contamination policy thresholds before the run.
- Public-safe receipt hashes and parser verdicts.

## Current Audit

Current audit receipt: `receipts/4090-data-hygiene-audit-2026-06-30.json`. Current validator: `scripts/validate_4090_data_hygiene.py`. The current verdict is expected to remain a blocking gap audit until true PASS receipts exist.

## Exact Duplicate Status

Corpus-wide exact token-document dedupe is now checked by `scripts/scan_c1_exact_dedup.py` and validated by `scripts/validate_c1_exact_dedup.py`. Current receipts: `receipts/4090-exact-dedupe-scan-2026-06-30.json` and `receipts/4090-exact-dedupe-validation-2026-06-30.json`; verdict: `C1_EXACT_DEDUPE_VALIDATED`. Remaining blockers are near-duplicate/MinHash scan, eval contamination scan, and threshold-policy receipts.

## Policy Threshold Status

C1 data-hygiene policy thresholds are locked by `receipts/4090-data-hygiene-policy-thresholds-2026-06-30.json` and validated by `receipts/4090-data-hygiene-policy-validation-2026-06-30.json`. The policy sets exact duplicate pass criteria, a 13-token shingle MinHash-style near-duplicate threshold at Jaccard >=0.80, and eval contamination thresholds of exact >=32 tokens or normalized >=200 character spans. These thresholds are policy evidence, not scan evidence.

## Local Heldout Contamination Status

Local Ember heldout exact 32-token overlap is scanned by `scripts/scan_c1_local_heldout_contamination.py` and validated by `scripts/validate_c1_local_heldout_contamination.py`. Current receipts: `receipts/4090-local-heldout-contamination-scan-2026-06-30.json` and `receipts/4090-local-heldout-contamination-validation-2026-06-30.json`; verdict: `C1_LOCAL_HELDOUT_CONTAMINATION_VALIDATED`. This does not close the full eval-suite or normalized-span contamination requirements.

## Local Heldout 16-Token Status

Local Ember heldout exact 16-token overlap is scanned by `scripts/scan_c1_local_heldout_multingram_contamination.py` and validated by `scripts/validate_c1_local_heldout_16gram_contamination.py`. Current receipts: `receipts/4090-local-heldout-16gram-contamination-scan-2026-06-30.json` and `receipts/4090-local-heldout-16gram-contamination-validation-2026-06-30.json`; verdict: `C1_LOCAL_HELDOUT_16GRAM_CONTAMINATION_VALIDATED`. This strengthens local heldout contamination coverage but does not close external eval-suite or normalized-span contamination requirements.
