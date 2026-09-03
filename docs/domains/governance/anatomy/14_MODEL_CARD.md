# 14 — Model Card

## Status: no owned trained checkpoint currently confirmed

As of the last totality board render (`ember-totality-20260801T052815Z.json`),
condition `C-BASE` was RED: "artifact root not provided / bytes not visible
from this tree (6 owned-pretrain candidate(s) name a checkpoint but its
manifest.json/model.pt were not found under the resolved artifact root
... this is a visibility failure, not an absence failure." This card
therefore describes the **target contract**, not a completed model. Anyone
citing this card as evidence of a working owned checkpoint is misreading it.

## Target architecture

Per `configs/ember-restart-3b.json` (`architecture_revision:
"ember-sparse-3b-v2"`, contract v3) — full detail in 03_MODEL_ARCHITECTURE.md:
`sparse_unified_decoder_verified_expert_accretion`, hidden size 2048, 14
layers, 16 attention heads, vocab 32000, tied embeddings, four named experts
(vision/audio/reasoning/tool, one active per episode), shared always-active
text FFN, 1D RoPE for text/audio and 2D RoPE coordinates for image.

## Target scale (goal conservation contract)

`src/ember/governance/scripts/verify_authority_conservation.py`'s `EXPECTED_CONSERVATION` block
pins: `minimum_new_network_parameters = 3,000,000,000` (3B),
`destination_total_parameters > 27,000,000,000` (27B, via measured growth —
see 05_GROWTH_AND_SCALING.md), `required_native_capabilities = text, image,
audio, reasoning, structured_tool_use`, `borrowed_lineage =
frozen_reference_only`, `mechanism_erasure = forbidden`.

## Lineage and provenance discipline

`configs/ember-restart-3b.json`'s `lineage` block declares:
`initialization: "random"`, `borrowed_weights: false`,
`teacher_outputs: false`, `model_derived_data: false`,
`external_judges: false` — an owned, from-scratch genesis by contract, not by
narrative claim. Condition `C(-1)` (paid-API-spend discipline) requires
every decisive-claim receipt to declare `api_spend_usd`/
`paid_api_surface_used`; it was RED on the last render because 3 additional
receipts had been merged that lacked the field despite an earlier fix PR
claiming to add it — a disclosed field-contract regression, not yet cured.

## Training data

`domains/model/configs/v1-pretrain-config.json` (marked `historical_only`, `EMBER-00`,
retained as the most recent real corpus-assembly receipt this repo has on
disk) documents a corpus-cleaning pass that DROPPED the `fineweb_edu` source
as "TAINTED — document inclusion via classifier trained on
Llama-3-70B-Instruct annotations" (7.4GB / 1.55M docs removed), retaining
only sources classed CLEAN. Whether an equivalent clean-only corpus
assembly has been completed for the current `ember-restart-3b` contract is
not established by this doc — see `src/ember/infrastructure/tools/ember-restart-3b/build_owned_*.py`
(04_TRAINING_PIPELINE.md) for the current owned-data construction scripts.

## Current gaps — honestly stated

No checkpoint bytes, no evaluation scores, and no capability claims are made
by this card. `C-BASE`, `C-SCALE`, `C(-1)` (regression), and the benchmark
conditions in 06_EVALUATION_AND_BENCHMARKS.md track the real remaining
distance between this contract and a card that could honestly claim a
trained, evaluated model.
