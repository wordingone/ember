# Ember Floor Contract — launch-vehicle deferral ledger

Created 2026-06-11 (user directive relayed via audit mail 14663 + intent-gap note
`B:/M/avir/kai/state/ember-intent-gap-note-2026-06-11.md`). Single source of truth
for every floor component the v0 launch vehicle ships WITHOUT. Dispositions and
survey evidence live in `nc2-own-technique-contract.md` (the NC2 contract — its
component list is binding; silent pivots are gate violations); this ledger adds
the operational tracking Kai's note requires: no silent floor→ceiling downgrade.

## Goal-shift record (audit item A)

What changed 2026-06-11, and where it is recorded:

1. **Launch urgency (user, direct + relayed 14663):** credits/usage ending soon →
   dispatch v0 TODAY once the launch gate is clean. This is an URGENCY change,
   not a scope change: the receipt gate stays intact (14663 item E), the
   autonomy clause (mail 14665, recorded in STATE) makes dispatch robust to
   Leo-unreachability. Recorded: STATE.md transition log + mail 14665 + here.
2. **Operational reading sharpened (intent-gap note):** v0 — text-only,
   near-vanilla dense decoder — is an executable LAUNCH VEHICLE, not a
   redefinition of Ember's floor. Every deferral below stays a floor-contract
   row with a receipt-producing pilot, a revision trigger, a named owner, and a
   kill/promote condition. Recorded: this file (the named floor-contract ledger
   14663 item B asks for) + GOAL.md (unchanged — already states the owned core
   is eventually pretrained from scratch locally, quantization-native,
   efficient, multimodal-unified, SDEK-operated).

GOAL.md text itself is UNCHANGED — only the user edits the goal.

## What v0 already carries (floor components IN the launch vehicle)

| Component | v0 surface | Evidence |
|---|---|---|
| Reserved multimodal vocab band | 8 reserved IDs in the frozen tokenizer | G-tokenizer GREEN (launch gate) vs `tokenizer-freeze-20260611T154111Z.json` |
| QAT (quantization-native pretrain) | int8-grid fake-quant STE on linear weights, enabled in config | `precision.qat` component contract #1; receipted tax 0.928× paced (fp19-bench c03) |
| Muon optimizer (CN-stack ADOPT) | hidden 2D params Muon, embed/norms/head AdamW | `optimizer` block; v2 table 1.35× data-efficiency survivor; AdamW-everything fallback = receipted deviation |
| QK-norm | step-0 lock from the Gemma-4 deep-dive | nc2 contract row 8 (four v0 locks) |
| Governor (residency budget) | 0.80 VRAM fraction / 1.5 GiB margin / 0.05 s pace, tighten-only | G-governor GREEN; user binding design gate 2026-06-10 |

## Deferral rows (audit item B format)

Statuses: WATCHING / ADOPT / RE-STAGED / SKIP-with-receipt — same vocabulary as
the nc2 dispositions table. Owner = who fires the pilot when the trigger lands.

| Component | Why deferred from v0 | Receipt-producing pilot | Revision trigger | Owner | Status | Kill / promote condition |
|---|---|---|---|---|---|---|
| Encoder-free multimodal TRAINING (soft-token embedder, `inputs_embeds` splice, span-bidirectional attn, 2D RoPE) | v0 corpus is text; the four ARCHITECTURE locks are in (band reserved, retrofit-proven per Gemma-4 deep-dive); sub-1B encoder-free has zero published prior art | post-v0 retrofit pilot: ~35M-param patch embedder on the v0 checkpoint, image-text floor task, governed | first v0 checkpoint evals land (#208) AND a vision-text floor world is specced | leo (spec) / eli (run) | RE-STAGED (architecture contracts IN v0) | promote on measurable image-grounded verify-rate > text-only control; kill the retrofit (not the component) on null at matched budget — successor = dedicated multimodal rung |
| BitNet / 1.58-bit ternary | quality crossover ~3B; training on 4090 saves nothing (inference-only payoff); int4/int8-QAT carries low-bit at ≤1B | onebitllms ternary pilot iff CPU-deploy becomes a requirement | hardware escalation to a ≥3B rung (user's call) OR a CPU-residency requirement | leo | RE-STAGED (nc2 row 3) | promote on ≥3B rung entry; SKIP-with-receipt if int4 QAT export meets every deploy target first |
| turboquant export + KV compression | export/serving surface, not a pretrain lever; nothing to export until checkpoint-1 | quantize the first WSD checkpoint; perplexity-delta + footprint receipt | first v0 checkpoint on disk | eli | ADOPT (nc2 row 2 — duty unchanged, sequenced post-ckpt-1) | promote on receipted export ≤ target footprint at bounded ppl tax; failure = named successor (torchao PTQ baseline) |
| SubQ / sparse / linear-hybrid attention | NSA attended-token floor ≈ full attention at v0's 1024–4k ctx; explicitly excluded in config (`throughput.excluded.sparse_attention`) per fp19 bench | GDN-hybrid 340M pilot (also carries sleep-consolidation substrate) | long-context world admission (NC1c) OR GDN pilot receipt | leo (prereg) / eli (run) | RE-STAGED (nc2 row 4) | promote on tokens/s × quality parity at ≥4× ctx; kill hybrid on quality cliff with receipt — successor = MLA/KV-compression-only route |
| MLA / KV-cache compression | inference-memory lever; v0 is pretrain-bound, KV pressure starts at sampling rounds | MLA retrofit probe on v0 core at first sampling round | first owned-core sampling round (post round-1 verdicts #205) | eli | WATCHING (CN-stack intake, nc2 row 7) | promote on measured F (verified-episodes/GPU-h) gain; SKIP-with-receipt if whole-batch sampler (#230 projection ≥2×) already saturates the GPU |
| SDEK / GDN-Jet fast-weight sleep consolidation | middle-timescale substrate named (gated delta-rule SSM); not a v0 pretrain component | 340M GDN-hybrid pilot per nc2 row 6 | wait-window GPU idle post-launch (run rides beside v0 only if governor headroom proves it; else post-v0) | leo (spec) / eli (run) | ADOPT-pilot (nc2 row 6) | promote on GSM-Infinite-class delta reproduced locally at pilot scale; kill on null — successor = LoRA-sleep baseline (kernel v1 freeze spec) |
| MTP / TOP auxiliary prediction | published NEGATIVE quality evidence ≤1B (Meta 2404.19737; TOP 340M/1.8B inconsistent) | speculative-decode DRAFTER on v0 core (Gemma-4-style post-hoc), throughput receipt | v0 sampling rounds begin AND decode is measured sampling bottleneck | eli | RE-STAGED to drafter (nc2 row 5) | promote on ≥1.5× decode throughput at unchanged verify rate; SKIP-with-receipt if sampler economics already meet F target |
| GRPO / RL-on-verifier-reward | floor ~1.5B (TinyZero 0.5B fails); v0 core is 0.37B — below the published floor; competence floor must exist first | non-zero-pass-rate GRPO pilot on the post-round-1 core | round-1 verdicts (#205) show nonzero verify floor | leo (prereg) / eli (run) | PILOT post-train (nc2 row 7) | kill on zero-pass-rate (pre-registered); promote on paired Δ over SFT-only arm; conflict "0.37B vs 1.5B floor" decided by the pilot receipt, not prose |
| FP8 training | zero published 4090 FP8 pretrains; TE silent-BF16-fallback; torchao tensorwise-only on sm89 | none until hardware/library evidence changes | a published consumer-4090 FP8 pretrain OR torchao sm89 rowwise support | leo (release-scan row) | SKIP-with-receipt (nc2 row 7) | re-enter via release-scan (#18 standing) on new external evidence |
| MoE | trades VRAM (scarce) for FLOPs (abundant) at ≤1B on one 4090 | none at this scale | local-scale evidence (multi-GPU or ≥3B rung) | leo (release-scan row) | SKIP-with-receipt (nc2 row 7) | re-enter on hardware escalation |
| DiffusionGemma sampler / dLLM | output quality below autoregressive per Google's own framing; bet is throughput-per-verified-episode, unproven locally | w1-style MBPP floor probe, DiffusionGemma vs Qwen-3B, same k/tasks/governor, decided on measured F | idle GPU window AND W-code admitted (STATE pending layer 19) | eli | WATCHING (nc2 row 9) | promote iff verify-rate floor stays nonzero AND F gain ≥ measured; kill on zero-verify floor |
| External research intake (standing) | n/a — pipeline, not a component | bounded release-scan sweep → typed WATCHING rows | every idle tick advancing the wait-window queue (STATE pending layer 18) | leo | standing | "no candidates" is a recorded outcome; ADOPT only via local residency-scale receipts |

## Invariants

- **No silent floor→ceiling downgrade:** removing or weakening any row above
  requires the user by name (never-reduce-scope; nc2 contract gate language).
- **Failed techniques get receipts and named successors** — a kill closes the
  pilot, never the component, unless the user closes it.
- **New research enters as WATCHING** and promotes only on local
  residency-scale receipts (nc2 "Research-intake posture").
- **This ledger is launch-vehicle bookkeeping** — the binding component
  contract remains `nc2-own-technique-contract.md`; on conflict, the nc2
  contract wins and this file gets repaired.
