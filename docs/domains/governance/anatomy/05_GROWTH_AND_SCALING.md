# 05 — Growth and Scaling

## C-GROW: function-preserving capacity growth

Condition `C-GROW` (`docs/domains/governance/spec/conditions-v1.md` §4.2; check function
`chk_cgrow` in `src/ember/governance/scripts/ember_tally_checks.py`) requires a MEASURED
function-preserving grow step with fewer FLOPs than training the grown
target from scratch. Two mechanisms are recognized
(`src/ember/governance/scripts/ember_tally_checks.py`, `CGROW_VALID_MECHANISMS`):

- **v2 `ff_widening_net2net`** — widen the FFN (net2net-style), preserving
  function via logit/loss-delta tolerances (`CGROW_LOSS_DELTA_TOL_CEIL =
  0.10` nats, `CGROW_LOGIT_MAX_DIFF_CEIL = 1e-2`), then compare
  first-to-target FLOPs for the warmstart arm vs. a from-scratch arm
  (`ratio_scratch_over_warmstart > 1.0` required).
- **v3 `identity_layer_insertion_depth`** — insert identity layers to grow
  depth under a strict iso-FLOP budget (`CGROW_V3_LOGIT_CEIL = 1e-5`,
  `CGROW_V3_LOSS_DELTA_CEIL = 1e-4` — essentially zero in float32), with both
  the warmstart and scratch arms held within ±1% of the same FLOP budget
  (`CGROW_V3_BUDGET_TOL = 0.01`) and an eval-loss inequality proving the
  claimed direction.

A companion cross-arm sweep check (`chk_cgrow_v3_sweep`) validates multiple
v3 receipts at distinct growth fractions `f` share one iso-FLOP budget and
either distinct eval-batch hashes per arm or a documented shared-batch
rationale — guarding against undocumented cross-arm evaluation leakage.

`src/ember/governance/scripts/ember_growth_harness.py` ("Repeated-cycle growth gate for Ember MVP
receipts") separately enforces `MIN_REPEATED_POSITIVE_CYCLES = 3` — a growth
claim must be backed by at least three repeated positive cycles, not a single
lucky run, before the harness accepts it.

## C-SCALE: the non-toy operating point

`docs/domains/governance/spec/conditions-v1.md` describes `C-SCALE` as "the APEX; the green
board is the WARM-UP, this is the WIN" — it requires the self-modification
gain (C7 operator load-bearing + C14 neural resident + C8
contribution-deletion) demonstrated at a non-toy operating point reached by
measured growth (C-GROW) from the owned seed (C-BASE), dense-undismissable at
matched active-compute budget against the dense scaling-law frontier
projection. `src/ember/governance/scripts/ember_c_scale_s3_producer.py` is the producer script
referenced by the last board render's C-SCALE row.

## Current gaps — honestly stated

The last board render (`ember-totality-20260801T052815Z.json`) had `C-GROW`
GREEN (a measured receipt exists under `receipts/cbase-grow-rung/`) but
`C-SCALE` RED: "1 candidate receipt(s) present but NONE satisfy the CHK ->
['c-scale-s3-working-set-20260704T122236Z.json: operating_capability_point=None
not a number > 3e+09 (toy scale is not undismissable)']." In plain terms: a
growth mechanism has been measured and validated in isolation, but no
candidate has yet reached the non-toy operating point C-SCALE requires.
