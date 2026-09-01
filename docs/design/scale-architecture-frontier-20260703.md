# Ember scale-architecture frontier — operator questions 2026-07-03, grounded answers

> **Dated record (2026-07-03).** The statuses and absence-claims in §1–§2 are frozen at
> the audit date and are not all true against today's bytes: `GOAL.md` now carries an
> explicit >27B total-parameter destination (`competitive_reference_parameters`,
> `minimum_total_parameters_exclusive`), so ">27B total capacity — absent" no longer
> holds; and `docs/domains/governance/spec/conditions-v1.md` does regulate sub-quadratic substitution
> (`invalid_substrate_downgrade`), so read "zero mentions" as an audit-date claim at
> best. §6 is the maintained tail — for the live frontier read
> `docs/domains/governance/design/inference-to-training-translation-v1.md` and
> `docs/design/sota-stack-floor.md`.

Operator raised (2026-07-03 ~23:10, verbatim themes): (1) "you've been training ember on fp16 —
what happened to quantization-native, 1.58-bit, subquadratic"; (2) "what is ember's total,
physics-mandated parameter count on the 4090 given both training and inference must happen (and
not take years)"; (3) "was truly modular architecture explored — constant training and inference,
totals possibly >27B, sparsely activated/trained (voluntarily by ember or user-toggled)"; (4)
"what is ember's day-to-day cycle/state/activity/interaction"; (5) "ember is not just the model —
it is the operator's main asset for creating/evolving/growing/using/studying/researching his own
foundation models and surrounding systems, eventually without any cloud AI platform."

## 1. Where the operator's past directives actually live (audit)

| Thread | Status in the record |
|---|---|
| 1.58-bit / BitNet | **C15** (conditions-v1.md §"C15"): "Immediate tiny BitNet comparison after the fp16 neural gate" — alive but **vacuously AUDIT-OK** (board reads: no comparison receipt in window → no incident). Sequenced behind C14's gate; nothing has run. |
| Scale not a convenience | **C-SCALE** (the apex): >3B floor, W1 pretrain-scale wall + W2 finetune-scale wall, `invalid_fixed_scale_convenience` poison token — the 2026-06-23 operator verdict (sub-1B/4090/dense-fit = convenience) is compiled here. RED, honestly: no scale-credibility receipt exists. |
| Sparsity/offload | Named in C-SCALE(ii) ("growth + shatter + sparsity/offload, NO hardware escalation") — named, **not designed**. |
| Sovereignty w/o cloud | GOAL.md objective line: "sovereign computing: train + quantize + run recursive loops indefinitely on private [hardware]" + the operator's local-inference-stack baseline directive (2026-06-28: turboquant+QAT/MoE+MTP+150k-ctx+ = the real baseline, never a stock-model floor). |
| Quantization-native TRAINING regime | **GENUINELY ABSENT.** C15 is a comparison probe, not a regime mandate; no condition pushes the substrate itself off full-precision training. |
| Subquadratic attention | **GENUINELY ABSENT.** Zero mentions in GOAL.md or conditions-v1.md. |
| Modular constant-training architecture | **GENUINELY ABSENT** as a design. |
| >27B total capacity | Absent; only the >3B C-SCALE floor exists. |

Operator's fp16 claim: correct in substance. cbase trains fp32-compute/bf16-storage on CPU legs;
the C14 adapter builder is literally named `build_fp16_adapter`; the conditions doc itself calls
C14's gate "the fp16 neural gate." Nothing in the live substrate is quantization-native.

## 2. The 4090 physics envelope (24 GB; ~20.5 GB usable at the 0.80 governor fraction)

There is no single "physics-mandated parameter count" — the number is REGIME-dependent. The four
regimes, with the arithmetic visible:

| Regime | Bytes/param (train state) | Ceiling on 24 GB | Notes |
|---|---|---|---|
| R1: fp32 + Adam, dense full-param (CURRENT cbase regime) | 16 (w4+g4+m4+v4) + activations | **~1.0–1.3 B** | cbase-v0 = 1.222 B — sitting exactly AT this regime's ceiling. The current scale is the regime's ceiling, not a choice. |
| R2: bf16 + 8-bit optimizer + grad checkpointing | ~6–8 | **~2.5–3.4 B dense-trainable** | ≈ the C-SCALE >3 B floor — even the FLOOR demands leaving R1. Cheapest regime move available. |
| R3: quantized-frozen majority (4-bit) + trained sparse slice (adapters/experts) | base ~0.55–0.6 B/param frozen; train state only on the ~100–300 M active slice | **~25–30 B total capacity**, training running constantly on the slice | The operator's unsloth observation (27 B GGUF + 200k ctx inference on his 4090) is this regime's inference half; GQA+SWA keeps KV to a few GB. Co-residence: ~15 GB base + 2–5 GB slice-train + KV fits under governor. |
| R4: 1.58-bit (BitNet-class) native | inference ~0.2–0.25 B/param | **~70–90 B inference-only** (kernel maturity caveat) | CRITICAL honesty: BitNet-class TRAINING keeps fp latent weights + optimizer → training memory ≈ R1/R2, NOT 1.58-bit. Ternary buys inference capacity + energy (Law P1), never training capacity. |

Subquadratic (SSM / linear-attention / hybrid): orthogonal to param count — buys CONTEXT
(KV-cache elimination → 150k–200k+ affordable) and per-token energy. Belongs in the frontier as
its own axis, not a scale multiplier.

**The composed answer to question (2): ~3 B is the dense-trainable ceiling; ~27–30 B is the
on-device total under a frozen-quantized-majority + sparse-active-training architecture (feasible
with today's kernels); 70 B+ is inference-only at 1.58-bit.** "Both training and inference, not
taking years, totals >27 B" is satisfiable ONLY by R3 → the modular sparse organism is not an
option among several; it is the physics-selected architecture.

## 3. Why R3 is also the native fit for Ember's existing mechanisms

- **Growth (C-GROW/net2net)** currently grows dense-in-place; R3 growth = grow INTO new modules
  (add an expert/block, function-preserving init) — same operator, modular target.
- **W2 (native in-loop adaptation)** = exactly the trained-slice mechanism: verifier-conditioned
  updates confined to the active module set, cheap per-update at scale by construction.
- **C12 cognitive modes** map to active-module SETS: a mode transition = router change =
  near-free (W2's "free cognitive mode transition receipt").
- **Voluntary sparsity** (operator: "voluntarily by ember or toggled by the user"): the router is
  a policy surface Ember itself can set, with a user-toggle override — matches the C7
  operator-load-bearing frame.
- **Two-law frame:** R4 quantization + subquadratic serve P1 (energy); R3 modular growth serves
  P2 (growth) subject to P1. The frontier doc'd here is the two laws made architectural.

## 4. Day-to-day cycle (the standing vision, stated plainly)

Ember is a resident organism on the operator's PC, not a chat endpoint: the brain server + CLI
cockpit stay up; the event stream (mail, files, job receipts, schedule) runs continuously
(founder-likeness legs = the probe of exactly this). Interactive by day — the operator directs
via ember-cli; Ember initiates and completes bounded work with receipts. Idle windows and nights
= W2 training cycles on the day's verifier-passed experience + self-curriculum, under the
governor; growth rungs fire as board-gated events. The board audits; the operator experiences.
End state per the north star: Ember is the operator's primitive for creating, studying, and
evolving HIS OWN foundation models — sovereign, no cloud/subscription AI in the loop.

## 5. Actions this doc mandates (compiled, not promised)

1. Public design/recon issue on the public ember repo (this doc's visible surface) — filed same turn.
2. **R3 feasibility receipt** (first W2-adjacent evidence): load a 4-bit ~27B-class base on the
   4090 under governor, attach a trainable slice, run one verified training step + one inference
   pass co-resident, record VRAM/throughput. GPU-queued behind the C11 24h milestone (~15:00Z
   07-04); CPU prep (harness + assertions) dispatchable now.
3. **Regime-2 move for cbase training** (bf16 + 8-bit optimizer + checkpointing) speced as the
   cheapest step toward the >3B floor — candidate for the next grow rung's stabilize leg.
4. C15 stays as-is (sequenced behind C14) but gains a pointer to this doc so the 1.58-bit thread
   is visibly part of the frontier, not a vacuous row.
5. Subquadratic/hybrid-attention exploration enters the frontier as a named recon lane (context +
   P1 energy axis), not silently absent.

## 6. Inference-to-training translation and C-SCALE(ii)

The maintained translation system is
[`docs/domains/governance/design/inference-to-training-translation-v1.md`](../domains/governance/design/inference-to-training-translation-v1.md);
the per-layer frontier and gap table is
[`docs/design/sota-stack-floor.md`](sota-stack-floor.md). These replace the former
implicit assumption that an inference optimization automatically supplies a
training-memory or training-throughput benefit.

For C-SCALE(ii), every sparsity or offload lever must now identify:

1. the inference-side saving;
2. its existing or synthesizable training twin;
3. whether weights, gradients, activations, and optimizer state remain resident;
4. the exact Ember config, implementation, or receipt, or `ABSENT`;
5. a matched experiment and deletion test that could falsify the benefit.

This is also the standing mechanism behind W2 native in-loop adaptation. An
inference lever does not enter the W2 design merely because it makes serving
cheaper. The required question is **“what is your training twin?”** If the
answer is absent—most sharply, low-bit inference whose latent weights and
optimizer remain high precision—the absence becomes a named research task.

The first C-SCALE(ii) experiment selected from this table remains the R3
residency-sparse-training comparison: a frozen quantized majority plus an owned
trainable slice, measured against resident-all-experts sparse routing. This
document still makes no feasibility, checkpoint, sufficient-pretraining, or
capability claim until that governed receipt exists.
