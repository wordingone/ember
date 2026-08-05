<!-- goal_id: EMBER-02 -->
<!-- workstream_id: EMBER-02C -->
<!-- next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember -->
# Ember Restart Evaluation Results

This surface may render only the output of
`scripts/ember_restart_eval_result_surface.py`. That renderer labels an
evaluation as **MEASURED CAPABILITY** only after the central admission contract
has independently admitted the exact receipt; every other record is **NOT
CLAIM-BEARING**.

## Current disposition

No corrected v3-or-successor owned checkpoint bundle is currently available to
the evaluator. Historical v2 snapshots are retained solely as bootstrap and
raw-forward evidence; they are not corrected-rung capability evidence. No
capability score is reported here.

The historical v2 checkpoint input verifier executed against manifest
`355bedc5f2cda3b3c17d5eed3d639f6a8d0ed00d3b4bf6203942d188a8585df9` and
verified its six declared shard bytes. Its result is
`HISTORICAL_V2_INPUT_ONLY` with `NOT_ELIGIBLE` admission. An archived decoder
source is available, but its available configuration hashes to
`e1351e61c9ede811dc484bb698c4113740c648a1ac434bcdf6fa8f436eb4a5e6`, which
does not equal the v2 manifest-bound configuration hash
`ad12a162479ea2ded8bc29bb0c1e7d1894af37899cdd292877a816b1c17fb61b`.
Consequently no historical raw forward, prediction envelope, or score has been
emitted from that source/config pair.

## Required result record

Before adding any result, preserve the checkpoint manifest hash, evaluator
commit, benchmark version/split, harness and protocol hashes, raw predictions,
score artifact, resource receipt, variance, and comparator identity. The
completion-certificate validator rejects a record that omits honest unresolved
gaps or inflates a preflight into a measured result.
