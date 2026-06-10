# Dynamic teacher system — HF hub as a sampler pool (design note)

*2026-06-10. Source: user thread ("could huggingface cli be leveraged as a dynamic
teacher system for ember? think GDM + huggingface cli"). Interpretation: GDM =
Darwin Gödel Machine (the self-modification-behind-empirical-gate lineage from the
novelty sweep); the analysis is the same if GDM meant the lab — the substance is
dynamic teacher acquisition. Status: design note + admissibility analysis. No GPU
work launched from this note; sequencing is gated on the 3B verdict.*

---

## 1. The idea, stated in ember's objects

The HF hub is ~2M frozen samplers behind one CLI (`hf download` + local
inference). A **dynamic teacher system** gives the accumulation loop a new
action: *acquire a teacher model T, run it locally as a sampler on an admissible
world, pass its outputs through the world's verifier, burn only verified
episodes into the ledger, retire the teacher.* In formalization-v0 terms:

- A teacher is **just another `π` in the sample step** of round operator R (§2).
  Nothing else in the loop changes: `verify → ledger → compile → gate` is
  sampler-agnostic by construction.
- The verifier axiom is untouched: **teachers propose, the world disposes.**
  `V` stays world-grounded, never learned, never a model. A teacher never
  grades, never rewards, never labels. (This is the line that separates this
  design from LLM-as-judge / RLAIF distillation, which stays banned.)
- The episode receipt extends with **sampler provenance**: `sampler_id`
  (HF model id + revision hash + quant config) per episode. This is what makes
  G3 leave-set-out recompile work *per teacher* — delete teacher T's episode
  set, recompile, measure.

## 2. Why this is the natural answer to the starvation receipt

The measured problem (q15 receipt, §3 of formalization): `F(θ_core, ARC-1, k=8)
= 0` at 1.5B. The loop starves because the core's own solve probability is below
the affordable-budget floor. Two registered repairs exist: restructure the world
(W-code, `research/world-choice.md` §6) or raise the sampler. A teacher pool is
the second repair **without violating residency** — the core stays small and
resident; the teacher runs in bounded bursts and is then evicted. The feed-rate
algebra:

```
F_pool(W, k) = feed by ANY admitted sampler; core distills via existing compile.
```

SOAR's own data says the same thing from the other side: pooled-archive
retraining beats own-data-only (2507.14172 Table 5). The teacher pool is the
verified-only, receipted version of that pooling.

## 3. Teacher admission — the §7 symmetry

Worlds are admitted by a *pre-commit measured floor* (§7a). Teachers get the
mirror criterion (§7b):

```
admit T for world W  iff  measured F(T, W, k_affordable) / GPU-hour
                          beats the core's, on a receipted probe,
                          BEFORE committing acquisition + sampling budget.
```

The objective stays C3's verifier-bits-per-GPU-hour — it now allocates budget
across `{core, T_1, T_2, …}` instead of just the core. Retirement is the same
metric trending below the core's (or below the next candidate's). Acquisition,
admission probe, sampling allocation, retirement: all receipted, all mechanical.

**Zero-new-code observation:** `w1_mbpp.py` already takes an arbitrary model id
and emits `feed_tasks / feed_pct / feed_ci95` + GPU-time — it IS the
teacher-admission instrument for W-code. `t1_probe` is the same for ARC. The
first teacher probe costs nothing to build.

## 4. The gate already covers the failure modes

- **Off-policy style mismatch (live hazard):** the q3 taxonomy shows SFT can
  teach ledger *surface form* while raising crash rate — a teacher's token
  style may be incompressible into a small core, making teacher episodes
  worse-than-useless for compile. G1/G2 exist exactly to catch this: admission
  probe (feed rate) is NOT the burn decision (gated gain). A teacher can feed
  prolifically and still fail the gate; then its episodes don't burn.
- **G2 sharpens, not weakens:** control arm = equal-volume *unverified teacher*
  outputs — isolating verification from teacher quality. This strengthens the
  C2-narrowed claim's scientific core rather than diluting it.
- **DGM lineage (the GDM half):** teacher routing/admission policy is a harness
  artifact `δ_H` behind the same gate (§6) — the loop can eventually *edit its
  own teacher market policy*, gated. That is an NC1+ item; at NC0 the policy
  stays a fixed mechanical rule (the §7b criterion above).

## 5. Goal tension — named, not papered over

GOAL.md: improvement comes from "its own experience"; "nothing load-bearing is
borrowed"; but also "the cloud minds, the borrowed cores … are scaffolding and
rehearsal." Teachers are scaffolding — admissible under the goal's own end-test:
**turn them all off and what remains must still be a mind.** Operationalized:

1. **Round-2's self-generated-episodes requirement is NOT substitutable.**
   Teacher feed accelerates reaching a measurable own-floor; it never replaces
   the requirement that core-generated episodes pass the gate.
2. **Own-feed fraction** becomes a tracked metric: share of gated gain
   attributable (per-teacher G3 leave-set-out) to core-generated vs
   teacher-generated episodes. Goal satisfaction requires it trending up;
   permanent teacher dependence = the loop is a distillery, not a mind.
3. Teacher weights are **disposable cache, never identity** — only ledger
   episodes persist (C1). Disk cap + eviction policy required (escalation rule:
   >100GB needs sign-off; a teacher pool can blow that quickly at fp16 — cap
   the cache, prefer q4).

## 6. Claim discipline

Verified distillation from a stronger teacher is heavily trodden (Orca/
MetaMath-class pipelines; RFT 2308.01825 with own-model). This design is an
**instantiation under C2/C3-narrowed, not a new claim.** The possibly-novel
sliver — *dynamic, measured, receipted teacher admission/retirement under
consumer-machine residency* (a "teacher market" with pre-commit feed-per-GPU-hour
admission) — gets its own adversarial lit check before any claim is written.
Until then it is engineering.

## 7. Constraints (mechanical)

- **Local-only:** teachers run on this machine (4090 ⇒ ~7–14B q4 bursts under
  the governor). HF Inference Endpoints / any cloud inference = escalation-only.
  `HF_HUB_OFFLINE` flips off only for the explicit acquisition event (MBPP-pull
  precedent), then back on.
- **Governor:** teacher inference goes through the same governed load path +
  decode pacer as the core. No exceptions for "it's just a probe."
- **License check per model** at acquisition time, recorded in the receipt.

## 8. Placement — local hf-cli vs HF compute (user question, 2026-06-10)

The question: should teachers run on HF compute (Inference API / Endpoints)
instead of locally, so they don't compete with ember for the one GPU?

**Decision: local hf-cli is the default.** Four reasons:

1. **The admission metric already prices the competition.** Feed-per-GPU-hour
   is measured against the alternative use of that same GPU-hour by the core.
   A teacher that can't beat the core's use of the hour isn't admitted — the
   "competition" is the test, not a problem to engineer away.
2. **Receipt integrity.** Local = revision-pinned weights + exact quant config
   + reproducible decode params. Serverless endpoints can change serving
   config silently; sampler provenance in receipts weakens to "whatever HF
   served that day." Paid dedicated endpoints pin revisions but are spend.
3. **Zero spend, zero egress.** Free-tier serverless is rate-limited far below
   probe scale (k × tasks ≈ thousands of generations) and non-pinnable; paid
   endpoints are buying back datacenter GPU-hours — the exact inversion the
   residency frame exists to resist.
4. **Verification already doesn't compete.** The sandbox is CPU-side; only
   generation contends for the GPU, and teacher generation is an idle-window
   burst by design.

**What the question gets right (registered, not adopted):** generation is the
GPU hog and verification is not — offloading teacher *generation* to compute
we don't own frees the whole 4090 for train/verify, a real pipeline split. It
is admissible in principle: cloud teachers don't touch the verifier axiom
(proposals verify locally) and fall under the same scaffolding clause as the
cloud founders themselves. But it is spend + task-data egress, both behind the
standing escalation line. **Named escalation trigger:** if a post-verdict
receipt shows (a) an admitted teacher's feed-per-GPU-hour substantially beats
the core's AND (b) GPU time is the binding constraint on round cadence (idle
windows can't supply the sampling budget the admission math says is worth
buying), the cloud option returns as a specific ask — named model, endpoint
type, $/GPU-hour, expected verifier-bits per dollar. Until that receipt
exists, paying for cloud teachers is optimizing an unmeasured bottleneck.

## 9. Lit-check verdict (Haiku adversarial sweep, 2026-06-10)

**SURVIVES-NARROWED** — same shape as C1–C4. Closest prior art per area:
RouteLLM (2406.18665) cost-quality routing = inference-time, not data
generation; GRACEs (2511.02833) teacher *selection* from a fixed set, no
dynamic pool / no per-cost measurement; RFT (2308.01825) / Orca (2306.02707)
verified filtering with FIXED teacher — the verifier component is standard;
SOAR (2507.14172) single-teacher measured-student-progress; In-Run Data
Shapley (2406.11011) per-source attribution but POST-HOC; **DataEnvGym
(2410.06215) = closest** — dynamic budgeted allocation across data-generation
*skills* with student feedback, but skills not models, no per-GPU-hour
admission, no receipts. Surviving claim (integration only, no single
component): dynamic multi-teacher pool + pre-commit feed-per-GPU-hour
admission + world-grounded verification + receipted per-teacher episode
attribution, in one online loop on consumer hardware.

## 10. Sequencing (gated on the 3B verdict — nothing fires from this note)

- **3B all-zero → W-code restructure (already registered):** the w1 floor
  probes (`w1_floor_q15/q3`) measure the core's F on MBPP; add ONE teacher
  candidate probe (7–8B coder class, q4) on the same harness in the same idle
  window. Two receipts, one comparison, admission decision recorded.
- **3B nonzero → s15→arc2→t5 chain proceeds;** teachers remain admissible later
  for worlds where the core's floor is positive but tiny.
- Either way: teacher episodes enter the ledger only through the existing
  schema + provenance extension (rides the W-code ledger-ingest wiring item
  already queued).
