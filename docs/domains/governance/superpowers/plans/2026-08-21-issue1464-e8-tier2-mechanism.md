# Issue 1464 E8 Tier-2 Mechanism Implementation Plan

Execute test-first. Carrier T is stacked on Carrier P only while P is under
review; rebase onto merged public master before publication.

## Goal

Implement the approved owned OWNED_Q_GALORE_PROJECTED_GRADIENT Tier-2
mechanism without changing BF16 model weights, frozen training identity, or the
Tier-1 path. The carrier includes the CUDA optimizer, closed contract and
resource accounting, tier-specific checkpoint custody, certified launch route,
terminal receipt, and fail-closed tests.

## Frozen authority

- Rank: min(512, min(parameter.shape)).
- Refresh gap: 200 optimizer steps; scale: 0.25.
- Projector: deterministic FP32 top-rank SVD, canonical singular-vector signs,
  signed symmetric INT4 in 256-value blocks.
- First moment: signed symmetric INT8 in 256-value blocks.
- Second moment: unsigned UINT8 in 256-value blocks.
- Learning rate, betas, epsilon, weight decay, model, data, seed, schedule, and
  full-gradient norm set remain identical to Tier-1.
- Persistent optimizer/projector state must remain on selected CUDA device.
- No random or stale-basis fallback; deterministic SVD failure refuses.
- One-dimensional and unreduced matrices use unprojected block-quantized state.
- T-09 exercises initial basis construction only; the 200-step steady-state
  refresh remains a named residual risk.

## Task 1: Quantization and projected optimizer

Files:

- Create tools/ember-restart-3b/a1_tier2_optimizer.py
- Create tests/ember_restart_model/test_a1_tier2_optimizer.py

Steps:

1. Add failing tests for signed INT4, signed INT8, and unsigned UINT8 block
   round trips, zero blocks, partial blocks, deterministic bytes, invalid
   inputs, canonical SVD signs, projection direction/shape, reconstruction, and
   1-D/unreduced routing.
2. Implement closed quantized tensor records with FP32 CUDA scales and packed
   payloads.
3. Implement deterministic FP32 SVD basis construction with canonical signs.
4. Implement ProjectedQuantizedAdamWCUDA using the shared
   FullGradientNormAccumulator, fused-backward updates, canonical parameter
   order, decoupled weight decay, and immediate gradient release.
5. Add small-model update, norm-equivalence, gradient-release, refresh-ordinal,
   non-finite, sparse, and device-placement tests.

## Task 2: Closed Tier-2 contract and resource preflight

Files:

- Create tools/ember-restart-3b/ember-restart-3b-a1-tier2.json
- Create tools/ember-restart-3b/a1_tier2_contract.py
- Create tests/ember_restart_model/domain-governance/test_a1_tier2_contract.py

Steps:

1. Add failing tests for exact schema, mechanism, placement, rank/gap/scale,
   quantization formats, hyperparameters, deterministic policy, and lineage.
2. Implement a closed loader that refuses missing, extra, or cross-tier fields.
3. Derive BF16 model bytes, maximum current-gradient transient, quantized
   moments/scales, packed projector/scales, dequantization/SVD workspace,
   checkpoint payload/transient bytes, CUDA margin, and B: floor without model
   allocation.
4. Assert host full-state bytes are zero and refuse any CPU persistent state.

## Task 3: Tier-2 checkpoint custody

Files:

- Create tools/ember-restart-3b/a1_tier2_checkpoint.py
- Create tests/ember_restart_model/domain-governance/test_a1_tier2_checkpoint.py

Steps:

1. Add failing round-trip and tamper tests for the separate closed schema.
2. Serialize BF16 weights and every optimizer record: step, projection
   direction/rank/refresh ordinal, packed basis and scales, packed moment
   payloads and scales, source shapes, and quantization metadata.
3. Reopen every shard with CPU mapping, verify raw hashes and tensor metadata,
   and prove exact optimizer coverage of registered parameters.
4. Refuse Tier-1/Tier-2 cross-loads and incomplete inventories.

## Task 4: Certified launch admission and route

Files:

- Modify src/ember/infrastructure/tools/ember-restart-3b/certified_train_launch.py
- Modify tools/ember-restart-3b/run_vertical_slice.py
- Modify tests/ember_restart_model/test_a1_certified_launch.py
- Modify tests/ember_restart_model/test_vertical_slice.py

Steps:

1. Add failing tests for the exact family/tier/mechanism tuple and all Tier-2
   contract/liveness pins.
2. Reopen the corrected liveness receipt, require FALLBACK_REQUIRED, exact
   threshold binding, and valid self digest before argv construction.
3. Admit a1-dense-tier2 as a distinct command with no Tier-1 alias.
4. Preserve Tier-1 compatibility and refuse partial cross-tier run specs.

## Task 5: Execution, final receipt, and identity closure

Files:

- Create tools/ember-restart-3b/a1_tier2_execution.py
- Create tests/ember_restart_model/test_a1_tier2_execution.py
- Modify tools/ember-restart-3b/input_identity.py
- Modify tests/ember_restart_model/test_input_identity.py
- Modify the canonical dependency-closure manifest through its repository
  remint command.

Steps:

1. Add failing execution/finalizer tests for Tier-2 identity, CUDA-only
   inventory, shared telemetry fields, checkpoint binding, and terminal receipt.
2. Wire the dense runner to the Tier-2 optimizer, resource preflight, checkpoint
   writer, and finalizer.
3. Emit truthful tier=TIER2, owned mechanism, cpu_offload=false, complete
   parameter coverage, unchanged architecture revision/count, and exact
   checkpoint hash.
4. Add Tier-2 contract and executable paths to input identity and dependency
   closure; remint only through the canonical command.

## Task 6: Carrier verification and publication

1. Run all Tier-2 tests with PYTHONDONTWRITEBYTECODE=1 and
   -p no:cacheprovider.
2. Replay the touched Tier-1 tests and prove the exact known-red 20-test public
   baseline is unchanged by node ID.
3. Run git diff --check, authority conservation, training dependency closure,
   repository guard, and identity freshness.
4. After Carrier P merges, fetch and rebase onto merged immutable master,
   remint identity/closure as required, rerun every gate, commit through the
   full hook, push through the safe wrapper, and create the governed draft PR.
5. Obtain exact-head review and green required checks before merge. Keep issue
   1464 open until the fresh Tier-1/Tier-2 runs, parity, battery, and E4-E8
   adjudication are terminal.
