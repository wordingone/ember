# Inference-To-Training Transfer Protocol V0

Status: DRAFT FILTER, not a pass.
Created: 2026-06-29.

This protocol exists because Ember has many DeepSeek, MTP, MLA, speculative decoding, and kernel references whose published wins often live on inference, draft-model, or distributed-serving axes. The baseline must not turn an inference-speed result into a training-efficiency, sample-efficiency, or one-4090 feasibility claim unless the transfer path is measured.

## Source Thread

Local Ember files already contain the relevant research thread:

- `<private-ember-local-checkout>\research\nc2-technique-survey-2026-06.md` separates MTP, MLA/KV compression, and FP8 from the one-4090 training claim.
- `<private-ember-local-checkout>\research\gpu-math-multiplier-table-v2-2026-06-11.json` includes rows that translate or reject inference multipliers for training and small-scale use.
- `<private-ember-local-checkout>\nc2-own-technique-contract.md` lists DeepSeek-style MTP, MLA, FP8, sparse attention, MoE, and GRPO as candidate components with staging decisions.
- `<private-ember-local-checkout>\receipts\ns-chain-roofline-4090-adjudication-20260623T171500Z.json` warns that training tall-skinny GEMM bottlenecks and small inference matmuls must not be conflated without direct measurement.

## DSpark Correction

`DSpark` is resolved as a DeepSeek DeepSpec draft-model algorithm, not as a standalone `deepseek-ai/DSpark` repository.

Pinned source:

- repository: `https://github.com/deepseek-ai/DeepSpec`
- commit: `6443750b5cc6317b9dfd6e971b272577281c8d1c`
- paper path: `DSpark_paper.pdf`
- config example: `config/dspark/dspark_qwen3_4b.py`
- released checkpoint rows: `deepseek-ai/dspark_qwen3_4b_block7`, `deepseek-ai/dspark_qwen3_8b_block7`, `deepseek-ai/dspark_qwen3_14b_block7`, `deepseek-ai/dspark_gemma4_12b_block7`

DeepSpec describes itself as a full-stack codebase for training and evaluating draft models for speculative decoding. Its README says the default configs/scripts assume one node with 8 GPUs, and the default `Qwen/Qwen3-4B` target-cache path can require roughly 38 TB of storage. Therefore DSpark is an external frontier baseline for speculative decoding and draft-model training/evaluation, not direct evidence for Ember's single-4090 foundation-model pretraining claim.

Receipt: `receipts/deepseek-dspark-resolution-2026-06-29.json`.

## Transfer Rules

| Optimization class | Typical published axis | Allowed Ember baseline use | Rejection rule |
|---|---|---|---|
| Speculative decoding, EAGLE, DeepSeek DSpark, DFlash, DeepSpec | Inference tokens/s, acceptance, completions/task, draft-model training | May baseline sampler throughput, draft-model quality, or CLI/agent-loop sampling cost. May not prove foundation-model pretraining speed, training energy, or sample efficiency. | Reject transfer unless the receipt measures the same model class, same GPU class, same task, and inference-only accounting is explicitly separated from training. |
| DeepSeek-style MTP drafter | Inference speed or auxiliary/draft objective | May be tested as a component ablation. Existing local survey treats small-scale MTP-as-pretraining-quality as negative or unproven. | Reject any automatic multiplier at <=1B unless matched ablation improves locked validation/capability at equal tokens, wall-clock, VRAM, and energy. |
| MLA / KV compression / FlashMLA | Inference memory, long-context serving, attention kernels | May be an attention/kernel candidate. Does not count as a one-4090 training bottleneck fix by default. | Reject unless forward+backward memory and throughput improve the actual training step on RTX 4090 under the selected context length. |
| DeepGEMM / fused kernels / TileKernels | Kernel throughput, often forward or microbenchmark | May enter C3 only as a kernel candidate. | Reject if the measured path is forward-only while the claim concerns forward+backward+optimizer training. |
| DeepEP, EPLB, DualPipe, 3FS, smallpond | Distributed MoE communication, load balancing, pipeline overlap, storage/data infra | May inform future multi-GPU or data-pipeline baselines. | Reject for the default single-4090 dense baseline unless it removes a measured local bottleneck without adding hidden distributed hardware. |
| FP8 DeepSeek-V3-style recipe | Training precision and throughput on datacenter paths | May become a training candidate only after Ada/RTX 4090 support, numerics, and quality are locally verified. | Reject if the path depends on H100/MI300-only kernels, unavailable libraries, or unmeasured loss/quality drift. |

## Required Receipt Fields

Any transfer claim must state:

- whether it measures inference-only, forward-only, forward+backward, optimizer-only, draft-model training, or full foundation-model train step;
- hardware, precision, batch size, sequence length, model size, target model, and dataset;
- tokens/s, acceptance, wall-clock, peak allocated VRAM, peak reserved VRAM, and energy if available;
- preserved functionality and quality metric;
- ablation or baseline arm;
- whether copied external numbers are being cited only as external context or used as a rejection threshold.

## Current Verdict

This protocol rejects free transfer. DSpark/DeepSpec is now pinned, but it is scoped to speculative decoding until a same-axis training receipt proves a wider claim.