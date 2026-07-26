# The actual stack

Written because the operator read these docs and could not answer basic questions from them: what
framework, what kernels, what the model actually is. The vocabulary — clean-genesis, verified expert
accretion, birth floor — describes real things, but a reader has to already know what they mean, and
the concrete stack was not written down anywhere in one place.

Every number here is derived from committed bytes and the arithmetic is reproduced rather than
quoted. Sources: `configs/ember-restart-3b.json` (contract v3), `configs/v1-pretrain-config.json`
(historical-only, see the corpus section), `data/ember-restart-3b/input-identity.json`, the tracked
Python import census, and a measured throughput receipt. Where something does not exist, this says
so.

## Framework

**Plain PyTorch. The birth decoder is hand-written, not a HuggingFace model.**

This distinction is the one a repo-wide grep gets wrong, so scope it to the birth path first. Every
third-party import under `tools/ember-restart-3b/`, the exclusive training namespace named by the
contract:

| import | role |
|---|---|
| `torch`, `torch.nn`, `torch.nn.functional`, `torch.utils.checkpoint` | the model and the loop |
| `tokenizers` (HuggingFace's standalone Rust library) | tokenizer, trained in-repo |
| `bitsandbytes` | 8-bit optimizer |

That is the whole list. **No `transformers`, no `datasets`, no `peft`, no `triton`, no JAX, no
DeepSpeed, no Megatron.**

The model is `tools/ember-restart-3b/model.py::UnifiedDecoder`, a `torch.nn.Module` written here,
along with everything under it: `RMSNorm`, `RawPatchProjector`, `RawAudioProjector`,
`RotaryCoordinates`, `SharedAttention`, `SwiGLUExpert`, `_DecoderLayer`. `launch_packet.py` pins the
`class UnifiedDecoder` marker as part of the launch preflight, so the identity of the decoder is
checked rather than assumed.

`LlamaConfig` / `LlamaModel` / `LlamaForCausalLM` do appear across the repo — every occurrence is
under `scripts/`, in reference-model, benchmarking, serving and throughput-probe paths. Those are
comparison and measurement surfaces. **None of them is the birth decoder**, and a census that counts
imports repo-wide will conclude otherwise. This document said exactly that in its first version and
was wrong.

Versions come from a measured receipt rather than a requirements file, because there is no
`requirements.txt` or `pyproject.toml` at master: **torch 2.6.0+cu124, CUDA 12.4,
bitsandbytes 0.49.2.** Single RTX 4090, 23.99 GiB, under WSL2.

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
contract's own `training.memory` block. The reserves are declared in GiB and the cap is in GiB, so
everything below is in bytes and reported in GiB — mixing decimal GB for tensor bytes with binary
reserves is how the first version of this table got the answer wrong by about a gigabyte.

```
weights   3,839,161,856 × 2 =  7,678,323,712 B   (all of them resident)
grads     1,725,232,640 × 2 =  3,450,465,280 B   (active only)
opt state 1,725,232,640 × 2 =  3,450,465,280 B   (active only)
                              --------------
                              14,579,254,272 B  = 13.578 GiB
+ activation reserve  4 GiB =  4,294,967,296 B
+ runtime reserve     2 GiB =  2,147,483,648 B
                              --------------
                              21,021,705,216 B  = 19.578 GiB
cap  training.gpu.memory_cap_gib = 22 GiB      = 23,622,320,128 B
headroom                         2,600,614,912 B =  2.422 GiB
```

It fits with about 2.4 GiB spare. That margin is why expert freezing is load-bearing rather than
decorative: taking gradients and 8-bit optimizer state on all 3.84B parameters instead of the active
1.73B adds `2 × 2 × 2,113,929,216` = 8,455,716,864 B (7.875 GiB), which puts the run at 27.45 GiB —
past the cap and past the card.

## Optimizer

`bitsandbytes.optim.AdamW8bit`, **device-resident and explicitly non-paged**
(`placement: cuda_non_paged`), block-wise, lr 1e-5, weight decay 0.01, percentile clipping 100.
Gradient checkpointing ON.

Worth flagging for anyone reading older receipts: the measured-throughput anchor
(`receipts/.../fp33-e2-full-tune-ceiling-*.json`) was taken with **paged** `paged_adamw_8bit` on a
borrowed 3B, not with the contract's non-paged configuration. The two are different placements with
different transfer behaviour, and throughput numbers should not be moved between them silently.

## Corpus — the planned assembly and the governed input are different objects

These are two separate artifacts and conflating them overstates what has actually been ingested.
The first version of this section did exactly that.

**The governed executed input, today.** `data/ember-restart-3b/input-identity.json` names artifact
`owned-four-domain-production-rung-v1`: **48,428 bytes, four records**, a deterministically replayed
owned image/audio/reasoning/tool rung. Its own provenance field ends with the words that matter —
"measured rung and **not sufficient-pretraining evidence**". That is the identity a run would bind
to right now, and it is a capability rung rather than a pretraining corpus. Nothing at master claims
otherwise.

**The 17.9 GB assembly is historical/planned, and says so in its own bytes.**
`configs/v1-pretrain-config.json` carries `authority.artifact_class = "historical_only"` and
`authority.execution_authority = "denied"`, under `goal_id: EMBER-00`. It describes four sources
with committed manifests and sha256s — permissively-licensed GitHub code (13.0 GB), English
Wikipedia (3.0 GB), Gutenberg (1.9 GB), and Ember's own MIT-clean ARC-DSL slice (0.5 MB), deduped by
exact document-level sha256 per source. It is corpus **evidence and design**, not the current
executed input, and quoting it as "the corpus" credits an ingestion that has not happened.

The part of it worth carrying forward is a **removal**: `fineweb_edu`, 7.4 GB and 1.55M documents,
dropped as TAINTED because documents were selected by a classifier trained on Llama-3-70B-Instruct
annotations. That is what "clean-genesis" concretely means — not a slogan, a 7.4 GB deletion with a
stated reason. Corpus filtering must be deterministic and free of model-mediated selection, and a
classifier trained on another model's outputs is model-mediated selection even though no weights are
copied. The rule survives the config's historical status; the tonnage does not transfer with it.

So the honest one-line answer to "what is it training on" is: **nothing at pretraining scale yet.**
There is a governed 48 KB rung with a valid identity, and a denied-authority design for 17.9 GB.

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
- **No ingested pretraining corpus.** The governed input identity is a 48 KB four-record rung whose
  own provenance says it is not sufficient-pretraining evidence, and the 17.9 GB assembly is a
  denied-authority historical config. Distance from "designed" to "ingested" is not zero here.

## How to check this document

Every number above comes from `configs/ember-restart-3b.json`, `configs/v1-pretrain-config.json`,
`data/ember-restart-3b/input-identity.json`, or the import census, all at master. Read an artifact's
own `authority` block before quoting its contents as current state — that is the check this document
failed on its first pass. The parameter total and the memory budget are arithmetic you can
re-run from the formulas in the contract's `parameter_formula` block — the contract states the
formulas and the total separately, and they agree, which is the check worth repeating whenever the
architecture changes.
