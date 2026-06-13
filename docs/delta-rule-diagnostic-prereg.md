# Delta-rule diagnostic — pre-registration (FROZEN before any receipt)

Frozen 2026-06-13, BEFORE the diagnostic produces a number (anti-goalpost;
freeze-target-before-iterating). eli runs it (mail 15439–15442). Ember derives
its OWN verdict — no Search win/fail imported
([[feedback_search_vs_ember_primitives_not_verdicts]]).

## Question
Is autograd `backward()` + the separable optimizer-step the exact layer that
blocks ember's candidate local-update method — AND can a local fused-update LM
block track backprop's next-token loss at EQUAL 4090 wall-clock?

## Arms (both run; ember's own, not the Search's)
- **WARM**: short backprop warmup → switch to delta-rule fused update (guards the
  kills-catalog zero-init winner-take-all lock).
- **COLD**: delta-rule from scratch. (The Search's cold failure = hypothesis to
  test in ember's regime, not a law.)

## Measured exact-layer criterion
Walk the LM block up the stack; the FIRST construct that forces a `backward()`
to make the method work = the measured blocking layer. Predicted: the autograd
line. A lower forced-autograd point revises the substrate boundary downward.

## Pre-registered parity band (frozen)
~10–50M params, equal 4090 wall-clock budget, next-token loss:
- **PASS**: delta-rule loss within 10% relative of backprop, OR lower.
- **FAIL**: >10% worse.
- **INCONCLUSIVE**: within noise (noise = seed spread, ≥2 seeds).

## Verdict map (frozen → action)
- **PASS (either arm)** → owned-update path PROCEEDS; autograd confirmed as the
  owned-substrate boundary; next = scale probe.
- **FAIL (both arms)** → owned-update SHELVED for round-1; round-1 bootstraps
  borrowed; the exact-layer finding (autograd) still stands as documented.
- **WARM PASS / COLD FAIL** → owned path proceeds WITH warm-init as a required
  precondition (kills-guard confirmed).

## Equal-wall-clock note
Parity is at EQUAL wall-clock, NOT equal steps — the local rule runs more steps
in the same time (no ~500ms backward). Loss-at-equal-time is the honest test;
loss-at-equal-steps would hide the entire throughput thesis.

## Citation lineage (required, per policy)
`docs/citation-policy-search-to-ember.md`: header = source step0778/step0785;
direct prior Widrow-Hoff (1960); [UNIQUE] warm-init delta-rule × next-token LM,
and local-update × low-bit weights (validated by no one).
