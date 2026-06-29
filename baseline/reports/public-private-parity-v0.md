# Public/Private Baseline Parity V0

Status: PUBLIC-SAFE VARIANT.
Created: 2026-06-29.

The public `wordingone/ember/baseline` tree intentionally omits private dirty-checkout extraction artifacts:

- `fragments/external-refs-private-v0.jsonl`
- `fragments/external-refs-private-summary-v0.json`

Those files are allowed only in `wordingone/ember-backup/baseline` because they summarize or quote paths from the private dirty checkout. They are not required for a public visitor to audit the external baseline: public-safe source pins, protocols, contracts, receipts, scripts, and reports remain present.

All other public-safe files should match the private tree byte-for-byte except for this parity report and generated manifest/line-ending receipts that name the containing repository path.