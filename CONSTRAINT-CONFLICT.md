# Issue #482 Spectral Measurement — Constraint Conflict

## The Conflict

**Issue #482 protocol requirement:**
- Compute grad_post_gate from B3 fork's forward pass on the pinned batch
- This requires GPU compute (forward + backward pass through 2.2B model)

**Teammate message constraint:**
- "CPU-ONLY work — do NOT touch the GPU, do NOT stop/start any server"

## What I Can Accomplish (CPU-only)

1. ✅ Load and verify pre-widen cached tensors
   - theta_gate_pre.pt (16384 × 9216)
   - grad_pre_gate.pt (16384 × 9216)
   - pre_momentum.pt (16384 × 9216)

2. ✅ Compute u_pre via _muon_step_in_copy
   - u_pre_spectral = 7.214187e-02
   - u_pre_rms = 3.096689e-04
   - Validates SVD plumbing (8/8 unit tests pass)

3. ✅ Load grown weights (32768 × 18432 gate_proj after widen)

## What's Blocked (Requires GPU)

4. ❌ Compute u_post
   - Requires grad_post_gate (32768 vector after widen)
   - grad_post_gate only exists via B3 phase forward pass (no cached version)
   - Forward pass on 2.2B model → GPU-required
   - Cannot proceed without violating CPU-only constraint

5. ❌ Spectral ratio computation
   - Cannot compute spectral_ratio = u_post_spectral / u_pre_spectral

6. ❌ RMS cross-check validation
   - Protocol requires step_rms values to match B3's 0.0003768490569200367
   - Cannot validate without recomputing u_post

## Proposed Resolution

Either:
1. **Lift CPU-only constraint**: Allow one GPU forward+backward on pinned batch (protocol says this is acceptable under L6)
2. **Modify protocol**: Use u_pre spectral only as a partial measurement (less scientifically clean but GPU-free)
3. **Cache grad_post_gate**: Re-run B3 phase in a separate task to cache grad_post_gate, then run spectral as pure CPU reuse

## Next Step

**Awaiting team-lead decision on constraint precedence.**

- If CPU-only wins: can provide partial spectral receipt (u_pre only)
- If measurement wins: can run full spectral measurement with GPU forward pass
