# Issue #704 live-int8 optimizer-state conservation ruling

Status: `SUPERSEDED_NOT_PLANNED` for the old file-backed 2.2B vehicle,
conditional on accepted transfer to #707 and EMBER-02/#1116.

Source master: `87f9669c537715ff0008080c22002eff04040bba`.

Review packet SHA-256:
`4B58EA388CB411875697B0537200017BBB76521C05063670008C620CC6C9A6B0`.

## Canonical owner transfer placeholders

Primary scientific owner: #707. Roadmap owner: EMBER-02/#1116. The int8 route
remains fallback-only behind the current FACTOR-1/precision experiment.

- accepted #707 transfer: https://github.com/wordingone/ember/issues/707#issuecomment-5224705277
- accepted #1116 transfer: https://github.com/wordingone/ember/issues/1116#issuecomment-5224705213
- bidirectional source link: https://github.com/wordingone/ember/issues/704; its terminal closure comment must link this carrier and both accepted transfers after merge
- version-controlled carrier gate: https://github.com/wordingone/ember/pull/1552; closure remains forbidden until its current public head is independently reviewed, green, and merged

## Historical-only retirement

The former 2.2B optimizer files, layout, checkpoint, and traffic constants are
not current execution subjects. A current screen must bind the admitted 3B
optimizer and active files from current bytes.

## Lossless surviving contract

- Freeze group size, scale dtype, padding, headers, and every metadata byte
  before execution.
- Compare realized persisted bytes with the exact attainable analytic count;
  never use an impossible round-number four-times threshold.
- Enumerate and hash the exact files backing live per-step state. Checkpoint or
  export compression cannot satisfy the active-state gate.
- Inventory all persistent, transient, and checkpoint surfaces. An FP32 mirror
  or fallback beside active int8 state refuses the experiment.
- Mutate a known active int8 group and scale between save and stream-in and
  require predictable decoded-state and next-update changes.
- Receipt per-step payload, scale, temporary, read, write, and checkpoint bytes.
- Prove stream-in from int8, re-encoding on write, and restart from int8 active
  state with no FP32 rehydration residue.
- Preserve matched seeds, exact data order, the step-time overhead gate, paired
  quality/stability band, resource envelope, negative fixtures, and rollback.

## Exact falsifier and reopen rule

Checkpoint-only quantization, an active FP32 mirror, missing causal mutation,
missing byte counters, absent restart evidence, or absent current-3B paired
quality evidence means no optimizer-state result. #704 retirement does not
promote int8 and does not weaken #707's sequencing or falsifiers.

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

Current Ember Lab, #707, EMBER-02, and the governed optimizer receipt path are
the sole authorities.

`NO_NEW_PARALLEL_AUTHORITY`
