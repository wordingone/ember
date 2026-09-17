<!-- goal_id: EMBER-02 -->
<!-- workstream_id: EMBER-02A -->
<!-- next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember -->
# Shared up/gate FP8 v2: speed screen for a declared approximate treatment

## Question and identity

Does the promoted native FP8 pair at `b3ea8dd0504e2eb9afab4d8939577abaa1bf8e4e`
save enough inclusive component time to prioritize a subsequent learning comparison?
This document specifies a new experiment, not an amendment to v1's failed
ideal-arithmetic gate. No old source or receipt is changed. There are zero
applied training positions and zero optimizer updates in this probe.

The v1 native kernels, autograd pair, measurement functions, document reduction,
compiler binder and process/GPU guards are imported unchanged and pinned by Git
blob. The new entry point is `src/ember/governance/scripts/issue1945_fp8_pair_v2.py`.
All eight new files are checked against the exact executed commit before and
after execution. A source or environment discrepancy is a refusal.

## Separate correctness from suitability

Admission to timing requires byte-exact quantization and scale agreement,
byte-exact transpose agreement, agreement with a finite-input Ada arithmetic
model, native FP8 instructions and explicit FP32 promotion, token independence,
nonfinite-input refusal, and changed-weight/zero graph replay checks.

The finite CPU model is an independent equation transcription of MMA-Sim,
arXiv:2511.10909v1, sections IV-C/D and Table III. Ada FP8 K32 instructions use
two chained K16 fused-dot-add stages with 13 fractional alignment bits and
round-toward-zero normalization to 13 fractional bits. Each K32 result then
enters the explicit round-to-nearest FP32 addition used by the pinned kernel.
Output scale multiplications and BF16 conversion are modeled separately.
The model accepts only finite FP8 operands in its bounded domain. It is not
a general replacement for the official simulator or a learning oracle.

The original ideal-arithmetic diagnostic is computed using the exact same
v1 function and tolerance, then retained as a separate observation. A failed
ideal diagnostic never becomes an accuracy pass. A successful hardware-model
comparison permits timing only; it does not permit installation or assert
no-worse learning.

Five native small fixtures are checked completely: ordinary, zero token,
cancellation, outlier token, and unequal branches. The optional CPU empirical
replay suite must be enabled by the operator launcher: it compares the independent
model with the retained b3ea8dd0 archive's 25 observed output tensors.

Before timing each saved production layer, run all native projection arms at
full size. Independently check all quantized bytes/scales and fixed sampled
forward/input-gradient coordinates against the hardware model. Rows touch both
sides of every document boundary; channels span both branches and edge tiles.
This samples actual-size arithmetic; it is not proof of all matrix elements.
Full-output finiteness and unchanged replay checks also run in the timing harness.

## Fixed experiment

Subjects: shared layers 0, 2, 13, 22; four documents of 1024 tokens; input width
1024 and each up/gate width 2048. The original operand-file SHA256 is
`e49ad84192da8f1f82b759e9360cba18b39eca2a716550048b08d2aa1197dc76`.

A/A2 are duplicate current BF16 baselines. B is bundled BF16. C is bundled FP8
forward with BF16 input gradients. D is bundled FP8 forward and input gradients.
E is unbundled FP8 with the same scaling definitions and shared input preparation.
All arms retain the BF16 per-document weight-gradient calculation and existing
trainable parameter ownership. Only D decides this speed screen; other arms
remain diagnostics, not post-hoc replacement winners.

Use the unchanged v1 captured measurement functions: two invocations per graph,
24 rotated/alternating arm-order rounds, three warm replays before each timing,
separate graph pools, CUDA-event elapsed time per invocation. No profiler is
active. No GPU clocks or power limits are changed.

The projection region includes pair forward/input-gradient calculation, all
quantization and weight refresh, packing, both required layouts and allocation.
The complete block also includes SiLU, elementwise multiplication, the unchanged
down projection, and all block input/weight gradients. No optimizer is invoked;
refresh is charged once per measured pair invocation. Compilation and capture
are setup, not part of steady-state timing; cache paths and codegen are retained.

Retain the prospective component thresholds previously specified: every layer
must save at least 20% in D's projection region; each full block must improve by
more than its duplicate-baseline fractional drift; drift must be <=2% in both
regions on every layer. Duplicate drift is a diagnostic, NOT a confidence interval.
A gain in one layer cannot hide a regression or noisy result in another.

Results are `SPEED_JUSTIFIES_LEARNING_COMPARISON`, `NO_COMPONENT_GAIN`,
`TIMING_INCONCLUSIVE`, `IMPLEMENTATION_CHECK_FAILED`, or `REFUSED_OR_FAILED`.
The first is prioritization evidence only. Every result has
`learning_qualified=false` and `trainer_integration_authorized=false` in its
verdict. The existing training/learning/evaluation gates are unchanged.
A sum of sampled layer times is not a measured training step or an 80k claim.

## Resources and evidence

Native Windows, torch 2.10.0+cu126, Triton 3.5.0, CUDA 12.6, exactly one visible
RTX 4090. Acquire the existing GPU lock before CUDA imports. Require 6 GiB free
and limit the PyTorch allocator to 4 GiB, exactly as v1. This is not a limit on
all driver/JIT allocations and not the complete training memory governor.
The outer owned-process limit is 600 seconds for this GPU run. An error is not
retried, thresholds are never adjusted automatically, and output is create-only.
All caches and outputs use a new external B-drive directory; nothing writes
mutable state into the checkout. Small fixture and sampled tensors, unchanged
ideal diagnostics, native codegen, raw timing rounds, source pins, memory peaks
and result status are retained. An external timeout can leave only partial
artifacts and the owned-process terminal record; that is not successful timing.

The operator first runs CPU tests (including historical tensor replay), freezes
the eight added files, pushes with existing hooks enabled, and then requests one
v2 GPU speed run. This probe never launches v1 with its failed gate disabled.

## Primary references

MMA-Sim paper: https://arxiv.org/html/2511.10909v1
Official simulator source for comparison of the specified arithmetic:
https://github.com/microsoft/MMA-Sim/tree/aab7f2ae9f06ffbee1e7e86cb21b708e4c6f9254
The native kernels and captured-region definitions are the pinned Ember v1
sources at the baseline commit above. No external simulator package is required.
