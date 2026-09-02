# C8 pre-registration v1 — primary class, falsifier, ablation, transfer (2026-07-05)

Status: PRE-REGISTRATION. This document is written BEFORE the real-scale run it governs. No
claim is made here; this file exists so that the eventual claim is falsifiable in the
conditions-v1.md C8 sense (registry lines 82–90) rather than post-hoc. Amendments after the
governed run launches must be dated, disclosed, and cannot relax thresholds.

## 1. Primary class (exactly ONE, per C8)

**Training protocol: criterion-gated, function-preserving, budget-matched depth growth
("earn-to-grow").** The candidate contribution is the PROTOCOL — grow the model only when a
receipted criterion licenses it (EARNED-FLOP gate per growth-v1.md §6; BOOTSTRAP_PASS
lineage per math-core §5 where the resident loop is the driver), with function preservation
verified at each growth event, under iso-FLOP accounting — not the growth operator itself
(G_stack composition is prior art, cited below) and not any single run's score.

## 2. Closest prior + claimed material difference (subject to §6 sweep)

- **G_stack / depth-stacking acceleration** (arXiv 2405.15319): establishes budget-matched
  stacking gains at 410M–7B on schedule-driven growth. Our v3 dry-run imports its iso-C framing
  directly (cgrow-experiment-design-20260628.md §5).
- **Net2Net** (arXiv 1511.05641): function-preserving operators; no budget-matched frontier
  claim, no gating criterion.
- **Claimed delta**: prior growth work grows on a SCHEDULE (token count / step count). The
  protocol under test grows on a RECEIPTED CRITERION (earned-FLOP / assimilation evidence),
  with the growth event admissible only when function preservation and budget accounting are
  simultaneously receipted — i.e., "when to grow" is decided by the system's own verified
  evidence, and the claim is that criterion-gated growth dominates schedule-driven growth (and
  scratch) at matched compute. If the §6 sweep surfaces prior art for criterion-gated growth
  with budget-matched evaluation, the delta narrows or the class is re-registered (dated).

**Prior-art sweep adjudication (dated 2026-07-05, pre-launch — §6 obligation DISCHARGED;
sweep log: historical pre-launch sweep log (not tracked at current head), 17 works, 8 axes):** criterion-TRIGGERED growth
is established prior art and is hereby named, not claimed: When-To-Grow/ORL (arXiv 2401.03104),
LAG (arXiv 2406.02469 — spot-verified: early-dynamics STRATEGY SELECTION, single-stage, no
function-preservation verification, no matched-compute framing), SECNN/NES (arXiv 2401.05686),
NORACL (arXiv 2604.27031), Firefly (arXiv 2102.08574), SMGrNN (arXiv 2512.12713). The §2 delta
is therefore SHARPENED (strengthening, not relaxing): the registered contribution is NOT
"growth triggered by a measured signal" — it is (i) the RECEIPTED admission gate (function
preservation + budget accounting simultaneously verified as the license for each growth event),
and (ii) the iso-FLOP three-way frontier comparison (criterion-gated vs schedule-driven vs
scratch), which no swept work runs. F2 is confirmed as the delta-killer arm. RULING:
DELTA-SURVIVES; the governed run is unblocked on this obligation. earn-to-grow is a statement about
the P2 growth-criterion object (the receipted criterion licensing capacity change, math-core §5
lineage) evaluated ON the P1 formal object (the achieved capability-energy envelope at pinned
ADM — an iso-FLOP comparison IS an envelope statement). F1/F2 test the envelope-displacement
claim; F3/F4 bind deletion and fidelity semantics. (Also filed as issue #123 comment, same day.)

## 3. Falsifier (hostile-runnable, pre-stated)

At the ≥0.8B rung (growth-v1.md §6 smallest admissible), paired arms at matched total FLOPs
(budget error ≤2%, the v3 dry-run standard), scored on eval loss over (a) the DECONTAMINATED
held-out batch (w2-scale-preregistration-v1.md §4 gate — contamination_recheck=0, sha-pinned)
and (b) external/disjoint benchmark rows (§5):

- **F1 (mechanism)**: warmstart-grown arm fails to beat scratch at iso-FLOP — eval-loss delta
  ≤ 0, or bootstrap 95% CI of the delta includes 0 → mechanism claim DEAD at this scale.
- **F2 (criterion)**: criterion-gated growth fails to beat schedule-driven growth at iso-FLOP
  (same operator, gate replaced by the schedule matched to equal growth-event count) → the
  PROTOCOL delta is dead even if F1 passes; the contribution collapses to prior art.
- **F3 (deletion, C8 CHK)**: deleting the contribution (running the recipe-less arm) fails to
  degrade the external/disjoint benchmark (§5) while plumbing stays intact → fails C8's
  deletion check regardless of F1/F2.
- **F4 (fidelity)**: growth events must use sequential composition (G_stack-proper) or receipt
  a measured connection-rate R_c; an interleaved-mode run without R_c is INADMISSIBLE under
  this pre-registration (the paper's own H.2: interleaved underperforms, R_c 30.4% vs 91.3%).

Verdict grammar: PASS requires F1 AND F2 AND F3 all surviving. Any single falsifier firing is
recorded as the verdict — no partial credit, no reframing in the terminal receipt.

## 4. Ablation design (deletion arms)

1. **A-scratch**: from-scratch at identical total FLOPs (deletes the whole recipe) — primary
   deletion arm; F1/F3 read from it.
2. **A-schedule**: same growth operator, criterion gate replaced by a token-schedule with the
   SAME number of growth events — isolates the criterion (F2).
S3's rung-1 deletion arm (c-scale-s3-deletion-arm-20260704T084922Z.json, honest FALSE) probed
contribution-deletion of a different object at a different scale; it is superseded FOR C8
PURPOSES by this design and remains standing evidence for its own C-SCALE field.

## 5. External/disjoint validation rows + transfer

- External benchmark: eval rows from a corpus family disjoint from the owned training shards
  (named + sha-pinned in the run config BEFORE launch; candidate: the held-out state_val
  families of the C14 battery are NOT admissible here — they are harness-internal; the rows
  must be external in provenance, not merely held out).
- Transfer beyond the scored instance: the protocol applied at a SECOND rung (different width/
  depth point) must reproduce the F1/F2 direction — one supporting receipt, pre-registered as
  directional (not magnitude-matched).

## 6. Prior-art sweep obligation (blocking)

Before the governed run launches: a literature sweep for criterion-gated / trigger-based
growth with budget-matched evaluation (search axes: "when to grow" NAS/growth triggers,
loss-plateau-triggered widening, MorphNet-class resource-gated growth, progressive stacking
schedulers). Every hit is logged with a one-line distinction-or-concession. A concession that
covers the §2 delta forces re-registration (dated amendment), not silent narrowing.

## 7. Convergence note (why this run is next on the GPU queue)

The SAME governed run serves: C8 mechanism arm (this doc), claims-evidence-map row 19
(earned growth), publication-gate conjunct (b), and P1 envelope point #2 (§6b-instrumented at
birth per issue #121's standard, joules-sampled). Receipt home:
receipts/cgrow-v3-real/<UTC>.json, one terminal receipt per arm + one comparison receipt
citing this file by path and sha.
