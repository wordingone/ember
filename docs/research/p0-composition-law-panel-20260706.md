# Research tick 2 — P0 composition law: panel synthesis (2026-07-06)

Panel: 3 Fable seats (THEORY / EXPERIMENT / ADVERSARY) + 3 sonnet verification legs, 456k tok.
Grounding: tick-2 pack (#207 comment 2026-07-06) — Net2Net 1511.05641, muTransfer 2203.03466,
GaLore 2403.03507, Q-GaLore 2407.08296, 8-bit optimizers 2110.02861, local receipts (QAT 368M,
D6 718M, rung-1 1.22B GROW_RUNG_PASS, fp35 muon kernel, w2-garm dry-run 20260706).

## 1. THE LAW'S FORM (the tick's core artifact)

Certification of the composed recipe = FOUR instruments, none sufficient alone:

1. **Micro-cells in normalized units** at the small rung — pairwise dangerous cells + the
   mandatory signal-zeroing triples (below). Every cell carries fail-closed lever-engagement
   assertions (#216 rule): a cell without engagement telemetry is inadmissible, never a null.
2. **Connecting-map audit at every grow event**: rung k+1's initial state is G(rung k terminal)
   — transfer reduces to the measurable commutation defect U_{k+1}∘G ≈ G∘U_k in
   width-normalized units (grow-then-step vs step-then-grow on a frozen probe batch).
   This is STRICTLY WEAKER than muTransfer's distributional claim (one trajectory, one map)
   — the lineage structure is why a law is possible here at all without a muP-analogue.
   [SOUND per verify; W2 grow-continuity = the weight-state case of this audit, still OPEN.]
3. **Ratio-invariance monitoring between grows**: the dimensionless mechanism-ratio vector
   (sec 2). Sign-transfer claim: if ratios are held invariant along the ladder AND the grow
   pushforward is update-equivariant, cell SIGNS measured at rung k persist at k+1. Signs
   only — magnitudes never promised. Voiding conditions must be enumerated on every
   certificate (ratio drift, pin change, hardware floor, basin change).
4. **Activation audit** (adversary's fig-leaf converter): for every threshold-gated mechanism,
   the certificate carries measured micro-ratio AND projected 27B ratio; a mechanism whose
   activation state flips between scales (or can't be projected) is auto-listed UNCOVERED,
   fail-closed. Plus an UNCOVERED-CLASSES section for the irreducibly long-horizon
   (SR random-walk needs ONE mid-horizon anchor to validate its cheap indicator; rare-event
   classes priced explicitly or inherited from the integration arm's stated horizon).

REJECTED: one-shot "micro certifies 27B" (muTransfer is the existence proof transfer is not
default; several mechanism ratios are width-dependent so signs can flip). ADOPTED: rolling
per-rung certification with bounded one-grow-step extrapolation.

## 2. The dimensionless ratio vector (what "normalized units" means)

- ρ_SR = E‖per-step update‖/Δ (~1/100 now) — cells A, I, SR variance
- ρ_noise = ε/Δ (net2net noise vs grid step) — cell A branches
- ρ_rank = r/width and ρ_grow = w_parent/r — cell C phases (see correction 4)
- ρ_spec = σ_asym/σ_max of momentum at grow — cell B via NS5 gain
- ρ_batch = (batch × (1−β)⁻¹) vs grad-noise scale — cell E; ADMISSIBILITY precondition for
  Muon-bearing cells (Muon has no LR-compensation channel; batch buys direction SNR only)
- ρ_block = fresh-state magnitude / block noise floor — cell H
- CANDIDATE MISSES (attack surface, unclosed): LR-schedule phase across grow, dataloader
  state across grow, RNG-stream architecture (single vs per-tensor generators — flips A2).

Headline prediction (falsifiable, probe P5): under the default absmax-referenced grid, ρ_SR
DRIFTS up the ladder (grid tracks weight scale, updates scale differently with width) — SR
receipts lose transferability at higher rungs unless the grid is re-referenced to update-RMS
or bit-width is scheduled per rung. The direct analogue of muP's LR rescaling: a
parametrization fix that CREATES the transfer law. If ratios are invariant by default, the
prediction dies and the law simplifies — protocol progress either way.

## 3. Signal-zeroing triple rule (kills the combinatorial explosion)

Pairwise closure is FALSE, by constructed counterexample [verified SOUND]:
growth × nearest-quant × Muon — momentum asymmetry is sourced from forward-view differences;
nearest-quant ties the views exactly (absorbing state), so Muon's amplifier gets exactly zero
input; both pairs can pass while the triple realizes no benefit. Rule: mandatory triples are
ONLY those where a third lever can ZERO a pair's mediating signal (identified from the
state-touch table) — a handful of cells, not a sweep.

Cell identity pins (read from live code BEFORE launch, stamped into every receipt):
(i) where quantization lives (fp-master+fake-quant vs SR-resident-master),
(ii) rounding mode + RNG stream independence, (iii) optimizer-state pushforward at grow
(production TODAY: reset — per rung-1 dry-run receipt field optimizer_reset_on_resume:true;
runtime-verify at probe time, the pack does not carry it).

## 4. Dangerous-cell sign table (post-verification corrections applied)

| Cell | Sign prediction | Status/condition |
|---|---|---|
| A1 growth-noise × fake-quant(nearest) | NEG — ties absorbing; only boundary-born entries untie | Δ/2 is an UPPER BOUND on protection, offset-dependent, NOT a guarantee [verify correction]; tick-1 said Δ vs seat Δ/2 — reconcile empirically (P1 measures, never asserts) |
| A2 growth-noise × SR-master | NEUTRAL-to-POS for untying — SR amplifies ε-energy ~Δ/ε sparse/random; unties even at ε=0 given INDEPENDENT per-entry RNG | RNG independence = engagement assertion, not assumption; expected-untie constant (ε/Δ vs 2ε/Δ) unpinned — measure |
| B growth × Muon/NS5 | POS untying (strongest breaker, small-σ gain a⁵≈485×) + NEG transient spike risk | NS5 preserves exact ties because iterates are (XXᵀ)ᵏX (row-Gram), NOT because odd [proof corrected by verify]; coefficients (3.4445,−4.775,2.0315) must be RUNTIME-READ (memory-tagged, not measured) |
| A×B×quant triple | Pair-POS flips to NO-BENEFIT under nearest-quant (signal zeroed) | The pairwise-closure counterexample; "negative"→"no benefit realized" [verify softening] |
| C growth × rank-r projection | BIPHASIC **iff r ≥ w_parent** (lossless instant, then projector starves fresh directions until SVD refresh, T-quantized delay); **monophasic-NEGATIVE if r < w_parent** | [verify correction — the r-regime is a pin, unestablished for production; P3 runs both arms] |
| D momentum-repr × Muon | bf16(relative-error) NEUTRAL [consistent w/ D6 MEASURED]; 8-bit(block-absolute) NEG, grows with width (floor-noise fed to 485× amplifier) | error-MODEL taxonomy, not bit-count |
| E batch/accum × Muon | NEG when ρ_batch shifts down from production point | admissibility precondition |
| F growth × state-pushforward | indeterminate w/o pin; wrong pin = NEG at step one | update-equivariance = the forced choice; production resets today |
| G checkpointing × stochastic forward | ZERO iff replay-deterministic; NEG (silent) otherwise | never an empirical cell — per-step recompute-hash assertion |
| H growth × 8-bit blocks | NEG — fresh state quantizes to exact zero in parent-scale blocks | mitigation structural: fresh capacity gets own blocks at grow |
| I weight-decay × 4-bit grid | NEG both branches — nearest: decay silently OFF; SR: decay becomes Δ-jump diffusion | #216 class; config says ON, physics says NO-OP |

SR structural clearance (corrected): SR unbiasedness ⇒ expectation-transparency to upstream
levers stands; interference = write-variance × curvature with Var_write ~ Δ²·f(1−f) ≤ Δ²/4
per write [verify correction — NOT Δ·|update|]; accumulation-splitting invariance holds ONLY
under a high-precision shadow accumulator with one SR commit — which is EXACTLY the
CPU-accumulation design decision (P3 arm interacts; the architecture premise goes on the
certificate).

## 5. Probe suite (merged, deduped, cheapest-first; ~7 GPU-h total)

| # | probe | source | window | GPU-h | fires |
|---|---|---|---|---|---|
| 1 | P5 grow-event RATIO-INVARIANCE audit + commutation defect (law probe) | seat1-P5 | instrumentation only, frozen batch, existing lineage | ~0 | FIRST — cheapest, highest law-relevance |
| 2 | P1 A3-UNTIE tier-0 (30 cells, 20-50M, {grid}×{noise}×{rounding}) | seat2-P1 + seat1-P1 merged | co-resident ≤2GiB (CPU fallback) | ~0.5 | with #1 |
| 3 | muP-parametrization audit of production builders (read init/LR scaling rules) | verify-leg demand | read-only code | 0 | with #1 |
| 4 | P2 post-grow rank spectrum, grad AND update-space, reset vs inherit-padded arms | seat2-P2 | piggyback W2 G-arm leg | ~0.2 | when W2 leg fires |
| 5 | P3 batch-LR coupling of the CERTIFICATION METRIC (envelope ~1/√batch) | seat2-P3 | dedicated | ~1.0 | after 1-2 |
| 6 | P1 tier-1 (368M decision cells) | seat2-P1 | dedicated | ~1.5 | after tier-0 shape |
| 7 | NS5 tie-preservation + gain pin + coefficient runtime read-back | seat1-P2 | CPU/GPU minutes + <1h | ~0.5 | opportunistic |
| 8 | Projector-starvation (Cell C, both r-regimes) — EXP-C1/PR #262 harness EXTENDS to this | seat1-P3 ≈ P-ADV-5 ≈ expc1 | dedicated | ~1.0 | harness merged; live leg authorized post-gate |
| 9 | P4 recipe-integration arm + ACTIVATION AUDIT (4 arms incl. zombie dissociation: loss-band PASS + tie-metric FAIL) | seat2-P4 + P-ADV-4 | dedicated | ~1.0 | after 1,2,5 metrics frozen |
| 10 | P-ADV-1 interference scaling ladder (368M→718M→1.22B, 2 highest-risk pairs) | adversary | chunked dedicated | ~2 | after signs exist at one width |
| 11 | P-ADV-2 fresh-init vs lineage A/B | adversary | dedicated | ~0.5 | with #10 |
| 12 | P-ADV-3 SR diffusion + ONE mid-horizon anchor (validates the cheap indicator) | adversary | chunked | ~1 | before any SR-class certificate |

Binding on all: fail-closed engagement assertions before artifact write; mechanism metrics
co-primary with trajectory bands (loss-only certifies zombies); ρ_batch stamped on every
Muon-bearing cell; pins read from live objects, never configs; pre-registered signs frozen
in docstrings; deviations → docs/ledgers/deviations.md.

## 6. Verification ledger (what the sonnet legs corrected — kept so numbers stay honest)

1. NS5 duplication-preservation: TRUE, proof corrected (row-Gram iterate structure, not oddness).
2. SR write variance: Δ²f(1−f) ≤ Δ²/4 per write, magnitude-independent; splitting-invariance
   conditional on high-precision accumulator (was: Δ·|update|, wrong units).
3. Biphasic Cell C requires r ≥ w_parent (else monophasic-negative from the instant).
4. "grad rank ≤ r" conflation (adversary): the tick-1 fact is rank ≤ parent width; whether
   that is within r is a separate unestablished pin.
5. Δ/2 unrepresentability: offset-dependent upper bound, not guarantee; tick-1's Δ vs Δ/2
   unreconciled — both replaced by measurement (P1 grid-landing assertions).
6. NS5 coefficients + optimizer_reset flag + 8.94e-8 logit diff: on-disk receipt citations
   the pack doesn't carry — runtime read-back mandatory before they anchor any cell.
7. tok/s figure inconsistent with own step-time (12,190 vs 11.7k, ~4%) — flagged; FLOP math
   unaffected (uses step-time directly). 16× grid-coarseness → ~15× (2^3.9).
8. Untie-fraction constant ε/Δ vs 2ε/Δ: convention-dependent, pin empirically.
9. MISTAGGED pattern (5 instances): compound claims riding a single basis tag — split CITED
   facts from DERIVED conclusions in all future seat schemas (schema note for tick 3).

## 7. Dispatched / next

- Tick-2 artifact → this file + #207 comment (compact form, no local paths).
- Queue updated: P0 tick 2 COMPLETE (frame+grounding+panel+synthesis); next P0 work = probe
  execution per table above (P5+P1-tier-0+muP-audit first).
- EXP-C1 harness (PR #262): gate in flight; live plumbing leg authorized post-merge; the
  harness's rank-sweep now doubles as probe #8 with the r-regime arms.
- Probe dispatch: next tick with free lane slots (budget-gated), nvidia-smi preflight,
  serialized against v2impl193's CPU extension and any W2 leg.
