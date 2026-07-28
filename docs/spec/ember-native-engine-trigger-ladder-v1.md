<!--
goal_id: EMBER-02
workstream_id: EMBER-02A
next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
-->

# Ember native-engine trigger ladder v1

Status: `preserved_trigger_gated`
Issues: [#158](https://github.com/wordingone/ember/issues/158), coupled to
[#155](https://github.com/wordingone/ember/issues/155)

## Purpose and boundary

Ember needs one owned training-and-inference substrate when measured framework
limits justify it. It does not need an unbounded rewrite merely because a
native engine is attractive. This contract preserves the engine direction,
names the evidence that fires each rung, and prevents trigger-less deferral.

“Native engine” is a capability of Ember Lab, not a new product identity. The
implementation may use Rust, C, C++, CUDA, and assembly behind stable owned
interfaces. This document does not claim that any rung is complete, that an
owned checkpoint exists, or that Ember has acquired new capability.

## Trigger ladder

| Trigger | Current review | Evidence that fires it | Required rung |
|---|---|---|---|
| T1 — parity tax | NOT_FIRED | A repeated PyTorch↔GGUF/runtime parity defect, or a measured parity-maintenance budget breach, with reproducible receipts | R2 |
| T2 — framework wall on directed work | PARTIALLY_FIRED | A directed #155 kernel track is blocked or materially taxed by the framework boundary. The consumer-GPU FP8 track is the present partial firing; fused Muon Newton–Schulz remains a second coupled track. | R0 |
| T3 — resident-training wall | ON_BLOCKER_PATH | In-serving or resident updates cannot be expressed with bounded ownership, identity, and resource receipts through the current substrate | R1 |
| T4 — shipped training capability | NOT_FIRED | Ember ships supported local training as an operator-facing product capability whose lifecycle requires one owned substrate | R3 |

T2 and T3 are reviewed by every totality-board audit. Their status is emitted
in the board receipt from the authoritative floor-contract row; absence or
malformation is a terminal board-construction error, not an omitted note.

## Rungs

### R0 — shared kernel seam

Create a narrow owned ABI and dispatch surface that both the current training
path and a future native runtime can call. The first two directed kernels are:

1. width-conditional consumer-GPU FP8 matrix multiplication for #155, with
   explicit unsupported-width refusal and no silent BF16 fallback;
2. fused Muon Newton–Schulz update for #155, with exact optimizer-state,
   numerical-equivalence, memory, and throughput receipts.

R0 promotes only when a kernel has a frozen reference implementation, exact
input/output and tolerance contracts, CPU/reference comparison, device and
dtype refusal tests, benchmark receipts, and at least one real consumer in
training or inference. A source file or microbenchmark alone is not promotion.

### R1 — shared tensor and update runtime

Move tensor identity, optimizer-state ownership, scheduling, checkpoint
publication, and bounded resident updates behind an owned runtime interface.
The positive proof is a checkpoint-bound update executed through the same
substrate used by serving, with replayable custody and resource receipts.

### R2 — native graph/runtime

Own graph lowering, memory planning, kernel selection, and train/infer parity
for the measured surface that fired T1. Promotion requires a two-sided parity
suite and a measured maintenance or performance win. It does not authorize a
whole-system rewrite outside the fired surface.

### R3 — Ember Lab product substrate

Expose the owned substrate through stable Ember Lab CLI/API/GUI contracts for
local model creation, training, evaluation, serving, and study. R3 requires
operator-independent installation and recovery, not merely an internal binary.

## Coupling to #155

The #155 FP8 and fused-Muon tracks are R0 pilots, not separate substrate
claims. Their receipts must bind:

- exact source and kernel identities;
- current model/config and tensor shapes;
- device, dtype, fallback/refusal behavior, and numerical tolerances;
- peak memory, elapsed time, and comparison baseline;
- the consuming training or inference call site;
- a result of `PROMOTE`, `PRESERVE_TRIGGER_GATED`, or `REJECT`.

A pilot cannot promote both its model-mechanism claim and the native substrate
from one self-attested receipt. The kernel result and substrate promotion are
separate verdicts.

## Board-audit contract

Every totality-board receipt includes `native_engine_trigger_review` with:

- this floor-row key, disposition, source path, and exact source SHA-256;
- issue #158 and coupled issue #155;
- T2 status `PARTIALLY_FIRED` requiring R0;
- T3 status `ON_BLOCKER_PATH` requiring R1;
- claim boundary
  `TRIGGER_REVIEW_ONLY_NO_NATIVE_ENGINE_CAPABILITY_CLAIM`.

Changing either status requires changing this hashed source and the
floor-contract row under review. Missing T2/T3, an unrecognized disposition,
or broken #155 coupling fails closed.
