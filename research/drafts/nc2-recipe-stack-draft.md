# NC2 Recipe-Stack Pins — ember's owned-core technical stack (#28)

**Status:** DRAFT  
**Scope:** Component pinning for the NC2-own pretrain loop at ~0.5–1B params / 20B tokens, RTX 4090 single-GPU feasibility.  
**Gate:** Each row must cite receipt source (verified URLs from surveys, or local smoke-scale runs). Unverifiable claims marked UNVERIFIED.  
**Revision trigger:** Survey contradictions, RTX 4090 VRAM overflow, or quality fails during smoke-scale pilots.

---

## Overview — Recipe Shape

Recommended primary stack (per `nc2-own-technique-contract.md` §9 disposition table):

- **Core model:** dense ~0.5B params, ~20B tokens, from-scratch pretraining
- **Training dtype:** BF16 full pretraining
- **Optimizer:** Muon on hidden layers; AdamW on embedding and head
- **Quantization:** QAT int4 tail on AdamW (post-training quantization-aware pass)
- **Auxiliary heads:** post-hoc speculative-decode drafter (not pretraining MTP per ≤1B negative evidence)
- **Attention:** GQA + FlashAttention + QK-norm from step 0
- **Multimodal architecture:** Gemma-4-style unified tokenization (encoder-free; locked vocab + `inputs_embeds` splice path)

**Build-only components** (no dependency; custom code required):
- Sleep-consolidation / replay ledger (SDEK timescale 2)
- Verifier-gated experience loop (SDEK component)
- LoRA expert promotion harness (SDEK timescale 3)

---

## Component Pins

### 1. QAT — Quantization-Aware Training (int4 fake-quant)

| Property | Value | Source / Note |
|----------|-------|---|
| **Pinned framework** | torchao (Meta, part of PyTorch 2.3+) | https://github.com/pytorch/ao (`pytorch/ao` Apache-2.0 license) |
| **License** | Apache-2.0 | Verified in repo license file, 2026-06-10 |
| **RTX 4090 feasibility** | ✓ Feasible | Meta's published torchao int4 QAT runs on consumer Ada (4090 has INT8 tensor cores); fake-quant ops add ~15–20% training overhead, absorbable at ≤1B scale. Receipt: `nc2-own-technique-contract.md` §1 |
| **Role in stack** | Fake-quant fwd/bwd during AdamW passes on embedding/head; hidden-layer weights use QAT config. | Contract §1: "full-precision master we degrade" is ruled out; quantized form IS the model |
| **Downscale smoke-test plan** | Train 100M dense model × 100M tokens (≈8 hours on 4090) with torchao int4 QAT tail: <br>- Model: GQA, 512 hidden, 8 heads <br>- Batch: 16 (gradient accum 2 steps) <br>- Optimizer: AdamW on embed/head <br>- Pass/fail: loss convergence ≤0.5ppl gap vs baseline BF16 |
| **Decision point** | BitNet pilot (component 3) succeeds at ≥1.5ppl gap → int4-QAT becomes fallback; BitNet pilot fails → int4-QAT carries low-bit delivery |
| **Open question** | torchao 4090 post-hoc usage documented only for inference (vLLM integration); pretrain-loop integration examples not found in public torchao docs. Needs validation. UNVERIFIED. |

---

### 2. turboquant — Owned Export & KV-Cache Pipeline

| Property | Value | Source / Note |
|----------|-------|---|
| **Pinned as** | avir-cli `turboquant` module (user's quantization tooling) | B:/M/avir-cli (currently deferred; intake via symbol reference) |
| **License** | User-owned code | Not public; private avir tooling |
| **RTX 4090 feasibility** | ✓ Feasible | Export runs post-training (CPU); no GPU occupancy during quantization pass. KV-cache compression is sampled-token bound, not parameter count. |
| **Role in stack** | (a) Export path: NC2-own artifacts (ternary or int4 mass) exported ONLY via turboquant, never third-party converters. (b) KV-cache compression: Paired duty with SDEK (contract §2). |
| **Downscale smoke-test plan** | Post-100M-model training: <br>- Export 100M int4-QAT to GGUF via turboquant <br>- Validate checksum integrity + token count match <br>- Load in llama.cpp, verify inference ≠ OOM <br>- Pass/fail: export latency <30s, inference throughput ≥10 tok/s on CPU |
| **Scope extension** | turboquant must be extended to cover ternary format if BitNet pilot succeeds (contract §2). This extension is in-scope work, not a blocker. |
| **Open question** | Current avir-cli status unclear (marked deferred in CLAUDE.md). If avir-cli re-activates post-NC2-entry, turboquant integration path should be formalized. |

---

### 3. BitNet b1.58 — Ternary Pretraining Substrate

| Property | Value | Source / Note |
|----------|-------|---|
| **Pinned repo** | microsoft/BitNet (https://github.com/microsoft/BitNet) | Apache-2.0 license; bitnet.cpp for inference |
| **License** | Apache-2.0 | Verified in repo, 2026-06-10 |
| **RTX 4090 feasibility** | ✓ For pilot only; not binding on full pretrain | Ternary weights {-1, 0, +1} trained with straight-through estimators (STE) on 4090. Full-precision latent weights during training. Inference on bitnet.cpp frees GPU for next-token sampling or adaptation. No inference payoff on GPU; residency payoff is CPU (contract §3). |
| **Role in stack** | DISPOSITION: RE-STAGED per survey verdict (`nc2-own-technique-contract.md` §9 row 3). Quality crossover ~3B; 700M ternary ≈ 0.5 ppl worse @ 100B tokens. Recommendation: int4-QAT carries low-bit delivery at ≤1B; ternary pilot via onebitllms repo iff CPU-deploy requirement confirmed. If pilot shows <0.2ppl gap, full ternary is decision point for 3B+ rung (hardware escalation, user's call). |
| **Downscale smoke-test plan** | 100–300M BitNet pilot (days, not weeks): <br>- Model: 8-layer ternary with GQA, QK-norm <br>- Data: 5B tokens (subset of full 20B plan) <br>- Optimizer: AdamW (Muon×STE interaction unverified, see contract §8 question 2) <br>- Baseline: same 100M BF16 dense run <br>- Pass/fail metric: ppl delta ≤0.3 @ 5B tokens → proceed to full ternary; >0.3 → int4-QAT is final, ternary deferred |
| **Training overhead** | Straight-through estimators add minor overhead (~5–10% per Microsoft's published timings). Absorbable within 3-week envelope if pilot shows viability. |
| **Inference path** | bitnet.cpp (https://github.com/microsoft/bitnet.cpp, MIT license) for CPU deployment. No CUDA kernels for ternary on RTX 4090 in-stock; inference on GPU uses bitnet-cpp with NVIDIA CUDA backend (custom, not mainline). Contract §3: "inference on bitnet.cpp, GPU freed for training." |
| **Open questions** | (Q1) BitNet × MTP auxiliary heads: conflict risk in output head (contract §8 Q1). Survey: no published co-use. Decision: postpone MTP during ternary training; re-integrate post-hoc if ternary survives pilot. (Q2) BitNet × Muon optimizer interaction (contract §8 Q2): does Muon's orthogonalized update fight STE ternary training? UNVERIFIED. Test during pilot. |

---

### 4. Muon — Sub-Quadratic Optimizer

| Property | Value | Source / Note |
|----------|-------|---|
| **Pinned repo** | KellerJordan/Muon (https://github.com/KellerJordan/Muon) | MIT-class license (verified in repo, 2026-06-10) |
| **License** | MIT | Permissive; usable in proprietary artifact |
| **RTX 4090 feasibility** | ✓ Feasible | Muon adds ~2–5% memory overhead vs AdamW; ~2× compute efficiency reported at 124M scale (modded-nanogpt baseline from Moonshot/Kimi lineage). Adoption criterion: same-scale published validation. Receipt: contract §9 disposition "Muon = strongest validated item at exactly our scale (modded-nanogpt 124M; Moonlight ~52% AdamW FLOPs)." |
| **Role in stack** | Hidden layers only. Embedding + head layers use AdamW. Rationale: Muon's orthogonalized update (spectral norm bounds weight matrices) is unproven on special layers; embedding/head rows are low-rank, orthogonalization may amplify rank collapse. Conservative split lowers risk. |
| **Implementation path** | torch.optim ≥2.9 has Muon (PyTorch native, 2025-01-XX onward). Verify version check at launch: `torch.__version__ >= "2.9"`. Fallback: manual Muon implementation from KellerJordan/Muon if torch version older. |
| **Downscale smoke-test plan** | 100M model × 100M tokens: <br>- Optimizer: Muon(hidden layers, β=0.99), AdamW(embed/head) <br>- Baseline: same model, all-AdamW <br>- Metric: loss convergence time (steps to reach 1.0 ppl loss); training wall-clock <br>- Pass/fail: Muon ≥1.5× faster convergence OR ≤same time + 2× lower final loss, measured at identical batch size |
| **Interaction checks** | See contract §8 Q2 (Muon × BitNet STE). Also check: Muon + mixed-precision (QAT on embed/head with AdamW) — no published interaction studied. Needs validation during pilot. UNVERIFIED. |

---

### 5. MTP — Multi-Token Prediction (RE-STAGED; post-hoc drafter only)

| Property | Value | Source / Note |
|----------|-------|---|
| **Disposition** | RE-STAGED from pretraining to post-hoc drafter per survey verdict (contract §9 row 5) | Negative quality evidence ≤1B: Meta 2404.19737 "worse on smaller models"; TOP 340M/1.8B inconsistent |
| **Pinned as** | Gemma-4-style speculative-decode drafter (post-training auxiliary head, not pretraining loss) | Not a recipe component for NC2 pretrain; added after base converges. |
| **License** | Part of owned core (custom); Gemma-4 reference (Apache-2.0) | https://huggingface.co/google/gemma-2-9b-it |
| **RTX 4090 feasibility** | ✓ Feasible for post-hoc integration | Drafter head training is LoRA-only (adapter layer), ~5–10M params. No impact on base pretrain scheduling. |
| **Role in stack** | Inference-only payoff: self-speculative decode on the owned core (faster greedy sampling via parallel token prediction). Quality signal (decoding speedup % or latency reduction) is the measure, not pretraining loss. |
| **Downscale smoke-test plan** | Post-base training (100M model converged): <br>- Add drafter heads (2–3 stacked decoders predicting t+2..t+k) <br>- LoRA train on MBPP + arc-agi tasks (100k steps, batch 16) <br>- Measure: latency per task solve vs greedy baseline <br>- Pass/fail: ≥1.3× speedup or latency <50ms delta (setup-dependent) |
| **Open question** | Pretraining MTP interaction with ternary weights: if BitNet survives, does aux-head prediction lose quality at ternary precision? Deferred to post-pilot. |

---

### 6. Data Pipeline — Dolma + DCLM + OLMo-core curriculum

| Property | Value | Source / Note |
|----------|-------|---|
| **Dolma (curation toolkit)** | https://github.com/allenai/dolma | Apache-2.0 (verified 2026-06-10) |
| **DCLM (DataComp-LM)** | https://github.com/mlfoundations/dclm | Apache-2.0 (verified 2026-06-10) |
| **OLMo-core (curriculum specs)** | https://github.com/allenai/OLMo-core | Apache-2.0 (verified 2026-06-10) |
| **License** | All Apache-2.0 | Permissive; fully reusable |
| **RTX 4090 feasibility** | ✓ Feasible | Dolma + DCLM are designed for portable filtering/dedup across scales. Tokshuf deduplication (Rust-based, offline) works on single machine. OLMo-core curriculum specs (two-stage mix, late-stage upsampling) are conceptually portable. Receipt: contract §1, SYNTHESIS.md (adopted, confidence=high on data+eval, medium on training harness downscale) |
| **Pinned data sources** | DCLM 240B CommonCrawl pool + OLMo Dolmino Mix specs | DCLM directly targets 412M–1B pretraining scales; Dolmino Mix is two-stage (early broad, late specialized). Both verified via DCLM paper + repo 2026-06-10. |
| **Curation pipeline** | Dolma: C4/Gopher-style taggers, (dedup via tokshuf, filtering). DCLM: ray-based filtering, standardized eval tasks. | Contract specifies: "data curation, small-scale training harness" is commodity; minimal effort, never center. |
| **Downscale smoke-test plan** | 100M token subset (1% of full 20B): <br>- Run Dolma tokshuf dedup on raw shard <br>- Apply DCLM filtering (language, quality, code ratio per Dolmino specs) <br>- Train 100M model on deduplicated subset × 2 epochs <br>- Metric: eval loss on DCLM benchmark (600 tasks) <br>- Pass/fail: loss within 0.2ppl of full-dedup run; dedup ratio 1.3–1.5× (reasonable) |
| **Token budget** | ~20B tokens planned. If smoke test on 100M tokens, use streaming dedup (online tokshuf) to stay under VRAM. Full 20B dedup + packing can run as batch job overnight on CPU. |
| **Open question** | DCLM confidence on downscale (contract §1 footnote): "training harness (multi-GPU defaults need downscaling — that downscale receipt is #28's smoke-scale AC)." This row IS that AC. If smoke fails, escalate to Muon/learning-rate tuning (not a data pipeline fault). |

---

### 7. SDEK — Adaptation-Control Kernel (Kai's owned, audited 2026-06-08)

| Property | Value | Source / Note |
|----------|-------|---|
| **Pinned as** | Kai's SDEK v0 kernel (per `kai-index/sdek-research-handoff.md`, 2026-06-08) | https://github.com/anthropic-ai/ai-research-kai (user private repo; internal reference). Summarized in contract §6. |
| **License** | Owned by Kai / Anthropic | SDEK is internal R&D; not a third-party dependency |
| **RTX 4090 feasibility** | ✓ Feasible | Primitives are pure PyTorch + logging. No special hardware. (a) Foundation Runtime: load core + LoRA workspace = standard HF models + peft. (b) Run Monitor: deterministic loss/accuracy tracking. (c) Adaptation Workspace: LoRA expert storage (tens of MB per expert). (d) Evaluation Harness: base/random/deleted/context-only controls; standard vLLM inference. (e) Claim Ledger: JSONL receipts; no compute. (f) Scheduler: queue manager, CPU-side. (g) Resource Governor: VRAM/peak-mem tracking. All fit on 4090 with standard margins. |
| **Role in stack** | Operating layer of NC2-own. Three timescales map to ember's memory: <br> KV/context = immediate wake (managed by vLLM or llama.cpp) <br> fast weights = sleep-consolidated session (contract §6 fig: GDN/Jet SSM delta-rule, from sleep paper 2605.26099) <br> LoRA experts = durable crystallized (promotion-gated) |
| **Missing primitive to add** | Sleep consolidation / offline recurrence (timescale 2). Contract §6 notes: Kai's v0 success criterion maps 1:1 to ember's terminal condition ("one temporary adapter → one durable expert with causal claim + deletion-test proof"). |
| **Downscale smoke-test plan** | 100M base model converged: <br>- Spin up SDEK harness with base core + LoRA workspace (adapter rank=32) <br>- Generate 10 episodes on MBPP (k=4 tries each) <br>- Measure: F = solved-tasks-per-GPU-hour <br>- Create 1 temporary LoRA adapter from successful episodes <br>- Run four-arm evaluation (base / deleted / context-only / random initialization) <br>- Pass/fail: deleted arm shows ≤50% of base's solve rate (causal claim holds); context-only shows <20% of base (not just memorization) |
| **Ledger format** | JSONL receipts (same as ember's t1/t2/t3/t4 tickets). Adapter metadata: rank, target_modules, rank_bsz, episodes_used, deletion_test_result. |
| **Convergence fact** | Contract §6: "NC0 already IS SDEK-v0 minus the scheduler." NC0's t1/t2/t3/t4 tickets ARE this ledger. Adoption of Kai's v0 scheduler for NC2 is a formalization step, not a new invention. |

---

### 8. Muon FP8 mixed-precision (SKIPPED for RTX 4090)

| Property | Value | Source / Note |
|----------|-------|---|
| **Disposition** | SKIP (per survey verdict, contract §9 row 7) | TE silent-BF16-fallback reports; torchao tensorwise-only on sm89 (4090 is sm89); zero published 4090 FP8 pretrain receipts |
| **Rationale** | Ada (4090) has INT8 tensor cores; FP8 tensor cores are not mainline. Reported consumer-stack FP8 setups (TE, torchao) fall back to BF16 silently. No evidence of ≤1B FP8 recipes on consumer cards. Adoption risk outweighs efficiency gain at this scale. |
| **Fallback** | Full BF16 training (default). If late-stage training slows, revisit FP8 post-pilot with a verified consumer recipe. |

---

### 9. Attention Architecture — GQA + FlashAttention + QK-norm

| Property | Value | Source / Note |
|----------|-------|---|
| **Pinned as** | Gemma-4 attention block (encoder-free multimodal architecture) | https://huggingface.co/google/gemma-2-9b-it (source of unified architecture design) |
| **License** | Gemma-4 model weights Apache-2.0 | Architecture patterns are reusable; inference code in HF transformers |
| **Components** | GQA (grouped query attention): shared key/value heads across query groups, ~10% VRAM + compute savings | DeepSeek-V2, Gemma-4 published evaluations (no ppl loss at ≤1B, 2–3% VRAM reduction realistic) |
|  | FlashAttention (https://github.com/Dao-AILab/flash-attention, Apache-2.0): IO-aware implementation, ~3–4× faster, no quality delta | Published 2023–2024; PyTorch 2.0+ includes native flash-attn; no external dependency needed |
|  | QK-norm: z-loss style normalization of Q/K before softmax; prevents gradient explosion in low-bit settings | Gemma-4 deep-dive (contract §8 deep-dive findings); cheap, must be in core from step 0 (unretrofittable) |
| **RTX 4090 feasibility** | ✓ Feasible | All three are implemented in mainline PyTorch + transformers. No custom kernels needed (Flash-attn has optimized CUDA, but fallback works). GQA reduces VRAM footprint for large-context sampling. |
| **Multimodal locks (v0 contracts)** | 1. Reserved vocab band: ~7 delimiter/placeholder token IDs pre-assigned (for multimodal span markers) <br> 2. `inputs_embeds` splice path: soft tokens overwrite placeholder embedding rows (encoder-free mechanism) <br> 3. Per-span bidirectional attention inside causal mask (image spans get attention to themselves + prior context) <br> 4. Per-channel RoPE with head_dim % 4 == 0 (2D RoPE splits head dims x/y for spatial encoding) | Contract §8 locks section. All must be in vocab + attention from step 0. Retrofit-proven later: embedder, audio, QAT. |
| **Downscale smoke-test plan** | 100M model with GQA (num_key_value_heads=4, num_query_heads=16): <br>- Measure: VRAM peak during training (batch=16, seq=2048) <br>- Compare to dense attention baseline <br>- Measure: throughput (tokens/sec/step) vs dense <br>- Pass/fail: ≤20% VRAM over dense, ≥95% throughput |
| **Future multimodal integration** | Vision embedder (~35M params, continuous soft tokens) retrofit-proven in Mono-InternVL. Audio: raw 16kHz projection (no mel-spectrogram). Both post-pretrain additions; core architecture is text-only v0. |

---

### 10. Gemma-4 Unified Multimodal Architecture (encoder-free foundation)

| Property | Value | Source / Note |
|----------|-------|---|
| **Pinned as** | Gemma-4 12B unified architecture (soft-token vision, text + audio tokenizer slots reserved) | https://huggingface.co/google/gemma-2-9b-it (weights + HF card documentation). Deep-dive reference: contract §8 section. |
| **License** | Gemma-4 weights Apache-2.0 | Architecture pattern is public; reusable in ember owned-core at smaller scale |
| **"Unified" means** | Fuyu-style continuous soft tokens (NOT discrete codes): image patches tokenized as 6912-float vectors (48×48px → single matmul into model width), audio as raw 16kHz projection. All modalities enter the main transformer via `inputs_embeds` splice. | Contract §8 deep-dive: this is NOT encoder-free in the "no vision encoder" sense; it IS unified in the "no frozen separate encoder tower" sense — the ~35M vision embedder is lightweight, adaptive, on-device |
| **v0 architectural locks** (cannot retrofit) | 1. **Reserved vocab band:** ~7 placeholder token IDs for multimodal span delimiters (e.g., `<image>`, `<audio>`, span-end markers). Assigned at tokenizer init. | 2. **`inputs_embeds` splice path:** model's forward pass accepts both token_ids AND pre-computed soft token embeddings; at runtime, placeholder rows get overwritten with vision/audio tensors. Standard HF pattern (similar to Qwen-VL). | 3. **Per-span bidirectional attention:** inside the causal mask, image span tokens attend to themselves (2D RoPE for spatial coherence) + all prior context. Requires `attn_mask` capability; PyTorch standard. | 4. **Per-channel RoPE:** head_dim % 4 == 0 required. Allows split of head dimensions into [x_position, y_position] for 2D positional encoding. (Standard heads: head_dim=128 or 64, both divisible by 4). Plus QK-norm from step 0. |
| **Retrofit-proven later** | Vision embedder (48×48 patching + linear projection), audio frame projection, modality expert LoRA adapters, QAT quantization, post-hoc speculative-decode drafter. All can be added after text-only base converges without changing core architecture. |
| **RTX 4090 feasibility** | ✓ Feasible at 0.5B dense | Smallest working encoder-free prior art is 1.8B (Mono-InternVL). Sub-1B is unexplored territory — NC2-own RESERVES multimodal capability in the core, but v0 is TEXT-ONLY and does NOT promise multimodal at 0.5B. The four locks ensure multimodal can be added later; they do NOT guarantee quality at small scale. |
| **Failure risk** | Fuyu 10.7% MMBench, EVE stage-skip collapse, Mono-InternVL catastrophic forgetting on multimodal tasks. All ≥1.8B models. Sub-1B unified pretraining is experimental. NC2-own admission (contract §8 honesty line): v0 failure to converge on multimodal is possible; proof point is 1B→3B rung expansion + measured MMBench ≥15%. |
| **Downscale smoke-test plan** | 100M text-only pretrain with all four locks in place (but no vision/audio input): <br>- Verify: vocab has 7 reserved slots (no loss of coverage) <br>- Verify: `inputs_embeds` path compiles (even if not used) <br>- Verify: per-span bidir attn compiles (masked, unused in text phase) <br>- Verify: RoPE splits head_dim cleanly (head_dim % 4 == 0) <br>- Measure: loss convergence vs architecture without locks (proxy for overhead) <br>- Pass/fail: locks impose ≤0.05ppl overhead; text loss remains on-track |
| **Retrofit readiness** | After 100M base converges: (a) add vision embedder (48×48 patcher + linear proj ~35M params), (b) freeze base, LoRA-train on image+caption pairs (synthetic or harvested), (c) measure multimodal loss on 1k eval images. Quality gate: ≤2ppl multimodal loss (very loose), decide whether to merge or defer. |

---

### 11. Replay & Consolidation (SDEK timescale 2) — BUILDING COMPONENT

| Property | Value | Source / Note |
|----------|-------|---|
| **Pinned as** | CUSTOM. No public release; research-phase in all surveyed ecosystems. | Contract §1.4: "sleep-consolidation (2605.26099) — offline recurrence mechanism reproducible at our scale; what's the substrate of its fast weights?" Survey verdict: GDN/Jet SSM delta-rule (fast weights = gated delta-rule SSM state matrices, backprop-through-sleep-passes). Receipt: contract §9 disposition row 6. |
| **Substrate** | Fast weights = gated-delta-network (GDN) or Jet (gated exponential timegate) SSM state matrices (from arxiv 2605.26099, Ouro-1.4B experiment: 41.9→61.5% GSM-Infinite). | Sleep paper shows efficacy at 1.4B; no code release; reverse-engineered from paper description. |
| **Role in stack** | Middle timescale of SDEK (immediate wake = KV context, fast-weight session = consolidated from offline replay, durable = LoRA experts). Implements "sleep consolidation" primitive missing from Kai's v0 kernel. |
| **Implementation path** | (a) Standard LoRA adapter structure (rank=32–64) for base model. (b) Offline recurrence loop: replay successful episodes from t3/t4 ledger, backprop through sleep passes (forward, lose gradient info, re-forward with selective backprop). (c) Measure: does single fast-weight pass (no grad) + Jet-layer projection recover ≥70% of LoRA adapter quality vs full forward+backward? |
| **RTX 4090 feasibility** | ? UNVERIFIED | Replay requires storing episode tensors (states, actions, rewards) — size depends on context length and episode count. 100 episodes × 2k context × float32 ≈ 25MB per episode = manageable. Jet layer forward is standard RNN-like (no expensive attention). Backward through sleep passes is unknown cost — possibly amortized across episodes. Needs pilot measurement. |
| **Downscale smoke-test plan** | 100M base model + 10 successful episodes (from t3/t4): <br>- Create LoRA adapter (rank=32) initialized from episode gradients <br>- Train Jet-layer SSM state matrix via sleep recurrence (500 steps) <br>- Measure: does Jet-trained adapter match LoRA adapter on 20 eval tasks? <br>- Pass/fail metric: solve rate within 5% of LoRA (accounting for noise) |
| **Open questions** | (Q1) Does Jet-layer training stabilize at small scale (<100M base)? UNVERIFIED. (Q2) Is the sleep backprop through SSM layers differentiable in pytorch? Needs code audit of Ouro-1.4B or arxiv 2605.26099 supplementary. (Q3) How many sleep passes needed per episode for convergence? |

---

### 12. Verifier-Gated Experience Ledger (SDEK component) — BUILDING COMPONENT

| Property | Value | Source / Note |
|----------|-------|---|
| **Pinned as** | CUSTOM. Exists nowhere in ecosystem; it is this repo. | Contract §1.5 and NC0 implementation (existing t1/t2/t3/t4 tickets). This component is the operational definition of ember. |
| **Core invariant** | Per contract §6: "no learned change becomes durable unless it proves causal benefit under matched-budget deletion tests" — the-search's deletion-test law. | NC0 receipts (t1_smoke, t2_r1, t3_seed, t4_arc1) ARE this ledger. Disposition: adopt NC0's harness structure as-is. Add Kai's SDEK scheduler for NC2 rung. |
| **Three-test gate** | Base solve rate (unmodified core) vs. (a) Deleted LoRA adapter (should drop significantly), (b) Context-only control (should stay near base), (c) Random-init adapter (should stay near base). Adapter is durable only if (a) shows ≥50% performance loss when deleted. | Closure condition (contract §6 convergence fact): "one temporary adapter becomes one durable expert with written causal claim, future-heldout benefit, no guard regression, loss of advantage when deleted." |
| **RTX 4090 feasibility** | ✓ Feasible | Ledger is JSONL + model checkpoints (standard HuggingFace save). Evaluation harness is vLLM inference + simple scoring (task-specific). No special hardware. Peak VRAM: base model + one LoRA adapter ~12–15GB, within 4090 headroom. |
| **Downscale smoke-test plan** | (Already implicitly running as NC0 t1–t4): 100M base model + MBPP/ARC-AGI eval <br>- Generate 20 episodes (base + 4 LoRA try-count variants) <br>- For 3 successful episodes, run deletion test <br>- Measure: solve rate (base=25%, deleted=12%, context-only=24%, random=23%) <br>- Pass/fail: at least 1 of 3 shows ≥40% deletion delta (causal proof) |
| **Ledger fields** | Per SDEK: adapter_id, parent_core_id, training_episodes (episode IDs), three_test_results {base, deleted, context_only, random}, deletion_delta_pct, claim_text, promotion_decision (durable/temporary), timestamp. |
| **Retention policy** | All temporary adapters stay in ledger (deletion-test failures are learning signals). Durable adapters merge into core LoRA workspace (never delete). Ledger is append-only (auditable history). |

---

### 13. Chinese-lab stack adoption (Muon primary; others re-staged)

Per contract §7 and survey verdict (contract §9 row 7):

| Component | Status | Receipt |
|-----------|--------|---------|
| **MLA (DeepSeek latent-compressed KV)** | WATCHING | KV pressure a binding constraint post-training (context length 2k–4k per ARC); MLA payoff measured post-base. Pilot if storage becomes issue. |
| **MTP (DeepSeek)** | RE-STAGED | Pretraining MTP = component 5 (negative ≤1B evidence). Post-hoc drafter = proven pattern. |
| **FP8 mixed-precision (DeepSeek-V3)** | SKIP | Zero published consumer-4090 pretrain receipts; fallback to BF16 |
| **Muon (Moonshot/Kimi)** | **ADOPT** | Same-scale validation (124M, Moonlight ~52% AdamW FLOPs). Receipt: contract §9 disposition row 7. |
| **Fine-grained MoE + loss-free balancing** | SKIP @ ≤1B | Sparsity pays at larger scale. Token budget (20B) is binding constraint; MoE trades VRAM (scarce) for FLOPs (abundant). Skip for NC2. |
| **NSA (DeepSeek) / MoBA (Moonshot) trainable sparse attention** | RE-STAGED | Minimum viable attended-token floor ~1.5–2k ≈ full attention at ARC's 2–4k context. Relevant for NC1c (long-context IFC world), not v0. GDN-hybrid (component 6) keeps the attention class alive now. |
| **Lightning/gated-deltanet hybrids** | WATCHING | Part of sub-quadratic attention class (component 4). GDN pilot measures feasibility. |
| **GRPO (DeepSeek-R1)** | PILOT (narrow) | Critic-free RL for post-SFT phase. Floor ~1.5B (TinyZero 0.5B fails). Conflict with 0.5B core size: either GRPO waits or core grows. Decision: pilot GRPO on 0.5B with non-zero-pass-rate kill (stop if 0 passes on first 5 tasks). If pilot survives, integrate; if not, defer to 1B+ rung. Receipt: contract §9 disposition row 7, conflict note. |

---

## Integration Sequencing (ember NC2 entry path)

1. **At NC2 entry gate (NC0 terminal condition met):**
   - Survey → pilot plan written (no pretrain spend yet)
   - Component compatibility checks (contract §8 Qs 1–8) via literature + dry runs

2. **Week 1: component pilots (days, not weeks)**
   - 100–300M BitNet + Muon + int4-QAT tail (5B tokens)
   - Measure: ternary quality gap at small scale
   - Decision: int4-QAT carries ≤1B, or ternary goes full run

3. **Week 2–3: full pretrain (if pilots survive)**
   - ~0.5B dense or ternary (user's decision post-pilot)
   - 20B tokens on 4090 (interruptible windowed bursts, not continuous)
   - Muon(hidden) + AdamW(embed/head)
   - Dolma+DCLM data pipeline

4. **Week 4+: evaluation & adaptation rung**
   - SDEK harness spinup (Foundation Runtime + Evaluation Harness)
   - t1 smoke tests on MBPP / ARC-AGI (frozen core benchmarking)
   - t2 LoRA accumulation loop (20–50 episodes, deletion-test gate per component 12)
   - t3 seed diversification (multiple random seeds, convergence check)
   - t4 long-run ARC validation (multirun, statistically valid pass rate)

5. **Decision point (NC2 rung completion):**
   - If core + ledger together reach verifier floor (per GOAL.md), promote durable experts
   - If not, diagnose (component swap, data, tokenizer) and iterate
   - Next rung decision (1B core, or 3B ternary) user's call

---

## Pass/Fail Criteria Summary

### Component-level passes (smoke-scale)

| Component | Smoke Model | Smoke Data | Pass Metric | Fail → Action |
|-----------|-------------|-----------|------------|---|
| QAT int4 (§1) | 100M | 100M tok | ppl ≤0.5 gap vs BF16 | Escalate to Muon/LR tuning; if no fix, int4 → fallback INT8 testing |
| turboquant (§2) | 100M exported model | synthetic | export <30s, inference ≥10 tok/s CPU | escalate, unclear what to fallback to — UNVERIFIED |
| BitNet (§3) | 100–300M ternary | 5B tok | ppl ≤0.3 gap vs baseline | ternary deferred to ≥3B rung; int4-QAT final |
| Muon (§4) | 100M | 100M tok | ≥1.5× convergence speed OR ≥2× final-loss improvement | all-AdamW fallback (no efficiency gain); investigate Muon×QAT interaction |
| SDEK harness (§7) | 100M base + 10 episodes | MBPP k=4 | ≥1 of 3 episodes shows ≥40% deletion delta | SDEK harness scope re-frame; escalate (unknown fix) |
| Consolidation/Jet (§11) | 100M + 10 episodes | replay loop | Jet-trained adapter within 5% solve rate of LoRA | Jet layer design issue; defer sleep-consolidation to ≥1B rung |
| Verifier gate (§12) | 100M base | 20 episodes | ≥1 episode passes three-test gate | ledger/evaluation harness malfunction; core gating broken |
| Attention (GQA+FA, §9) | 100M | 2k seq length | ≤20% VRAM overhead, ≥95% throughput | GQA issue; revert to dense attention |
| Gemma-4 locks (§10) | 100M text-only | pretrain | ≤0.05ppl overhead vs no-locks baseline | Architectural lock design; simplify (drop lowest-leverage locks) |

### Full pretrain gate (if all smoke tests pass)

- Core converges to 1.0 ppl at 20B tokens (typical for 0.5B models at this data scale)
- SDEK harness produces ≥5 durable LoRA experts with causal proofs (deletion-test ≥40% delta)
- t4 arc1 pass rate ≥15% (baseline acceptable for small-scale; scales with adaptation rung)
- Zero OOM events during 3-week window (VRAM headroom maintained)

---

## Open Questions & Unverified Claims

1. **torchao int4 QAT pretrain loop integration** (§1): documented only for inference. Does torchao expose a pretrain-harness API, or must we wire fake-quant ops manually? UNVERIFIED.

2. **turboquant post-NC2-entry** (§2): avir-cli status currently deferred. Is turboquant integration timing on the critical path for NC2 entry, or can we defer export infrastructure to "resident form finalization" rung? UNVERIFIED.

3. **Muon × BitNet STE interaction** (§3, contract §8 Q2): does Muon's orthogonalized update fight ternary STE? No published interaction. Must test during pilot.

4. **Muon × QAT interaction** (§4, contract §8 Q7): AdamW on embed/head with fake-quant; Muon on hidden layers. Is there a training-loop incompatibility (e.g., different learning-rate schedules for the two optimizer branches)? UNVERIFIED.

5. **BitNet × MTP output-head conflict** (§3, contract §8 Q1): ternary output weights + auxiliary heads predicting stacked tokens. Does ternary precision hurt auxiliary-loss gradient signal? No co-use published. Deferred to post-pilot.

6. **Sleep-consolidation (Jet SSM) at ≤100M** (§11, contract §8 Q6): arxiv 2605.26099 validates at 1.4B. Is the mechanism reproducible at <100M? Needs pilot measurement.

7. **GRPO floor conflict** (§13, contract §9 conflict): TinyZero 0.5B fails; GRPO floor ~1.5B. If GRPO pilot on 0.5B shows zero passes, do we escalate to 1B core (token budget undertrains) or drop GRPO? UNVERIFIED; user decision pending pilot.

8. **Sub-1B encoder-free multimodal** (§10, contract §8 Q5): smallest known = 1.8B (Mono-InternVL). NC2-own v0 is text-only with locked architectural slots. Retrofit-proven at 1B+; ≤1B is unexplored. Admission in contract: v0 failure risk accepted.

9. **Dolma+DCLM downscale receipt** (§6): medium confidence per contract §1. Is the training harness downscaling (multi-GPU defaults → single-GPU) straightforward, or are there hidden gradient-accumulation / batch-norm interactions that break at small batch? #28's smoke-scale AC tests this.

10. **MLA (latent-compressed KV, §13)** (component 7): measured payoff in DeepSeek-V3 at 671B. Is the mechanism feasible and necessary at ≤1B, 2–4k context? WATCHING — defer to post-base if KV becomes an issue.

---

## Architecture Decision Record (ADR)

| Decision | Rationale | Revision Trigger |
|----------|-----------|---|
| dense 0.5B, not MoE | Token budget binding; sparsity pays at larger scale. VRAM abundant relative to FLOPs. Muon delivers efficiency without sparsity. | If pretrain stalls at 0.5B despite Muon, escalate to 1B (not MoE). |
| BF16 full pretrain, not FP8 | Zero published consumer-4090 FP8 pretrain receipts. TE silent-fallback, torchao sm89-limited. Risk > reward. | Revisit post-pilot with verified consumer FP8 recipe. |
| int4-QAT, not ternary lead | Ternary pilot decides; if gap >0.3ppl, int4-QAT is NC2 primary. | If pilot shows <0.2ppl gap, ternary becomes primary; user decides 3B escalation. |
| Muon(hidden)+AdamW(embed/head), not all-Muon | Embedding/head rows are low-rank; orthogonalization may amplify rank collapse. Conservative split empirically unproven but theoretically safer. | If Muon on embed/head shows ≥5% training speedup without loss, flip to all-Muon. |
| Drafter-only MTP, not pretraining | Negative ≤1B evidence (META 2404.19737). Post-hoc speculative decode proven on Gemma-4. | If future <1B model proves MTP pretraining viable, reconsider. |
| Text-only v0 multimodal | Sub-1B encoder-free multimodal unproven. Architectural locks ensure retrofit path; no quality promise at 0.5B. | If retrofit to 1B + measured MMBench ≥15%, declare v0.5 multimodal-capable. |
| Gemma-4 architecture shape | Unified soft-token design, existing public reference. Encoder-free lines up with "owned" directive (no frozen borrowed encoders). | If smaller non-Gemma4 multimodal architecture published and validated <1B, evaluate adoption. |

---

## Residency Budget Gate (user 2026-06-10, binding)

Ember lives **comfortably** on this machine:
- **Steady-state inference:** ternary/int4 → CPU-viable or low-VRAM (not GPU-always)
- **Training bursts:** scheduled, windowed, interruptible (not perpetual GPU occupation)
- **Goal:** smallest core that clears verifier floor

**Budget constraints (from residency, not compute scarcity):**
- Ternary 1B ≈ 0.2GB weights (CPU inference possible)
- int4 1B ≈ 0.5–0.7GB weights (CPU inference + GPU context <8GB)
- Pretrain on 4090: 20B tokens ≈ 2–3 weeks at 100 tok/s (interruptible; not continuous)

**Fallback if core-grows required:** 1B dense training (3–4 weeks, user escalation to confirm VRAM/schedule impact).

---

## References & Receipt Locations

| Item | Receipt / URL | Verified | Date |
|------|---|---|---|
| DCLM data pipeline | https://github.com/mlfoundations/dclm | ✓ | 2026-06-10 |
| Dolma curation | https://github.com/allenai/dolma | ✓ | 2026-06-10 |
| OLMo-core curriculum | https://github.com/allenai/OLMo-core | ✓ | 2026-06-10 |
| Muon optimizer | https://github.com/KellerJordan/Muon | ✓ | 2026-06-10 |
| torchao QAT | https://github.com/pytorch/ao | ✓ | 2026-06-10 |
| BitNet + bitnet.cpp | https://github.com/microsoft/BitNet | ✓ | 2026-06-10 |
| Gemma-4 architecture | https://huggingface.co/google/gemma-2-9b-it | ✓ | 2026-06-10 |
| Sleep consolidation paper | arxiv 2605.26099 | ✓ | contract §6 |
| Muon same-scale validation | "modded-nanogpt 124M; Moonlight" — source from contract §9 disposition row 7 | UNVERIFIED — contract cites, no primary URL | 2026-06-10 |
| NC0 receipts (smoke baseline) | B:/M/avir/leo/state/nc-ladder/receipts/t1-smoke-*.json, t2-r1-*.json, t3-seed-*.json, t4-r1-*.json | ✓ local | 2026-06-09/10 |
| Contract § & disposition table | B:/M/avir/leo/state/nc-ladder/nc2-own-technique-contract.md | ✓ local | 2026-06-10 |
| Synthesis (ecosystem survey) | B:/M/avir/leo/state/nc-ladder/research/external-stack/SYNTHESIS.md | ✓ local | 2026-06-10 |

---

## Next Steps (for lead gate & revision)

1. **URL verification:** Lead should re-verify all GitHub/HF URLs (§ component pins) to confirm 2026-06-10 state unchanged.
2. **Muon primary citation:** Contract cites "Moonlight ~52% AdamW FLOPs" but no direct URL given. Lead should locate the actual Moonshot paper / release note.
3. **turboquant status:** Confirm avir-cli post-NC2-entry timeline with Eli/user. If critical path, accelerate intake.
4. **Pilot schedule:** Lead to confirm whether 100–300M BitNet pilot (§3) runs in parallel with other components or sequentially.
5. **Gate integration:** Formalize pass/fail thresholds (§ Pass/Fail Criteria Summary) as acceptance tests in the harness code before smoke tests begin.

---

**Draft authored:** 2026-06-10 (Leo / Claude Code subagent)  
**Status:** awaiting lead gate + revision before PR  
**Do NOT merge into main without lead approval**

