# World choice — is ARC the right world for ember?

*2026-06-10. Triggered by the user's direct challenge (paraphrased): ARC tests a
very specific kind of intelligence; it was designed to be adversarial to modern
neural architectures; a model that dominates agentic benchmarks but fails
ARC-AGI is still near-superintelligent — so ARC failure is not proof of
non-intelligence, and ARC success is not proof of generalization. Think hard
about whether ARC is the right call.*

*Companion formalism: `docs/formalization-v0.md` §3, §7.*

---

## 1. What ember needs from a world (first principles)

From the goal text, a training world must provide:

1. **Verification density** — cheap, local, deterministic ground truth supplied
   by the world's own dynamics. The loop's binding resource is
   verifier-bits per GPU-hour.
2. **Floor accessibility** — the core must already solve *something* (`F > 0`,
   formalization §3). Separation between arms is only measurable above a
   nonzero floor; a world where the core verifies 0% generates no
   self-experience and the loop starves.
3. **Leak resistance** — held-out surfaces that survive contamination, so G1
   (transfer) means something.
4. **Portfolio coupling** — gains should bear on the problems this portfolio
   actually failed to solve, or the loop is a treadmill.

## 2. What ARC actually is

Chollet designed the ARC series as the *inverse* of benchmark hacking: tasks
trivial for humans, constructed specifically to defeat memorization, scale,
and prior-knowledge shortcuts — i.e., **adversarial to exactly the mechanism
ember's cores run on**. That design intent has consequences on each
requirement:

- Verification density: **excellent.** Grids execute in ms; ground truth is
  the grid itself. This is why it was chosen for NC0.
- Floor accessibility: **fails at residency scale — now measured, not
  argued.** Receipt `t4-r1-q15-arc1-seed14-20260610T150153Z`: 1.5B core, four
  arms × 100 held-out tasks × k=8 — all-zero. Published anchor: SOAR reports
  ~1% pass@1 zero-shot for a 7B-class base; positive ARC results at small
  scale (e.g. test-time-training lines reporting ~50%+) buy the floor with
  per-task adaptation compute far outside a residency budget.
- Leak resistance: **excellent** — the eval splits are the cleanest held-out
  surfaces available at this size, and ARC-2 adds a distribution-shifted
  second surface for free.
- Portfolio coupling: **weak.** ARC measures few-shot abstract rule induction
  over grids. The portfolio's unsolved problems (below) are
  engineering-shaped: dense-verification, long-horizon, tool-mediated.

The user's framing is correct and matches the frontier evidence: models that
dominate terminal-bench/SWE-bench-class agentic work can still fail ARC-AGI.
ARC isolates one capability axis; it neither proves nor disproves the
capability axis ember's goal actually targets (accumulate from verified
experience in inspectable worlds).

## 3. The error in the original design — and the fix

NC0 used ARC in **two roles at once**: as the instrumentation world (where the
loop is proven) and as the implicit hardness thesis (solving ARC ⇒ the mind is
real). The roles have opposite requirements: instrumentation wants floor
accessibility; a hardness thesis wants adversarial difficulty. Conflating them
produced this week's bind: a world too hard to feed the loop at the core sizes
residency demands.

**Fix — split the roles:**

- **ARC becomes a held-out transfer surface, not a training world.** Its
  adversarial design is precisely what you want in an *eval*: if accumulation
  on other worlds ever moves the ARC needle without ARC training data, that is
  strong transfer evidence, leak-resistant by construction. ARC-1/ARC-2 eval
  splits stay in the T4 battery permanently.
- **Training worlds are selected by the §7 criterion** (floor-accessible,
  verification-dense, portfolio-coupled):
  - **W-code (immediate):** graded program-synthesis with unit-test verifiers
    (MBPP-class difficulty ramp; same sandbox, same receipts). Even small
    cores have a known nonzero floor here — the loop can be *proven* (G1/G2/G3
    separation measured) before being aimed at harder worlds. The t5 harm
    suite already uses MBPP-50; the world reuses that plumbing.
  - **W-ifc (NC1c, feasibility already receipted):** IFC/building-data
    checks — per-check partial credit = dense graded verifier; couples to the
    vault corpus and WEB-CAD kernel work.
  - **W-policy (NC1d):** ARC-AGI-3 *policy* world — ember writes explorer
    policies (segmentation/priority/BFS organ variants) verified by local game
    execution against the frozen dolphin v3 K=6/25 baseline and the
    792-experiment zero-learning RHAE ledger. Note this is NOT the same task
    type as ARC-1 grids: policy-writing is engineering-shaped with graded
    outcomes; the-search's failure ledger becomes the scoring substrate.
  - **W-harness (NC-K):** ember's own organs as a world — test suites +
    invariant checks as verifier; the avir-cli invariant map (in extraction
    now) defines the task space. Maximum portfolio coupling: this is where
    "fork the local agent stack and own it" materializes as verified episodes.

## 4. What this does NOT change

- **The 3B verdict in flight gates first.** Receipts decide, not this
  analysis. If 3B shows a nonzero ARC floor with meta separation, ARC-1
  remains a valid NC0 world *and* the restructure still applies from round 2
  (training worlds broaden; ARC keeps the transfer-surface role).
- **If 3B is also all-zero:** the registered successor is the world
  restructure above — **not a fourth model size.** Climbing the size ladder
  to chase ARC's floor is the datacenter reflex the goal's final sentence
  bans: the world was mis-roled; the core was not too small for the *goal*,
  only for ARC-as-training-world.
- The seed ledger, four-arm protocol, kill criteria, and all receipts carry
  unchanged — they are world-agnostic plumbing.

## 5. Portfolio coupling — the hardness inventory (user item 2.2)

Ember is not another local-model serving framework; nothing on the
HF/llama.cpp/vllm/unsloth shelf has: a verifier-gated experience ledger, a
matched-control + deletion-test gate on every artifact, invariant-gated
self-editing harness, or residency as a correctness criterion. Those
frameworks serve weights; ember is the loop that *earns* them.

The portfolio's hardest unsolved problems, and where they enter the world
ladder:

| Unsolved problem | Evidence of hardness | World |
|---|---|---|
| Self-generated-criteria improvement (the-search, R1–R6) | 792 experiments, zero learning-based RHAE > 0; the-search is a failure ledger | W-policy inherits the ledger as baseline + scoring; ember's gate (G2 control) is the direct descendant of that discipline |
| ARC-AGI-3 interactive worlds | dolphin v3 heuristic ceiling K=6/25; no learning method beat heuristics locally | W-policy |
| Owned local agent stack (no borrowed organs) | LiteRT-class upstream walls in WEB-CAD; every fork = build+test+bench = a verification-dense world | W-harness (NC-K), then NC2-own component contract |
| Building-data / geometry kernels | WEB-CAD NURBS/BRep kernel; IFC round-trip | W-ifc |

The thread through all four: **worlds where verification is dense and the
problems are the portfolio's own.** That is the hardness thesis in a form the
loop can eat — as opposed to ARC's hardness, which is real but aimed at a
different axis and starves the loop at residency scale.

## 6. Decision

1. ARC re-roled: permanent held-out transfer surface; training-world role ends
   with the NC0 3B verdict regardless of its sign.
2. W-code (MBPP-graded) is the next training world if 3B confirms
   floor-unmeasurable — pre-registered successor, replacing any further size
   climb.
3. W-ifc / W-policy / W-harness enter per the existing ladder (NC1c/NC1d/NC-K),
   now with the world-choice criterion (§7 of the formalization) as the
   admission test, including measured floor accessibility before any round-1
   commitment.
