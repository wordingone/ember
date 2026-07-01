# Single RTX 4090 >=1B Foundation Ceiling Baseline V1

Status: ENGINEERING_BASELINE_SURFACE_READY for `single_4090_ge_1b_foundation_ceiling`. The theoretical ceiling is mapped and now paired with a runnable/replayable engineering surface. This is not an Ember win, not a governed non-dry-run result, and not overall `/baseline` completion.
Claim family: `single_4090_ge_1b_foundation_ceiling`.
Access date: 2026-06-29.
Hardware target: one RTX 4090-class 24GB GPU.

## Question

What is the fastest honest path by which an individual could train, or pretraining-equivalent-train, a foundation-model-scale system with at least 1B active/trainable parameters on one RTX 4090-class GPU in days rather than years?

This module uses <=14 calendar days as the days-scale threshold. It separates from-scratch training from pretraining-equivalent adaptation because the two have different field claims and falsifiers.

## Pinned Source Anchors

| Source row | Role in this ceiling | Scope limit |
|---|---|---|
| `nvidia-rtx-4090` | Hardware boundary: one RTX 4090-class 24GB GPU, local probe also observed NVIDIA GeForce RTX 4090, 24564 MiB, 450 W limit. | Hardware spec is not a training throughput receipt. |
| `chinchilla` | Scaling-law compute/data pressure and the `6 * parameters * tokens` training-FLOP approximation used for lower-bound economics. | Compute lower bound, not a capability guarantee. |
| `mlcommons-algoperf` | Time-to-result and reproducible training accounting discipline. | Protocol discipline, not a 4090 result. |
| `pytorch-sdpa-flashattention` | Evidence-backed attention kernel path via PyTorch scaled dot product attention routing, including FlashAttention-style kernels where supported. | Must be measured at the selected forward+backward training shape. |
| `pytorch-activation-checkpointing` | Activation-memory reduction mechanism with recompute cost. | Memory win must include throughput penalty. |
| `bitsandbytes-8bit-optimizers` | Optimizer-state reduction source for fitting >=1B training on 24GB. | Stability, quality, and speed costs must be measured. |
| `bitnet` | Low-bit/1.58-bit training/architecture candidate. | Credited only with same-axis train-step and quality evidence. |
| `deepseek-deepspec-dspark` / `deepseek-open-infra-index` | Inference/kernel/infrastructure transfer candidates. | Rejected for training-speed credit unless same-axis training receipts exist. |
| `nvidia-cutlass` / `triton-language` | Native CUDA C++/CUTLASS and Triton custom-kernel anchors for the lower-level 4090 ceiling. | PyTorch is not accepted as the automatic ceiling unless these paths are bounded, measured, or shown to be irrelevant for the selected forward+backward+optimizer stack. |

## Compute Floor

The baseline lower-bound formula is:

```text
training_flops ~= 6 * active_parameters * trained_tokens
```

For 1B active/trainable parameters:

| Token budget | Training FLOPs | Days @ 50 TFLOP/s | Days @ 75 TFLOP/s | Days @ 100 TFLOP/s | Days @ 150 TFLOP/s | Days @ 200 TFLOP/s | Days @ 250 TFLOP/s |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 5B | 3.00e19 | 6.94 | 4.63 | 3.47 | 2.31 | 1.74 | 1.39 |
| 10B | 6.00e19 | 13.89 | 9.26 | 6.94 | 4.63 | 3.47 | 2.78 |
| 20B | 1.20e20 | 27.78 | 18.52 | 13.89 | 9.26 | 6.94 | 5.56 |
| 30B | 1.80e20 | 41.67 | 27.78 | 20.83 | 13.89 | 10.42 | 8.33 |
| 50B | 3.00e20 | 69.44 | 46.30 | 34.72 | 23.15 | 17.36 | 13.89 |

Required sustained end-to-end training throughput for <=14 days:

| Token budget | Required sustained throughput |
|---:|---:|
| 5B | 24.80 TFLOP/s |
| 10B | 49.60 TFLOP/s |
| 20B | 99.21 TFLOP/s |
| 30B | 148.81 TFLOP/s |
| 50B | 248.02 TFLOP/s |

Ceiling answer on compute alone:

- 1B / 5B-10B tokens is days-scale on a 4090 if the full stack sustains about 25-50 TFLOP/s end to end.
- 1B / 20B tokens is days-scale only with about 100 TFLOP/s sustained end-to-end training throughput.
- 1B / 30B tokens is days-scale only with about 149 TFLOP/s sustained; this is aggressive but not mathematically impossible.
- 1B / 50B tokens needs about 248 TFLOP/s sustained; this is an extreme best-case ceiling and cannot be treated as practical without a representative long-run receipt.

These FLOP floors do not prove useful foundation-model capability. They define the outside ruler Ember must beat or tighten.

## Memory Feasibility Stack

A 1B active/trainable-parameter model can fit on 24GB only if the optimizer, activation, sequence, batch, and temporary-memory stack are engineered as part of the baseline.

| Stack | Weights | Gradients | Optimizer/master state | Approx subtotal before activations | Baseline ruling |
|---|---:|---:|---:|---:|---|
| bf16 weights + bf16 grads + fp32 AdamW moments + fp32 master | 2GB | 2GB | 12GB | 16GB | Mathematically fits before activations, but leaves too little practical headroom for useful sequence/batch without activation checkpointing and careful fragmentation margin. |
| bf16 weights + bf16 grads + 8-bit optimizer + fp32 master estimate | 2GB | 2GB | ~5-6GB | ~9-10GB | Plausible fit path with activation checkpointing, sequence packing, fused kernels, small microbatching, and measured stability/quality. |
| bf16 weights + bf16 grads + compressed/offloaded optimizer state | 2GB | 2GB | variable | ~4GB + offload/compression | Conditionally valid only if CPU/NVMe bandwidth, stalls, restart cost, and quality cost are in the wall-clock receipt. |
| low-bit/QAT/BitNet-style path | <2GB effective weights | variable | variable | unknown | Candidate ceiling mechanism, but not credited unless the same training-axis receipt preserves quality and covers backward+optimizer. |

Required memory receipt fields for any Ember run against this baseline:

- parameter count and active/trainable/frozen split;
- weights, gradients, optimizer/master state, activations, temporary buffers, dataloader staging, fragmentation margin, and evaluation overhead;
- sequence length, microbatch, global batch via accumulation, packing policy, and activation checkpointing policy;
- peak allocated and peak reserved VRAM from the selected run;
- restart/resume and checkpoint storage costs.

## Precision, Quantization, And Kernel Stack

Allowed mechanisms for the ceiling:

- bf16/fp16 training when numerically stable;
- PyTorch scaled-dot-product attention / FlashAttention-style route only when selected by the runtime and measured at the chosen train shape;
- activation checkpointing with the recompute penalty counted in throughput;
- 8-bit optimizer or equivalent optimizer-state compression with stability and quality receipts;
- sequence packing and fused losses/kernels where they preserve the exact task and evaluation contract;
- QAT/int8/int4/1.58-bit/BitNet-style training only when training-axis evidence exists on the selected model family;
- CPU/NVMe offload only when wall-clock stalls and failure/restart costs are included.

Rejected automatic transfers:

- inference-only speedups do not reduce training FLOPs by default;
- forward-only kernel microbenchmarks do not count as forward+backward+optimizer training speed;
- distributed MoE, pipeline, EP, or storage systems do not count for one-4090 dense training unless the receipt shows a local one-GPU bottleneck removed;
- draft-model/speculative decoding wins do not count as foundation pretraining wins without same-axis training evidence.

## Native C++/CUDA/Triton Ceiling

PyTorch is a reproducible reference path, not the automatic ceiling. The C1 ruler must account for native C++/CUDA, CUTLASS-style kernels, Triton kernels, fused optimizer/loss/attention paths, and any lower-level route that could materially raise sustained one-4090 training throughput.

Therefore a final C1 PASS requires one of two outcomes:

1. native/lower-level implementation or benchmark receipts show the ceiling and the PyTorch path is not leaving a material gap; or
2. the claim is explicitly bounded as a PyTorch-framework baseline and cannot be used as the absolute 4090 ceiling.

The current full-stack probes are PyTorch/SDPA receipts. They are valuable evidence for the reference implementation, but they do not close the native C++/CUDA/Triton ceiling by themselves.

## Engineering Implementation Surface

The theoretical ceiling is implemented as an inspectable engineering baseline under `engineering/4090-1b/`:

- `environment.json` locks the hardware/software and receipt contract.
- `configs/from_scratch_1b_4090.json` defines the from-scratch lane.
- `configs/pretraining_equivalent_1b_4090.json` defines the pretraining-equivalent lane.
- `train_1b_4090.py` computes exact active/trainable parameter counts, memory plan, throughput requirement, and stop-rule receipts.
- `parse_receipts.py` validates dry-run, probe, and native kernel receipts.
- `native_kernel_probe_4090.py` records bounded Triton/native GEMM telemetry against PyTorch at transformer-relevant shapes.
- `README.md` gives replay commands and non-dry-run gates.

Current dry-run receipts:

- `receipts/4090-engineering-from-scratch-dry-run.json`: `DRY_RUN_ENGINEERING_BASELINE_READY`, 1,027,764,224 active trainable parameters, estimated 11.69GB 8-bit-optimizer memory plan before required representative long-run receipts, 10B-token/14-day requirement of 50.98 sustained TFLOP/s.
- `receipts/4090-engineering-from-scratch-parse.json`: `ENGINEERING_DRY_RUN_PASS`.
- `receipts/4090-engineering-pretraining-equivalent-dry-run.json`: `DRY_RUN_ENGINEERING_BASELINE_READY`, 1,027,764,224 active trainable parameters, 5B-token/7-day requirement of 50.98 sustained TFLOP/s.
- `receipts/4090-engineering-pretraining-equivalent-parse.json`: `ENGINEERING_DRY_RUN_PASS`.

This engineering surface does not complete the family by itself. It replaces the earlier report-only state and defines the object that a governed long run must execute or beat.

Bounded governed GPU probes now exist for both lanes: `receipts/4090-governed-probe-from-scratch.json` and `receipts/4090-governed-probe-pretraining-equivalent.json`, with parser PASS receipts. They execute real local RTX 4090 forward/backward optimizer steps at bounded probe shape and preserve a no-completion-claim stop rule. They do not substitute for representative full-1B long-run throughput evidence.

Full-config memory allocation probes now exist for both lanes: `receipts/4090-full-memory-probe-from-scratch.json` and `receipts/4090-full-memory-probe-pretraining-equivalent.json`, with parser PASS receipts. These allocate the C1 planned 1.027B-parameter memory stack on the local RTX 4090 and reserve 11.6875GB peak against 23.9878GB device memory. This supports memory feasibility; it does not prove full forward/backward throughput at the 1B shape.

Full-shape block throughput probes now exist for both lanes: `receipts/4090-full-shape-block-probe-from-scratch.json` and `receipts/4090-full-shape-block-probe-pretraining-equivalent.json`, with parser PASS receipts. They run the locked C1 block shape at sequence length 2048, hidden size 2048, 16 heads, bf16, and SDPA causal attention. Observed lower-bound block throughput was 7.32-7.73 TFLOP/s. This is representative block telemetry, not full 19-layer 1B long-run throughput.

Full-stack bounded step probes now exist for both lanes: `receipts/4090-full-stack-step-probe-from-scratch.json` and `receipts/4090-full-stack-step-probe-pretraining-equivalent.json`, with parser PASS receipts. They execute all 19 configured transformer layers at sequence length 2048, hidden size 2048, 16 heads, bf16, activation checkpointing, SDPA causal attention, forward/backward, and AdamW optimizer step. They reserve about 10.49GB and observe 27.98-28.48 lower-bound TFLOP/s, below the 50.98 sustained TFLOP/s requirement for the locked 10B/14-day or 5B/7-day lanes. They use a hidden-state surrogate loss, so they are not long-run language-model training receipts and not C1 completion.

A native kernel probe now exists at `receipts/4090-native-kernel-probe-from-scratch.json`, with parser PASS receipt `receipts/4090-native-kernel-probe-from-scratch-parse.json`. It compares PyTorch tuned matmul with a simple Triton GEMM on C1 transformer shapes. PyTorch measured about 138-155 TFLOP/s; the simple Triton kernel measured about 45-49 TFLOP/s with relative BF16 error below 0.5%. This bounds one lower-level GEMM path and shows PyTorch is currently stronger for these shapes, while leaving fused attention/backward/optimizer/native C++ paths as required future C1 evidence.

A bounded native training-stack probe now exists at `receipts/4090-native-training-stack-probe-pretraining-equivalent.json`, validated by `receipts/4090-native-training-stack-validation-2026-06-30.json`. It measures PyTorch/CUDA SDPA attention forward/backward, CUDA cross-entropy, and fused AdamW API behavior at C1-like shapes; it still leaves a full CUDA C++ transformer block, Triton fused attention backward replacement, fused residual/norm stack, full 19-layer native long-run receipt, and thermal/power stability as open native-ceiling surfaces.

## From-Scratch Path

This lane is the from scratch training lane; it is separate from pretraining-equivalent adaptation.

Minimum complete from-scratch comparator:

- exact architecture with >=1B active/trainable parameters;
- token budget and data provenance;
- capability target and evaluation suite frozen before training;
- representative local sustained throughput at the selected 1B-ish shape, including PyTorch reference and native C++/CUDA/Triton ceiling treatment;
- memory receipt proving fit on one 24GB RTX 4090;
- wall-clock inclusion for data prep, training, eval, restart/recovery, and packaging;
- energy method or explicit estimate from power limit and wall-clock.

Ceiling ruling: from-scratch days-scale is theoretically credible for 1B active parameters at 5B-20B tokens if the stack sustains roughly 25-100 TFLOP/s. 30B tokens is the aggressive practical frontier. 50B tokens is an extreme upper ceiling. None of these token budgets, by themselves, prove broad frontier capability; they establish the days-scale compute envelope Ember must beat or justify.

## Pretraining-Equivalent Path

Definition: continued pretraining, distillation, adapter/LoRA, retrieval-augmented training, synthetic curriculum, or another path that claims foundation-model-relevant capability without a clean from-scratch run.

Minimum complete pretraining-equivalent comparator:

- base model identity, license, and acquisition cost;
- trainable and frozen parameter counts, with >=1B active/trainable if the claim says active/trainable >=1B;
- data provenance and token/example budget;
- matched base, random/control, context-only, and deletion/ablation arms;
- capability delta over base under a frozen external evaluation suite;
- wall-clock and energy accounting including data prep, eval, recovery, and packaging.

Ceiling ruling: pretraining-equivalent days-scale is more credible for meaningful capability than from-scratch 1B training, but it is a different field claim. It cannot be laundered into a from-scratch foundation-training result.

## Capability Target Floor

A valid Ember-vs-baseline run must freeze one of these target classes before execution:

1. from-scratch LM capability floor: loss and downstream/evaluation target at a named token budget and data mix;
2. compact/data-efficient reasoning floor: external reasoning/task suite with leakage controls;
3. pretraining-equivalent delta floor: statistically meaningful improvement over base and matched controls.

A lower loss or faster run without a predeclared capability target is not a field-level win.

## Falsifiable Contract

Build or run Ember artifact `X_4090_1B` that trains or pretraining-equivalent-trains at least 1B active/trainable parameters on one RTX 4090-class 24GB GPU, beating the strongest sourced comparator `Y_4090_1B` on wall-clock-to-declared-capability metric `Z_days_to_capability` by threshold `T`, while preserving one-GPU compute, source/data, memory, precision, quantization, optimizer, activation, native C++/CUDA/Triton ceiling treatment, evaluation, energy, and replay constraints `C`, under budget `B`, verified by `baseline/scripts/validate_4090_ceiling.py`, `baseline/scripts/verify_completion.py`, and the family-specific receipts `V`, producing verdict `PASS`, `FAIL`, or `INVALID-RUN`.

## Required Receipts

- deterministic ceiling calculation: `receipts/4090-ceiling-calculation-2026-06-29.json`;
- local short throughput probe: `receipts/4090-throughput-probe-2026-06-29.json`;
- family validator: `receipts/4090-ceiling-validation-2026-06-29.json`;
- native/Triton GEMM probe and parser: `receipts/4090-native-kernel-probe-from-scratch.json`, `receipts/4090-native-kernel-probe-from-scratch-parse.json`.

## Baseline Verdict

SINGLE_4090_ENGINEERING_BASELINE_SURFACE_READY for the mapped-and-implemented ceiling surface.

The absolute ceiling is not years. For a 1B active-parameter run, days-scale is mathematically credible at 5B-20B tokens if the stack sustains 25-100 TFLOP/s and fits memory with activation and optimizer-state engineering. A 30B-token run is an aggressive practical ceiling. A 50B-token run is an extreme best-case ceiling. Meaningful broad foundation capability is not guaranteed by any of these compute envelopes and must be tested against a frozen target.

This is not a governed Ember training result, not a proof that Ember beats the baseline, not operator acceptance, and not overall `/baseline` completion. A future completion attempt must execute or otherwise replay this engineering surface under locked data, target, memory, throughput, energy, and parser receipts.

Representative LM-loss probes now exist for both lanes: `receipts/4090-full-stack-lm-loss-probe-from-scratch.json` and `receipts/4090-full-stack-lm-loss-probe-pretraining-equivalent.json`, with parser PASS receipts. They execute token embeddings, all 19 layers, tied LM-head logits over vocab size 32768, cross-entropy, backward, and AdamW at sequence length 2048. Observed lower-bound throughput was about 29.6 TFLOP/s, still below the 50.98 sustained TFLOP/s requirement. These receipts replace the hidden-state surrogate limitation for bounded step telemetry, but they are not real-data long-run training receipts and not C1 completion.

Throughput-gap validation now exists at `receipts/4090-training-throughput-gap-validation-2026-06-30.json`. It mechanically checks the current full-stack LM-loss measurements against the locked required sustained TFLOP/s and preserves the result as a hard C1 non-completion gate until a replacement measured full-stack long-run receipt or stronger native/lower-level ceiling receipt closes the gap without weakening the data, memory, evaluation, and replay constraints.

Seeded real-token LM-loss probes now exist at `receipts/4090-real-data-lm-loss-probe-from-scratch.json` and `receipts/4090-real-data-lm-loss-probe-pretraining-equivalent.json`, validated by `receipts/4090-real-data-lm-loss-validation-2026-06-30.json`. They run the same full 1B stack on a sha-verified separator-free window from pinned token shard `v0-00000.bin`; they are still one-step bounded telemetry, not multi-step stability, checkpoint/resume, or long-run training.

Bounded checkpoint/resume evidence now exists at `receipts/4090-real-data-checkpoint-resume-probe-pretraining-equivalent.json`, validated by `receipts/4090-checkpoint-resume-validation-2026-06-30.json`. It saves, hashes, reloads, and deletes a model+optimizer checkpoint between real-token full-stack steps; it is not a long-run checkpoint cadence or recovery receipt.

Bounded checkpoint-cadence evidence now exists at `receipts/4090-real-data-checkpoint-cadence-probe-pretraining-equivalent.json`, validated by `receipts/4090-checkpoint-cadence-validation-2026-06-30.json`. It records two streamed real-token model+optimizer checkpoint save/hash/reload/delete events over four steps, with checkpoint overhead dominating elapsed time; it is still not a long-run checkpoint policy, recovery, evaluation, or throughput-completion receipt.

Bounded eval-accounting evidence now exists at `receipts/4090-real-data-eval-accounting-probe-pretraining-equivalent.json`, validated by `receipts/4090-eval-accounting-validation-2026-06-30.json`. It records no-grad tied-LM-head eval loss and timing on two additional streamed real-token windows after bounded training, with eval time included in total elapsed; it is still not a full external evaluation suite, recovery accounting, or completion receipt.

Bounded recovery-accounting evidence now exists at `receipts/4090-real-data-recovery-accounting-probe-pretraining-equivalent.json`, validated by `receipts/4090-recovery-accounting-validation-2026-06-30.json`. It records checkpoint save/hash/reload/delete plus post-recovery streamed train/eval loss and timing, with recovery time included in total elapsed; it is still not a long-run recovery policy, full external evaluation suite, or completion receipt.

Bounded integrated policy evidence now exists at `receipts/4090-integrated-policy-probe-pretraining-equivalent.json`, validated by `receipts/4090-integrated-policy-validation-2026-06-30.json`. It combines 8 streamed real-token train steps, two model+optimizer checkpoint cadence events, two no-grad eval windows, and a post-recovery train/eval cycle in one receipt; checkpoint/recovery overhead drops measured throughput to 2.27 TFLOP/s, so it is still not long-run throughput or completion.

Bounded multi-step stability evidence now exists at `receipts/4090-real-data-multistep-stability-probe-pretraining-equivalent.json`, validated by `receipts/4090-multistep-stability-validation-2026-06-30.json`. It records four same-window real-token optimizer steps with finite losses and 47.67 lower-bound TFLOP/s, still below the locked 50.98 TFLOP/s requirement and not long-run throughput.

Bounded steady-state throughput evidence now exists at `receipts/4090-real-data-steady-state-throughput-probe-pretraining-equivalent.json`, validated by `receipts/4090-steady-state-throughput-validation-2026-06-30.json`. It records 16 same-window real-token optimizer steps at 61.40 lower-bound TFLOP/s, above the locked 50.98 TFLOP/s arithmetic threshold; it is still not varied-data, dataloader-inclusive, checkpoint-cadenced, evaluated, or long-run throughput.

Bounded varied-window throughput evidence now exists at `receipts/4090-real-data-varied-window-throughput-probe-pretraining-equivalent.json`, validated by `receipts/4090-varied-window-throughput-validation-2026-06-30.json`. It records 16 unique real-token shard windows at 60.16 lower-bound TFLOP/s, above the locked 50.98 TFLOP/s arithmetic threshold; it is still not dataloader-inclusive, checkpoint-cadenced, evaluated, recovered, or long-run throughput.

Bounded streamed-window throughput evidence now exists at `receipts/4090-real-data-streamed-window-throughput-probe-pretraining-equivalent.json`, validated by `receipts/4090-streamed-window-throughput-validation-2026-06-30.json`. A longer 128-window streamed evidence packet now also exists at `receipts/4090-real-data-streamed-128-window-throughput-probe-pretraining-equivalent.json`, validated by `receipts/4090-streamed-128-window-throughput-validation-2026-06-30.json`: it executes 128 unique real-token windows at the full 1B stack shape with per-step loader timing included, records 25.009s elapsed, and measures a 64.638 TFLOP/s lower bound against the 50.980 TFLOP/s requirement. This strengthens dataloader-inclusive throughput evidence only; it is still not full-shard dataloader coverage, checkpoint-cadenced, evaluated, recovered, or days-scale long-run throughput.

Bounded power-sampled throughput evidence now exists at `receipts/4090-real-data-streamed-128-window-power-sampled-probe-pretraining-equivalent.json`, `receipts/4090-power-sampled-128-window-throughput-2026-06-30.json`, and `receipts/4090-power-sampled-128-window-validation-2026-06-30.json`. It wraps a 128-window streamed real-token full-stack C1 run with nvidia-smi samples, records 94 samples over 31.966s, measures 64.551 lower-bound TFLOP/s against the 50.980 TFLOP/s requirement, and estimates 9,898.822 joules / 2.750 Wh for the bounded child-wall-clock probe. This supports the energy-accounting method only at bounded probe scale; it is not full-run energy accounting, not data-prep/eval/recovery/packaging energy, and not completion.

Bounded policy-amortized evidence now exists at `receipts/4090-policy-amortized-256-window-probe-pretraining-equivalent.json`, `receipts/4090-policy-amortized-256-window-power-2026-06-30.json`, and `receipts/4090-policy-amortized-256-window-validation-2026-06-30.json`. It records 256 streamed real-token train windows, checkpoint cadence at 128 and 256 steps, four eval windows, one recovery cycle, and 167 nvidia-smi samples over 97.353s. With checkpoint/eval/recovery overhead included, measured lower-bound throughput is 36.084 TFLOP/s against the 50.980 TFLOP/s requirement, with 21,311.846 joules / 5.920 Wh around child wall clock. This is a policy-overhead gap receipt, not completion; future C1 completion must close this measured gap or supersede it with a stronger native/lower-level receipt under the same accounting constraints.

Bounded policy-optimized evidence now exists at `receipts/4090-policy-optimized-1024-window-probe-pretraining-equivalent.json`, `receipts/4090-policy-optimized-1024-window-power-2026-06-30.json`, and `receipts/4090-policy-optimized-1024-window-validation-2026-06-30.json`. It records 1024 streamed real-token train windows, one checkpoint at step 1024, four eval windows, one recovery cycle, and 397 nvidia-smi samples over 232.009s. With checkpoint/eval/recovery overhead included, measured lower-bound throughput is 57.390 TFLOP/s against the 50.980 TFLOP/s requirement, with 80,386.935 joules / 22.330 Wh around child wall clock. This closes the bounded policy-overhead throughput gap for the 1024-window pretraining-equivalent probe only; data-hygiene PASS, full external eval contamination PASS, days-scale run evidence, and overall completion remain open.

C1 data-governance evidence now exists at `receipts/4090-data-governance-2026-06-30.json`, validated by `receipts/4090-data-governance-validation-2026-06-30.json`. It pins a 6.973B-content-token Ember v0 substrate with tokenizer/shard hashes, marks the 5B pretraining-equivalent token floor ready, and records a 3.026B-token shortfall for the locked 10B from-scratch lane. It is not a dedupe/contamination pass, dataloader-inclusive long-run throughput receipt, checkpoint cadence receipt, or completion receipt.

C1 data-hygiene audit evidence now exists at `receipts/4090-data-hygiene-audit-2026-06-30.json`, validated by `receipts/4090-data-hygiene-validation-2026-06-30.json`. It preserves source-pin, byte-stability, and task-fold duplicate evidence while marking corpus-wide exact dedupe, near-duplicate/MinHash dedupe, eval contamination, and policy-threshold receipts as missing C1 blockers. It is not a dedupe PASS, not a contamination PASS, and not C1 completion.

C1 exact-document dedupe now has real scan evidence: `receipts/4090-exact-dedupe-scan-2026-06-30.json` plus `receipts/4090-exact-dedupe-validation-2026-06-30.json` scan all 4,236,458 separator-delimited documents across the pinned 26-shard token stream and find zero exact duplicate documents. This does not cover near-duplicate/MinHash dedupe or eval contamination.

C1 data-hygiene policy thresholds are now locked by `receipts/4090-data-hygiene-policy-thresholds-2026-06-30.json` and validated by `receipts/4090-data-hygiene-policy-validation-2026-06-30.json`. They define the exact-dedupe, near-duplicate/MinHash, and eval-contamination pass rules before the remaining scans run.

C1 local heldout contamination now has exact 32-token scan evidence: `receipts/4090-local-heldout-contamination-scan-2026-06-30.json` plus `receipts/4090-local-heldout-contamination-validation-2026-06-30.json` scan 753 heldout token patterns over the full pinned token stream and find zero exact hits. Full eval-suite and normalized-span contamination scans remain required.

C1 bounded near-duplicate/MinHash sample evidence now exists: `receipts/4090-near-duplicate-minhash-sample-2026-06-30.json` and `receipts/4090-near-duplicate-minhash-sample-validation-2026-06-30.json`. The deterministic 50,000-document sample was drawn from 3,808,603 eligible documents across the full 4,236,458-document pinned shard stream, found 25 above-threshold crossing pairs at the 0.80 Jaccard policy threshold, and observed max exact Jaccard 0.914169. This is problem-finding evidence, not a pass: full-corpus near-duplicate remediation and a corpus-wide PASS receipt remain required.

C1 near-duplicate sample remediation evidence now exists: `receipts/4090-near-duplicate-sample-remediation-2026-06-30.json` and `receipts/4090-near-duplicate-sample-remediation-validation-2026-06-30.json`. The packet clusters the 25 above-threshold sample crossing pairs into 4 connected components, keeps the lowest deterministic document per component, and identifies 24 sample documents / 38,772 tokens for exclusion. This is sample remediation only; full-corpus MinHash scanning, full-corpus exclusion materialization, and post-remediation PASS validation remain required.

C1 targeted near-duplicate expansion evidence now exists: `receipts/4090-near-duplicate-targeted-expansion-2026-06-30.json` and `receipts/4090-near-duplicate-targeted-expansion-validation-2026-06-30.json`. The run rescanned all 4,236,458 pinned documents, compared 3,808,603 eligible documents to the 4 discovered cluster representatives, and materialized 1,668 exclusion documents covering at least 2,949,980 tokens. This expands the discovered clusters across the full corpus, but it is still not an all-pairs full-corpus near-duplicate PASS.

C1 targeted near-duplicate exclusion materialization now exists: `fragments/c1-near-duplicate-targeted-exclusions-2026-06-30.jsonl`, `receipts/4090-near-duplicate-targeted-exclusion-manifest-2026-06-30.json`, and `receipts/4090-near-duplicate-targeted-exclusion-manifest-validation-2026-06-30.json`. The manifest records 1,668 hash-addressed exclusions covering a 2,949,980-token floor for the discovered clusters only. A targeted filtered-corpus view now also exists at `receipts/4090-targeted-filtered-corpus-view-2026-06-30.json`, validated by `receipts/4090-targeted-filtered-corpus-view-validation-2026-06-30.json`: it applies those exclusions as a replayable view over the pinned document stream, leaving 4,234,790 documents and a 6,974,918,778-token floor. This is still not an all-pairs near-duplicate PASS and not a binary shard rewrite.

C1 post-filter near-duplicate challenge evidence now exists: `receipts/4090-targeted-filtered-near-duplicate-sample-2026-06-30.json`, validated by `receipts/4090-targeted-filtered-near-duplicate-sample-validation-2026-06-30.json`. It rescans all 4,236,458 pinned documents, applies all 1,668 targeted exclusions before sampling, draws a deterministic 50,000-document challenge sample from the remaining 4,234,790-document view, and still finds 25 above-threshold crossing pairs with max exact Jaccard 0.955778. Deterministic challenge remediation now exists at `receipts/4090-targeted-filtered-challenge-remediation-2026-06-30.json`, validated by `receipts/4090-targeted-filtered-challenge-remediation-validation-2026-06-30.json`: it clusters those 25 crossing pairs into 14 components, identifies 25 additional challenge-sample exclusions covering 38,244 tokens, and verifies zero overlap with the existing 1,668-document targeted manifest. This proves the targeted filtered view is not enough for a C1 near-duplicate PASS; all-pairs/full-corpus remediation and pass validation remain required.

C1 cumulative near-duplicate v2 evidence now exists: `fragments/c1-near-duplicate-cumulative-exclusions-v2-2026-06-30.jsonl`, `receipts/4090-near-duplicate-cumulative-exclusion-manifest-v2-2026-06-30.json`, `receipts/4090-cumulative-filtered-corpus-view-v2-2026-06-30.json`, and `receipts/4090-cumulative-filtered-near-duplicate-sample-v2-2026-06-30.json`, with validation receipts for each. It combines the 1,668 targeted-cluster exclusions with the 25 validated post-filter challenge exclusions into 1,693 excluded documents covering a 2,988,224-token floor, materializes a replayable v2 filtered view with 4,234,765 remaining documents / 6,974,880,534 token floor, then reruns the deterministic 50,000-document challenge sample. The v2 challenge still finds 25 above-threshold crossing pairs with max exact Jaccard 0.927525, so it is stronger problem-finding evidence, not a C1 near-duplicate PASS; all-pairs/full-corpus remediation and pass validation remain required.

C1 cumulative near-duplicate v3 evidence now also exists: `fragments/c1-near-duplicate-cumulative-exclusions-v3-2026-06-30.jsonl`, `receipts/4090-cumulative-filtered-challenge-remediation-v3-2026-06-30.json`, `receipts/4090-near-duplicate-cumulative-exclusion-manifest-v3-2026-06-30.json`, `receipts/4090-cumulative-filtered-corpus-view-v3-2026-06-30.json`, and `receipts/4090-cumulative-filtered-near-duplicate-sample-v3-2026-06-30.json`, with validation receipts for each. It adds 16 exclusions from the v2 challenge crossings to the prior 1,693-document cumulative manifest, yielding 1,709 exclusions covering a 3,012,037-token floor, and materializes a replayable v3 filtered view with 4,234,749 remaining documents / 6,974,856,721 token floor. The v3 deterministic 50,000-document challenge still finds 10 above-threshold crossing pairs with max exact Jaccard 0.912172. This is measurable remediation progress, not a C1 near-duplicate PASS; all-pairs/full-corpus remediation and pass validation remain required.

C1 cumulative near-duplicate v4 evidence now exists: `fragments/c1-near-duplicate-cumulative-exclusions-v4-2026-06-30.jsonl`, `receipts/4090-cumulative-filtered-challenge-remediation-v4-2026-06-30.json`, `receipts/4090-near-duplicate-cumulative-exclusion-manifest-v4-2026-06-30.json`, `receipts/4090-cumulative-filtered-corpus-view-v4-2026-06-30.json`, and `receipts/4090-cumulative-filtered-near-duplicate-sample-v4-2026-06-30.json`, with validation receipts for each. It adds 10 exclusions from the v3 challenge crossings to the prior 1,709-document cumulative manifest, yielding 1,719 exclusions covering a 3,026,203-token floor, and materializes a replayable v4 filtered view with 4,234,739 remaining documents / 6,974,842,555 token floor. The v4 deterministic 50,000-document challenge sample found zero above-threshold crossing pairs and max exact Jaccard 0.799711. This clears this bounded challenge sample only; it is still not an all-pairs/full-corpus near-duplicate PASS, and full-corpus remediation/pass validation remain required.
C1 cumulative near-duplicate v4 full-document LSH bucket-census evidence now also exists: `receipts/4090-cumulative-filtered-lsh-bucket-census-v4-2026-06-30.json` and `receipts/4090-cumulative-filtered-lsh-bucket-census-v4-validation-2026-06-30.json`. It scans all 3,806,884 eligible v4-filtered documents for selected MinHash band 0, records 3,723,151 buckets, 28,337 collision buckets, 112,070 collision document memberships, and a max bucket size of 2,994. This is corpus-scale collision-pressure evidence for one of 16 bands only; it is still not full-band coverage, not exact all-pairs Jaccard adjudication, not a C1 near-duplicate PASS, and not overall baseline completion.
C1 cumulative near-duplicate v4 full-document LSH bucket-census coverage has expanded to bands 0, 4, and 8: `receipts/4090-cumulative-filtered-lsh-bucket-census-v4-2026-06-30.json`, `receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band4-2026-06-30.json`, and `receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band8-2026-06-30.json`, with validation receipts for each. Each scanned all 3,806,884 eligible v4-filtered documents. Band 4 records 3,726,985 buckets / 28,392 collision buckets / max bucket size 2,290; band 8 records 3,724,494 buckets / 28,593 collision buckets / max bucket size 1,296. Together this is 3 of 16 selected-band collision-pressure coverage only; it is still not full-band coverage, not exact all-pairs Jaccard adjudication, not a C1 near-duplicate PASS, and not overall baseline completion.
C1 cumulative near-duplicate v4 full-document LSH bucket-census coverage has expanded again to bands 0, 4, 8, 12, 16, and 20. The new receipts are `receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band12-2026-06-30.json`, `receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band16-2026-06-30.json`, and `receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band20-2026-06-30.json`, with validation receipts for each. Each scanned all 3,806,884 eligible v4-filtered documents. Band 12 records 3,718,516 buckets / 28,324 collision buckets / max bucket size 3,766; band 16 records 3,722,972 buckets / 28,684 collision buckets / max bucket size 2,142; band 20 records 3,716,406 buckets / 29,149 collision buckets / max bucket size 2,392. Together this is 6 of 16 selected-band collision-pressure coverage only; it is still not full-band coverage, not exact all-pairs Jaccard adjudication, not a C1 near-duplicate PASS, and not overall baseline completion.
C1 cumulative near-duplicate v4 full-document LSH bucket-census coverage has expanded to 9 of 16 bands: 0, 4, 8, 12, 16, 20, 24, 28, and 32. The new receipts are `receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band24-2026-06-30.json`, `receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band28-2026-06-30.json`, and `receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band32-2026-06-30.json`, with validation receipts for each. Each scanned all 3,806,884 eligible v4-filtered documents. Band 24 records 3,728,419 buckets / 28,292 collision buckets / max bucket size 1,761; band 28 records 3,725,146 buckets / 28,764 collision buckets / max bucket size 2,147; band 32 records 3,722,249 buckets / 28,691 collision buckets / max bucket size 2,856. Together this is 9 of 16 selected-band collision-pressure coverage only; it is still not full-band coverage, not exact all-pairs Jaccard adjudication, not a C1 near-duplicate PASS, and not overall baseline completion.
C1 cumulative near-duplicate v4 full-document LSH bucket-census coverage now spans all 16 selected bands: 0, 4, 8, 12, 16, 20, 24, 28, 32, 36, 40, 44, 48, 52, 56, and 60. The final-band receipts are `receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band36-2026-06-30.json`, `receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band40-2026-06-30.json`, `receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band44-2026-06-30.json`, `receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band48-2026-06-30.json`, `receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band52-2026-06-30.json`, `receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band56-2026-06-30.json`, and `receipts/4090-cumulative-filtered-lsh-bucket-census-v4-band60-2026-06-30.json`, with validation receipts for each. Each scanned all 3,806,884 eligible v4-filtered documents. Bands 36/40/44/48/52/56/60 respectively record 28,850 / 29,705 / 29,276 / 28,289 / 28,356 / 29,178 / 29,320 collision buckets and max bucket sizes 1,318 / 4,898 / 630 / 5,741 / 1,019 / 2,389 / 907. Across all 16 selected bands this records 460,200 observed collision buckets and max observed bucket size 5,741. This completes selected-band LSH census coverage only; exact candidate/Jaccard adjudication, remediation as needed, a replacement C1 near-duplicate PASS, and overall baseline completion remain open.
C1 cumulative near-duplicate v4 exact-adjudication preparation has begun with a materialized band-48 LSH collision-candidate index: `fragments/c1-cumulative-filtered-lsh-candidate-index-v4-band48-2026-07-01.jsonl`, receipt `receipts/4090-cumulative-filtered-lsh-candidate-index-v4-band48-2026-07-01.json`, and validation `receipts/4090-cumulative-filtered-lsh-candidate-index-v4-band48-validation-2026-07-01.json`. It covers all 3,806,884 eligible v4-filtered documents for selected band 48 and writes 28,289 collision buckets / 113,574 document memberships / 20,991,666 candidate-pair upper bound before deduplication, with max bucket size 5,741. This is a concrete candidate surface for exact Jaccard adjudication; it is not exact adjudication, not full 16-band candidate-index coverage, not a C1 near-duplicate PASS, and not overall baseline completion.





C1 local heldout exact 16-token contamination now has full pinned-shard scan evidence: `receipts/4090-local-heldout-16gram-contamination-scan-2026-06-30.json` plus `receipts/4090-local-heldout-16gram-contamination-validation-2026-06-30.json` scan 1,637 exact 16-token heldout patterns across all 6,977,868,758 stream tokens / 6,977,868,743 valid 16-token windows and find zero hits. Available eval-text normalized-span evidence now also exists at `receipts/4090-eval-text-inventory-normalized-span-scan-2026-06-30.json`, validated by `receipts/4090-eval-text-inventory-validation-2026-06-30.json`: it inventories 20 local heldout items, scans 17,912 normalized 200-character windows against checked-in local training JSONL, finds zero exact normalized-span hits, and records six imported external benchmark receipts as metadata-only raw-eval-text gaps. This strengthens local contamination evidence, but it is still not a full external eval-suite contamination PASS or token-shard/full-corpus normalized-span PASS.

C1 cumulative near-duplicate v4 band-48 candidate-index exact adjudication has begun with `receipts/4090-cumulative-filtered-lsh-candidate-index-v4-band48-adjudication-partial25-2026-07-01.json`, validated by `receipts/4090-cumulative-filtered-lsh-candidate-index-v4-band48-adjudication-partial25-validation-2026-07-01.json`. The first 25 materialized band-48 collision buckets contain 75 candidate pairs, 74 exact Jaccard computations plus 1 size-pruned impossible crossing, 17 above-threshold crossing pairs, and max exact Jaccard 0.970803. A deterministic remediation packet `receipts/4090-cumulative-filtered-lsh-candidate-index-v4-band48-adjudication-partial25-remediation-2026-07-01.json` clusters those crossings into 12 components and 14 proposed exclusions with zero overlap against the existing v4 cumulative manifest. This is problem-finding and partial remediation evidence only; full band-48 adjudication, remaining candidate coverage, follow-up manifest materialization, reruns, C1 PASS receipts, and overall baseline completion remain open.

C1 cumulative near-duplicate v5 materialization now exists from that partial band-48 remediation: `fragments/c1-near-duplicate-cumulative-exclusions-v5-2026-07-01.jsonl`, `receipts/4090-near-duplicate-cumulative-exclusion-manifest-v5-2026-07-01.json`, `receipts/4090-near-duplicate-cumulative-exclusion-manifest-v5-validation-2026-07-01.json`, `receipts/4090-cumulative-filtered-corpus-view-v5-2026-07-01.json`, and `receipts/4090-cumulative-filtered-corpus-view-v5-validation-2026-07-01.json`. The v5 view carries 1,733 cumulative exclusions / 3,039,393 excluded-token floor and leaves 4,234,725 documents / 6,974,829,365 content-token floor. This materializes the first partial band-48 remediation into the replayable training view, but it is not full band-48 adjudication, not full 16-band exact adjudication, not a C1 near-duplicate PASS, not eval-contamination evidence, and not overall baseline completion.

C1 cumulative near-duplicate v5/v6 band-48 adjudication evidence now exists: `receipts/4090-cumulative-filtered-lsh-candidate-index-v5-band48-2026-07-01.json`, `receipts/4090-cumulative-filtered-lsh-candidate-index-v5-band48-validation-2026-07-01.json`, `receipts/4090-cumulative-filtered-lsh-candidate-index-v5-band48-adjudication-partial25-2026-07-01.json`, `receipts/4090-cumulative-filtered-lsh-candidate-index-v5-band48-adjudication-partial25-validation-2026-07-01.json`, and `receipts/4090-cumulative-filtered-lsh-candidate-index-v5-band48-adjudication-partial25-remediation-2026-07-01.json`. The v5 band-48 candidate index records 28,278 collision buckets / 113,549 collision document memberships / 20,991,648 candidate-pair upper bound. Exact adjudication of the first 25 v5 candidate-index rows still finds 18 above-threshold crossing pairs with max exact Jaccard 0.975309; the remediation packet proposes 9 additional exclusions with zero overlap against v5. The applied v6 manifest/view receipts `receipts/4090-near-duplicate-cumulative-exclusion-manifest-v6-2026-07-01.json`, `receipts/4090-near-duplicate-cumulative-exclusion-manifest-v6-validation-2026-07-01.json`, `receipts/4090-cumulative-filtered-corpus-view-v6-2026-07-01.json`, and `receipts/4090-cumulative-filtered-corpus-view-v6-validation-2026-07-01.json` now carry 1,742 cumulative exclusions / 3,050,833 excluded-token floor and leave 4,234,716 documents / 6,974,817,925 content-token floor. This is direct progress against C1 near-duplicate hygiene, but it is not full band-48 adjudication, not full 16-band exact adjudication, not eval-contamination evidence, not a C1 near-duplicate PASS, and not overall baseline completion.

C1 cumulative near-duplicate v6/v7 band-48 adjudication evidence now exists: `receipts/4090-cumulative-filtered-lsh-candidate-index-v6-band48-2026-07-01.json`, `receipts/4090-cumulative-filtered-lsh-candidate-index-v6-band48-validation-2026-07-01.json`, `receipts/4090-cumulative-filtered-lsh-candidate-index-v6-band48-adjudication-partial25-2026-07-01.json`, `receipts/4090-cumulative-filtered-lsh-candidate-index-v6-band48-adjudication-partial25-validation-2026-07-01.json`, and `receipts/4090-cumulative-filtered-lsh-candidate-index-v6-band48-adjudication-partial25-remediation-2026-07-01.json`. The v6 band-48 candidate index records 28,274 collision buckets / 113,536 collision document memberships / 20,991,630 candidate-pair upper bound. Exact adjudication of the first 25 v6 candidate-index rows still finds 3 above-threshold crossing pairs with max exact Jaccard 0.978495; the remediation packet proposes 3 additional exclusions with zero overlap against v6. The applied v7 manifest/view receipts now carry 1,745 cumulative exclusions / 3,055,337 excluded-token floor and leave 4,234,713 documents / 6,974,813,421 content-token floor. This is direct progress against C1 near-duplicate hygiene, but it is not full band-48 adjudication, not full 16-band exact adjudication, not eval-contamination evidence, not a C1 near-duplicate PASS, and not overall baseline completion.
C1 cumulative near-duplicate v7/v8 band-48 adjudication evidence now also exists: `receipts/4090-cumulative-filtered-lsh-candidate-index-v7-band48-2026-07-01.json`, `receipts/4090-cumulative-filtered-lsh-candidate-index-v7-band48-validation-2026-07-01.json`, `receipts/4090-cumulative-filtered-lsh-candidate-index-v7-band48-adjudication-partial25-2026-07-01.json`, `receipts/4090-cumulative-filtered-lsh-candidate-index-v7-band48-adjudication-partial25-validation-2026-07-01.json`, and `receipts/4090-cumulative-filtered-lsh-candidate-index-v7-band48-adjudication-partial25-remediation-2026-07-01.json`. The v7 band-48 candidate index records 28,271 collision buckets / 113,530 collision document memberships / 20,991,627 candidate-pair upper bound. Exact adjudication of the first 25 v7 candidate-index rows still finds 3 above-threshold crossing pairs with max exact Jaccard 0.952118; the remediation packet proposes 2 additional exclusions with zero overlap against v7. The applied v8 manifest/view receipts now carry 1,747 cumulative exclusions / 3,058,613 excluded-token floor and leave 4,234,711 documents / 6,974,810,145 content-token floor. This is narrower crossing pressure than v6 but still blocking-gap evidence only: full band-48 adjudication, full 16-band exact adjudication, replacement near-duplicate PASS receipts, eval-contamination PASS receipts, and overall verifier PASS remain required.

C1 cumulative near-duplicate v8/v9 windowed band-48 adjudication evidence now exists: `receipts/4090-cumulative-filtered-lsh-candidate-index-v8-band48-2026-07-01.json`, `receipts/4090-cumulative-filtered-lsh-candidate-index-v8-band48-validation-2026-07-01.json`, `receipts/4090-cumulative-filtered-lsh-candidate-index-v8-band48-adjudication-partial25-skip0-2026-07-01.json`, `receipts/4090-cumulative-filtered-lsh-candidate-index-v8-band48-adjudication-partial25-skip25-2026-07-01.json`, their validation receipts, and `receipts/4090-cumulative-filtered-lsh-candidate-index-v8-band48-adjudication-window50-remediation-2026-07-01.json`. The v8 band-48 candidate index records 28,270 collision buckets / 113,527 collision document memberships / 20,991,624 candidate-pair upper bound. Exact adjudication now covers candidate-index rows 0-49: rows 0-24 find 1 crossing pair with max exact Jaccard 0.985401, and rows 25-49 find 22 crossing pairs with max exact Jaccard 0.985562. The combined deterministic remediation packet covers 50 adjudicated rows, 23 crossing pairs, 14 connected components, and 19 new exclusions with zero overlap against v8. The applied v9 manifest/view receipts now carry 1,766 cumulative exclusions / 3,087,096 excluded-token floor and leave 4,234,692 documents / 6,974,781,662 content-token floor. This is expanded band-window evidence, not full band-48 adjudication, not full 16-band exact adjudication, not eval-contamination evidence, not a C1 near-duplicate PASS, and not overall baseline completion.

C1 cumulative near-duplicate v9/v10 windowed band-48 adjudication evidence now exists: `receipts/4090-cumulative-filtered-lsh-candidate-index-v9-band48-2026-07-01.json`, `receipts/4090-cumulative-filtered-lsh-candidate-index-v9-band48-validation-2026-07-01.json`, four exact-adjudication receipts covering candidate-index rows 0-99 with validation receipts, and `receipts/4090-cumulative-filtered-lsh-candidate-index-v9-band48-adjudication-window100-remediation-2026-07-01.json`. The v9 band-48 candidate index records 28,258 collision buckets / 113,496 collision document memberships / 20,991,589 candidate-pair upper bound. Exact adjudication now covers rows 0-99: rows 0-24 find 0 crossings with max exact Jaccard 0.799622; rows 25-49 find 8 crossings with max 0.947971; rows 50-74 find 50 crossings with max 0.988074; rows 75-99 find 36 crossings with max 0.988072. The combined deterministic remediation packet covers 100 adjudicated rows, 94 crossing pairs, 30 connected components, 78 unique crossing documents, and 48 new exclusions with zero overlap against v9. The applied v10 manifest/view receipts now carry 1,814 cumulative exclusions / 3,155,898 excluded-token floor and leave 4,234,644 documents / 6,974,712,860 content-token floor. This is expanded band-window evidence, not full band-48 adjudication, not full 16-band exact adjudication, not eval-contamination evidence, not a C1 near-duplicate PASS, and not overall baseline completion.

C1 cumulative near-duplicate v10/v11 windowed band-48 adjudication evidence now exists: `receipts/4090-cumulative-filtered-lsh-candidate-index-v10-band48-2026-07-01.json`, `receipts/4090-cumulative-filtered-lsh-candidate-index-v10-band48-validation-2026-07-01.json`, five exact-adjudication receipts covering candidate-index rows 0-124 with validation receipts, and `receipts/4090-cumulative-filtered-lsh-candidate-index-v10-band48-adjudication-window125-remediation-2026-07-01.json`. The v10 band-48 candidate index records 28,236 collision buckets / 113,426 collision document memberships / 20,991,240 candidate-pair upper bound. Exact adjudication now covers rows 0-124: rows 0-24 find 0 crossings with max exact Jaccard 0.799622; rows 25-49 find 0 crossings with max 0.795349; rows 50-74 find 16 crossings with max 0.985433; rows 75-99 find 15 crossings with max 0.979626; rows 100-124 find 28 crossings with max 0.997024. The deterministic remediation packet covers 125 adjudicated rows, 59 crossing pairs, 25 connected components, 65 unique crossing documents, and 40 new exclusions with zero overlap against v10. The applied v11 manifest/view receipts now carry 1,854 cumulative exclusions / 3,221,182 excluded-token floor and leave 4,234,604 documents / 6,974,647,576 content-token floor. This is expanded band-window evidence, not full band-48 adjudication, not full 16-band exact adjudication, not eval-contamination evidence, not a C1 near-duplicate PASS, and not overall baseline completion.

C1 cumulative near-duplicate v11/v12 windowed band-48 adjudication evidence now exists: `receipts/4090-cumulative-filtered-lsh-candidate-index-v11-band48-2026-07-01.json`, `receipts/4090-cumulative-filtered-lsh-candidate-index-v11-band48-validation-2026-07-01.json`, six exact-adjudication receipts covering refreshed candidate-index rows 0-149 with validation receipts, and `receipts/4090-cumulative-filtered-lsh-candidate-index-v11-band48-adjudication-window150-remediation-2026-07-01.json`. The v11 band-48 candidate index records 28,220 collision buckets / 113,370 collision document memberships / 20,991,071 candidate-pair upper bound. Exact adjudication now covers rows 0-149 on the v11-filtered corpus: rows 0-24 find 0 crossings with max exact Jaccard 0.799622; rows 25-49 find 0 crossings with max 0.795349; rows 50-74 find 0 crossings with max 0.797549; rows 75-99 find 0 crossings with max 0.789764; rows 100-124 find 41 crossings with max 0.997024; rows 125-149 find 15 crossings with max 0.991576. The deterministic remediation packet covers 150 adjudicated rows, 56 crossing pairs, 33 connected components, 71 unique crossing documents, and 38 new exclusions with zero overlap against v11. The applied v12 manifest/view receipts now carry 1,892 cumulative exclusions / 3,250,574 excluded-token floor and leave 4,234,566 documents / 6,974,618,184 content-token floor. This is expanded band-window evidence, not full band-48 adjudication, not full 16-band exact adjudication, not eval-contamination evidence, not a C1 near-duplicate PASS, and not overall baseline completion.

C1 cumulative near-duplicate v12/v13 windowed band-48 adjudication evidence now exists: `receipts/4090-cumulative-filtered-lsh-candidate-index-v12-band48-2026-07-01.json`, `receipts/4090-cumulative-filtered-lsh-candidate-index-v12-band48-validation-2026-07-01.json`, seven exact-adjudication receipts covering refreshed candidate-index rows 0-174 with validation receipts, and `receipts/4090-cumulative-filtered-lsh-candidate-index-v12-band48-adjudication-window175-remediation-2026-07-01.json`. The v12 band-48 candidate index records 28,206 collision buckets / 113,318 collision document memberships / 20,966,617 candidate-pair upper bound. Exact adjudication covers rows 0-174: rows 0-99 find zero crossings, rows 100-124 find 14 crossings with max 0.970588, rows 125-149 find 8 crossings with max 0.972816, and rows 150-174 find 14 crossings with max 0.979872. The deterministic remediation packet covers 175 adjudicated rows, 36 crossing pairs, 28 connected components, 60 unique crossing documents, and 32 new exclusions with zero overlap against v12. The applied v13 manifest/view receipts now carry 1,924 cumulative exclusions / 3,295,935 excluded-token floor and leave 4,234,534 documents / 6,974,572,823 content-token floor. This is expanded band-window evidence, not full band-48 adjudication, not full 16-band exact adjudication, not eval-contamination evidence, not a C1 near-duplicate PASS, and not overall baseline completion.

C1 cumulative near-duplicate v14/v15 windowed band-48 adjudication evidence now exists: `receipts/4090-cumulative-filtered-lsh-candidate-index-v14-band48-2026-07-01.json`, `receipts/4090-cumulative-filtered-lsh-candidate-index-v14-band48-validation-2026-07-01.json`, nine exact-adjudication receipts covering refreshed candidate-index rows 0-224 with validation receipts, and `receipts/4090-cumulative-filtered-lsh-candidate-index-v14-band48-adjudication-window225-remediation-2026-07-01.json`. The v14 band-48 candidate index records 28,172 collision buckets / 113,224 collision document memberships / 20,960,456 candidate-pair upper bound. Exact adjudication covers rows 0-224: rows 0-149 find zero crossings with max exact Jaccard below 0.8, rows 150-174 find 3 crossings with max 0.934893, rows 175-199 find 15 crossings with max 0.975369, and rows 200-224 find 67 crossings with max 0.99239. The deterministic remediation packet covers 225 adjudicated rows, 85 crossing pairs, 18 connected components, 44 unique crossing documents, and 26 new exclusions with zero overlap against v14. The applied v15 manifest/view receipts now carry 1,978 cumulative exclusions / 3,364,087 excluded-token floor and leave 4,234,480 documents / 6,974,504,671 content-token floor. This is expanded band-window evidence, not full band-48 adjudication, not full 16-band exact adjudication, not eval-contamination evidence, not a C1 near-duplicate PASS, and not overall baseline completion.
