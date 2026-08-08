# Issue #703 PPM capability-floor conservation ruling

Status: `SUPERSEDED_NOT_PLANNED` for the historical experiment carrier,
conditional on accepted transfer to EMBER-02/#1116.

Source master: `87f9669c537715ff0008080c22002eff04040bba`.

Review packet SHA-256:
`4B58EA388CB411875697B0537200017BBB76521C05063670008C620CC6C9A6B0`.

## Canonical owner transfer placeholders

Canonical owner: EMBER-02/#1116. This file is safe to publish in the grouped
capability-measurement carrier with #705 and #782, while retaining independent
issue identity and falsifiers.

- accepted #1116 transfer: https://github.com/wordingone/ember/issues/1116#issuecomment-5224705162
- bidirectional source link: https://github.com/wordingone/ember/issues/703; its terminal closure comment must link this carrier and the accepted transfer after merge
- version-controlled carrier gate: https://github.com/wordingone/ember/pull/1552; closure remains forbidden until its current public head is independently reviewed, green, and merged

## Historical-only retirement and corrected classification

The old STEP50 checkpoint, tokenizer `2c557...`, shards-v0 slice, and their
sub-3B identities are historical provenance only. The experiment is not neural
training-data-efficiency evidence. PPM has zero trainable neural parameters,
not zero parameters or zero cost: its corpus-derived state, source bytes,
state bytes, build cost, and evaluation cost are part of the claim.

## Lossless surviving contract

- Preserve three separate arms: current checkpoint only, standalone PPM only,
  and a normalized checkpoint-plus-PPM blend.
- Define a PPM token probability as byte-LM mass over future byte strings whose
  actual tokenizer emits that token next.
- Bind normalizer, pre-tokenizer, model, merge rules, decoder, prefix
  competition, byte fallback, special tokens, EOS/EOT, and boundary behavior.
- Ban naive per-token byte-string score renormalization.
- Require adversarial tiny-lattice enumeration, a toy lattice matching the
  real tokenizer class, a live full-vocabulary mass check, telescoping proof,
  and the frozen negative fixture.
- Preserve the alphabet-257 EOT convention and disclose that the BPB numerator
  includes terminal EOT while the raw-byte denominator excludes it.
- Positionally separate PPM-train, calibration, and evaluation slices; perform
  content-level near-duplicate scans and retain checkpoint-training versus
  evaluation contamination status.
- Freeze lambda on calibration data disjoint from evaluation, the SESOI,
  bootstrap constructors, influence diagnostic, and exhaustive verdict lattice.
- Report BPB, latency per byte, CPU energy, state bytes, build cost, and the
  amortization schedule without a dimensionally invalid exchange rate.
- Bind the current 3B checkpoint, corpus, tokenizer, scorer, and all exact
  source bytes before any current measurement.

## Exact falsifier and reopen rule

Missing current custody or any failed lattice, normalization, telescoping,
disjointness, deduplication, planted-gain, endpoint-identity, cost, or verdict
gate prevents a claim-bearing floor or blend result. A standalone floor result
never becomes a training-data-efficiency or model-capability claim.

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

Current Ember Lab, EMBER-02, and the existing evaluation/custody spine remain
the sole authorities.

`NO_NEW_PARALLEL_AUTHORITY`
