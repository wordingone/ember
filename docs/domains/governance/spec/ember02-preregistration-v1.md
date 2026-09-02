# EMBER-02 Pre-Registration v1

**Status:** PRE-REGISTRATION — frozen upon merge; binds at rung-1 dispatch. Amendments only as versioned superseding documents (v2, v3, …) under the tighten-only rule (§9). Machine-readable threshold freeze: `ember02-preregistration-thresholds-v1.json` (this document and that file are generated from the same threshold table, §8; on any discrepancy, the stricter reading governs pending an errata amendment). Independent ratification pass 1 applied (edits E-A..E-G, §0).
**Repo pin:** `wordingone/ember @ 3d48d3870919bd04cec735f68d0fad45fcfae0b2`. Authority order: INVARIANT.md → GOAL.md → CONTINUITY.md / docs/domains/governance/guides/START-HERE.md → the closed-boundary research annex (`docs/domains/governance/research/`, pinned).
**Hard gate:** EMBER-01 certification must exist before any training step executes. Dispatch validates against this document's commit sha (`--prereg <sha256>`).
**Verdict authority:** the repo's CI, guards, admission contract, and board conditions adjudicate all evidence; nothing here is self-declared credit (INVARIANT.md clauses 1–2).

---

## 0. Ratification changelog (independent ratification pass 1 — all rulings applied, none loosens a frozen predicate)

| Edit | What changed | Sections |
|---|---|---|
| E-A | F-02 band restructured: horizon-widened form (`sqrt(t/T-01)` growth — the frozen estimator's own extrapolation uncertainty) AND an exit-band breach with all kill predicates green demoted to FORECAST-MISS (anomaly + failure-library + recalibration + pivot receipt required before R3 funding). Both fixes taken — stricter than either alone: the hard band is retained, and a miss forces receipts instead of generating post-hoc amendment pressure | §3 R2-E1, §8 F-02 |
| E-B | F-08 final credit adjudicated at MATCHED CUMULATIVE CHARGED BUDGET: control's final checkpoint vs A3's OWN checkpoint at the control's budget point (the hash-chained checkpoint sequence supplies it); T-19 = 0.33 recast as the control-continuation floor for trajectory evidence ONLY, never the credit denominator | §3 R4-E5, §4.4, §8 T-19/F-08 |
| E-C | Sigma source for full-suite metrics named: `sigma_credit(m) = max(sigma_seed(m) where R1-E7 measures it, sigma_eval(m))`, with `sigma_eval` = per-benchmark item-level nonparametric bootstrap (10,000 resamples) or exact binomial SE, receipted with the frozen eval; max = wider band = stricter credit bar; computable from receipts that will exist | §2, §6, §8 F-08/F-09 |
| E-D | T-20 declared AMENDMENT-FROZEN: the shared signal-band coefficient is consumed on both the credit side (raise = tighter) and the tolerance side (raise = looser), so no unambiguous global tighten direction exists; its value is immutable for the program and any change is a scope decision requiring operator authority | §2, §8 T-20, §9 rule 5 |
| E-E | F-11 doc wording harmonized to the JSON's per-metric reading: `sigma_seed(grad_norm_ratio)` | §8 F-11 |
| E-F | T-22/T-23 baseline stated explicitly as each arm's OWN R1-scale measured value (removes the T-08 contradiction for A1 under Tier-1 offload) | §3 R2-E2, §4.1, §8 T-22/T-23 |
| E-G | D-01/D-02 backstop floors pre-committed (above-chance at T-24; D-02 additionally no-regression-vs-R3-exit beyond the signal band); the deferred settlements may only TIGHTEN from these backstops | §3 R3-E3/R4-E1, §8 D-01/D-02, §9 rule 8 |

---

## 1. Subject and scope

- **Goal:** EMBER-02 (`active_goal_id` per GOAL.md EMBER_AUTHORITY_V1); `next_executed_outcome`: first sufficiently pretrained clean-genesis 3B Ember.
- **Ladder subject:** the existing validated candidate manifest (checkpoint `bf20f050…`; 3,839,161,856 total/trainable/served parameters; 1,020,589,568 active and episode-trainable; cursor step 2; 2,048 tokens seen), continued — not a fresh genesis — under the `ember-owned-rung-v1` admission contract. Closed-boundary ledger t0 = the candidate's genesis receipt: the already-seen 2,048 tokens are charged, not orphaned. Admission-contract validation (`python src/ember/governance/scripts/ember_restart/contract.py validate configs/ember-restart-3b.json`) is the fail-closed prerequisite; if it rejects the continuation manifest, the ladder halts pending an operator decision — no silent fresh genesis.
- **Boundary:** one RTX-4090-class 24 GiB GPU plus the declared local host. All creation cost — data acquisition/curation, host work, tools, verification, evaluation, test-time reasoning, failed runs, aborted segments — is charged to this boundary (§5).
- **Two ladders, two axes:** GOAL.md's [3B, 7B, 15B, >27B] is the parameter ladder across goals. The R1–R5 STEP ladder below lives entirely inside the 3B rung. Rung letters are R (not B) to avoid collision with the repo's B1–B5 bottleneck walls (START-HERE.md §2).
- **Execution surface:** every executed job runs through the ember-cli execution surface (GOAL.md §10). Command bindings: `ember-cli train start --rung R<n> --prereg <sha256>` (fail-closed on entry-gate receipts + prereg hash), `ember-cli train status`, `ember-cli train abort --reason <kill-id>` (kill receipt written first), `ember-cli receipts verify --rung R<n>`, `ember-cli frontier show`.

## 2. Statistical calibration primitives (used throughout)

- **Seed-noise sigma `sigma_seed(m)`:** for each frozen probe metric `m`, the pooled standard deviation of `m` across independent-seed replicas at matched step counts, measured at R1 scale (threshold T-07 seeds) and filed as receipt R1-E7. All variance-calibrated bands below are formulas over `sigma_seed(m)`; they become numbers the moment R1-E7 lands, with zero post-hoc freedom.
- **Suite-metric sigma `sigma_credit(m)` (E-C):** for metrics adjudicated by F-08/F-09 — including full-suite metrics R1-E7 cannot cover (no R4-scale multi-seed run will ever exist to supply their seed sigma) — `sigma_credit(m) = max(sigma_seed(m) where R1-E7 measures m, sigma_eval(m))`, where `sigma_eval(m)` is the per-benchmark evaluation-variance bound: item-level nonparametric bootstrap standard error (10,000 resamples) or, for accuracy-type metrics, the exact binomial standard error — computed from and receipted with the frozen eval itself. Taking the max widens the band, which for credit predicates is the STRICTER direction.
- **Signal band:** a between-arm delta on metric `m` with |delta| ≤ T-20 × `sigma_seed(m)` adjudicates **NO-SIGNAL** — a third outcome distinct from pass and fail, creditable to no arm. **(E-D)** T-20 is AMENDMENT-FROZEN: it is consumed on both the credit side (raising it = stricter) and the tolerance side (raising it = looser), so no single tighten direction exists; its value is immutable for the program and any change is a scope decision requiring the operator's explicit authority.
- **Kill band:** kill predicates on the same axis fire at T-21 × `sigma_seed(m)` (strictly wider than the signal band; lowering T-21 = tighter, direction unambiguous).
- **Formula-freeze rule:** every R2+ threshold defined as a formula over R1 measurements is frozen HERE as the formula; substituting the measured numbers is mechanical, receipted, and not an amendment. Values marked DEFERRED-AMENDMENT (§8) can only be set by a superseding pre-registration version before the rung that consumes them, never mid-rung, and may only TIGHTEN from their pre-committed backstops (E-G).

## 3. The rung ladder (R1–R5)

Common structure per rung: entry gate (all predicates receipted before dispatch), exit evidence (receipt-checkable), kill criteria (frozen here), two mandatory closing receipts (failure-library entry per anomaly/kill/falsifier, classed under `receipts/failure-classes/` so no failure class repeats; forecast-recalibration receipt: predicted vs measured step time, tokens/s, proxy-joules/token, peak VRAM, loss trajectory), and one closed-boundary frontier receipt (§5). Funding rule: no rung is funded until its predecessor is green AND both closing receipts exist AND no fired falsifier lacks a pivot receipt (earned-compute law L6).

### R1 — WARM-100 (cold canary, T-01 steps)

**Entry:** EMBER-01 certification receipt; this pre-registration hash-pinned; admission-contract validation green; dispatch-gate receipts under `receipts/ember-restart-3b/` bound to this run; energy-proxy logger smoke-tested pre-birth; fixed-prior manifest committed (§5.2).

**Exit (state WARM):**
- R1-E1: T-01 consecutive steps complete; zero NaN/Inf in loss and grad-norm fields.
- R1-E2: mean loss over final T-03 steps < mean loss over first T-02 steps.
- R1-E3: checkpoint save/restore round trip — hash-bound checkpoint written, reloaded, cursor advances correctly.
- R1-E4: measured tokens/s, MFU, peak allocated/reserved VRAM, host utilization receipted (forecast baseline).
- R1-E5: first closed-boundary frontier receipt per §5.4 with `energy_boundary: DEGRADED_PROXY`.
- R1-E6: forecast-recalibration receipt filed.
- R1-E7: seed-noise measurement filed — `sigma_seed(m)` per frozen probe metric, ≥ T-07 seeds.
- R1-E8: A1-mechanism discriminating-check receipts filed (liveness leg; parity leg if the fallback tier is invoked) per §4-A1. An A1 arm without green R1-E8 is not funded at R2.

**Kill:** loss NaN/Inf at any step; loss > T-04 × initial loss sustained T-05 steps; peak reserved VRAM exceeds the arm's residency-receipt declared budget (F-01); free-commit margin below the host governor floor (declared in the fixed-prior manifest) at a phase boundary → checkpoint + clean abort; energy-logger sample coverage < T-06; any unreceiptable step (a stopped run).

### R2 — CAPABLE-1k (efficiency proof, T-10 steps)

**Entry:** R1 green + closing receipts; arm configs validated through the admission contract (every arm ≥3B total parameters — GOAL.md §3 forbids any sub-3B new network); per-arm residency receipt (byte-level state inventory, wall #10); per-arm gradient-support receipt mechanism armed (§4-A2); A1 discriminating checks green (R1-E8); precision micro-arm configs frozen (§4.3).

**Data-stream law:** all arms at a rung consume the identical frozen data stream — same source manifest, shuffle seed, batch schedule, data cursor discipline — receipted per arm. A data-stream mismatch between compared arms voids the comparison for credit (still usable for kill decisions against the mismatched arm's own bands).

**Exit (state CAPABLE):**
- R2-E1: loss trajectory inside the horizon-widened predicted band F-02. **(E-A)** An exit-band breach with all kill predicates green adjudicates as **FORECAST-MISS**, not a hard rung-fail: mandatory anomaly + failure-library entry + forecast-recalibration receipt + pivot receipt, all required before R3 funding — a miss forces receipts; it is never silent passage and never a false failure of a healthy run.
- R2-E2: efficiency floor — **(E-F)** each arm adjudicated against its OWN R1-scale measured baseline (the per-arm R1-scale smoke measurement of §4.1): tokens/s ≥ T-22 × the arm's own R1-scale measured value; proxy-joules/token ≤ T-23 × the arm's own R1-scale measured value; P1 receipt-shape check passes (`src/ember/governance/scripts/check_energy_law_theory.py`).
- R2-E3: matched-control delta at equal budget (C3/C4/C5) on the frozen cheap-probe battery, adjudicated against the signal band (F-03): A3 below the band vs A2 fires falsifier F1 (pivot receipt); inside band = NO-SIGNAL.
- R2-E4: frozen cheap-probe battery above chance with a one-sided lower confidence bound at level T-24 exceeding chance per probe.
- R2-E5: precision-localization verdict receipted (adjudicated by the frozen bands of §4.3).
- R2-E6: router health — utilization entropy ≥ T-13 × maximum entropy over the arm's selectable subsets, sustained; breach flags the rung's comparison CAPACITY-CONFOUNDED (§4.5).
- R2-E7: second frontier receipt + closing receipts.
- R2-E8: gradient-support receipts per arm — measured parameters receiving nonzero gradient per step and resident optimizer-state bytes, each within T-11 of A3's.

**Adjudication asymmetry (binding on every R2 arm verdict):** R2 evidence can KILL an arm and can fire F1's pivot, but no A3-superiority claim is creditable from R2 alone; superiority claims require the R3 sustained-regime re-check. Rationale: fixed task-routing pays no router-warmup transient — the 1k-step regime is biased toward A3, so an early pass is weak evidence and an early win is inflated.

**Kill:** R1 set, plus: matched-control catastrophic loss beyond the kill band (F-04); router collapse — entropy below T-13 floor sustained T-14 steps; gradient-support tolerance breach sustained past T-12 steps (an entry-gate failure for the arm, not a disclosure); micro-arm divergence aborts the micro-arm only (main lane unaffected).

### R3 — MULTIMODAL-10k (governed sustained run, T-15 steps)

**Entry:** R2 green + closing receipts; R3 config frozen INCLUDING the precision partition selected by the §4.3 verdict; multimodal data manifest receipted — image/audio corpora, full provenance, acquisition/curation charged to the ledger, zero learned imports (no learned encoders or filters; raw patches/frames project directly into decoder tokens per GOAL.md §4); surviving-arm decision receipted per §4.4; governed-run controls armed (checkpoint cadence, commit-margin governor, segment gates every T-16 steps); data-stream law in force.

**Exit (state MULTIMODAL):**
- R3-E1: unbroken hash-chained checkpoint sequence; mid-run restart reproduces the recorded trajectory within F-05.
- R3-E2: image and audio spans in the training mix, receipted per-modality token counts.
- R3-E3: modality probes above floors — DEFERRED-AMENDMENT D-01, **with pre-committed backstop (E-G):** each modality probe above chance with a one-sided lower confidence bound at level T-24 (mirrors R2-E4); the D-01 settlement may only TIGHTEN from this backstop. (Probe suites are built and frozen by a superseding version before R3 dispatch; never mid-rung.)
- R3-E4: no cross-modality regression — text capability within F-06 of its R2 exit level.
- R3-E5: sustained matched-control continuation for surviving arms at equal budget; this is the mandatory confirmation for any R2-era A3-superiority claim and for any R2-era F2 firing.
- R3-E6: third frontier receipt + closing receipts.

**Kill:** R2 set, plus: segment-gate failure (any T-16-step segment outside continuation bands); cross-modality regression beyond the kill band (F-07); checkpoint-chain break (a gap in the hash chain is a stopped run, not a patched one).

### R4 — ADMITTED-100k (birth-cert evidence assembly, T-17 steps)

**Entry:** R3 green + closing receipts; full frozen eval suite staged under custody rules (conserved-benchmark resolver; no missing result is converted into completion); R4 kill table frozen; segment gates every T-18 steps.

**Exit (state ADMITTED-eligible; the birth-cert bundle):**
- R4-E1: full capability vector (§6) on the frozen held-out suite, bound to exact checkpoint bytes — thresholds DEFERRED-AMENDMENT D-02, **with pre-committed backstop (E-G):** every suite metric above chance with a one-sided lower confidence bound at level T-24 AND no suite metric below its R3-exit level beyond the signal band; the D-02 settlement may only TIGHTEN from this backstop. (Frozen by superseding version once suite custody is staged, before R4 dispatch.)
- R4-E2: all five native capabilities exercised and evidenced: text, image, audio, reasoning, structured tool use (GOAL.md `model_birth.required_native_capabilities`).
- R4-E3: reasoning evidence on the required axes (multi-step, compositional, counterfactual, causal, action-coherence, component-deletion) on frozen unseen tasks, no forbidden substitutes.
- R4-E4: D-gate + P-gate at full scale (gains disappear under artifact deletion; persist across restart).
- R4-E5: final matched-control delta — **(E-B) adjudicated at MATCHED CUMULATIVE CHARGED BUDGET:** the control arm's final checkpoint is compared against A3's OWN checkpoint at the control's cumulative charged budget point (the unbroken hash-chained checkpoint sequence supplies it); required positive delta beyond the credit band (F-08). T-19 floors the control's continuation budget for trajectory evidence only; it is never the credit denominator — an A3 "win" over a budget-starved control is not creditable.
- R4-E6: complete closed-boundary lineage receipt — the whole ladder INCLUDING failed runs, aborted segments, all arms, all eval and test-time compute.
- R4-E7: closing receipts.

**Kill:** R3 set at R4 scale, plus segment gates; a fired unadjudicated falsifier blocks continuation past the current segment.

### R5 — birth claim (adjudication event, not a step count)

Submission of the R4 bundle through the admission contract and board. Every receipt carries the INVARIANT hash stamp (F3) and predecessor-hash chain (F4). Confirmation-run bar: any result outside its predicted band in the favorable direction, or any acceleration claim, earns zero funding or claim weight until an independent confirmation run (fresh seed, same frozen config, tolerance F-09, sigma source per §2 `sigma_credit`) reproduces it. Breakpoint test for any frontier-bend claim: slopes fitted before/after the claimed break with the frozen estimator F-10; the break must survive held-out continuation steps recorded AFTER the claim is filed, or it is a trend, not a bend. A rejected bundle returns to R4 with a pivot receipt; it does not un-earn R1–R3 states.

## 4. Physiology arms and constraints

### 4.1 Arms

| Arm | Config | Total | Active/episode-trainable | Role |
|---|---|---|---|---|
| A1 dense | Owned unified dense decoder; training-state mechanism per §4-A1 | ≈3.84B (matched) | ≈3.84B | Modularity null hypothesis |
| A2 homogeneous-MoE | Same decoder, undifferentiated expert banks, episode-granularity learned gating (§4-A2) | ≈3.84B (matched) | ≈1.02B (matched to A3, receipt-enforced) | Load-bearing control: matches A3 on total AND active capacity |
| A3 role-prior | The EMBER-02 candidate: shared core + differentiated expert banks, task-level routing (GOAL.md §4) | 3.839B | 1.021B | The constitutional hypothesis |

**Measured-match declaration:** the capacity match is declared over total parameters, episode-trainable parameters (router/gate parameters INCLUDED), and MEASURED active FLOPs per token, receipted at R1-scale smoke per arm before R2 funds it — this per-arm R1-scale smoke measurement is also each arm's own T-22/T-23 efficiency baseline (E-F). Each arm's full loss function — including any auxiliary routing/load-balance terms and coefficients — is frozen in the threshold JSON's arm-config block reference before R2 dispatch; an objective term present in one arm and absent in another is a mandatory receipt-level disclosed mismatch. Eval-time routing per arm is frozen with the harness (matched test-time compute).

**The experimental variable is a PACKAGE:** the A2-vs-A3 variable is the differentiation+task-routing package, not either component alone. No receipt or publication attributes an A3 win to the role prior in isolation or to routing granularity in isolation without a further pre-registered component ablation. Pre-registered tie interpretation: A2 matching A3 at matched capacity and budget — including by emergent specialization in A2's learned gating — is evidence AGAINST the marginal value of the predefined role prior and fires F1's pivot consequence; emergent specialization in the control is a result, not a control defect.

### §4-A2 — A2 episode-granularity gating (residency-enforcing constraint)

A2's routing operates at episode granularity: at episode start a learned gate selects an expert subset whose parameter count matches A3's episode-active set within T-11; only that subset (plus shared core and gate) receives gradient or optimizer state during the episode. Rationale: under token-level learned top-k routing, per-step gradient support spans potentially all experts, requiring optimizer state approaching the full ~3.84B — the ~61 GB full-state wall of the residency table below. Every funded A2 step is covered by (i) the residency receipt and (ii) the gradient-support receipt (R2-E8). A mismatch is an entry-gate failure for the arm.

**Residency arithmetic (24 GiB):** mixed-precision AdamW ~16 B/param caps full-state training at ≈1.6B params; 3.84B full-state ≈61 GB does not fit; 7 B/param compressed state ≈26.9 GB does not fit; 5 B/param with gradient release ≈19.2 GB is marginal before activations. A2/A3 at ~1.02B episode-trainable (~7.7 GB BF16 weights + ~14 GB active-subset optimizer/grad state) are tight-but-feasible under the episode-granularity constraint. Every arm lands a residency receipt before its first funded step.

### §4-A1 — A1 training-state mechanism (two-tier rule + discriminating check)

The dense null A1 carries: "full-parameter dense training as achievable on this boundary." Guarded against two corruptions — algorithmic handicap (weaker optimizer → strawman) and starvation handicap (mechanism so slow the equal-budget arm is vestigial):

- **Tier 1 (default): full-state AdamW with CPU offload of optimizer state.** Identical optimizer math to A2/A3; the offload wall-clock/energy tax is charged to the ledger as boundary truth.
- **Tier 2 (fallback): owned Q-GaLore-class projected-gradient state, on-GPU.** Admitted only if Tier 1 fails the liveness leg, and only after passing the parity leg. (Published ideas are admissible research inputs; the implementation is owned — GOAL.md §6.)
- **Discriminating check (receipted at R1 scale, R1-E8):**
  1. *Liveness leg:* measure Tier 1 tokens/s and proxy-joules/token; A1's equal-budget R2 token count must be ≥ T-08 × A3's. Below floor → Tier 1 rejected, fall to Tier 2.
  2. *Parity leg:* run the candidate mechanism and offloaded full-state AdamW on the SAME model, same frozen data stream, same seed, for T-09 matched steps (offload always fits at some speed, so the true-AdamW reference is always producible). The mechanism's per-step loss trajectory and gradient-norm statistics must stay within F-11 of the reference. Inside band → the mechanism changes A1's COST, not its per-step capability. Outside → it may not carry the null.
- **Both tiers fail →** A1 is re-scoped by superseding version as a disclosed LOWER-BOUND-ONLY reference arm ("dense as best-achievable on this boundary"), banned from being cited as a beaten null.
- **Honest-null receipt language (frozen):** "A1 instantiates the dense null as 'full-parameter dense training as achievable on this boundary, mechanism M, parity and liveness receipts attached.' Any A3-vs-A1 claim quotes the mechanism and its check receipts. An A1 arm whose checks failed cannot be the null in any capability-credit claim."

**A1 honest limit:** A1 cannot match active capacity (an active-matched ~1B dense control would be a forbidden sub-3B network). The A1 comparison runs at matched TOTAL capacity and equal charged budget, active-capacity mismatch disclosed on every receipt.

### 4.3 Precision localization micro-arms

Micro-arms at R1/R2 scale test precision partitions: (a) BF16 baseline; (b) float32 router / BF16 body; (c) low-bit expert weights with higher-precision router/control/normalization/accumulation. Each accounts TOTAL training-state memory, not only served weights (low-bit forward weights coexist with higher-precision latent/training state). Adjudication bands: each partition's loss trajectory vs the BF16 baseline within the signal band = EQUIVALENT; beyond kill band worse = REJECTED; better beyond signal band = CANDIDATE (confirmation-run bar applies). The verdict selects the partition frozen into R3/R4. Falsifier F6: divergence, calibration loss, expert churn, or no net energy gain once master state is counted. Micro-arms abort independently.

### 4.4 Arms per rung

| Rung | Arms funded | Comparison receipted |
|---|---|---|
| R1 | A3 + micro-arms + A1 discriminating-check segments | None (canary + measurement baselines) |
| R2 | A1, A2, A3 at equal budget | Three-arm matched comparison on cheap probes; F1–F4 probed first here — R2 can kill, never credit |
| R3 | A3 + A2 (control); A1 parks unless it wins R2 outright (beyond the signal band on the frozen battery) | Sustained matched delta; mandatory confirmations for R2-era claims |
| R4 | A3 + A2 checkpointed-control at continuation budget ratio ≥ T-19 (disclosed, pre-registered, never post-hoc; **(E-B)** the ratio floors trajectory evidence only — final credit is adjudicated at matched cumulative charged budget per R4-E5/F-08) | Final birth-cert matched delta |

### 4.5 Falsifier table (receipt-checkable; firing forces a pivot receipt)

| ID | Failure mode | Against | Probed | Decisive predicate |
|---|---|---|---|---|
| F1 | Wrong role ontology | A3 | R2; R3 re-check MANDATORY before any A3-superiority credit; R4 | A3 fails to beat A2 beyond the signal band at matched capacity/budget; learned routing consistently bypasses role interfaces. A2 tying A3 by emergent specialization is F1-supporting evidence against the prior's marginal value |
| F2 | Interface bottleneck | A3 | R2/R3 — regime-qualified | A1 (or shared paths) transfers better at equal budget; inter-role communication dominates runtime. An R2-only firing constrains continuation (pivot receipt) but the CONCLUSION requires R3 sustained-regime confirmation (dense is typically stronger per-FLOP in the earliest regime) |
| F3 | Router collapse | A2, A3 | R2 onward | Utilization entropy below T-13 floor; load-balance loss rising; inactive roles never acquire competence |
| F4 | Duplicate cognition | A2, A3 | R2/R3 | High representational redundancy without robustness or efficiency gain |
| F5 | Credit-assignment failure | A2, A3 | R3 | Learning stalls; verifier attribution unstable |
| F6 | Low-bit instability | micro-arms | R1/R2 | §4.3 falsifier |
| F7 | Tool illusion | any capability claim | R4 + any claim | Model-only deletion ablation removes the claimed capability |
| F8 | Memory illusion | any durable-gain claim | every rung | Gain vanishes after restart (P-gate) or survives artifact deletion (D-gate) |
| F9 | Growth without function | any accretion event | if growth fires | Equal-budget dense/fixed-sparse control matches the grown system; active cost rises with no durable gain |
| F10 | Benchmark gaming | all | R2 onward | Performance fails on frozen variants, counterfactuals, or independently sourced tasks |

**Effective-capacity block + CAPACITY-CONFOUNDED class:** every arm-comparison receipt carries per-arm per-expert token histograms and utilization entropy. A rung where any compared arm breaches its utilization bounds yields a comparison flagged CAPACITY-CONFOUNDED — usable for kill decisions, never for credit, and inadmissible as a §5.4 advantage leg (a collapsed arm's effective active capacity has diverged from the nominal match).

Falsifier consequences follow GOAL.md §8: a fired row constrains the tested regime and forces the pre-registered action; it never deletes a mechanism family or forces a named successor; only the operator reduces scope. Negative results are published, not silently retired.

## 5. Closed-boundary receipt contract

### 5.1 Ledger field classes (every rung receipt)

1. Learned-import attestation: zero imported learned weights, embeddings, learned-parameter tokenizers, teacher outputs, learned filters/judges, hidden accelerator services (INVARIANT.md clause 3, fail-closed on unknown provenance).
2. Fixed-prior manifest reference (§5.2).
3. Human interventions: every intervention changing data, curriculum, stopping, selection, reward, routing, evaluation, or publication — actor role + timestamp.
4. Data accounting: bytes acquired, sources, dedup/curation ops, repetitions, synthetic ancestry as a provenance graph (never counted as new information), retained originals.
5. Host accounting: CPU/GPU/RAM/storage/network utilization; offload bytes (A1's offload traffic and time charged here as boundary truth, not footnoted); checkpoint and failure overhead.
6. Energy: the §5.3 proxy block.
7. All-compute coverage: training, validation, tools, environments, judging, search, retrieval, rollouts, test-time reasoning, final evaluation — INCLUDING failed runs, aborted segments, restarts.
8. Walls checklist: the 12-bottleneck protocol rows, each green/red/not-probed for the rung.
9. Identity spine: goal_id, workstream_id, next_executed_outcome, checkpoint hashes, config/tokenizer/optimizer hashes, cursor, INVARIANT hash stamp (F3), predecessor-receipt hash (F4).

### 5.2 Fixed-prior manifest

One versioned manifest, committed before R1, referenced by hash from every receipt: all non-learned priors — training loop, kernels, ember-cli, deterministic tools, corpora + acquisition provenance, benchmark payloads, solver/compiler versions, configuration — each with sha256 and provenance line. The energy method's exact CPU package counter, sampling cadence, idle-baseline procedure, and the host governor floor are pinned in this manifest. Deterministic tools comply with the criterion-receipted-before-first-use rule.

### 5.3 Energy block — DEGRADED_PROXY is the PERMANENT declared boundary

By operator ruling: no AC wall meter will be purchased. DEGRADED_PROXY is the program's permanent declared energy boundary; the `upgrade_path` field stays schema-defined but the upgrade is UNPLANNED — no rung, claim, or publication conditions on it. Receipts and publications state the proxy boundary plainly as the declared boundary, never as a gap-to-fix. A proxy point is never presented as a wall-metered point.

```json
"energy": {
  "energy_boundary": "DEGRADED_PROXY",
  "method": {
    "gpu": "NVML power sampling, integrated over run",
    "cpu": "CPU package power counter (exact counter named in fixed-prior manifest)",
    "sample_hz": "<pinned in fixed-prior manifest>"
  },
  "gpu_joules": 0.0,
  "cpu_pkg_joules": 0.0,
  "total_proxy_joules": 0.0,
  "idle_baseline": { "gpu_w": 0.0, "cpu_pkg_w": 0.0, "measured_interval_s": 0 },
  "sample_coverage_fraction": 0.0,
  "excluded_components": ["RAM", "storage", "network", "motherboard", "cooling", "PSU conversion losses"],
  "uncertainty": { "stated_bound_pct": null, "basis": "<disclosed estimation method>" },
  "upgrade_path": "AC_WALL_METERED"
}
```

Sample coverage ≥ T-06 or the run is killed (an unmetered run is not a frontier point). Energy is a measured integral, never a TDP multiplication.

### 5.4 Admissible frontier point

A rung receipt is an admissible closed-boundary frontier point iff: (1) ledger complete, failed work included; (2) fixed-prior manifest hash-verified + learned-import attestation; (3) capability leg — frozen held-out eval bound to exact checkpoint bytes, no harness/tool substitution (F7 probed by model-only ablation); (4) time leg — whole-run wall-clock including host-side and serial work; (5) energy leg — integrated proxy, coverage ≥ T-06, boundary flag disclosed; (6) reproducibility — config, seeds, data cursor, recipe pinned (reproduces or names its mismatch); (7) any advantage claim carries the matched-control delta legs and, if durable, D/P-gate evidence — a CAPACITY-CONFOUNDED comparison cannot serve this leg; (8) INVARIANT stamps F3 + F4. Under the strict boundary the audited public Pareto set is unpopulated; R1's receipt is positioned to be the first admissible public point, and the ladder publishes a frontier trajectory. The denominator is published as rigorously as the numerator.

## 6. Capability vector, benchmark set, and scalarization

- **Capability vector:** C = (reasoning, knowledge, code, agentic execution, multimodal grounding, calibration, transfer, retention), instantiated on the frozen suites below plus per-rung probe batteries; reported as Pareto points against the closed-boundary denominators (per proxy-joule, wall-second, active FLOP, unique token).
- **FROZEN_GENERAL_SUITE:** MMLU-Pro, GSM8K, MATH-500, ARC-Challenge, HumanEval+, MBPP, HellaSwag, GPQA-Diamond — as available under custody rules.
- **Conserved mandate set (GOAL.md §11 / CONTINUITY.md resolver):** the ten-name operator mandate verbatim (SWE-Bench Pro, FrontierCode Diamond, GDPval-AA, GDPpdf, Blueprint-Bench 2, AutomationBench, OSWorld-Verified, Legal Agent Benchmark, Humanity's Last Exam, Terminal-Bench 2.1) plus ARC-AGI 1/2/3 — 13 recovered names — plus the registry's **2 permanently-open `UNRECOVERED_PLACEHOLDER` slots** (`unresolved-direct-01`/`02`), pending operator restatement. No synthetic names, no silent narrowing to 13. These are durable obligations attached to the first admissible model; this freeze binds which suites gate which rung (cheap probes at R2, modality probes at R3 per D-01, full suite at R4 per D-02) and carries the placeholder slots as explicitly open.
- **Eval harness freeze:** tasks, judges (deterministic external verification preferred), context limits, tool access, output budgets, retry policy, contamination checks, per-arm eval-time routing. **(E-C)** Per-benchmark `sigma_eval` computation (bootstrap or exact binomial SE, per §2) is receipted with each frozen eval.
- **Scalarization: NONE.** Declared before any result exists: no scalar "intelligence-efficiency" number will ever be used; Pareto-vector reporting only. (Scalarization is admissible only with weights declared before results; declaring NONE is the strictest admissible position.)

## 7. Comparator registry

GLM-5.2, Kimi K3, DeepSeek-V4-Flash, and Inkling are capability and systems-engineering TARGET ENVELOPES: never plotted on Ember's closed-boundary frontier, never presented as one-GPU creation evidence; their data acquisition, fleets, teachers, post-training, and evaluation compute are not charged to any local boundary. Registry rows (dated 2026-08-01, provider-reported, with mandatory mismatch disclosures) live in the annex; mechanics: rows append-only with re-audit on citation — a row older than its last audit is quoted with that date, never silently refreshed. A matched comparison against ANY envelope requires freezing harness, tools, judge, context, output length, effort, retries, sandbox resources, timeout, and complete test-time energy; until then a row supports "target envelope" statements only. Borrowed models used locally occupy explicit frozen reference seats and contribute zero lineage signal.

## 8. Frozen threshold table (the single normative statement of every number)

The companion JSON (`ember02-preregistration-thresholds-v1.json`) is generated from this table and must agree exactly.

**Numeric freezes (frozen_form: number):**

| ID | Value | Meaning |
|---|---|---|
| T-01 | 100 | R1 step count |
| T-02 | 10 | R1-E2 first-window steps |
| T-03 | 10 | R1-E2 final-window steps |
| T-04 | 2.0 | R1 divergence kill: loss multiple of initial loss |
| T-05 | 10 | R1 divergence kill: sustained steps |
| T-06 | 0.95 | Minimum energy-logger sample coverage (all rungs) |
| T-07 | 2 | Minimum seed replicas for sigma_seed (R1-E7) |
| T-08 | 0.33 | A1 liveness floor: A1 equal-budget tokens ÷ A3 tokens |
| T-09 | 100 | A1 parity-leg matched steps |
| T-10 | 1000 | R2 step count |
| T-11 | 0.02 | Gradient-support tolerance (±, vs A3) |
| T-12 | 100 | Gradient-support breach kill window (steps) |
| T-13 | 0.50 | Router-entropy floor as fraction of maximum entropy |
| T-14 | 100 | Router-collapse sustain window (steps) |
| T-15 | 10000 | R3 step count |
| T-16 | 1000 | R3 segment-gate size (steps) |
| T-17 | 100000 | R4 step count |
| T-18 | 10000 | R4 segment-gate size (steps) |
| T-19 | 0.33 | **(E-B)** R4 control-arm continuation-budget floor for TRAJECTORY EVIDENCE ONLY (disclosed on receipt); never the credit denominator — final credit adjudicates at matched cumulative charged budget (F-08). Direction: raise = tighter |
| T-20 | 2 | Signal-band multiplier (× sigma). **(E-D)** AMENDMENT-FROZEN: consumed on both credit and tolerance sides, so no unambiguous tighten direction exists; value immutable; any change = operator scope decision |
| T-21 | 6 | Kill-band multiplier (× sigma; = 3 × signal band). Direction: lower = tighter |
| T-22 | 0.90 | **(E-F)** R2 efficiency floor: tokens/s as fraction of the arm's OWN R1-scale measured value. Direction: raise = tighter |
| T-23 | 1.10 | **(E-F)** R2 efficiency ceiling: proxy-joules/token as multiple of the arm's OWN R1-scale measured value. Direction: lower = tighter |
| T-24 | 0.95 | Probe confidence level (one-sided lower bound vs chance); also the D-01/D-02 backstop level (E-G). Direction: raise = tighter |

**Formula freezes (frozen_form: formula — become numbers mechanically when the named receipts land; substitution is receipted, not an amendment):**

| ID | Formula | Consumed by |
|---|---|---|
| F-01 | `peak_reserved_vram_bytes <= residency_receipt.declared_peak_bytes` (per arm) | R1+ kill |
| F-02 | **(E-A)** `abs(loss(t) - powerlaw_fit_R1(t)) <= T-20 * sigma_seed(loss) * sqrt(t / T-01)`, fit frozen as least-squares power law over R1 steps 20..100 — the band widens with extrapolation horizon, the frozen estimator's own uncertainty growth. Breach with all kill predicates green adjudicates FORECAST-MISS (anomaly + failure-library + recalibration + pivot receipt before R3 funding), not hard rung-fail | R2-E1 |
| F-03 | NO-SIGNAL iff `abs(delta_m) <= T-20 * sigma_seed(m)`; F1 pivot iff `delta_m(A3 - A2) < -T-20 * sigma_seed(m)` on the frozen battery | R2-E3 |
| F-04 | Catastrophic kill iff `delta_m(arm - control) < -T-21 * sigma_seed(m)` | R2+ kill |
| F-05 | Post-restart per-step loss deviation `<= T-20 * sigma_seed(loss)` over a T-09-step window | R3-E1 |
| F-06 | Text retention: `R3_text_metric >= R2_exit_metric - T-20 * sigma_seed(m)` | R3-E4 |
| F-07 | Regression kill: `R3_text_metric < R2_exit_metric - T-21 * sigma_seed(m)` | R3 kill |
| F-08 | **(E-B, E-C)** Final credit: `delta_m(A3@B_ctrl - control@B_ctrl) > +T-20 * sigma_credit(m)` on the frozen suite, where `B_ctrl` = the control's cumulative charged budget and `A3@B_ctrl` = A3's own hash-chained checkpoint at that budget point; `sigma_credit(m) = max(sigma_seed(m) where R1-E7 covers m, sigma_eval(m))` per §2 | R4-E5 |
| F-09 | **(E-C)** Confirmation-run tolerance: reproduced metric within `T-20 * sigma_credit(m)` of the claimed value (fresh seed, same frozen config; sigma_credit per §2) | R5 |
| F-10 | Breakpoint estimator: two-segment least-squares slope fit in log-capability vs log-cumulative-proxy-joules; break admitted only if the post-break slope holds over >= one full held-out segment (T-18 steps) recorded after the claim | R5 |
| F-11 | **(E-E)** Parity band: `mean_t abs(loss_mech(t) - loss_ref(t)) <= T-20 * sigma_seed(loss)` AND `abs(grad_norm_ratio - 1) <= T-20 * sigma_seed(grad_norm_ratio)`, over T-09 matched steps, same model/data/seed, ref = CPU-offloaded full-state AdamW | R1-E8 |

**Deferred amendments (frozen_form: deferred_amendment — settable only by a superseding version BEFORE the consuming rung dispatches; may only TIGHTEN from the pre-committed backstop):**

| ID | What | Backstop (E-G, binding until settlement) | Why deferred |
|---|---|---|---|
| D-01 | R3 modality-probe floors | Each modality probe above chance, one-sided lower confidence bound at T-24 | Probe suites do not exist yet; built and frozen before R3 dispatch |
| D-02 | R4 capability-vector thresholds | Every suite metric above chance at T-24 AND no metric below its R3-exit level beyond the signal band | Full-suite custody staging incomplete; frozen before R4 dispatch |

**Manifest-pinned (frozen_form: manifest_pinned — physical measurement-method constants, pinned in the fixed-prior manifest at its commit, immutable thereafter):** energy `sample_hz`; idle-baseline `measured_interval_s`; CPU package counter identity; host governor free-commit floor.

## 9. Change control (tighten-only)

1. This freeze binds at rung-1 dispatch.
2. Amendments only as NEW versioned superseding documents; the prior version is never edited (append-only discipline).
3. Amendments take effect only BETWEEN rungs — never mid-rung, never retroactively on a fired rung's adjudication.
4. Every amendment names what changed, why, and the triggering receipt (pivot receipt, fired falsifier, or operator directive).
5. Thresholds may TIGHTEN between rungs by amendment; any LOOSENING of a threshold, kill criterion, or falsifier is a scope reduction requiring the operator's explicit authority. **(E-D)** T-20 is additionally AMENDMENT-FROZEN: it has no unambiguous tighten direction (credit-side and tolerance-side consumers pull opposite ways), so its value may not change by ordinary amendment at all; any change is an operator scope decision.
6. Fired predicates adjudicate against the version in force at rung dispatch.
7. The A1 LOWER-BOUND-ONLY re-scope (§4-A1) is a named amendment path: fires only on both discriminating-check legs failing; disclosed as an arm re-scope; loosens nothing.
8. D-01/D-02 settlement and F-formula numeric substitution are the only value-entering events; neither may weaken any predicate already frozen, and D-01/D-02 may only tighten from their §8 backstops (E-G).
