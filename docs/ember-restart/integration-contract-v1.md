goal_id: EMBER-02
workstream_id: EMBER-02A
next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

# Ember owned-rung integration contract v1

Status: executable candidate/admission boundary under the current
`goal_executing` authority, with every checkpoint-consuming command still
required to fail closed until its named receipts exist. The canonical subject
is `manifests/ember-current-subject-v1.json`: the exact clean-owned step-2
checkpoint manifest is
`BF20F05018991EB611B0623EDD50A00EC30639DA2F8CCAE646F6962F152A2A2B`,
with 3,839,161,856 unique/trainable/served parameters,
1,020,589,568 active parameters, 2,048 observed text tokens, and the
shared route only. It is
structural resume/checkpoint evidence, not sufficiently pretrained and
not capability-admitted. Its disposition is `CHECKPOINT_CANDIDATE_NOT_ADMITTED`.
The prior 1,024-token
`AF954C22FB8FB7A0DC640BFD2E0AB97E8E4CDE989607372FC45C3DB7878699A4`
subject is preserved as the historical step-1 predecessor, not presented as
current. Allocation, custody, and a validated scorer do not authorize
capability or admission claims.

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

The executable authority is `src/ember/governance/scripts/ember_restart/contract.py`. A candidate is checked with:

```text
python src/ember/governance/scripts/ember_restart/contract.py validate <run-manifest.json> --trusted-verifier-registry <trusted-verifiers.json>
```

An admission attempt is checked with an independently supplied verifier registry:

```text
python src/ember/governance/scripts/ember_restart/contract.py validate <run-manifest.json> --trusted-verifier-registry <trusted-verifiers.json>
```

The registry is a separate command-line input for both candidate and admission validation. A run manifest cannot declare its own parameter-realization, sufficiency, or evaluation verifier trusted. The content-addressed parameter counter is executed only when its exact bytes are independently admitted for the `parameter_realization` evidence class.

## `CHECKPOINT_CANDIDATE`

A candidate must bind all of the following:

- clean owned random initialization, null parent, and explicit false values for borrowed weights, teachers, judges, filters, and generated labels;
- allocated, unique, total-trainable, and served parameter counts of at least 3,000,000,000; episode-active and episode-trainable counts are positive, bounded by total capacity, and strictly sparse; all six values must equal the validator's independent recomputation for the content-addressed `ember-sparse-3b-v2` model config and also match the output of a content-addressed counter executed in isolated Python mode against that config and exact checkpoint manifest, with the receipt bound to the counter-source bytes, active route, and expert-genesis shard hashes;
- one `ember-unified-decoder` using raw image patches and audio frames, decoder soft-token splicing, multimodal-span attention, 2D-capable positional treatment, and no separate pretrained encoder;
- a shared core with an always-active nonlinear SwiGLU text FFN plus exactly four asymmetric vision, audio, reasoning, and tool expert banks, each bound to its own content-addressed checkpoint shard with distinct verified bytes; exactly one route is active per episode: `shared` for semantic text or one declared domain expert in addition to the shared core;
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

- a `PASSED` `ember-sufficient-pretraining-v2` receipt bound to the exact checkpoint-manifest SHA-256, content-addressed training ledger, stopping evaluation, and checkpoint progression; it records checkpoint-matching tokens, GPU-hours, modality exposure, and held-out measurements, and its independently trusted local verifier is executed with fixed arguments against those artifacts with output required to match the receipt;
- a minimum non-bootstrap scale floor: total observed training tokens are at least the checkpoint's total trainable parameter count, and each of text, image, audio, reasoning, and typed-tool training has at least 1,000,000 observed tokens;
- held-out learning evidence over at least 1,000,000 held-out tokens, using the closed `plateau-and-heldout-v2` criterion, with content-addressed genesis/final measurements over the identical frozen split, harness, and protocol, and finite final loss at least 10 percent below the bound genesis loss;
- a progression of at least three distinct content-addressed `ember-sparse-checkpoint-v3` manifests with complete shard byte/hash records and strictly increasing manifest-bound token cursors, whose first checkpoint binds the genesis measurement and whose terminal checkpoint/path/token count exactly binds the admitted subject;

These numeric gates are only a fail-closed minimum that prevents a random or few-token checkpoint from being renamed "sufficiently pretrained." They do not establish compute-optimal training, useful capability, baseline competitiveness, or the final >27B target. Those claims still require the independent checkpoint-bound external evaluations and comparative evidence below.

- exactly one checkpoint-bound `MEASURED` external-evaluation receipt for each of text, image, audio, reasoning, and typed tools; every receipt binds benchmark ID/version, split, harness, protocol, raw predictions, score artifact, nonzero sample count, finite numeric metrics, and a capability-specific `PASSED` criterion; the exact local verifier bytes must be externally trusted for that criterion and are executed with fixed arguments against those artifacts, with output required to match the receipt;
- raw predictions use the closed `ember-owned-predictions-v1` envelope validated by
  `src/ember/governance/scripts/ember_restart/prediction_contract.py`. The envelope binds the exact checkpoint
  manifest, model config, owned tokenizer, inference implementation bytes, benchmark,
  version, capability, split, protocol, decoding parameters, per-row input hashes,
  generated token IDs, stop reasons, and typed outputs. Decoding must be greedy and
  autoregressive with teacher forcing explicitly false. Text, reasoning, audio, MMMU,
  Spider, and typed-tool adapters materialize scorer inputs without changing answers;
- verifier-byte hashes admitted for the correct evidence class by the externally supplied trusted-verifier registry;
- a content-addressed serving manifest whose seat is exactly `OWNED_ADMITTED`, checkpoint binding matches the training and evaluation subject, endpoint is loopback HTTP, protocol is `openai-chat-v1`, identity route is `/v1/models`, and server implementation path/hash binds the exact local source bytes that serve the checkpoint.
- Ember CLI executes the checked-in central resolver against the run manifest and independently supplied verifier registry before selecting that seat. It then requires the live identity route to return the exact admitted seat, checkpoint SHA-256, and derived `ember-owned:<12 hex>` model name before session initialization.
- `EMBER_OWNED_RUNG_MANIFEST` selects an explicit run manifest; otherwise the CLI checks `EMBER_HOME/owned/current.json`. A present manifest without its independent registry fails closed. `EMBER_MODEL_URL` may not redirect the admitted identity.

Efficiency, retention, deletion/ablation, comparator gaps, and honest deficiencies remain required completion evidence. They cannot substitute for the five capability receipts.

## Truth states

- `CHECKPOINT_CANDIDATE`: bound bytes exist; no sufficiency or capability credit.
- `OWNED_ADMITTED`: the complete admission evidence above validates; this is the only state that may unlock Ember CLI's ordinary owned-model seat.
- anything else: Ember CLI remains fail closed, with borrowed models available only through the explicit `REFERENCE_ONLY` seat and no target-lineage credit.

## Next execution

The exact step-2 checkpoint is both parent and immutable root of the first v4 expert-accretion episode. The older step-1 checkpoint remains historical evidence; it is not claimed as a cryptographically proven parent of step 2. Before any checkpoint-consuming GPU command, the public path must:

1. remove the permissive legacy continuation bridge and require exact step-2 parent/root identity;
2. emit and independently trust a closed, same-byte hardened-counter realization receipt for the exact step-2 manifest, config, counts, route, expert genesis, and parameter bytes;
3. consume the canonical owned prompt and frozen split, bind runtime source/config/tokenizer from the same byte snapshots, reject provisional receipts, and use same-open-handle required-shard loading;
4. run the clean-checkout shared-text raw forward, scorer, preflight, and ordinary owned Ember CLI replay while retaining the `NON_CLAIM_RAW_FORWARD`/failed-criterion boundary.

The immediate CPU commands are the focused lineage/counter/verifier and prompt/runtime contract suites plus the repository guard on their exact proposed heads. No GPU dispatch is authorized by this contract state. After those increments merge and independently pass, a disk-budgeted clean-checkout shared-text forward is the next GPU command; only its exact outputs may proceed to scoring and preflight. None of these steps authorize sufficient-pretraining, capability, competitiveness, admission, or field-level credit.
