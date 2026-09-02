# Gemma 4 "Unified" (Encoder-Free) Multimodal Architecture — Research for the ~1B Owned Core

**Date:** 2026-06-09. **Purpose:** architectural template study for a small (~0.5–1B) from-scratch multimodal-capable pretrain on one RTX 4090, where v0 is text-only but must RESERVE unified-multimodal capability with no architecture break.

**Method note:** Gemma 4 12B Unified shipped 2026-06-03; no arXiv technical report was found as of 2026-06-09 — the primary sources are Google's launch blog, the developer guide, the official model card, the HF transformers `Gemma4` implementation docs, and HF model cards. Searches for a "Gemma 4 technical report" on arXiv returned only third-party coverage. Treat per-source attribution below accordingly.

---

## 1. What makes Gemma 4 12B "unified" / encoder-free

**The claim, verbatim:** "Gemma 4 12B eliminates these encoders entirely, projecting raw image patches and audio waveforms directly into the LLM's embedding space through lightweight linear layers" — official model card ([ai.google.dev/gemma/docs/core/model_card_4](https://ai.google.dev/gemma/docs/core/model_card_4)). Launch blog: vision uses "a single matrix multiplication, positional embedding and normalizations"; for audio "we removed the audio encoder entirely and projected the raw audio signal" ([blog.google introducing-gemma-4-12b](https://blog.google/innovation-and-ai/technology/developers-tools/introducing-gemma-4-12b/)).

Only the **12B** is "Unified." The rest of the Gemma 4 family (E2B, E4B, 26B-A4B MoE, 31B dense) keeps dedicated encoders: ~150M vision encoder for E2B/E4B, ~550M for 31B, ~300M audio (Conformer over mel-spectrograms on E2B/E4B) ([model card](https://ai.google.dev/gemma/docs/core/model_card_4); [HF transformers Gemma4 doc](https://huggingface.co/docs/transformers/model_doc/gemma4)). So within one family Google ships both philosophies, and the encoder-free one is the mid-size laptop model.

### Vision path (continuous patches, NOT discrete codes)

Per the developer guide ([developers.googleblog.com gemma-4-12b-the-developer-guide](https://developers.googleblog.com/gemma-4-12b-the-developer-guide/)) and two corroborating teardowns ([lilting.ch](https://lilting.ch/en/articles/gemma-4-12b-unified-encoder-free), [Grootendorst visual guide](https://newsletter.maartengrootendorst.com/p/a-visual-guide-to-gemma-4-12b)):

- **Patching:** image → 16×16 px patches, then 3×3 spatial pooling → effective **48×48 px patches** ("both height and width must be divisible by 48 (= patch size 16 × pooling kernel 3)" — [HF transformers doc](https://huggingface.co/docs/transformers/model_doc/gemma4)). Natural aspect ratio preserved; no square-resize.
- **Projection:** each patch flattens to 48×48×3 = **6,912 floats**, projected by a **single [6912 × 3840] matmul** to the LLM hidden dim (~26.5M params) ([lilting.ch](https://lilting.ch/en/articles/gemma-4-12b-unified-encoder-free); dev guide: "Raw 48x48 pixel patches are projected to the LLM hidden dimension with a single matmul").
- **Position:** "a factorized coordinate lookup (X and Y matrices) attaches spatial location information directly to the input" ([dev guide](https://developers.googleblog.com/gemma-4-12b-the-developer-guide/)). Two learned tables, one per axis; embeddings for a patch's (x, y) are looked up and **added** ([Grootendorst](https://newsletter.maartengrootendorst.com/p/a-visual-guide-to-gemma-4-12b)). Sizes conflict across sources: lilting.ch says [1120 × 3840] per axis (~8.6M params); the HF `Gemma4VisionConfig` has `position_embedding_size` default **10240** ("stores up to 10,240 positions per axis") ([HF doc](https://huggingface.co/docs/transformers/model_doc/gemma4)). UNVERIFIED which number applies to the 12B Unified checkpoint specifically (the HF config defaults appear to describe the encoder-bearing variants).
- **Norm:** "a final LayerNorm for stability" before tokens enter the sequence ([Grootendorst](https://newsletter.maartengrootendorst.com/p/a-visual-guide-to-gemma-4-12b)). Notably "Gemma 4 does **not** apply the standard ImageNet mean/std normalization … the model's own patch embedding layer handles the final scaling internally (shifting values to the [-1, 1] range)" ([HF doc](https://huggingface.co/docs/transformers/model_doc/gemma4)).
- **Total embedder: ~35M params** (≈26.5M matmul + ≈8.6M positional + ≈0.9M norms, per [lilting.ch](https://lilting.ch/en/articles/gemma-4-12b-unified-encoder-free)) replacing the 150M encoder of E4B — "35M linear projection replaces 150M 16-layer Vision Encoder" ([lilting.ch](https://lilting.ch/en/articles/gemma-4-12b-unified-encoder-free)). No attention in the embedder; "each patch is processed independently" ([MarkTechPost](https://www.marktechpost.com/2026/06/03/google-deepmind-releases-gemma-4-12b-an-encoder-free-multimodal-model-with-native-audio-that-runs-on-a-16-gb-laptop/)).
- **Token budget:** configurable `num_soft_tokens` per image — 70 / 140 / **280 (default)** / 560 / 1120, covering ~161K to ~2.6M px image area ([HF transformers doc](https://huggingface.co/docs/transformers/model_doc/gemma4); [model card](https://ai.google.dev/gemma/docs/core/model_card_4)).
- **Attention compensation:** "the causal mask is removed for image tokens during the attention computation in the LLM body's 48 layers, allowing all patches to reference all patches" ([lilting.ch](https://lilting.ch/en/articles/gemma-4-12b-unified-encoder-free)). This is first-class in the HF implementation: `use_bidirectional_attention` — "When set to `\"vision\"`, vision tokens attend bidirectionally while text tokens use causal attention" — plus `mm_token_type_ids` ("text (0), image (1), video (2)") to mark the spans ([HF doc](https://huggingface.co/docs/transformers/model_doc/gemma4)). The lost intra-image mixing of a ViT encoder is paid for inside the backbone, not in the embedder.
- **2D RoPE inside the body:** "The 2D RoPE which Gemma 4 uses independently rotate[s] half the attention head dimensions for the x-axis and the other half for the y-axis" for vision tokens ([HF doc](https://huggingface.co/docs/transformers/model_doc/gemma4)); the factorized lookup design "follows the factorized RoPE adopted by Qwen2-VL" ([lilting.ch](https://lilting.ch/en/articles/gemma-4-12b-unified-encoder-free)).

### Audio path (12B only does it raw)

- "Raw 16 kHz audio signals are sliced into 40ms frames (640 floats each) and projected linearly to the LLM input space" ([dev guide](https://developers.googleblog.com/gemma-4-12b-the-developer-guide/)). One 40ms frame → one soft token (`audio_ms_per_token` default 40 in `Gemma4Processor` — [HF doc](https://huggingface.co/docs/transformers/model_doc/gemma4)); max audio length 30 s ([model card](https://ai.google.dev/gemma/docs/core/model_card_4)) → ≤750 tokens (`audio_seq_length` default 750). No mel-spectrogram, no Conformer on the 12B — those exist only on E2B/E4B ([HF doc](https://huggingface.co/docs/transformers/model_doc/gemma4)). Raw amplitude floats in, linear matmul, done.

### Vocabulary / embedding changes vs a text-only model

This is the part most relevant to the ~1B core, and the answer is: **almost nothing changes.**

- **No discrete image/audio codes.** Unlike Chameleon/Emu3, no VQ codebook is added to the vocab. Images and audio enter as **continuous "soft tokens"** (projected embeddings) spliced into the sequence; they never pass through the embedding table or the LM head.
- **Vocab stays 262,144** — same 262K SentencePiece vocab across all Gemma 4 sizes ([model card](https://ai.google.dev/gemma/docs/core/model_card_4)), same count as text-only Gemma lineage.
- **Only a handful of discrete delimiter/placeholder tokens** are needed, and they sit in the reserved range of the tokenizer. From `Gemma4Config` defaults ([HF doc](https://huggingface.co/docs/transformers/model_doc/gemma4)): `boi_token_id=255999`, `boa_token_id=256000`, `image_token_id=258880`, `audio_token_id=258881`, `eoi_token_id=258882`, `eoa_token_index=258883`, `video_token_id=258884`. The placeholder token (e.g. `<image>`) is expanded by the processor to N copies and the N embedding rows are **overwritten** with the soft tokens — the embedding table entry itself is a dummy. Mechanism inherited from Gemma 3's `<start_of_image>` expansion ([vLLM Gemma4 recipe](https://docs.vllm.ai/projects/recipes/en/latest/Google/Gemma4.html)).
- Ordering convention in chat template: images "before text," audio "after text" ([HF gemma-4-12B model card](https://huggingface.co/google/gemma-4-12B)).
- (Family note, not 12B-specific: E2B/E4B add **Per-Layer Embeddings** — `vocab_size_per_layer_input=262144`, `hidden_size_per_layer_input=256`, with "for multimodal inputs where input_ids are not available, only the context-aware projection is used" — [HF doc](https://huggingface.co/docs/transformers/model_doc/gemma4). PLE is a memory-saving device for edge, orthogonal to unification.)

### Backbone context (what the soft tokens land in)

12B Unified: 11.95B params, 48 layers, 262K vocab, 256K context, "hybrid attention mechanism that interleaves local sliding window attention with full global attention, ensuring the final layer is always global," 1024-token sliding window, global layers with "unified Keys and Values" + "Proportional RoPE (p-RoPE)" ([model card](https://ai.google.dev/gemma/docs/core/model_card_4)); "the same advanced decoder structure as the Gemma 4 31B Dense model" ([dev guide](https://developers.googleblog.com/gemma-4-12b-the-developer-guide/)). Multi-Token Prediction drafters ship alongside for ~3x speculative-decoding speedup, sharing the target model's embedding table ([InfoQ](https://www.infoq.com/news/2026/05/gemma4-multi-token-prediction/); [ai.google.dev MTP overview](https://ai.google.dev/gemma/docs/mtp/overview)). Training data "web documents, code, images, audio," cutoff January 2025, 140+ languages ([model card](https://ai.google.dev/gemma/docs/core/model_card_4)).

**UNVERIFIED:** whether the 12B was pretrained multimodal from scratch or adapted from a text checkpoint. The release materials do not say ([MarkTechPost summary of disclosure gaps](https://www.marktechpost.com/2026/06/03/google-deepmind-releases-gemma-4-12b-an-encoder-free-multimodal-model-with-native-audio-that-runs-on-a-16-gb-laptop/)); training-data listing (images+audio in pretrain mix) implies native multimodal pretrain but Google has not published stages, ratios, or stability tricks. Also UNVERIFIED: any Gemma-4-specific QK-norm/z-loss-style stability measures (no technical report yet).

---

## 2. The QAT release (incl. 12B Unified W4A16)

Released ~2026-06-06 ([Google QAT blog](https://blog.google/innovation-and-ai/technology/developers-tools/quantization-aware-training-gemma-4/); [winbuzzer](https://winbuzzer.com/2026/06/06/google-releases-smaller-gemma-4-models-for-local-ai-xcxwbn/)). Four checkpoint flavors per model ([HF gemma-4-12B-it-qat-q4_0-unquantized](https://huggingface.co/google/gemma-4-12B-it-qat-q4_0-unquantized)):

1. **Unquantized-QAT** — "half-precision weights extracted from the QAT pipeline, ideal for custom downstream compilation and research."
2. **GGUF Q4_0** — "the popular Q4_0 quantization format" for llama.cpp/Ollama/LM Studio.
3. **Mobile format** — "a novel quantization format specialized for mobile use cases"; "we've reduced the memory footprint of Gemma 4 E2B to 1GB" ([QAT blog](https://blog.google/innovation-and-ai/technology/developers-tools/quantization-aware-training-gemma-4/)); 0.84 GB reported for E2B ([GIGAZINE](https://gigazine.net/gsc_news/en/20260608-google-ai-gemma-4-qat/)).
4. **Compressed-tensors w4a16** — "QAT checkpoints serialized in the compressed-tensors format for native, optimized inference with vLLM," available for **E2B, E4B, 12B, 31B** ([HF gemma-4-12B-it-qat-w4a16-ct](https://huggingface.co/google/gemma-4-12B-it-qat-w4a16-ct)). w4a16 = 4-bit weights, 16-bit activations.

**Recipe disclosure is thin.** The Gemma 4 cards state only "by simulating quantization during training, QAT minimizes quality loss" and "QAT results yield even higher overall quality compared to standard PTQ baselines" ([QAT blog](https://blog.google/innovation-and-ai/technology/developers-tools/quantization-aware-training-gemma-4/)). No steps, no distillation detail, no group size, no layer-exclusion list, no statement on whether the 35M vision embedder / audio projection are quantized (UNVERIFIED — the w4a16-ct card "does not disclose … whether the multimodal vision/audio pathways receive special treatment"). The known lineage is **Gemma 3 QAT**: "We applied QAT on ~5,000 steps using probabilities from the non-quantized checkpoint as targets" and "we reduce the perplexity drop by 54% … when quantizing down to Q4_0" ([Gemma 3 QAT dev blog](https://developers.googleblog.com/en/gemma-3-quantized-aware-trained-state-of-the-art-ai-to-consumer-gpus/)). Reasonable inference (UNVERIFIED for Gemma 4): same short-distillation QAT — a few-thousand-step fine-tune with fake-quant ops, teacher = the bf16 checkpoint's output distribution.

Independent quality signal: Unsloth measured Q4_0-conversion fidelity — 12B QAT at "88.76%" top-1 vs "74.08%" naive Q4_0, and notes the QAT GGUFs are released at one precision because "precisions higher than the uploaded UD-Q4_K_XL version degrade accuracy rather than improve it" ([Unsloth Gemma 4 QAT docs](https://unsloth.ai/docs/models/gemma-4/qat)). Third-party framing: ~72% VRAM cut vs bf16 ([Digg/aggregate](https://digg.com/ai/50gy1fa0); [gadgetbond](https://gadgetbond.com/google-gemma-4-qat-quantization-aware-training/)).

**Takeaway for the owned core:** QAT here is not an architecture property — it's a cheap post-pretrain pass (≈5K steps, self-distillation) that any from-scratch model can replicate; the encoder-free design helps only in that there is no separate encoder with its own quantization sensitivity.

---

## 3. Prior-art lineage: encoder-free multimodal

Two distinct families — don't conflate them:

**(a) Continuous-patch, understanding-oriented (Fuyu line — Gemma 4 12B is this):**

- **Fuyu-8B** (Adept, Oct 2023) — the origin: image patches through a single linear projection (~[2700×4096], ~11M params) straight into the decoder ([lilting.ch lineage section](https://lilting.ch/en/articles/gemma-4-12b-unified-encoder-free); [HF adept/fuyu-8b](https://huggingface.co/adept/fuyu-8b)). Worked for OCR/charts, failed at general visual reasoning — "10.7% on MMBench" ([lilting.ch](https://lilting.ch/en/articles/gemma-4-12b-unified-encoder-free)). Lesson: the projection is sufficient mechanically, but without the right data/training the backbone never learns vision semantics.
- **EVE / EVE-7B** (BAAI, NeurIPS 2024) — first to make it respectable: Vicuna-7B + patch embedding + patch-aligned distillation from a ViT, 35M public images; "rivaling encoder-based VLMs and outperforming Fuyu-8B" ([arXiv 2406.11832](https://arxiv.org/pdf/2406.11832); [github.com/baaivision/EVE](https://github.com/baaivision/EVE)). Key negative result: staged training is load-bearing — "doubling the training data from 4M to 8M while skipping Stage 1 caused VQA-v2 to collapse from 64.6% to 50.2%" ([lilting.ch citing EVE](https://lilting.ch/en/articles/gemma-4-12b-unified-encoder-free)).
- **EVEv2** (ICCV 2025 highlight) — "Divide-and-Conquer": **modality-specific weights inside the transformer** (separate attention/FFN/norm params for vision vs text tokens), 4-stage training (patch embed → vision layers w/ frozen LLM → full align → SFT), ~92M pretrain + 7.3M SFT samples at 7B; finding: "significant weight shifts across various network layers between the VLMs and the original LLMs" when modalities share weights — modality interference is the core failure mode ([arXiv 2502.06788](https://arxiv.org/html/2502.06788v1)).
- **Mono-InternVL / -1.5** (CVPR 2025; arXiv Jul 2025) — **the smallest published encoder-free model that clearly works: 1.8B** (InternLM2-1.8B base + 1.2B visual experts via MoE, "embed visual parameters into a pre-trained LLM … via delta tuning, freezing the LLM when optimizing the visual parameters"; +113 points over InternVL-1.5 on OCRBench, first-token latency −67%) ([arXiv 2410.08202](https://arxiv.org/html/2410.08202v3); [github.com/OpenGVLab/Mono-InternVL](https://github.com/OpenGVLab/Mono-InternVL); [Mono-InternVL-1.5, arXiv 2507.12566](https://arxiv.org/html/2507.12566v1)). Their stated diagnosis: naive monolithic training "often suffer[s] from unstable optimization and catastrophic forgetting," fixed by the LLM-centric freeze-and-delta-tune approach ([arXiv 2410.08202](https://arxiv.org/html/2410.08202v1)).
- Adjacent 2025 work: **BREEN** (data-efficient encoder-free via learnable queries, [arXiv 2503.12446](https://arxiv.org/html/2503.12446v1)); HoVLE, SAIL, VoRA (vision-as-LoRA) — same retrofit family. UNVERIFIED: no encoder-free model **below ~1.3B** with credible benchmarks was found in this research pass; sub-1B encoder-free is essentially unpublished territory.

**(b) Discrete-token, early-fusion (Chameleon line — Gemma 4 is NOT this):**

- **Chameleon-7B/34B** (Meta, May 2024) — images → 1024 discrete tokens from an 8192-entry VQ codebook, folded into a 65,536 BPE vocab ("includes the 8192 image codebook tokens"); ~10T mixed-modal tokens ([arXiv 2405.09818](https://arxiv.org/html/2405.09818v1)). See §5 for its stability story.
- **Emu3-8B** (BAAI, Sep 2024) — everything via next-token prediction; SBER-MoVQGAN tokenizer, 512×512 image → 4,096 tokens from a **32,768** codebook; total vocab 184,622 ([arXiv 2409.18869](https://arxiv.org/pdf/2409.18869); [HF BAAI/Emu3-VisionTokenizer](https://huggingface.co/BAAI/Emu3-VisionTokenizer)); Emu3.5 continues the line ([arXiv 2510.26583](https://arxiv.org/pdf/2510.26583)).
- **Show-o (1.3B)** — smallest in this family: Phi-1.5 base + discrete image tokens (MAGVIT-v2), unified understanding **and generation**, "comparable performance … to LLaVA-v1.5-Phi-1.5" ([arXiv 2408.12528](https://arxiv.org/pdf/2408.12528); [showlab tech report](https://showlab.github.io/Show-o/assets/show-o.pdf)). Caveat: a VQ tokenizer is still an encoder by another name — it moves the encoder offline rather than removing it.

**What failed at small scale / in general:** (i) Fuyu-style "just project patches" with naive joint training → no visual reasoning (Fuyu MMBench 10.7%); (ii) skipping alignment stages → benchmark collapse (EVE's 64.6→50.2); (iii) shared weights for both modalities → interference and weight drift away from the language optimum (EVEv2); (iv) unfrozen-LLM joint training at small scale → catastrophic forgetting of language (Mono-InternVL's motivation); (v) encoder-free generally needs disproportionately more multimodal data than encoder-based at the same size — EVEv2 attributes its remaining gap "primarily … [to] significant discrepancy in data magnitude" ([arXiv 2502.06788](https://arxiv.org/html/2502.06788v1)).

---

## 4. What a text-only v0 must decide UP FRONT to reserve unified multimodal

Derived from the Gemma 4 mechanism (§1) plus the retrofit literature (§3). The good news: the Fuyu/Gemma-4 continuous-soft-token design is **deliberately retrofit-friendly** — EVE, Mono-InternVL, and VoRA all grafted it onto finished text LLMs. What cannot be cheaply retrofitted is the token/position bookkeeping.

**Must decide at v0 (architecture-breaking if wrong):**

1. **Vocab reservation.** Size the tokenizer with a reserved, never-trained token band and pre-assign IDs for `<boi>/<eoi>/<image_soft>/<boa>/<eoa>/<audio_soft>/<video_soft>` — exactly Gemma's pattern (255999–258884 inside a 262,144 table — [HF doc](https://huggingface.co/docs/transformers/model_doc/gemma4)). Cost at 1B scale is a few thousand embedding rows ≈ nothing. Re-sizing the embedding + LM head later breaks every downstream checkpoint diff.
2. **Soft-token splice path in the forward pass.** The model code must accept `inputs_embeds` overrides at placeholder positions (and `mm_token_type_ids`-style modality markers) from day one, even if unused. This is plumbing, but if the serving/training stack assumes `input_ids`-only end-to-end (KV cache code, loss masking, packing), retrofitting touches everything.
3. **Attention-mask flexibility.** Gemma 4 flips image spans to bidirectional inside a causal decoder (`use_bidirectional_attention="vision"` — [HF doc](https://huggingface.co/docs/transformers/model_doc/gemma4)). Decide now that the attention kernel takes a per-span mask pattern, not a hardcoded causal triangle. With FlashAttention-style kernels this is a block-mask capability choice; bolting it on after committing to a causal-only fused kernel is painful.
4. **RoPE dimension budget.** Gemma 4 gives vision tokens 2D RoPE by splitting head dims x/y ([HF doc](https://huggingface.co/docs/transformers/model_doc/gemma4)); Qwen2-VL's M-RoPE is the precedent ([lilting.ch](https://lilting.ch/en/articles/gemma-4-12b-unified-encoder-free)). Choose head_dim and RoPE layout so half-splitting (or 3-way t/x/y) is clean — i.e., head_dim divisible by 4, and a RoPE implementation parameterized per-position-channel rather than a single fused 1D rotation. The *weights* don't change; the *kernel contract* does.
5. **Hidden size as the projection target.** The patch matmul is [patch_dim × d_model]. Nothing to reserve except: don't make d_model so small that a 6,912-dim patch projection becomes the information bottleneck. At d_model ≈ 2048 (typical 1B), a 48×48 patch → 2048 is a 3.4× compression vs Gemma's 1.8× — consider 32×32 patches (3,072 → 2048) instead. (Inference, not sourced — flag as a design decision.)
6. **Normalization stance.** Decide v0's norm placement/QK-norm with multimodal in mind (see §5) — adding QK-norm later changes the architecture graph and invalidates the pretrained attention statistics.

**Safely retrofittable later (proven by prior art):**

- The **vision embedder itself** (matmul + X/Y lookups + LayerNorm, ~35M at Gemma scale, ~5–10M at 1B scale): EVE and Mono-InternVL added equivalents to finished LLMs ([arXiv 2406.11832](https://arxiv.org/pdf/2406.11832), [arXiv 2410.08202](https://arxiv.org/html/2410.08202v3)). A v0 "stub" is unnecessary — what matters is the splice path (#2).
- The **audio projection** (640-float frames → d_model): trivially additive, same argument ([dev guide](https://developers.googleblog.com/gemma-4-12b-the-developer-guide/)).
- **Modality-specific experts/weights** (EVEv2 / Mono-InternVL style): added post-hoc by construction — visual experts "initialized from pre-trained MLPs" of the frozen LLM ([arXiv 2410.08202](https://arxiv.org/html/2410.08202v3)).
- **QAT**: a ~5K-step post-pass (§2).
- **MTP drafters**: shipped 5 months after Gemma 4 launch as add-ons sharing the embedding table ([InfoQ](https://www.infoq.com/news/2026/05/gemma4-multi-token-prediction/)).

**Cannot retrofit (avoid these paths):**

- The **Chameleon/Emu3 discrete-code route**: folding an image codebook into the vocab changes embedding table, LM head, loss, and sampling for ALL tokens, and drags in the §5 stability problem at pretrain time. If v0 is text-only, this family is foreclosed unless you re-pretrain.
- A **fused causal-only attention stack** (#3) and a **1D-only RoPE contract** (#4) — both are silent architecture breaks for the unified path.

---

## 5. Training-stability record of encoder-free multimodal, and sub-1B applicability

**Chameleon (discrete early-fusion, the canonical horror story)** — [arXiv 2405.09818](https://arxiv.org/html/2405.09818v1):
- Failure mode: with modalities of "significantly varying entropy," competing norm growth pushed logits "outside the effective representation range of bf16"; softmax-driven divergence in mid-to-late training. Chameleon-7B "diverges after approximately 20% of a training epoch" without fixes.
- Fixes: **QK-Norm** (LayerNorm on queries/keys), **z-loss** at 10⁻⁵·log²Z on the final softmax, **dropout 0.1** (needed at 7B alongside z-loss; not at 34B), **norm reordering** (post-block norm placement, needed ≥~8B), and a conservative LR (1.0×10⁻⁴ vs Llama-2's 3.0×10⁻⁴, 4000-step warmup).
- Scale dependence is explicit in the paper: which fixes are needed varies by size (7B needed dropout+z-loss; 34B needed norm-reordering instead).

**Continuous-patch family (the Gemma 4 route)** — instability shows up as *interference/forgetting*, not bf16 divergence:
- EVE: stage-skipping → collapse (64.6→50.2 VQA-v2) ([lilting.ch citing EVE](https://lilting.ch/en/articles/gemma-4-12b-unified-encoder-free)).
- EVEv2: shared-weight modality interference; text-vs-multimodal data ratio is a "delicate balance" — too much text "slows multimodal capability development," too little causes "catastrophic linguistic forgetting" ([arXiv 2502.06788](https://arxiv.org/html/2502.06788v1)).
- Mono-InternVL: "unstable optimization and catastrophic forgetting" in naive monolithic training; the freeze-LLM/delta-tune EViP schedule "dramatically prevents model collapse" ([arXiv 2410.08202](https://arxiv.org/html/2410.08202v1)).
- Gemma 4 12B: no published stability incident or trick (UNVERIFIED — no technical report; the LayerNorm in the embedder and bidirectional-span attention are the only visible stability-relevant choices).

**Do the Chameleon fixes apply at sub-1B?** Direct evidence: none — no published sub-1B encoder-free run was found (UNVERIFIED territory; EVEv2 explicitly "did not train smaller models below 2B," [arXiv 2502.06788](https://arxiv.org/html/2502.06788v1)). Reasoned transfer: Chameleon's mechanism (entropy mismatch between modalities → norm competition under a shared softmax) is strongest when image tokens share the embedding/LM-head softmax — i.e., the **discrete** route. The continuous soft-token route never puts image content through the final softmax, so z-loss urgency drops; but QK-norm addresses the *inner* softmaxes, which soft tokens DO pass through, and smaller models train in bf16 with the same dynamic range. Cheap insurance: QK-norm costs ~nothing at 1B and is already standard in several modern small models; z-loss is a one-line regularizer. Sub-1B-specific risk skews toward the EVE/Mono-InternVL failure modes (forgetting, interference) because a 1B backbone has far less slack capacity than 7B — expect staging and data-ratio control to matter MORE, and bf16 range divergence to matter less. (This paragraph is synthesis, not sourced.)

---

## What the owned ~1B core must copy from this template — and what to skip

**Copy:**

1. **Continuous soft-token unification, not discrete codes.** One decoder; raw patches (and later 40ms audio frames) → single linear projection + factorized X/Y learned position lookups + LayerNorm → spliced at placeholder positions. It is the cheapest possible multimodal interface (~5–10M params at d_model≈2048), it is retrofit-proven (EVE/Mono-InternVL), and it keeps v0 a pure text model with zero dead weight.
2. **Gemma's vocab bookkeeping, verbatim.** Build the v0 tokenizer with a reserved ID band and pre-assigned `<boi>/<eoi>/<image_soft>/<boa>/<eoa>/<audio_soft>` IDs at fixed positions. This is the single highest-leverage no-regret decision — costs kilobytes now, saves a re-pretrain later.
3. **The three kernel contracts:** (a) forward pass accepts `inputs_embeds` + modality-span markers; (b) attention supports per-span bidirectional blocks inside the causal mask; (c) RoPE is implemented per-channel so head dims can later split x/y (head_dim % 4 == 0). These are v0 code-shape decisions, not v0 weights.
4. **QK-norm from step 0, z-loss as a config flag.** Chameleon's inner-softmax fix is cheap, standard, and removes the one divergence class that cannot be fixed after pretrain; z-loss can stay off for text-only v0 and flip on for the multimodal continue-pretrain.
5. **Staged multimodal onboarding when the time comes:** freeze the text backbone, train embedder first (EVE Stage-1 / Mono-InternVL EViP pattern), control the text:multimodal ratio explicitly. At 1B, forgetting is the enemy, not bf16 overflow.
6. **The QAT pattern** (later, optional): ~5K-step self-distillation against the bf16 checkpoint before any int4 deployment.

**Skip:**

- **Discrete VQ image tokens in the vocab** (Chameleon/Emu3/Show-o): forecloses nothing we need (understanding-first), imports the worst stability profile, and cannot coexist with a text-only v0.
- **A vision encoder of any size** — defeats the purpose; the 4090 budget can't carry a 150M+ tower plus the backbone, and Gemma 4 just demonstrated the encoder is droppable at production quality.
- **PLE (per-layer embeddings)**: an edge-memory trick for Gemma's E-series; complexity with no payoff at 1B on a 24GB card.
- **MoE / modality-experts at v0**: EVEv2/Mono-InternVL's expert separation is a *retrofit* mechanism — adopt it only if shared-weight interference actually shows up in the multimodal phase.
- **MTP drafters, 256K context, 262K vocab size itself**: scale furniture, not template. A ~1B core wants a much smaller vocab (32–64K) — just with the reserved band from item 2.
- **Copying Gemma's exact patch geometry blindly**: 48×48 patches → d_model 2048 over-compresses relative to Gemma's ratio; pick patch size so patch_dim/d_model stays ≈1.5–2× (e.g. 32×32×3=3,072 → 2048).

The one-sentence version: **the template's value is not the 35M matmul — it's that Gemma 4 proves a plain causal LM with reserved token IDs, a splice-able embedding path, span-bidirectional attention, and a 2D-capable RoPE needs nothing else to become multimodal; v0 must lock those four contracts and can defer every gram of multimodal weight.**
