# NC2 Technique Survey — from-scratch pretrain on 1× RTX 4090 (24GB, Ada/sm89)

Date: 2026-06-09. Target: ~0.1–1B params, ~20B tokens, 2–4k context, single 4090.
Method: WebSearch + WebFetch, June 2026. Every claim cited inline. Unverified claims marked UNVERIFIED.

---

## 1. BitNet b1.58 ternary from-scratch training

**What it is.** Train a decoder-only transformer from scratch with ternary weights {-1, 0, +1} (1.58 bits) and 8-bit activations. Linear layers are replaced by BitLinear: latent weights are kept in BF16, quantized on-the-fly each forward pass (absmean per-tensor scaling for weights, absmax per-token for activations), and gradients flow through the quantizer via the straight-through estimator (STE); the optimizer updates the latent FP weights ([HF BitNet docs](https://huggingface.co/docs/transformers/en/quantization/bitnet), [JMLR BitNet paper](http://www.jmlr.org/papers/volume26/24-2050/24-2050.pdf)).

**Smallest scale where quality holds vs fp16.** The original paper ([arXiv 2402.17764](https://arxiv.org/abs/2402.17764)) trained 700M/1.3B/3B/3.9B on 100B RedPajama tokens: at **700M the ternary model is ~0.5 perplexity worse than FP16 LLaMA; at 1.3B the gap shrinks to within ~0.05; at 3B BitNet b1.58 slightly beats FP16** — the crossover is near 3B ([emergentmind summary of the paper's table](https://www.emergentmind.com/topics/bitnet-b1-58), community reproduction at 700M/1.3B/3B confirming the paper's numbers: [1bitLLM/bitnet_b1_58-large (700M)](https://huggingface.co/1bitLLM/bitnet_b1_58-large), [-xl (1.3B)](https://huggingface.co/1bitLLM/bitnet_b1_58-xl), [-3B](https://huggingface.co/1bitLLM/bitnet_b1_58-3B)). Below 700M: **BitNet b1.58 Reloaded** ([arXiv 2407.09527](https://arxiv.org/abs/2407.09527)) tested 100K–48M models and found "the effective capacities of the models with 1.58-bit weights are around half that of the models with 16-bit weights" — i.e., you need ~2× hidden size to match 16-bit on language tasks at tiny scale; it also found small networks need *conservative* LRs (1e-4–1e-3), inverting the large-model "aggressive LR" advice ([HTML](https://arxiv.org/html/2407.09527v1)). The **Spectra suite** ([arXiv 2407.12327](https://arxiv.org/abs/2407.12327)) trained ternary TriLMs 99M–3.9B on 300B tokens alongside FP16 FloatLMs and PTQ QuantLMs: TriLMs win on *bits* (TriLM-3.9B ≈ FloatLM-1.1B validation loss at ~equal bit-size) but at fixed *parameter count* below ~1B, ternary trails FP16; competitiveness emerges at 3B+. **When are 1.58 bits enough?** ([arXiv 2411.05882](https://arxiv.org/abs/2411.05882)) shows ternary training matches or beats 16-bit at small scale for MLPs/GNNs/encoder-decoder models — but those are not decoder-only LMs.

**Training recipe.** Latent BF16 weights + STE; two-stage learning-rate and weight-decay schedule (high LR + decay first, then drop both); subln normalization; the 2B4T official model adds squared-ReLU FFNs ([2B4T tech report, arXiv 2504.12285](https://arxiv.org/abs/2504.12285)). Official training tips + PyTorch BitLinear code: [microsoft/unilm bitnet Training Tips/Code/FAQ PDF](https://github.com/microsoft/unilm/blob/master/bitnet/The-Era-of-1-bit-LLMs__Training_Tips_Code_FAQ.pdf).

**Training overhead/savings.** None of the savings appear at training time on a 4090: matmuls still run in BF16/FP16 against dequantized weights; the fake-quant ops add overhead (no published per-step overhead number for BitNet specifically — UNVERIFIED magnitude, typically cited ~10–30% for fake-quant QAT generally). Savings are inference-only: 2B4T uses 0.4GB non-embedding memory and ~12× less energy per inference than Qwen2.5-1.5B ([tech report](https://arxiv.org/html/2504.12285v1)).

**2025–2026 follow-ups.** (a) **BitNet a4.8** ([arXiv 2411.04965](https://arxiv.org/abs/2411.04965)): 4-bit activations for attention/FFN inputs + sparsified-8-bit intermediates, same training cost as b1.58, comparable quality, enables INT4/FP4 kernels, 55% active params, 3-bit KV cache. (b) **BitNet b1.58 2B4T** (Apr 2025, [arXiv 2504.12285](https://arxiv.org/abs/2504.12285)): first official open 2B/4T-token native 1-bit model, parity with full-precision peers of its size; weights at [microsoft/bitnet-b1.58-2B-4T](https://huggingface.co/microsoft/bitnet-b1.58-2B-4T). (c) **Falcon-Edge** (TII, May 2025): 1B and 3B BitNet models trained from scratch, with an open training/fine-tuning toolkit [tiiuae/onebitllms](https://github.com/tiiuae/onebitllms) and a recipe that emits bf16 + native-BitNet + pre-quantized variants from one run ([Falcon-Edge blog](https://falcon-lm.github.io/blog/falcon-edge/)). This is the strongest evidence that ~1B from-scratch ternary is *practical*, though Falcon-Edge does not claim parity with the best bf16 1B peers on all benchmarks. (d) Scaling-law work below 700M: Reloaded ([2407.09527](https://arxiv.org/abs/2407.09527), capacity ≈ half) and Spectra ([2407.12327](https://arxiv.org/abs/2407.12327)) are the relevant data; no dedicated sub-700M decoder-LM scaling-law paper found beyond these.

**Inference.** [microsoft/BitNet (bitnet.cpp)](https://github.com/microsoft/BitNet): official inference framework, CPU speedups 1.37–6.17×, GPU kernels added 2025-05-20; inference only — it contains no training code.

**Maturity of open training implementations.** Official BitLinear reference code (unilm PDF appendix), [nanotron 1.58-bit support via HF](https://huggingface.co/blog/1_58_llm_extreme_quantization), [tiiuae/onebitllms](https://github.com/tiiuae/onebitllms), 1bitLLM reproductions. Usable but not turnkey single-GPU.

**Verdict: PILOT.** At 0.1–1B params the published evidence is consistently against quality parity (≈0.5 ppl penalty at 700M/100B tokens; ~2× capacity penalty at <50M), and a 4090 gains nothing at training time. Pilot a ternary fork only if 1-bit CPU/edge deployment is a hard product requirement; do not make it the primary pretrain.

---

## 2. Sub-1-bit quantization ("SubQ")

**What it is.** Compressing weights below 1 bit per weight via structured binary + sparsity (prune N of M binarized weights) or codebook/clustered binary residuals.

**From-scratch vs post-hoc — be precise.** Every sub-1-bit method found is **post-training quantization of an existing FP model**: **STBLLM** ([arXiv 2408.01803](https://arxiv.org/abs/2408.01803)) — N:M structured binarization, 0.55 bits/weight, PTQ on LLaMA-1/2/3, OPT, Mistral; **BTC-LLM** ([arXiv 2506.12040](https://arxiv.org/abs/2506.12040)) — learnable transformation + binary codebook at 0.8 bpw, beats STBLLM, PTQ; **NanoQuant** ([arXiv 2602.06694](https://arxiv.org/html/2602.06694v1)) — sub-1-bit PTQ. These all depend on the weight structure of a *trained* FP teacher (saliency/Hessian partitioning, codebooks over trained weights) — there is nothing to prune or cluster at random init. **No from-scratch sub-binary training recipe was found.** The from-scratch floor today is 1 bit: **FBI-LLM** ([arXiv 2407.07093](https://arxiv.org/abs/2407.07093), code [LiqunMa/FBI-LLM](https://github.com/LiqunMa/FBI-LLM)) trains fully binarized 130M/1.3B/7B models from random init via autoregressive distillation from an FP teacher — note even this needs a teacher, and it is 1.0 bit, not sub-1-bit.

**Overhead/savings.** PTQ methods: zero pretrain cost, applied after; quality at 0.55–0.8 bpw is far below the FP model (STBLLM LLaMA-1-7B ppl 31.7 at 0.55 bpw vs ~5.7 FP — usable only as extreme-compression demo) ([STBLLM](https://arxiv.org/abs/2408.01803)).

**Open implementations.** STBLLM/BTC-LLM code releases not verified as public — UNVERIFIED; FBI-LLM code public.

**Verdict: NOT-REAL-YET** (as a from-scratch training recipe). Sub-1-bit exists only as PTQ, with severe quality loss, and at 0.1–1B scale there is no published sub-1-bit result at all. Irrelevant to this pretrain.

---

## 3. QAT for small from-scratch models (int4)

**What it is.** Quantization-aware training: simulate int4 (weights) / int8 (activations) quantization in the forward pass with STE gradients, either during the tail of pretraining or a short fine-tune, so the deployed quantized model loses little quality.

**Strongest small-scale evidence.** Google's **Gemma 3 QAT** applied QAT to models from **1B** up: ~**5,000 steps** of fine-tuning using **probabilities from the non-quantized checkpoint as targets** (distillation), formats = per-channel int4, per-block int4, switched fp8; resulting int4 models preserve near-bf16 quality at ~4× smaller ([Google developers blog](https://developers.googleblog.com/en/gemma-3-quantized-aware-trained-state-of-the-art-ai-to-consumer-gpus/), [gemma-3-1b-it-qat-int4](https://huggingface.co/google/gemma-3-1b-it-qat-int4-unquantized)). **torchao QAT** (int8-dynamic-activation + int4 grouped weights) recovered up to 96% of hellaswag degradation and 68% of wikitext ppl degradation vs PTQ on Llama-3-8B, and was used for the released quantized Llama-3.2 **1B/3B** ([PyTorch QAT blog](https://pytorch.org/blog/quantization-aware-training/), [torchao QAT docs](https://docs.pytorch.org/ao/stable/workflows/qat.html)).

**Overhead.** QAT runs only for a short tail (Gemma: ~5k steps; torchao: fine-tune phase); fake-quant adds per-step cost but torchtune's QAT+LoRA recipe is 1.89× faster than vanilla QAT ([torchtune QAT recipe](https://meta-pytorch.org/torchtune/0.5/recipes/qat_distributed.html)). Total cost is a few percent of pretrain compute.

**Open implementations.** Mature: [pytorch/ao](https://github.com/pytorch/ao) (QAT API + docs), [torchtune QAT recipes](https://github.com/meta-pytorch/torchtune/blob/main/recipes/quantization.md). This is the most production-hardened item in this survey.

**When QAT-int4 beats ternary-from-scratch.** At ≤1B params: Spectra's controlled comparison shows 4-bit QuantLMs beat TriLMs at fixed parameter count below the ~3B crossover ([arXiv 2407.12327](https://arxiv.org/abs/2407.12327)), and BitNet's own scaling data puts ternary parity at ≥1.3–3B ([arXiv 2402.17764](https://arxiv.org/abs/2402.17764)). So for a 0.1–1B model: pretrain in BF16, QAT-int4 the tail → strictly better expected quality than ternary-from-scratch, at ~equal deployed size (int4 vs 1.58-bit differs by ~2.5×; if that memory delta matters, revisit ternary).

**Verdict: ADOPT** (as the deployment path: BF16 pretrain + torchao int4 QAT on the final few % of tokens, optionally with Gemma-style self-distillation targets).

---

## 4. Multi-token prediction (MTP) pretraining

**What it is.** Add auxiliary heads/modules that predict tokens t+2…t+k alongside the next token. DeepSeek-V3's variant is *sequential*: one extra transformer layer per depth that keeps the causal chain, sharing embedding and output head with the trunk ([DeepSeek-V3 tech report, arXiv 2412.19437](https://arxiv.org/abs/2412.19437), [module walkthrough](https://deepwiki.com/deepseek-ai/DeepSeek-V3/4.4-multi-token-prediction-(mtp))). The MTP module can be reused as a self-speculative drafter at inference (DeepSeek-V3: MTP-1 acceptance >80% → ~1.8× decode throughput; [SGLang MTP tutorial](https://rocm.docs.amd.com/projects/ai-developer-hub/en/latest/notebooks/inference/mtp.html)).

**Published evidence at ≤1B — negative for quality.** Meta's MTP paper found gains only emerge with scale: "on smaller models, multi-token prediction results in worse results," with usefulness starting in the 1B–3B range and clear wins at 13B (+12% HumanEval) ([arXiv 2404.19737](https://arxiv.org/abs/2404.19737)). The TOP paper trained **340M/1.8B/7B** head-to-head and found MTP "shows inconsistent improvements, underperforming in standard NLP benchmarks" — their rank-loss alternative (token order prediction, one extra unembedding layer) beat NTP, MTP, and DeepSeek-style MTP at all three sizes ([arXiv 2508.19228](https://arxiv.org/abs/2508.19228)). A pretraining-curriculum paper exists for making MTP easier early in training ([arXiv 2505.22757](https://arxiv.org/pdf/2505.22757)). No published replication showing DeepSeek-style MTP *quality* gains at ≤1B was found.

**Open implementations.** [deepseek-ai/DeepSeek-V3](https://github.com/deepseek-ai/DeepSeek-V3) (reference), **Megatron-Core MTP** (production training implementation, [docs](https://docs.nvidia.com/megatron-core/developer-guide/latest/user-guide/features/multi_token_prediction.html)), inference support in SGLang/vLLM; curated list: [Awesome-Multi-Token-Prediction](https://github.com/Xiaohao-Liu/Awesome-Multi-Token-Prediction). No maintained nanoGPT-scale MTP trainer found.

**Interaction with weight-tied small models.** DeepSeek's MTP shares embedding + output head with the trunk, which composes naturally with a tied-embedding small model; but **no published study of MTP on a weight-tied ≤1B model was found** — UNVERIFIED territory. Note Gemma 4 12B ships "Multi-Token Prediction (MTP) drafters to reduce latency" ([Google blog](https://blog.google/innovation-and-ai/technology/developers-tools/introducing-gemma-4-12b/)) — production precedent for MTP-as-drafter, not for MTP-as-quality-booster at small scale.

**Verdict: SKIP-AT-THIS-SCALE for quality; PILOT as a post-hoc drafter head.** The ≤1B evidence (Meta, TOP) says MTP doesn't buy quality and may cost it. The drafter use-case is real but can be added after pretrain (train an MTP head on the frozen trunk) at low risk. If an auxiliary loss is wanted, TOP ([2508.19228](https://arxiv.org/abs/2508.19228)) has better small-scale evidence than MTP.

---

## 5. Muon optimizer

**What it is.** Momentum SGD whose 2D-parameter updates are approximately orthogonalized via Newton-Schulz iteration before application; non-matrix params (embeddings, norms, head) stay on AdamW ([KellerJordan/Muon](https://github.com/KellerJordan/Muon)).

**Small-scale evidence — strongest of any item here.** The **modded-nanogpt speedrun** is run at exactly your scale (GPT-2 124M to 3.28 FineWeb val loss): Muon is the optimizer behind the record line that cut training from 45 min to <90 s on 8×H100 and from 10B to <0.4B tokens (combined with many other changes) ([KellerJordan/modded-nanogpt](https://github.com/KellerJordan/modded-nanogpt)). **Moonlight** (Moonshot) scaled it: 16B-total/3B-active MoE on 5.7T tokens, with weight decay + per-parameter update-scale fixes; Muon reached matched loss with **~52% of AdamW's training FLOPs** ([arXiv 2502.16982](https://arxiv.org/abs/2502.16982), [MoonshotAI/Moonlight](https://github.com/MoonshotAI/Moonlight)). At 30–200M decoders, an independent study reports Muon hits target loss with 48–52% of AdamW compute and composes well with MLA+MoE ([arXiv 2509.24406](https://arxiv.org/abs/2509.24406)).

**Maturity.** High and rising: `torch.optim.Muon` is in PyTorch core since 2.9 ([docs](https://docs.pytorch.org/docs/stable/generated/torch.optim.Muon.html); single-GPU fine — distributed support still missing as of 2.9 per [torchtitan issue #2494](https://github.com/pytorch/torchtitan/issues/2494)); reference impls: [KellerJordan/Muon](https://github.com/KellerJordan/Muon), Moonlight's distributed version.

**Known conflicts with QAT/fake-quant/ternary STE.** Published negative result: the Bit-by-Bit progressive-QAT paper (LLaMA-2/3 + Mistral, 1B–13B) tested Muon for ultra-low-bit QAT and found it "did not yield consistent gains over AdamW: convergence speed and final perplexity were comparable or slightly worse, and we observed larger short-horizon oscillations near quantization thresholds in some layers," hypothesizing STE rounding noise destroys the curvature signal Muon exploits ([arXiv 2604.07888, Appendix B.5](https://arxiv.org/html/2604.07888)). Related: Muon's orthogonalized updates are unusually sensitive to directional (quantization) error in optimizer state ([MuonQ, arXiv 2605.11396](https://arxiv.org/abs/2605.11396); [Muon state quantization, arXiv 2509.23106](https://arxiv.org/abs/2509.23106)). **No published from-scratch BitNet-ternary + Muon run was found** (see §14).

**Overhead.** Newton-Schulz adds a few % step time at 100M–1B scale (modded-nanogpt uses 5 NS steps; cost negligible vs matmuls — overhead figure UNVERIFIED beyond the speedrun's own wall-clock wins).

**Verdict: ADOPT** (Muon on hidden 2D weights, AdamW on embeddings/head — the modded-nanogpt config). Single caveat: for the QAT tail (§3), switch to AdamW or accept the documented Muon-QAT null/negative interaction.

---

## 6. MLA (multi-head latent attention)

**What it is.** Compress K/V into a low-rank latent vector that is cached instead of full K/V; up-projections are absorbed into Q/output projections at inference. Introduced by DeepSeek-V2/V3 ([arXiv 2412.19437](https://arxiv.org/abs/2412.19437)); 3–9× KV-cache reduction with quality matching or beating MHA in DeepSeek's ablations ([Raschka MLA gallery](https://sebastianraschka.com/llm-architecture-gallery/mla/)).

**Small-scale evidence.** "Latent Multi-Head Attention for Small Language Models" trained **30M-param GPTs**: MLA+RoPE with r=d/2 gave **45% KV-cache reduction at +0.3% validation loss** and ~1.4× inference speedup; plain MLA *without* decoupled RoPE was 3–5 points worse than MHA — the RoPE-decoupling detail is load-bearing ([arXiv 2506.09342](https://arxiv.org/abs/2506.09342)). The Muon study also ran MLA in 30–200M models as part of its MLA+MoE+Muon combination (68% memory reduction, 8–12% ppl improvement vs their baseline) ([arXiv 2509.24406](https://arxiv.org/abs/2509.24406)).

**Does it pay at ≤1B / 4k context?** KV cache for a ~0.5B GQA model at 4k context is tens of MB — not a 24GB bottleneck during training; the payoff is inference batch size / long-context serving, plus a small parameter saving. Quality-neutral-to-positive at small scale *if* implemented with decoupled RoPE; implementation complexity is the real cost.

**Open implementations.** [DeepSeek-V3 repo](https://github.com/deepseek-ai/DeepSeek-V3), educational reference [rasbt/LLMs-from-scratch MLA chapter](https://github.com/rasbt/LLMs-from-scratch/blob/main/ch04/05_mla/README.md), plus FLA/flame ecosystem configs. Maturity: good reference code, no single-GPU turnkey trainer.

**Verdict: PILOT.** Not needed for the 24GB budget at 2–4k context; GQA is simpler and battle-tested. Pilot MLA only if the roadmap includes serving many concurrent sessions or growing context later.

---

## 7. FP8 mixed-precision training on consumer Ada (RTX 4090)

**What it is.** Run GEMMs in FP8 (E4M3/E5M2) with scaling factors, master weights in higher precision. DeepSeek-V3's recipe: fine-grained scaling (1×128 activation tiles, 128×128 weight blocks), E4M3 everywhere, periodic FP32 promotion of accumulators; <0.25% loss penalty vs BF16 at 671B scale ([arXiv 2412.19437](https://arxiv.org/abs/2412.19437), [analysis](https://dataturbo.medium.com/deepseek-technical-analysis-5-fp8-training-ff34768727b8)).

**Does the stack support the 4090?** Mixed and partly contradictory evidence — flagging it explicitly:
- **Transformer Engine** currently advertises "FP8 ... on Hopper, Ada and Blackwell GPUs ... in both training and inference," requiring compute capability 8.9+ ([NVIDIA/TransformerEngine README](https://github.com/NVIDIA/TransformerEngine)); MXFP8/NVFP4 are Blackwell-only. But multiple community/secondary sources report that on Ada, `te.Linear` historically asserted "compute capability 9.x required" or silently fell back to BF16, losing the speedup without warning ([TE issue #15](https://github.com/NVIDIA/TransformerEngine/issues/15), [bestgpusforai 2026 guide](https://www.bestgpusforai.com/blog/best-gpus-for-ai)). Which TE versions actually execute FP8 GEMMs on sm89, and at what efficiency, is UNVERIFIED — must be benchmarked on the actual card before relying on it.
- **torchao float8**: `_scaled_mm` **tensorwise** scaling is enabled on sm89 (4090); **rowwise** scaling kernels are H100-only (CUTLASS) ([pytorch/ao issue #889](https://github.com/pytorch/ao/issues/889), [torchao float8 README](https://github.com/pytorch/ao/blob/main/torchao/float8/README.md)). So the only 4090 path is the *least outlier-robust* recipe (per-tensor), the opposite of DeepSeek's fine-grained approach.
- **Real-world reports**: the best recent public numbers (nanochat + TE: 20–30% speedup from FP8) are from **Blackwell** (RTX 5090/B200), with no 4090 data in the thread ([karpathy/nanochat discussion #382](https://github.com/karpathy/nanochat/discussions/382)). Ada FP8 cuBLASLt throughput has its own history of underperforming relative to spec ([NVIDIA forum: Ada 4090 FP8 cuBLASLt performance](https://forums.developer.nvidia.com/t/ada-geforce-rtx-4090-fp8-cublaslt-performance/250737)). **No published successful end-to-end FP8 pretrain on a 4090 was found.**

**Overhead/savings.** Best case on supported hardware: 1.2–1.5× throughput ([PyTorch float8 rowwise blog](https://pytorch.org/blog/accelerating-training-float8-rowwise-crusoe/)); at 0.1–1B the GEMMs are small, so realizable gains shrink further, while per-tensor scaling raises divergence risk.

**Verdict: SKIP-AT-THIS-SCALE.** BF16 is the right precision for this run: the only verified 4090 path (torchao tensorwise) is the riskiest recipe, no public 4090 training success exists, and the DeepSeek block-scaled recipe has no 4090 implementation ("no published co-use found"). Revisit only if profiling shows the run is GEMM-throughput-bound and a 1-day FP8-vs-BF16 pilot diverges by <0.1% loss.

---

## 8. Trainable sparse attention (DeepSeek NSA, Moonshot MoBA)

**What it is.** Sparse attention trained end-to-end rather than applied post-hoc. **NSA**: each query attends through three gated branches — compressed coarse tokens, top-16 selected blocks of 64 tokens, and a 512-token sliding window ([arXiv 2502.11089](https://arxiv.org/abs/2502.11089)). **MoBA**: context partitioned into blocks; queries route to top-k blocks, MoE-style; deployed for Kimi's long-context serving ([arXiv 2502.13189](https://arxiv.org/abs/2502.13189), [MoonshotAI/MoBA](https://github.com/MoonshotAI/MoBA)).

**Do they pay below 8k?** NSA's reported wins grow with length: ~9× forward / ~6× backward at 64k, ~4× around 8–16k; at short lengths the three-branch gating overhead means it is at best break-even around 2–4k and can be *slower* than dense ([paper](https://arxiv.org/pdf/2502.11089), [analysis](https://blog.tilderesearch.com/blog/sparse-attn)). Architectural arithmetic for a 2–4k workload: NSA's floor per query is 512 (window) + 16×64 (selected) + compressed tokens ≈ 1.5–2k attended tokens — at 2–4k context that *is* nearly full attention, plus branch overhead. MoBA's published evaluations are long-context (up to 1M); nothing below 8k.

**Open implementations.** NSA: [fla-org/native-sparse-attention](https://github.com/fla-org/native-sparse-attention) (Triton, trainable with flame), [lucidrains/native-sparse-attention-pytorch](https://github.com/lucidrains/native-sparse-attention-pytorch), [tilde-research/nsa-impl](https://github.com/tilde-research/nsa-impl), [Relaxed-System-Lab/Flash-Sparse-Attention](https://github.com/Relaxed-System-Lab/Flash-Sparse-Attention). MoBA: official [MoonshotAI/MoBA](https://github.com/MoonshotAI/MoBA). DeepSeek released no official NSA training code.

**Verdict: SKIP-AT-THIS-SCALE.** At 2–4k context FlashAttention-2 dense is faster, simpler, and risk-free. NSA/MoBA are long-context tools.

---

## 9. Linear/hybrid attention (lightning attention, gated DeltaNet, Mamba-2/GLA hybrids)

**What it is.** Replace most softmax-attention layers with linear-time recurrent state (fast-weight) layers, keeping a fraction of full-attention layers. Production exemplars: **MiniMax-01** (lightning attention 7:1 hybrid at 456B; [arXiv 2501.08313](https://arxiv.org/abs/2501.08313) — UNVERIFIED arXiv ID; model repo [MiniMax-AI](https://github.com/MiniMax-AI)) and **Qwen3-Next** (3:1 Gated-DeltaNet:full-attention hybrid, 80B-A3B, with stability fixes — zero-centered RMSNorm, attention output gating; [architecture analysis](https://01.me/en/2025/09/qwen3-next/), [HF blog on Qwen3.5 attention choices](https://huggingface.co/blog/mlabonne/qwen35)).

**Small-scale evidence.** The **Gated DeltaNet** paper (the layer Qwen3-Next adopted) trained **340M and 1.3B** models and beat Mamba2 and DeltaNet on language modeling/retrieval at those sizes; hybrids with sliding-window attention improved further ([arXiv 2412.06464](https://arxiv.org/abs/2412.06464)). Mamba-2/GLA were likewise validated at 130M–2.7B (same paper's baselines). So small-scale viability is real and replicated.

**Training stability.** Workable but with sharp edges: documented numerical-instability issues in the gated-DeltaNet kernels at gate extremes ([fla issue #389](https://github.com/fla-org/flash-linear-attention/issues/389), [#104](https://github.com/fla-org/flash-linear-attention/issues/104)); production hybrids needed dedicated stability interventions (Qwen3-Next's zero-centered RMSNorm + output gating, per [analysis](https://01.me/en/2025/09/qwen3-next/)).

**Open code.** Mature and active: [fla-org/flash-linear-attention](https://github.com/fla-org/flash-linear-attention) (GLA, DeltaNet, Gated DeltaNet, NSA, etc.) + [fla-org/flame](https://deepwiki.com/fla-org/flame/7.3-linear-attention-models-(gla-delta-net)) training framework with 340M reference configs.

**Does it pay at 2–4k context?** Compute-wise, no: dense attention at 4k is a small fraction of FLOPs at 0.1–1B. The payoffs are (a) constant inference state (no KV growth) and (b) the sleep-consolidation substrate in §13 *requires* fast-weight (SSM/DeltaNet) layers. That coupling is the only reason to consider it here.

**Verdict: PILOT** — not for speed, but as the substrate bet: a GDN-hybrid at 340M (fla/flame reference config) is reproducible and is the prerequisite for §13-style consolidation work. If sleep-consolidation is not on the roadmap, SKIP-AT-THIS-SCALE.

---

## 10. Fine-grained MoE + loss-free balancing at ≤1B total params

**What it is.** Many small experts with top-k routing; **auxiliary-loss-free balancing** replaces the load-balance loss with per-expert bias terms adjusted online (DeepSeek-V3's approach) ([arXiv 2408.15664](https://arxiv.org/abs/2408.15664)).

**Small-scale evidence.** Loss-free balancing was validated on **1B and 3B MoE models** (100B/300B tokens) with better perplexity *and* better balance than aux-loss training ([arXiv 2408.15664](https://arxiv.org/abs/2408.15664)) — so the mechanism works at 1B. **OLMoE** (6.9B total/1.3B active, 5T tokens) showed compute-matched MoE reaches dense quality with ~3× fewer training FLOPs ([arXiv 2409.02060](https://arxiv.org/abs/2409.02060)).

**Does sparse beat dense at 20B tokens / 24GB VRAM?** No — the constraint inversion kills it. MoE trades **more parameters (more VRAM)** for **fewer FLOPs per token**. On a single 4090 the scarce resource is VRAM (weights + optimizer states + activations in 24GB), while FLOPs are comparatively abundant for a 0.1–1B model. A ≤1B-*total* MoE has ≤~250M active params — a weaker model than a 1B dense at equal memory. All published MoE wins (OLMoE, DeepSeek, Moonlight) hold total params ≫ active params, i.e., assume memory is cheap. No published study of MoE at ≤1B total on a ~20B-token budget was found that shows a win over dense — and the OLMoE controlled comparison's framing implies the opposite at fixed total params.

**Open implementations.** OLMoE (code+data+logs open, [arXiv 2409.02060](https://arxiv.org/abs/2409.02060)), Megatron-Core, loss-free balancing reference in DeepSeek-V3 repo.

**Verdict: SKIP-AT-THIS-SCALE.** Dense wins when VRAM, not FLOPs, is the binding constraint.

---

## 11. GRPO (critic-free RL) with a programmatic verifier for code

**What it is.** Group Relative Policy Optimization: sample a group of completions per prompt, normalize rewards within the group to get advantages — no value network ([DeepSeekMath, arXiv 2402.03300](https://arxiv.org/abs/2402.03300)). With a programmatic verifier (unit tests / execution) as reward, this is RLVR for code.

**Minimum scale where it shows gains.** Convergent evidence puts the floor at **~1.5B for reasoning-style tasks**: TinyZero documents that **Qwen2.5-0.5B fails to learn** (countdown task) while 1.5B+ learns search/self-verification ([Jiayi-Pan/TinyZero](https://github.com/Jiayi-Pan/TinyZero)); an execution-verified-RL study on Qwen2.5 0.5B/1.5B/3B found **0.5B → zero accuracy across all benchmarks; 1.5B and 3B → substantial gains**, with 3B approaching the 7B base ([arXiv 2604.00442](https://arxiv.org/pdf/2604.00442)). The general mechanism: GRPO needs a non-zero pass rate in the sample group to produce signal — a model that never passes tests gets zero gradient. For narrow, simple verifier domains a sub-1.5B model *can* have non-zero pass rates, but no published positive result below 1.5B was found for code synthesis. A from-scratch 0.5–1B/20B-token model will be far weaker than Qwen2.5-0.5B, so expect the zero-signal regime on general code; a deliberately narrow task distribution (matched to what the base can occasionally solve) is the only viable configuration.

**Open implementations.** Mature: [TRL GRPOTrainer](https://huggingface.co/docs/trl/grpo_trainer), [huggingface/open-r1](https://github.com/huggingface/open-r1) (GRPO + sandboxed code rewards; example artifact: [Qwen2.5-1.5B-Open-R1-Code-GRPO](https://huggingface.co/CM/Qwen2.5-1.5B-Open-R1-Code-GRPO)), [volcengine/verl](https://github.com/volcengine/verl). Recent analysis of what makes code-verifier RLVR work: [Aletheia, arXiv 2601.12186](https://arxiv.org/pdf/2601.12186); note also the finding that off-policy drift is catastrophic for 1.5B models ([2604.00442](https://arxiv.org/pdf/2604.00442)).

**Verdict: PILOT** (post-pretrain). Tooling is mature and 24GB suffices for GRPO on a 0.5–1B policy; but published evidence says expect nothing below ~1.5B unless the verifier task family is narrowed until base pass-rate > 0. Design the pilot around that constraint; kill criterion = pass-rate stays at 0 in the group samples.

---

## 12. Encoder-free unified multimodal at small scale

**Gemma 4 12B "unified" details.** Released June 2026, Apache 2.0. Decoder-only transformer with **no modality encoders**: vision = a "lightweight embedding module consisting of a single matrix multiplication, positional embedding and normalizations" over raw patches; audio = "removed the audio encoder entirely and projected the raw audio signal into the same dimensional space as text tokens" ([Google blog](https://blog.google/innovation-and-ai/technology/developers-tools/introducing-gemma-4-12b/)). Secondary reporting: 48×48 pixel patches projected by one matmul; 16kHz audio sliced into 40ms frames, linearly projected ([MarkTechPost](https://www.marktechpost.com/2026/06/03/google-deepmind-releases-gemma-4-12b-an-encoder-free-multimodal-model-with-native-audio-that-runs-on-a-16-gb-laptop/)). All modalities share one set of weights; also ships MTP drafters; ~16GB RAM laptop deployment; performance near their 26B MoE ([dev guide](https://developers.googleblog.com/gemma-4-12b-the-developer-guide/)).

**Prior art.** **Fuyu-8B** (2023): the architectural ancestor — image patches linearly projected straight into a vanilla decoder ([Adept blog](https://www.adept.ai/blog/fuyu-8b/)). **Chameleon** (7B/34B): early-fusion with *discrete* image tokens in the text vocabulary; needed QK-norm and norm-reordering to stabilize mixed-modal training ([arXiv 2405.09818](https://arxiv.org/abs/2405.09818)). **Emu3** (8B): everything as discrete tokens, pure next-token prediction ([arXiv 2409.18869](https://arxiv.org/abs/2409.18869)).

**Smallest known encoder-free multimodal models.** **Mono-InternVL-1.8B/2B** — monolithic (encoder-free) MLLM beating its modular 2B baseline on average ([arXiv 2410.08202](https://arxiv.org/abs/2410.08202), [Mono-InternVL-1.5, arXiv 2507.12566](https://arxiv.org/html/2507.12566)); EVE/EVEv2 at 7B ([arXiv 2502.06788](https://arxiv.org/abs/2502.06788)); SOLO, BREEN (7B-class). **Nothing published at ≤1B** with competitive results was found — encoder-free multimodal at sub-1B is unproven.

**Tokenizer strategy options.** (a) **Continuous projection** (Fuyu/Gemma 4): no vocab change; a linear layer maps patches/frames to hidden dim; needs only boundary special tokens. (b) **Discrete codebook** (Chameleon/Emu3): VQ tokenizer; vocab grows by the codebook size (thousands of rows in embedding + unembedding).

**Cost to RESERVE multimodal capability in a text-only v0 pretrain.**
- Continuous-projection route: **near zero now.** No vocab or architecture change; the projection layer is added later. The reserve actions are: (1) include a handful of unused special tokens (`<img_start>`, `<img_end>`, `<audio_start>`, …) in the v0 tokenizer — a few embedding rows; (2) adopt **QK-norm** in v0 attention — Chameleon's documented stabilizer for later mixed-modal training ([2405.09818](https://arxiv.org/abs/2405.09818)), harmless for text-only.
- Discrete route: reserve e.g. 8–32k codebook IDs → at d=1024 that is ~8–33M embedding params (×2 if untied) sitting untrained through v0 — real but modest; rows stay near-init until multimodal data arrives.
- What is NOT reserved by either: actual visual competence — Mono-InternVL/EVE show integrating vision into a pretrained LLM still takes substantial dedicated multimodal training.

**Verdict: ADOPT the cheap reservation** (special tokens + QK-norm, continuous-projection plan); the multimodal training itself at ≤1B is **NOT-REAL-YET** (no published encoder-free model below ~1.8B).

---

## 13. Sleep consolidation (arXiv 2605.26099)

**The arXiv ID resolves.** "Do Language Models Need Sleep? Offline Recurrence for Improved Online Inference," Lee, McLeish, Goldstein, Fanti ([arXiv 2605.26099](https://arxiv.org/abs/2605.26099)).

**Mechanism.** The model is (or is converted to) an SSM-attention hybrid whose SSM blocks hold **fast weights = fixed-size state matrices updated by a gated delta/Hebbian outer-product rule** (S_t = α_t·S_{t-1} + β_t·v_t·k_tᵀ) — concretely Gated DeltaNet and Jet layers ([HTML](https://arxiv.org/html/2605.26099v1)). When the context window fills, the model "sleeps": it runs **N offline recurrent forward passes over the accumulated context with no new input tokens**, letting the same delta-rule dynamics consolidate context into the fast-weight matrices; then the KV cache is cleared (hard or sliding-window eviction) and inference resumes on the updated fast weights. There is no separate consolidation algorithm — the whole multi-pass process is trained **end-to-end by backpropagating through sleep**. Wake-time latency is preserved; extra compute moves into the sleep phase.

**Substrate.** Fast weights live in the linear-attention/SSM state matrices (GDN/Jet) — *not* LoRA deltas, not MLP weights. This ties directly to §9: a softmax-only transformer has no substrate for this method.

**Scale and results.** Synthetic: 4-layer GDN-attention hybrid (d=256) and 10-layer Jet-Nemotron (d=512); realistic: pretrained **Ouro 1.4B and Jet-Nemotron 2B** with N ∈ {1,2,4,6}. Gains concentrate on deeper-reasoning instances: GSM-Infinite 6-op 41.9%→61.5% (Ouro, 4 sleep passes); cellular-automaton accuracy ~10%→>30% with 4 loops ([HTML](https://arxiv.org/html/2605.26099v1)).

**Reproducibility at small scale.** Mixed: the synthetic-task models are tiny (4 layers, d=256 — trivially reproducible on a 4090); but training cost was "1–2 H100 GPU-days per run," cost grows ~linearly with N, the authors flag training can be "slow and unstable," and **no code release was found** ([abs](https://arxiv.org/abs/2605.26099)).

**Verdict: PILOT (research track only).** Real paper, real mechanism, plausible at 4090 scale for the synthetic regime — but no code, requires the §9 hybrid substrate, and adds backprop-through-N-passes cost. Not a pretrain component for v0; a candidate v1 experiment if the GDN-hybrid pilot in §9 is taken.

---

## 14. Compatibility matrix

| Pair | Status | Evidence |
|---|---|---|
| **BitNet × MTP** | **No published co-use found.** | Searched combinations of BitNet/ternary with DeepSeek-style MTP; nothing. Mechanically compatible in principle (MTP module is just extra BitLinear-izable layers) — UNVERIFIED. |
| **BitNet × Muon** | **No published from-scratch co-use found.** Nearest evidence is negative-leaning: Muon in ultra-low-bit *QAT* gave no consistent gains over AdamW and showed oscillations near quantization thresholds ([Bit-by-Bit, arXiv 2604.07888, App. B.5](https://arxiv.org/html/2604.07888)); Muon's orthogonalization is documented to amplify directional (quantization-like) noise ([MuonQ, 2605.11396](https://arxiv.org/abs/2605.11396)). STE-ternary gradients are exactly such noise — treat the combo as an open experiment, not a default. |
| **Muon × QAT** | **Published null/negative result:** "Muon did not yield consistent gains over AdamW: convergence speed and final perplexity were comparable or slightly worse, and we observed larger short-horizon oscillations near quantization thresholds" ([2604.07888, App. B.5](https://arxiv.org/html/2604.07888), LLaMA-2/3 + Mistral, 1B–13B). Practical rule: run the QAT tail on AdamW. |
| **FP8 × BitNet** | **No published co-use found.** BitNet training keeps INT8 absmax activations + BF16 latent weights ([HF BitNet docs](https://huggingface.co/docs/transformers/en/quantization/bitnet)); BitNet a4.8 targets INT4/FP4 *inference* kernels ([2411.04965](https://arxiv.org/abs/2411.04965)). No FP8-tensor-core BitNet *training* recipe exists in the literature. |
| (bonus) **Muon × MLA / MoE** | Positive published co-use at 30–200M scale ([2509.24406](https://arxiv.org/abs/2509.24406)). |

---

# Recommended stack — 4090 / 20B tokens / ~0.5–1B from-scratch

**Sizing note (arithmetic, my estimate):** 6·N·D FLOPs → 0.5B×20B ≈ 6e19 FLOPs ≈ ~10–12 days on a 4090 at ~40% MFU in BF16; 1B ≈ ~3 weeks. 20B tokens is Chinchilla-optimal for ~1B and 40 tokens/param for 0.5B — **0.5B is the better-matched target**.

## Primary stack

1. **Architecture:** dense decoder-only ~0.5B; GQA full attention, 2–4k context, FlashAttention-2; RoPE; **QK-norm** (free stability now + Chameleon-documented insurance for later multimodal — §12); squared-ReLU or SwiGLU FFN; tied embeddings. *Biggest risk:* none material — this is the boring, evidence-backed baseline.
2. **Precision:** **BF16 mixed precision** (skip FP8 — §7). *Biggest risk:* leaving ~1.2–1.3× theoretical throughput on the table if Ada FP8 turns out to work; mitigate with a 1-day FP8-tensorwise pilot only if schedule-bound.
3. **Optimizer:** **Muon on hidden 2D weights + AdamW on embeddings/head** (`torch.optim.Muon`, modded-nanogpt config — §5). Expected ~1.5–2× data/compute efficiency vs AdamW per [2502.16982](https://arxiv.org/abs/2502.16982)/[2509.24406](https://arxiv.org/abs/2509.24406). *Biggest risk:* interaction with the QAT tail — switch to AdamW for that phase (§14).
4. **Objective:** plain next-token prediction. No MTP for quality (§4: negative ≤1B evidence). Optionally evaluate **TOP** ([2508.19228](https://arxiv.org/abs/2508.19228)) as a one-variable experiment — it has the small-scale evidence MTP lacks. *Biggest risk of skipping MTP:* losing a cheap drafter — recoverable post-hoc by training an MTP head on the frozen trunk.
5. **Deployment path:** **torchao int4 QAT on the final ~5% of tokens** (Gemma-style self-distillation targets optional) — §3. *Biggest risk:* QAT instability with Muon — run tail on AdamW.
6. **Multimodal reservation:** reserve special boundary tokens in the tokenizer + QK-norm now; plan Fuyu/Gemma-4-style continuous patch projection later; no codebook vocab reserved (§12). *Biggest risk:* if a discrete-token route is later chosen, vocab surgery is needed — accepted.
7. **Post-train:** SFT, then **GRPO pilot** (TRL/open-r1) on a *narrow* programmatic-verifier task family with measured base pass-rate > 0; kill if group pass-rate = 0 (§11). *Biggest risk:* zero-signal regime below 1.5B — that is why it is a pilot with a kill criterion, not a plan dependency.

## Fallbacks / parallel pilots (in priority order)

- **Optimizer fallback:** AdamW end-to-end if Muon shows instability at scale-up (loss spikes that NS-steps/LR retune don't fix).
- **Ternary pilot (only if 1-bit edge deployment is a hard requirement):** 0.3–0.5B BitNet fork using [tiiuae/onebitllms](https://github.com/tiiuae/onebitllms) + the [unilm training-tips recipe](https://github.com/microsoft/unilm/blob/master/bitnet/The-Era-of-1-bit-LLMs__Training_Tips_Code_FAQ.pdf); use AdamW (not Muon — §14); accept the ~0.5-ppl-class quality penalty at this scale (§1); bitnet.cpp for inference.
- **Substrate pilot (only if sleep-consolidation research is on the roadmap):** 340M Gated-DeltaNet hybrid via [fla-org/flame](https://github.com/fla-org/flash-linear-attention), as the prerequisite for §13 experiments.
- **Explicitly rejected at this scale:** FP8 training (§7), MoE (§10), NSA/MoBA (§8), MLA (§6 — optional pilot only), sub-1-bit anything (§2).

---

*All web claims above carry their inline citation; items marked UNVERIFIED were not confirmable from primary sources during this survey (2026-06-09).*
