# LLM Program Synthesis on ARC-AGI-1 — State of the Art (research survey, 2026-06-09)

Scope: induction (write-a-Python-program, verify against train pairs) on the original Chollet corpus
(400 public train / 400 public eval / 100 private). Compiled to inform the nc-ladder expert-iteration
loop: Qwen2.5-Coder-7B-Instruct sampling k programs per task, verified by execution on the task's own
train pairs, on a single 4090.

Terminology used below: **ARC-train** = the 400 public training tasks; **ARC-eval** = the 400 public
evaluation tasks (BARC calls this the "validation split"; SOAR calls it "ARC-test"). "Solved" usually
means 2 attempts (Kaggle rules) unless stated.

---

## 1. BARC — "Combining Induction and Transduction for Abstract Reasoning" (Li, Hu, ... Ellis; Cornell/SJTU/Basis/Autodesk, Nov 2024)

Paper: https://arxiv.org/abs/2411.02272 (PDF mirrored at
https://www.cs.cornell.edu/~ellisk/documents/arc_induction_vs_transduction.pdf). ARC Prize 2024
1st-place paper award (https://arcprize.org/blog/arc-prize-2024-winners-technical-report).

**Setup.** Base model for BOTH induction and transduction: **Llama-3.1-8B-Instruct** — chosen because
"preliminary experiments suggested Llama3.1-8B-instruct was better than Mistral-7B-v0.3,
Qwen2-7B-Instruct, and deepseek-coder-6.7b-instruct" (paper, Sec. 2 footnote 1). Induction model is
fine-tuned to emit a Python `transform(input_grid)` over numpy arrays using a hand-written `common.py`
library (`from common import *`, `Color.BLUE` enums etc.) — deliberately NOT a restrictive DSL
("We still allow arbitrary Python code", Sec. 3).

**Seed → synthetic data pipeline.** 100 (later 160) hand-written "seed" Python files, each =
NL description + `transform_grid` (the solver) + `generate_input` (a probabilistic input generator).
LLM remix (self-instruct-style description mutation + RAG code generation, GPT-4 descriptions +
GPT-4o-mini code) →:
- Section-4 datasets: 100k problems from 100 seeds.
- **ARC-Heavy**: 200k problems from 160 seeds (60 new seeds targeting train tasks the v1 models missed).
- **ARC-Potpourri**: 400k problems = ARC-Heavy + all Sec.-4 data + **100k transduction-only examples from
  re-arc (Hodel 2024)**.

**Grid serialization (Appendix B.1).** Grids are rendered as **color WORDS, one token per pixel**,
whitespace-separated cells, newline-delimited rows ("Black Gray Black\nGray Gray Gray\n..."); colors
that tokenized to >1 token were renamed (maroon→brown) so every cell costs exactly 1 token. Induction
assistant turns begin "Let's solve this puzzle using Python code with the common library functions"
and emit `from common import *` + commented numpy code.

**Induction solve rates vs k (all on ARC-eval, 2-try):**
| budget k | data | solve rate |
|---|---|---|
| 2,048 samples | 100k gpt4o-mini data | 11.07% (Table 1) |
| 2,048 samples | 100k GPT-4-descriptions data | 18.78% (Table 1) |
| ~2,000 samples | Fig. 8 scaling curve: near-monotonic rise to ~20% (Sample+Filter), oracle a few points higher; ~9% of train-pair-passing programs are false positives, half of those squashed by majority vote |
| 10,000 samples, majority vote | ARC-Heavy model | 30.50% (Table 2) |
| 20,000 samples, majority vote | ARC-Potpourri model | **38.00%** (Table 2) |
| 384 samples (Kaggle-scale) | Potpourri | 14% on ARC-eval, **4% on the private test set** (Table 3) |

Transduction (Potpourri, TTT+reranking) 43.00%; **ensemble 56.75%** on ARC-eval vs avg human 60.2%
/ best human 97.8% (Table 2, human data LeGris et al. 2024). The scaled-down Kaggle ensemble scored
19% private / 36.5% eval. For context in the same table: Greenblatt 42%, CodeIt 15%, Wind-2020 39%.

**HuggingFace artifacts (org `barc0`, https://huggingface.co/barc0):**
- Models: `barc0/Llama-3.1-ARC-Potpourri-Induction-8B`, `barc0/Llama-3.1-ARC-Heavy-Induction-8B`,
  `barc0/Llama-3.1-ARC-Potpourri-Transduction-8B`, `barc0/Llama-3.1-ARC-Heavy-Transduction-8B`
  (+ TTT variants). **License tag: `llama3.1`** (Llama 3.1 Community License — verified via HF API).
  GGUF quants exist third-party (e.g. `mradermacher/Llama-3.1-ARC-Heavy-Induction-8B-i1-GGUF`).
- Datasets: `barc0/200k_HEAVY_gpt4o-description-gpt4omini-code_generated_problems` (139k rows),
  `barc0/100k-gpt4-description-gpt4omini-code_generated_problems` (103k),
  `barc0/100k-gpt4omini-description-gpt4omini-code_generated_problems` (103k),
  `barc0/induction_heavy_100k_jsonl` (94.9k) + `induction_heavy_suggestfunction_100k_jsonl`
  (the two used to train the Potpourri induction model), `barc0/transduction_formatted_rearc_dataset_100k`.
  **No license tag on the datasets** (verified via HF API — empty); contents are GPT-4o(-mini) outputs.
- Code: https://github.com/xu3kev/BARC — 162 seeds in `seeds/`, `seeds/common.py` library, vLLM
  inference scripts. **No license file on the repo** (GitHub API license=null) — code reuse is legally
  gray; the seeds/common.py are the valuable hand-written parts.

## 2. Ryan Greenblatt — GPT-4o program sampling (June 2024)

Blog: https://blog.redwoodresearch.org/p/getting-50-sota-on-arc-agi-with-gpt

- **k:** ~8,000 samples/task total (~5k initial + ~3k revision completions across the 12 best
  train-pair-scoring candidates). Selection: filter on train pairs, then majority vote → 3 submissions.
- **Solve rates:** 50% on a 100-problem ARC-eval subset; **72% on a held-out 100-problem ARC-train
  subset** (vs 85% human on train). Scaling: ~**+3% absolute per doubling of k**, log-linear from
  k=128 (~14%) → 256 (~17%) → 512 (~21%) → 1024 (~25%) → 2048 (~30%) → 8192 (~37%) before revision;
  revision "fix[es] around 20% of the remaining incorrect solutions" (≈ what 100k raw samples would buy).
  ARC Prize 2024 tech report credits him 42% on ARC-eval / 43% semi-private
  (https://arxiv.org/html/2412.04604v1).
- **Grid representation — what actually worked:** vision did NOT. Direct quote: "GPT-4o's vision is
  terrible on grids" — it "totally fails to extract the colors of cells from an image for images >12x12
  and is quite bad at 8x8." Images were included but the load-bearing representations were TEXTUAL:
  (a) 2D ASCII grid with **spreadsheet-style coordinate labels** (A1, B7...), (b) **per-color location
  lists grouped by connected components**, (c) connected components **normalized** to origin (shape
  comparison), (d) input→output **diff** listings, and during revision (e) ASCII diff of expected vs
  actual output. Two prompt variants (grid-size-changing vs size-preserving). Few-shot prompt ≈ 30k
  tokens of meticulous handwritten step-by-step reasoning — though he notes GPT-4o "seems to not really
  bother doing a good job of following my reasoning examples."

## 3. Test-time training / small fine-tuned models (MindsAI, ARChitects, Akyürek; 2024→2025-26 follow-ups)

ARC Prize 2024 tech report: https://arxiv.org/abs/2412.04604 (also
https://arcprize.org/media/arc-prize-2024-technical-report.pdf).

- **MindsAI (Jack Cole et al.)** — 55.5% private (highest 2024 score; not open-sourced → ineligible).
  Method per the report: "Salesforce T5 series model pretrained on the public evaluation set and
  synthetic data, is further fine-tuned at test time on each private task" — i.e. a sub-1B encoder-decoder
  + test-time fine-tuning + augmentation ensembling. Pioneered TTT for ARC from 2023 (33% → 55.5%).
- **the ARChitects (1st place Kaggle 2024, 53.5% private)** — `Mistral-NeMo-Minitron-8B` base, custom
  tokenizer cut to 64 symbols, **one token per grid cell** (prevents digit chunking), heavy augmentation
  TTT, DFS-based candidate generation, selection by solution stability under augmentations. Paper:
  "The LLM ARChitect: Solving the ARC Challenge Is a Matter of Perspective"; 2025 follow-up "Product of
  Experts with LLMs: Boosting Performance on ARC Is a Matter of Perspective"
  (https://arxiv.org/abs/2505.07859) — scoring candidates under multiple grid "perspectives"
  (augmented serializations) because autoregressive likelihood is order/serialization-sensitive.
- **Akyürek et al., "The Surprising Effectiveness of Test-Time Training"**
  (https://arxiv.org/abs/2411.07279, code https://github.com/ekinakyurek/marc, MIT): fine-tune on
  re-arc + geometric-transform augmentations (notably: "excluding LM-generated data from fine-tuning
  actually outperforms the model trained on all data"), then per-task LoRA TTT with invertible
  augmentations (rotations/flips/transpose/**color permutation**/example permutation/translation).
  Numbers on ARC-eval: **Llama-3.2-1B: 5% fine-tuned → ~29% with TTT**; Llama-3-8B: 36% → 47.1%;
  applied to BARC's transduction model: 53.0%; **ensembled with BARC induction+transduction: 61.875%**
  (≈ avg human). 47.5% semi-private (2nd-place 2024 paper award).
- **Guillermo Barbadillo / OmniARC, 2nd place Kaggle 2024, 40% private**
  (https://ironbar.github.io/arc24/05_Solution_Summary/): **Qwen2.5-0.5B-Instruct** + LoRA(r=128),
  multi-task pretraining (output prediction, input-distribution learning, examples→code), per-task TTT
  (~300 steps), 96 augmented predictions + voting. Notable negatives: BARC's 400k synthetic tasks gave
  "no significant improvement" in his pipeline; his examples→code induction track reached only ~5% on
  ARC-eval despite 3 weeks of DSL work — code-induction at 0.5B scale is hard.
- **2025-26 follow-ups** (ARC Prize 2025: https://arcprize.org/blog/arc-prize-2025-results-analysis,
  tech report https://arxiv.org/abs/2601.10904): competition moved to ARC-AGI-2. 1st **NVARC 24.03%**
  (synthetic-data-driven ensemble of an improved Architects-style TTT model + TRM components);
  2nd ARChitects 16.53% (2D-aware masked-diffusion LLM, recursive self-refinement); 3rd MindsAI 12.64%
  (test-time fine-tuning + augmentation ensembles + tokenizer dropout). Paper awards: **TRM** (7M params,
  ~45% ARC-AGI-1 / ~8% ARC-AGI-2), **SOAR** (below), **CompressARC** (76K params, ~20-34% ARC-AGI-1,
  no pretraining). Takeaway: tiny fine-tuned/recursive models reach 29-55% on ARC-AGI-1 ONLY via
  ARC-specific training + TTT; nothing small does it zero-shot.

## 4. Michael Hodel — arc-dsl + re-arc (the no-cloud curriculum seeds)

- **arc-dsl**: https://github.com/michaelhodel/arc-dsl — **MIT** (GitHub API SPDX verified). Hand-written
  DSL (`dsl.py`, ~160 primitives) + **`solvers.py`: a verified DSL solver program for every one of the
  400 ARC training tasks** (tests in `tests.py`). LLM-legible reformat exists:
  https://github.com/mdda/arc-dsl-llm.
- **re-arc**: https://github.com/michaelhodel/re-arc — **MIT**. Paper: "Addressing the Abstraction and
  Reasoning Corpus via Procedural Example Generation", https://arxiv.org/abs/2404.07353. A
  **procedural example generator per training task** (`generators.py`) + per-task **verifier**
  (`verifiers.py`, = the solver, used to keep only valid generated pairs); ships `re_arc.zip` =
  **1000 verified examples per task × 400 tasks** with two difficulty metrics per example. arc-dsl is
  vendored as a single `dsl.py`. Entry point `generate_dataset` in `main.py`.
- Use in the literature: BARC's ARC-Potpourri folds in 100k re-arc examples
  (`barc0/transduction_formatted_rearc_dataset_100k`); Akyürek's TTT fine-tunes mainly on re-arc;
  Barbadillo trains on re-arc. **Everything needed to build unlimited verified (task, program, pairs)
  triples locally with zero cloud calls is in these two MIT repos** — the DSL solvers are ground-truth
  programs, and re-arc generates fresh pairs those programs provably solve.

## 5. Prompt-format evidence for code-writing with open ≤14B models

What the systems that actually work use:
- **Digit matrices + explicit shape header (SOAR — same base model as our loop).** SOAR's solver
  prompts (https://github.com/flowersteam/SOAR/blob/main/soar/prompt.py, `grid_formatting.py`) default
  to **`numpy` mode — `str(np.array(grid))`** digit matrices — with every grid preceded by
  `## Input i (grid shape: X by Y):` and a color-legend line; fine-tuning prompts use a pipe-separated
  `ascii` mode (`0|7|7`). They imported Greenblatt's full representation zoo
  (spreadsheet/color-location modes are in the file) but **"only numpy is used"** (comment in source).
- **Color words, 1 token/pixel (BARC, 8B).** Whitespace-separated color names, renamed so each is one
  token (Appendix B.1). Works at 8B *after* fine-tuning on 100-400k examples.
- **One token per cell, custom tokenizer (ARChitects, 8B transduction)** — prevents multi-digit
  chunking; their 2025 paper (2505.07859) shows likelihood is brittle to serialization order, fixed by
  scoring under multiple augmented "perspectives."
- **Coordinates + connected components help big prompted models (Greenblatt, GPT-4o)** — spreadsheet
  coords, per-color location lists, normalized components, diffs. Vision useless (quote in §2).
- **Object-based abstraction doubles prompted GPT-4 (Xu et al.,
  https://arxiv.org/abs/2305.18354):** raw text grids → GPT-4 solves 13/50 easiest tasks; with
  object-centric graph (ARGA) representations → 23/50. Failure attributed to inability to maintain
  "object cohesion" across text lines; accuracy is higher for horizontal than vertical object motion
  (sequence-order artifact); GPT-4V recognizes grid size only ~50% of the time from images.

Known failure modes (replicated across sources):
- **Off-by-one / wrong grid dims:** Greenblatt needed separate prompt variants for size-changing vs
  size-preserving tasks; SOAR/ironbar both inject explicit `shape: X by Y` headers — evidence that
  models mis-track dimensions without them; GPT-4V can't even read sizes from images (2305.18354).
- **Color-permutation brittleness:** every strong TTT pipeline (Akyürek, ARChitects, ironbar) includes
  color permutation in its augmentation set precisely because fine-tuned models latch onto absolute
  color identities; BARC renames colors for tokenization; voting is done after un-permuting.
- **Vertical-vs-horizontal asymmetry** from row-major serialization (2305.18354).
- **False positives:** ~9% of programs that pass the train pairs still fail the test pair (BARC Fig. 8);
  majority vote over passing programs squashes about half of that.

## 6. The key planning numbers — open 7-8B zero-shot pass@k

The cleanest published data is SOAR (Pourcel, Colas, Oudeyer; ICML 2025), **the published version of
exactly our experiment**: https://arxiv.org/abs/2507.14172, code https://github.com/flowersteam/SOAR
(MIT). It samples Python programs from **Qwen2.5-Coder-7B/14B/32B-Instruct** (+Qwen2.5-72B,
Mistral-Large-2), executes on train pairs, then alternates evolutionary search (3k samples + 3k
refinements per task) with hindsight fine-tuning on its own traces.

**Table 1 (ARC-eval, 400 tasks, base models before any ARC fine-tune):**
| model | pass@1 | Sample-6k | Sample&Refine-6k | after 4 SOAR iters (6k) |
|---|---|---|---|---|
| Qwen2.5-Coder-7B | **1.00%** | **5.63%** | 14.25% | **36.25%** |
| Qwen2.5-Coder-14B | 1.00% | 12.63% | 19.87% | 42.75% |
| Qwen2.5-Coder-32B | 1.50% | 12.88% | 25.25% | 44.38% |
| Qwen2.5-72B | 1.75% | 18.50% | 25.62% | 44.88% |
| Mistral-Large-2 | 2.50% | 19.75% | 26.25% | 45.50% |

Pooled 5-model majority-vote ensemble: **52.0%** ARC-eval (oracle 57.25%). On **ARC-train** (the split
our loop verifies against — easier), Figure 2 shows base-model 6k-budget search starts ≈12-14% for the
7B and climbs to ≈36-40% after 4 self-improvement iterations; search alone plateaus ~5.2k attempts
("diminishing returns"). Fine-tuning cost: LoRA r=256, 3 epochs, single H100 with Unsloth (RS-LoRA for
7B/14B) — 4090-class feasible with QLoRA; fine-tuning is ~5% of total FLOPs, sampling dominates.

**So: is ~0% at k=8-32 zero-shot the expected baseline?** Calibration from the table: pass@1 = 1% on
ARC-eval (≈4/400). Greenblatt's GPT-4o curve gains ~3%/doubling, but a zero-shot 7B gains far less
(1% → 5.63% over ~12.7 doublings ≈ +0.36%/doubling). Interpolating, k=8-32 on ARC-eval ≈ 1.5-2.5%;
ARC-train runs maybe 2× that (it's the easier split, and the easiest tasks — identity-ish recolors,
tilings — are what a coder model gets). **Expected: 0-3% of train tasks verified at k≤32, i.e. 0-12
tasks out of 400 — "approximately zero" but NOT exactly zero.** If a run verifies literally 0/400 at
k=32 with execution working, suspect harness issues (prompt missing shape headers, wrong
function-signature contract, parsing/timeout bugs) before concluding "model can't."

---

# Implications for an expert-iteration loop on a 4090

**(a) Is zero-shot 7B at k≤32 expected to verify ~0%?** Essentially yes — published anchor: the same
base model (Qwen2.5-Coder-7B-Instruct) verifies **1.00% pass@1 and only 5.63% at k=6,000** on ARC-eval
(SOAR Table 1); on ARC-train at k≤32 expect **low single digits of tasks (0-12/400), concentrated on
trivial recolor/tile/crop tasks**. Two consequences: (1) a near-empty ledger at k=32 is the published
baseline, not a bug — but exactly-zero across all 400 train tasks would be slightly *below* expectation,
worth a harness audit; (2) raising k alone is the worst-value axis: the base-model curve is nearly flat
(+0.36%/doubling), and SOAR found search-alone plateaus by ~5k samples. The signal that moves the curve
is fine-tuning on verified episodes — which is the point of the loop.

**(b) Cheapest local-only path to a non-empty verified-episode ledger** (ranked; all zero-cloud):
1. **Seed the ledger from re-arc + arc-dsl directly (free, deterministic, tonight-sized).**
   `michaelhodel/arc-dsl` `solvers.py` already contains a **verified program for every one of the 400
   train tasks** (MIT), and `re-arc` generates unlimited fresh input-output pairs per task with
   difficulty knobs (MIT). That is a complete (task, program, verified pairs) curriculum with no model
   in the loop — translate DSL solvers to plain-Python episodes (or fine-tune the 7B to emit DSL calls;
   `mdda/arc-dsl-llm` exists for LLM legibility). Caveat: pure-DSL style is a narrower program prior
   than free Python; use as bootstrap, not destination.
2. **Hindsight relabeling of failed samples (SOAR's trick — turns k≈0% into 100% data).** Every
   syntactically-valid sampled program f, run on the task's inputs, defines a NEW synthetic task
   (inputs, f(inputs)) for which f is verified-correct. This is how SOAR bootstraps from a 1%-pass@1
   model without any external data, and it's free given the sampler already runs. Their curation:
   ≤50 episodes/task, mix top-accuracy + diverse-low-accuracy.
3. **Adopt the SOAR checkpoint as the core** — `julien31/Soar-qwen-7b` is *literally our base model
   after 4 expert-iteration rounds* (Apache-2.0, base = Qwen2.5-Coder-7B-Instruct): 36.25% ARC-eval at
   6k budget vs 5.63% for the base. Starting from it (or SFT-ing the base on `julien31/soar_arc_train_5M`,
   MIT, 2.75M rows of deduped verified solutions + hindsight tasks) yields a fat verified ledger at
   k=32-128 instead of k=6000. Use if "open weights + our loop" is the goal; skip if the experiment's
   point is bootstrapping from the raw base.
4. **BARC induction checkpoint as a second opinion / ensemble** — `barc0/Llama-3.1-ARC-Potpourri-Induction-8B`
   (Llama-3.1 Community License; GGUF quants exist) writes `common.py`-style numpy Python; 38% ARC-eval
   at 20k samples. Its 100k induction SFT sets (`barc0/induction_heavy_100k_jsonl` + suggestfunction
   variant) are usable for SFT but carry **no license tag** and are GPT-4o-mini-generated — fine for a
   local experiment, weaker provenance than SOAR/re-arc. Note ironbar found BARC synthetic data gave no
   lift in HIS (transduction, 0.5B) pipeline — signal it's induction-specific.
   For prompt format, copy SOAR exactly (it's tuned for this base model): digit matrix via
   `str(np.array(grid))`, `## Input i (grid shape: X by Y):` headers, color legend, few-shot solved
   examples, `def transform(grid)`-style contract; add color-permutation + transpose augmentation at
   sampling time and majority-vote across the ~9% false-positive rate.

**(c) Exact HF/GitHub IDs + licenses for everything recommended:**
| artifact | ID / URL | license |
|---|---|---|
| re-arc (generators+verifiers, 400 tasks) | github.com/michaelhodel/re-arc | MIT |
| arc-dsl (DSL + 400 verified solvers) | github.com/michaelhodel/arc-dsl | MIT |
| arc-dsl-llm (LLM-legible fork) | github.com/mdda/arc-dsl-llm | MIT (per upstream) |
| SOAR code | github.com/flowersteam/SOAR | MIT |
| SOAR 7B checkpoint | julien31/Soar-qwen-7b | Apache-2.0 |
| SOAR larger checkpoints | julien31/Soar-qwen-14b / -32b / -72b / Soar-mistral-123b | Apache-2.0 (qwen-coder-based; 72b/123b check card) |
| SOAR verified-episode dataset (2.75M rows) | julien31/soar_arc_train_5M | MIT |
| BARC induction model | barc0/Llama-3.1-ARC-Potpourri-Induction-8B | llama3.1 (Community License) |
| BARC induction SFT data | barc0/induction_heavy_100k_jsonl, barc0/induction_heavy_suggestfunction_100k_jsonl | none declared |
| BARC synthetic problems | barc0/200k_HEAVY_gpt4o-description-gpt4omini-code_generated_problems | none declared |
| BARC re-arc transduction data | barc0/transduction_formatted_rearc_dataset_100k | none declared (re-arc itself MIT) |
| BARC seeds/common.py code | github.com/xu3kev/BARC | **no license file** (use ideas, not code, for anything redistributed) |
| TTT code (Akyürek) | github.com/ekinakyurek/marc | MIT |

Bottom line for the running experiment: the zero-ish ledger at k≤32 matches SOAR's published baseline
for this exact model; don't buy more k — buy episodes. The fastest non-empty ledger is re-arc+arc-dsl
(400 verified programs, infinite pairs, MIT, zero model calls) plus SOAR-style hindsight relabeling of
the samples already being thrown away; the fastest strong sampler is the Apache-2.0 Soar-qwen-7b, which
is this experiment's expert-iteration endpoint published a year early.

---
Sources index: BARC paper https://arxiv.org/abs/2411.02272 · BARC HF https://huggingface.co/barc0 ·
BARC code https://github.com/xu3kev/BARC · Greenblatt https://blog.redwoodresearch.org/p/getting-50-sota-on-arc-agi-with-gpt ·
ARC Prize 2024 report https://arxiv.org/abs/2412.04604 · ARC Prize 2025 results
https://arcprize.org/blog/arc-prize-2025-results-analysis · ARC Prize 2025 report https://arxiv.org/abs/2601.10904 ·
TTT https://arxiv.org/abs/2411.07279 + https://github.com/ekinakyurek/marc ·
ARChitects 2025 https://arxiv.org/abs/2505.07859 · OmniARC https://ironbar.github.io/arc24/05_Solution_Summary/ ·
arc-dsl https://github.com/michaelhodel/arc-dsl · re-arc https://github.com/michaelhodel/re-arc +
https://arxiv.org/abs/2404.07353 · SOAR https://arxiv.org/abs/2507.14172 + https://github.com/flowersteam/SOAR +
https://huggingface.co/collections/julien31/soar-arc-6856d27681fce01d9af4c4a3 ·
object-representations https://arxiv.org/abs/2305.18354
