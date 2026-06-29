# Single-4090 Foundation-Model Ceiling V0

Status: DRAFT. No Ember speed claim is granted.
Claim family: C1-4090-1B.
Hardware target: one RTX 4090-class 24GB GPU.

## Question

What is the fastest honest path by which an individual could train or pretrain-equivalent-train a >=1B active-parameter foundation-model-scale system on one RTX 4090 in days rather than years?

Default days-scale threshold from the goal: <=14 calendar days wall-clock.

## Compute Floor

Use the common dense-transformer training estimate:

```text
training_flops ~= 6 * active_parameters * trained_tokens
```

For 1B active parameters:

| Token budget | Approx FLOPs | Days at 50 TFLOP/s | Days at 100 TFLOP/s | Days at 150 TFLOP/s | Days at 200 TFLOP/s |
|---:|---:|---:|---:|---:|---:|
| 5B | 3.0e19 | 6.9 | 3.5 | 2.3 | 1.7 |
| 10B | 6.0e19 | 13.9 | 6.9 | 4.6 | 3.5 |
| 20B | 1.2e20 | 27.8 | 13.9 | 9.3 | 6.9 |
| 30B | 1.8e20 | 41.7 | 20.8 | 13.9 | 10.4 |

Implication: a 1B/20B-token run needs about 99 TFLOP/s sustained end-to-end to fit <=14 days. A 1B/30B-token run needs about 149 TFLOP/s sustained end-to-end to fit <=14 days.

## Memory Feasibility

1B dense parameters are not automatically impossible on 24GB, but the optimizer and activation stack decide whether the run is practical.

Approximate memory components:

- bf16 weights: ~2 GB per 1B params;
- bf16 gradients: ~2 GB;
- AdamW moments in fp32: ~8 GB;
- fp32 master weights if used: ~4 GB;
- activations, attention buffers, KV-like intermediates, dataloader staging, and fragmentation: variable and often decisive.

Likely required stack for 24GB:

- activation checkpointing or selective recompute when needed;
- fused/chunked cross entropy;
- memory-efficient attention;
- careful microbatching and gradient accumulation;
- optimizer-state reduction, Muon/AdamW split, 8-bit states, or CPU/NVMe offload if the baseline permits;
- no hidden multi-GPU or hosted compute.

## Capability Boundary

A days-scale 1B run is not automatically a meaningful foundation model. The claim must declare:

- active trainable parameter count;
- token budget;
- data mixture and contamination/dedupe checks;
- training type: from scratch, continued pretraining, distillation, retrieval-augmented, adapter-only, or other;
- capability target and evaluation suite;
- wall-clock inclusions and exclusions.

## First Required Short Job

Before any long training job:

1. static memory estimate for the exact config;
2. tiny shape/import check;
3. <=10 minute GPU throughput probe with receipt;
4. projection against <=3d, <=7d, and <=14d thresholds;
5. compute-spend packet if a long run can change the verdict.

## Verdict Rule

PASS requires a governed run or externally sufficient evidence showing the declared >=1B active-parameter training target reaches its capability threshold within the declared days-scale budget on one RTX 4090-class GPU.

FAIL if the locked run is valid but misses time, token, capability, memory, or preserved-functionality thresholds.

INVALID-RUN if the run violates protocol, hides compute, omits receipts, cannot verify parameter accounting, or lacks parser output.

Current verdict: NOT RUN.
