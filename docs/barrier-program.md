# Barrier Program — the six dominant barriers to local foundation-model creation

Mandate (operator, 2026-07-10): the mission's dominant barriers must be under *named, receipted
attack* at all times — **total compute, data efficiency, memory traffic, optimizer-state cost,
training instability at scale, capability per token**. Process and faithfulness work (gates,
custody, board hygiene) is scaffold: necessary, but it never counts as attacking a barrier.

Binding: the research loop is BARRIER-FIRST — every research tick picks the weakest-attacked
barrier (or writes a dated justification in the queue). This document is the map; the audit
receipts behind it live in `receipts/barrier-program/` (4 scout + 4 skeptic JSONs, generated
2026-07-10 by an 8-agent audit workflow; verdicts: REAL_AND_OPEN / ALREADY_COVERED /
NOT_FEASIBLE_LOCAL / THEATER).

Position summary (all numbers receipted, 2026-07-10, live 2.2B rung-2 stabilize leg):

| # | Barrier | Position (measured) | Attack state |
|---|---------|--------------------|--------------|
| 1 | Total compute | 79–81 s/step @ 2.2B; C-GROW 2.4309× is **matched-step only** — fixed-capability INCONCLUSIVE | PARTIAL → #701 |
| 2 | Data efficiency | fixed shards-v0 corpus; zero curation/curriculum/blending receipts; tokenizer-gap receipt only | **WEAKEST** → #703 |
| 3 | Memory traffic | GPU ~idle (≈30 W avg, ~4% util) while ~13 CPU cores run the offload path; 79 s/step never decomposed | PARTIAL → #702 |
| 4 | Optimizer-state cost | fp32 moments, file-backed (184 memmaps); muon-local for matrices; no precision/factorization screens | PARTIAL → #704 |
| 5 | Instability at scale | strongest axis: rung ladder, kill bands, transplant-carries (P-2 CONFIRMED), boundary base rate banked | ACTIVE |
| 6 | Capability per token | eval receipts exist (math500 / ARC / MMLU-pro) but no unified capability-per-token metric; MTP thread #688 | PARTIAL → #705 |

Energy receipt (new axis-adjacent fact): `kwh_running=0.0196` through 3 blocks of the live leg —
capability-per-joule is measurable on this box for free from existing logging.

---

## 1. Total compute

**Position.** The box's binding realization: 79–81 s/step at 2.2B (trace receipts,
`step-trace-cbase-grow-rung2-stabilize-leg1-block0*.jsonl`). The growth ladder reuses compute
across scales — but the headline C-GROW saving (2.4309×) is measured at **matched step count
(766)** and explicitly disclaims comparable from-scratch loss (external audit, SHAs in #701).
Compute-to-fixed-capability is therefore UNMEASURED. A "no FLOPs budget exists" gap was killed
by the skeptic pass as THEATER — accounting alone moves nothing; the crossing experiment
supersedes it.

**Next decisive experiment → #701:** frozen heldout NLL + capability target; grown vs
from-scratch at final width, matched data/order/optimizer; measured FLOPs/tokens/wall to first
crossing; paired seeds; pre-registered equivalence grammar; smallest faithful rung. A ratio < 1
is a publishable negative.

**Queued (skeptic-surviving):** WSD schedule + critical-batch-size ramp; MTP per-step signal
amplification (couples to axis 6 / #688); kernel-fusion pass beyond fused-Muon.

## 2. Data efficiency — WEAKEST AXIS

**Position.** shards-v0 is a fixed corpus with no curation, dedup-quality, ordering, or
multi-epoch receipts anywhere in the tree. The only data-adjacent receipts are the frozen 50M
pair (#689, blocked on a decisive consumer) and a tokenizer-gap note (#695 receipts). Externally
validated cheap lever sitting unused: n-gram/PPM byte-level blending (+0.080 BPB in the
within-frontier re-measurement of the field challenge) — a zero-parameter capability floor that
also sharpens what the neural params must earn.

**Next decisive experiment → #703:** n-gram blending floor — blend a byte-level backoff model with a
frozen checkpoint at eval time; measure heldout BPB delta vs checkpoint-alone at matched
compute. Kill: delta < +0.02 BPB or blend cost exceeds its BPB gain. Cost: CPU-hours, runnable
during GPU tenancy.

**Queued:** multi-epoch/decay schedules; token-level near-dup detection; code/prose mix
optimization; vocab-size sweep; heldout contamination freeze + live-scan guard.

## 3. Memory traffic

**Position.** The creation-inference gap made concrete: during the live 2.2B leg the GPU
averages ≈30 W at ~4% sampled utilization while ~13 CPU cores run the offload optimizer —
the box is CPU/memory-bound, not GPU-FLOPs-bound. The 79 s/step aggregate has **never been
decomposed** (no per-phase breakdown, no PCIe/DRAM throughput measurement). Inter-block staging
overhead ≈12% (100–112 s per 10-step block). Commit limit is elastic 79.6→~95.6 GB (pagefile
16→32 GB max, observed expanding live); the in-run governor has a block-interior blind window
(#627) with the per-parameter fp32-grad allocation as the intra-step peak driver.

**Next decisive experiment → #702 (step-time attribution):** torch.profiler over ≥10 consecutive
steps; segment forward / backward / optimizer / host↔device copies; measure copy-kernel
throughput vs PCIe 4.0 peak. Kill: if no phase exceeds 25% the axis is balanced (unlikely on
current evidence); else the top phase becomes the named optimization target. Every other lever
on this axis (direct-copy #627 cure, gradient-checkpointing toggle, elastic-limit dynamics)
prioritizes off this receipt.

**Queued:** #627 direct-copy + safe-point governor (CUDA fixture gated); gradient-checkpointing
on/off matched-block measurement; ETW elastic-expansion latency trace; intra-step peak
histogram.

## 4. Optimizer-state cost

**Position.** fp32 moments in file-backed memmaps (file-backed pages charge no commit — the
cure that ended the crash class); muon-local (momentum-only) for matrix params, externally
re-validated at small scale (+0.127 in the field re-measurement). No state-precision or
factorization screens exist.

**Next decisive experiment → #704 (int8 optimizer-state screen):** symmetric per-group quantization of
the file-backed state (quantize at save, dequant on stream-in). Kill: storage shrink < 4×, or
step time +15%, or final stabilize loss deviates beyond the paired-seed band. Couples to axis 3
(state bytes ARE the traffic).

**Queued:** factored second moments for non-muon params; state-precision ladder (int6/int4)
after int8 verdict.

## 5. Training instability at scale — strongest axis

**Position.** The rung ladder with kill bands, planned-outage discipline, in-run governors, and
the transplant-vs-reset program. P-2 CONFIRMED (transplant cos 0.9576 vs reset 0.7304): rung-3
design input flipped to transplant-carries. Boundary-spike base rate banked (#591): block starts
run hot and decay — instrument windows must be trajectory-based, not endpoint-anchored.

**Next decisive experiment:** carry P-2 into the rung-3 prereg (transplant-carries arm) with a
per-step divergence-halt mechanism (skeptic-surviving gap: bands exist per-block, not per-step).

**Queued:** qk-norm and z-loss screens at the next rung (paired seeds); muP-style transferable
hyperparams remain unexamined.

## 6. Capability per token

**Position.** Eval receipts exist (math500, ARC-challenge, MMLU-pro rate checks) but nothing
binds training choices to a per-token capability metric; "better by wide margin vs size class"
has no standing scoreboard. MTP thread is live (#688 config split + hostile-review gate on any
head-quality prereg). Tokenizer efficiency flagged but unmeasured. TTT and depth-recurrence are
field levers with legality/design rules already distilled.

**Next decisive experiment → #705 (unified capability-per-token baseline):** one receipt schema
scoring {frozen checkpoint} × {eval battery} ÷ {training tokens consumed}, emitted at every
rung boundary; seeded with the existing math500/ARC/MMLU receipts. Kill: none (it's an
instrument) — but any rung that regresses capability-per-token forces a design review.

**Queued:** MTP H-Q experiment (gated on the three audit conditions + equal-total control C);
tokenizer-efficiency measurement; n-gram floor as the zero-parameter baseline (axis 2 twin);
TTT per-document trial; depth-recurrence-vs-growth ablation (bears on rung design).

---

## Program rules

1. **One decisive experiment per axis at all times** — an axis whose experiment landed gets its
   next one promoted from the queue the same week.
2. **Skeptic-killed items stay recorded** (THEATER / NOT_FEASIBLE_LOCAL verdicts in the
   receipts) — they are not re-proposed without new evidence.
3. **Claim hygiene:** any efficiency claim states its comparison target (matched-step vs
   fixed-capability; matched-data vs matched-tokens). The 2.4309× lesson is the template.
4. **Live-run receipts are barrier receipts:** every training leg's logs (s/step, VRAM peak,
   watts, kWh, staging overhead, commit trajectory) feed axis positions for free — the
   instrumentation exists; the reading discipline is this document.
