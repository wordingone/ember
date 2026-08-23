# Issue #1413 Packed Throughput Implementation Plan

**Goal:** Produce mergeable source for a governed audio-64 packed specialist route and exact >1000 true-token/s close evidence.

**Base:** `bd2a836c894c21d1431e49b3c515d7977fbe3193`

### Task 1: Deterministic specialist-stream remint

- Add RED tests for stale config detection, unchanged non-config commitments, canonical `--check`, and guarded `--write`.
- Add `remint_specialist_stream.py` using `emit_stream_manifest` and `write_stream_build_receipt` in temporary custody.
- Remint the two checked-in artifacts; verify only the config pin and dependent raw manifest/build receipt identities change.

### Task 2: Packed decoder and cursor contract

- Add RED tests for audio-64 shape, record order, exact cursors/hashes, true versus padded tokens, mixed-expert refusal, topology drift refusal, partial-pack refusal, and padding exclusion.
- Add `decode_owned_packed_batch` and a closed packed cursor/receipt schema without changing `decode_owned_batch`.

### Task 3: Packed eager training and equivalence

- Add RED tests proving the unchanged single-record consumer has identical bytes/behavior.
- Add token-weighted single-record reference loss and packed eager loss at identical pre-update state.
- Add packed selection training with optimizer-update global steps, exact resume cursor, checkpoint progress validation, memory counters, and telemetry.

### Task 4: Packed census and Stage-2 activation

- Add RED tests for observation-only census, raw/self hash reopening, signature drift refusal, and capture-boundary ordering.
- Reuse `TrainingSignatureCensus` and `CensusBoundStage2Executor` with the packed batch.
- Require census before activation and zero fallback.

### Task 5: Governed CLI and receipts

- Add preflight, census, BF16, accelerated, and receipt-only comparison CLI surfaces.
- Bind source/config/runner/stream/build/selection/records/tokens/seed/order/cursors/checkpoints and peak allocated/reserved memory.
- Gate closure on true source tokens/s strictly greater than 1000.

### Task 6: Verification and lifecycle

- Run focused RED then GREEN tests through hidden owned processes with finite timeouts and verified cleanup.
- Run remint `--check`, source compilation, repository guard, authority conservation, and exact diff review.
- Freeze exact premerge census and one-step BF16 commands for the integrator; that role executes host-bound legs.
- Obtain independent exact-head review, green required checks, audited merge, merged-source matched arms, terminal receipt review, public #1413 close evidence, and verified issue `CLOSED`.
