# c04 design constraints v1 — the ceiling-first core (2026-06-12, ~3:05 PM LA)

Successor architecture to c03, REQUIRED by compute-ceiling-program-v1
verdict @9236963: c03's mechanical stack exhausted at ~1.85× measured vs
the 3.3× shatter criterion — the residual is architectural. c04 is
designed FOR the levers, and every constraint below is pinned to a receipt,
not taste. **No c04 pretrain exists until the design-time bench gate (§3)
passes — gate 9 (#349) consumes its receipts.**

## 1. Receipt-derived constraints

**C-1. Shape policy (fp35c-weight-cache-ab-...214509Z, per-shape):** fp8
wins only expansion shapes (K=1024→N=4096: 1.15×) and loses contractions
(K=4096→N=1024: 0.852×) and squares (1024²: 0.60×) at c03 widths. c04's
dtype route is decided by a PER-SHAPE fp8 A/B on c04's ACTUAL GEMM set at
design time (harness exists) — fp8 adopted only if the FLOP-weighted
per-shape product beats bf16; otherwise bf16 stays and the lever is
receipted-killed for c04 too. No width is chosen FOR fp8 without the
receipt.

**C-2. Activation budget (L5 OOM cells, fp32-step-econ-...213856Z):** c03
could not run no-ckpt at ANY useful batch on 24GB — a permanent ~33%
recompute tax. c04 MUST fit no-checkpoint at its measured batch knee:
params(bf16/qat) + optimizer state + activations(B_knee, seq) ≤ 0.80 ×
24GB − 1.5GB margin. This is an equation the candidate grid must satisfy
on paper first, then by a measured warmup cell.

**C-3. Optimizer wall-share (fp33-e4-profiler + fp35-fused-muon-kernel-ab
...215202Z):** c03's Muon NS chain held 45.9% of step wall; compile-fusing
NS5 recovered only 1.0885×. c04 constraint: optimizer phase ≤15% of step
wall at the design bench, achieved by any receipted means — fewer NS
iterations (equivalence-checked), Muon restricted to 2D cores with a fused
side optimizer, or replacement. The 15% is measured, not promised.

**C-4. Compile-resident (fp32-l6-compile-ab-...215844Z):** compile gave
1.272× on c03 and is free capability now (MSVC env receipted). c04 trains
compiled from step 0; ZERO graph breaks at the design bench — a break is a
design defect, not an env issue.

**C-5. QAT placement (phase anatomy: qat_fwd = 12% GPU share):**
quantization-nativeness stays a goal property, but if fake-quant holds
>10% GPU share at c04 shapes, the design moves to delayed-QAT (fp warmup →
QAT phase-in), decided by one A/B cell. Assumed-in-place QAT was a c03
mistake the profiler caught only after launch.

**C-6. Candidate grid:** width/depth candidates (e.g. hidden 2048–2560 ×
depth 12–16, embeddings per owned tokenizer) sized so C-2 holds and FLOP/
token stays within budget for §3's wall-clock gate. Wider-not-deeper is
the receipt-backed prior (arithmetic intensity + fp8 shape behavior +
launch-overhead amortization), but the GRID decides, not the prior.

## 2. What c04 inherits unchanged

Owned tokenizer + shards (TOKEN-SHARDS-V0), curriculum/floor protocol
(fp-23/24), verifier/receipt/gate stack, W-code world, round design with
the gate-stats methods, governor rails (fraction/margin/pacing untouched).
The ARCH kill loses weights + config only — recorded in program §3b.

## 3. Design-time bench gate (the criterion, restated per-core)

For each surviving candidate: one governed bench (<1h, full lever stack —
compiled, dtype per C-1, no-ckpt per C-2, optimizer per C-3) measuring
tok/s_paced. GATE: planned token budget ÷ tok/s_paced ≤ **24 governed
hours**, with C-2..C-5 receipts attached. The winning candidate's bench
receipt becomes gate 9's efficiency receipt. If NO candidate passes, the
residual is hardware — the program presents the priced scale-out residual
to the user (program §4.5) rather than silently relaxing the criterion.

## 4. Sequence

1. Candidate grid arithmetic (paper, C-2/C-6) — Leo, this doc's successor
   issue carries it.
2. Per-shape fp8 A/B + per-candidate design benches — eli, <1h each,
   ENG/ARCH-tagged receipts.
3. Gate: winning candidate → gate-9 receipt → user sees the wall-day
   number BEFORE any pretrain dispatch (1h rule stands until then).
4. Token budget for c04-v0 re-derived against H3's calendar skeleton
   (06-22 survives if pretrain ≤1 day and ≥5 round days remain).
