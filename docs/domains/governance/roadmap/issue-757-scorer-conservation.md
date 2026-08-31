# Issue #757 program-level scorer conservation ruling

Status: `SUPERSEDED_NOT_PLANNED` for the historical W1 scorer carrier,
conditional on accepted transfer to EMBER-02/#1116.

Source master: `87f9669c537715ff0008080c22002eff04040bba`.

Review packet SHA-256:
`4B58EA388CB411875697B0537200017BBB76521C05063670008C620CC6C9A6B0`.

## Canonical owner transfer placeholders

Canonical owner: EMBER-02/#1116. Publish with baseline tracker #735.

- accepted #1116 transfer: https://github.com/wordingone/ember/issues/1116#issuecomment-5224705589
- bidirectional source link: https://github.com/wordingone/ember/issues/757; its terminal closure comment must link this carrier and the accepted transfer after merge
- version-controlled carrier gate: https://github.com/wordingone/ember/pull/1552; closure remains forbidden until its current public head is independently reviewed, green, and merged

## Historical-only retirement

The historical STEP50 model, tokenizer, local scorer, ARC and HellaSwag
aggregates, and MMLU-Pro capacity mismatch remain provenance. Aggregate-only
receipts do not become a current 3B baseline.

## Lossless surviving contract

- The scorer owns exact context/continuation encoding and teacher-forced causal
  alignment; it never retokenizes a concatenated string.
- Preserve merge-boundary, off-by-one, missing-response-shape, wrong-checkpoint,
  wrong-tokenizer, and same-shape corruption negatives.
- Integrate through the exact installed evaluator and task semantics.
  Generation tasks may not silently become teacher-forced multiple choice.
- Deterministic generation binds prompt, stops, filters, extraction, few-shot
  settings, and maximum-token policy, or records an explicit incompatibility.
- Run complete canonical task traversals with exact sample counts, metrics,
  uncertainty, request coverage, deterministic identity, realized device, and
  zero paid API use.
- GPU use requires governed device custody and bounded CPU-versus-GPU score
  parity before its metrics are admitted.
- Emit one per-sample row `{item_id, gold, prediction, correct}` and bind a
  standalone deterministic reducer that reproduces every aggregate.

## Exact falsifier and reopen rule

Aggregate-only evidence, a limited sample smoke, missing reducible outputs,
silent task substitution, unbound checkpoint/tokenizer/device identity, or an
unresolved installed-task mismatch is not a trustworthy baseline.

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

Current Ember Lab, EMBER-02, and the current evaluator/checkpoint/custody spine
remain the sole authorities.

`NO_NEW_PARALLEL_AUTHORITY`
