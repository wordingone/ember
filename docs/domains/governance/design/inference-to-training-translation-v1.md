# Inference-to-training translation v1

**Authority:** issue #55. **Scope:** maintained research baseline, not a capability
claim. **Rule:** every inference lever is asked, “what is your training twin?”

`ABSENT` is an admissible result. It identifies a research obligation; it does not
mean that Ember has implemented or disproved the mechanism. Field-maturity labels
are bound to the primary sources below. Ember status is bound only to checked-in
paths; no row upgrades a configuration, harness, or historical receipt into a
trained-checkpoint claim.

| ID | Inference technique | Inference benefit | Training analog | Field maturity | Ember status | Candidate experiment |
|---|---|---|---|---|---|---|
| T01 | post-training quantization | Smaller resident weights and integer inference | Quantization-aware training with fake-quantized forward weights and latent trainable weights | ESTABLISHED [S01] | CONFIGURED/HISTORICAL_ONLY: `domains/model/configs/v0-pretrain-config.json`; the old 0.928x pacing number is not a current native-checkpoint claim and is explicitly guarded against as stale by `src/ember/governance/scripts/test_ember_cbase_launch.py` | Same-seed QAT-on/QAT-off run with exact token, FLOP, quality, and peak-memory receipts |
| T02 | speculative decoding | Draft several tokens and verify them in parallel | Multi-token-prediction auxiliary heads trained jointly with the backbone | ESTABLISHED_IN_RESEARCH [S02] | CONFIGURED: two heads at weight 0.3 in `domains/model/configs/v0-pretrain-config.json`; isolation benefit remains unreceipted | Same architecture and total FLOPs with auxiliary loss weight 0.3 versus 0.0 |
| T03 | frozen low-bit residency | Keep a large base resident at four bits | Frozen quantized majority with a trained low-rank or sparse slice | SHIPPED_FOR_FINETUNING [S03] | PREFLIGHT_ONLY: `src/ember/governance/scripts/r3_feasibility_probe.py`; no owned admitted R3 checkpoint | One governed update plus inference while the frozen base and trainable slice remain co-resident |
| T04 | mixture-of-experts partial activation | Route each token through only a subset of experts | Sparse gradient routing; the unresolved twin is residency-sparse training where only the active slice is resident and trainable | ESTABLISHED_FOR_CONDITIONAL_COMPUTE; RESIDENCY_GAP_REMAINS [S04] [S03] | PARTIAL: owned expert routing exists in `tools/ember-restart-3b`; no receipt proves nonresident inactive experts during training | Compare resident-all-experts sparse routing with streamed inactive experts under identical tokens and route decisions |
| T05 | kv-cache reduction | Reduce decoding-state memory through fewer KV heads | GQA uptraining plus activation checkpointing or sequence-parallel activation partitioning | ESTABLISHED [S05] [S06] | DESIGN_ONLY: `docs/domains/governance/ember-restart/ember-multimodal-v0-config-spec.md`; current 3B birth evidence does not claim this training-memory win | Measure full-step activation peak for MHA, GQA, and GQA plus checkpointing at fixed model and tokens |
| T06 | pruning | Remove inference-time weights or structures | Dynamic sparse training and masked backpropagation with regrowth | ESTABLISHED_IN_RESEARCH [S07] | ABSENT: no current owned sparse-training receipt | Fixed-FLOP dense versus prune-and-regrow training with deletion control and final dense-cost evaluation |
| T07 | serving distillation | Deploy a smaller student that imitates a larger teacher | Online or self-distillation loss during training | ESTABLISHED [S08] | ABSENT: no current owned self-distillation training receipt | Same-seed student with and without checkpoint-frozen teacher logits at matched total FLOPs |
| T08 | ternary inference | Reduce weight bandwidth with {-1,0,1} weights | BitNet-class quantization-aware training retains latent update state; an inference-sized optimizer-memory twin is not established | PAPERS_ONLY_FOR_NATIVE_TERNARY_RECIPE; MEMORY_TWIN_ABSENT [S09] | TRIGGER_GATED: `src/ember/governance/scripts/ember_phase3_c14/floor_contract_manifest.py`; no native ternary checkpoint | Measure resident inference bytes separately from latent-weight, gradient, and optimizer bytes during one real step |
| T09 | parameter and optimizer offload | Stream cold inference weights from slower tiers | ZeRO-style parameter, gradient, and optimizer-state partitioning or offload | ESTABLISHED [S10] | PARTIAL/DESIGN_ONLY: host-state experiments exist; no current governed 3B birth receipt proves the complete offload path | One restartable step with byte-accounted transfers, optimizer identity, and post-resume equality |
| T10 | low-rank adapters | Add a small inference-time delta instead of replacing a base | Low-rank adaptation trains only factor matrices against a frozen backbone | ESTABLISHED [S11] | HISTORICAL_ONLY: adapter harnesses exist, but they are not the owned 3B birth checkpoint | Compare adapter-only, sparse-expert, and full-update arms at matched update FLOPs and held-out data |
| T11 | low-bit optimizer state | N/A directly; motivated by keeping deployment-sized systems trainable | Block-wise quantized optimizer statistics | ESTABLISHED [S12] | ABSENT in the current production path: `src/ember/infrastructure/tools/ember-restart-3b/checkpoint_artifacts.py` rejects an AdamW8bit identity | Add an owned 8-bit optimizer-state codec with checkpoint round-trip and matched-quality control |
| T12 | low-rank update compression | Reduce transmitted or stored update material | Gradient low-rank projection while retaining full-parameter learning | ESTABLISHED_IN_RESEARCH [S13] | ABSENT: no current GaLore-class owned training receipt | Same-seed projected versus full-rank gradients with optimizer-state bytes and convergence per FLOP |
| T13 | flash attention | Reduce attention IO and materialized score memory at inference | The same IO-aware exact-attention kernel accelerates forward and backward training | SHIPPED_AND_MEASURED [S14] | SPECIFIED: `docs/domains/governance/ember-restart/ember-multimodal-v0-config-spec.md`; not credited as a current 3B training result | Kernel-identical eager/SDPA/Flash forward-backward comparison with peak HBM and end-to-end step time |
| T14 | state-space recurrence | Linear-time decoding without a growing KV cache | Parallel selective-state-space scan during training | ESTABLISHED_IN_RESEARCH [S15] | ABSENT: subquadratic architecture remains a named recon lane only | Matched-parameter Transformer/SSM/hybrid pretraining at increasing sequence lengths and fixed tokens |
| T15 | adaptive computation | Spend fewer inference layers or iterations on easy tokens | Differentiable halting or learned conditional depth during training | ESTABLISHED_IN_RESEARCH [S16] | ABSENT: no owned adaptive-depth receipt | Add a ponder-cost arm and compare quality per executed layer with a fixed-depth control |
| T16 | grouped-query attention conversion | Reduce KV heads without full retraining | Uptrain an existing multi-head checkpoint into GQA using a bounded fraction of original compute | ESTABLISHED [S05] | ABSENT_AS_CONVERSION: GQA is specified for new architecture work, not proven as an Ember checkpoint conversion | Convert one exact checkpoint, then compare quality, KV bytes, update FLOPs, and deletion of the conversion loss |

## Standing process

1. A new inference lever cannot enter the SOTA gap table without a row here.
2. The row must identify an existing training twin or mark the twin `ABSENT`.
3. Field maturity must cite a primary paper or public implementation artifact.
4. Ember status must cite an exact checked-in config, implementation, or receipt;
   otherwise it is `ABSENT`.
5. W2/C-SCALE(ii) experiments select from the `ABSENT` and `PARTIAL` rows, freeze
   a comparator and deletion test, and may change status only after the receipt lands.

## Sources

- [S01] https://arxiv.org/abs/1712.05877
- [S02] https://arxiv.org/abs/2404.19737
- [S03] https://arxiv.org/abs/2305.14314
- [S04] https://arxiv.org/abs/2101.03961
- [S05] https://arxiv.org/abs/2305.13245
- [S06] https://arxiv.org/abs/1604.06174
- [S07] https://arxiv.org/abs/1911.11134
- [S08] https://arxiv.org/abs/1503.02531
- [S09] https://arxiv.org/abs/2402.17764
- [S10] https://arxiv.org/abs/2104.07857
- [S11] https://arxiv.org/abs/2106.09685
- [S12] https://arxiv.org/abs/2110.02861
- [S13] https://arxiv.org/abs/2403.03507
- [S14] https://arxiv.org/abs/2205.14135
- [S15] https://arxiv.org/abs/2312.00752
- [S16] https://arxiv.org/abs/1603.08983
