goal_id: EMBER-02
workstream_id: EMBER-02A
next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

# Ember owned-rung integration contract v1

Status: executable candidate/admission boundary. This contract does not claim that an owned 3B checkpoint exists.

## Integration ownership

The integration founder declares these integration namespaces before the first commit:

- `docs/ember-restart/`
- `scripts/ember_restart/`
- `tests/ember_restart/`
- the narrow Ember CLI model-seat and process-entry changes required to consume an admitted manifest

The model-building founder retains model, training, checkpoint, and owned-inference implementation namespaces. The evaluation founder retains frozen evaluation, benchmark, and evaluation-receipt namespaces. The integration founder consumes their content-addressed outputs and resolves shared interface changes; no founder writes another founder's worktree.

## One load-bearing object

One `ember-owned-rung-v1` JSON manifest binds the entire path:

`owned data + owned tokenizer -> unified decoder training -> checkpoint shards -> frozen evaluations -> Ember CLI owned seat`

The executable authority is `scripts/ember_restart/contract.py`. A candidate is checked with:

```text
python scripts/ember_restart/contract.py validate <run-manifest.json> --trusted-verifier-registry <trusted-verifiers.json>
```

An admission attempt is checked with an independently supplied verifier registry:

```text
python scripts/ember_restart/contract.py validate <run-manifest.json> --trusted-verifier-registry <trusted-verifiers.json>
```

The registry is a separate command-line input for both candidate and admission validation. A run manifest cannot declare its own parameter-realization, sufficiency, or evaluation verifier trusted. The content-addressed parameter counter is executed only when its exact bytes are independently admitted for the `parameter_realization` evidence class.

## `CHECKPOINT_CANDIDATE`

A candidate must bind all of the following:

- clean owned random initialization, null parent, and explicit false values for borrowed weights, teachers, judges, filters, and generated labels;
- allocated, unique, total-trainable, and served parameter counts of at least 3,000,000,000; episode-active and episode-trainable counts are positive, bounded by total capacity, and strictly sparse; all six values must equal the validator's independent recomputation for the content-addressed `ember-sparse-3b-v1` model config and also match the output of a content-addressed counter executed in isolated Python mode against that config and exact checkpoint manifest, with the receipt bound to the counter-source bytes, active expert, and expert-genesis shard hashes;
- one `ember-unified-decoder` using raw image patches and audio frames, decoder soft-token splicing, multimodal-span attention, 2D-capable positional treatment, and no separate pretrained encoder;
- a shared core plus exactly four asymmetric vision, audio, reasoning, and tool expert banks, each bound to its own content-addressed checkpoint shard, with distinct verified bytes and exactly one declared expert active per episode;
- an owned tokenizer with verified bytes;
- exactly one owned and locally verified data-manifest binding for each of text, image, audio, reasoning, and typed tools;
- positive observed token exposure for all five capabilities and the exact training command;
- a content-addressed checkpoint manifest whose nonempty shard list binds every shard's relative path, SHA-256, and byte count.

Candidate validation proves an internally bound checkpoint path, not sufficient pretraining or capability.

## `OWNED_ADMITTED`

Admission adds all of the following without weakening the candidate gates:

- a `PASSED` `ember-sufficient-pretraining-v1` receipt bound to the exact checkpoint-manifest SHA-256;
- exactly one checkpoint-bound `MEASURED` external-evaluation receipt for each of text, image, audio, reasoning, and typed tools;
- verifier-byte hashes admitted for the correct evidence class by the externally supplied trusted-verifier registry;
- a content-addressed serving manifest whose seat is exactly `OWNED_ADMITTED` and whose checkpoint binding matches the training and evaluation subject.

Efficiency, retention, deletion/ablation, comparator gaps, and honest deficiencies remain required completion evidence. They cannot substitute for the five capability receipts.

## Truth states

- `CHECKPOINT_CANDIDATE`: bound bytes exist; no sufficiency or capability credit.
- `OWNED_ADMITTED`: the complete admission evidence above validates; this is the only state that may unlock Ember CLI's ordinary owned-model seat.
- anything else: Ember CLI remains fail closed, with borrowed models available only through the explicit `REFERENCE_ONLY` seat and no target-lineage credit.

## Next execution

This contract directly enables the model-building founder's disk-budgeted sparse >=3B allocation plus one-real-batch routed vertical slice to emit the first `CHECKPOINT_CANDIDATE` manifest, followed by the evaluation founder running the frozen preflight against that exact manifest. It does not authorize a capability claim from allocation, a dry run, or a toy checkpoint.
