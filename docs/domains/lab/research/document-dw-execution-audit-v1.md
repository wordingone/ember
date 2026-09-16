# #1945 — document weight-gradient execution audit, v1

## Question and scope

Does the existing grouped BF16 weight-gradient candidate remain exact and faster
when it must rearrange its inputs on every call, and when both paths run inside
CUDA graphs? This is a measurement repair, not a new kernel or trainer treatment.
The attention experiment at `a44c2ef2c76d492578fe7252d5855414b4a4d762` and shared
experiment at `ebe129f0383c56010f9c8eab2946c10e1013f5c4` retain their original
criteria, results, and dispositions. Their receipts were published at
`12019f093543016ce1cda4256df6b8908f647684`.

The earlier timers excluded the candidate's reversed-document concatenations,
compared repeated eager submissions, and reused a candidate output buffer while
the reference allocated outputs. Their numerical comparisons used floating-point
`torch.equal`, which does not distinguish signed zero. None of those receipts
establishes a production speedup or correctness for all 120 model consumers.

The new successor scope is explicit, informed by those earlier results: six
attention q/o cases at layers 1, 2, 3 and twelve shared up/gate/down cases at
layers 0, 2, 13, 22. K/v and the vocabulary head are excluded prospectively;
this exclusion does not turn the earlier failed all-attention gate into a pass.

## Fixed subjects and reference

Use the already located operand bundle with SHA256
`e49ad84192da8f1f82b759e9360cba18b39eca2a716550048b08d2aa1197dc76`.
Every sampled call covers four documents of 1,024 rows, descending document
reduction, BF16 partials, and BF16 ordered additions.

Reference calls import the real `reduce_weight_gradient` from the frozen checkout.
Attention is also compared to its saved actual gradient. Shared inputs and internal
upstream gradients are reconstructed by invoking `CIADecoder._document_swiglu`
and its `_document_linear` method on saved local-block input, then asking autograd
for the internal gradients and weight gradients. This is current-source local
replay, NOT a fresh independent comparison to the complete original R1 snapshot.
No full network, optimizer, or training step is instantiated.

Both paths receive the same ascending merged matrices. Their strides and storage
offsets are reported. This recreates a local sampled interface; it does not certify
every stride or invocation in the full trainer. Common subject construction is
outside both timers. Candidate-specific rearrangement is inside the primary timer.

## Four arms

| Label | Work in its callable | Role |
|---|---|---|
| `reference_a` | Production four document matmuls and three ordered adds | Primary baseline |
| `reference_b` | Identical baseline with a separately captured graph | Timing self-comparison |
| `kernel_only` | Existing grouped kernel on pre-rearranged inputs | Diagnostic only; cannot select a winner |
| `inclusive` | Reverse-document concatenate both operands, allocate output, execute the same grouped kernel | Primary candidate |

Candidate output allocation is inside both candidate callables. The graph allocator
naturally reserves capture-time storage; this is not charged as repeated setup to
either graph arm. Fixed document-boundary metadata is prepared once. There is no
new precision policy, kernel tuning sweep, wider gradient accumulator, or changed
optimizer cadence.

## Timing and numerical protocol

Use the preceding environment: native Windows, one RTX 4090, torch 2.10.0+cu126,
CUDA 12.6, and Triton 3.5.0. Pin the existing production dependency blobs and the
instrument's complete source commit. Refuse dirty tracked files or source drift.
The source check accepts exact working bytes first, including a blob committed
with CRLF line endings. Its existing alternate check permits CRLF checkout bytes
that normalize to the pinned LF blob; no other conversion or clean filter is used.
The receipt still records the actual working-byte SHA256. The CPU fixtures cover
both stored line-ending styles, Git's LF-to-CRLF checkout, and changes that must
still be refused. This portability correction changes no numerical or timing gate.

Eager is secondary and diagnostic: 16 complete calls between CUDA events, with
possible host-submission gaps explicitly included. Graph is primary: capture 16
complete calls for each label in a separate graph/private pool, then time one
replay and divide by 16. Warm up on a side stream before capture. Run exactly
24 rounds, one per permutation of the four labels. Each label occupies each
order position six times. Three warmups precede each sample. No automatic
extension, retry, tuning, or eager fallback if capture fails.

Before timing, compare finite BF16 storage bits (including signed zero) for eager
and captured results. Zero the live upstream buffers and verify graph replay
actually produces zero, then restore the inputs and recheck exactness. Repeat the
original-data equality check after timing. A baseline disagreement is a refusal;
a candidate disagreement remains an explicit negative. Preserve per-site results
as they complete, including raw samples and diagnostic errors.

## Prospective decision

`PROCEED_TO_BLOCK_TEST` requires all 18 cases present, all numerical/replay checks
passing, at least 5% reduction in the **sum of the 18 sampled graph call medians**,
no sampled site more than 2% slower, and total saved time exceeding the sum of
absolute differences between the duplicated baseline medians. These are engineering
screening margins for a next experiment, not statistical confidence bounds or
learning-noninferiority margins. The duplicate-baseline difference is a diagnostic,
not an estimate of all uncertainty.

Otherwise report `NO_PROGRESSABLE_NET_GAIN` or `NUMERICAL_OR_REPLAY_FAILURE`.
An invalid execution reports `REFUSED_OR_INTERRUPTED`; missing cases cannot pass.
Neither a median of site speedup ratios nor the kernel-only arm adjudicates progress.
The sum is a sample summary, NOT a training-step time or extrapolation to 24 layers.

## Custody and execution boundaries

Only three new files are added: this specification, the instrument, and its CPU
tests. Production modules and prior receipts are not modified.

Run CPU tests through the existing `owned_process.py` with a finite 120-second cap.
Before any GPU execution, freeze and publish the new commit using the repository's
reviewed process; publication alone does not pass hooks or CI. The instrument
requires the exact commit SHA. Use the existing owned launcher with a finite
600-second cap for the later GPU diagnostic, and the existing configured
`EMBER_GPU_LOCK_PATH`. Never invent a separate lock or bypass a held lock.
The diagnostic reserves a new B: output directory, redirects new compilation
caches there, requires 6 GiB free GPU memory and caps this process's allocator at
4 GiB. These are execution limits, not time estimates. Files are create-only;
failed or interrupted results are not overwritten. The owned launcher handles
process-tree cleanup; a hard termination may leave only the plan and completed
per-site receipts. Such a partial run cannot pass.

Zero applied positions, zero optimizer updates, no governed-hour, learning,
protected-evaluation, admission, or #1945 completion credit. A positive result
selects an integrated block test; it does not authorize production integration.

## Verification boundary

CPU tests cover arm bookkeeping, descending document order, fresh-input use,
bit comparisons, finite diagnostics, sample completeness, numerical and timing
refusals, source freezing, create-only receipts, and shared-autograd orchestration.
The orchestration test uses a stated CPU double, not the complete decoder.
They do not test CUDA graph execution, the Triton binary, native Windows resource
containment, or GPU performance. Those remain unexecuted until the bounded local run.

Technical reference: PyTorch CUDA semantics, CUDA Graphs section,
https://docs.pytorch.org/docs/main/notes/cuda.html#cuda-graphs . Runtime source is
pinned to the Ember commit above, not to the evolving documentation page.
