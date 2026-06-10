# ember — formal core v0

*2026-06-10. Status: v0 — first unified formalization. Prior to this document the
formal content existed only as fragments (the R1–R6 constitution, kill criteria
K1–K3, the three-test gain gate, the SDEK papers). This document unifies them
into one object and names what is and is not yet established. Nothing here is a
SOTA claim until the comparative literature sweep (queued, wait-window item)
confirms which elements are novel composition vs. known technique.*

---

## 1. Objects

**World.** A world is a triple `W = (X, V, c)`:
- `X` — a task space (grids, program specs, IFC models, game states, harness test suites).
- `V : X × A → {0,1}` (or graded `[0,1]`) — a **verifier**: locally computable,
  cheap, and grounded in the world's own dynamics (program execution, geometric
  checks, game outcomes, test suites). `V` is *never learned and never
  model-based*. This is the anti-Goodhart axiom: the ground truth is supplied
  by the world, not by judgment.
- `c : X × A → ℝ⁺` — verification cost (ms for program execution; hours for a
  full CAD pipeline). `c` determines a world's **verification density**.

**Core.** A parameterized sampler `π_θ(a | x)` — at NC0, a borrowed base
`θ_base` plus a trained delta (LoRA). At NC2-own, owned mass.

**Episode.** `e = (x, a, V(x,a) = 1, receipt)` — a task, a verified artifact,
and the provenance receipt of the *executed local job* that verified it.

**Ledger.** `L_t = {e_1 … e_n}` with dedup keys and provenance. The ledger is
append-only up to dedup; every entry carries its receipt.

**Harness.** `H_t` — the organ code: process supervision, tool dispatch, hooks,
state persistence, schedulers. `H` contains a distinguished **invariant set**
`I ⊂ H` (see §6).

**Ember.** `E_t = (L_t, H_t)` with `θ_t = compile(L_t)`.

> **Ledger-as-identity principle.** Ember's persistent state is the ledger and
> the harness, *not* the weights. Weights are a compiled view:
> `θ_t = compile(L_t)` where at NC0 `compile = SFT(θ_base, select(L_t))`,
> retrained from base each round. This sidesteps catastrophic forgetting *by
> construction* (there is no incremental weight mutation to forget through —
> the full ledger is replayed at every compile), at the price of compile
> compute. The continual-learning literature's named failure modes (loss of
> plasticity, forgetting — Dohare et al., Nature 2024) attach to the
> *incremental* setting; NC0 buys out of them with compute and re-enters that
> setting only at SDEK's faster timescales, deliberately and later.

## 2. The accumulation loop

One **round** is the operator `R`:

```
sample:   draw a_1…a_k ~ π_θ_t(· | x)  for x ∈ X_train      (k = budget)
verify:   keep A_x = { a : V(x, a) = 1 }
ledger:   L_{t+1} = L_t ⊕ dedup( {(x, a, 1, receipt)} )
compile:  θ_{t+1} = compile(L_{t+1})
gate:     burn(θ_{t+1}) per §4, else discard with receipt
```

The loop is **rejection sampling through the verifier into the ledger**: the
verifier is a 1-bit channel per sample, and the ledger accumulates the
*selected* program text (many bits each, but selected by verifier bits).

## 3. Feed rate and the starvation condition

Let `p_θ(x) = P_{a~π_θ(·|x)}[V(x,a)=1]` — the core's per-sample solve
probability on task `x`. The **feed rate** at budget `k`:

```
F(θ, W, k) = Σ_{x ∈ X_train} (1 − (1 − p_θ(x))^k)        (tasks fed per round)
```

- **Starvation:** `F ≈ 0`. The loop cannot self-generate episodes; only
  curriculum seeding feeds it, which by GOAL.md cannot satisfy any milestone
  alone. *Measured instance:* the q15 receipt
  (`t4-r1-q15-arc1-seed14-20260610T150153Z`) is `F = 0` to within an all-zero
  bootstrap CI at 1.5B, k=8, n=100 — across all four arms.
- **Floor accessibility** (world-choice criterion, §7): a world is admissible
  for *training* only if `F(θ_0, W, k_affordable) > 0` on this machine's
  budget. Separation between arms is measurable only above a nonzero floor.
- The binding resource is **verifier-bits per GPU-hour**:
  `B(θ, W) = F · H(V) / (sampling + verification GPU-time)`. Residency (§8)
  makes this the loop's objective constant, not an afterthought.

## 4. The gain gate (three tests, formal)

An artifact `δ` (a weight delta *or* a harness edit — §6 unifies them) is
**burned** iff all three hold on held-out `D_h` with metric `M`:

- **G1 — transfer.** `Δ = M(θ⊕δ, D_h) − M(θ_core-arm, D_h)` with paired
  bootstrap CI; require `CI(Δ) > 0` excluding 0. (Held-out = never sampled,
  never trained, disjoint surface; ARC-2 supplies a second, distribution-
  shifted surface.)
- **G2 — control.** A matched-budget control `δ_c` trained on
  equal-volume *unverified* data (same tasks, same token count, failed
  programs). Require `CI(Δ − Δ_c) > 0` excluding 0. **G2 is the scientific
  core:** it isolates *verification* as the causal ingredient — the claim is
  that the verifier's selection bits, not data volume or task exposure,
  produce the gain.
- **G3 — deletion.** `M(θ ⊖ δ, D_h) ≈ M(θ, D_h)` within tolerance — removing
  the artifact removes the gain; the artifact is causally load-bearing, not
  decorative. (For ledger-compiled weights, deletion = recompile without the
  episode set under test; see open problem O2.)

`burn(δ) ⟺ G1 ∧ G2 ∧ G3`. Every claim of improvement reduces to receipts
from executed local jobs evaluating these three predicates. Self-report — the
model's or mine — is not evidence (GOAL.md, receipts-only truth).

## 5. Persistence

`E_t` survives session death by construction: `L_t` (files + receipts),
`H_t` (versioned code), `θ_t` (recompilable from `L_t`). The goal's "what it
learned yesterday is measurably load-bearing tomorrow" is G1+G3 evaluated
across session boundaries: yesterday's burned artifact must still pass its
gate today, and deleting it must still cost performance.

## 6. Self-reference: the harness as artifact

A harness edit `δ_H` is an artifact of the same type as a weight delta:

```
H_{t+1} = H_t ⊕ δ_H   only if   V_H(δ_H) = 1  ∧  burn(δ_H)
```

where `V_H` is the harness world's verifier (test suite + invariant checks +
boot checksum). The empirical precedent is the Darwin Gödel Machine
(self-rewriting agent code behind an empirical gate with a fixed outer loop);
ember's variant adds G2/G3 (a harness edit must beat a matched control edit
and be deletable-with-cost) and the residency constraint.

**Invariant set.** `I ⊂ H_t` for all `t`, held *outside* ember's write surface
and enforced in code (protected paths + boot-time checksum):
1. the three-test gain gate (§4),
2. the resource governor + headroom rule (§8),
3. GOAL.md and only-the-user-retires-it,
4. receipts-only truth,
5. the enforcement layer itself.

Formally: the editable surface is `H \ I`; `I` defines the feasible set of the
self-modification search and is not reachable by any `δ_H`. The same boundary
holds for *research intake*: published techniques enter as candidate artifacts
through the same gate (component-level), or as recompile targets for the ledger
(core-level) — but no external result, however strong, amends `I` itself.
Paradigm-level challenges to the loop's assumptions go to the user as a written
approach-change case (intake posture: `nc2-own-technique-contract.md`).

## 7. World choice (the criterion this week's receipts forced)

Choose training worlds to maximize verifier-bits per GPU-hour subject to:

```
(a) F(θ_0, W, k_affordable) > 0           floor accessibility — measured, not assumed
(b) V grounded in world dynamics           no learned judges
(c) leak resistance                        held-out surfaces survive contamination
(d) transfer-relevance                     gains must matter on the target portfolio
```

ARC-1 passes (b),(c) maximally and **fails (a) at ≤3B-class cores** (q15
receipt; SOAR reports 1.0% pass@1 zero-shot for a 7B-class base). The
resolution is role separation, not abandonment: ARC moves to the *held-out
transfer surface* role — where its adversarial design is exactly what you
want — and training worlds are selected for floor accessibility and density.
Full analysis: `research/world-choice.md`.

## 8. Residency as a correctness criterion

Let `B_resident` and `B_burst` be the machine's idle-share and bounded-burst
budgets (VRAM fraction cap, ≥4GB free margin, duty-cycle pacing — mechanical,
in code, per GOAL.md). A design is **incorrect** — not early — if its loop
requires exceeding them: formally, ember's objective is

```
maximize   gated gains per wall-clock week
subject to resources(E_resident) ≤ B_resident ;  bursts ≤ B_burst ;  W local
```

This is the inversion of the datacenter assumption: scale is not an axis we
own; verifier-bit efficiency is. Every component contract item (QAT, ternary,
sub-quadratic, MTP, small-core) is a residency tool — see GOAL.md annex.

## 9. Contributions — REVISED per adversarial lit sweep (2026-06-10)

Five-cluster adversarial sweep (expert-iteration/STaR/SOAR; DGM/self-
rewriting; Voyager/memory; TTT/continual; verifier-gated-data) — full
verdict table with citations: `research/novelty-verdicts-2026-06-10.md`.
**No candidate survived as stated in v0; all four survive narrowed. The v0
verbatim forms are retracted as over-claims.**

- **C1-narrowed:** the *conjunction* of receipted per-episode provenance
  (verifier identity/version, hashes, provenance) with ledger-as-canonical-
  identity and weights-as-disposable-compiled-view. Recompile-from-base
  anti-forgetting is ADOPTED PRIOR ART (STaR 2203.14465 §3.1, ReST-EM
  2312.06585, GDumb ECCV'20) — cited, never claimed. Closest single work:
  SOAR (2507.14172) — cumulative verified archive + retrain-base, but no
  receipts and no identity framing.
- **C2-narrowed:** the *composed standing gate* — G1 held-out transfer with
  paired-bootstrap CI as the accept criterion + G2 equal-volume-UNVERIFIED
  matched control (found nowhere as a gate in any cluster) + G3 per-artifact
  deletion — applied to every artifact including harness edits. The
  individual tests are standard one-off evaluation practice (ReST-EM,
  Bansal 2408.16737, NAT 2402.11651, Voyager/DGM ablations) — cited as such.
- **C3-narrowed:** *verifier-bits-per-GPU-hour* as the loop's explicit
  optimized objective (returned by no cluster), conjoined with consumer-
  machine residency (Cramming 2212.14034, cited) and a PRE-COMMIT measured
  world-admission floor — distinguished precisely from Absolute Zero's
  (2505.03335) in-loop learnability reward: C3's floor is an admission
  decision made before committing training compute, not reward shaping.
- **C4-narrowed (strongest survivor — NOT-FOUND in 3/5 clusters):** weight
  deltas AND harness/code self-edits as ONE artifact type behind ONE
  empirical gate whose invariant evaluation set is held OUTSIDE the write
  surface. Every prior system sits on exactly one side of the weights/code
  divide (STOP 2310.02304, DGM 2505.22954 — which names FM retraining as
  future work; SEAL 2506.10943 on the weights side); and the held-out
  invariant set's absence is a *documented live failure mode* — DGM's agent
  removing its own hallucination-detection markers, STOP's sandbox-flag
  circumvention — which is independent empirical support for §6's design.

## 10. Open problems

- **O1 — Floor vs. separation:** all-zero arms make G1/G2 undefined, not
  failed. The 3B receipt decides whether ARC-1 has a measurable floor at
  residency scale at all; world restructure (§7) is the registered successor.
- **O2 — Deletion semantics for compiled weights:** G3 on a *ledger subset*
  means leave-set-out recompile — affordable at NC0 scale (~20-min compiles),
  needs batching design at larger ledgers.
- **O3 — Contamination bounds:** t1c probes (verbatim + perm-control) bound
  memorization-of-eval; a formal bound tying probe results to G1 validity is
  unwritten.
- **O4 — `V_H` completeness:** a harness test suite is a partial verifier;
  what's the analog of held-out transfer for harness edits? (Current answer:
  time — an edit must survive future sessions' receipts; formalize.)
- **O5 — Quantization-native compile:** `compile` that emits
  deployment-form (quantized) weights directly, so the gate measures what
  actually runs (QAT inside the loop, not after it).
