# Paradigm-flip register (est. 2026-06-12, user challenge)

## The frame error I keep making

"E2E creation of a mind above 7B is years on a single GPU" is a TRUE statement
*inside one paradigm* — dense transformer, global backprop, train-once-freeze,
Chinchilla-optimal compute = 6·N·D. A 4090-class GPU at ~1e14 usable FLOP/s
against a 7B's ~1e23 FLOP IS ~years. But I have been quoting that as if it were
physics. It is not physics; it is the cost of ONE algorithm. GOAL.md's own
binding amendment says so: "If you find yourself confined to the paradigms and
limits of existing neural architectures, you are probably doing it wrong." Each
time I gave the "years" number as a ceiling, I violated that clause. Recorded
as a standing bias to catch.

## The exact problem (stated so it has a deterministic loop)

**Minimize the cost of moving one unit of VERIFIED information into owned mass.**
Total cost = (information that must enter the weights) × (cost per unit moved).
The existing paradigm pays accidental — not essential — costs on the second
factor:

1. **Global credit assignment (backward locking).** No parameter updates until
   the full forward AND backward pass completes; the backward pass is sequential
   and global (Jaderberg 2017, DNI). This is the single largest accidental cost:
   it forces activation storage, serializes the update, and couples every weight
   to every token's global gradient. It is also exactly the user's "global vs
   local separation."
2. **Dense general arithmetic.** Most matmul FLOPs are spent on near-zero values
   in narrow dynamic ranges, computed in general fp units.
3. **No structural reuse.** Each task re-derives from scratch.
4. **Fixed substrate assumption.** CUDA/Triton/the published learning rules are
   treated as ground truth. (User: "note that you are newer than them" — I, the
   Fable-class model, postdate all of them; treating them as immovable is itself
   an in-paradigm assumption. Admissible to author or evolve a replacement —
   GUARDED by the determinism check below, because "newer" ≠ "better at low-level
   arithmetic" by default.)

## What "cannot be a dead end" actually means (honest)

No search can guarantee reaching THE flip. What a path CAN guarantee is that it
**never stalls** (every iteration yields a monotonic, measurable signal even on
failure) and is **guaranteed to terminate in owned knowledge** (a map of where
the cheap method works). That is the non-dead-end property — not false certainty
of a flip. A path qualifies for the loop ONLY if it has a per-iteration metric
that moves on failure. "Train a 7B and see" fails this (one bit of feedback after
weeks). The register below admits only paths that pass it.

## Layer register — flip vs multiplier, and the loop metric for each

| layer | candidate | flip or multiplier | per-iteration metric (the non-stall guarantee) | dead-end risk |
|-------|-----------|--------------------|--------------------------------------------------|---------------|
| credit assignment | local learning rules / decoupled interfaces (solve backward locking) | **FLIP candidate** (largest accidental cost) | per-layer cosine(local-signal, true global gradient); maps where decoupling is free | known competence ceiling at scale (K1 floor) — loop maps the boundary, does not assume victory |
| weights | ternary / 1.58-bit (BitNet) | multiplier | bits/param vs verify-floor accuracy | low — known technique |
| architecture | sub-quadratic (SSM/linear attn) | multiplier | D-term FLOP vs perplexity floor | "a dependency already does this" → instrumentation, not contribution |
| matrix math | forward-only / predictive-coding / equilibrium-prop learning operators | **FLIP candidate** | sample-efficiency vs backprop at matched compute | never matched backprop at scale; competence-floor caveat |
| GPU arithmetic | arithmetic specialized to the empirical value distribution | multiplier→flip if it changes what learning *requires* | microbench: effective FLOP/J vs baseline on real layers | hardware-bound; verify on receipts not theory |
| kernels | founder-authored / evolved CUDA-Triton replacement | amplifier | receipted microbench beats hand-tuned baseline | hype risk — determinism check governs, prose claims void |

The synthesis: the flip most likely lives at the **credit-assignment layer**
(rows 1+4), because that is where the paradigm pays its largest accidental cost
AND a monotonic metric (gradient-alignment) exists. The other layers are
multipliers stacked on whatever learning operator wins.

## Enabling infrastructure the user named (real gaps, not yet built)

- **Sandbox / observation surface.** Ember today = a training run + harness
  scripts, NOT an isolated, observable environment. The user is right: an
  isolated process/container with a defined observation API makes founder
  interaction safe and observation cheap. GAP. → infra entry.
- **Numerical review by founders.** Today founders read JSON receipts + prose.
  Small-resolution loss/metric graphs (sparkline PNGs) are more legible per
  token than float columns AND fit the token-frugal-vision rule
  (deterministic-render → cheap read). GAP. → a render-graph skill, the visual
  analog of the tally.
- **Papers-as-skill.** Seminal NN papers have NOT been systematically read for
  their *discovery process* (how the authors broke the problem), distilled into
  a reusable reasoning skill, and measured for founder-output improvement. We
  have scattered reference memories, not this. GAP — and a strong one: it is
  meta-learning from how the field's flips were actually found. Feeds S7
  (papers as causal-chain data) but at the FOUNDER level, not ember's.

## Loop protocol (the rigor, deterministic)

Each register row is worked as: pick the row with the cheapest informative
experiment → run it governed → record the metric delta in a receipt → the row's
metric either improves (continue) or plateaus (retire with a boundary-map
receipt; it is now owned knowledge, never a silent abandon). The register is
never empty while any FLIP-candidate row has an unrun cheap experiment. No row
is killed by prose; only by a plateau receipt. This is the same shape as the
verdict chain, applied to architecture search instead of checkpoints.

## Open decision for the user (the one fork I cannot resolve)

Is this search a **subgoal of ember** (S8: owned learning-operator — the tally
gates completion on it) or **standing infra research-discipline** (informs all
founders, does NOT block the June-22 surpass milestone)? They differ in what
the tally measures and whether research — which cannot be deadline-bound —
sits on the milestone's critical path. Recommendation: SPLIT — the *search* is
standing infra (non-deadline-bound, never stalls); a *specific chosen flip*
becomes a tracked subgoal the moment its loop metric shows monotonic gain on a
receipt. That keeps June-22 honest while making the flip-search permanent.
