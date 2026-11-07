# 14 — Model Card

## Current research candidate

The canonical family is CIA-3B. [03_MODEL_ARCHITECTURE.md](03_MODEL_ARCHITECTURE.md) identifies the checked-in `CIA3-R1-N61` configuration and the separate selected-checkpoint evidence. The configuration declares 3,082,539,008 unique parameters, width 1,024, 24 layers, 25 global experts, two resident experts and one selected expert. A trained checkpoint's parameter inventory must be verified from its actual manifest and measurement.

The owner-reported current selection is checkpoint-manifest digest `d9c6a349e73d5ea773adb1c94347abe1f248bfd5269561a017ffe9bb61d813a0`, observed through pointer `c3105614dbb1ea2722a9e0bb36bd856735349a512129d232e1970cedde086523` on October 9 at18:34Z. The pointer was published October 7 and remained selected after the owner reported H36 was not accepted. This public page holds the pointer report; direct manifest fields, model bytes and acceptance receipts remain separately required.

| Evidence class | Current boundary |
| --- | --- |
| Canonical family | CIA-3B in GOAL.md |
| Configuration | CIA3-R1-N61; SHA256 `c4f7fe9e4f5132d89eccfe02094f017d5a9293098c3b313519328f11a786eb5e` |
| Selected checkpoint | Actual full metadata verified19:37:09Z; manifest SHA256 d9c6a349e73d5ea773adb1c94347abe1f248bfd5269561a017ffe9bb61d813a0; independently_qualified=false |
| Episode trainable inventory | Writer counts `requires_grad` tensors; per-token compute and learning results need separate evidence |
| Data supply | Source resolution, availability, admission and actual positive-loss consumption are separate |
| Sufficient pretraining / external competence | Required frozen evaluations and checkpoint-bound results remain unproved by this card |
| Native operation | Adopted operation contract describes required behavior; actual launch and operation receipts remain required |

The [native-operation contract](../operator/native-operation-contract-v1.json) defines CURRENT/FRESH selection, corpus resolution and owned operation outcomes. It grants no resource allocation, data admission or inference competence by itself.

## Historical v2 card and board snapshot

The retained material below concerns `ember-sparse-3b-v2` and the August 1 board. Preserve its evidence for comparison and recovery; its visibility failure does not establish the state of today's CIA checkpoint.

### August 1 checkpoint visibility

As of the last totality board render (`ember-totality-20260801T052815Z.json`),
condition `C-BASE` was RED: "artifact root not provided / bytes not visible
from this tree (6 owned-pretrain candidate(s) name a checkpoint but its
manifest.json/model.pt were not found under the resolved artifact root
... this is a visibility failure, not an absence failure." This card
therefore describes the **target contract**, not a completed model. Anyone
citing this card as evidence of a working owned checkpoint is misreading it.

### Historical target architecture

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

### Historical remaining conditions

No checkpoint bytes, no evaluation scores, and no capability claims are made
by this card. `C-BASE`, `C-SCALE`, `C(-1)` (regression), and the benchmark
conditions in 06_EVALUATION_AND_BENCHMARKS.md track the real remaining
distance between this contract and a card that could honestly claim a
trained, evaluated model.
