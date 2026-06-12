# fp-33 kernel route v0 — FP8-on-sm89 attack plan from E4/E5 receipts (2026-06-12)

Inputs (gated this date): E4 profiler receipt fp33-e4-profiler-20260612T032739Z
(backward 56.5% GPU share incl. grad-ckpt recompute, forward 20.2%, QAT 12.0%,
optimizer 11.3%; ~407ms/step governed) and E5 bench receipt
fp33-e5-fp8-bench-20260612T033056Z (torchao rowwise FP8 → hard RuntimeError:
CUTLASS cannot initialize, WSL2 torch 2.6.0+cu124; bf16 baseline 9593 tok/s
paced). Verdict KERNEL_ROUTE: the prebuilt dispatch path is closed on this
machine; the wall is broken by building the kernel path ourselves. Owner: Leo
(kernel research lane, per the fp-33 amendment); Eli runs probes/dispatches.

## Target order (by measured share, not interest)

1. **Backward GEMMs (56.5% region)** — FP8 mm with rowwise scaling wired into
   the linear backward paths (grad_input, grad_weight) and the grad-ckpt
   recompute forward. Ceiling: 2x GEMM throughput → bounded by the GEMM
   fraction inside backward (profiler phase-split of backward is probe P3).
2. **Forward GEMMs (20.2%)** — same kernel, second integration site.
3. **Optimizer + launch overhead (11.3%)** — cuda-graph-step row; untouched
   until FP8 lands (smaller prize, and graphs interact with governor pacing).
   DISCREPANCY RESOLVED (eli mail 14746): live 12c050e7 runs
   optimizer.mode=muon_split (2 Muon + 6 AdamW groups,
   v0ext-dryrun-20260611T074548Z.json) — the E4 script's "AdamW" label was
   wrong, the registry muon row was right; its receipt field now cites the
   dry-run receipt. fused-muon-kernel row therefore targets a REAL phase.

## Route ladder (cheapest probe first; each rung = receipt before the next)

- **P1 — native-Windows torch probe: PASS (2026-06-12, gated).** Receipt
  fp33-p1-native-fp8-probe-20260612T044036Z: kernel-name trace
  `sm89_xmma_gemm_e4m3bf16_..._5x_cublas` on native Windows torch
  2.10.0+cu126 — fp8 tensor cores engage via cuBLAS, no CUTLASS init failure.
  E5's wall was environment-bound (WSL2 torch 2.6.0+cu124), as hypothesized.
  **Route resolved: fp8 training jobs run native-Windows-side; the work that
  remains is INTEGRATION (contract below), not kernel authoring.**
- **Integration A/B round 1 — cast-heavy variant: FAIL (2026-06-12, gated).**
  Receipt fp33-fp8-linear-ab-20260612T051338Z: 0.45x mean across seeds
  {16,17,18} × 3 c03 shapes — the 3-4 dtype casts per backward mm dominate at
  K=1024 (raw _scaled_mm wins only at K=4096, and inconsistently). Stability
  gates all PASS, so the kill is throughput-only. Adoption blocked by the WSD
  segment guard, registry unpromoted. **Next variant (cheapest unprobed):
  pre-quantized weight cache — cast weights to fp8 ONCE at init, per-step
  casts drop to activations only (1-2 ops); same A/B protocol, same bars.**
  If that fails too at c03 widths, the honest fallback is fp8-at-larger-width
  (the technique scales INTO the next config, not out of this one) — recorded
  as a width-conditional row, not a route abandonment.
- **P2 — CUTLASS-direct build in WSL2: UNBUILT (fallback).** Fires only if
  native-side integration hits a wall (e.g. WSL2-resident daemon coupling
  that can't move native). Receipt bar unchanged: micro-bench + kernel-name
  proof of fp8 tensor-core engagement.
- **P3 — Triton rowwise fp8 mm (authored): UNBUILT (fallback).** Known caveat
  triton#5583 (Triton fp8 slower than CUTLASS _scaled_mm on Ada) — acceptable
  ONLY if P1-route integration AND P2 fail; the bar is then beating BF16, not
  beating CUTLASS. Paired with backward phase-split probe to size the true
  GEMM fraction.
- **Stability recipe (parallel, math axis):** µnit Scaling (2502.05967,
  hp-free FP8 at small widths) is the default; InfiR2 (2509.22536) the
  fallback; To-FP8-and-Back (2405.18710) failure modes become gate
  assertions in the proxy arm.

## Integration contract

Custom autograd.Function wrapping nn.Linear forward/backward at the c03
shapes (0.37B: hidden/MLP dims per v0 config); checkpoint-recompute path
included. Numerics-changing → A/B segment receipt required before adopting
into live v0 (WSD segment-boundary rule). Proxy: speedrun arm per
docs/registry-dispatch-gate-spec-v0.md — one technique per arm, seeds
{16,17,18}, wall-clock + tokens-to-target.

## Registry state (this commit)

fp8-rowwise-torchao → KILL (E5 receipt; revival = env change). New row
fp8-custom-kernel-sm89 CANDIDATE (this route). unit-scaling-muP unchanged
CANDIDATE (now coupled as the stability half).

## Expected value (honest bound, no theater)

If GEMMs are ~70% of fwd+bwd time (P3 phase-split to confirm), full FP8 at 2x
GEMM ≈ 1.37x step-time; with QAT-fwd also fp8-fused, ceiling ~1.45x. The
remaining headroom (recompute elimination via selective checkpointing,
cuda-graphs, fused optimizer) stacks multiplicatively per the registry
composition fields. Every claim above becomes a measured_multiplier or dies.
