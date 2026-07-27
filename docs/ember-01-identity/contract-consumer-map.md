<!-- goal_id: EMBER-01 -->
<!-- workstream_id: EMBER-01C -->
<!-- next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember -->

# Ember identity contract and consumer map

Status: EMBER-01C candidate for EMBER-01A integration. This document defines
field meaning and maps current identity boundaries. It does not select a
canonical checkpoint, authorize a network, or modify a production consumer.

## Normative rules

The machine schema is
`manifests/ember-01-identity/schema-v1.json`. The executable semantics are in
`scripts/ember_01_identity/validate_identity.py`. The schema closes the set of
fields; the validator enforces relationships that JSON Schema cannot express.
The runtime validator loads this exact checked-in schema and reports
`schema.validation` findings before applying semantic admission rules; the CLI
does not maintain a weaker parallel type system.
Neither may derive missing identity from a filename, directory name, UI label,
endpoint, architecture config, tensor shape, or parameter total.

An unknown value is represented only as:

```json
{"status": "unresolved", "reason": "specific evidence still missing"}
```

Every such object must have its exact dotted path in the top-level
`unresolved` list. Missing fields, empty reasons, and undeclared unresolved
objects fail. A consumer that needs executable/admission identity invokes
`--require-resolved` and fails if any unresolved value remains.

### Parameter fields

- `allocated`: logical scalar slots instantiated by the declared architecture.
  It says nothing about training, independence, residency, or use.
- `unique`: distinct stored scalar locations after tied/aliased storage is
  counted once. Independently stored exact copies remain stored parameters but
  receive no learned-capacity credit merely because they occupy storage.
- `active`: unique stored parameters actually exercised by the declared
  episode route. Sparse total and episode-active capacity are never conflated.
- `trainable`: unique parameters enabled for gradient/update and present in
  the optimizer's declared update set.
- `served`: unique parameters verified as loaded and addressable by the
  bound backend process. A config or checkpoint count cannot establish it.
- `actually_trained`: unique parameters with lineage-bound update evidence.
  Allocated copies, untouched experts, exact twins that never diverged, and
  parameters absent from the optimizer/update receipt receive no credit.

`unique <= allocated`; each of `active`, `trainable`, `served`, and
`actually_trained` must be no greater than `unique`. These inequalities are
necessary, not sufficient evidence of useful capacity.

### Checkpoint and lineage

`checkpoint.byte_sha256` binds exact checkpoint bytes. Each tensor binds name,
shape, dtype, and content hash. Ancestry is an explicit ordered relation; the
validator never reconstructs it from directories. Tokenizer, corpus, sample
ordering, curriculum, verifier, optimizer state, numerics, and stopping rule
are separate hashes or explicit values so changing any one changes identity.
The stopping rule is a structured criterion/result/receipt object, never free
text.
For `OWNED_ADMITTED`, hash strings alone are insufficient: the caller supplies
actual checkpoint bytes, an exact tensor manifest, a content-addressed artifact
bundle for every declared architecture/tokenizer/data/order/curriculum/
accepted-shard/caller/gate/validator/optimizer/numerics/backend/ancestry/
mechanism/runtime-dependency object, and
verifier bytes or an independently trusted closed verifier registry. Artifact
entries are rehashed from decoded bytes and checked against the manifest.

### Accepted training-input identity

`data.accepted_input` binds the accepted input ID, shard-manifest bytes,
trainer caller bytes, gate bytes, validator bytes, authority disposition, and
a checkpoint-bound forwarding receipt. Owned admission accepts only
`CURRENT_EXECUTABLE`; `HISTORICAL_REFERENCE` and `UNRESOLVED` remain
preservable evidence but cannot authorize training input, model birth, or a
milestone. The signed forwarding receipt must repeat the exact accepted-input
ID and every component hash and must bind the resulting checkpoint.

The current coordination authority is public issue #812 with body SHA-256
`6876226b0cf0e8f7c99a9b01107b90b8c60ad73f065da5e4ecf24adf7d7930cf`.
Issues #682 and #793 are historical references only, pinned respectively at
`c4f794643ea163cb313fc893637006452ac6abf6ca6ac9b3c1bbe8b1b2b19219`
and `62fe4a4d1eacffea4d1b963015cbdf479490cce78f686e73483525460dae3527`.
Issue text is not artifact
authority by itself: EMBER-01A must resolve the actual accepted shard/caller/
gate/validator bytes into this contract.
The executable trust root is
`accepted-training-input-authorities-v1.json`; admission rehashes its closed
active record and requires manifest and signed receipt to bind authority ID
`ember-02-issue-812`, input ID `github-issue-812`, and active-record SHA-256
`cb77071a43d117d78edb5a7687bd9fcdb0ad8213326bc168dc7e00a3dcf42554`.

### Capability and mechanism state

Native text, image, and audio each have an explicit evidence state and
checkpoint-bound receipt hashes. Reasoning and structured tool use use the same
evidence shape.
Experts, routing, memory substrates, world models, and deletion objects are
identity-bearing arrays. A harness, tool, script, verifier, UI label, human, or
borrowed model cannot supply neural capability credit.

### Owned admission

`OWNED_ADMITTED` is the only disposition eligible for owned selection or
owned-completion credit. Admission additionally requires all unresolved fields
to be absent, clean-genesis ownership, at least 3B allocated/unique/active/
trainable/served/actually-trained parameters, nonzero training exposure for
text/image/audio, verified checkpoint-bound receipts for every native modality
plus reasoning and structured tool use, and a `PASSED`
`ember-sufficient-pretraining-v1` criterion. Any missing proof leaves the
object `OWNED_CANDIDATE`.

Receipt hashes are references, not evidence by themselves. Admission requires a
`--receipt-bundle` whose keys are SHA-256 digests of canonical receipt JSON.
Each referenced receipt is resolved and rehashed, then checked for the exact
checkpoint, verifier, evidence class, result, and (for model birth) allowed
criterion. Missing content, a fabricated hash/content pair, or a receipt for a
different checkpoint/verifier/class fails closed. An admitted identity always
resolves its evaluation receipt even when the result does not count toward
owned completion; disabling completion credit cannot preserve unverified
scientific-result fields.
The CLI therefore requires `--checkpoint`, `--tensor-manifest`,
`--artifact-bundle`, `--receipt-bundle`, and either `--verifier` or
`--trusted-verifier-registry` for an admitted subject. Supplying only mutually
consistent manifest and receipt hashes cannot admit a model.

Learned-signal and neural-credit sources use closed enumerations. Owned
admission accepts only owned training data or locally verified experience as
learned signal, and only owned-checkpoint or checkpoint-bound causal evidence
as capability credit. Renamed external sources cannot pass by avoiding a
denylisted spelling.

### Backend, evaluation, and references

Backend identity binds executable and command bytes, requires the running
process executable hash to equal the artifact-bound backend, and resolves a
signed checkpoint/verifier-bound receipt over process identity, protocol,
device, and resource lease. Runtime dependencies are independently rehashed.
An endpoint is location, not identity. Evaluation binds exact subject checkpoint, benchmark/version/split,
harness bytes/hash, comparator identity plus artifact bytes/hash, score,
uncertainty, and receipt. A
`REFERENCE_ONLY` subject cannot be selected as owned Ember or increment owned
completion.

## Machine census coverage

`manifests/ember-01-identity/consumer-census-v1.json` is generated by
`census_consumers.py` across eight logical public/private/live-local roots.
Git roots are read from exact committed objects, independent of checkout or
index state. Filesystem roots receive deterministic content-universe hashes;
missing or inaccessible roots remain explicit. Absolute host roots are never
serialized.

The preserved environment-bound discovery snapshot contains 65,202 regex evidence
records: 57,707 executable-source line records and 7,495 content-hashed
file/category records for state, config, and documentation surfaces. These are
candidate discovery records, not 65,202 consumers. Every executable matching
line survives. Repeated
JSON/JSONL/log events are represented as one file/category identity surface,
not falsely multiplied into separate code paths. Every row includes source
path, line/content hashes, matched current input, and an exact closed
category-level integration requirement. The snapshot''s earlier generic
derived-label/protocol/failure/conflict fields are superseded and supply no
credit. Its content-bound adjudication overlay fails closed: all 45,607
executable matches remain conservative integration consumers, 7,302 document
or data matches remain identity sources. Test paths are not dismissed: their
57,694 executable matches remain conservative consumers. Nothing among the
discovered rows is left unadjudicated. Thirteen load-bearing
consumers additionally have hand-reviewed semantics bound by exact root, path,
category, and evidence hash in `consumer-semantics-v1.json`.

The preserved multi-root discovery used public master
`1d7c2d2ff13be8bb10ce5e0b731bd190d8e5d138`,
private-backup default `054d6e8d94ea218c3ad3b177df790602fe075b01`,
the live execution tree, benchmark assets, two role-labelled coordination
evidence surfaces, the current EMBER-01C exclusive namespace as a separate
candidate surface, and the
configured-but-missing private backup root. The canonical snapshot is
68,645,445 bytes with SHA-256
`d8350a696e923cdf49374a14d570536b0a7edc7f962b6c12f2afa0780959bdda`.
Two complete unchanged-input environment runs were byte-identical. A
deterministic clean-clone verifier replays the overlay from every exact
content-bound row, producing zero unadjudicated discovered matches. Because
the snapshot is stale, suffix-limited, and contains a missing configured root,
it is environmental discovery only and makes no global-completeness claim. A
host-independent portable profile separately replays the exact substantive PR
source commit with no environment roots. Its checked adjudication manifest
binds every executable decision by path, line, category, and evidence hash;
whole-file nonconsumer decisions additionally bind the file-content hash.
Repeated identical source lines therefore cannot share or overwrite a review
decision. Every executable row is either a reviewed consumer, a reviewed
nonconsumer, or one of the thirteen exact hand-reviewed consumers; zero rows
may remain unresolved. Two complete portable runs must be byte-identical and
all tracked files must be accounted. The exact source commit, counts, canonical
hash, and byte hash live only in the machine receipt so a later receipt-only
commit does not make this prose stale.
The machine receipt is `consumer-census-stability-v1.json`.

## Load-bearing consumer map

| Boundary | Current source/consumer and evidence | Current failure behavior | Conflict or gap | EMBER-01A integration action |
|---|---|---|---|---|
| Active classification | `STATE.md:67-72` classifies ember-cli, cbase, Qwen, and a Qwen benchmark result. | Documentation can say no capability credit, but runtime does not consume the table. | Correct classification is not executable identity. | Import classifications as migration inputs only; bind runtime to manifest bytes. |
| CLI model identity | `tools/ember-cli/src/model-config.ts:5-6` hardcodes `LOCAL_MODEL_ID = 'qwen-3.6'`. | Feature checks treat that string as the local model. | Borrowed Qwen is encoded as the local identity. | Replace with manifest-derived disposition/model ID; make Qwen an explicit reference seat. |
| CLI config source | `tools/ember-cli/src/entrypoints/process-entry.ts:98-108` defines endpoint, binary, model path, and modelName independently. | `loadModelsJson` returns null for missing, unreadable, or malformed config at lines 146-152. | Config loss silently falls through; no manifest/hash identity exists. | Require a manifest reference and fail closed when identity is absent or invalid. |
| Endpoint precedence | `process-entry.ts:192-247` resolves environment, GPU-free, config, or managed endpoint. | It discloses the selected endpoint source but validates no loaded identity. | Operator-visible location is mistaken for model identity. | Resolve endpoint only after identity binding; display disposition and checkpoint hash. |
| Managed model path | `process-entry.ts:726-743` derives binary/model paths and writes `EMBER_MODEL_URL`. | Existence checks occur before spawn at lines 756-769. | Existing bytes need not match any declared checkpoint or backend hash. | Verify manifest, checkpoint, executable, protocol, and lease before spawn/adopt. |
| Adopted server | `process-entry.ts:749-754` adopts any healthy server on the resolved port. | Health and context probes suffice. | A healthy Qwen server can be adopted without subject verification. | Require server-reported manifest ID plus independently verified bytes before adoption. |
| Request model label | `process-entry.ts:904` sends `EMBER_MODEL_NAME ?? "ember"`. | Missing model name becomes the unqualified label `ember`. | UI/request label can counterfeit identity. | Send the manifest model ID and forbid unqualified Ember without admitted owned identity. |
| Session endpoint fallback | `tools/ember-cli/src/entrypoints/session-init.ts:520-539` falls back to environment then `http://localhost:8081`. | A reachable endpoint becomes the production client at lines 593-596. | Default location can silently supply a different backend. | Remove identity-free fallback; require bound endpoint or explicit offline state. |
| Model lifecycle | `tools/ember-cli/src/services/model-lifecycle.ts:29-32` stores process state in module globals. | External endpoints are declared unmanaged at lines 64-72 and 98-106. | New CLI instances cannot recover durable ownership or identity. | Move lifecycle/process identity to `ember-lab`; manifest remains the model authority. |
| Brain supervisor registry | `tools/ember-cli/src/services/brain-server-supervisor.ts:71-79` mirrors port/path/PID/launcher/time/device. | Stale rows are reclaimed using PID/cmdline checks at lines 431-450. | No checkpoint, executable, protocol, or manifest hash is recorded. | Extend the compatibility view from the bound `ember-lab` identity; never author identity here. |
| Brain default checkpoint | `brain-server-supervisor.ts:222-228` derives a fixed model path and labels it informational. | Child code resolves the real checkpoint separately. | Parent and child can disagree while the row looks authoritative. | Pass a manifest ID and require the child to attest the same checkpoint bytes. |
| Serving registry | `scripts/serving_registry.py:2-19` declares itself the model-server source of truth with row schema `port, model_path, pid, launched_by, ts, device`. | Missing registry returns an empty set; writes are atomic. | It is a process locator, not a model identity registry. | Retain as derived compatibility output only; `ember-lab` is sole runtime writer. |
| Owned cbase server label | `scripts/serve_cbase_openai.py:73-106`, `:520`, and `:540` hardcode `cbase-2.2b`. | The same label is returned regardless of verified served/trained capacity. | Label exceeds/obscures the actual historical object described in `STATE.md:68`. | Remove fixed identity; serve only the verified manifest model ID/disposition. |
| Owned cbase architecture | `serve_cbase_openai.py:15-16` says architecture is inferred from tensor shapes; lines 115-156 perform inference. | Shape inference constructs a Llama config. | Architecture identity is reconstructed, not hash-bound. | Require exact architecture source/hash and reject inference as identity authority. |
| Owned cbase checkpoint | `serve_cbase_openai.py:282-353` checks model-file hash, loads tensors, remaps names, infers config, and loads a Llama model. | Model file mismatch and state-dict mismatch fail. | Strong byte checking still omits tokenizer/data/ancestry/mechanism/backend identity and drops training-only keys. | Validate the full manifest first; report any conversion/remap as a new derived artifact identity. |
| Owned cbase counts | `serve_cbase_openai.py:364-382` sums loaded parameters and writes a small load receipt. | Count reflects constructed model parameters. | Allocated, unique, active, trainable, served, and actually trained are conflated or absent. | Emit all six definitions from verified tensors/update/runtime evidence. |
| Checkpoint writer | `scripts/timeshare_pretrain.py:204-258` writes model, optimizer, RNG, step, timestamp, and per-file hashes. | Atomic directory rename and hash verification protect file integrity. | Manifest omits architecture, tokenizer, data ordering/curriculum/verifier, parameter semantics, ancestry, mechanisms, and stopping rule. | Wrap save/load with the identity manifest and reject incomplete legacy identity for new lineage. |
| Checkpoint loader | `timeshare_pretrain.py:260-297` verifies file hashes then loads model/optimizer/RNG. | Corrupt files fail; semantically wrong but correctly hashed bundles may load. | File integrity is not full experiment identity. | Validate exact identity and expected parent before any tensor/optimizer load. |
| Growth accounting | `scripts/cbase_grow_rung.py:219-282` records before/after sums and alias-adjusted unique counts. | It distinguishes tied storage in receipts. | It does not establish trained divergence, active route, served subject, or useful capacity. | Map legacy fields explicitly and leave unsupported counts unresolved; never upgrade credit by arithmetic. |
| Dry-run accounting | `scripts/cbase_grow_rung2_dryrun.py:315-370` loads model/optimizer/RNG and computes before/after and alias-adjusted counts. | Load/check calculations can pass on a dry run. | Dry-run allocation can be reported beside training language without served/trained identity. | Bind dry-run disposition and prohibit model-birth/capability credit. |
| Benchmark admission | `scripts/ember_research_benchmark_harness.py:15-21` freezes five IDs; lines 65-111 validate assets and emit admission metadata. | Admitted means harness/tasks are ready. | Receipt lacks exact subject checkpoint, comparator, score uncertainty, and owned-completion boundary. | Require evaluation section from the subject manifest; readiness never increments completion. |
| Watchdog/outage | `tools/ember-cli/scripts/liveness-watchdog.ps1:22-29` stands down on a planned outage and archives expiry; server tick begins near line 426. | Runtime can relaunch a server when the marker is absent/expired. | Liveness policy can resurrect a borrowed backend without identity/lease authority. | Make watchdog a client of `ember-lab`; start only the manifest-bound lease holder. |
| Operator display | `tools/ember-cli/src/screens/repl.ts:887-891` renders endpoint/circuit/outage state. | UI can show health and outage without exact loaded subject. | Healthy/offline is observable; owned/reference identity is not. | Render model ID, disposition, checkpoint prefix, backend hash, lease, and unresolved state. |
| Model card/paper | No tracked file named as a model card was found by the authoring census; publication-like candidates remain in the machine census. | Publication can proceed from ad hoc receipts/docs. | No consumer guarantees published results bind the exact subject manifest. | Generate model-card and paper result tables only from validated manifests and receipts. |

## Decision log

1. **One manifest, not one label.** Model, experiment, checkpoint, backend, and
   evaluation IDs remain separate fields in one joined object.
2. **Closed-world schema.** Unknown fields fail instead of becoming informal
   extension points that consumers reinterpret.
   The executable validator applies this schema directly.
3. **Explicit unresolved state.** Unknown is valid for census and migration but
   is never silently replaced. Execution/admission requires resolved mode.
4. **Hash exact bytes and tensors.** Whole-file and tensor-level identities
   catch different mismatch classes.
5. **Six parameter meanings.** Storage, update, route, and serving questions
   cannot share one `parameter_count`.
6. **Reference is a disposition.** It is not inferred from model family names
   and it mechanically blocks owned selection/completion.
7. **Endpoint and PID are runtime coordinates.** They never author model
   identity.
8. **Operational receipts are not capability evidence.** Capability credit is
   restricted to the owned checkpoint and checkpoint-bound causal evidence.
9. **Legacy consumers are adapters, not authorities.** EMBER-01C records their
   current behavior; EMBER-01A owns production binding.
10. **Admission is positive proof.** Candidate, historical, and reference
    dispositions can never select Ember or increment owned completion.
11. **Multimodal and birth evidence are structured.** Each required modality
    and the sufficient-pretraining stopping criterion carry receipt hashes.
12. **Admission resolves bytes, not declarations.** Checkpoint, tensors,
    architecture, tokenizer, data, optimizer/numerics, backend, ancestry,
    mechanisms, receipts, and verifier authority are independently supplied and
    rehashed.
13. **Git checkout state is not evidence.** Public/private census reads exact
    commit objects, so staged deletion or an empty worktree cannot erase a
    consumer.

## EMBER-01A integration checklist

- [ ] Adopt the schema ID and validator semantics without weakening required fields.
- [ ] Add exact active-goal/workstream headers after the EMBER-01 transition lands.
- [ ] Bind train launch and checkpoint save/load before tensors or optimizer state are used.
- [ ] Bind serving launch/adoption to checkpoint, executable, protocol, process, and lease.
- [ ] Replace CLI hardcoded Qwen/local identity and unqualified `ember` fallback.
- [ ] Derive the serving-registry compatibility view from `ember-lab`; remove dual writers.
- [ ] Make Qwen and every external model explicitly `REFERENCE_ONLY`.
- [ ] Bind benchmark execution and completion to exact subject/comparator manifests.
- [ ] Generate model-card/paper/demo identity from validated evidence only.
- [ ] Add mismatch fixtures at each production adapter, not only at the core validator.
- [ ] Run `--require-resolved` for every launch, save/load promotion, serve, benchmark, and publication action.
- [ ] Preserve legacy artifacts as unresolved/historical rather than inventing missing identity.

## Reproduction

```text
python -B -m pytest -q -p no:cacheprovider tests/ember_01_identity
python -B scripts/ember_01_identity/census_consumers.py --root . --root-locator-spec manifests/ember-01-identity/consumer-census-roots-v1.json --replay-profile portable --semantics-manifest manifests/ember-01-identity/consumer-semantics-v1.json --consumer-scope manifests/ember-01-identity/consumer-scope-v1.json --adjudication-manifest manifests/ember-01-identity/consumer-adjudication-v1.json --output <portable-output.json>
python -B scripts/ember_01_identity/validate_identity.py tests/ember_01_identity/fixtures/valid-identity-v1.json
```

The portable replay requires no host-root environment variables. Full
environmental discovery uses the same checked locator spec with
`--replay-profile full` and explicitly configured `EMBER_CENSUS_*` roots; it is
supplemental evidence, not completion authority. These commands load no model,
use no GPU, and execute no benchmark.
