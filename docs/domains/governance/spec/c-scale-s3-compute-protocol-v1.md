# C-SCALE S3 compute protocol v1 — the five unproduced CHK fields, defined

Status: FROZEN v1 (maintainer spec authorship per #74; wall surfaced by the #73 gap report:
five of test_c_scale.py's fifteen contract fields have no producer anywhere in the tree, and
`docs/spec/c-scale-s2-token-bill-protocol.md` §1.2 scopes the 6ND FLOPs pair out of S2; doc
absent as of 2026-08-01 in this contract tree, unmerged to master).
Consumer contract is FROZEN: `src/ember/governance/scripts/ember_totality/test_c_scale.py` (zero probe edits) —
`capability_per_compute_ratio` must re-derive as projected/measured within 1%,
`contribution_deletion_collapses_excess` must be literally true, and
`active_working_set_bytes <= device_working_set_floor_bytes` with both positive ("governed fit,
no hardware escalation"; memory-fit ALONE stays insufficient —
`invalid_memory_fit_as_scale_affordability`).

## 1. FLOPs accounting (fields 1–3)

**Estimator, pinned for BOTH arms:** training FLOPs of a segment = `6 × N_active × T`, where
`N_active` = the dedup-aware unique parameter count actually training during that segment (from
the rung receipts' own `params_unique` fields — never nominal/duplicated counts) and `T` = that
segment's receipted training tokens (the same rows the W1 pricing leg aggregates). The 6N form
counts parameter FLOPs only; attention-FLOPs are EXCLUDED on both arms symmetrically (named
exclusion — estimator bias cancels in the ratio, which is the only quantity the probe checks).

- **measured_flops_to_capability** = Σ over every receipted grow-path segment of
  `6 × N_active(seg) × T(seg)`. This is where the grow path's real compute advantage lives,
  and why the FLOPs ratio is NOT the token ratio: early tokens are spent while the model is
  SMALL (seed pretraining at N₀ ≈ 0.6× the final width), so each early token costs fewer FLOPs
  than a dense-final token. The producer is pure receipt arithmetic (CPU-now), citing the same
  bill_aggregation_rows as `scratch/w1-control/w1-pricing-20260704T063236Z.json` plus each
  row's `params_unique` at that segment.
- **projected_dense_flops_to_capability** = `6 × N_final × T_dense`, where `T_dense` is the W1
  control arm's tokens-to-match. Fairness inherits W1's rules verbatim
  (`docs/spec/w1-token-collapse-control-v1.md` §2 — absent as of 2026-08-01 in this contract
  tree, unmerged to master: standard from-scratch schedule, never a
  hobbled control). Before the control run completes, this field is UNPRODUCIBLE — same
  outcome ladder as W1: L1 → measured T_dense; L2 → ceiling-valued T_dense with
  `lower_bound: true` carried into the ratio; L3 → the S3 FLOPs arm is REFUTED alongside W1
  and no compliant composite exists (lands as truth).
- **capability_per_compute_ratio** = projected / measured, emitted with numerator and
  denominator so the probe re-derives it. The probe requires the ratio to exceed 1 against the
  6ND dense projection; a ratio ≤ 1 is emitted anyway (gap report / refusal path in the #73
  assembler — never suppressed).

## 2. Deletion-collapse of the excess (field 4, C8 linkage)

The claim `contribution_deletion_collapses_excess: true` means: the capability bought above the
dense projection is BOUND to the grown structure — delete the growth, lose the gain.

**Ablation is well-defined because growth is receipted:** the rung receipts record the exact
net2net growth maps (which FF channels / heads / layers are new at each rung). The deletion arm
re-slices the grown checkpoint back to the pre-grow architecture along those recorded maps and
evaluates on the SAME sha-pinned capability batch as W1 (`function_preservation_check` idiom).

Pre-registered criteria (ALL required for `true`):
1. `ablated_loss ≥ pre_grow_terminal_loss` — deleting the grown delta surrenders at least
   everything gained since growth (the grown capacity is load-bearing, not padding).
2. **Random-ablation control:** deleting a RANDOM parameter subset of equal count (same
   layer-type distribution, seed recorded) must hurt strictly LESS than deleting the grown
   delta. This is the leg that attributes the collapse to the grown structure specifically —
   without it, criterion 1 is satisfiable by any model that merely dislikes being cut.
3. Both evals run with the identical code path/config as the capability point; receipts carry
   both losses, the growth-map citation, and the random seed.

CPU-feasible today at rung-1 scale (eval-only, 1.22B). The arm is honest in both directions:
a FAILED collapse (criterion 1 or 2 false) is emitted as a receipt and poisons the excess claim
— exactly the C8 deletion-collapse idiom the probe's GREEN line cites.

**v1.1 amendment (2026-07-04, from the first real run's honest negative):** the first execution
(receipt `c-scale-s3-deletion-arm-20260704T084922Z.json`) returned `false` and exposed a
CONFOUND in criterion 1 as frozen above: the ablated model inherits every post-grow gradient
step on its ORIGINAL weights, so it beats the pre-grow checkpoint even when the grown channels
carry nothing (measured: ablated 0.82 vs pre-grow 3.97 on real corpus after only 36 post-grow
steps — the comparison conflates "growth is load-bearing" with "no training happened since
growth"). Criterion 1 for all FUTURE runs is therefore: `ablated_loss ≥
matched_continuation_loss`, where matched-continuation = the pre-grow checkpoint trained the
SAME post-grow token budget with the SAME data/schedule but WITHOUT growth (a cheap in-window
run at rung-1 scale; its receipt is cited alongside). Criterion 2 (random-ablation control)
is unchanged and remains the attribution leg — note the first run also failed it in the
informative direction (random hurt MORE than targeted: at 36 stabilization steps the grown
channels are barely trained, exactly what "not yet load-bearing" predicts). The v1 receipt
stands as a valid honest negative under the criteria in force at its run time; the field
stays `false` until a run under v1.1 criteria passes. Batch reconciliation: when the real W1
control runs, its sha-pinned capability batch becomes the canonical eval batch for this arm
(the first run's documented synthetic-batch + real-corpus pair was the correct interim).

## 3. Governed working set (field 5)

- **active_working_set_bytes** = peak device memory actually touched during ONE governed
  serving forward pass at the operating configuration: resident weight bytes + peak activation
  bytes + KV bytes, measured (CUDA peak-allocated tracking around the pass), never computed
  from shapes alone.
- **device_working_set_floor_bytes** = the governor-capped device budget (the standing
  resource rail: cap fraction × device VRAM), cited from the governor config in force during
  the measurement — never the raw device total (that would be exactly the "hardware
  escalation" the probe forbids).
- Fit (`active ≤ floor`) is NECESSARY, never sufficient — the probe's
  `invalid_memory_fit_as_scale_affordability` token stays authoritative; this field only
  closes the loop that the OTHER fields' capability claims run inside the governed envelope.
- GPU-window leg, cheap (one instrumented forward pass piggybacking any resident-model block).

## 4. Producer + staging

One new producer, `src/ember/governance/scripts/ember_c_scale_s3_producer.py` (build target, issue #75):
`--flops` mode (CPU-now: receipt arithmetic for fields 1–3, honest UNPRODUCIBLE marker while
W1's T_dense is pending), `--deletion-arm` mode (CPU: re-slice + paired evals per §2),
`--working-set` mode (GPU window: instrumented pass per §3). Every mode emits its own receipt
under `receipts/ember-c-scale/`; the #73 assembler consumes them as the S3 field sources and
keeps gap-reporting any field still unproduced. Rails: no probe edits, no GOAL edits, receipts
born from execution, C(-1) declarations, sandbox under `scratch/c-scale-s3/`.

## 5. Dependency truth

S3's FLOPs pair completes WITH W1 (shares T_dense); the deletion arm is independent and
runnable today; the working-set leg is window-work. The apex condition's remaining walls after
this spec: owned >3e9 resident (rung ≥ 2 growth — owns both `operating_capability_point` and
W2's `no_borrowed_base`) and the W1/W2 real runs already scheduled. Nothing else about
C-SCALE is undefined.
