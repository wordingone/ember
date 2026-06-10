# NC2 Recipe-Stack — PINNED (#28)

**Status:** PINNED (supersedes the 2026-06-10 draft in the lead's state dir)
**Scope:** Component pinning for the NC2-own pretrain loop at ~0.5–1B params /
~20B tokens, RTX 4090 single-GPU.
**AC discharge:** per-component URL + commit pin + license + 4090-feasibility
note + smoke-scale validation plan. "Proven recipe" = local receipt at the
claimed scale, never a README claim — smoke plans below name the receipt each
pilot must produce.
**Verification provenance:** every pin in §Pins was re-verified 2026-06-10:
commit SHAs + SPDX via GitHub API; licenses with NOASSERTION resolved by
reading the LICENSE file; web claims (4 items) verified by parallel
fact-check agents with adversarial recheck; two items verified by direct
execution on this machine (receipts named inline).

---

## Recipe shape (unchanged from draft / technique contract §9)

- Core: dense ~0.5B, ~20B tokens, from-scratch, BF16.
- Optimizer: Muon on hidden layers; AdamW on embedding + head.
- Quantization: int4-QAT tail; ternary (BitNet) pilot decides the low-bit lead.
- MTP: post-hoc speculative-decode drafter only (pretraining MTP re-staged).
- Attention: GQA + FlashAttention + QK-norm from step 0; Gemma-4-style
  unified-multimodal locks reserved in vocab/attention (v0 text-only).
- Build-only (no ecosystem dependency exists): replay/sleep-consolidation,
  verifier-gated experience ledger, LoRA expert promotion harness.

---

## Pins (verified 2026-06-10)

| # | Component | Pin @ commit | License | Verified how |
|---|-----------|--------------|---------|--------------|
| 1 | QAT framework | github.com/pytorch/ao @ `abea9e0c4199` | **BSD-3-Clause** | LICENSE file read (GitHub SPDX says NOASSERTION; file is Meta BSD-style). Draft said Apache-2.0 — **corrected**. |
| 2 | Export/KV pipeline | avir-cli `turboquant` (local, deferred intake) | user-owned | local; unchanged from draft |
| 3 | Ternary substrate | github.com/microsoft/BitNet @ `01eb415772c3` | **MIT** | GitHub API. Draft said Apache-2.0 — **corrected**. bitnet.cpp is NOT a separate repo (`microsoft/bitnet.cpp` 404s); it ships INSIDE this repo (src/, include/, gpu/, run_inference.py) — **corrected**. |
| 4 | Optimizer | github.com/KellerJordan/Muon @ `f98f1cacc026` | MIT | GitHub API ✓ |
| 4b | Optimizer (fused kernel) | github.com/nil0x9/flash-muon | MIT | GitHub API ✓ |
| 4c | Optimizer (native) | `torch.optim.Muon` | BSD (PyTorch) | **executed locally**: present in torch 2.10.0+cu126 on this machine (same env as the native-smoke receipt). |
| 5 | MTP drafter reference | google/gemma-4-12B-it (HF) | Gemma terms | see component 10 — draft's gemma-2-9b-it URL was the wrong generation — **corrected**. |
| 6a | Data curation | github.com/allenai/dolma @ `669f534823b0` | Apache-2.0 | GitHub API ✓ |
| 6b | Pretrain configs + eval | github.com/mlfoundations/dclm @ `361714bdd60b` | **MIT** | GitHub API. Draft said Apache-2.0 — **corrected**. |
| 6c | Curriculum specs | github.com/allenai/OLMo-core @ `8d22ca94fdc7` | Apache-2.0 | GitHub API ✓ |
| 6d | Single-GPU framework (A/B) | github.com/NousResearch/Automodel @ `d719b85ea8c6` | Apache-2.0 | GitHub API ✓ |
| 6e | Post-train templates | github.com/allenai/open-instruct @ `26de99604002` | Apache-2.0 | GitHub API ✓ |
| 6f | RL environments | github.com/NousResearch/atropos @ `c20c85256e5a` | MIT | GitHub API ✓ |
| 7 | SDEK kernel | local: `kai-index/sdek-research-handoff.md` (avir repo) | internal | local handoff doc; the draft's `github.com/anthropic-ai/ai-research-kai` URL is not a real pin — **removed**. |
| 9 | FlashAttention | github.com/Dao-AILab/flash-attention @ `fc8cbad6b6b9` | BSD-3-Clause | GitHub API ✓ |
| 10 | Unified-multimodal reference | huggingface.co/google/gemma-4-12B-it (released 2026-06-03) | Gemma terms | WebFetch model card + adversarial recheck; gemma-4 E2B/E4B artifacts also present in this machine's HF cache. |
| 11 | Replay/consolidation | CUSTOM (no public release) | — | unchanged; substrate ref arXiv 2605.26099 |
| 12 | Verifier-gated ledger | CUSTOM — this repo's t1–t4 harness | — | NC0 receipts are the existing instance |

GRPO dtype escape hatches (kept from synthesis, now verified real):
unsloth#5183 (closed; TRL-first import order) and unsloth#4891 (open;
Half/BF16 matmul_lora mismatch under 4-bit GRPO) — both title-checked via
GitHub API. llama.cpp#21447 (closed; llama-quantize generalization
workaround for custom archs) and llama.cpp#5761 (closed, never merged;
BitNet b1.58 — the fork path for ternary GGUF stays named) — both confirmed.

---

## Resolved questions (were UNVERIFIED in the draft)

1. **torchao QAT in a TRAINING loop — RESOLVED, exists.** The draft claimed
   QAT was "documented only for inference." Wrong: torchao documents a full
   training-time QAT flow — `torchao.quantization.QATConfig` +
   `quantize_()`, prepare (Linear→FakeQuantizedLinear) → train → convert,
   with Int4WeightOnly / Int8DynActInt4Weight configs.
   Primary: https://docs.pytorch.org/ao/main/workflows/qat.html
   (adversarially rechecked; TorchTune/Unsloth integrations exist with
   measured accuracy recovery). Smoke plan §1 of the draft stands, with the
   documented API as the wiring — no manual fake-quant ops needed.
2. **Muon primary citation — RESOLVED.** arXiv 2502.16982, "Muon is Scalable
   for LLM Training" (Moonshot): "achieves comparable performance to AdamW
   trained counterparts while requiring only approximately 52% of the
   training FLOPs." Caveat the draft missed: Moonlight is a 2.24B-activated /
   15.29B-total MoE on 5.7T tokens — that receipt is SCALE-UP evidence; the
   same-scale (~124M) validation rests on the modded-nanogpt speedrun
   lineage, which is a leaderboard receipt, not a paper.
3. **torch-native Muon — RESOLVED, present.** `torch.optim.Muon` exists in
   torch 2.10.0+cu126 (executed locally). Bug fix to the draft's launch
   check: `torch.__version__ >= "2.9"` is a STRING compare and is FALSE for
   "2.10.x" — use `packaging.version.parse`.
4. **"Gemma-4" reference — RESOLVED.** Gemma 4 12B is real (released
   2026-06-03): unified, encoder-free multimodal — raw image patches and
   audio waveforms projected into the embedding space via lightweight linear
   layers; 48 layers; 256K context. The draft's URL
   (google/gemma-2-9b-it — Gemma TWO, text-only, 2024) is replaced
   everywhere by google/gemma-4-12B-it.
5. **Native-Windows escape hatch for the training harness — RECEIPTED.**
   Probe-b (#27, `receipts/native-smoke-20260610T230236Z.json` +
   `...230645Z.json`): torch 2.10.0+cu126 + triton-windows 3.5.0 +
   bitsandbytes 0.49.1 execute a governed LoRA SFT step on the 4090
   natively (loss 1.212, warm load 5.1s). Combined with probe-a
   (`receipts/wsl9p-probe-2026-06-10T225917Z.json`: 9P penalty 903–10,612%
   on 6/6 I/O ops), the recipe's 4090-feasibility column no longer assumes
   WSL residency; harness placement is an open lead decision with receipts
   on both sides.

## Corrected claims (kept conclusions, fixed citations)

- **MTP ≤1B evidence (component 5):** arXiv 2404.19737's abstract supports
  "benefits especially pronounced on LARGER models" (13B coding gains); the
  draft's "worse on smaller models" phrasing is not abstract-derivable.
  RE-STAGED disposition unchanged — the supporting wording is now "no
  published ≤1B gains; benefit concentrates with scale," plus TOP 340M/1.8B
  inconsistency as before.
- **Sleep-consolidation numbers (component 11):** the Ouro-1.4B
  41.9→61.5% GSM-Infinite figures are NOT in the public arXiv 2605.26099
  abstract — treat as contract-internal reading of the paper body,
  UNVERIFIED against public sources. Mechanism pin (GDN/Jet delta-rule fast
  weights) unchanged.
- **Mono-InternVL floor (component 10):** it is 1.8B LLM + 1.2B visual
  experts ≈ 3B TOTAL (1.8B activated), not "a 1.8B model." The "sub-1B
  encoder-free is unexplored territory" admission gets STRONGER, not weaker.

---

## Smoke-scale validation plans (AC item 4 — receipt each pilot must produce)

Unchanged in substance from the draft §Pass/Fail summary; restated here as
the binding table. Every pilot writes a JSONL/JSON receipt with a governor
block (fraction, free_gb, margin_gb) per repo convention; runtime estimates
respect interruptible-window residency.

| Component | Smoke config | Pass metric | Fail → action |
|-----------|-------------|-------------|---------------|
| QAT int4 (torchao QATConfig) | 100M model × 100M tok, AdamW embed/head | ppl gap ≤0.5 vs BF16 baseline | LR/Muon-interaction tuning; then INT8 fallback test |
| turboquant export | 100M trained model → GGUF | export <30s; CPU inference ≥10 tok/s | escalate (no named fallback — flagged UNVERIFIED) |
| BitNet ternary | 100–300M, 5B tok, AdamW (Muon×STE untested) | ppl gap ≤0.3 vs BF16 twin | ternary deferred to ≥3B rung; int4-QAT is final |
| Muon split | 100M × 100M tok, Muon(hidden)+AdamW(embed/head) vs all-AdamW | ≥1.5× convergence speed OR ≥2× final-loss gain | all-AdamW fallback; investigate Muon×QAT |
| SDEK harness | 100M base + 10 MBPP episodes (k=4) | ≥1/3 episodes shows ≥40% deletion delta | harness scope re-frame; escalate |
| Consolidation/Jet | 100M + 10 episodes, 500 sleep steps | Jet-adapter within 5% solve rate of LoRA | defer sleep-consolidation to ≥1B rung |
| Verifier ledger | 100M base, 20 episodes | ≥1 episode passes three-test gate | gating harness malfunction — fix before anything else |
| GQA+FA+QK-norm | 100M, seq 2048, batch 16 | ≤20% VRAM over dense; ≥95% throughput | revert to dense attention |
| Gemma-4 locks (text-only) | 100M pretrain, locks compiled-in unused | ≤0.05 ppl overhead vs no-locks twin | drop lowest-leverage locks |
| Data pipeline | 100M-tok subset: dolma tokshuf dedup + DCLM filter, 2 epochs | within 0.2 ppl of full-dedup; dedup ratio 1.3–1.5× | escalate to LR tuning (not a data fault) |

Integration sequencing, ADR table, and residency budget gate: unchanged from
the draft (week-1 pilots → week-2/3 pretrain → week-4 SDEK/adaptation rung;
dense-not-MoE, BF16-not-FP8, drafter-only MTP; ternary/int4 CPU-residency
targets). FP8 stays SKIP (sm89, zero consumer pretrain receipts).

---

## Remaining open questions (carried, now 6 not 10)

1. Muon × BitNet STE interaction (test during ternary pilot).
2. Muon × QAT two-optimizer-branch scheduling (test during QAT smoke).
3. BitNet × MTP output-head conflict (deferred post-pilot, by design).
4. Jet/GDN consolidation reproducibility at ≤100M (pilot measures).
5. GRPO floor ~1.5B vs 0.5B core (pilot with zero-pass kill; user call).
6. turboquant intake timing (avir-cli deferred; escalate if critical path).

Discharged vs the draft's 10: torchao QAT API (resolved §above), Muon
citation (resolved), Dolma/DCLM downscale (the smoke table IS the test — a
plan, not a question), MLA (WATCHING disposition is a decision, not a
question).
