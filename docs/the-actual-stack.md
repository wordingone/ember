# The actual stack

Written because the operator read these docs and could not answer basic questions from them: what
framework, what kernels, what the model actually is. The vocabulary — clean-genesis, verified expert
accretion, birth floor — describes real things, but a reader has to already know what they mean, and
the concrete stack was not written down anywhere in one place.

Every number here is derived from committed bytes and the arithmetic is reproduced rather than
quoted. Sources: `configs/ember-restart-3b.json` (contract v3), `configs/v1-pretrain-config.json`,
the tracked Python import census, and a measured throughput receipt. Where something does not exist,
this says so.

## Framework

**PyTorch, with HuggingFace `transformers` for the model class.** Not JAX, not DeepSpeed, not
Megatron. The import census over every tracked `.py` at master:

| import | occurrences | role |
|---|---|---|
| `torch` | 527 | everything |
| `transformers` — `LlamaConfig`, `LlamaModel`, `LlamaForCausalLM` | 35 | the decoder |
| `tokenizers` (HF, standalone) | 23 | tokenizer, trained in-repo |
| `datasets` | 13 | corpus loading |
| `bitsandbytes` | 8 | 8-bit optimizer |
| `peft` (LoRA) | 2 | reference/finetune paths only, not the birth run |
| `triton` | 1 | one probe; nothing in the training path |

Versions, from a measured receipt rather than a requirements file (there is no
`requirements.txt`/`pyproject.toml` at master — worth fixing separately):
**torch 2.6.0+cu124, CUDA 12.4, bitsandbytes 0.49.2.** Single RTX 4090, 23.99 GiB, under WSL2.

## What the sparse kernel backend is

**There isn't one.** This is the question that prompted the doc and it deserves the blunt answer.

"Sparse" in `ember-sparse-3b-v2` is a **routing and freezing** property, not a kernel property. The
model carries four named experts per layer — vision, audio, reasoning, tool — plus an always-active
shared text FFN. Exactly one expert is active per episode or batch
(`training.expert_activation = exactly_one_declared_expert_per_episode_or_batch`), the other three
are frozen, and which one is active comes from an **explicit local episode declaration** rather than
a learned router (`learned_external_routing: false`). Every kernel that runs is a dense kernel. There
is no block-sparse matmul, no MoE dispatch kernel, no structured-sparsity path, no custom Triton in
the training loop.

The practical consequence, which is the part worth carrying: sparsity here buys **memory and
gradient cost**, not FLOPs-per-active-parameter. It reduces what you have to differentiate and store
optimizer state for. It does not make any individual matmul cheaper.

## The model, with the arithmetic done

From `configs/ember-restart-3b.json`. Hidden 2048, 14 layers, 16 attention heads, vocab 32000, tied
embeddings, RMSNorm pre-attention / pre-FFN / final, per-head RMSNorm on Q and K before RoPE. 1D RoPE
for text and audio, 2D coordinate RoPE for image. Both causal and bidirectional attention modes.

Per layer:

```
shared attention      4H²        = 16,777,216
shared text FFN      12H²        = 50,331,648
four experts       4×12H²        = 201,326,592
QK RMSNorm         2×(H/heads)   = 256
RMSNorm            2H            = 4,096
                                 ------------
                                   268,439,808
```

Whole model: `32000×2048` tied embedding + `14 × 268,439,808` + final RMSNorm + image projection
`(48×48×3)×H` + audio projection `640×H` = **3,839,161,856 unique trainable parameters.** That
reproduces the contract's stated total exactly, and clears its own
`assertion_minimum_unique_trainable_parameters = 3,000,000,000`.

**The number that the "3B" label hides:** three of the four experts are frozen on any given step, so
`3 × 12H² × 14 = 2,113,929,216` parameters take no gradient. **Active parameters per step ≈ 1.73B**,
against 3.84B unique. Both numbers are true and they answer different questions — the assertion is on
unique parameters, and anything about step cost or optimizer state is about the active ones. Quoting
one where the other belongs is the easiest mistake to make here.

## Memory budget, checked against the cap

bf16 weights at 2 bytes; gradients and 8-bit AdamW state at 2 bytes per **active** parameter, per the
contract's own `training.memory` block:

```
weights   3.839B × 2B = 7.68 GB   (all of them resident)
grads     1.725B × 2B = 3.45 GB   (active only)
opt state 1.725B × 2B = 3.45 GB   (active only)
                        -------
                        14.58 GB
+ activation reserve     4 GB
+ runtime reserve        2 GB
                        -------
                        20.58 GB   against training.gpu.memory_cap_gib = 22 (23.62 GB)
```

It fits, with roughly 3 GB of headroom. That headroom is why the expert freezing is load-bearing
rather than decorative: without it, gradients and optimizer state on all 3.84B parameters add about
8.5 GB and the run does not fit on this card at all.

## Optimizer

`bitsandbytes.optim.AdamW8bit`, **device-resident and explicitly non-paged**
(`placement: cuda_non_paged`), block-wise, lr 1e-5, weight decay 0.01, percentile clipping 100.
Gradient checkpointing ON.

Worth flagging for anyone reading older receipts: the measured-throughput anchor
(`receipts/.../fp33-e2-full-tune-ceiling-*.json`) was taken with **paged** `paged_adamw_8bit` on a
borrowed 3B, not with the contract's non-paged configuration. The two are different placements with
different transfer behaviour, and throughput numbers should not be moved between them silently.

## Corpus

From `configs/v1-pretrain-config.json`, four sources, all with committed manifests and sha256s:
permissively-licensed GitHub code (13.0 GB), English Wikipedia (3.0 GB), Gutenberg (1.9 GB), and
Ember's own MIT-clean ARC-DSL slice (0.5 MB). Deduplication is exact sha256 at document level, per
source.

The interesting part is a **removal**: `fineweb_edu`, 7.4 GB and 1.55M documents, dropped as TAINTED
because documents were selected by a classifier trained on Llama-3-70B-Instruct annotations. That is
what "clean-genesis" actually means in practice — not a slogan, a 7.4 GB deletion with a stated
reason. Corpus filtering must be deterministic and free of model-mediated selection, and a
classifier trained on another model's outputs is model-mediated selection even though no weights are
copied.

## The coined terms, decoded

| term | what it concretely means |
|---|---|
| clean-genesis | random init, no parent checkpoint, no borrowed weights, no teacher outputs, no model-derived training data, no external model judges. All six are explicit fields under `lineage` in the contract, all false or null. |
| verified expert accretion | experts are added over time rather than trained jointly from the start, and each addition has to pass an admission check before it counts. The four expert slots exist in the architecture from the beginning; accretion is about when each becomes trainable. |
| sparse | one of four experts active per episode, chosen by explicit declaration, other three frozen. Routing-level, not kernel-level. See above. |
| birth floor | the minimum the first real training run has to satisfy before the model counts as born, rather than as a test run. |
| owned model / owned seat | a model whose identity manifest validates, as opposed to a borrowed third-party model, which can only ever occupy an explicitly-requested reference seat. |
| identity manifest | a committed record binding each consumer of the model — tokenizer, optimizer, checkpoint, serving path, benchmark, publication — to a specific sha256, so no consumer can quietly reinterpret a field. |

## What does not exist yet

Stated plainly, because a doc that only describes what is built reads as a claim that the rest is
done:

- **No dependency manifest.** No `requirements.txt`, no `pyproject.toml`, no lockfile at master. The
  version pins above come from a measured receipt, which means the environment is reproducible by
  archaeology rather than by declaration.
- **No 3B-shape phase profile.** The only phase breakdown in the repo is at 368M. Everything anyone
  says about where 3B step time goes is extrapolation from a model an order of magnitude smaller.
- **No device-memory-bandwidth receipt.** Statements about DRAM bandwidth headroom currently rest on
  the vendor datasheet number, not on a measurement taken on this card.
- **No custom kernels of any kind** in the training path.

## How to check this document

Every number above comes from `configs/ember-restart-3b.json`, `configs/v1-pretrain-config.json`, or
the import census, all at master. The parameter total and the memory budget are arithmetic you can
re-run from the formulas in the contract's `parameter_formula` block — the contract states the
formulas and the total separately, and they agree, which is the check worth repeating whenever the
architecture changes.
