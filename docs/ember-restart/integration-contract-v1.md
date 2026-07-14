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

## Training-input phase boundary

The manifest must bind the exact owned tokenizer bytes to their training script, training-corpus manifest, freeze receipt, and an independently trusted content-addressed tokenizer verifier. The verifier executes against those exact artifacts and must reproduce the receipt, which records the 32k vocabulary, tokenizer/corpus/script/verifier hashes, pre-step-0 freeze, and an explicit false borrowed-tokenizer flag.

Every text, image, audio, reasoning, and tool data binding contains:

- a content-addressed source manifest and the exact content-addressed training-record bytes;
- one class, either `SMOKE_ONLY` or `SEMANTIC_PRETRAINING`, shared by the whole run;
- exact tokenizer, record-count, and token-count bindings with model-mediated data and borrowed labels explicitly false;
- an independently trusted, content-addressed local verifier whose executed output must reproduce the receipt;
- empty semantic checks for `SMOKE_ONLY`; or capability-specific tokenizer round-trip, source/target pairing, and raw-media/local-answer/typed-tool execution checks for `SEMANTIC_PRETRAINING`.

Changing only a manifest label cannot turn smoke fixtures into pretraining data. `OWNED_ADMITTED` requires `SEMANTIC_PRETRAINING` throughout.

The optimizer is one structured object containing implementation, hyperparameters, and state format. That exact object must agree across the run manifest, model config, checkpoint manifest, and optimizer-realization receipt. A checkpoint produced by `torch.optim.AdamW` cannot be described as paged 8-bit AdamW, or vice versa.

## `OWNED_ADMITTED`

Admission adds all of the following without weakening the candidate gates:

- a `PASSED` `ember-sufficient-pretraining-v1` receipt bound to the exact checkpoint-manifest SHA-256, content-addressed training ledger, stopping evaluation, and checkpoint progression; it records checkpoint-matching tokens, GPU-hours, and final loss, and its independently trusted local verifier is executed with fixed arguments against those artifacts with output required to match the receipt;
- exactly one checkpoint-bound `MEASURED` external-evaluation receipt for each of text, image, audio, reasoning, and typed tools; every receipt binds benchmark ID/version, split, harness, protocol, raw predictions, score artifact, nonzero sample count, finite numeric metrics, and a capability-specific `PASSED` criterion; the exact local verifier bytes must be externally trusted for that criterion and are executed with fixed arguments against those artifacts, with output required to match the receipt;
- raw predictions use the closed `ember-owned-predictions-v1` envelope validated by
  `scripts/ember_restart/prediction_contract.py`. The envelope binds the exact checkpoint
  manifest, model config, owned tokenizer, inference implementation bytes, benchmark,
  version, capability, split, protocol, decoding parameters, per-row input hashes,
  generated token IDs, stop reasons, and typed outputs. Decoding must be greedy and
  autoregressive with teacher forcing explicitly false. Text, reasoning, audio, MMMU,
  Spider, and typed-tool adapters materialize scorer inputs without changing answers;
- verifier-byte hashes admitted for the correct evidence class by the externally supplied trusted-verifier registry;
- a content-addressed serving manifest whose seat is exactly `OWNED_ADMITTED`, checkpoint binding matches the training and evaluation subject, endpoint is loopback HTTP, protocol is `openai-chat-v1`, and identity route is `/v1/models`.
- Ember CLI executes the checked-in central resolver against the run manifest and independently supplied verifier registry before selecting that seat. It then requires the live identity route to return the exact admitted seat, checkpoint SHA-256, and derived `ember-owned:<12 hex>` model name before session initialization.
- `EMBER_OWNED_RUNG_MANIFEST` selects an explicit run manifest; otherwise the CLI checks `EMBER_HOME/owned/current.json`. A present manifest without its independent registry fails closed. `EMBER_MODEL_URL` may not redirect the admitted identity.

Efficiency, retention, deletion/ablation, comparator gaps, and honest deficiencies remain required completion evidence. They cannot substitute for the five capability receipts.

## Truth states

- `CHECKPOINT_CANDIDATE`: bound bytes exist; no sufficiency or capability credit.
- `OWNED_ADMITTED`: the complete admission evidence above validates; this is the only state that may unlock Ember CLI's ordinary owned-model seat.
- anything else: Ember CLI remains fail closed, with borrowed models available only through the explicit `REFERENCE_ONLY` seat and no target-lineage credit.

## Next execution

This contract directly enables the model-building founder to preserve the current bounded synthetic-ID run as `SMOKE_ONLY`, bind the checked-in owned tokenizer, replace arbitrary token cycles with content-addressed semantic text/image/audio/reasoning/tool records, make the optimizer declaration match the executed runtime, and run the first disk-budgeted semantic pretraining segment. That segment may emit a `CHECKPOINT_CANDIDATE` for the evaluation founder's frozen preflight. It does not authorize sufficient-pretraining or capability credit from allocation, a dry run, a smoke checkpoint, or a renamed data class.
