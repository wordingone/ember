# Cosmos 3 — external read (user pointer, 2026-06-10)

*NVIDIA Cosmos 3, launched COMPUTEX 2026-06-01 (post-knowledge-cutoff;
web-verified same day as this note). Sources: NVIDIA newsroom/blog, technical
coverage of the architecture, technical report at research.nvidia.com
(cosmos-lab/cosmos3). Assessed against GOAL.md, formalization-v0 §1/§7, and
the problem-level calibration (2026-06-10).*

## What it is

Open frontier foundation model for physical AI. **Two-tower
mixture-of-transformers:** an autoregressive VLM *reasoner* (causal
self-attention; interprets motion, object interactions, physical context) and
a diffusion *generator* (full attention; physics-aware video + action
denoising), coupled **one-way** (reasoner → generator), sharing a **3D
multimodal RoPE** that aligns video/audio/action tokens temporally.
**Action is a first-class token modality** (forward dynamics, inverse
dynamics, policy generation; fixed per-embodiment action dims — camera,
vehicle, egocentric, single/dual-arm, humanoid). Omnimodal in/out: text,
image, video, stereo audio, JSON action arrays.

Sizes: Nano 16B (8B dense backbone — **built on Qwen3-VL 8B**), Super 64B
(32B, Qwen3-VL 32B), Edge 4B (2B dense) announced-not-released. 20T-token
multimodal training. **OpenMDW-1.1 license** (Linux Foundation): weights +
code + training recipes + 6 synthetic-data datasets (robotics, physics,
spatial reasoning, human motion, driving, warehouses) — train/modify/
redistribute all permitted. Nano targets workstation GPUs; NVFP4/FP8
quantization paths. Known failure modes (their own card): temporal
inconsistency, object morphing, inaccurate 3D structure.

## What it means for ember — five threads, one axiom

**1. The verifier axiom holds against it (the load-bearing point).**
Cosmos is a *learned* world model — it generates what is *likely*. Ember's
formalization axiom (§1): V is never learned, never model-based; ground truth
is supplied by world dynamics. A Cosmos-class model **cannot be ember's
verifier** — it is the strongest possible learned judge, and its own card
lists the physics failures that make learned judges Goodhartable. Nothing in
Cosmos 3 weakens the axiom; its release sharpens why the axiom is a
differentiator: nobody ships a verification-gated experience ledger — they
ship generators.

**2. Three roles it CAN legitimately fill (without violating the axiom):**
- **World/task source** — generated scenarios are admissible as *task
  distribution* (same status as re-arc's generated ARC variants) so long as
  ember's artifacts are verified by hard dynamics (game engine, simulator
  with real physics, program execution), never by Cosmos's imagination.
- **Policy prior / proposal sampler** — in policy worlds (NC1d-class), a
  world model may propose; the grounded verifier decides. Same shape as
  core-proposes-program / sandbox-verifies.
- **Corpus mass** — the 6 OpenMDW datasets + released recipes are legally
  harvestable inputs for NC2-own's owned-mass multimodal pretrain. This is
  the most concrete near-term value.

**3. Architecture datapoint for the NC2-own contract (item 8).** The
contract's unified-multimodal item follows Gemma-4's encoder-free
one-transformer shape. Cosmos 3 is the strongest *contrary* datapoint:
frontier physical-AI chose a **two-tower split by attention regime** (causal
AR for understanding; full-attention diffusion for generation) with one-way
coupling and shared positional geometry — and treats **action as a native
token modality**. Registered as a datapoint, not a pivot: ember's v0 worlds
emit text-form artifacts (programs), where unified-AR remains right; if/when
ember enters action-bearing worlds (ARC-AGI-3 policies are still programs;
true continuous-action worlds are further out), the two-tower + mRoPE
pattern is the precedent to revisit. No contract change now.

**4. The resident-form corroboration.** "Think before it acts" = a reasoner
tower that runs continuously while the expensive generator is recruited on
demand — the closest industrial instance yet of GOAL.md's RESIDENT FORM
(constant thinking, episodic depth; prior precedents Moshi/Helix/GR00T). And
the Edge-4B/Nano-NVFP4 push confirms residency is where the industry is
heading — residency-as-correctness is not a fringe constraint.

**5. The borrowed-core irony.** NVIDIA's frontier physical-AI model is built
on **Qwen3-VL backbones** — even at 20T tokens and frontier scale, the
language core is borrowed. That is ember's "borrowed cores are scaffolding"
stance playing out at the top of the industry, and it locates the actual
moat exactly where ember's goal puts it: not the backbone, but what you
build around and eventually instead of it.

## Disposition

- No change to the accumulation track or the world ladder.
- NC2-own corpus note: OpenMDW SDG datasets + recipes → candidate owned-mass
  inputs (logged in the technique-contract dossier when NC2-own opens).
- NC1d/embodied-future note: Cosmos-as-task-source + grounded-verifier
  pattern pre-registered above; two-tower datapoint on contract item 8.
- Per problem-level calibration: everything Cosmos already does is
  dependency-layer for ember. The contribution layer — receipted ledger,
  three-test gate, invariant-gated self-editing, residency-bounded
  accumulation — is exactly what this release does NOT contain.
