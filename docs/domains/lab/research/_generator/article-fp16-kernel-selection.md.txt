---
slug: fp16-kernel-selection
title: What a four-cycle FP16 thread actually established
subtitle: A chain that produced three unwelcome verdicts and one finding that outranks all of them.
question: Does requesting FP16 accumulation on this card's dense contractions buy enough to matter, and if it does, what is the mechanism?
issue: 1945
dated: 2026-09-15
interpretation_of_events_through: 2026-09-15T18:20:00Z
hypotheses:
  - the-time-weighted-fp16-accumulation-rate-over-the-whole-eligible-share-20260915
  - machine-fill-not-intensity-decides-where-the-roofline-over-predicts-20260915
  - which-output-size-scaling-cost-dominates-the-sub-wave-contractions-20260915
  - does-the-kernel-selection-change-at-the-dip-and-was-the-tile-premise-ever-true-20260915
receipts:
  - fp16-timeweighted
  - machine-fill
  - wave-boundary-sweep
  - kernel-identity-audit
---

## Opening

Four cycles asked whether FP16 accumulation is a route to this campaign's throughput terminal. The
headline answer is no: the time-weighted gain across thirteen timed contractions is **1.359x**
against a **1.50x** bar frozen before the run, so the arm is REFUTED. Two follow-up cycles tried to
explain the gain's shape and both failed — one on a self-contradictory criterion, one because the
predicted step turned out to be a ramp. The fourth cycle came out INCONCLUSIVE and produced the most
consequential result of the day: the two arms were **not running the same kernel**. Every speedup in
the thread is a ratio between two independently selected kernels, which leaves the measurements
intact and the mechanism story unsupported.

## Why this chain was run at all

Nothing forced it. The chain was chosen over four alternatives because it was the only candidate
touching *numerical representation* — one of three route families this campaign had left — and
because a published vendor rate suggested FP16 accumulation carries the same dense throughput as
FP8 on this architecture, which would make it a lever available without the loss-bar problem FP8
carries. That reasoning is not in any receipt. It is the kind of thing a verdict token cannot
record, and it is why a chain of three REFUTED/INCONCLUSIVE cycles was still worth four hours.

## What was compared

The comparison is between **two requested compute-type routes** through the same library call:
identical operands, identical shapes, one call asking for 32-bit accumulation and one asking for
16-bit. This wording matters and was not the wording used at the time. The experiment controls what
is *requested*; it does not control what the library then *selects*, and cycle four is the cycle
that found out those are different things.

All four cycles ran isolated shapes at k=n=1024 on one RTX 4090. None ran the real workload, none
ran under the governed measurement harness, and none has matched-run variation.

## The four cycles and their frozen criteria

**Cycle one — is the gain large enough?** Criterion frozen before the run: SUPPORTED above 1.50x
time-weighted across the eligible contraction set. Measured: 42,999.3 us/step of timed contraction
work falls to 31,639.2 us/step, a time-weighted **1.359x**; the median across shapes is lower still
at 1.209x. **REFUTED.** The receipt's own boundary is explicit that this composes measured per-shape
factors by measured per-shape device time and is *not* an end-to-end prediction: it covers 94.4% of
the derived census but only 60.0% of eligible-site time, and holds every non-contraction millisecond
constant.

**Cycle two — is the gain explained by how full the machine is?** Per-shape speedups split cleanly:
shapes above 1.4x and shapes below 1.1x separated at every one of three premised tile sizes, where
kernel duration, total FLOPs, contraction depth and census weight all failed to separate them. The
cycle still closed **INCONCLUSIVE**, because the frozen criterion contradicted itself — it required
a rival check that its own output elements term could not pass, output size not being independent of
the thing being tested. A criterion that cannot be satisfied is not a criterion, and the honest
verdict was to say so rather than pick the reading that fit.

**Cycle three — is there a step at the wave boundary?** Twelve shapes from m=512 to m=16384, with a
dominance margin of **1.6x** frozen before the run: the jump at the boundary had to be 1.6 times the
next-largest jump anywhere in the sweep. Measured largest jump 0.2364 at the boundary, runner-up
0.2342 elsewhere — a ratio of **1.009**. **REFUTED.** The gain rises smoothly, which is what a cost
proportional to output elements predicts and what machine fill does not. Cycle two's separation was
real and its explanation was a correlation.

**Cycle four — does the kernel change at the dip?** The sweep contained a sharp fall the dominance
test was structurally blind to, because that test ranks rises: 1.658x at m=1792, **1.007x at
m=2048**, 1.244x at m=2304. The hypothesis was that the library selected a different kernel at that
shape. The criterion: SUPPORTED if the two anchors agree with each other and the dip differs;
INCONCLUSIVE if the anchors disagree. Seven shapes were profiled and the kernel symbol read by
largest self device time. **The anchors disagreed** — m=1792 ran `ampere_h16816gemm_128x128` and
m=2304 ran `ampere_h16816gemm_256x128` — so a difference at the dip carries no information and the
cycle closed **INCONCLUSIVE.** The dip question is still open.

## The finding that outranks the verdict

Cycle four's tile audit was reported under every outcome by design, and it is where the value is.
Two earlier cycles computed every CTA count and wave number from an **assumed 128x128 tile**; the
sweep's own docstring called the tile unobservable. It was observable. **Four tiles actually ran** —
128x128, 128x64, 256x128 and 64x64 — and the two arms ran *different kernels at six of the seven
profiled shapes*, three of the 32-bit arms landing on a CUTLASS 64x64 kernel that the 16-bit arm
never selected.

So the thread's central claim needs restating in three separate pieces that had been fused into one:

1. **The measured ratio stands.** 1.359x time-weighted, 1.007x to 1.658x across the sweep. These are
   repeated timings with their spreads recorded and nothing here touches them.
2. **The verdict stands.** 1.359x is below the 1.50x bar that was frozen before the run. REFUTED
   remains REFUTED.
3. **The attribution does not stand.** Calling that ratio an *accumulator-precision* effect requires
   the two arms to differ only in accumulation. They differ in selected kernel, tile, and in three
   cases kernel family. What was measured is the value of *requesting* the 16-bit route, which is a
   useful engineering quantity and is not a statement about accumulators.

Separating the two would need explicit algorithm pinning. No instrument in this campaign does that,
and building one is not currently justified by a route whose ceiling is already under the bar.

## What is still open

The dip at m=2048 is confounded between the CTA count crossing one wave and m crossing a power of
two, and nothing run so far separates them. Every number is an isolated shape at k=n=1024; the real
census shapes were never put through any of it. Every profiled duration in cycle four is explicitly
**not a rate** — the arms ran under a profiler — so those durations may corroborate a ratio but may
never be quoted as timings. And no cycle here has independent matched-run variation, which under the
governed-run evidence contract makes every ceiling in this thread INCOMPLETE rather than passed.

## The decision this produced

Stop narrowing FP16. A fifth cycle would refine the explanation of a gain whose ceiling is already
below the bar, which is the compositional trap this campaign has been warned about: a sequence of
locally rational small results and no movement. The chain's residual value is banked as a measured
lever worth 11,360.1 us/step in one later composition, carried with its attribution caveat attached.
The next lever chosen instead was byte-elimination at the four largest unexplained elementwise
sites — which was itself subsequently refuted, and pointed at the first work-removal candidate this
campaign has measured.
