# "SubQ" Term Resolution — 2024–2026 ML Literature

Research date: 2026-06-09. Question: in the directive list "QAT, turboquant, 1.58 bit, or SubQ, MTP" — is "SubQ" a specific named technique?

## 1. Every distinct thing named "SubQ" / "Sub-Q" found

### 1a. SubQ — the Subquadratic Inc. LLM (May 2026) — DOMINANT referent
- **What:** "SubQ 1M-Preview", announced **2026-05-05** by Miami startup **Subquadratic Inc.** (Justin Dangel CEO, Alex Whedon CTO, $29M seed). Claims first "fully subquadratic" frontier LLM; core technique = **Subquadratic Sparse Attention (SSA)** — content-dependent sparse token selection, ~O(n·k) complexity, claimed 52× prefill speedup vs FlashAttention at 1M tokens, 12M-token context research result, SWE-Bench Verified 81.8.
- Primary: https://subq.ai/introducing-subq and https://subq.ai/
- Press/analysis: https://www.datacamp.com/blog/subq-ai-explained (confirms May 5 2026 release, SSA, private-beta-only availability, no quantization component); https://venturebeat.com/technology/miami-startup-subquadratic-claims-1-000x-ai-efficiency-gain-with-subq-model-researchers-demand-independent-proof ; https://explainx.ai/blog/subq-ssa-sparse-attention-12m-context-2026 ; https://aiagentsdirectory.com/blog/subq-is-a-sub-quadratic-llm-built-for-12m-token-reasoning ; https://www.codiste.com/subq-first-sub-quadratic-frontier-llm-long-context-ai
- Skepticism: HN thread https://news.ycombinator.com/item?id=48023079 — no public API, benchmarks only to 1M despite 12M claim, astroturf accusations, admitted "chart crime"; VentureBeat headline: "researchers demand independent proof." Claims are **unverified independently** as of June 2026.
- **Not quantization.** It is a sub-quadratic *attention architecture* (SSA). DataCamp explicitly: article does not discuss quantization.

### 1b. GSM8K-AI-SubQ — reasoning dataset (sub-questions)
- **What:** Dataset for distilling LLM problem-decomposition ability; "SubQ" = **sub-questions** (ChatGPT decompositions of GSM8K problems + feedback). Unrelated to efficiency/quantization.
- URL: https://github.com/DT6A/GSM8K-AI-SubQ

### 1c. "subq" as generic community shorthand for "sub-quadratic" (attention/architectures)
- Pre-startup usage exists informally (e.g., HN/blog phrasing "subquadratic attention done well"), and a 2024–2025 theory literature on sub-quadratic alternatives to transformers exists without using "SubQ" as a proper name: https://arxiv.org/abs/2410.04271 (Fundamental Limitations on Subquadratic Alternatives to Transformers), https://arxiv.org/abs/2505.14840 (Subquadratic Algorithms and Hardness for Attention with Any Temperature), https://arxiv.org/html/2510.05364v1 (survey: Rise of Sub-Quadratic Architectures). None of these brand a method "SubQ"; the proper-name usage effectively belongs to Subquadratic Inc. since May 2026.

### 1d. Near-misses that are NOT named "SubQ" (checked and excluded)
- **No quantization method named SubQ exists.** Searches for "SubQ"/"Sub-Q" + quantization/QAT/sub-bit/ternary/4-bit return only differently-named methods: NanoQuant — sub-1-bit LLM PTQ (https://arxiv.org/abs/2602.06694); S²NN sub-bit spiking NNs (https://arxiv.org/pdf/2509.24266); Sparq sub-byte RISC-V inference (https://arxiv.org/pdf/2306.09905); SQS Bayesian sparse-quantized sub-distributions (https://arxiv.org/html/2510.08999); Sherry 1.25-bit ternary (https://arxiv.org/pdf/2601.07892); Attn-QAT 4-bit attention QAT (https://arxiv.org/pdf/2603.00040). None is ever abbreviated "SubQ".
- **No Chinese-lab technique/kernel/model component named SubQ** (DeepSeek, Qwen, Moonshot/Kimi, MiniMax, Zhipu/GLM, ByteDance/Seed, Tencent/Hunyuan, Baichuan, StepFun) — searches return only model-comparison articles, no SubQ-named artifact. Closest RL-adjacent names are S2Q (successive sub-value Q-learning, https://arxiv.org/pdf/2602.17062) and SUBSAMPLE-Q (https://arxiv.org/pdf/2403.00222) — neither is called "SubQ".
- **Medical noise:** "SubQ"/"sub-Q" overwhelmingly means *subcutaneous* (injection route) in non-ML literature. Irrelevant.

## 2. Verdict

**There is one clearly dominant ML referent as of June 2026: SubQ, the Subquadratic Inc. sub-quadratic-attention LLM (SSA), announced 2026-05-05.** It is a named model/architecture, not a quantization technique, and its claims are not independently verified. Outside that, "SubQ" is **not a named technique** in the 2024–2026 literature — no paper, kernel, or lab component carries the name; "no named technique found" holds for the quantization reading specifically.

## 3. Best-fit interpretation for the directive context

The directive list "QAT, turboquant, 1.58 bit, or SubQ, MTP" is an *efficiency-techniques* list, not a pure quantization list — MTP (multi-token prediction) is already architectural/training-side. Given (a) no quantization method named SubQ exists anywhere, and (b) the SubQ/SSA announcement was the loudest efficiency story of May 2026, the best-fit reading is **"SubQ" = sub-quadratic attention (the SSA-style sparse/linear-attention family), most likely prompted by the Subquadratic Inc. SubQ release**. The list-position after "1.58 bit, or" does not rescue a quantization reading: a "sub-1-bit quantization" interpretation has real techniques behind it (e.g., NanoQuant) but none is called SubQ, so that reading is unsupported. Treat the directive item as: adopt a sub-quadratic attention mechanism (SSA-class sparse attention / linear-attention / SSM hybrid) as one of the candidate efficiency components.
