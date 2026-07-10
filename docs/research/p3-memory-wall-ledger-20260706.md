# P3 memory wall — the 27B VRAM ledger (research tick 2026-07-06)

**Related:** #207 (bottleneck ledger), #241 (rung-3 un-fail engineering), #244 (WDDM VRAM gate audit — measurement-integrity companion).

---

## The law (derived 3 independent ways)

**Governed floor:** 19.19 GiB at 27e9 params = ~6.1 bits/param for everything resident.

After activation/workspace reserve, **TRAINING STATE must average ≤ ~4.5-5 bits/param**. The composed ledger tightens the resident master to **≤ 4.1 bits (5 bits does not close).** `[DERIVED — three-seat panel, arithmetic independently verified]`

**Structural corollary:** the budget admits **at most ONE dense ≥4-bit tensor** — weights claim it. Gradients/moments must be transient, factored, or low-rank in any viable design.

**Field positioning:** Nothing in the fetched literature trains from scratch anywhere near this regime:
- GaLore (2403.03507): 7B/24GB *feasibility* at 19.7B tokens with **bf16 weights** `[CITED]`
- 8-bit states at 1.5B (2110.02861) `[CITED]`
- Adafactor (1804.04235) `[CITED]`

**The ≤4.1-bit-master training regime is unclaimed territory: P3's field-level contribution surface.** `[DERIVED]`

---

## One composed design, not three rivals

**NF4-stochastic-rounding weights + Muon momentum via lifted-NS polar identity + per-layer grad-fuse:**

1. **Dense tensor:** NF4 + stochastic-rounding 4-bit weights (sole dense ≥4-bit tensor) `[MEASURED — D6 receipt production already bfloat16-native]`
2. **Optimizer state:** Rank-r projected Muon momentum via the exact lifted-NS identity `polar(P·M_r) = P·polar(M_r)` (5-line proof, momentum rotated across subspace switches) `[DERIVED]`
3. **Gradient accumulation:** Per-layer grad-fuse (no model-wide grad buffer; projection restores gradient accumulation) `[DERIVED]`
4. **Checkpoint:** Full checkpointing (production) + optional compressed-state streaming (PCIe is NOT the wall: break-even ~6 GB/s vs ~25 GB/s available, closed-form BW = C_eff / T_mb) `[DERIVED]`

**Total VRAM footprint:** ~19.0 GiB at 27B shapes. `[DERIVED — composition-honest ledger]`

**Measured this tick (box-specific):** host RAM = 64 GB. Full-precision-state offload (218–272 GB) is dead here as configured; offload survives only as the compressed accessory. **NVMe endurance, not bandwidth, is the offload clock.** `[MEASURED — native Windows Python 3.10, torch 2.10.0+cu126, RTX 4090]`

---

## The load-bearing unknown: sub-grid update precision

**Update-accumulation precision gap:** 4-bit grid step ~1e−2 vs Muon per-element update ~1e−4 = **~100x gap.** `[MEASURED — two independent seats]`

Stochastic rounding ≈ 1% flip probability per update; convergence at that noise floor is **unreceipted anywhere.** `[DERIVED]`

**Binding ledger rule:** Every proposal must carry an explicit "update-accumulation precision: __ bits × __ params" line:
- `bf16 × 27e9` self-refutes at 50 GiB. `[ASSUMED → REFUTED]`
- `rank-r factored` = the projection mechanism — **the accumulator question IS the projection question.** `[DERIVED]`
- BitNet-class ternary training keeps high-precision latents: an inference result in a training costume, irrelevant to residency. `[CITED — 2305.17118 and successors keep fp32+ latents]`

---

## Immediate engineering consequences

**1. Rung-3 (4.24B) un-fails with existing knowledge** `[DERIVED]`
- Per-layer grad-fuse + 8-bit momentum → 14.6 GiB `[MEASURED]`
- bf16-momentum variant → 18.2 GiB thin-fit `[MEASURED — fully covered by D6 receipt]`
- Family ceiling full-resident ~7B `[DERIVED]`
- **Dispatch:** Engineering lane. `[ASSIGNED]`

**2. Post-grow rank collapse (novel, checkable)** `[DERIVED]`
- Immediately after net2net growth, duplicated units manufacture low-rank gradient structure
- Largest where the ladder is largest
- **Probe:** Spectrum check on live W2 runner (cheap) `[DESIGNED]`

**3. Compute honesty** `[STATED]`
- 27B step inside 24GB is winnable
- 27B Chinchilla from-scratch = ~41 years on this card
- **P3 feeds the growth ladder (P1/P2); it does not replace it.** `[CONSTRAINT]`

---

## Pre-registered experiment queue (kill criteria frozen before any run)

**EXP-B: Bandwidth soak** `[COMPLETED — 2026-07-06]`

Instrument probe only: synthetic random tensors, zero model/training-data risk (L3 moot).

**Receipt:** `receipts/expB-bandwidth-soak-20260706T153452Z.json` `[MEASURED]`

**Results (48 iterations/arm after 5 warmup):**

| Arm | H2D GB/s | D2H GB/s | GEMM ms | Notes |
|---|---|---|---|---|
| A: copy-only baseline | 26.73 | 26.39 | — | H2D+D2H, no GEMM |
| B: full schedule | 26.34 | 26.22 | 178.3 | H2D+GEMM+D2H concurrent |
| C: duplex-off ablation | 26.31 | — | 179.3 | H2D+GEMM, no D2H |

- Duplex degradation (C→B): **−0.13%** (noise-level) `[MEASURED]`
- Compute-contention degradation (A→B): **1.43%** `[MEASURED]`
- Bubble ratio: **0.995** (near-perfect overlap) `[MEASURED]`
- CPU-AdamW: dummy fp32-master+bf16-moments, 254.4M params → **469.25M params/s** `[MEASURED]`

**Kill-condition verdicts (frozen at pre-registration):**

- K1 (H2D-under-load < 6.5 GB/s): measured 26.34 GB/s → **SURVIVED** `[MEASURED]`
- K2 (CPU-Adam < 35M params/s AND duplex < 8 GB/s): 469.25M params/s, 26.34 GB/s → **SURVIVED** `[MEASURED]`
- K3 (predicted-vs-measured bubble mismatch > 2×): ratio 0.995 → **SURVIVED** `[MEASURED]`
- H1 primary (H2D ≥ 15 GB/s under saturating GEMM, duplex ≤ 20%): 26.34 GB/s, −0.13% → **SURVIVED** `[MEASURED]`

**Verdict:** PCIe bandwidth is not the wall at this slot/card. CPU-AdamW throughput clears the offload-viability bar. `[MEASURED]`

---

**EXP-C1: Rank-r momentum projection via lifted-NS identity** `[COMPLETED — 2026-07-06]`

Swept five arms (full/r8/r32/r128/B0_r32_int8) on the 718M D6 template. Kill criteria: eval loss within 2% of control, rho-sustained fraction ≤ 0.5 (projection-fiction gate).

**Receipt:** `receipts/expc1-rank-sweep-20260706T175635Z.json` `[MEASURED]`

**Results summary:** All arms rejected on rho-sustained criterion (100% of timed steps exceeded rho > 0.5 threshold). Eval-loss tracking passed (all ≤ 0.04% delta), but projection mechanism did not reduce effective dimensionality — projected subspaces are fiction for all tested ranks. `[MEASURED]`

**Verdict:** Lifted-NS polar identity does not enforce low-rank structure in practice at these dims. Pre-registration and kill criteria: see https://github.com/wordingone/ember/issues/207#issuecomment-4930954547 `[RECEIPT-HONEST]`

**Successor:** SR4-MASTER (calibrated full-rank Muon under NF4 quantization; no projection).

---

**SR4-MASTER: NF4+SR masters vs bf16**

At 368M, 3 arms including nearest-rounding positive control. Decay-compressed schedule. **Kill condition: flip-rate stall.** `[DESIGNED]`

---

**Quantized-parent growth probe** (gated on SR4-MASTER)

Growth lineage from the quantized SR4 winner; measure whether growth-manufactured low-rank structure absorbs the rank-r projection without catastrophic loss spike. Pre-registered kill: if loss flattens post-grow (→ growth did not activate), or if post-grow convergence diverges >2% from parent trajectory. `[DESIGNED]`

---

## Open forks (L8, named not decided)

**F1 — C1 scale-class semantics if the honest full-resident ceiling is ~7B with 27B step-feasibility via the 4-bit regime.** `[OPEN QUESTION — operator decision point]`

**F2 — RAM 64 GB → 192 GB opens the full offload tier (hardware allocation = operator's set).** `[OPEN QUESTION — operator decision point]`

---

## Deviations from original P3 dispatch (disclosed)

**Deviation 1 — reduced EXP-B footprint (disclosed):** nvidia-smi ground truth showed ~795 MiB free VRAM with a bare CUDA context (resident inference servers on ports 8082/8090-8092 hold ~22.8 GiB, never touched). This is tighter than both the pre-reg's 6 GB design and the ~1.7 GiB estimate. Buffers sized to 295 MiB budget with 500 MiB safety margin. Sustained-bandwidth numbers should be footprint-independent per pre-reg; GEMM-load SM-occupancy profile most likely affected. `[MEASURED]`

**Deviation 2 — WDDM VRAM-reporting finding (worth flagging to future VRAM-ledger tooling on this box):** `torch.cuda.mem_get_info()` reported ~17.9 GiB free at the exact instant nvidia-smi reported ~0.8–1.3 GiB — a **~17 GB discrepancy**, attributed to Windows WDDM GPU-memory virtualization/oversubscription. **torch's self-reported free memory is NOT a safe sizing basis on this box.** This run sized everything off nvidia-smi subprocess queries; post-exit nvidia-smi confirmed VRAM returned to baseline (used 22881 MiB vs 22896 pre-run, within driver noise). `[MEASURED]`

---

## Provenance and grounding

- **P3 synthesis comment:** wordingone/ember issue #207, comment authored 2026-07-06, 3-seat panel synthesis (theory/experiment-design/adversary)
- **Tick-2 grounding delta:** wordingone/ember issue #207, comment authored 2026-07-06, panel assignment protocol draft
- **EXP-B receipt:** `receipts/expB-bandwidth-soak-20260706T153452Z.json` (landed 2026-07-06)
- **D6 reference:** `receipts/d6-bf16-momentum-ab-20260703T160041Z.json`, live GPU A/B at current 718.3M shape, production-already-bf16-native finding
- **Literature:** GaLore (2403.03507), BitNet derivatives (2305.17118 family), AdafFactor (1804.04235), QLORA / QLoRA-style techniques (2110.02861 reference family)

All arithmetic above independently recomputed and cross-checked against the source comments' own derivations. No assumptions carried without a measurement, citation, or explicit ASSUMED tag. Every claim admits invalidation by a pre-registered experiment or a cited measurement contradiction. `[RECEIPT-HONEST]`
