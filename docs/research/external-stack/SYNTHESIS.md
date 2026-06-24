# External stack synthesis — owning the full stack (#23)

User requisite 2026-06-10: AI2, "LumiGuide"/EuroHPC, Nous Research,
Cognitive Computations, Unsloth, vLLM/llama.cpp — non-frontier, maximally
public orgs as the resource base for owning every layer. Three Haiku survey
artifacts in this directory carry the receipts (URLs verified per claim);
this file is the synthesis: what we take, what we build, which tracker item
consumes each pin. "LumiGuide" does not exist in the LLM space — closest
real referent is the LUMI/EuroHPC open-model ecosystem (Poro/Viking,
OpenEuroLLM), surveyed as such.

## The shape of the answer

The ecosystem hands us the COMMODITY layers nearly whole — data curation,
small-scale training harness, post-training recipes, serving. It hands us
almost NOTHING for the layers the goal actually claims as contribution:
QAT/ternary pretraining, MTP, replay/consolidation, verifier-gated
experience. That split matches the goal's problem-level calibration test
exactly: where a dependency exists, it is instrumentation; the missing
layers are the work.

## Adopt (instrumentation layer — minimum effort, never the center)

| Layer | Pin | License | Consumed by |
|---|---|---|---|
| Data curation/dedup | github.com/allenai/dolma (tokshuf dedup, taggers) | Apache-2.0 | #28 recipe stack |
| Pretrain configs 412M–1B + eval | github.com/mlfoundations/dclm (open_lm) | Apache-2.0 | #28 (downscale to 1×4090) |
| Single-GPU pretrain framework (alt) | github.com/NousResearch/Automodel (FSDP2, single-GPU YAML explicit) | Apache-2.0 | #28 (A/B vs open_lm) |
| Curriculum recipe (two-stage mix) | github.com/allenai/OLMo-core (Dolmino Mix specs public) | Apache-2.0 | #28 |
| Optimizer | github.com/KellerJordan/Muon (+ flash-muon) | MIT-class | #28 (component contract §7) |
| Post-train SFT/DPO templates | github.com/allenai/open-instruct | Apache-2.0 | round-2+ arms |
| RL environments incl. MBPP | github.com/NousResearch/atropos (reward fns, trajectory API) | MIT | #26 partial-credit arm; round-2 GRPO worlds |
| Serving (GPU) | vLLM — AWQ-INT4 + Marlin (1.7–2.4× on Ada), multi-LoRA hot-swap | Apache-2.0 | NC-K resident form (#34) |
| Serving (CPU/edge) | llama.cpp GGUF Q4_K_M/Q5_K_M; custom-arch via tensor-type workaround (issue #21447) | MIT | NC-K resident form (#34) |
| GRPO dtype fixes | unsloth issues #5183 (TRL-first import) + #4891 (dtype=fp16) | — | #24 attempt-7 candidate if the lm_head pre-hook fails |

## Build (contribution layer — no dependency provides these)

1. **GRPO training loop on OUR verifier** — Atropos gives environments;
   nobody publishes the loop wired to a local sandbox oracle. Ours exists
   (t2_grpo + t1_probe rewards); #24 finishes integration.
2. **QAT/ternary PRETRAINING** — BitNet b1.58 requires native training;
   ecosystem has inference only (bitnet.cpp). The survey's "skip for 2026
   Q2" recommendation is REJECTED per the component contract (1.58-bit is
   directed component #3) and break-the-wall: the floor is fake-quant/
   ternary layers inside our own pretrain harness + microsoft/BitNet
   (bitnet.cpp) as the serving path pin. llama.cpp upstream never merged
   b1.58 (issue #5761 closed stale) — fork path stays named.
3. **MTP pretraining heads** — not formalized anywhere surveyed; our
   t2_mtp aux-head implementation is already ahead; ports into the
   pretrain harness at NC2-own.
4. **Replay/sleep-consolidation** — research-phase everywhere; our ledger
   IS the replay buffer; spec lands in #35.
5. **Verifier-gated experience ledger + three-test gain gate** — exists
   nowhere in the ecosystem; it is this repo.

## Notes gated from the surveys

- DisTrO/Psyche: bandwidth claims UNVERIFIED, implementation entangled
  with Solana infra — irrelevant to single-box; ignore.
- Cognitive Computations: training infra private; public take = Dolphin
  dataset (Apache-2.0) curation/filtering METHODOLOGY + laserRMT as a
  post-hoc rank-reduction reference. Thin.
- Nemotron recipes: datacenter-scale only; data sources (Nemotron-CC) are
  the reusable part.
- DCLM confidence per survey: high for data+eval, medium for training
  harness (multi-GPU defaults need downscaling — that downscale receipt is
  #28's smoke-scale AC).
