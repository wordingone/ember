# Citation policy — Search → ember imports

Standing requirement, Jun 2026-06-13 15:09–15:10Z (verbatim, with the 15:10Z
scope correction): *"every script and code **from search** that makes it into
ember problem space must cite either directly relevant literature, or, if the
experimental algorithm doesn't have a direct prior, its complete predecessors
must be cited. (mark the ones that are the most unique)."*

## Why it is scoped to Search→ember (not all ember code)

It rides on the primitives-not-verdicts distinction
([[feedback_search_vs_ember_primitives_not_verdicts]]). The Search and ember are
different projects/purposes; what crosses the boundary is a **primitive** (a
script, an algorithm, a piece of math/formalization), never a verdict. The
moment a Search primitive enters ember's problem space it stops being "ours by
inheritance" and must stand on its own published lineage — so ember can re-derive
its verdict against the actual literature, not against The Search's toy-task
outcome. Code authored natively in ember from first principles is out of scope
here (it cites whatever it builds on under normal practice); this policy is the
hard gate on the *import* path.

## The requirement (mechanical, per imported unit)

Every Search-origin file or function that lands in `nc-ladder/` carries a
citation header that does ALL of:

1. **Names the Search source** it was lifted from (e.g. `the-search/.../step0778.py`)
   — provenance, so the primitive is traceable, not laundered.
2. **Cites the direct prior literature** if one exists — the published method the
   algorithm IS (e.g. the delta rule = Widrow-Hoff LMS 1960). One citation that
   the algorithm directly instantiates discharges the requirement.
3. **If there is NO direct prior** (an experimental algorithm with no single
   published parent): cites its **complete predecessors** — the full set of lines
   it descends from — not a token reference.
4. **MARKS the most unique element(s)** — the part with no clean prior anywhere,
   the genuinely novel coupling. The mark (`[UNIQUE]`) is the flag that says
   "this is the part ember is actually betting on; it has no literature backstop;
   its verdict must be earned by ember's own receipt."

A primitive that cannot name either a direct prior or a complete predecessor set
does not enter the ember problem space until that lineage is reconstructed.

## Predecessor map for the local-update family (the current import set)

These are the Search primitives the depth-track diagnostic imports
([[ember-owned-substrate-diagnostic]]). Lineage reconstructed here once so the
code headers can reference it.

| Search primitive | direct prior? | lineage (cite complete predecessors when no direct prior) |
|---|---|---|
| **Delta-rule forward model** `step0778.py`/`step0785.py` — `W -= eta·outer(pred_error, input)` | **YES** — Widrow & Hoff, *Adaptive switching circuits* (1960): LMS / delta rule. The error-modulated outer-product update IS the delta rule. | upstream: Hebb (1949) correlational outer product; Rosenblatt (1958) perceptron error-correction. |
| **Fold memory** `fluxcore_torch.py` — cosine-winner additive attraction | partial | competitive learning / SOM (Kohonen 1982); Hopfield associative memory (1982); **Oja's rule (1982)** normalized Hebbian — directly relevant to the winner-take-all collapse the kills-catalog flags. |
| **AtomicFold** `atomic_fold.py` — attention weights ARE the gradient signal | NO | predictive coding (Rao & Ballard 1999); target propagation (Lee et al. 2015); feedback alignment (Lillicrap et al. 2016) / direct FA (Nøkland 2016). **[UNIQUE]** the attention-weights-as-credit-signal identity has no clean direct prior. |
| **Living Seed** `living-seed/` — computation IS adaptation (no separate update step) | NO | RTRL online forward-mode credit (Williams & Zipser 1989); equilibrium propagation (Scellier & Bengio 2017); Forward-Forward (Hinton 2022). **[UNIQUE]** the literal no-separable-step R2 form. |
| **Echo-state + delta** `step916` | **YES** — reservoir computing / echo-state networks (Jaeger 2001); read-out = delta rule (Widrow-Hoff 1960). | — |

## The element with NO prior anywhere — the one to MARK hardest

**[UNIQUE — MOST]** **local-fused-update × quantization-native low-bit weights.**
The Search ran every local rule in float32 ("stay float32 for prediction error",
CONSTRAINTS); ember's weights live on a low-bit grid. A local/predictive update
applied *directly on quantized weights* — no fp32 master, error-signal on the
grid — is validated by no one, in neither lineage. Complete predecessors to cite
when this code is written: the delta-rule line above (the update) **×** quantized
training (Gupta et al. 2015, *Deep Learning with Limited Numerical Precision* —
stochastic rounding; QAT, Jacob et al. 2018). The coupling is the open problem at
the center of the owned substrate — it is marked because ember's verdict on it
cannot be borrowed from either parent field.
