# #1945 shared up/gate FP8 pair, v1

Status: source implementation for a standalone experiment; not installed in any trainer.
Baseline source: `edc200bef9e459cb41aea0ac6a1016a8b07211e4`.
Operand SHA256: `e49ad84192da8f1f82b759e9360cba18b39eca2a716550048b08d2aa1197dc76`.
Approved question: does projection-family reuse make FP8 forward plus input gradients economical while retaining the original document-wise BF16 weight-gradient rule?

## Scope and boundaries

The four saved shared subjects are layers 0, 2, 13 and 22. Each has four 1024-row documents, hidden width 1024, up/gate width 2048, and BF16 weights. No expert, qkv, output-head or whole-trainer change is present. All outputs are component evidence with zero applied tokens and zero optimizer updates. No existing receipt is rewritten.

No claim of BF16 bitwise equivalence, no-worse learning, route stability or 80k qualification is made. The CPU oracle is not a CUDA oracle for historical BF16 reductions. The former document-dW experiment remains negative and independent.

## Arithmetic

For up and gate weights `Wu, Wg`, stack their output rows to form `W = [Wu; Wg]`.
`[U,G] = X W^T`; `dX = [Du,Dg] W`. Bundling changes floating-point reduction structure even before FP8.

Forward scales: one per token row of X and one per output row of W. Each nonzero scale is `max(abs(row)) / 448`, clamped below by the smallest positive normal FP32 value, 2^-126. Zero rows use scale 1. Values are divided in FP32, clamped to [-448,448], rounded to E4M3, and stored. No document/batch-wide activation maximum is used.

Backward preparation: form `E = [Du,Dg] * weight_channel_scales` in FP32 while directly packing the FP8 destination. Quantize each E row to E5M2 with max 57344 and the same zero/floor rule. Compute `dX = row_scale(E) * (QE @ QW)` using the same quantized weight bytes as forward. D uses one reduction; E uses two FP32 partials, then adds and scales once before BF16 storage. E therefore does not introduce separate BF16 rounding of each branch; its two FP32 reductions are still a different order from D.

The CUDA kernels use explicit FP8 operands and FP32 dot outputs. They do not select BF16 on failure. `max_num_imprecise_acc=0` is specified, but it is not represented as a guarantee of Hopper-style accumulation behavior on Ada. Emitted FP8 MMA instructions and independent numerical checks decide whether the actual implementation is usable.

The original BF16 x, Du and Dg go to `ember_v0_document_reduction.reduce_weight_gradient` independently for Wu and Wg with descending document order. FP8 outputs change subsequent arriving gradients, so BF16 weight-gradient arithmetic does NOT imply unchanged updates.

## Layout and lifetime

One row-wise weight quantization writes the packed forward shadow. A tiled transpose moves those exact FP8 bytes into the backward layout; it does not requantize. D/E maintain both layouts. C needs only the forward FP8 layout plus a bundled BF16 matrix for its BF16 dgrad. B needs only the BF16 bundle.

The bundled forward writes separate contiguous U and G output buffers directly. The native backward preparation reads existing Du and Dg and packs scaled E directly; there is no intermediate BF16 concatenation for D/E.

Every measured invocation includes preparation and refresh. This deliberately charges one full refresh per pair use, corresponding to one use per applied update in the proposed future trainer. Existing owner Parameters are never replaced. The probe never calls an optimizer. Its test weights are saved-operand clones, not live model/checkpoint weights.

`ShadowLease` is a host-boundary guard with an explicit generation. Python is not rerun during graph replay. A future trainer would need to bracket replay and propagate optimizer generations; this package does not pretend that integration already exists. The probe instead includes refresh in each captured callable and tests that replay observes changed BF16 weights.

## Fixed arms

| Arm | Forward | Input gradient | Weight gradient |
|---|---|---|---|
| A/A2 | Current two BF16 projections | Current separate BF16 branches | Current descending document reduction |
| B | Bundled BF16 | Bundled BF16 | Current rule |
| C | Bundled E4M3 | Bundled BF16 | Current rule |
| D | Bundled E4M3 | Bundled E5M2 x E4M3, absorbed scales | Current rule |
| E | Two FP8 projections, sharing X quantization | Two FP8 partials with the same joint gradient scale as D | Current rule |

B measures bundling plus any physical packing/copy cost. C adds forward quantization. D adds backward quantization and its second weight layout. D versus E measures the bundled-versus-separate matrix execution with matched scaling definitions. E is NOT a straw-man wrapper that redundantly quantizes the shared activation twice.

## Two explicit native stages

1. `--phase capability` (default): small native FP8 quantization, dual-layout, FP64-product oracle, mixed-format MMA, token-locality, poisoned-input refusal, and captured changed-weight/zero replay tests. No saved-subject throughput claim. This stage still pins the real operand file and source.
2. `--phase full`: reruns the fixed capability checks then evaluates all four real saved shared subjects. This is a different explicitly requested run with new custody, not an automatic retry of a failed test.

A capability failure has no performance verdict. Do not modify numerical margins after seeing it. Correct an implementation defect in a new source commit, retaining the refusal.

## Measurements and screens

Two regions are measured, with independent captured graphs:
- projection region: pair forward + pair input gradient + all applicable weight refresh, using fixed BF16 arriving gradients reconstructed from the current shared block;
- complete shared block: pair forward, SiLU, multiply, unchanged down projection, all input/weight gradients, and applicable refresh.

Both include allocations, layout changes and refresh within the captured callable. Two complete invocations per graph; three warm replays before each timed graph; 24 fixed rounds using rotated and alternating-direction orders of A/A2/B/C/D/E. Graph pools are separate. No numerical checks or host synchronizations occur inside the timed graph. Compilation/initial capture is excluded from steady-state timing, not represented as free setup for deployment.

Local numerical diagnostics compare every full-block output and gradient to A without assigning a learning margin. A cancellation norm ratio is reported separately. A real shared subject is not evidence for all invocations or a complete training trajectory.

The independent native dot oracle permits one BF16 ULP plus `1e-6 * sum(abs(quantized products))` after scales. This is a declared implementation-accuracy envelope, not a no-worse-learning threshold. Byte-level quantizers and the transpose must match the independent CPU definitions exactly on the specified fixtures.

The prospective COMPONENT screen for D requires all four subjects to pass implementation checks, each projection region to save at least 20%, and each full block to improve by more than its duplicate-baseline fractional drift. If either region's A/A2 drift exceeds 2% in any subject, timing is inconclusive. This duplicate control is a diagnostic, NOT a confidence interval. Every other arm and all raw rounds remain in the receipt, including negatives. The screen is NOT a choice of the fastest post-hoc arm.

Possible results: `NATIVE_CAPABILITY_PASSED`, `COMPONENT_SCREEN_PASSED`, `NO_COMPONENT_GAIN`, `TIMING_INCONCLUSIVE`, `IMPLEMENTATION_CHECK_FAILED`, or a `REFUSED_OR_FAILED` execution envelope. All have `learning_qualified=false` / no integration authority. Exit 2 is a completed negative/inconclusive component verdict; exit 1 is refusal/failure. No rerun-to-pass or threshold relaxation.

## Resources and custody

Native Windows; torch `2.10.0+cu126`; Triton `3.5.0`; CUDA `12.6`; one visible RTX 4090, capability 8.9. The existing GPU lock is required; no guessed lock path. Require 6 GiB free before allocation and cap this process's PyTorch allocator at 4 GiB. The outer owned-process timeout is finite (120 seconds CPU tests; 600 seconds capability; 600 seconds full probe). These are process safety ceilings, not runtime predictions.

PyTorch's allocator fraction does not limit all driver/JIT allocations; this component probe is not the full campaign's resource governor. It imports the existing compiler binder. All caches, receipts and temporary compilation files go to a new B: custody directory. Full-probe peak allocated and reserved bytes are reported.

The runner requires an exact full commit SHA, a clean tracked tree and a descendant of the baseline. Dependencies are pinned by Git blob; every experiment file is checked against the frozen commit with the existing CRLF-checkout allowance. Source binding is checked again after execution. Results are create-only JSON; PTX is retained for actually executed kernel specializations. An external kill can leave partial artifacts without result.json; the owned-process terminal is then authoritative for cleanup, not a successful experiment.

## CPU verification command

From the repository root, through the existing owned launcher:

```powershell
python -B .\src\ember\governance\scripts\owned_process.py --timeout-seconds 120 -- python -B -m pytest --noconftest -o "addopts=" -q -p no:cacheprovider .\src\ember\governance\scripts\tests\test_issue1945_fp8_pair_v1.py
```

Before any GPU execution: pass native CPU checks, review and freeze the added files into a commit, and preserve the previous negative result. No hook bypass is part of this package.

## Sources

The current decoder and document reduction at the baseline commit define the reference arithmetic. External API references: Triton 3.5.0 `python/triton/language/semantic.py` (supported FP8 operand combinations); Triton `language.dot` documentation (FP32 dot output); NVIDIA PTX ISA MMA instructions (SM89 FP8 instruction forms). Hardware and learning behavior still require native execution.
