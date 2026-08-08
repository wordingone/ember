# Issue #701 fixed-capability growth conservation ruling

Status: `SUPERSEDED_NOT_PLANNED` for the historical 2.2B/cbase matched-step
vehicle, conditional on accepted transfer to EMBER-05/#1119.

Source master: `87f9669c537715ff0008080c22002eff04040bba`.

Review packet SHA-256:
`4B58EA388CB411875697B0537200017BBB76521C05063670008C620CC6C9A6B0`.

## Canonical owner transfer placeholders

Canonical owner: EMBER-05/#1119. Existing accepted #1119 comment
`5099471639` preserves the matched grow-versus-from-scratch experiment, but a
#701-specific append is still required for the crossing amendments below.

- accepted #1119 transfer: https://github.com/wordingone/ember/issues/1119#issuecomment-5224705111
- bidirectional source link: https://github.com/wordingone/ember/issues/701; its terminal closure comment must link this carrier and the accepted transfer after merge
- version-controlled carrier gate: https://github.com/wordingone/ember/pull/1552 at exact candidate head `780f8fe4580216e61734ad66df7c3e193d235afd`; closure remains forbidden until this carrier is independently reviewed, green, and merged

## Historical-only retirement

The old cbase subject, its 2.2B identity, and the `2.4309x` same-step ratio are
historical measurements only. Same step count is not fixed capability. Current
authority requires an owned clean-genesis model with at least three billion
unique parameters; the historical trainer cannot be revived.

The historical single-seed control reaching the old target at least `6.302x`
more cheaply remains a regime-bounded negative prior. It is not a general kill
of growth and is not overwritten by this ruling.

## Lossless surviving contract

- Compare a current owned at-least-3B grow path with a from-scratch model at
  the same final width.
- Freeze the heldout evaluator and a data-disjoint heldout slice before either
  arm runs.
- Use byte-identical initialization across arms, or an explicitly controlled
  initialization whose difference is preregistered and receipt-bound; match
  data, data order, optimizer, evaluation, tuning budget, and stopping rules
  across arms.
- Evaluate both arms before training. If either complete initial uncertainty
  interval already meets the joint target, refuse as
  `TARGET_INVALID_ALREADY_MET` and freeze a harder target under a new prereg ID.
- The target must clear both initial evaluations by a preregistered noise
  margin, name every capability component, and require all components at one
  checkpoint.
- Measure sustained crossing on a common cumulative-FLOP evaluation grid or
  retain exact per-arm crossing intervals end to end.
- Preserve valid non-crossing as right-censored bounds rather than dropping an
  arm or inventing a ratio.
- Charge grow transformation, optimizer-state migration or reset,
  checkpoint/load, evaluation, recovery, and all training work separately.
- Preserve the historical self-referential-target warning and freeze a target
  externally rather than locating it where a hindsight-fit ladder stopped.
- Publish positive, negative, censored, and inconclusive outcomes under one
  frozen grammar.

## Exact falsifier and reopen rule

No current at-least-3B, independently replayable paired package satisfying
every clause above means no fixed-capability growth-efficiency result exists.
Any moved target, unequal data/order/tuning, unequal evaluation cadence,
initially met target, uncensored non-crossing, or omitted cost invalidates the
ratio and keeps the canonical EMBER-05 obligation open.

## Credit boundary

- `completion_credit=false`
- `scientific_execution_credit=false`
- `acquisition_credit=false`
- `result_credit=false`
- `gpu_credit=false`
- `training_credit=false`
- `checkpoint_credit=false`
- `capability_credit=false`
- `milestone_credit=false`

Current Ember Lab, governed execution, and the EMBER-05 receipt spine are the
sole authorities.

`NO_NEW_PARALLEL_AUTHORITY`
