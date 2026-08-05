# SOTA-stack floor — maintained frontier baseline for Ember

**Origin:** operator direction, 2026-06-27. **Track:** training and inference
research substrate. **Claim boundary:** citations and checked-in Ember evidence
only; this specification grants no capability credit.

## Purpose

The floor is a maintained, per-layer survey of available and synthesizable
training and inference techniques. Its gap table is the external baseline that
any field-level-contribution claim must reference. Without that baseline,
“frontier” and “contribution” are unfalsifiable.

It has two load-bearing jobs:

1. identify each layer's irreducible job and the metric that defines “better”;
2. compare Ember's exact current evidence to a cited external frontier without
   allowing Ember to edit the frontier to flatter itself.

## Required sharpenings

1. **Maintenance:** a one-time survey expires. Each row records its evidence and
   must be revisited when a new frontier artifact changes the comparison.
2. **Synthesis:** the survey covers both individual techniques and combinations
   that are compatible across layers. Cross-layer conflicts remain explicit.
3. **Receipts-only literature:** every maturity or frontier claim has a primary
   citation. Every Ember status has an exact config, implementation, or receipt.
4. **Training translation:** every inference technique is mapped through
   [`docs/design/inference-to-training-translation-v1.md`](inference-to-training-translation-v1.md).
   Missing training twins are recorded as research gaps rather than silently
   treated as irrelevant.

## Survey nodes

Pretraining objective and curriculum; architecture; tokenizer and vocabulary;
quantization; optimizer and schedule; data pipeline; parameter growth;
multimodal fusion; long context; inference and decoding; serving runtime.

For every node:

1. state its irreducible job and metric;
2. cite the frontier techniques and their maturity;
3. identify compatible combinations and conflicts;
4. compare Ember's current evidence as `EXCEEDS`, `MEETS`, `LAGS`, or
   `UNMEASURED`;
5. link the node's inference lever to its training-side twin in
   `docs/design/inference-to-training-translation-v1.md`;
6. name a bounded experiment when the row is `LAGS` or `UNMEASURED`.

After the per-node pass, perform a cross-node synthesis pass. A synthesized
stack is only a contribution candidate; it earns no claim without a frozen
external baseline, execution receipt, comparator, and deletion test.

## Deliverables

- `docs/design/sota-stack-floor.md`: maintained per-layer gap table and evidence links.
- `docs/design/inference-to-training-translation-v1.md`: inference-to-training mapping.
- `docs/ledgers/technique-registry.jsonl`: adopted technique registry.
- `scripts/check_inference_training_translation.py`: deterministic structural
  and citation-resolution gate.
- a re-survey cadence and frontier-delta mechanism; until that mechanism lands,
  maintenance remains an explicit open obligation.

## Governance

This floor binds C8/C-SCALE: a field-level contribution is RED by construction
when its relevant frontier row is absent, stale, uncited, or not connected to a
training translation. A green structural check proves document integrity only;
it does not prove that Ember meets or exceeds the frontier.
