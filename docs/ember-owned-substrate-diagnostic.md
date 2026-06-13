# The minimum Ember-owned training substrate — depth-track diagnostic

Opened 2026-06-13 ~14:47Z on Jun directive: ember has been too SHALLOW —
optimizing *inside* the inherited PyTorch/autograd/optimizer frame. The Search
was "too deep" (a bottomless pit that forced hard problem-solving); ember needs
to go deeper than it has. **The task is NOT a premature rewrite.** It is a
surgical diagnostic: *find the exact layer where inherited abstractions prevent
the method Ember actually needs.* PyTorch, AdamW, Muon, ordinary autograd =
baselines/components, not the assumed ground. The c04/PyTorch receipts are KEPT
— they become the baseline the owned substrate must beat.

## The inherited stack, bottom → top, with the blocking line

| layer | what it is | ember's relationship |
|---|---|---|
| CUDA kernels (cuBLAS matmul, elementwise) | raw GPU compute | **component** — reuse; everyone calls cuBLAS |
| Tensor abstraction (storage/strides/dtype) | array container | **component** — reuse (PyTorch tensors or tinytorch) |
| **— THE BLOCKING LINE (hypothesis) —** | | |
| Autograd (`grad_fn` graph, `backward()`) | builds a reverse-mode graph, stores activations, global reverse sweep | **BLOCKS** — assumes the update comes from a global reverse sweep |
| Optimizer (Adam/Muon: separable state + update) | external controller, R2-violating | **BLOCKS** — assumes a separable update step after backward |
| Training loop (fwd → loss → backward → step) | the inherited paradigm | **BLOCKS** — wrong loop shape for a fused local update |

**Hypothesis (to be measured, not asserted): the exact blocking layer is
autograd's `grad_fn`/`backward` + the separable optimizer-step.** Everything
below (tensors, kernels) is a reusable component. The specific inherited
*assumption* that blocks ember's candidate method is: **weight updates come from
a global reverse sweep.** A local / fused / predictive update — the R2-compliant
method — violates exactly that assumption, so autograd is the abstraction it
cannot live inside.

## Evidence it's a real method, not a hope (miner #1, The Search substrates)

The Search already *implemented* local update mechanisms that skip autograd
entirely. Every one "avoids full backpropagation, activation caching, and
optimizer state; unit-step or O(1) amortized per sample" (miner #1). The
load-bearing candidates for an LM substrate:

- **Delta-rule forward model** (`step0778.py`/`step0785.py`): `W -= eta ·
  outer(prediction_error, input)`. Local Hebbian/delta, **no backprop chain,
  claimed 10–20× cheaper than transformer backprop.** This is a *predictive*
  update — ember's pretrain regime exactly.
- **Fold memory** (`fluxcore_torch.py`): cosine-winner additive attraction,
  no backward, claimed ~15× faster per step than SGD/Adam.
- **AtomicFold** (`atomic_fold.py`): attention weights ARE the gradient signal;
  1-pass train/inference, no activation graph.
- **Living Seed** (`living-seed/`): computation IS adaptation (no separate
  step) — the literal R2 form.

(Claims are The Search's own, on toy tasks — labeled, not yet ember-validated.)

### Citation lineage — required on every Search→ember import (Jun 2026-06-13)

Per the standing citation policy (`docs/citation-policy-search-to-ember.md`):
code lifted from The Search into ember cites either its direct prior or its
complete predecessors, and MARKS the most unique element. For the import set
above:

- **Delta-rule forward model** (`step0778.py`/`step0785.py`) — DIRECT prior:
  Widrow & Hoff (1960), LMS / delta rule (`W -= eta·outer(error, input)` IS the
  delta rule). Upstream: Hebb (1949), Rosenblatt (1958).
- **Fold memory** (`fluxcore_torch.py`) — competitive learning / SOM (Kohonen
  1982), Hopfield (1982), Oja's rule (1982).
- **AtomicFold** (`atomic_fold.py`) — predictive coding (Rao & Ballard 1999),
  target-prop (Lee 2015), feedback alignment (Lillicrap 2016). **[UNIQUE]**
  attention-weights-as-credit-signal.
- **Living Seed** — RTRL (Williams & Zipser 1989), equilibrium-prop (Scellier &
  Bengio 2017), Forward-Forward (Hinton 2022). **[UNIQUE]** no-separable-step R2
  form.
- **[UNIQUE — MOST]** local-fused-update × **quantization-native low-bit
  weights**: validated by no one. Predecessors = the delta-rule line × quantized
  training (Gupta 2015 stochastic rounding; QAT, Jacob 2018). This coupling is
  the owned substrate's deep open problem — ember earns its verdict, borrows none.

## Why autograd/Adam is the thing being replaced (miner #2, R2)

R2 = "∄ decomposition F = F_c ∘ F_u into independent compute and update."
Adam violates it: the forward pass runs without Adam; it is external two-moment
state applied after a global backward. A compliant update has ΔW *emerge from
the same local operations that drive the forward pass* — no separable
controller, no reverse sweep. That is precisely the autograd-and-above stack.

## Does the local rule transfer — in ember's regime? (miner #5, experiments)

The Search's 1252-experiment record answers the question that decides the bet,
and the split falls exactly on the prediction/action line:
- **Forward-model delta rule (linear, no backprop) TRANSFERS in the prediction
  regime: cold→warm +73% prediction accuracy, 5/7 games** (C28/PB5).
  Navigation / action-selection transfer: **0/7.** ember's pretrain is
  next-token *prediction* — the side that transferred.
- Delta-rule + echo-state (step916) beat published RL baselines 2.5× on its
  learning benchmark, no backprop, O(D²)/step.
- Prediction-error attention (alpha, C25) is a *validated* R3 self-modification —
  encoding adapts to action-consequence prediction, 100/100 on 10 games.

Depth-appropriate caveat — and exactly the first-principles question ember must
OWN rather than inherit: **The Search never validated low precision for the
local update — "stay float32 for prediction error" (CONSTRAINTS).** ember is
quantization-native. The interaction *local-fused-update × low-bit weights* is
unproven by anyone; it is the deep open problem at the center of the owned
substrate, not a detail to bolt on.

## The minimum Ember-owned substrate (hypothesis to test)

Components below the blocking line (tinytorch or PyTorch tensor ops + cuBLAS) +
an **owned forward-with-fused-local-update loop** that replaces `backward()` +
`optimizer.step()`. Nothing below autograd is rewritten. The owned surface is
the loop and the update rule — the smallest possible ownership that escapes the
blocking assumption.

## The diagnostic experiment — finds the exact layer empirically

Take The Search's delta-rule forward-model primitive (implemented, no-backprop,
claimed 10–20× cheaper), instantiate it as an **ember-shaped LM block** (one
transformer-width predictive layer, next-token target), and **walk UP the stack
until something forces autograd.** The first point where the inherited frame
demands a `backward()` to make the method work IS the answer — measured, not
argued. Two outcomes:
- It never forces autograd → the blocking line is confirmed at autograd; the
  owned substrate is the fused-update loop on borrowed tensors. Then the scale
  question: does its next-token loss track backprop's at ~10–50M params?
- It forces autograd somewhere lower → that lower point is the real blocking
  layer; revise the substrate boundary there.

Honest risk: these primitives are toy-scale; LM-scale predictive quality is
unproven. This track is **diagnostic + minimal proof**, not a build commitment
(matches "not premature rewrite"). Kill criterion: if the delta-rule LM block
cannot track backprop next-token loss within a pre-registered band at small
scale, the owned-update path is shelved and round-1 bootstraps borrowed — the
exact-layer finding (autograd line) still stands as the documented boundary.

## Status

Depth track OPEN. All 5 miners in (#1 update-rules, #2 R2/Adam, #3 kills/bans,
#4 families+runtimes, #5 experiments). Two decisive additions:

- **Runtime-axis PROOF (#4):** `fluxcore_torch.py` / `selfref/` / `atomic_fold.py`
  already run real update rules on torch tensors with ZERO autograd graph ("no
  loss, no optimizer, no autograd graph; manual additive update"). The
  torch-tensors-minus-autograd rung is *implemented and GPU-proven*, not
  hypothetical — confirming the blocking line is autograd, not the tensor layer.
  `fluxcore_torch.py` is eli's runtime template.
- **Kills guard (#3):** zero-init local rules lock into winner-take-all (13
  variants dead, `kills/hebbian-wa_step960.md`; root cause = near-zero scores
  never break symmetry). The LM-block diagnostic MUST warm-init (short backprop
  warmup) before switching to the fused update — folded into eli's spec (mail
  15440), else a FALSE fail. NB: every Search failure was ACTION-credit / RL
  exploration, NOT the predictive forward-model — which transferred (5/7). The
  failure class does not touch ember's next-token regime.

NEXT: eli runs the warm-init delta-rule LM-block diagnostic (mail 15439/15440);
its receipt — autograd-boundary + equal-wall-clock parity + step-time delta —
decides whether the owned-update path proceeds.
