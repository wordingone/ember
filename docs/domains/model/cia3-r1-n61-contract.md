# CIA3-R1-N61: equation-supported normalization inventory

Relates to #2163 and #1116. This is a corrected research-candidate contract, not production adoption, realized weights, trained capacity, or completed S0.

## CIA-NORM-001: three reference vectors lack specified consumers

Issue #2163's recomputation counts 64 width-1024 RMSNorm vectors. Its shared decoder equations assign two norms at each of 24 layers, plus one at each of 12 sparse depths. Together with the named final normalization, these account for 61 vectors. The remaining three vectors have no specified consumer or semantics in the decoder or typed adapter definitions.

CIA3-R1-N61 counts the 61 evidenced vectors. It does not add idle tensors to reproduce a reference total. The original reference remains unchanged as provenance; this candidate has a distinct revision. If source evidence identifies the missing consumers, name their operation and semantics and issue another explicit revision. Adding typed-adapter normalization changes embedding semantics and is not an arithmetic-only repair.

The specification item closes when the reference assigns real consumers or is explicitly corrected to 61. Until then, the discrepancy remains recorded while implementation proceeds on the evidenced operations. Neither resolution permits nominal padding or silently changes v2's accepted configuration.

## Derived inventory

| Component | Named prospective consumer | Elements |
|---|---|---:|
| Attention projections and Q/K norms | 24 GQA attention blocks | 62,917,632 |
| Shared SwiGLU | 24 shared nonlinear blocks | 150,994,944 |
| Tied vocabulary matrix | Input embedding and output projection, counted once | 33,554,432 |
| Router query projections and keys | Global/local queries; keys at 12 sparse depths for 25 experts | 2,404,352 |
| 61 width norms, modality embedding, raw adapters | Decoder/final normalization; modality offsets; image/audio projection | 1,512,448 |
| Shared subtotal | Above consumers | 251,383,808 |
| 25 expert bundles | 12 sparse-depth SwiGLU blocks per expert; 113,246,208 elements per bundle | 2,831,155,200 |
| Total | Full global population | 3,082,539,008 |

Core plus one expert is 364,630,016; core plus two resident experts is 477,876,224. These are accounting envelopes, not measured operations or resident allocation. The 3,072-element difference from R1 is exactly three width-1024 vectors. Attention's Q/K head norms are already counted separately and must not be removed again.

`src/ember/model/cia_inventory.py` enumerates each prospective tensor by name, shape, component role and global expert identity. Its meta-only materializer constructs no weight values and cannot prove initialization diversity, reachability, gradient flow, optimizer updates, serving engagement, or learning. The executable candidate must consume this inventory and supply those proofs before qualification. Names alone are not a traced runtime consumer certificate.

The explicit update-support map excludes router parameters from core+expert-set and excludes inactive experts. It must later be checked against actual changed tensors, optimizer membership, stale gradients and preserved optimizer clocks. Topology mutation remains a separately governed transaction.

## Current checks and remaining scope

The CPU-only tests cover formula/inventory agreement with the declared correction, every global expert's shape inventory, metadata materialization, update-support separation, malformed expert identities, and preceding-history interval boundaries. These tests do not prove causal routing or logits: decoder integration must demonstrate suffix and co-batch noninterference, packed-document isolation, and incremental/prefill equivalence.

The initial inventory checks alone leave model ownership, decoder integration of route consumers, valid evidence predicates, immutable object and promotion integration, and optimizer mutation unproved. Later sections distinguish the integrated CPU mechanics from the still-open identity and qualification obligations. Native crash recovery, full-scale learning, paging comparisons, coupled qualification, production throughput and the complete EMBER-02 certificate remain later unsatisfied obligations under the parent issues.

## CPU selection oracle

`src/ember/model/cia_routing.py` consumes preceding-history boundaries for one request/document at a time. Global selection uses the detached preceding 1024-position embedding epoch; local selection uses only the shared-path vector at `segment_start - 1`, not a segment mean. Both first intervals use a fixed zero beginning state. Greedy ties resolve by global expert ID. Temperature is explicitly 1 in selector version `CIA3-R1-N61-cpu-greedy-v1`.

The oracle records history digests/cutoffs and checks generation, request, document, epoch, key content, prior content, selected IDs and selector version before local consumption. These checks detect stale or modified selection state; they do not authenticate a caller, certify loaded model objects, or replace residency/request leases. Tensor fields remain process-local objects and are not an immutable serving transaction.

Fixed full-width tensor tests cover suffix noninterference, visible-history sensitivity, packed-document beginning states, separate requests, prefix replay, last-vector local semantics, changed keys/priors/IDs/version refusal and stopped global-history gradients. No optimizer update, small learned network, full decoder, or capability subject is created. The oracle alone does not establish actual decoder logits, padded-input handling, route recomputation/backward binding, straight-through task gradients, or paging engagement. The numerical CPU extension below integrates unpadded decoder routing and task gates; padding, durable route replay and paging remain outside its scope. Caller-supplied shared-path provenance and re-embedding under the generation must become enforced decoder/runtime contracts.

## Full-shape parameter-owning decoder graph

`src/ember/model/cia_decoder.py` now instantiates all 3,082,539,008 declared elements as BF16 meta `nn.Parameter` objects. It checks exact registered names/shapes, rejects extra parameters and repeated Parameter objects, and uses the tied vocabulary matrix for both embedding and output. Distinct Parameter objects on meta are not proof of distinct physical storage. The optional full-population CPU extension below allocates physical weights and checks storage ownership.

The graph implements raw patch/frame projections, modality offsets, 24 GQA/shared-SwiGLU layers, 12 expert depths, head Q/K normalization, 32/16/16 three-axis RoPE and final normalization. Explicit fixed-route metadata traces exercise these shapes, all 25 expert projection paths, and selected autograd connections. They are unpadded single-document fixtures. Router tensors are registered but not consumed by the fixed-route trace. The separate numerical CPU forward integrates the selection oracle and supplies real logits for conformance tests.

`apply_update_support` applies the role map to the actual Parameter objects, clears stale gradients and returns the selected objects. It does not rebuild an optimizer, preserve its moments, serialize clocks, prove numerical updates or authorize state deletion. Actual optimizer integration must keep all those obligations.

The default constructor remains meta-only. Explicit `materialize_cpu(seed=...)` now initializes the complete 3,082,539,008-element BF16 population for CPU conformance. There is no lower-scale constructor. Numerical `forward` uses decoder-owned routing weights and preceding-history selection independently for each explicitly packed, unpadded document. It is a full-population CPU reference, not two-resident-slot paging, cached incremental serving, governed training, or production adoption. Meta backward alone still proves only graph connectivity.

## Routing graph and state integration boundary

`trace_routing_gate` separately consumes the decoder-owned global/local query and expert-key parameters using the same score functions as the CPU oracle. Its winners remain explicit fixture inputs. It validates the complete parameter inventory before constructing the meta graph. The unit-forward selected-softmax gate has fixed-tensor tests for finite gradients, including extreme finite float64 logits. These checks do not establish numerical decoder routing, causal logits, learned selection, or route replay during backward.

The following existing consumers constrain the next S0/S1 carrier. Existing integration paths and symbols refer to the parent commit; the CIA class is introduced by this change. These are source-inspection findings, not executed CIA recovery evidence.

| Obligation | Existing integration point | Required CIA extension and decisive negative |
|---|---|---|
| C04 evidence validity | `src/ember/infrastructure/tools/ember-restart-3b/checkpoint_artifacts.py::admit_quarantined_checkpoint` takes a verifier callback and checks its materialized counter receipt | Claim-class metric validation must precede model-generation selection. Bind actual evidence identity and frozen thresholds; malformed, nonfinite, wrong-type, missing and out-of-domain evidence must fail through the eventual activation entry point. Existing byte/counter admission is not capability qualification. |
| C05 immutable object identity | The same module's `_checkpoint_candidate_receipt`, `_validated_records` and `_atomic_publish_no_replace`; `durable_io.py::atomic_create_durable` | Add versioned expert-object and index bindings through existing custody. Swapped bytes, mismatched expected digest, reused object identity and missing objects must prevent load. Do not introduce a second checkpoint publication ledger. |
| C06 guarded generation selection | Existing checkpoint admission rejects live staging leases and changed candidate bytes before publication | Publication makes a bundle selectable; it is not an atomic current-generation compare-and-swap. Integrate expected-parent selection, request-held identities and concurrent promotion rejection at the actual activation owner. Resource lease epochs in `runtime/ember-lab/src/lib.rs` do not by themselves establish model-generation leases. |
| C07 update support | `CIADecoder.apply_update_support`; existing checkpoint optimizer contracts and owner-sharded optimizer validation | Preserve inactive optimizer clocks and moments while applying selected supports. Numerical changed-tensor checks, inactive-state equality and reload are still needed; requires-grad flags alone are insufficient. |
| S1 native durable recovery | `checkpoint_artifacts.py::write_checkpoint_artifacts`, `load_checkpoint_artifacts`, and `durable_io.py` | Reuse complete state, cursor, RNG, and optimizer contracts. Windows uses write-through file moves in the small-file helper; its directory-flush helper returns immediately on Windows. Real termination at write/publication boundaries and fresh-process continuation must verify the complete integration. |
| Owned serving admission | `src/ember/infrastructure/tools/ember-cli/src/services/checkpoint-load.ts` | Current accepted schemas are sparse checkpoint v3/v4/v5 and expert names are vision/audio/reasoning/tool. A CIA schema needs explicit topology and artifact validation at each consumer. Merely permitting a new architecture string or renaming old weights is invalid. |

For S4, consume #2115's persistent local-to-trajectory comparison with #1945/#2106 owners. Its required interrupted and uninterrupted arms compare subsequent applied updates from published bytes, including optimizer, RNG, cursor, routing/residency and accumulation state. The issue is an open experimental specification, not an existing CIA result. No additional trainer, evaluator, data catalog, or trajectory authority is introduced here.

## Numerical CPU conformance boundary

Initialization uses a local CPU generator: width norms start at one; other tensors use a normal distribution with standard deviation 0.02, divided by sqrt(48) for attention-output and SwiGLU-down residual projections. The operation preserves the selected update-support flags. Registered physical storage must be distinct across different named tensors; the vocabulary matrix remains tied through its two consumers.

Numerical execution recomputes global selections from preceding 1024-position embedding epochs and local selections from the shared-path vector immediately before each 256-position segment. The selected unit-forward gate retains its task-gradient graph. Each packed document receives an independent attention and route computation. Inputs are explicitly unpadded: no validity-mask or incremental KV-cache contract is implied. Callers cannot force numerical expert IDs through the metadata fixture API.

`tests/test_issue2163_cia_numerical.py` requires the explicit `EMBER_CIA_CPU_CONFORMANCE=1` resource opt-in. The complete population is allocated once per test class. Routine CI may collect these tests while skipping the physical allocation; a skipped test is not numerical evidence. The bounded local run must supply its source identity, complete output, enforced memory/time envelope and cleanup result independently of routine CI.

The update-support test uses native PyTorch AdamW with BF16 parameters, gradients and moments, scalar optimizer clocks and no FP32 master weights. It is a changed-tensor and retained-state mechanics test only. It does not choose the production optimizer or establish full-state durable recovery, admitted learning, capability, useful-token throughput, or any EMBER-02 birth clause. Production master-weight/optimizer numerics and durable paging remain explicit qualification obligations.