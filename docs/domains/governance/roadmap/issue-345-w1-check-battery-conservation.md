# Issue #345 terminal conservation ruling

Status: `SUPERSEDED_NOT_PLANNED` for the historical W1 cbase
step-50 / step-766 check battery. The surviving current-scale growth
interpretation obligations are conserved by canonical EMBER-05 issue #1119.

Source master: `87f9669c537715ff0008080c22002eff04040bba`.

## Authority and credit boundary

- `completion_credit=false`
- `result_credit=false`
- `gpu_credit=false`
- `training_credit=false`
- `checkpoint_credit=false`
- `capability_credit=false`
- `milestone_credit=false`

No check in the historical battery is credited as executed by this ruling.
The old checkpoints remain provenance only and are not admissible current
research subjects under the 3B floor.

## Lossless check contract

The following obligations transfer without narrowing:

1. Re-evaluate the grown checkpoint on the fixed certified 16-window target
   batch ten times, with FP32 loss accumulation and enumerated fixed seeds.
   Diff the launch-time and in-loop evaluation paths for mode or dtype
   asymmetry. The collapse reading is killed if the FP32 target lands
   materially below `9.375`.
2. Certify at least 160 fresh clean windows, yielding at least ten
   non-overlapping 16-window batches. Evaluate the exact step-50 control
   checkpoint against the grown checkpoint, retain per-batch paired
   differences, and compute the frozen bootstrap 95 percent confidence
   interval. A bare token match is never sufficient.
3. Evaluate the genuine pre-grow checkpoint, then continue it unwidened for
   exactly `1,572,864` tokens and compare it with the post-grow checkpoint at
   matched marginal tokens. Keep the grow-step marginal bill separate from
   the cumulative lineage bill.
4. Preserve the receipted `0.7059` evaluation-noise statistic only as
   cross-checkpoint context; the paired design must not depend on its
   transferability.
5. Preserve cost ordering, identity-bound receipts, exact data positions,
   resource-governed launches, and refusal when certification or identity is
   missing.

## Lossless transfer

Canonical transfer URL placeholder:

- EMBER-05 / #1119: https://github.com/wordingone/ember/issues/1119#issuecomment-5224550783

#1119 owns current 3B-or-larger differentiated growth, paired dense and
schedule controls, persistence, transfer, deletion, and matched quality. It
must retain this battery as interpretation law rather than inheriting a W1
result.

## Reopen and falsifier

Reopen if the accepted transfer omits the fixed target batch, `9.375` kill
threshold, exact step-50-versus-grown pair, fresh-window certification,
paired CI, exact `1,572,864`-token unwidened control, cumulative-versus-
marginal distinction, or evaluation-noise caveat. Any current growth reading
without those gates is refused.

`NO_NEW_PARALLEL_AUTHORITY`
