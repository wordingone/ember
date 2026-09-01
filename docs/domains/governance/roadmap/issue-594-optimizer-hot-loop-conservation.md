# Issue #594 terminal conservation ruling

Status: `SUPERSEDED_NOT_PLANNED` for the historical v9/C8/2.2B optimizer
hot-loop vehicle. Current optimizer and transition obligations belong to
#707; current resource, process and operational custody belongs to #898.

Source master: `87f9669c537715ff0008080c22002eff04040bba`.

## Authority and credit boundary

- `completion_credit=false`
- `result_credit=false`
- `gpu_credit=false`
- `training_credit=false`
- `checkpoint_credit=false`
- `capability_credit=false`
- `milestone_credit=false`

## Settled historical attribution and custody gap

AC1 is standing, settled and not in dispute as historical public-comment
attribution evidence:

- M1 PowerShell governor spawning measured `2.424-2.556 s` per call times
  140, or `339-358 s/step`, and was dominant/not killed;
- M2 truncate/re-create measured `5.91 s/step` and was killed;
- M5 transfer measured `1.93 s` and was killed;
- M3 mapped dirty write measured about `23.89 s/step` and survived as a
  secondary term;
- M4 NS measured `86.5 s` with the missing-normalization/numerical-overflow
  caveat; and
- the historical composite was `476 s/step`.

The runner script and component-benchmark receipt bytes remain off-repository
and custody-incomplete, merely queued for a tracked landing. Public comments
preserve the accepted attribution, but they are not tracked-byte custody and
do not create a current-3B or post-cure result.

AC2 remains unexecuted and retracted. No post-cure governed block exists,
merged #619 did not semantically cure the path, and permission to launch was
withdrawn before execution.

## Lossless current obligations

Preserve R2 in-process commit reads; R3 persistent shadow gradients/direct
copy with zero steady-state lazy creates and governor calls; R4 an in-run pace
gate; R1 current CUDA NS engagement, bit-equivalence and peak-reduction proof;
exact admitted current-3B source/config/checkpoint/optimizer identity;
whole-run and intra-step allocation coverage; structured worker traces;
receipt-before-abort; and negative, rollback, source-drift and foreign-launcher
refusal evidence.

Canonical transfer URL placeholders:

- optimizer / #707: https://github.com/wordingone/ember/issues/707#issuecomment-5224552197
- Ember Lab resource authority / #898:
  https://github.com/wordingone/ember/issues/898#issuecomment-5224552487

The accepted #627 transfers on #707 and #898 are substrate, not a substitute
for this explicit #594 evidence and correction chain.

## Reopen and falsifier

Reopen if a transfer calls AC1 provisional, omits the custody gap or correction
chain, credits AC2, drops R2/R3/R4/R1, or promotes historical measurements
across scale. A current result requires tracked evidence and a governed
post-cure current-3B block.

`NO_NEW_PARALLEL_AUTHORITY`
