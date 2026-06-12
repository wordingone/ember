# Compute-ceiling program v1 — shatter the local training ceiling (2026-06-12)

**v1.2 (user order 2:33 PM LA, executed 2:34 PM):** run 12c050e7 STOPPED
(train_cancel, kill-receipted, daemon alive, GPU freed at ~1.3B tokens
paid). User rule, BINDING: **no training run >1 hour until the ceiling
problems are solved.** Runs are measurement instruments until the shatter
criterion is met — producing checkpoints on an unproven path is datacenter
economics imported onto a residency machine; on one machine, iteration
speed IS the research capability. §4 rule 3's boundary decision is
DISSOLVED (no live run); the next pretrain exists only through gate 9 with
the full lever stack receipted + the ENG/ARCH architecture verdict. All
lever benches now run in full governed windows (<1h each).

User directive 21:15Z (binding, NO DEFERRAL): "unless you explicitly solve
the local full training compute bottleneck completely and utterly shatter
the ceiling, ember's not gonna get anywhere. Everything downstream, even
ember's nature would not be solvable. Deferral for this problem is not an
option."

Register: this is **H0** — it outranks every other entry. The S5 chain and
round design are DOWNSTREAM of this program. Reframe accepted: ember's
nature requires pretrain-from-scratch to be an ITERATION operation (hours,
overnight at worst), not a multi-day commitment. At today's measured
ceiling a 7B-token c03 pretrain costs 3.4–4.5 wall-days — at that price we
get ~2 architecture/data iterations before 06-22 and ZERO exploration of
ember's design space. That is the real ceiling cost: not wall-clock,
ITERATIONS.

## 1. The ceiling, from receipts (no vibes)

Baseline (fp32-step-econ-20260611T142831Z, c03 = hidden 1024 / 20 layers /
seq 1024, QAT variant, governed 0.80/1.5GiB/0.05s):

| cell | tok/s paced | tok/s raw | pacing tax |
|---|---|---|---|
| B=4 ckpt eager (LIVE RUN CONFIG) | 17,899 | 22,903 | 21.9% |
| B=8 | 23,088 | 26,875 | 14.1% |
| B=24 | 24,079 | ~28k | ~12% |

Phase anatomy (fp33-e4-profiler): wall shares — backward 41.5 / optimizer
45.9 / forward+QAT ~12; GPU-work shares — backward 56.5 / forward 20.2 /
QAT 12.0 / optimizer 11.3. **The optimizer phase consumes 45.9% of step
WALL while doing 11.3% of GPU work — it is launch/memory-bound (Muon
Newton-Schulz chain, #329's 1008 GB/s bw ceiling claim). That asymmetry is
the single largest measured inefficiency on the board.**

Known route receipts: fp8 torchao KILLED (0.45×, fp33-fp8-linear-ab); fp8
NATIVE-Windows route P1 PASS (kernel-name receipt, fp33-p1); fused-muon
harness MERGED, bench NOT RUN (#329); torch.compile fails in daemon env
(receipted) — eager pinned; B=24 lr-certification (E1b) never run, <1h cost.

## 2. Mathematical ceiling obligation (roofline)

MFU = (FLOPs/token × tok/s_raw) / peak_FLOPs. FLOPs/token ≈ 8·N_active
(fwd 2N + bwd 4N + ckpt recompute 2N; N ≈ c03 non-embedding params).
First-cut: ~28k tok/s raw at N≈0.3B → ~67 TFLOPS sustained → MFU ≈ 30–40%
against a consumer bf16 peak of 165–210 TFLOPS. **Roofline gap ≈ 2.5–3×
before any architecture change, on top of the levers below.** Obligation
(eli, receipt): pin GPU model/peak specs + per-phase achieved-vs-peak so
the gap is a NUMBER, not a range. Small-model caveat: hidden 1024 has low
arithmetic intensity — batch and fusion are how it climbs the roofline.

## 3. Lever stack — each lands by A/B receipt at c03, compound tracked

| # | Lever | Expected (basis) | Status → action |
|---|---|---|---|
| L1 | B=24 (+lr cert E1b) | 1.345× (MEASURED) | cert at 1B-ckpt boundary, <1h |
| L2 | B-ladder beyond 24 (B=32/48 to VRAM/compute knee) | unknown, bench is cheap | NEW bench cell |
| L3 | Fused-muon NS chain (#329) | optimizer wall 45.9%→bw-bound fusion; step 1.3–1.6× if phase halves | BENCH NOW (governed window beside live run — fp33 precedent) |
| L4 | fp8 native route (fp-35c successor) | backward = 56.5% GPU; GEMM ~2× → step 1.3–1.5× | integration A/B, beat-bf16 bar stands |
| L5 | Checkpointing OFF (recompute tax ~25% of fwd+bwd) | 1.15–1.25× if VRAM fits (17.2 GiB free at B=4!) | NEW bench cell |
| L6 | torch.compile on native-Windows path (daemon env failure = wall to break, not accept) | 1.1–1.3× (QAT elementwise fusion) | break-the-wall item |
| L7 | Duty cycle: loader/ckpt/eval stalls in REAL run (benches exclude by design) | unknown — measure | mine from 12c050e7 logs |
| L8 | Data/objective efficiency (H2: selection, replay, easy-mass discount) | effective-compute multiplier, unbounded | round-design constraint |

Compound mechanical target (L1×L3×L4×L5 mid-estimates): **≥3.3×, stretch
~5× with L2/L6 → ≥72k tok/s paced → 7B-token c03 pretrain in ~27h.** That
is the shatter criterion v1: **pretrain-from-scratch ≤ 1 governed day.**
Misses are receipted KILLs that name the physics (bw-bound, VRAM, lr).

## 4. Binding rules

1. NO DEFERRAL: at every tick, ≥1 lever must be in flight (bench running,
   PR open, or receipt landed) until the shatter criterion is met or every
   lever is receipted-KILLED. "Waiting for the run boundary" is valid ONLY
   for levers that physically require it (L1 cert, integration swaps);
   benches ride governed windows beside the live run (fp33 precedent).
2. Gate 9 (#349) consumes this stack: the NEXT pretrain launches only with
   every lever applied/killed/waived-priced.
3. Live run 12c050e7 is NEVER touched mid-flight; the 1B-token checkpoint
   (~09:00Z) is the first boundary where certified levers may enter via a
   registered, receipted restart decision — arithmetic presented to the
   user, who owns the restart call.
3b. **ENG/ARCH verdict tags (v1.1, user 21:21Z — "if its architecture
   makes the training speed lukewarm... the owned core is going to be
   wrong anyways"):** every lever receipt tags its finding ENG (removable
   by engineering: fusing, batching, precision routing) or ARCH (intrinsic
   to c03's design: QAT fake-quant tax, Muon NS chain structure, hidden-
   1024 arithmetic intensity). The checkpoint does NOT validate the
   architecture — only the lever receipts can. **Architecture-kill
   trigger:** if c03 cannot reach the shatter criterion with ALL ENG
   levers applied (i.e. the residual gap is ARCH-tagged), c03 is the wrong
   core; the boundary decision becomes three-way — continue / certified
   resume / STOP + architecture redesign (NC2 recipe-stack pins: Muon
   variant, BitNet-class, QAT placement, replay — already a registered
   wait-window item). What survives an ARCH kill: shards/tokenizer,
   curriculum + floor protocol, verifier/receipt/gate stack, W-code world,
   round design — the owned SYSTEM. What dies: the config and its
   checkpoints. A kill here is data, not a stopping signal.
4. Safety rails unmoved: governor fraction/margin/pacing are the floor;
   the pacing tax is a deliberate rail, not a lever. 100% wall-to-wall
   stays banned.
5. Scale-out (second GPU / cloud) is USER-owned; this program's job is to
   exhaust the local ceiling and present the priced residual, never to
   assume the purchase.

## 5. Owners

- **eli (lane #1, displaces everything):** L3 bench NOW; L2+L5 bench cells
  (one harness run); GPU-peak receipt (§2); then L4 fp-35c integration A/B.
- **Leo:** L7 duty-cycle mining from existing run logs; compound ledger
  (this doc's table updated per receipt); E1b cert + restart arithmetic at
  the 1B boundary; H2/L8 round-design constraint.
- **jude:** adversarial verify on every lever receipt (A/B single-variable
  discipline, governor identity, seed coverage).
- **mira:** run-monitor unchanged; flags any bench-window governor
  violation as RED immediately.
