# C1 4090 Data Governance Protocol V0

Status: SUPPORTING EVIDENCE, NOT COMPLETION.

This protocol binds the single-4090 >=1B baseline to real token-substrate evidence instead of synthetic-only probes. It imports public-safe summaries from the existing Ember v0 tokenizer and token-shard receipts.

## Required Checks

- Frozen tokenizer receipt exists and was frozen before step 0.
- Token shard receipt records content token count, stream token count, per-source counts, shard hashes, and reserved-band guard.
- C1 model vocab compatibility is explicit: all observed token ids must fit within the C1 vocab.
- From-scratch and pretraining-equivalent lanes are evaluated separately against their locked token budgets.
- Dedupe, contamination, real-data LM-loss probe, checkpoint/resume, and long-run throughput gaps must remain explicit until separately receipted.

## Current Receipt

Current receipt: `receipts/4090-data-governance-2026-06-30.json`. Validator: `scripts/validate_4090_data_governance.py`.
