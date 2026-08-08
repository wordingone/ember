# Issue #735 trustworthy-baseline conservation ruling

Status: `SUPERSEDED_NOT_PLANNED` for the historical W1 STEP25-to-STEP50
vehicle, conditional on accepted transfer to EMBER-02/#1116.

Source master: `87f9669c537715ff0008080c22002eff04040bba`.

Review packet SHA-256:
`4B58EA388CB411875697B0537200017BBB76521C05063670008C620CC6C9A6B0`.

## Canonical owner transfer placeholders

Canonical owner: EMBER-02/#1116. Publish with scorer tracker #757.

- accepted #1116 transfer: https://github.com/wordingone/ember/issues/1116#issuecomment-5224705455
- bidirectional source link: https://github.com/wordingone/ember/issues/735; its terminal closure comment must link this carrier and the accepted transfer after merge
- version-controlled carrier gate: https://github.com/wordingone/ember/pull/1552; closure remains forbidden until its current public head is independently reviewed, green, and merged

## Historical-only retirement

The W1 STEP25 and STEP50 checkpoints, their tokenizer, and the pilot replay are
historical provenance. The replayed model/evaluation evidence does not prove a
current 3B baseline or a bit-exact resumable full state.

## Lossless surviving contract

- Bind the current owned 3B checkpoint, full model and optimizer state, RNG,
  source, tokenizer, corpus, evaluation manifests, and runtime identity.
- Compare every model tensor, including MTP heads, and every optimizer
  tensor/scalar by value and normalized byte identity where required.
- Shape-only optimizer parity and one BF16 loss float cannot prove resumability.
- Reload exact checkpoint bytes and reproduce the frozen evaluation under a
  tolerance declared before replay.
- Place the checkpoint and manifest in durable content-addressed custody, not
  scratch-only storage.
- Execute the current program-level capability battery with exact task
  versions, configurations, complete sample coverage, metrics, uncertainty,
  and claim boundary.
- Preserve incompatible-task, missing-tokenizer, malformed-state, replay
  divergence, and non-comparable states rather than imputing them.

## Exact falsifier and reopen rule

Absent current-3B full-state identity, durable custody, exact reload, or
complete program-level evaluation means no trustworthy current baseline
exists. Historical W1 arithmetic cannot satisfy EMBER-02's checkpoint-bound
capability floors.

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

Current Ember Lab, EMBER-02, and the current checkpoint/evaluation/custody
spine remain the sole authorities.

`NO_NEW_PARALLEL_AUTHORITY`
