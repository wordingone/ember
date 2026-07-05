# Parity Receipts

This directory contains **parity verification artifacts** produced by the board-suite port validation — not live board state.

Parity receipts demonstrate that the ported board conditions and their verdict logic faithfully reproduce the original semantics. They are verification evidence, not canonical board state.

**Why separate?** The canonical `receipts-totality/` directory must remain lexically newest-clean: any automated logic that picks the newest receipt by modification time must pick from active board verdicts, never from stale verification artifacts. Moving parity receipts to this isolated directory preserves that invariant and makes the receipt-storage architecture explicit.

**How to read them:** Parity receipts follow the same JSON schema as active board receipts (see `ember-totality-*.json` structure in the root `receipts-totality/` directory). They are produced by running the board suite against a fresh snapshot of the ported conditions and comparing the output signature against the pre-registered parity profile.
