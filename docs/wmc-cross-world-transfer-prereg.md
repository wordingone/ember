# #33 cross-world transfer — pre-registration (FROZEN), the STRONG transfer test

**Status:** frozen 2026-06-16 (the lead, seat) — #33 **ADVANCE-f**. Operationalizes the
strong test that ADVANCE-e named but left open ("the strong test remains whether
the same resolver *parameterization* transfers across the two instances"). Companion
to `world-model-compiler-decision.md` (#33), `v0-multimodal-floor-probe-prereg.md`
(the perceptual instance's grounding read), and the llmwiki `prove-by-use-002` gate
(the symbolic instance's). Frozen before either instance's grounding receipt exists
(anti-goalpost). **It has a time-sensitive output (§7): a launch-instrumentation
requirement that must be specified BEFORE the authorized run, or the test becomes
unrunnable post-hoc.**

## 1. Question

#33's central claim is that ember's worlds are separate because grounding is done
by ONE transferable resolver — `attention(query, {keys})` — not by per-world
taxonomies. ADVANCE-e gave the claim two instances of that form:

- **Perceptual:** `resolve(query=caption-position, keys=image-patch-embeddings) →
  grounded token` (measured by ΔNLL at the launch's checkpoint-1, MR-8).
- **Symbolic:** `resolve(query=problem-statement, keys=problem-index-entries) →
  skill-page pointer` (measured by llmwiki retrieval grounding, prove-by-use-002).

ADVANCE-e's verdict ("both ground ⟹ one mechanism") is the **weak** test — two
instances passing *independently* is consistent with two coincidental
address-space-specific taxonomies. The STRONG question:

> **Does the same resolver PARAMETERIZATION transfer across the two address spaces —
> or is grounding address-space-specific (a different learned mechanism per world)?**

## 2. Why "same parameterization" cannot mean literal weight-sharing

The two address spaces have incompatible key sets (image-patch vectors vs
problem-index entries, different dimensionality/semantics), so the resolver cannot
share *all* weights. Decompose the resolver:

- **Transferable core:** the query-projection `Q` + the attention operation
  (softmax over query·key, value aggregation) — the address-space-AGNOSTIC part.
- **Address-space-specific shim:** the key/value projections `K,V` that map raw
  keys (patches / index entries) into the shared attention space.

"Same parameterization transfers" ⟺ **the core (Q + attention) trained on one
address space gives a sample-efficiency head start when only the thin K,V shim is
retrained for the other space.** No head start ⟹ the mechanism is
address-space-specific (the core learned nothing transferable).

## 3. PRIMARY test — architectural-transfer head start (mechanical)

- **Arm FROM-SCRATCH:** train the full resolver (Q+K+V+attention) on address space B
  from random init; measure **tokens-to-grounding-threshold** T_scratch (grounding
  threshold = a fixed, pre-frozen metric value: ΔNLL ≥ ε_floor for perceptual, or
  retrieval-accuracy ≥ a_floor for symbolic — taken from the respective instance's
  own frozen floor).
- **Arm FROZEN-CORE:** take the resolver core (Q + attention) trained on address
  space A; FREEZE it; retrain ONLY the K,V shim for address space B; measure
  tokens-to-threshold T_transfer.
- Run BOTH transfer directions (perceptual→symbolic AND symbolic→perceptual);
  ≥2 seeds each; equal compute budget per cell.

## 4. BANDS — frozen

Let r = T_transfer / T_scratch (sample-efficiency ratio; <1 = the frozen core helps).

- **TRANSFER (one mechanism):** r ≤ **0.5** in BOTH directions (frozen core ≥2×
  sample-efficiency) → the resolver core is address-space-agnostic → strong evidence
  for #33's one-transferable-mechanism claim. The worlds are separate not because
  grounding differs but because the *key sets* differ — exactly the #33 thesis.
- **ADDRESS-SPACE-SPECIFIC (refuted):** r ≥ **0.9** in either direction (frozen core
  gives no head start) → grounding is a per-world learned mechanism; #33's transfer
  claim is bounded/false. A sharp, receipted negative — worlds are separate because
  the *mechanism* is, not just the keys.
- **INCONCLUSIVE:** 0.5 < r < 0.9, or directions disagree → one bounded extension
  (more seeds, or one intermediate freeze-depth: freeze attention only, retrain Q+K+V)
  then decide mechanically. Asymmetric transfer (one direction passes) is itself a
  finding: a partial/directional mechanism, reported as such.

ε_floor, a_floor, r-bands, seed floor, and equal-compute are frozen here.

## 5. Corroborating invariants (cheaper, run per-instance EARLIER)

Independent of the transfer experiment, two signatures should hold in BOTH spaces
IF it is one mechanism — measurable on each instance alone:

- **∅-pointer behavior (ADVANCE-d: empty-pointer is legal):** inject a query with NO
  valid referent in the key set; a true resolver emits diffuse/low-confidence
  attention (the ∅ pointer), NOT a spurious confident pointer. Same ∅-handling in
  both spaces = corroboration; a confident wrong pointer = an oracle, not a resolver.
- **Attention-selectivity signature:** the entropy-over-keys profile (sharp when a
  clear referent exists, diffuse when not) should have the SAME qualitative shape in
  both spaces. Divergent shapes weaken the one-mechanism reading even if both ground.

These are weak-but-cheap; the §3 head-start is the decisive test.

## 6. VERDICT → ACTION

| Verdict | Action |
|---|---|
| TRANSFER | #33's central claim is supported with a receipt → the resolver core is the compile target; worlds-are-separate is a key-set fact, not a mechanism fact. Feeds the world-model-compiler design (one resolver, per-world shims). |
| ADDRESS-SPACE-SPECIFIC | #33's transfer claim is bounded; record it. The compiler needs per-world resolvers, not one — a different (and cheaper-to-know-now) architecture. Successor = the maintainer's call. |
| INCONCLUSIVE | One bounded extension (seeds / intermediate freeze-depth), then decide. |

## 7. DEPENDENCIES + the time-sensitive launch-instrumentation requirement

This test is **doubly-gated**: it needs the perceptual instance grounded (launch
checkpoint-1 floor-probe PASS) AND the symbolic instance grounded (llmwiki
prove-by-use-002). It fires only after both. BUT one input must be captured NOW, not
post-hoc:

> **LAUNCH-INSTRUMENTATION REQUIREMENT (specify before the authorized run):** the run
> must checkpoint the **resolver core (Q-projection + attention parameters)** as a
> SEPARABLE artifact (distinct from the image-patch K,V projections), and log
> per-checkpoint **attention-entropy-over-keys** statistics. Without a separable core
> checkpoint, the §3 FROZEN-CORE arm is impossible to construct after the fact — the
> transfer test would be permanently unrunnable on the v0 run.

This is the consequence that makes freezing now (not post-launch) necessary. It is a
concrete addition to the launch config / the #13 packet's run-spec: **"emit a
separable resolver-core checkpoint + attention-entropy logs at each checkpoint."**

## 8. Honest scope

A TRANSFER verdict is strong evidence, not proof — two address spaces is the minimum
to distinguish one-mechanism from per-world; more worlds would harden it. ΔNLL and
retrieval-accuracy are grounding proxies, not pointer-selection ground truth (the
ADVANCE-e caveat carries). This test upgrades #33 from the weak coincidence
("both ground") to a measured sample-efficiency transfer — the strongest test
available at v0 scale.

## Ownership (routable action-contract)

- **Spec (frozen): the lead (seat)** — this doc. One immediate seat action: fold the §7
  launch-instrumentation requirement into the #13 packet's run-spec so the
  authorized run emits the separable resolver-core checkpoint (done same-tick).
- **Run the transfer test: the engineer** — after BOTH gates clear; emit the r-ratio receipt;
  verdict mechanical against §4.
- **Routing: `GATED: perceptual-grounding-PASS AND symbolic-grounding-PASS`** — fires
  only when both instances have grounded; frozen seat output until then.

Per user direction.
