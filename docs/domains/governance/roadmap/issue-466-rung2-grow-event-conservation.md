# Issue #466 terminal conservation ruling

Status: `SUPERSEDED_NOT_PLANNED` for the historical 2.2B rung-2 grow runner
and llama-server window. The surviving growth science is conserved by
EMBER-05 issue #1119, optimizer and transition-equivalence work by #707, and
control/resource custody by #898.

Source master: `87f9669c537715ff0008080c22002eff04040bba`.

## Authority and credit boundary

- `completion_credit=false`
- `result_credit=false`
- `gpu_credit=false`
- `training_credit=false`
- `checkpoint_credit=false`
- `capability_credit=false`
- `milestone_credit=false`

Historical runner selftests prove apparatus shape only. The real grow event
did not complete and receives no current execution credit.

## Preserved phase contract

The current owner must retain the strict order
`PREFLIGHT -> B1 -> B1m -> B2 -> B3 -> STABILIZATION -> SERVER_RESTORE`,
with every phase refusing without the previous content-addressed receipt.

- PREFLIGHT binds host commit, GPU headroom, disk headroom, exact source,
  executable, config, data, lease, process and artifact identities.
- B1 takes a quiescent double-SHA snapshot and binds model, optimizer, RNG and
  nonzero momentum provenance.
- B1m bypasses the dataloader with serialized tensors and records the exact
  ordered per-microstep eight-tuple identity over
  `(input_ids, attention_mask, position_ids, labels)` for all eight
  microsteps, with dropout-free deterministic QAT state.
- B2 refuses `eps=0`, includes epsilon parameters in every cache key, and
  verifies loaded post-grow weights for realized eta RMS versus tau and
  `twin_cosine < 1` for every split pair.
- B3 compares an explicit zero-momentum reset arm with a disclosed momentum
  transplant arm, emits the transition decomposition fields, and adjudicates
  gate-only behavior against the frozen scale-convention `sqrt(2)` null.
- STABILIZATION remains exactly 30 steps / 491,520 tokens, with per-step
  losses, a full optimizer-state checkpoint, and the production estimator
  comparison. Measured VRAM must remain within plus or minus 15 percent of
  `18.253 GiB`; outside-band operation refuses and records DEV-002
  attribution rather than fixing forward.
- SERVER_RESTORE preserves receipt-before-outage, exact process identity,
  planned-outage marker, relaunch and health verification under current Ember
  Lab authority.

Repeated CPU/CUDA placement failures additionally require one structural
cache-load device choke point and phase-entry same-device assertions. Every
original abort band, stale/foreign cache negative and rollback remains live.

## Lossless transfer

Canonical transfer URL placeholders:

- EMBER-05 / #1119: https://github.com/wordingone/ember/issues/1119#issuecomment-5224550960
- optimizer / #707: https://github.com/wordingone/ember/issues/707#issuecomment-5224551169
- Ember Lab resource authority / #898:
  https://github.com/wordingone/ember/issues/898#issuecomment-5224551395

#1119 owns differentiated growth and matched quality. #707 owns optimizer
pushforward versus reset, transition equivalence, current-factor/update-shape
identity, CUDA engagement and matched current-scale controls. #898 owns
dispatch, lease, process-tree, outage, resource and operational receipts.

## Reopen and falsifier

Reopen if any accepted transfer loses the ordered phase chain, exact B1m
eight-tuple, `eps=0` refusal, eta/twin checks, reset/transplant comparison,
`sqrt(2)` null, fixed stabilization bill, estimator/VRAM refusal, structural
device choke point, or resource/rollback negatives. A current claim without a
real complete chain is falsified.

`NO_NEW_PARALLEL_AUTHORITY`
