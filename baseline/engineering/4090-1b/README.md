# Single-4090 >=1B Engineering Baseline

This directory is the engineered surface for `single_4090_ge_1b_foundation_ceiling`.

The theory report answers what the ceiling is. This directory turns that ceiling into a replayable object Ember must beat: locked configs, an environment contract, a dry-run/train harness, and a receipt parser.

## Files

- `environment.json` records the hardware/software and receipt contract.
- `configs/from_scratch_1b_4090.json` locks the from-scratch >=1B path.
- `configs/pretraining_equivalent_1b_4090.json` locks the pretraining-equivalent path.
- `train_1b_4090.py` validates the config, computes exact active/trainable parameter counts analytically, estimates memory and TFLOP requirements, and emits receipts. Non-dry-run execution requires explicit data, output, and capability target arguments.
- `parse_receipts.py` converts harness receipts into mechanical PASS/INVALID verdicts for the engineering surface.
- `full_stack_step_probe_4090.py` runs a bounded all-layer 1B stack step on CUDA and emits a non-completion telemetry receipt.
- `full_stack_lm_loss_probe_4090.py` runs token embeddings, all layers, tied LM-head logits, cross-entropy, backward, and optimizer step at the locked C1 shape.
- `native_kernel_probe_4090.py` compares PyTorch matmul with a simple Triton GEMM at locked transformer shapes and records native toolchain availability.

## Dry-Run Commands

From the repository root:

```powershell
python baseline\engineering\4090-1b\train_1b_4090.py --config baseline\engineering\4090-1b\configs\from_scratch_1b_4090.json --receipt baseline\receipts\4090-engineering-from-scratch-dry-run.json --dry-run
python baseline\engineering\4090-1b\parse_receipts.py --receipt baseline\receipts\4090-engineering-from-scratch-dry-run.json --out baseline\receipts\4090-engineering-from-scratch-parse.json
```

For a local workspace mirror:

```powershell
python state\ember-baseline\engineering\4090-1b\train_1b_4090.py --config state\ember-baseline\engineering\4090-1b\configs\from_scratch_1b_4090.json --receipt state\ember-baseline\receipts\4090-engineering-from-scratch-dry-run.json --dry-run
python state\ember-baseline\engineering\4090-1b\parse_receipts.py --receipt state\ember-baseline\receipts\4090-engineering-from-scratch-dry-run.json --out state\ember-baseline\receipts\4090-engineering-from-scratch-parse.json
```

## Non-Dry-Run Gate

A non-dry-run must provide:

- token data path;
- checkpoint/output directory;
- frozen capability target;
- dedupe and contamination receipts;
- long-job compute-spend packet;
- memory and throughput receipts at representative shape;
- parser verdict.

A dry-run parser PASS does not complete the overall baseline. It proves the engineered surface exists and is mechanically inspectable.

## Native Ceiling Rule

PyTorch is the reproducible reference implementation, not the automatic 4090 ceiling. Completion of C1 requires native C++/CUDA/Triton/custom-kernel ceiling treatment: either lower-level receipts show no material remaining ceiling gap, or the result is explicitly bounded as a PyTorch-framework reference baseline and cannot complete the absolute single-4090 ceiling.

## Full-Stack Step Probe

The full-stack step probe executes all configured transformer layers at the locked C1 shape and emits `FULL_STACK_STEP_PROBE_NOT_COMPLETION`. Parser PASS validates bounded telemetry only; it is not a long-run training receipt and not a family completion claim.

## Native Kernel Probe

Replay command used for the current receipt:

```powershell
$env:CC='C:\msys64\mingw64\bin\cc.exe'; $env:PATH=$env:PATH + ';C:\msys64\mingw64\bin'
& 'C:\Program Files\Python310\python.exe' baseline\engineering\4090-1b\native_kernel_probe_4090.py --config baseline\engineering\4090-1b\configs\from_scratch_1b_4090.json --receipt baseline\receipts\4090-native-kernel-probe-from-scratch.json --capability-target c1_native_kernel_probe --warmup 3 --iters 10
& 'C:\Program Files\Python310\python.exe' baseline\engineering\4090-1b\parse_receipts.py --receipt baseline\receipts\4090-native-kernel-probe-from-scratch.json --out baseline\receipts\4090-native-kernel-probe-from-scratch-parse.json
```

Current result: PyTorch tuned matmul measured about 138-155 TFLOP/s on the locked GEMM shapes, while the simple Triton kernel measured about 45-49 TFLOP/s with relative BF16 error below 0.5%. This proves the native path is measurable and bounded for this microbench, but it does not exhaust fused attention/backward/optimizer/native C++ possibilities and does not complete C1.

## Full-Stack LM-Loss Probe

The LM-loss probe executes all configured layers at sequence length 2048 with tied LM-head logits over vocab size 32768, cross-entropy, backward, and AdamW. Current receipts exist for both from-scratch and pretraining-equivalent lanes. They observed about 29.6 lower-bound TFLOP/s against the locked 50.98 TFLOP/s requirement, with about 10.61GB reserved. This is representative LM-loss telemetry, not a real-data long-run training receipt and not family completion.

The same probe also supports real-token mode via `--token-shard-dir`. Current real-data receipts validate a seeded one-step run on a sha-verified separator-free pinned shard window for both lanes. This removes the random-token limitation for bounded telemetry only; it is not multi-step stability, checkpoint/resume, or long-run completion.

The probe also supports `--checkpoint-resume-probe`, which performs bounded model+optimizer checkpoint save/hash/reload and a post-resume real-token step. The current checkpoint receipt is supporting mechanics evidence only, not long-run checkpoint cadence or completion.

The probe also supports `--checkpoint-cadence-probe`, which performs repeated model+optimizer checkpoint save/hash/reload/delete events at a fixed step interval while streamed real-token training continues. The current cadence receipt records two checkpoint events over four streamed steps and exposes the checkpoint overhead; it is not a long-run checkpoint policy, recovery, or completion receipt.

The probe also supports `--eval-accounting-probe`, which runs no-grad tied-LM-head evaluation on additional streamed real-token windows after bounded training and includes eval time in total elapsed. The current eval receipt is accounting evidence only, not a full external evaluation suite or completion receipt.

The probe also supports `--recovery-accounting-probe`, which saves a model+optimizer checkpoint, reloads fresh state, and runs post-recovery streamed train/eval windows with recovery time included in total elapsed. The current recovery receipt is accounting evidence only, not a long-run recovery policy or completion receipt.

A bounded four-step same-window real-token stability receipt also exists. It records the loss sequence and throughput for repeated optimizer steps, but it is not full-data coverage, convergence, or long-run completion.

A bounded 16-step same-window steady-state throughput receipt also exists. It clears the arithmetic TFLOP/s threshold for the narrow probe, but does not include varied-data streaming, checkpoint cadence, evaluation, recovery, or long-run wall-clock accounting.

A bounded 16-step varied-window real-token throughput receipt also exists. It uses 16 unique sha-pinned shard windows and clears the arithmetic TFLOP/s threshold, but it is still not dataloader-inclusive, checkpoint-cadenced, evaluated, recovered, or long-run wall-clock accounting.

A bounded 16-step streamed-window real-token throughput receipt also exists. It loads each memmap shard window and creates the GPU tensors inside the timed step, clearing the arithmetic TFLOP/s threshold with loader timing included. It is still not full-shard dataloader coverage, checkpoint-cadenced, evaluated, recovered, or long-run wall-clock accounting.
