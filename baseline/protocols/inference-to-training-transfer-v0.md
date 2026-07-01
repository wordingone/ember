# Inference-To-Training Transfer Protocol V1

Status: BASELINE_COMPLETE for the `architecture_growth_keystone_sota` family only.
Created: 2026-06-29.

This protocol exists because Ember has many DeepSeek, MTP, MLA, speculative decoding, precision, kernel, and infrastructure references whose published wins often live on inference, draft-model, forward-only, distributed-serving, or data-pipeline axes. The baseline must not turn those results into training-efficiency, sample-efficiency, single-4090 feasibility, or keystone-growth claims unless the transfer path is measured on the same axis.

## Source Thread

Local Ember files already contain the relevant research thread:

- `B:\M\ember\research\nc2-technique-survey-2026-06.md` separates MTP, MLA/KV compression, and FP8 from the one-4090 training claim.
- `B:\M\ember\research\gpu-math-multiplier-table-v2-2026-06-11.json` includes rows that translate or reject inference multipliers for training and small-scale use.
- `B:\M\ember\nc2-own-technique-contract.md` lists DeepSeek-style MTP, MLA, FP8, sparse attention, MoE, and GRPO as candidate components with staging decisions.
- `B:\M\ember\receipts\ns-chain-roofline-4090-adjudication-20260623T171500Z.json` warns that training tall-skinny GEMM bottlenecks and small inference matmuls must not be conflated without direct measurement.

## Pinned External Architecture Anchors

| Lane | Source rows | What it controls | Scope limit |
|---|---|---|---|
| AG-DEEPSEEK-INFERENCE-TRANSFER | `deepseek-deepspec-dspark`, `deepseek-open-infra-index` | DSpark/DeepSpec speculative decoding, draft-model training/evaluation, DeepSeek open infrastructure candidates including DeepGEMM, DeepEP, FlashMLA, DualPipe, 3FS, and TileKernels. | Same published axis only unless a same-axis training receipt exists. |
| AG-LOWBIT-KERNEL-TRAINING | `bitnet` | Low-bit/1.58-bit architecture and quantized-training candidate. | Requires preserved-quality full training-step or pretraining-equivalent evidence; inference/model-format-only evidence is not enough. |

## DSpark Correction

`DSpark` is resolved as a DeepSeek DeepSpec draft-model algorithm, not as a standalone `deepseek-ai/DSpark` repository.

Pinned source:

- repository: `https://github.com/deepseek-ai/DeepSpec`
- commit: `6443750b5cc6317b9dfd6e971b272577281c8d1c`
- paper path: `DSpark_paper.pdf`
- config example: `config/dspark/dspark_qwen3_4b.py`
- released checkpoint rows: `deepseek-ai/dspark_qwen3_4b_block7`, `deepseek-ai/dspark_qwen3_8b_block7`, `deepseek-ai/dspark_qwen3_14b_block7`, `deepseek-ai/dspark_gemma4_12b_block7`

DeepSpec is an external frontier baseline for speculative decoding and draft-model training/evaluation, not direct evidence for Ember's single-4090 foundation-model pretraining claim.

Receipt: `receipts/deepseek-dspark-resolution-2026-06-29.json`.

## Transfer Rules

| Optimization class | Typical published axis | Allowed Ember baseline use | Rejection rule |
|---|---|---|---|
| Speculative decoding, EAGLE, DeepSeek DSpark, DFlash, DeepSpec | Inference tokens/s, acceptance, completions/task, draft-model training | May baseline sampler throughput, draft-model quality, or CLI/agent-loop sampling cost. | Reject transfer unless the receipt measures the same model class, same GPU class, same task, and inference-only accounting is explicitly separated from training. |
| DeepSeek-style MTP drafter | Inference speed or auxiliary/draft objective | May be tested as a component ablation. Existing local survey treats small-scale MTP-as-pretraining-quality as negative or unproven. | Reject any automatic multiplier at <=1B unless matched ablation improves locked validation/capability at equal tokens, wall-clock, VRAM, and energy. |
| MLA / KV compression / FlashMLA | Inference memory, long-context serving, attention kernels | May be an attention/kernel candidate. Does not count as a one-4090 training bottleneck fix by default. | Reject unless forward+backward memory and throughput improve the actual training step on RTX 4090 under the selected context length. |
| DeepGEMM / fused kernels / TileKernels | Kernel throughput, often forward or microbenchmark | May enter architecture/kernel lane only as a kernel candidate. | Reject if the measured path is forward-only while the claim concerns forward+backward+optimizer training. |
| DeepEP, EPLB, DualPipe, 3FS, smallpond | Distributed MoE communication, load balancing, pipeline overlap, storage/data infra | May inform future multi-GPU or data-pipeline baselines. | Reject for the default single-4090 dense baseline unless it removes a measured local bottleneck without adding hidden distributed hardware. |
| FP8, BitNet, 1.58-bit, QAT, optimizer/state compression | Low-bit training, inference, model-format, or optimizer memory | May become a training candidate only after numerics, quality, and train-step path are verified. | Reject if the path lacks preserved quality, backward pass, optimizer state, or selected-hardware support. |

## Required Receipt Fields

Any transfer claim must state:

- whether it measures inference-only, forward-only, forward+backward, optimizer-only, draft-model training, or full foundation-model train step;
- hardware, precision, batch size, sequence length, model size, target model, and dataset;
- tokens/s, acceptance, wall-clock, peak allocated VRAM, peak reserved VRAM, and energy if available;
- preserved functionality and quality metric;
- ablation or baseline arm;
- whether copied external numbers are being cited only as external context or used as a rejection threshold.

## Current Verdict

ARCHITECTURE_GROWTH_BASELINE_COMPLETE for the architecture/growth comparator-family definition only. It rejects free transfer. DSpark/DeepSpec and DeepSeek open-infra anchors are pinned, and BitNet/low-bit training candidates are scoped to same-axis training evidence only. This is not an Ember architecture win and not overall `/baseline` completion.