# 03 — Model Architecture (authoritative)

## Current active architecture: ember-restart-3b

The active EMBER-02 architecture contract is `configs/ember-restart-3b.json`
(`contract_version: 3`, `architecture_revision: "ember-sparse-3b-v2"`),
superseding contract v1 ("dense positionless production shell retired before
GPU materialization" — the config's own `supersedes.reason`). Namespaces are
exclusive per-purpose: model root `models/ember-restart-3b/`, training root
`src/ember/infrastructure/tools/ember-restart-3b/`, checkpoint root `receipts/ember-restart-3b/`.
Lineage: `initialization: "random"`, `borrowed_weights: false`,
`teacher_outputs: false`, `model_derived_data: false`,
`external_judges: false` — a from-scratch, owned genesis by contract.

Architecture (`configs/ember-restart-3b.json` → `model` block):

- `"architecture": "sparse_unified_decoder_verified_expert_accretion"`
- `hidden_size: 2048`, `layers: 14`, `attention_heads: 16`, `vocab_size: 32000`, `tied_embeddings: true`
- Normalization: RMSNorm pre-attention, pre-FFN, final, and per-head QK-RMSNorm before RoPE
- Position encoding: 1D RoPE for text/audio, 2D RoPE coordinates for image, explicit multimodal span metadata, both causal and bidirectional attention modes
- Expert routing: four named experts (`vision`, `audio`, `reasoning`, `tool`), each a `SwiGLU_4H` block sized `12*hidden_size^2`, plus an always-active shared text FFN of the same shape; exactly one expert active per episode/batch (`active_experts_per_episode_or_batch: 1`), inactive experts frozen, routing is an explicit local episode declaration (not a learned external router)
- Image projection: `48x48x3` input → `hidden_size`-wide projection (`(48*48*3)*hidden_size` params)
- Audio projection: 640-sample frames → `hidden_size`-wide projection (`640*hidden_size` params)
- The config embeds its own `parameter_formula` block so total trainable-parameter count is derivable from `hidden_size`/`layers` rather than hand-claimed.

## Retired / historical architecture (do not execute)

`src/ember/governance/scripts/timeshare_pretrain.py` (the earlier "c03" dense decoder — 0.37B,
hidden 1024, 20 layers, 16 heads, vocab 32k) and its config family
(`domains/model/configs/v0-pretrain-config.json`, `domains/model/configs/v1-pretrain-config.json`) are
marked `EMBER_ARTIFACT_CLASS=historical_only` / `goal_id: EMBER-00` and the
script itself raises `SystemExit("historical_only: the sub-3B cbase trainer
and every importer are execution-denied")` immediately after its docstring.
`src/ember/governance/scripts/ember_bitnet_core.py` (BitNet b1.58 ternary twin, C15) is defined
architecture-parity with c03, so it inherits the same historical status for
production purposes — it remains live only as a comparison harness (C15).

## Current gaps — honestly stated

Condition `C-BASE` was RED on the last board render
(`ember-totality-20260801T052815Z.json`): "artifact root not provided / bytes
not visible from this tree (6 owned-pretrain candidate(s) name a checkpoint
but its manifest.json/model.pt were not found under the resolved artifact
root ... this is a visibility failure, not an absence failure." In plain
terms: **no owned ember-restart-3b checkpoint bytes are confirmed present and
hashed under this tree as of the last board render.** This doc describes the
*designed* architecture from the frozen contract; it does not claim a trained
model exists. See 14_MODEL_CARD.md for the honest current-state summary.
