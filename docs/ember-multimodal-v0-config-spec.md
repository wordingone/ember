# ember-multimodal-v0 — config spec (the first unlocker)

**Status:** authored 2026-06-14 (the lead), the lead-class architecture decision per the engineer's
readiness mapping (15615): "first unlocker = multimodal config spec (the lead/the maintainer)."
Unblocks #26 (the engineer builds the architecture extension + config against THIS), which
unblocks #414/#415 → readiness. Grounding: NC2-own contract §8 +
docs/research/gemma4-unified-architecture.md + v0-pretrain-config.json (carry envelope)
+ survey verdicts (components 7/8) + residency design gate.

## I. The four v0 LOCKS — concrete, size-independent (what the engineer builds)

The locks must be in the owned core from step 0 (unretrofittable per §8). v0-text
satisfies 1+4 only; **2 and 3 are the build**.

- **Lock 1 — reserved vocab band. DONE.** Tokenizer has the 8-id multimodal
  delimiter/placeholder band; vocab stays 32000. Config marks those IDs as
  multimodal placeholders.
- **Lock 2 — `inputs_embeds` splice path. MISSING → BUILD.** `forward()` accepts
  `inputs_embeds`; soft tokens (embedder output) **overwrite the embedding rows at
  placeholder-token positions** before the decoder stack. The placeholder positions
  + splice plumbing must exist from step 0 even while v0 trains text-into-the-
  multimodal-skeleton (the splice path is exercised by a synthetic-soft-token
  selftest before any real image data).
- **Lock 3 — per-span bidirectional attention inside the causal mask. MISSING →
  BUILD.** The attention-mask constructor accepts span boundaries and marks
  image-token spans as **bidirectional (full attention within the span)** while the
  rest of the sequence stays causal. Must accept span inputs from step 0 (text-only
  v0 passes empty span set → pure causal, but the capability is wired).
- **Lock 4 — per-channel RoPE, head_dim % 4 == 0. SATISFIED.** head_dim = 1024/16 =
  64; 64 % 4 == 0. Build requirement: the RoPE impl must support the **2D x/y split**
  of head dims (factorized position) so image 2D-RoPE works later; verify v0 RoPE
  factorizes.
- **Plus QK-norm from step 0** (cheap, unretrofittable; z-loss as a flag). Add to
  the config.

## II. Carry-forward envelope (proven — from v0 config + survey)

- **optimizer:** Muon (hidden 2D) + AdamW (embed/norms/head); lr_muon 0.02,
  lr_adamw 3e-4, wd 0.1. (#414 re-measures Muon-vs-AdamW on THIS config — the v0
  fp-44 numbers were 0.37B text, do not transfer.)
- **precision:** BF16 base; int4 QAT tail on **AdamW, not Muon** (survey component 1:
  Muon×QAT published null/negative).
- **objective:** next-token CE (chunked/fused FLCE). **MTP aux heads: carried from v0
  as a DIRECTED component (#5, NC2-own contract) — NOT dropped.** Survey flags
  NEGATIVE quality evidence ≤1B + a re-stage-to-post-hoc-drafter recommendation;
  that is a **re-measure flag for #414-class**, not a drop (only the maintainer abandons a
  directed component). v0 fallback rule preserved (MTP selftest fail → CE-only,
  RECEIPTED, re-enters at v0.1).

> **Mechanism/accounting erratum:** the historical v0 implementation is two
> independent hidden-to-vocabulary auxiliary heads, not DeepSeek sequential
> MTP and not a speculative drafter. The declared split is 368,354,304 base +
> 65,536,000 auxiliary = 433,890,304 realized. Quality remains unscreened (#722).
- **attention:** GQA + FlashAttention + QK-norm. **schedule:** WSD (warmup 0.01 /
  stable 0.85 / decay-to 0.10).
- **governor:** VRAM_FRACTION 0.80 / MARGIN_GIB 1.5 / pacer 0.05s; margin-violation
  auto-kill; **fix-forward BANNED**. Identical to v0.

## III. The embedder + multimodal data (retrofit-proven; the data path is new)

- **Vision embedder (~35M):** 48×48px patch → 6912-float vector → ONE matmul into
  model width (1024) + factorized X/Y position lookups + LayerNorm. Fuyu-style
  **continuous soft tokens, NOT discrete codes**. Retrofit-proven — but the data
  pipeline it consumes does not exist.
- **Audio (defer):** raw 16kHz 40ms → one linear projection. Scope v0 to
  **image-text first**; audio is a later modality (the locks already reserve it).
- **B-MULTI-1 multimodal corpus (NEW eng, separate from B2 text):** image-text pairs
  in encoder-free 48×48px-patch format. AC: patch format matches the embedder input;
  uses the reserved tokenizer band for image-span delimiters. This is the engineer's
  data-pipeline build, parallel to the architecture build.

## IV. The ONE open decision — core size / E2B-surpass (default + revision, NOT a the maintainer-block)

Tension between two the maintainer gates: residency (06-10) = smallest core, pilot small, grow
only if the verify floor demands; vs E2B-surpass (06-14). §8 honesty line: smallest
WORKING encoder-free multimodal = **1.8B** (Mono-InternVL); **sub-1B is unverified**.

- **DEFAULT (ships, no escalation):** the first real multimodal long training = the
  architecture-locked multimodal config at the **v0 size class (~0.37–0.5B dense),
  both modalities trained** (genuinely non-toy — it is NOT text-only). Run as a
  windowed multi-day governed burst. E2B-surpass is the **growth trajectory** (grow
  per the residency gate "only if the verify floor demands"), not the v0 size.
  Rationale: this satisfies BOTH gates — non-toy multimodal (06-14) AND smallest-
  core-pilot-first (06-10) — and reserves, without over-promising, the sub-1B
  capability §8 calls unverified.
- **REVISION TRIGGER (the only thing that escalates to the maintainer on wake):** if the pilot's
  verify-floor receipt shows sub-1B multimodal cannot clear the E2B-surpass floor,
  the core-size/hardware decision (≥1.8B = more VRAM/disk/compute) is **the maintainer's** — a
  hardware-envelope escalation per the residency gate, not a the lead call.

## V. Sequencing (mirrors CC tasks)

1. **the lead — THIS spec. DONE.**
2. **the engineer eng (#26)** — build ember-multimodal-v0 config + architecture extension
   (locks 2+3, 2D-RoPE split, QK-norm, inputs_embeds splice, bidirectional-span
   mask); synthetic-soft-token selftest proves the splice path before real data.
3. **the engineer eng (B-MULTI-1)** — multimodal corpus / data pipeline (parallel to 2).
4. **the engineer eng (B-MULTI-4)** — B3 runner selftest against the multimodal config.
5. **#414** optimizer re-measure on the multimodal config; **#415** density re-test.
6. **Readiness gate** — multimodal-target (this) + DT-6 signal-economics +
   crash-survival (#25) all green → governed launch per pre-auth.

## VI. Honesty / constitutional

This RESERVES sub-1B multimodal capability; it does NOT promise E2B-surpass at
0.5B (§8). The pilot IS the test of that. No directed component is dropped (MTP
carried with a re-measure flag). Failure catalog on record (§8): Fuyu 10.7%
MMBench, EVE stage-skip collapse, Mono-InternVL catastrophic forgetting — the
pilot's kill criteria must watch for the forgetting mode specifically.

Per user direction.
