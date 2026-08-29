# Issue #1413 Census-Bound Activation Consumer Plan

> **For Codex:** Author this carrier in parallel, publish it as a draft, and keep it merge-blocked behind the census-authority carrier. After census merge, rebase only the authority-consuming delta.

**Goal:** Activate the reviewed SM89 FP8 down projection and CUDA graph training region on the real Ember path only when the merged census authority admits the exact live signature.

**Architecture:** A closed activation authority reopens the merged census receipt and pins its raw SHA-256. Model construction replaces only live 4H-to-H SwiGLU down projections. The pretraining loop captures/replays only forward/loss/backward; clipping, optimizer update, FP8 refresh, cursor mutation, checkpointing, and telemetry remain outside capture. Every mismatch or fallback refuses.

**Tech Stack:** Python 3.12, PyTorch/CUDA, unittest/pytest, governed Ember vertical runner, owned-process custody.

---

### Task 1: Write activation RED tests

**Files:**
- Modify: `tests/ember_restart_model/test_training_acceleration.py`
- Modify: `tests/ember_restart_model/test_pretrain.py`
- Modify: `tests/ember_restart_model/test_runner_preflight.py`

Cover default-disabled behavior, missing/mismatched census hash, unapproved signatures, non-SM89 refusal, exact down-projection sites, stale FP8 weights, graph identity drift, zero-fallback enforcement, and receipt closure.

### Task 2: Implement the authority consumer and model binding

**Files:**
- Modify: `tools/ember-restart-3b/training_acceleration.py`
- Modify: `tools/ember-restart-3b/model.py`
- Modify: `tools/ember-restart-3b/run_vertical_slice.py`

Parse a closed activation contract, reopen the census sidecar, verify its exact hash and admitted signatures, and wrap only `SwiGLUExpert.down` instances. Preserve the original BF16 master parameters and checkpoint state identity.

### Task 3: Integrate captured training and receipts

**Files:**
- Modify: `tools/ember-restart-3b/pretrain.py`
- Modify: `tools/ember-restart-3b/training_acceleration.py`

Use static buffers per admitted signature. Capture/replay `forward_loss_backward`; leave clipping, optimizer step, cursor and checkpoint operations outside. Refresh FP8 weights exactly once after each optimizer step. Emit kernel, graph, recompute, throughput, and zero-fallback receipts.

Cache by the cheap static tuple (expert, tensor shapes/dtypes/device/layout, spans, checkpointing) and perform canonical JSON plus SHA-256 only for a first-seen tuple. No replay step may perform per-step canonical hashing.

### Task 4: Verify and publish the parallel draft

Run focused and affected suites through `src/ember/governance/scripts/owned_process.py`, then authority conservation, repo guard, and diff checks. Publish an immutable draft head for independent structural review. State clearly that it cannot merge before Carrier 1.

### Task 5: Rebase the authority-consuming delta and execute

After Carrier 1 merges, rebase this draft and modify only the merged census path/hash/signature bindings. Re-run exact-head review and CI. Execute matched BF16 baseline and accelerated arms under normal GPU/disk/custody gates. Require both mechanisms, zero fallbacks, matched loss, and throughput strictly greater than 1000 tok/s before #1413 closure.
