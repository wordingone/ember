# Issue #1413 Stage 2 Census and Activation Plan

> **For Codex:** Execute this plan in the two governed worktrees named below. Publish both as drafts from immutable heads. Merge census authority first; rebase only the activation carrier's authority-consuming delta afterward.

**Goal:** Produce the real training-path CUDA-graph signature authority, then bind FP8 down-projection and CUDA-graph activation to that reviewed authority with zero fallback and receipted throughput.

**Architecture:** Carrier 1 adds a closed, deterministic signature grammar and an observation-only collector at the real decoded-batch boundary. It cannot activate either accelerator and emits a no-overwrite census receipt. Carrier 2 wires the already-reviewed FP8 and graph primitives into the same training loop, but activation fails closed unless an exact merged census receipt and its admitted signature set verify.

**Tech Stack:** Python 3.12, PyTorch/CUDA, unittest/pytest, governed Ember vertical runner, `src/ember/governance/scripts/owned_process.py`, `src/ember/governance/scripts/worktree_lifecycle.py`.

---

### Task 1: Carrier 1 closed signature grammar

**Files:**
- Modify: `tools/ember-restart-3b/training_acceleration.py`
- Test: `tests/ember_restart_model/test_training_acceleration.py`

1. Add failing tests for canonical tensor descriptors, active-expert and span binding, deterministic SHA-256, unique signature counts, closed receipt keys, and no-overwrite output.
2. Run the focused test and retain the RED output.
3. Implement the minimum `training_step_signature` and `TrainingSignatureCensus` surface.
4. Re-run the focused test through `src/ember/governance/scripts/owned_process.py`; require green and owned cleanup.

### Task 2: Carrier 1 real-path producer integration

**Files:**
- Modify: `tools/ember-restart-3b/pretrain.py`
- Modify: `tools/ember-restart-3b/run_vertical_slice.py`
- Test: `tests/ember_restart_model/test_pretrain.py`
- Test: `tests/ember_restart_model/test_runner_preflight.py`

1. Add failing tests proving the observer sees the actual decoded batch before mutation, does not change optimizer/cursor behavior, and is absent by default.
2. Add an optional signature observer to `run_pretraining_segment` and a governed CLI census-output option.
3. Mint the census only after the bounded segment terminates; bind source/config/input/run identities and refuse an existing output path.
4. Run focused and affected suites, authority conservation, repo guard, and diff checks through owned finite-time commands.
5. Publish Carrier 1 as a draft and request independent exact-head review.

### Task 3: Real census execution and authority pin

**Files:**
- Add: `docs/domains/governance/spec/llmq/ember-training-signature-census-v1.json`
- Extend: Carrier 1 tests as needed for immutable receipt pins.

1. After Carrier 1 source review, execute the census on the governed real predecessor path with the normal GPU/disk/custody gates and zero activation.
2. Verify raw hash, self-hash, source/config/input identities, signature counts, and owned cleanup.
3. Add the exact immutable census sidecar without overwriting any receipt; rerun every Carrier 1 gate and obtain exact-head review.
4. Merge Carrier 1 only after required checks and review are green.

### Task 4: Carrier 2 activation binding

**Files:**
- Modify: `tools/ember-restart-3b/training_acceleration.py`
- Modify: `tools/ember-restart-3b/model.py`
- Modify: `tools/ember-restart-3b/pretrain.py`
- Modify: `tools/ember-restart-3b/run_vertical_slice.py`
- Test: `tests/ember_restart_model/test_training_acceleration.py`
- Test: `tests/ember_restart_model/test_pretrain.py`
- Test: `tests/ember_restart_model/test_runner_preflight.py`

1. In the parallel activation worktree, add failing tests for census/hash mismatch, an unapproved live signature, non-SM89, stale FP8 weights, any fallback, capture identity drift, and default-disabled behavior.
2. Add explicit activation authority parsing; it must reopen the merged census sidecar and exact hash.
3. Cache signatures by the cheap static tuple (expert, tensor shapes/dtypes/device/layout, spans, checkpointing) and perform canonical JSON plus SHA-256 only for a first-seen tuple; graph replay must never hash per step.
4. Wrap only live 4H-to-H SwiGLU down projections with `DynamicFp8DownProjection`; refresh persistent FP8 operands exactly once after each optimizer update.
5. Capture/replay only `forward_loss_backward` by an admitted signature. Keep optimizer step, clipping, cursor movement, checkpoint publication, and telemetry outside capture.
6. Emit exact kernel, graph, recompute, fallback, and throughput receipts; reject any fallback or incomplete mechanism count.
7. Run focused/affected suites, authority conservation, repo guard, and diff checks; publish Carrier 2 as a parallel draft for independent structural review.

### Task 5: Pinned-order integration and governed A/B

1. After Carrier 1 merges, rebase Carrier 2 and change only the authority-consuming pin/delta required by the merged census.
2. Re-run all tests and obtain fresh exact-head independent review and green CI.
3. Execute matched BF16 baseline and census-bound accelerated arms with identical source/config/data/checkpoint/seed/order and normal custody gates.
4. Require real FP8 dispatches, real CUDA-graph replays, zero fallbacks, matched loss, and throughput strictly greater than 1000 tok/s before any #1413 closure claim.
5. Publish exact receipts to #1413, verify the public issue is `CLOSED`, then update the permanent backlog without ever marking the goal complete.
