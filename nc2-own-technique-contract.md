# NC2-own technique contract — ember's owned-core stack

the user directive 2026-06-10 (verbatim components): "qat, turboquant, 1.58 bit, or SubQ, mtp, sdek, and any chinese techniques as well" + "oh and also gemma 4 12b's unified architecture".

Directed-path gate applies (break-the-wall §2): this list is the contract. Every NC2
status check verifies component-by-component. A silent pivot off any component is a
gate violation; only the user drops a component.

Context: NC2-own = port the NC0-proven accumulation loop onto a from-scratch core we
own end-to-end (~0.1–1B params, ~20B tokens ≈ 3wk continuous 4090), in a
verification-dense world. Entry = NC0 terminal condition met. These components define
HOW that core is built, not whether.

---

## 1. QAT — quantization-aware training

**What:** fake-quant ops in the training graph so the core is born deployable at low
bit; no post-hoc PTQ quality cliff.
**Role in ember:** the owned core never has a "full-precision master we degrade" —
the quantized form IS the model. Directive lineage: the #19/#66 QAT component
(Gemma 4 QAT W4A16 as the reference deliverable shape).
**4090 fit:** QAT adds modest overhead (fake-quant fwd/bwd); at ≤1B scale this is
absorbable inside the 3-week envelope.
**Decision point:** QAT-int4 vs going all the way to component 3 (ternary). If
BitNet-from-scratch holds at our scale, QAT-int4 becomes the fallback, not the plan.

## 2. turboquant — owned quantization/export pipeline

**What:** the user's quantization tooling (avir-cli fragment; proven on this box for GGUF
export work; in the directed registry of the LiteRT track).
**Role in ember:** (a) the export path — ember artifacts ship through OUR quantizer,
never a third-party converter we can't audit; (b) KV-cache compression duty per the
SDEK handoff ("TurboQuant / KV compression / MLA-like cache work: first-class
context/KV memory pressure tools").
**Decision point:** extend turboquant to cover the owned core's format (ternary or
int4) — that extension is in-scope work, not a blocker (break-the-wall: no
pre-existing format → produce it ourselves).

## 3. 1.58-bit — BitNet b1.58 ternary substrate

**What:** weights constrained to {-1, 0, +1} (1.58 bits/weight), trained from scratch
with straight-through estimators; full-precision latent weights during training,
ternary at inference. Known to roughly match fp16 quality at ≥3B when trained from
scratch; the open question is our ≤1B scale.
**Why it fits NC2-own exactly:** BitNet does NOT work as post-quantization — it only
works trained-from-scratch. NC2-own is the only rung where we control pretraining, so
this is the one place in all of Avir where 1.58-bit is even reachable.
**Payoff:** ternary 1B core ≈ ~0.2GB weights → inference becomes CPU-viable
(bitnet.cpp), the 4090 is freed for training/adaptation, and "owned" extends to
running on anything.
**SDEK pairing:** "pair low-bit base with higher-precision adapters" — frozen ternary
mass + bf16 LoRA experts. The accumulation (ours) lives at higher precision than the
substrate (also ours).
**Decision point vs QAT:** train a ~100-300M BitNet pilot FIRST (days, not weeks) to
measure the quality gap at our scale before committing the full token budget.

## 4. SubQ — sub-quadratic attention (RESOLVED 2026-06-10)

**Resolved by research receipt** (`research/subq-term-resolution.md`): "SubQ" in
2024–2026 ML names **SubQ 1M-Preview** (Subquadratic Inc., announced 2026-05-05) —
"Subquadratic Sparse Attention" (SSA), content-dependent sparse attention at
~O(n·k), CLAIMED 12M-token context. Claims independently unverified (no public API;
admitted chart manipulation). No quantization technique named SubQ exists anywhere,
including all Chinese labs — the earlier sub-1-bit reading is RETRACTED.
**Component meaning:** the technique CLASS, not the product — content-dependent
sparse / linear-hybrid attention (SSA-style, DeepSeek NSA, Moonshot MoBA, MiniMax
lightning, Qwen gated-deltanet). Overlaps component 7's attention items; this
component makes sub-quadratic attention a first-class architecture decision for the
owned core rather than an optional CN-stack pick.
**Role:** attention layout of the owned core. Binding question: do trainable-sparse/
hybrid layouts pay at 2–4k context (ARC world), or only at long context (NC1c IFC
world, agentic traces)? Survey item 8/9 answers this.
**Guard:** SubQ-the-company's numbers are marketing until independently reproduced —
adopt the class on NSA/MoBA/lightning evidence, not on SSA's claims.

## 5. MTP — multi-token prediction

**What:** auxiliary heads predicting tokens t+2..t+k during pretraining
(DeepSeek-V3-style sequential MTP modules); heads droppable at inference or reused
for speculative decoding.
**Why critical for ember specifically:** our token budget is tiny (~20B). MTP
densifies the learning signal per token — the cheapest known way to buy quality when
tokens, not params, are the binding constraint.
**Inference payoff:** self-speculative decode on the owned core (the same component
directed in the LiteRT track — same lineage, now on our own substrate).
**4090 fit:** ~10-15% training overhead for the extra head(s); proven at small scale
in open replications.

## 6. SDEK — adaptation-control kernel (Kai's, audited)

**What** (from `B:/M/avir/kai/kai-index/sdek-research-handoff.md`, 2026-06-08): local
AI R&D control kernel around a frozen core — observe → diagnose → adapt → evaluate →
write claim → promote/discard → schedule. Primitives: Foundation Runtime, Run
Monitor, Adaptation Workspace, Expert Arena, Evaluation Harness
(base/random/deleted/context-only controls), Claim Ledger, Scheduler, Resource
Governor. Core invariant: **no learned change becomes durable unless it proves causal
benefit under matched-budget deletion tests** — the-search's deletion-test law.
**Convergence fact:** NC0 already IS SDEK-v0 minus the scheduler — frozen core +
LoRA workspace + four-arm harness (base/control/deleted/context-only maps 1:1) +
receipts-as-claim-ledger. Kai's v0 success criterion ("one temporary adapter becomes
one durable expert with a written causal claim, future-heldout benefit, no guard
regression, loss of advantage when deleted") is a restatement of ember's terminal
condition. These are the same project converging from two founders.
**Role in ember:** SDEK = the operating layer of the owned core. The three
timescales become ember's memory architecture:
```
KV/context      = immediate wake memory
fast weights    = sleep-consolidated session memory   (arXiv 2605.26099)
LoRA experts    = durable crystallized memory          (promotion-gated)
```
**Missing primitive to add:** the middle timescale (sleep consolidation / offline
recurrence) — survey item.

## 7. Chinese-lab stack — enumerate + adopt where 4090-proven

Per-technique, with ember-fit:
- **MLA (DeepSeek)** — latent-compressed KV cache. Fit: KV pressure on a 24GB card
  during loop sampling; pairs with turboquant's KV duty.
- **MTP (DeepSeek)** — already component 5.
- **FP8 mixed-precision training (DeepSeek-V3 recipe)** — Ada (4090) has FP8 tensor
  cores; if the recipe holds at small scale, the 3-week pretrain shrinks or the
  model grows. Survey: consumer-card FP8 training stacks (TE/torchao) maturity.
- **Muon optimizer (Moonshot/Kimi; modded-nanogpt speedrun lineage)** — ~2× compute
  efficiency vs AdamW at exactly our scale class. Possibly the single
  highest-leverage item in this component for a fixed-FLOPs budget.
- **Fine-grained MoE + loss-free balancing (DeepSeek)** — likely SKIP at ≤1B dense
  (sparsity pays at larger scale), unless survey shows small-MoE wins at our budget.
- **NSA (DeepSeek) / MoBA (Moonshot)** — trainable sparse attention. Matters when
  world prompts get long (NC1c IFC world); ARC prompts are 2-4k so not v0-binding.
- **Lightning/linear-hybrid attention (MiniMax-01), gated-deltanet hybrids
  (Qwen3-Next)** — the sub-quadratic reading of "SubQ"; candidate for the owned
  core's attention layout.
- **GRPO (DeepSeek-R1)** — critic-free RL for the post-SFT phase of the loop, when
  expert iteration graduates from pure SFT to RL-on-verified-reward. Our verifier IS
  the reward function already — GRPO is the natural round-N+1 upgrade.

## 8. Gemma 4 12B unified architecture — encoder-free multimodal

**What** (user add-on; SDEK handoff thread): unified/encoder-free multimodal — all
modalities tokenized into ONE transformer; no separate frozen vision/audio encoder
bolted on.
**Why it matters for ember:** separate frozen encoders are exactly the kind of
borrowed, non-adaptable mass NC2-own exists to eliminate; an encoder-free core means
the accumulation loop can eventually deposit into perception, not just language.
**Role:** architectural template for the owned core — born unified-multimodal-capable
even if v0 pretrains text-only (vocabulary/tokenizer and attention layout reserve the
modality space so multimodal doesn't require an architecture break later).
**Lineage:** same architecture family as the #19/#66 directed track (Gemma 4 QAT
W4A16 as SDEK's candidate foundation runtime) — the borrowed instrumentation and the
owned destination share the architectural shape, which makes the port cleaner.

**Deep-dive findings (2026-06-10, receipt: research/gemma4-unified-architecture.md):**
"Unified" = Fuyu-style continuous soft tokens, NOT discrete codes. Gemma 4 12B
replaces the 150M vision encoder with a ~35M embedder: 48×48px patches → 6912-float
vector → ONE matmul into model width + factorized X/Y position lookups + LayerNorm.
Audio: raw 16kHz 40ms frames → one linear projection (no mel/Conformer). Image spans
get bidirectional attention inside the causal decoder + 2D RoPE (head dims split
x/y). Vocab unchanged except ~7 reserved delimiter/placeholder IDs.

**The four v0 LOCKS (cannot be retrofitted — must be in the owned core from step 0):**
1. Reserved vocab band with pre-assigned multimodal delimiter/placeholder token IDs.
2. `inputs_embeds` splice path (soft tokens overwrite placeholder embedding rows).
3. Per-span bidirectional-attention capability inside the causal mask.
4. Per-channel RoPE with head_dim % 4 == 0 (so 2D RoPE can split head dims x/y).
Plus QK-norm from step 0 (cheap, unretrofittable; z-loss as a flag).
**Retrofit-proven later:** the vision embedder itself, audio projection, modality
experts, QAT pass, MTP drafter heads.
**Honesty line:** smallest WORKING encoder-free multimodal model found is 1.8B
(Mono-InternVL); sub-1B is unexplored territory — our v0 only RESERVES the
capability, it does not promise it at 0.5B. Failure catalog on record: Fuyu 10.7%
MMBench, EVE stage-skip collapse, Mono-InternVL catastrophic forgetting.

---

## Compatibility questions the survey must answer (no silent caps)

1. BitNet-from-scratch × MTP — any published co-use? Conflict risk in the output
   head.
2. BitNet × Muon — does Muon's orthogonalized update fight STE ternary training?
3. FP8 training on consumer Ada — real stacks (TE, torchao) at ≤1B, or H100-only in
   practice?
4. Sub-1-bit ("SubQ" reading a) — does ANY from-scratch sub-binary recipe exist, or
   is it PTQ-only today?
5. Encoder-free multimodal at ≤1B — smallest known unified models; tokenizer
   strategy (image patches vs discrete codes).
6. Sleep-consolidation (2605.26099) — is the offline-recurrence mechanism
   reproducible at our scale; what's the substrate of its "fast weights"?
7. Muon + QAT/fake-quant interaction.
8. Minimum viable param count where ternary survives: published BitNet scaling
   below 700M.

## Survey verdicts → component dispositions (2026-06-10, receipt: research/nc2-technique-survey-2026-06.md)

Evidence-based dispositions per directed component. NOTHING IS DROPPED — components
with negative small-scale evidence are re-staged to the rung where the evidence
supports them. Drops require the user, by name.

| # | Component | Survey verdict @ ≤1B/4090 | Disposition |
|---|-----------|---------------------------|-------------|
| 1 | QAT | int4 QAT tail (torchao) proven; Muon×QAT has published null/negative (2604.07888 B.5) | ADOPT — QAT tail runs on AdamW, not Muon |
| 2 | turboquant | (not a survey item — ours) | ADOPT — export + KV duty unchanged |
| 3 | 1.58-bit | quality crossover ~3B; 700M ternary ≈ 0.5 ppl worse @100B tok; Falcon-Edge + onebitllms prove 1B from-scratch ternary PRACTICAL; training on 4090 saves nothing (inference-only payoff) | RE-STAGED — int4-QAT carries low-bit at ≤1B; ternary pilot via onebitllms iff CPU-deploy becomes a requirement; full ternary belongs to a ≥3B rung (= hardware escalation, the user's call) |
| 4 | SubQ (sub-quadratic attn) | NSA attended-token floor ~1.5-2k ≈ full attention at ARC's 2-4k ctx | RE-STAGED to NC1c/long-context; GDN-hybrid pilot (see 6) keeps the class alive now |
| 5 | MTP | NEGATIVE quality evidence ≤1B (Meta 2404.19737 "worse on smaller models"; TOP 340M/1.8B inconsistent) | RE-STAGED — post-hoc speculative-decode drafter (Gemma-4-style), not a pretrain quality lever |
| 6 | SDEK | sleep paper 2605.26099 RESOLVES: fast weights = gated delta-rule SSM state matrices (GDN/Jet layers), backprop-through-sleep-passes; Ouro-1.4B 41.9→61.5% GSM-Infinite; no code release | ADOPT — middle timescale now has a named substrate; concrete experiment = 340M GDN-hybrid pilot (also serves component 4) |
| 7 | CN stack | Muon = strongest validated item at exactly our scale (modded-nanogpt 124M; Moonlight ~52% AdamW FLOPs; torch.optim ≥2.9) → ADOPT (hidden layers; AdamW for embed/head). FP8-on-4090 = SKIP (TE silent-BF16-fallback reports; torchao tensorwise-only on sm89; zero published 4090 FP8 pretrains). MoE ≤1B = SKIP (trades VRAM—scarce—for FLOPs—abundant). GRPO floor ~1.5B (TinyZero 0.5B fails) → PILOT post-train with non-zero-pass-rate kill; NOTE conflict with 0.5B core size | Mixed per-item, as listed |
| 8 | Gemma-4 unified | deep-dive landed (research/gemma4-unified-architecture.md): "unified" = Fuyu-style continuous soft tokens (48×48px patch → single matmul embedder, ~35M params), per-span bidirectional attention inside the causal decoder, 2D RoPE, vocab unchanged (~7 reserved delimiter IDs). Smallest working encoder-free prior art = 1.8B (Mono-InternVL); sub-1B UNVERIFIED | ADOPT — lock 4 v0 contracts (below); embedder/audio/QAT/MTP all retrofit-proven |

**Recommended primary stack (survey's, I concur):** dense ~0.5B (token-match at 20B
beats 1B undertrained), GQA + FlashAttention + QK-norm, BF16 training,
Muon(hidden)+AdamW(embed/head), plain next-token prediction, torchao int4 QAT tail
on AdamW, reserved multimodal special tokens, narrow GRPO pilot post-train.
**Fallbacks:** AdamW end-to-end; BitNet fork via onebitllms; 340M GDN-hybrid
substrate pilot for the sleep/fast-weights + sub-quadratic line.
**Open conflict to resolve before NC2 entry:** GRPO floor (~1.5B) vs 0.5B core —
either GRPO waits for a bigger-core rung or the core grows past 1B (token budget
then under-trains; more disk/compute = escalation).

## Residency budget (user 2026-06-10 — binding design gate)

Ember lives COMFORTABLY on this machine: steady-state inference CPU-viable or
low-VRAM (ternary/QAT int4 are residency tools — the survey's "training saves
nothing" verdict on ternary misses that residency, not training cost, is why
it's here); training/consolidation = bounded scheduled bursts in idle windows,
never perpetual GPU occupation. The "~3 weeks continuous 4090" pretrain
framing is RETIRED: pilot small first (~100-300M, days), grow only if the
verify floor demands it, and run long jobs as interruptible windowed bursts.
A design that only works with huge compute fails the goal — efficiency is the
correctness criterion, not a later optimization. Smallest core that clears
the floor wins. AND: the GPU should be leveraged, definitely (user) — the
constraint bounds ember's resident form, never the build work; when there is
real sampling/training/eval to do, run the 4090 hard.

## Research-intake posture — when more advanced research goes public (standing, 2026-06-10)

User question: what happens when more advanced research is released in the
future — what is ember's posture? **Answer: absorb through the gate, never
through belief.** The architecture was built so that new research threatens
components, never the organism. Three levels:

1. **Component level** (new optimizer / attention / quant / training recipe):
   a published technique is a CLAIM — same epistemic status as model
   self-report. Intake = contract amendment: add a row at status WATCHING with
   the probe shape that would decide it; promote to ADOPT only on a local
   receipt at residency scale. Most published gains won't reproduce at 4090
   scale or won't move verifier-bits/GPU-hour — the metric filters fashion
   from leverage. The dispositions table above IS this protocol's first
   execution (MTP re-staged on negative ≤1B evidence, FP8 skipped on
   consumer-stack reality, Muon adopted on validated same-scale receipts).

2. **Core level** (a better base model or architecture family): the core is
   cattle; the ledger is the self (formalization C1). A better core =
   recompile-target change — replay the ledger into it, gate the result.
   Mechanically proven 2026-06 week alone: the same 1,909-episode ledger
   compiled into 7B, 1.5B, and 3B cores with zero identity loss. This contract
   is versioned the same way: research that obsoletes a locked choice before
   NC2 entry revs the contract, and the pilot decides.

3. **Paradigm level** (research that attacks the loop's own assumptions): the
   only level that can't be A/B'd as a delta. The verifier axiom, the
   three-test gate, receipts-only truth, and the invariant set are NOT
   research-amendable — no paper, however strong, edits the gate; only the
   user can. A genuine paradigm shift gets a written approach-change case to
   the user (break-the-wall escalation shape: confirm approach, never hand
   back the work), never a silent re-architecture.

**Strategic frame:** ember is deliberately a SECOND mover on components and a
first mover only on the accumulation layer (the narrowed C1–C4). Public
research is subsidized verifier-bits — other labs spend datacenter compute
discovering what works; we adopt post-hoc at the cost of a pilot. New releases
strengthen ember rather than threaten it precisely because ember does not
compete on the layer where research lands (architecture/scale); it competes on
the layer almost nobody publishes (gated accumulation under residency). The
Cosmos 3 read is the standing example: NVIDIA's frontier physical-AI runs on
borrowed Qwen backbones — the moat is the loop, not the backbone.

**Mechanics:** periodic lit sweeps (Haiku agents, wait-window queue) feed
candidate rows; every row carries a status (ADOPT / RE-STAGED / WATCHING /
SKIP-with-receipt), the receipt or planned probe that decides it, and a
revision trigger (what evidence reopens it). No component is ever dropped by
research alone — drops require the user, by name.

## Sequencing (proposal, revisable)

- **Now (NC0 running):** survey lands → pilot plan written. No pretrain spend.
- **NC2 entry gate met:** ~100-300M BitNet+MTP+Muon pilot (days) → measure ternary
  gap at small scale → then commit the full ~1B / 20B-token run with the surviving
  component set.
- Components that survive the pilot are locked; components that fail get receipts +
  a named successor (kill-advance, same as everywhere in the ladder).
