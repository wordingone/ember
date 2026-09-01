# Issue #1413 Packed Throughput Design

## Decision

Add one explicit, additive packed-specialist benchmark route. The unchanged single-record specialist consumer remains byte-for-byte unchanged. The new route consumes a caller-bound `ExecutionSelection` in source order, groups exactly 64 records from one expert into each optimizer update, and reports throughput from true non-padding source tokens only.

The first admitted family is `audio` with `all_records_semantic_pretraining_v1`. The verified first 256 records are uniformly 15 tokens, so the fixed 64-record shape contains 960 true tokens, 960 processed tokens, and zero padding. Passing the public greater-than-1000 gate therefore requires a measured forward/backward/update step under 0.96 seconds. This is reachable but not guaranteed; speed alone may fail honestly.

## Authority and stale-pin cure

The canonical indexed stream is deterministic (`INDEX_PURE_NO_PRNG`) and does not store mutable corpus payloads. Current merged config bytes changed from `c267b0de...` to `33a82113...`; all tokenizer, generator, verifier, chunk, family-root, and corpus-root commitments remain identical. A narrow remint command rebuilds both checked-in stream artifacts, refuses drift outside the model-config pin and manifest/build-receipt identities, and supports a non-writing `--check` mode.

The rebuilt selection receipt is derived from the reminted manifest plus its exact build-receipt bytes. Benchmark consumption respects `STREAM_CONSTRUCTION_NOT_SUFFICIENT_PRETRAINING_OR_CAPABILITY`: it produces throughput and parity evidence only, never a capability claim.

## Packed batch contract

Packing validates every input record independently with the existing decoder, then requires:

- exactly one common active expert;
- identical modality/span topology for the admitted static signature;
- 64 records per measured pack;
- source-order preservation and exact start/end selection cursors;
- right padding only, with an explicit boolean loss mask;
- separate `true_source_tokens`, `processed_padded_tokens`, and `padding_tokens` counters;
- record-list, token-list, and pack-signature SHA-256 bindings.

For audio the initial fixed shape has no padding. General right-padding support is still fail-closed and tested so later variable-length packs cannot count padding as throughput.

## Execution and comparison

Three arms use identical source/config/selection/seed/order and fresh genesis:

1. unchanged single-record BF16 at the same pre-update model state, aggregated by token-weighted cross entropy;
2. packed eager BF16;
3. packed census-bound FP8 plus CUDA graphs.

The packed eager loss must match the unchanged single-record aggregate within the preregistered tolerance. The accelerated trajectory must match packed eager within the same tolerance. Global step counts optimizer updates. The data cursor separately records selected ordinal, next source index, records consumed, true tokens consumed, and pack ordinal; checkpoint resume must reproduce the uninterrupted next pack, loss, cursor, optimizer state, and checkpoint identity.

The Stage-2 census is observation-only and minted before activation from a real decoded CUDA pack without model allocation. Activation reopens exact raw and self hashes and refuses any static-signature drift. Decode, clip, optimizer update, FP8 refresh, cursor mutation, telemetry, and checkpoint publication remain outside graph capture.

The terminal comparator requires finite matched losses, exact arm identities, exact cursor/order equivalence, zero fallbacks, real FP8 dispatches, real graph capture/replay, explicit peak allocated and reserved memory, and strictly greater than 1000 true source tokens per second. Processed/padded throughput is reported but cannot satisfy the gate.

## CLI freeze shape

The governed runner gains additive `packed-specialist-preflight`, `packed-specialist-census`, and `packed-specialist` commands. Every command requires the exact stream manifest/build receipt paths and raw hashes, capability/rule, `--pack-records 64`, and a no-overwrite artifact root. Training commands remain disk-budget-runner children. Census is a hidden owned CUDA process and cannot activate training. Baseline and accelerated arms write separate immutable receipts; the existing receipt-only comparator is extended for packed receipts.

## Safety and fallback

No B custody is cleaned or overwritten. Live A-heldout and foreign GPU processes remain untouched. If the fixed audio-64 density becomes invalid, cannot fit the governed memory cap, or distorts the gate, the primary input is disqualified and the reviewer-preauthorized B-train-2 fallback is used only after its current adapter/tranche chain is executable.
