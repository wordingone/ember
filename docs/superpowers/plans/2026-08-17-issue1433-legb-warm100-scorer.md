# Issue #1433 Leg-B WARM-100 scorer plan

## Authority and scope

Consume, but do not redefine, the governed semantic runner's published result:
`run_vertical_slice.py` emits a JSON object whose `post_step_checkpoint` is
minted by `published_checkpoint_receipt()`. The scorer takes the exact result
path and caller-pinned SHA-256, reopens both it and the checkpoint, and accepts
only an exact fresh WARM-100 boundary (`data_cursor.global_step == 100`).

The scorer cross-checks the published manifest digest, checkpoint identity,
shard records, and full data cursor against the reopened checkpoint. It refuses
subscale, stale-receipt, and receipt/checkpoint-swap inputs before model load.
Evaluator runs require nonempty raw predictions and bind canonical score bytes;
their output records the consumed run-result digest plus prediction and score
digests. The claim boundary is derived from the accepted checkpoint cursor.

## TDD and verification

1. Add a dedicated fixture test for exact acceptance plus subscale, stale, and
   swap refusals, and for prediction/score hash chaining.
2. Capture RED against the current scorer.
3. Add only the receipt consumer, dynamic boundary, required CLI inputs, and
   output bindings.
4. Run the dedicated test, in-memory compile, the cheap first downstream
   consumer (`scripts/test_cbase_heldout_eval.py`), and `git diff --check`.

HellaSwag's frozen-test versus scored-validation split and any modality-marker
cure remain separate authority dependencies. This change neither repairs nor
claims them.
