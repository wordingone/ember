# World-model compiler — are ember's worlds separate by design, or bolted-on?

**Status:** decision-record, authored 2026-06-14 (the lead). Triggered by the maintainer
(thinking-together, 2026-06-14): *"world model compiler (current framework is
separate worlds, why)."* Mode-2 artifact: captures the lead's derived analysis so it
survives compaction. It makes the calls inside the goal (the maintainer overrides), but it
**does NOT authorize a build or a dispatch** — acting-in-worlds is a post-pretrain
phase; nothing here changes v0.

Distinct from ember-issue-#33 (`docs/research/world-choice-r2.md`), which is world
*admission* (which world to add next, by the §7 criteria of
`docs/research/world-choice.md`: floor accessibility, verification density, portfolio
coupling). That is the layer ABOVE this one. This record is about world
*integration* — how a world relates to the substrate once admitted.

## The question

Why is ember's "act in worlds, verify against world-provided ground truth, burn
verified experience" framework currently a set of **separate worlds**? Is a fixed
per-world separation part of ember's design, or an artifact of incremental
construction that a world-model compiler should dissolve?

## Grounding — what "separate" actually means today

From `world-choice-r2.md` + the harness scripts:
- `scripts/w1_humaneval.py` is **cloned from `w1_mbpp` semantics** (governed
  generation, t1_probe sandbox, per-sample rows, receipts + samples.jsonl).
- The ARC-AGI-3 arcade "Game API/judge infra is **separate** from the t1_probe
  sandbox" — blocked on a new arcade harness.
- IFC/building world needs its own kernel-verifier instrumentation.
- The verifiers hardened at **different times** per world ("V is born hardened on
  HumanEval+, unlike MBPP where extended joined at eng #21").

So two things are currently fused under the word "separate":
1. **The skeleton** — act → run in a sandbox → grade against ground-truth the
   world provides → emit receipts → burn verified experience. This is
   **identical across every world.** The clones prove it: `w1_humaneval` is
   `w1_mbpp` with the dataset and verifier swapped.
2. **The per-world specifics** — dataset, verifier, action codec (emit
   code-tokens vs game-actions vs CAD-ops). These are **genuinely distinct.**

## Settled position

The separation is **bolted-on at the skeleton layer, by-design at the
verifier/action layer.** A clone (`w1_humaneval` ← `w1_mbpp`) is the signature of
a missing abstraction, not a principled boundary. The fix is a **world-model
compiler**: ONE substrate (the skeleton) that compiles a **world-spec**
(dataset + verifier + action-codec) into a running harness, with worlds entering
as **pluggable adapters** rather than copied scripts.

This is the same principle at two levels, and both resolve to "one substrate":

- **Learned layer (the mind):** ONE world-model — one set of weights acting
  across all worlds — not per-world models. Already implied by v0's
  *multimodal-unified* commitment and the goal's singular "*a* mind." Per-world
  models would (a) contradict the singular-mind identity and (b) make the goal's
  required **cross-world held-out transfer** impossible to measure honestly — you
  cannot ask "did the code gain help on games" if code and games run different
  models.
- **Harness layer (the compiler):** ONE skeleton + pluggable world-adapters.
  Kills the clone duplication; makes "research tasks, experiments, retrieval,
  routing, etc." (the goal's open-ended world list) an act of writing an adapter,
  not forking a harness.

## Constitutional reasoning

- **R5 (one ground truth):** cloned harnesses can drift in *what counts as
  verified* — already visible (verifiers hardened at different times per world).
  One substrate = one verification contract = R5-clean. Separate skeletons are a
  standing R5 hazard.
- **R6 (no deletable component):** a world should be cleanly add/removable (the
  goal wants worlds added freely). A pluggable **adapter** is cleanly deletable;
  a **cloned harness** is not — deleting it leaves the skeleton logic duplicated
  elsewhere. So the compiler form is the R6-correct one, and the current clone
  form is an R6 smell.
- **Transfer (goal invariant):** "every gain must survive held-out transfer."
  Cross-world transfer is only natively measurable when worlds share the
  substrate the model runs on. The compiler makes cross-world transfer a
  first-class measurement instead of an ad-hoc cross-harness comparison.

## The pattern — same shape as the multimodal locks and the growth operator

A capability you cannot retrofit must be wired-but-dormant from step 0. The
world-adapter **seam** is that class at the harness/identity layer:

- **Formalize the world-adapter INTERFACE now** (unretrofittable): the
  receipts/ledger/checkpoint/optimizer-state and the act→verify→receipt contract must not
  hard-assume a single world or a single action space. A world is admitted by
  registering an adapter (dataset + verifier + action-codec), not by cloning a
  script.
- **Do NOT build the full compiler for v0, and do NOT block v0 on it.** v0
  pretrain (multimodal-input unification) precedes the acting-in-worlds phase. v0
  may run its loop against a single world; what it must NOT do is calcify
  single-world / single-action-space assumptions into the harness — that is the
  "separate worlds forever" horn, the exact analogue of the growth operator's
  "fixed-body forever" horn.

## Decision

Formalize the world-model compiler's **TYPE/interface** now (harness seam:
world = pluggable adapter, one shared world-model, one verification contract);
do **NOT** build the compiler or admit multiple training worlds in v0; require
only that v0's harness expose the adapter seam rather than weld single-world
assumptions in. (the lead call, 2026-06-14 — not escalated; the maintainer overrides. Design call
inside the goal, his to redirect but mine to make.)

## OPEN — the real research piece (named, not bounced back)

How does ONE world-model represent **heterogeneous action spaces** (code-tokens
vs discrete game-actions vs continuous CAD-ops) on one substrate **without a
per-world output head that silently re-introduces the separation**? This is the
multimodal-unification problem one level up: v0 unifies input modalities via
Fuyu-style continuous soft tokens; the same logic — a shared token interface that
absorbs the modality instead of bolting a head onto it — is the candidate
direction for ACTION/world unification. Stated as direction, not solved: a naive
per-world action head would defeat the whole point, so this needs the same care
the input-side locks got.

**Revision criterion:** if, when acting-in-worlds begins, a shared action
interface proves to cost more than the transfer it buys (e.g. a per-world head
matched on transfer in a controlled test), the seam stays but the
single-world-model claim weakens to "shared trunk, thin per-world heads" — a
measured fallback, not a default. The seam (adapters, one verification contract)
is correct regardless; only the depth of weight-sharing is the open variable.

## Readiness relevance (CANDIDATE, like the growth seam — pending the maintainer)

Before v0 launches, its harness should not calcify single-world / single-action
assumptions into receipts/ledger/checkpoint/optimizer-state. Lower priority than the
multimodal-INPUT locks (those gate the pretrain itself; the world seam gates the
later acting phase), so recorded as a candidate, not locked. the maintainer may converge on
"single training world is genuinely fine for v0, formalize the seam later," which
retires this.

Per user direction.

---

## ADVANCE 2026-06-16 — heterogeneous action spaces resolve to a shared primitive grammar

ember resumed (the maintainer lifted the block); the OPEN piece is the seat's live thread. Advancing it, not restating.

### 1. The invariant was mis-stated — fix it first
"Without a per-world output head" is the right intent but the wrong literal. The **input** side already runs >1 input mechanism — continuous patch-projection (pixels/geometry) AND embedding-lookup (text) — and that is no violation, because each mechanism is **shared across all worlds**. So the lock is **no per-WORLD specialization**, NOT "literally one output head." A *small, closed set of per-PRIMITIVE output mechanisms, each shared across every world,* satisfies the lock. A per-world scalar-head violates it (kills cross-world transfer); a single scalar-head shared by CAD + every other continuous world does not. The doc previously conflated per-world with per-mechanism; this is the resolution.

### 2. The asymmetry that makes output harder than input (must be respected)
Input is **consumed** — projection can be lossy and the transformer just attends. Output is **executed** — the action must satisfy the world's typed, discrete-or-continuous validity contract (a game rejects "extrude 5mm"; CAD rejects "press A"). So you cannot project one shared continuous action-embedding and hope; the world has a hard contract. This is why the naive symmetric move (one continuous action token + per-world decoder) fails — the decoder is learned and per-world = separation re-introduced (Candidate 1, rejected).

### 3. The resolution — actions decompose into a shared closed primitive set; a world's action space is a GRAMMAR over it
Closed shared ontology of action-primitives (the bet: these span the goal's world list — code, games, CAD, research-tasks, retrieval, routing):
- **`emit-token`** — discrete symbolic. Covers code tokens, game button-verbs, command verbs, query strings. (LM head over a shared symbol vocab.)
- **`emit-scalar`** — continuous real value(s). Covers CAD parameters, continuous control, any world's continuous knob. **A continuous/regression output, NOT digit-tokenization** — the action-side analogue of the input-side soft-token decision; text-serializing a float destroys its metric structure exactly as discrete image-tokenization destroys the input's (the mirror failure of Candidate 2, everything-is-text).
- **`emit-pointer`** — a selection grounded in the observed state. Covers CAD face/edge selection (cf. FutureCAD grounding-transformer, `reference_futurecad_nl_brep_grounding`), game target-selection, code variable/identifier reference. (Attention over state entities.)
- **`commit` / `stop`** — episode/step control. Shared across all.

A **world-action is a primitive-program** — a short sequence: `emit-token "fillet" → emit-pointer edge → emit-scalar radius → commit`. The action space is a finite grammar over shared primitives, and structured/mixed actions are handled by **composition** (finite primitives, unbounded expressions — the same move language makes). The **deterministic world-adapter** (a world-spec component alongside dataset + verifier, **zero learned weights on the critical path**) declares which primitives the world admits and parses the primitive-program into the world's executable call. The model learns ONE policy that emits primitive-programs; it never learns a per-world output mapping.

### 4. Why this is R5/R6-clean and strengthens the transfer invariant
- **R5 (one ground truth):** one action-emission contract across all worlds; the adapter *renders*, it does not *redefine*. Clean.
- **R6 (clean add/remove):** the adapter is deterministic world-spec → deletable; removing a world removes its adapter, not a head. Adding a world is registering an adapter + (rarely) extending the *shared* ontology — never a per-world head. Closed-but-rarely-extensible: "closed" buys transfer, extension stays shared.
- **Transfer (goal invariant) — sharpened:** transfer is now measured at the **primitive level** — does `emit-scalar` precision, does `emit-pointer` grounding, learned in CAD transfer to a continuous-control or selection sub-task in another world? This is a stronger, more honest probe than "did serialized-action text transfer," and it is only askable because the primitives are shared. The compiler makes primitive-level cross-world transfer first-class.

### 5. Revision criterion — sharpened
The doc's fallback was "shared trunk, thin per-world heads." Correct it: the first fallback is **ontology extension** (a world needs a primitive the closed set lacks → extend the *shared* ontology; still no per-world head). Only if **primitive-sharing itself fails a controlled transfer test** (a per-world emit-mechanism measurably beats the shared one on held-out transfer) does weight-sharing depth weaken — and even then the seam (adapters, one verification contract, primitive-typed action log) stays. The open *empirical* bet is the ontology's completeness across the world list, not the architecture.

### 6. v0 readiness seam — sharper than "expose the adapter seam"
Concrete requirement: v0's harness must record actions as **`(primitive-kind, payload)` in the shared ontology from step 0** — NOT as world-native action logs. If v0 logs actions world-natively (e.g. raw game-action ids, raw CAD-op structs), the primitive decomposition cannot be retrofitted — the data to measure primitive-level transfer is already gone. This is the calcification horn for the action side, exactly analogous to the input-side locks. v0 may still run a single world; it must log in the primitive-typed contract. Ships as the conservative default — the primitive-typed action-log contract is the v0 requirement, recorded below the multimodal-INPUT locks; the maintainer can override to defer it. A concrete logging contract now, not a vague seam.

Per user direction.

---

## Ownership (added 2026-06-16 — routing contract per cron-tick step 6b)

The routable split for #33. The compiler itself is **GATED:post-pretrain** (acting-in-worlds is a later phase; nothing here authorizes building it now). Only the v0 logging seam routes today.

- **Seat (the lead) — research, held:** the primitive ontology (§3) and its open empirical bet — does the closed set (`emit-token` / `emit-scalar` / `emit-pointer` / `commit`) span the goal's world list? Couples to llmwiki (#45): the problem-index grain = the primitive-class grain = the same closed-but-useful classification question. Tracked via **CC task #33** (seat-owned, in_progress). The seat gates the first adapter-interface formalization when acting-in-worlds opens.
- **the engineer — the one v0-execution requirement that routes NOW:** §6's primitive-typed action-log contract — v0's harness records actions as `(primitive-kind, payload)` in the shared ontology from step 0, never world-native. This is an unretrofittable readiness seam, so it belongs in the multimodal-unified harness build (**#26**), recorded **below** the multimodal-INPUT locks. Does NOT authorize compiler work — logging contract only.
- **President (an agent) — runs/gates:** carries the primitive-typed action-log as a v0 readiness CANDIDATE (like the growth seam — **GATED:the maintainer-convergence**; the maintainer may converge on "single training world is fine for v0, formalize later," which defers it). Reconciles this doc via the step-6b scan — note it lives in `nc-ladder/docs/`, so the scan must cover `nc-ladder/docs/*.md`, not only `state/*.md` root.

**Proven-routed by:** task #33 (research half) + the §6 logging-contract line under #26 (execution half). **Deliberate holds:** the compiler build (post-pretrain) and the readiness-lock depth (the maintainer-convergence).

---

## ADVANCE 2026-06-16 (b) — does the closed primitive set span the goal's world list? (the OPEN bet, first pass)

The OPEN empirical bet (§3/§5): does {emit-token, emit-scalar, emit-pointer, commit/stop} cover the goal's worlds? First-pass mapping (world → its action → covering primitive):

| world | action | primitives | gap? |
|---|---|---|---|
| grids (ARC) | place colored cells / submit grid | emit-token (color) + emit-pointer (cell/region) + commit | none |
| programs (HumanEval/MBPP) | emit code | emit-token + commit | none |
| games (ARC-AGI-3) | discrete move / target | emit-token (verb) + emit-pointer (target) + commit | none |
| buildings/CAD (IFC) | extrude/fillet/place | emit-token (op) + emit-pointer (edge/face, FutureCAD grounding) + emit-scalar (dim) + commit | none — the canonical full-primitive case |
| experiments | configure + launch | emit-token (keys) + emit-scalar (hyperparams) + emit-pointer (dataset/component) + commit | none |
| retrieval | query + select | emit-token (query) + emit-pointer (result) + commit | none — = llmwiki's query op |
| routing | select destination | emit-pointer (+ emit-token label) + commit | none — selection is pure emit-pointer |
| research-tasks | produce a spec/hypothesis | emit-token (text) + emit-pointer (cite prior result) + emit-scalar (quant prediction) + commit | STRESS, not gap |

**Two findings.**

1. **The set spans — the stress point is research-tasks, and it's a grain question not a gap.** A research-task "action" (write a spec, design an experiment) is high-level: it is a *program* of primitives (a long emit-token sequence with embedded emit-pointer citations + emit-scalar predictions), not one atomic action. The doc's "finite primitives, unbounded expressions" already covers this by composition. So research-tasks don't need a new primitive — they need the *verifier* (how do you ground-truth a spec?), which is the per-world adapter's job, not the action grammar's. This **reinforces the thesis**: the cross-world differentiator is the VERIFIER, not the action space. The action grammar is genuinely shared; the separation that's real lives in the verifier + the adapter's declared primitive-subset.

2. **emit-pointer is the cross-world workhorse and the direct llmwiki coupling.** It does the most lifting — retrieval, routing, selection, CAD/game grounding all reduce to "select an entity in observed state." It is also exactly llmwiki's problem-index: **problem → emit-pointer → skill-page**. So the #33 primitive-ontology research and the llmwiki problem-index research are *the same research object* viewed twice: a well-grounded emit-pointer (attention over state entities) IS a working problem→skill router. Highest-leverage primitive to get right; llmwiki's problem-index is its first real testbed (retrieval world), before CAD grounding or game targeting. Couples #33 ↔ #45 concretely, not just thematically.

**Next on this thread (seat-held, no dispatch):** stress-test the bet against a world the list doesn't name yet (adversarial completeness — find a world whose action genuinely needs a 5th primitive); and specify emit-pointer's grounding interface precisely enough that llmwiki's problem-index can be its first instance.

## ADVANCE 2026-06-16 (c) — adversarial-completeness pass + emit-pointer grounding interface (first instance built)

**Adversarial-completeness pass (tried to break the 4-primitive set; could not).** Probed worlds the list doesn't name, looking for an action needing a 5th primitive:

- **Editing / deletion** (act = remove or mutate an EXISTING entity, not emit a new one) — the strongest stress, because emit-{token,scalar,pointer} all *produce*. Resolves WITHOUT a 5th: `delete E` = emit-pointer(E)+emit-token(DELETE); `modify E.attr` = emit-pointer(E)+emit-token(SET)+emit-scalar(value). Editing is a grammar over the four. But it **sharpens** emit-pointer: the primitive must address entities already in observed state, not only index newly-emitted ones — which is exactly the grounding interface below.
- **Continuous control / robotics** (act = a real-valued action vector per tick) — emit-scalar×N covers the vector; the step loop + commit cover cadence. No 5th.
- **Distributional actions** (emit a distribution, not a sample) — a probability vector = emit-scalar×N; sampling is the environment's job. No 5th.
- **Dialogue / negotiation** (utterance conditioned on a partner) — emit-token for the utterance; the partner is observed state, referenced by emit-pointer. No 5th.

**Residual flag (one place to keep probing, not a v0 gap):** a truly *continuous-time* control world (act at arbitrary real-valued times) would stress the discrete-emission/step-cadence assumption, not the primitive set. All of ember's named worlds are discrete-step, so this is out of v0 scope — logged so the bet isn't silently over-claimed.

**emit-pointer grounding interface (specified — the open §107 piece, now concrete):**

```
emit-pointer.resolve(query, address_space) -> pointer
  query         : a state-derived vector (what we're looking for)
  address_space : a TYPED set of currently-addressable entities, each with a key/embedding
  resolver      : attention(query, {keys}) -> argmax|sample   (pointer-network / cross-attention)
  pointer       : a typed reference whose target type is declared per world
```

The *interface* and the *resolver mechanism* are shared across worlds; only `address_space` and the pointer's declared type are world-specific — CAD: faces/edges (`face|edge`); games: on-screen targets (`target`); code: symbols/files (`symbol`); retrieval: skill pages (`skill-page`). The declared type is what lets the per-world **verifier** check "does this reference resolve to a real entity" — consistent with finding (1) above (the differentiator is the verifier).

**First instance — BUILT today (proving the primitive by use, not assertion):** the llmwiki problem-index IS this interface instantiated for the retrieval world. `address_space` = `<local>` skill pages keyed by `problem_class`; `query` = a problem-instance; `resolver` = the problem→class router; `pointer` = `skill_id`. Three first-instance skill pages now exist with cross-surface trajectories (anti-goalpost-preregistration, compute-matched-comparison-validity, component-decomposition-binding-constraint), and the standard is frozen in `llmwiki/.agent/config`. The OPEN research that remains — *which query embedding makes problem→class routing reliable* (v2's admitted gap) — is precisely the resolver's parameterization, and it is **shared** with CAD grounding and game targeting. So tuning the llmwiki router is not a retrieval side-quest; it is the first real measurement of emit-pointer's grounding, transferable to every other world. This is the concrete #33 ↔ #45 coupling, now with an artifact behind it.

Per user direction.

## ADVANCE 2026-06-16 (d) — resolver parameterization decided (the transferable-form trap)

The resolver's *parameterization* (the open piece (c) named) is now designed:
`<local-path>` (committed llmwiki 23e8a76).
The load-bearing decision for #33: **the locally-optimal resolver is NOT the
transferable one, and the goal demands the transferable one.** A symbolic
`problem_class` taxonomy + keyword match wins every local metric at small N — but
it has no analogue in CAD face-selection or game targeting, so tuning it
transfers nothing. Only the `attention(query, {keys})` form is the *shared*
`emit-pointer` mechanism (c) requires; CAD/game grounding already ARE
attention-over-keys. So the retrieval instance must build+measure the attention
form (symbolic kept only as the small-N interpretable oracle to score it). This
is flagged so a future "simplification" back to symbolic doesn't silently sever
the #33 coupling. Verifier rule sharpened: ∅ ("no covering entity") is a legal,
correct pointer output — forcing argmax is how a resolver fakes coverage; the
per-world verifier must accept the empty pointer. Measurement is scale-gated
(needs a querent who doesn't hold the answer + a corpus where the answer isn't
obvious → arrives with bulk extraction); forward bar = a `prove-by-use-002`
receipt, the first cross-world-transferable measurement of emit-pointer's grounding.

Per user direction.

## ADVANCE 2026-06-16 (e) — the multimodal floor-probe is emit-pointer's PERCEPTUAL instance (#33's first scale-gated test, riding the launch)

Authoring the checkpoint-1 floor-probe for the earn-the-run launch
(`v0-multimodal-floor-probe-prereg.md`, MR-8) surfaced that it **is a second
instance of the emit-pointer resolver (c)/(d)** — the perceptual one, in a
different address space:

    emit-pointer.resolve(query, address_space) -> pointer
      multimodal:  query = caption position ; address_space = image patch keys ;
                   resolver = the model's attention over image patches ;
                   "pointer" = the grounded next-caption token
    the probe metric ΔNLL = NLL(cap | image ABLATED) − NLL(cap | image PRESENT)
    measures exactly whether attention-over-image-keys is doing grounding work.

So #33 now has **two resolver instances of the same `attention(query,{keys})` form**
(the transferable form (d) demanded), in two address spaces: **symbolic/retrieval**
(llmwiki problem-index → skill-page; gated on `prove-by-use-002`, awaits bulk
extraction) and **perceptual/cross-modal** (image patches → grounded token; measured
at the authorized run's checkpoint-1, MR-8).

Why the perceptual instance is the stronger *first* test:
1. **No symbolic-taxonomy trap.** (d)'s load-bearing warning was that the retrieval
   resolver can collapse to a keyword/`problem_class` oracle that wins locally but
   transfers nothing. Image patches have **no symbolic-taxonomy shortcut** —
   attention-over-keys is the only available form, so the perceptual instance
   measures the transferable mechanism directly, with no oracle to collapse to.
2. **Rides the authorized launch — no separate compute ask.** The probe fires at
   checkpoint-1 of the run the maintainer authorizes; #33's first scale-gated grounding read
   arrives **free with the launch**, and **earlier** than `prove-by-use-002` (which
   waits on llmwiki bulk extraction). The perceptual instance likely produces #33's
   FIRST empirical grounding signal.

**The cross-world transfer prediction (now first-class, two address spaces):** if
attention-over-keys grounding emerges in BOTH perceptual (image) and symbolic
(problem-index) address spaces at v0 scale, that is evidence for **one transferable
resolver mechanism** — the #33 central claim — over two locally-optimal per-world
taxonomies. Perceptual-PASS + retrieval-PASS = the cross-world transfer signal #33
is built to find; a split (one passes, one fails) bounds the claim to an
address-space-specific mechanism, which is itself a sharp, receipted finding.

**Honest scope:** ΔNLL>0 is *weak* evidence — it shows the image moves the caption
distribution, not that a clean pointer-*selection* emerged; v0's encoder-free
attention is the substrate, and the floor-probe is the first read that the substrate
grounds **at all**. The strong test remains whether the same resolver
*parameterization* transfers across the two instances.

**Routing:** seat-held research; measurement `GATED: the maintainer-launch-authorization` (fires
at the run's checkpoint-1, same gate as MR-8) — no dispatch, a named empirical test
that runs when the launch runs. Couples #33 ↔ the earn-the-run launch concretely:
the launch is not only the goal's first real run, it is #33's first grounding
measurement.

## ADVANCE (f) — the STRONG transfer test, frozen (`wmc-cross-world-transfer-prereg.md`)

ADVANCE-e named but did not operationalize the strong test: "whether the same resolver
*parameterization* transfers across the two instances." (e)'s verdict ("both ground =>
one mechanism") is the WEAK test — two instances passing independently is consistent
with two coincidental per-world taxonomies. ADVANCE-f freezes the strong test as a
standalone prereg (`docs/archive/pre-restart/wmc-cross-world-transfer-prereg.md`):

- **Decompose** the resolver into a transferable CORE (query-projection `Q` +
  attention) and an address-space-specific SHIM (`K,V` projections over the keys).
  "Same parameterization transfers" iff the core trained on one address space gives a
  **sample-efficiency head start** when only the shim is retrained for the other.
- **PRIMARY mechanical test:** r = T_transfer / T_scratch (tokens-to-grounding,
  frozen-core vs from-scratch), both directions, >=2 seeds. **TRANSFER** (one
  mechanism) if r <= 0.5 both ways; **ADDRESS-SPACE-SPECIFIC** (refuted) if r >= 0.9
  either way; INCONCLUSIVE between -> bounded extension. Corroborating per-instance
  invariants: empty-pointer handling (ADVANCE-d) + attention-selectivity signature.
- **Time-sensitive consequence (why freeze now, not post-launch):** the FROZEN-CORE
  arm is impossible to build unless the launch checkpoints the **resolver core
  separably** (Q + attention, distinct from the image-patch K,V) and logs
  attention-entropy. This is a launch-instrumentation requirement -> folded into the
  #13 packet's run-spec this tick, so the v0 run captures what makes #33's central
  claim testable later. Without it, the transfer test is permanently unrunnable on v0.
- **Routing:** `GATED: perceptual-grounding-PASS AND symbolic-grounding-PASS` —
  doubly-gated (launch checkpoint-1 + llmwiki prove-by-use-002); frozen seat output.

This upgrades #33 from the weak coincidence to a measured transfer with a mechanical
verdict, and surfaces the launch-instrumentation dependency before it is too late.


Per user direction.
