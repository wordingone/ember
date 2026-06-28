# Growth operator vs fixed body — is param-count identity or compile target?

**Status:** decision-record, authored 2026-06-14 (the lead). Triggered by the maintainer's question
(14:48Z): "If Ember's identity is ledger + harness, and weights are only
compile(L_t), then is a fixed parameter count actually part of Ember's identity —
or just a temporary v0 compile target?" **Position recorded below; the OPEN piece
(the growth trigger) awaits the maintainer's convergence — this doc does NOT authorize a build
or a dispatch.** Mode-2 (thinking-together) artifact: captures the lead's derived
analysis so it survives compaction, not a frozen spec.

## The question (two horns the maintainer posed)

Either v0 **proves** the fixed-body ledger→compile→gate loop, or v0 **accidentally
defines** ember as a fixed-body organism forever.

## Settled position

A fixed param count is a **compile target, not identity** — *but only if we make it
so before v0 launches.* Left alone, v0 promotes fixed-body into identity by
omission, and the second horn is what happens. So it is neither clean horn: it is a
choice gated on one decision taken before launch.

### Why it is a choice, not automatic

`weights = compile(L_t)` is only real if the checkpoint is a **recomputable cache of
the ledger** — R6: weights are deletable precisely because ledger+init recompiles
them; R2: the update signal *is* the computation. If that holds, a param count is
just the shape of one compile output, and growth is a new ledger entry kind
`grow(...)` that `compile` replays into a larger shape. **Identity = ledger +
harness (the fixed rules, incl. the growth *rule*); the body is downstream of both.**

The danger is not a fixed body in v0 — it is **where the fixed-shape assumption is
allowed to live:**
- **In the v0 compile target only** (this run emits a ~0.5B body) → ember is not
  fixed-body; v0 just compiled one body. Clean.
- **Leaked into harness invariants** — ledger schema, checkpoint/resume format,
  optimizer-state map, and the R4 "tested-against-prior-state" comparison all
  silently assuming one tensor shape → fixed-shape is welded into the irreducible
  interpreter. Growth then requires modifying the interpreter from inside it: banned
  *in principle*, not just in v0. This is the "forever" horn, and it happens
  silently if unaddressed.

## The pattern — multimodal-locks, one layer up

The v0 multimodal LOCKS taught: a capability you cannot retrofit must be
wired-but-dormant from step 0. Shape-agnostic growth is that class, at the
**harness/ledger layer** instead of the forward pass. Therefore:

- **Formalize the operator's INTERFACE now** (unretrofittable): ledger admits a
  `grow` entry; `compile` can emit a variable shape; checkpoint stays
  replayable-from-ledger; R4 comparison is defined across a shape change.
- **Ban the operator from FIRING in v0**: zero `grow` entries in v0's ledger, fixed
  compile target, one variable. Banning growth from v0 is correct *regardless* of
  this question — it would confound the "does the loop work at all" experiment.

## Constitutional constraints the formalization must carry

- **R4 — function-preserving at the instant of firing** (net2net / zero-init the new
  params) so "tested against prior state" stays well-defined across the shape
  change. Mechanics: known/solved.
- **R6 — a dormant rule is not a deletable component.** A present-but-unused `grow`
  rule (no substrate yet) ≠ a component that can be switched off. Keep the
  distinction explicit or the formalization reads as an R6 violation.
- **R2 — the TRIGGER must be intrinsic to the ledger's own dynamics**, not an
  external "val-loss plateaued → grow" scheduler (that smuggles a reward back in).
  **UNSOLVED.** This is the real problem hiding under the maintainer's question.

## Decision

Formalize the growth operator's **TYPE** now (harness lock); do **NOT** formalize its
**TRIGGER** (unsolved under R2 — formalizing it now would bake a constitutionally
dirty operator into the harness, worse than leaving it open); keep v0's ledger empty
of grow-entries.

## Readiness relevance (CANDIDATE 4th precondition — pending the maintainer convergence)

Before v0 launches, the harness must not have calcified fixed-shape into its
invariants: the checkpoint must be **replayable-from-ledger** and the ledger
schema / optimizer-state map must not hard-assume one tensor shape. If v0 launches
with a non-replayable checkpoint + fixed-shape-assuming ledger, it forecloses growth
permanently — i.e. "ember is ready" would be subtly false against ember's own
identity claim. Recorded as a CANDIDATE precondition, not yet locked: the maintainer may
converge on "fixed body is genuinely fine, formalize nothing," which retires this.

## Growth-gain criterion + git-diff comparison (the maintainer direction, 2026-06-14)

the maintainer set the gain criterion: a growth (added neurons) is justified ONLY if the grown
model shows **receipt-backed held-out improvement over a matched smaller baseline**,
and the gain is **deletion-dependent** (ablating the grown neurons removes the gain)
**and persistent** (holds over continued training, not a transient spike). Maps to
R4 (tested vs prior state) + R6-inverted (the gain must DEPEND on the grown
component — it is load-bearing, not deletable-without-loss).

Resource constraint (the maintainer): measure this WITHOUT running the grown and baseline
models as separate trainings. Vehicle: a **git-like system over the ledger** —
commits = ledger states (compile(L_t)); a growth = a branching commit; the **diff**
= the grown parameters. Mechanics:
- **Function-preserving init** (net2net/zero-init, already required by R4) makes the
  diff START at zero — at the growth commit the grown branch ≡ parent, exactly like
  a git branch identical to its parent. This is what makes the diff well-defined and
  the comparison fair.
- **Deletion-dependence = ablate the diff in-place** (mask the grown neurons, one
  forward pass, no retraining) → held-out gain must vanish. Resource win: one trained
  model, evaluated with/without the diff masked, not two trainings.
- The established mechanism for "a smaller sub-model is itself valid inside the larger
  one" is **matryoshka / slimmable / nested-submodel training**. Growth-diff = the
  outer ring; baseline = the inner ring; both from ~1× compute + marginal diff
  overhead, not 2×.
- **Honest baseline:** the base-alone output must be a real training objective (not
  merely an ablation of a co-adapted base), else ablating the diff yields a
  co-adaptation-crippled model that OVERSTATES the gain. With base-alone in the
  objective, ablation degrades to a genuine matched baseline and deletion-dependence
  is honest.

**Consequence (constraint → virtue):** constraining the base to stay standalone-valid
caps co-adaptation, so the in-place measured gain LOWER-BOUNDS the free-growth gain.
For a GATE that is the correct bias — grow only if even the conservative estimate
clears the bar; never grow on an inflated number.

**De-risks the open R2 trigger:** because the diff is ablatable, growth is
REVERSIBLE — grow, measure in-place, revert if the gain doesn't clear the bar. A
perfect intrinsic trigger matters less when a wrong growth is cheap to undo: the
trigger can be liberal, the GATE stays strict.

DECIDED (the lead call, 2026-06-14 — not escalated): the in-place git-diff/ablation is
the **continuous gate** (conservative; lower-bounds the gain, so it cannot authorize
growth on an inflated number), backed by **rare true-separate-baseline calibration
runs** that measure how much the in-place gate understates. Revision criterion: if
calibration shows understatement within noise, drop it and the in-place gate becomes
the sole arbiter; if understatement is large or variable, raise calibration
frequency. (the maintainer overrides if wrong; this is a design call inside the goal, his to
redirect but mine to make.)

## OPEN — awaiting the maintainer (do not pre-empt)

The intrinsic growth trigger under R2: what ledger-derived signal, with no outside
scorer, is allowed to license a `grow` — something the ledger says *about itself*
that means "this body is too small to keep compiling cleanly"? Until this is named,
the trigger stays unformalized and the implied harness-audit (is the v0 checkpoint
replayable-from-ledger; is any fixed-shape assumption already calcified — an the engineer
eng item) is **scoped but NOT dispatched.**

Per user direction.
