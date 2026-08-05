<!-- EMBER_ARTIFACT_CLASS=historical_only -->

# Multimodal-unified v0 pretrain — launch authorization brief (maintainer-facing, pre-staged)

**Status:** authored 2026-06-14 (the lead). **SUPERSEDES `pretrain-launch-authorization-brief.md`**
(that brief authorizes the pre-pivot C04 *text* pretrain — 2.2B-token, 0.37B text,
Muon-vs-AdamW; moot under the maintainer's 2026-06-14 reactivation, which made the
*multimodal-unified* config the launch target). This brief packages the GO for the
run the reactivation actually names. Pre-staged like its predecessor: every gate
pre-written so the moment readiness hits 3/3 the launch is execution, not
improvisation. **Authoring this is pre-staging, not launching** — no run starts
from this doc.

Companion: `docs/ember-restart/ember-multimodal-v0-config-spec.md` (the architecture — the 4
locks, carry envelope, embedder, the §IV core-size decision). This brief is the
*authorization* layer on top of it.

## What is being authorized

The **multimodal-unified v0 governed pretrain** — the architecture-locked
multimodal config (locks 1–4 + QK-norm), **both modalities trained** at the v0
size class (~0.37–0.5B dense per config-spec §IV default), run as a windowed
multi-day governed burst on this machine alone. Genuinely non-toy — it is NOT the
text-only run the maintainer explicitly ruled out ("not a half assed readiness that plans to
train a toy text only model"). E2B-surpass is the growth *trajectory* from this
pilot, not the v0 size (config-spec §IV).

## The three readiness preconditions — ALL must be green (pre-authorized launch is gated on these, not on the lead's word)

| # | Precondition | Gate (receipt-class, never self-report) | Status 2026-06-14 |
|---|---|---|---|
| 1 | **Multimodal-target trained on real data** (never text-only, never synthetic-only) | **END-TO-END real-data smoke** of the launch harness on the §IV config + a valid real-data tok/s on the 368M/L20 config = the N-basis. Wiring + launch-config lever are BOTH the gate. | **GREEN (2026-06-16, source-verified PR #441 / ER-2d).** The §IV 368M/L20 harness trains on REAL matched image-text data, packed to 4096 tok/step; FINAL tok_s_paced=8,627.0 -> N=745M/gov-day; healthy 35.5/65.45 mix; binding_preserved + Lock-4 multi-image RoPE fixed. Full resolution + the 6-catch history below. |
| 2 | **DT-6 signal-economics** | A diagnostic/pilot PASS must read as **verified-signal-per-GPU-hour** (equal-wall-clock band), not "it ran" — `scripts/loop_econ_gate.py` emits the metric and gates on it | **GREEN (2026-06-16, source-verified)** — #430/PR #432 `loop_econ_gate.py` exists + committed; selftest 3/3 (AC1 REJECT missing-signal, AC2 ACCEPT valid, AC3 REJECT within-floor; failures:[]). The economic-PASS gate (verified-signal-per-GPU-hour > equal-wall-clock band) is mechanized. |
| 3 | **Crash-survival** | Founder roster + workspace recover automatically after a real PC restart | **GREEN** — the 2026-06-14 restart recovered full roster + workspace (the maintainer-confirmed); the ultimate drill, not a synthetic one |

Readiness: **3/3 GREEN** (2026-06-16, source-verified). **Precondition-1 = GREEN (ER-2d).**
The the maintainer ping (#13) is ARMED — held for the maintainer's wake (he is asleep; no ping while asleep).

**ER-2d — DONE, precondition-1 GREEN, FINAL N (source-verified on PR #441 branch
`eng/437-er2d`, the lead-signoff posted; merges on auto-merge).** `receipts/ember437-er2d-20260616T072423Z.json`:
the launch loader is now packed AND correspondence-preserving. Verified **at source, not from
flags** — `MatchedPackedCorpusLoader.next_batch` packs K=8 matched pairs per seq, each image's
patches immediately followed by **that same pair's caption** (`[DELIM_START, patches×n,
DELIM_END, cap×64]`), so `binding_preserved=true` is real code; and the **Lock-4 multi-image
RoPE** is fixed (`img_offset` per-span slice of x/y positions — multi-image now supported, the
wall broken). `tok_s_paced=8,627.0` / raw 9,661.3 at PACKED `tokens_per_step=4096`, §IV model
(params 377,586,688, n_layers=20), 200/200, `er2d_pass=true`, loss →1.22.
- **FINAL N (replaces the ER-2c provisional):** 1 governed day affords `8,627.0 × 86,400 ≈
  745M tokens`. Chinchilla-optimal 20·P = 7.37B → ceiling `≈ 9.9 governed days`. The matched
  loader is ~2× slower than the ER-2c throughput shortcut (8 images/seq → ~5.5× more patch
  tokens) — exactly why N had to be measured on the real loader; the provisional would have
  under-provisioned governed-days ~2×.
- **Launch mix is HEALTHY (35.5% patch / 65.45% text):** both modalities substantially present
  — neither text-starvation (§3's original fear) nor the image-starvation of ER-2c's 6.4%
  artifact. The matched loader balances the mix naturally; the grounding floor is well-supported.
- **Minor refinement noted (not a gate-blocker):** the loader truncates images to the pool's
  min n_patches for uniform shape; for CC3M fixed-resolution patches min≈max, so negligible,
  but a refinement for the scaled corpus (ER-3).

precondition-1 is now genuinely green: the launch harness trains the §IV 368M model on REAL
**matched** image-text data, packed to the launch config (4096 tok/step), with a valid FINAL N
and a healthy mix. Grounding itself is what the authorized run measures (checkpoint-1
floor-probe, kill-#6) — readiness means the harness is launch-capable, which it now is.

---

**History (how precondition-1 got to green — the 6-catch chain):**

**ER-2c — N-basis (source-verified, #440/PR #440 = commit 4528066).**
`receipts/ember437-er2c-20260616T064826Z.json`: `tok_s_paced=18,122.9` / `tok_s_raw=22,260.8`
at **PACKED `tokens_per_step=4096`** (batch=4×seq=1024, asserted) on the **EmberTransformerLayer
368M** launch model (n_layers=20, hidden=1024, params=377,586,688 — the §IV build, not the
Llama proxy), 200/200 steps, `er2c_pass=true`, loss 10.56→2.0. This IS a valid N-basis.
**The attention-wall flag is CLEARED:** I warned that if packed EmberTransformerLayer
throughput came back far below #434's Llama synth (19,935.6) the eager-attention path would
be a wall to break (SDPA/flash). It came back at **22,260.8 raw > 19,935.6** — the hand-rolled
layer is *faster raw* than the Llama proxy on real data. No attention wall. Measure-first was
correct.

**BUT precondition-1 is NOT green — the loader that produced the valid N cannot teach
grounding (source-verified, `scripts/train_multimodal_v0.py` PackedCorpusLoader, lines
282–372).** PackedCorpusLoader loads ONE anchor image, **discards its own caption**, fills
each of the 4 batch rows with text drawn from **subsequent, unrelated pairs**, and
**replicates that one anchor image across all 4 rows** (`np.stack([patches_np]*batch_size)`).
The comment is explicit: *"each gets the same image but different text fill."* This is a
**throughput-only** loader — perfect for measuring tok/s (uniform shape, 4096 tok/step → N
valid), but **structurally incapable of teaching image grounding**: a model trained on
image-glued-to-unrelated-text has no signal to bind the modalities and cannot beat a
text-only control on the image-grounded verify-floor — it would fail kill-criterion #6 by
construction. The `--live` path's `CorpusLoader` (line 180) DOES preserve correspondence
(uses the pair's own `data["caption"]`) but is **unpacked** (118 tok/step — the original
problem). So **neither existing loader is launch-ready**: one has correct binding/wrong
throughput, the other correct throughput/broken binding.

The packed split (`patch_token_fraction=0.064` / text 0.936) is therefore a **throughput-loader
artifact** (one image replicated + bulk unrelated text), NOT the launch mix — the launch
patch/text floor must come from ER-2d's realized split, not this number.

**One item closes precondition-1 (ER-2d — the launch loader):** a loader that is BOTH packed
(≈4096 tok/step → N stays valid) AND correspondence-preserving (each image's patches matched
to ITS OWN caption within the sequence). The single-image shortcut was driven by the **Lock-4
multi-image RoPE** constraint; packing matched pairs to fill seq=1024 means multiple images
per sequence, so ER-2d must handle/fix that RoPE path (break-the-wall: make multi-image
supported, not accept the binding-broken loader). Re-measure tok/s on THAT loader = the
**final N** (model compute dominates ER-2c's 18,122.9, so the provisional N below is close);
re-measure patch:text = the launch floor.

**N (PROVISIONAL — ER-2c basis, model-compute-dominated so within a small margin of final):**
1 governed day affords `18,122.9 × 86,400 ≈ 1.566B tokens`. Chinchilla-optimal demand
20·P = `7.37B tokens` → `7.37B / 1.566B ≈ 4.7 governed days`. Default pilot = 1 governed day
(1.566B tok), verify-floor as the success bar, 7.37B as the ceiling (budget-decision §5/§7).
Disk at this scale (368M ckpt ~4.4GB incl. AdamW state, tiny corpus, keep-last-N) is well
under 100GB. Final N re-confirms on ER-2d's launch loader.

the lead does not ping the maintainer (#13) until **3/3 receipt-green** — which now requires **ER-2d**
(correspondence-preserving packed launch loader) done + final N/patch-floor measured on it.
N is computed from the **launch-loader real-data** tok/s, never the synthetic or the
throughput-shortcut number.

## Governor rails — mechanical, non-negotiable, identical to every prior brief

VRAM_FRACTION=0.80 · MARGIN_GIB=1.5 · decode pacer 0.05s. Margin violation
auto-kills; **fix-forward on a margin violation is BANNED** — killed and
relaunched governed (2026-06-10 PC-crash precedent). This is what makes a
multi-day unattended run safe.

## Kill criteria — frozen BEFORE launch (anti-goalpost), multimodal-specific

The run aborts (not babysat) on any of:
1. Governor margin violation → auto-kill (mechanical, wired).
2. Loss divergence / NaN → halt.
3. Sustained throughput below the committed measured tok/s → halt + re-measure
   (the run is measurement, not a checkpoint to nurse).
4. **Catastrophic forgetting of the text modality** (config-spec §VI: the
   Mono-InternVL failure mode) — the pilot watches text-eval drift explicitly; a
   forgetting collapse halts before GPU-days are spent.
5. **MTP fallback rule** (config-spec §II): MTP selftest fail → CE-only, RECEIPTED,
   re-enters at v0.1 — not a silent drop of the directed component.
6. Checkpoint-1 floor-probe FAILS the held-out floor → halt **before** continuing —
   do not spend remaining GPU-days on a run the floor-probe says won't transfer.

## Long-job rule — why this reaches the maintainer (not auto-launched)

A multi-day multimodal pretrain is >12 GPU-h, so by the long-job rule it needs a
**measured lever receipt + the maintainer authorization** — not a silent checkpoint start.
The lever receipt here = the B-MULTI-4 runner selftest tok/s on the realized
config (the multimodal analogue of C04's §3 bench; #414 re-measures Muon-vs-AdamW
on THIS config — the 0.37B-text fp-44 numbers do not transfer, config-spec §II).

## The ONE open decision (carried from config-spec §IV — default ships, no the maintainer-block)

- **DEFAULT (ships at readiness, no escalation):** v0 size class ~0.37–0.5B dense,
  both modalities. Satisfies both the maintainer gates — non-toy multimodal (06-14) AND
  smallest-core-pilot-first (06-10 residency).
- **REVISION TRIGGER (the only thing that escalates to the maintainer):** if the pilot's
  verify-floor receipt shows sub-1B multimodal cannot clear the E2B-surpass floor,
  the core-size/hardware bump (≥1.8B = more VRAM/disk/compute) is a
  hardware-envelope decision = **the maintainer's**, not a the lead call.

## The ask (readiness 3/3 GREEN — ready now, held for the maintainer's wake)

> Authorize the multimodal-unified v0 governed pretrain — locks 1-4 config,
> **0.368B** both-modalities (measured, matched image-text), rails + kill criteria
> above. **Your budget pick:** default **1 governed day ~ 745M tokens** (smallest
> non-toy pilot — clears the verify-floor or kills early at checkpoint-1), OR up to
> the **Chinchilla ceiling 7.37B tokens ~ 9.9 governed days**. Extension toward the
> ceiling is a new N = your call (never a silent grow).
> **Lever receipt (FINAL, on the real launch loader):** `tok_s_paced=8,627.0`
> (raw 9,661.3) on the §IV 368M/L20 config at PACKED 4096 tok/step, matched
> image-caption pairs, RTX 4090 bfloat16 grad-ckpt, governor rails (receipt
> `ember437-er2d-...072423Z`). 1 governed day ~ 745M tokens; N = frozen-budget / 745M.
> (The earlier 19,935.6 / 1.72B figure was the SYNTHETIC single-image throughput
> shortcut; the matched launch loader is ~2x slower — the FINAL number is 8,627.)
> **Network-bound contingency:** 8,627 is COMPUTE-bound (pre-encoded). The real run
> streams live CC3M URLs (network fetch), so realized tok/s could be lower —
> unmeasurable until acquisition; the run's first checkpoint confirms it. A reason
> the 1-day pilot is the right first step (cheap realized-throughput read).
> **Corpus:** on-the-fly CC3M streaming (pre-encode is rail-blocked at TB-scale;
> ~1GB metadata + live image streaming). **This needs your authorization to acquire
> CC3M** (external dataset). Reliability: ~20% dead URLs + network dependency +
> run-to-run non-determinism, handled by retry->skip->cycle + a fixed-seed manifest.
> **Optimizer:** **AdamW** (fp44 default; measured viable; avoids the torch>=2.7 env
> risk). Muon = revision-trigger only (needs torch>=2.7 + its own multimodal
> measurement) if AdamW's loss-quality proves insufficient.
> **Run-spec additions (capture at launch-config time):**
> (i) merge PR #443 first (ER-4 floor-probe harness onto master — non-blocking,
> ~5min, mechanically-forced doc-drop) so the checkpoint-1 kill-#6 probe is present;
> (ii) checkpoint the #33 resolver core (query-projection + attention) SEPARABLY
> from the image-patch K,V projections, and log attention-entropy per checkpoint —
> so the #33 cross-world transfer test (`wmc-cross-world-transfer-prereg.md`) is
> runnable later; without it that test is permanently unrunnable on v0.

## Status — ready for the maintainer's wake

**Readiness 3/3 GREEN (2026-06-16, source-verified at merged/PR refs).**
Precondition-1 (multimodal-target trained on real matched data) GREEN — ER-2d, PR
#441 source-verified, FINAL N=745M/gov-day. Precondition-2 (DT-6 signal-economics,
#430/PR #432) GREEN. Precondition-3 (crash-survival) GREEN. The #13 ping is ARMED,
held for the maintainer's wake (no ping while asleep). **Two staleness flags for the maintainer to
reconcile (the maintainer-owned, not seat-rewritten):** (1) `founder-state.md` (06-10) reads
the engineer=ASLEEP / an agent+an agent=DORMANT, contradicted by the 06-15 President restructure +
live watchers (all active this session); (2) `ember-floor-contract.md` row 47 still
frames encoder-free multimodal training as RE-STAGED/post-v0, contradicted by the
06-14 reactivation that made it the v0 launch target.
