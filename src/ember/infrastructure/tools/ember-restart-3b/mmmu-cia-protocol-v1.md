<!-- goal_id: EMBER-02 -->
<!-- workstream_id: EMBER-02B -->
<!-- next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember -->
<!-- repository copy 2026-09-20: the seat copy (sha256 07892c4c2e3103b03e2c2c4e123f2b3e093004c5a1a564d23214266232e1fd6c) carried no goal-binding header; these four comment lines are the only difference, the protocol text below is byte-identical -->
# mmmu-cia-protocol-v1 — how a CIA checkpoint answers an MMMU multiple-choice item

Frozen 2026-09-20. The sha256 of this file is the `protocol_sha256` every envelope and receipt
produced by `mmmu_cia_evaluation.py` carries. Changing a byte here changes the protocol identity.

## Inputs

The 847 eligible multiple-choice items of the MMMU validation split, bound by digest to the custody
`scripts/ember_restart/mmmu_front_unit.py` pins: answer dictionary `76080f55…`, eligible id set
`7a8800c9…`, validation freeze v2 `2f1f5ab0…`, image-inputs v1 `719619b7…`, upstream license
`c71d239d…`, scorer adapter `07cc4114…`. Every item's `input_sha256` (id, question, literal options
string, image byte digests; `json.dumps(sort_keys, compact separators, ensure_ascii=True)` — the
freeze's own definition, which differs from the front unit's `ensure_ascii=False` on the 36 rows with
non-ASCII text) must equal the frozen image-inputs row, or the item refuses as `PREPROCESSING_DRIFT`.

## One document per item

1. For each image in column order `image_1..image_7` (absent columns skipped):
   `<boi>` (token 1) — one position, modality text, axes `(t, 0, 0)`;
   the image resized with bilinear filtering to a patch grid `gx × gy`, aspect preserved, with
   `max(gx, gy) ≤ 8`, each axis ≥ 1, patch size 16 px; raw RGB bytes scaled to `[0, 1]` as
   bf16, one 768-vector per patch, row-major, through `embed_image` (modality 1), axes
   `(t, x, y)` where `x, y` are the patch's grid coordinates;
   `<eoi>` (token 2) — one position, axes `(t, 0, 0)`.
2. Then the text, tokenized by the frozen tokenizer with no special tokens, modality text, axes
   `(t, 0, 0)`:

        Question: <question, stripped>
        Options:
        A. <option 0>
        B. <option 1>
        ...
        Answer:

   `<image N>` markers inside the question are left as text; images precede all text.
3. `t` is the running position index over the whole document. One document start at 0. The
   document refuses above 4,096 positions.

## Prediction

The reference forward is run once on the document. At the final position, the argmax is taken
over the token ids of the item's option labels only (`A`→40, `B`→41, … in tokenizer-2c557), and
that label is the prediction. The unconstrained argmax token id at the same position is recorded
beside it (`free_argmax_token_id`) so the reader can see what free greedy decoding would have
emitted; it does not enter the score.

Item 0 is scored twice and the two results must be identical (`NONDETERMINISTIC_SCORE` otherwise).

## Scoring

Predictions are emitted as an `ember-owned-predictions-v1` envelope (claim status
NON_ADMISSIBLE_RAW_PREDICTIONS), materialized through the repository prediction contract's
`mmmu` adapter to `[{id, prediction}]`, and scored by `scripts/ember_restart_eval_mmmu.py` against
the cached upstream `mmmu/main_eval_only.py`. The reported score is the upstream `Overall.acc`
over exactly 847 items.

## What this protocol does not claim

The CIA governed runner embeds text only; the image projection exercised here is genesis-initialized
in every runner-produced checkpoint, and the receipt states that under
`image_projection_trained_by_runner`. A score under this protocol is an executable protected
evaluation number and nothing else: no image-capability tier, no learning credit, no
qualification credit. The 4-way chance rate on a label-constrained choice is the reader's baseline,
not the producer's floor; the gate's floor is pre-registered by its caller with its basis.
