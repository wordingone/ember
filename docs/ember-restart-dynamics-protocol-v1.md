<!-- goal_id: EMBER-02 -->
<!-- workstream_id: EMBER-02C -->
<!-- next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember -->
# Ember Restart Dynamics Protocol v1

This protocol covers the checkpoint-bound efficiency, retention, and
deletion/ablation families required by the restart contract. None may be
replaced by a configuration claim, training log summary, or self-report.

## Efficiency

Before target inference, freeze the hardware identity, runtime/build hashes,
precision policy, batch/sequence shape, decoding parameters, warm-up count,
measurement window, and counter source. Record per-window wall time, tokens,
peak allocated memory, andâ€”when a local counter is availableâ€”energy or average
power. Report throughput and uncertainty from the preserved raw windows.

Comparator throughput is valid only under the same hardware, runtime,
precision, prompts, output cap, and measurement window. A different device or
batch shape is a separate result, not a comparator gap.

## Retention

Freeze a non-overlapping local evaluation slice and its scorer before selecting
the checkpoint sequence. Measure each named owned checkpoint under identical
prompt and decoding settings, preserving per-item rows. Report the sequence,
absolute score, change from the immediately preceding owned checkpoint, and
uncertainty. Missing earlier checkpoints or changed slice bytes are visible
gaps, not evidence of retention.

## Deletion and ablation

This family activates only when a promoted expert, permanent-growth mechanism,
or deletion claim exists in the owned lineage. Before applying the operation,
freeze the target checkpoint SHA-256, mechanism identifier, intervention code,
seed, affected parameters/artifacts, counterfactual policy, and the same
capability slices used for comparison. Preserve pre/post hashes, affected-item
logs, score deltas with uncertainty, and any failure to recover.

If no such mechanism has appeared, the manifest must record
`NOT_APPLICABLE_NO_PROMOTED_MECHANISM`; it is not a passing ablation result.
If it appears but cannot be reproduced from the retained checkpoint and
intervention bytes, record a visible failure rather than a qualitative claim.
