# 03 — Model Architecture

## Canonical family and configuration

The canonical EMBER-02 family is CIA-3B, selected in [GOAL.md](../authority/GOAL.md#4-architecture-and-the-headline-research-hypothesis). The checked-in configuration [configs/ember-cia-3b.json](../../../../configs/ember-cia-3b.json) declares revision `CIA3-R1-N61` and 3,082,539,008 unique parameters. Its SHA256 is `c4f7fe9e4f5132d89eccfe02094f017d5a9293098c3b313519328f11a786eb5e`.

| Configuration field | Declared value |
| --- | --- |
| Decoder width / depth | 1,024 / 24 layers |
| Vocabulary / attention heads / KV heads | 32,768 / 16 / 4 |
| Shared FFN / expert FFN dimensions | 2,048 / 3,072 |
| Sparse layer cadence | Every second layer |
| Global / resident / selected experts | 25 / 2 / 1 |
| Global epoch / local segment | 1,024 / 256 tokens |
| Parameter dtype | BF16 |

The actual selected pointer and full manifest bytes were independently verified on 2026-10-09T19:37:09Z. Selected pointer SHA256 c3105614dbb1ea2722a9e0bb36bd856735349a512129d232e1970cedde086523 binds manifest SHA256 d9c6a349e73d5ea773adb1c94347abe1f248bfd5269561a017ffe9bb61d813a0. That manifest declares CIA3-R1-N61, inventories 3,082,539,008 unique/allocated/served/trainable parameters and 701,964,288 episode update-support parameters, and records independently_qualified=false. These identities establish the selected architecture and its recorded inventory; they do not establish sufficient training or native capability qualification.

The implementation entry point is `src/ember/model/ember_v0_decoder.py::CIADecoder`; the CIA hour path is `src/ember/infrastructure/tools/ember-restart-3b/cia_hour.py`. The directory's historical name does not identify the decoder being executed. The generic `infer.py` consumer and v2 `UnifiedDecoder` must retain their own explicit identity and eligibility.

Episode trainable parameter inventory counts enabled `requires_grad` tensors. It does not measure per-token FLOPs, observed updates or learned competence. Global, resident, selected, served and trainable quantities require their own definitions.

Raw image patches and audio frames, causal functional routing, reasoning and structured tool use remain required architecture and acceptance surfaces. A configuration or source implementation supplies no qualification result. The operator's current questions about routing granularity, shared FFN capacity, width/depth, multimodal interfaces and gradient/load balance remain open empirical questions.

## Historical v2 comparison and recovery reference

The following preserved contract snapshot describes `ember-sparse-3b-v2`. Its dimensions and evidence apply to that reference. Further execution requires an explicit bounded CIA qualification, comparison or reusable-infrastructure purpose under GOAL.md. Weights, trained-token credit and certificates require their original lineage.

### Historical v2 architecture contract

The retained v2 architecture contract is `configs/ember-restart-3b.json`
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

### Historical board visibility

Condition `C-BASE` was RED on the last board render
(`ember-totality-20260801T052815Z.json`): "artifact root not provided / bytes
not visible from this tree (6 owned-pretrain candidate(s) name a checkpoint
but its manifest.json/model.pt were not found under the resolved artifact
root ... this is a visibility failure, not an absence failure." In plain
terms: **no owned ember-restart-3b checkpoint bytes are confirmed present and
hashed under this tree as of the last board render.** This doc describes the
*designed* architecture from the frozen contract; it does not claim a trained
model exists. See 14_MODEL_CARD.md for the honest current-state summary.
