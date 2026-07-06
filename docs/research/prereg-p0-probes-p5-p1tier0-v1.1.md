# PRE-REGISTRATION v1.1 (FROZEN 2026-07-06): P0 probes P5 + P1-tier-0 + muP audit

Source: docs/research/p0-composition-law-panel-20260706.md (panel synthesis, #207).
v1.1 note: v1 was adversarially reviewed BEFORE first execution (Fable verdict leg,
2026-07-06 — 15 amendments: operational definitions pinned, LR/state-provenance confounds
closed, assertion semantics repaired, verdict bands made coherent, cell count corrected).
Pre-execution amendment lands clean per the freeze rule below; nothing has run against v1.
Freeze rule: this spec is frozen at v1.1. Any change after first execution = v1.x with a
dated deviation entry here AND in docs/deviations.md. Silent iteration voids receipts.
Zombie rule (binding on both probes): loss/trajectory bands alone certify NOTHING here;
mechanism metrics are co-primary. A run whose engagement assertions did not fire writes NO
metrics artifact (fail-closed, #216) — it writes a FAILED-ENGAGEMENT receipt.

## PROBE P5 — ratio-invariance + commutation audit (instrumentation-only, ~0 GPU-h)

GOAL: measure whether the dimensionless mechanism ratios are ladder-invariant by default, and
whether the grow pushforward approximately commutes with the update map. No training; forward
+ backward + optimizer-step-in-copy per measurement point.

INPUTS (runtime-discovered, fail-closed if absent): the three receipted checkpoints —
368M QAT, 718M D6-segment, 1.22B rung-1 (paths resolved from their receipts at execution
time; the receipt file consulted is itself recorded in the artifact). One frozen probe
batch: 16 microbatches × 1024 tokens, fixed seed 20260706, saved to disk before any
measurement, sha256 in artifact.

STATE + LR PINS (confound guards — verdict-critical):
- Optimizer-state provenance MUST be identical in kind across the three checkpoints
  (warm-loaded from the checkpoint's own saved state in all three, or — only if a checkpoint
  carries no state — the probe records PROVENANCE-MISMATCH and the affected ratios are
  UNRESOLVED, never compared cross-width). Runtime-read the production reset flag
  (optimizer_reset_on_resume) and stamp it (closes tick-2 ledger item 6).
- The in-copy update is computed TWICE: at the checkpoint's own LR and at pinned unit LR
  (lr=1.0, all else identical). ALL cross-width ρ_SR verdicts are taken on the UNIT-LR
  series; the checkpoint-LR series is reported alongside. Assertion stamps LR, schedule
  position, and tokens-seen per checkpoint.

MEASUREMENTS per checkpoint (per tensor class: attention / FF / embedding separately):
- ρ_SR, per-block: for each quantized weight block b, ‖update_b‖_RMS / Δ_b where Δ_b is that
  block's grid step read from the LIVE quantizer object (never config). Reduce: median over
  blocks → per-tensor; median over tensors → per-class. Stamp grid granularity
  (per-tensor / per-channel / per-block + block size) — granularity itself is a pin.
- ρ_noise = ε/Δ with ε = the net2net noise magnitude the production grow path would inject
  (read from live grow code; if data-dependent, record the empirical distribution on this
  checkpoint). Δ = the same per-block reduction as ρ_SR.
- ρ_rank = r/width and ρ_grow = w_parent/r per projected tensor (r from live projector if
  projection enabled; else recorded N/A — an N/A is a finding, not a gap).
- ρ_spec, exactly: at the grow event (1.22B rung-1 pre-grow state only),
  ρ_spec = ‖M − P_dup(M)‖₂ / σ_max(M), where M = momentum matrix and P_dup = the
  symmetrization projector over duplicated column pairs. At non-grow checkpoints:
  N/A-by-construction (recorded). If production resets state at grow (runtime flag above):
  recorded N/A-with-reason (production-reset) — that N/A is itself a law-relevant finding.
- ρ_batch, one formula: B_simple = tr(Σ_g)/‖ḡ‖² via Welford over the 16 microbatches;
  ρ_batch = (batch_size × (1−β)⁻¹) / B_simple with β runtime-read from the live optimizer.
  Orientation: ρ_batch matched across widths = admissibility precondition for Muon-bearing
  cells; the scalar and both factors are all recorded.
- ρ_block = per-block min |fresh-state entry| / (absmax_block/(2^{bits−1}−1)) on optimizer
  state tensors (8-bit path only; N/A recorded otherwise).
- PINS read from live objects and stamped: quant location (fake vs resident), rounding mode,
  RNG stream architecture (generator object identities per tensor), optimizer split
  (Muon/AdamW tensor lists), NS iteration count + coefficients (runtime read-back — closes
  tick-2 MISTAGGED C4), optimizer-state provenance + reset flag (above).
COMMUTATION DEFECT at the rung-1 grow event (the receipted G):
  d_comm = ‖U_{k+1}(G(θ_k)) − G(U_k(θ_k))‖_RMS / ‖U_k(θ_k) − θ_k‖_RMS
  on the frozen batch, one step, in-copy, at the pre-grow checkpoint; U_{k+1} uses the
  PRODUCTION pushforward (whatever the runtime-read reset/carry flag says — pre-registered
  as production-as-found, stamped). Per-tensor-class + aggregate. This is a MEASUREMENT
  (baseline value of the law's central observable); no pass bar at v1.1.

PRE-REGISTERED PREDICTION (the headline): ρ_SR (unit-LR series) is NOT invariant — it
drifts monotonically with width across 368M → 718M → 1.22B under the default
absmax-referenced grid. Verdicts are PER-CLASS; the headline verdict = majority of classes;
mixed per-class outcomes (any class PROMOTE while any class KILL) ⇒ GRAY/UNRESOLVED overall
with the per-class table as the artifact.
- KILL per class (prediction dies): max/min ρ_SR across the three widths ≤ 1.2 (~±10%).
  Promote-the-null: drift REJECTED, law simplifies, re-parametrization descoped. GOOD outcome.
- PROMOTE per class: max/min ≥ 1.5 with monotone direction AND the across-width spread
  exceeds the within-checkpoint noise: the per-microbatch ρ_SR spread (16 replicates per
  checkpoint) must give a 95% band per width point that EXCLUDES the KILL band before a
  PROMOTE is valid.
- GRAY per class (1.2–1.5, non-monotone, or noise-band overlap): UNRESOLVED — extend to
  per-layer resolution before any claim; no third category invented post hoc.
- Any missing width point (OOM/wall-cap kill of one leg) ⇒ UNRESOLVED. Two-point "monotone"
  is meaningless and is pre-registered as non-evidence.
ENGAGEMENT ASSERTIONS (before artifact write): checkpoint sha recorded; Δ read from live
quantizer (assert grid object exists and quantizes a test tensor); update computed in-copy
(assert source state dict bitwise unchanged after probe); probe batch sha matches; LR /
schedule-position / tokens-seen / state-provenance stamped per checkpoint; all 7 ratios have
non-null values or explicit recorded N/A-with-reason.
BUDGET: CPU/GPU minutes; hard wall 60 min per checkpoint. GPU co-resident ≤2 GiB;
nvidia-smi preflight; serialize behind any running GPU job (one-job rule; this probe WAITS,
it never kills).

## PROBE P1 TIER-0 — A3-untie micro-cells (~0.5 GPU-h ceiling, co-resident ≤2 GiB)

GOAL: measure untie/absorb behavior of duplicated units under quantization × noise × RNG —
the A-cell signs from the tick-2 table, at ~25M scale.

DESIGN: base model ~25M params (4 layers, H=512), FIXED-SEED RANDOM INIT (seed 20260706),
ZERO pretraining — init procedure is pre-registered, not merely recorded. Batch geometry
pre-registered: batch 48 × seq 1024 (≈49k tokens/step × 200 steps ≈ the 10M-token slice).
Grown once at step 0 by duplicating the FF block width ×2 via the PRODUCTION net2net path
(engagement assertion: grow receipt fields present). Then 200 steps, same data order every
cell, enforced by assertion (below).

RNG ARCHITECTURE (one lever means one lever): three NAMED streams with fixed per-role seeds
— data-order (seed 1), ε-injection (seed 2), SR-rounding (seed 3 family). Assertion:
per-step batch content hash identical across ALL cells (data stream isolated from the ε and
SR levers by construction).
SHARED-vs-INDEPENDENT SR RNG, defined by REALIZED DRAWS, not object identity: "shared" =
corresponding entries of each duplicated pair receive IDENTICAL realized draws
(implementation: draw the parent block's mask once, replicate to the duplicate); step-0
assertion: realized draw tensors on duplicated pairs bitwise identical in shared cells,
differing in independent cells. Generator object ids additionally receipted.

CELLS = {quant regime} × {noise ε} × {RNG architecture}:
- quant ∈ {fp32-none (control), fake-quant-nearest 4bit, fake-quant-SR 4bit, SR-resident 4bit}
- ε ∈ {0, Δ/4, 2Δ}; Δ donor pinned = the fake-quant-nearest cell's step-0 per-tensor Δ
  (same absolute noise everywhere, including fp32 controls — THE control anchor)
- RNG ∈ {shared, independent} — applies to SR rounding draws only; for nearest and fp32
  cells the RNG axis collapses (structurally-N/A).
CELL COUNT (corrected at v1.1 — the dispatch note's "30" was an overcount): full grid
4×3×2 = 24 = 18 EXECUTABLE (SR-bearing: fq-SR and SR-resident × 3ε × 2RNG = 12; nearest × 3ε
= 3; fp32 × 3ε = 3 — the fp32 controls are INSIDE the 18) + 6 STRUCTURAL-N/A (the collapsed
RNG copies of nearest and fp32 cells). Exactly one lever differs between any cell and its
matched neighbor.
METRICS (co-primary, both required), steps {0,1,5,10,25,50,100,200}:
- tie-metric-exact: fraction of duplicated weight pairs bitwise identical — in the QUANTIZED
  VIEW for quant cells; in the MASTER representation for fp32 cells (defined per regime).
- tie-metric-cos: cosine similarity distribution of duplicated unit vectors in the MASTER
  representation, all regimes.
- loss curve recorded but explicitly NON-CERTIFYING (zombie rule).
PRE-REGISTERED SIGNS:
- A1 (fake-quant-nearest, ε<Δ/2 i.e. the Δ/4 cell): ties ABSORB — tie-metric-exact ≥ 0.99
  at step 200. KILL for A1 theory: < 0.9 at step 200 (offset-dependence larger than theory
  allows → back to theory).
- A2 (SR cells, ε=0, independent RNG): unties — tie-metric-exact ≤ 0.1 by step 50.
  FALSIFIABLE COROLLARY: same cell with SHARED draws stays tied (≥ 0.99 at step 50). If the
  shared-draw cell unties too, the decoherence attribution is WRONG (another asymmetry
  source exists) → flag, do not reinterpret.
- ε=2Δ cells: untie under ALL quant regimes (representable noise) — sanity anchor; failure =
  harness defect, not physics.
- fp32 controls: untie rate scales with ε; ε=0 fp32 stays bitwise tied (determinism check).
ENGAGEMENT ASSERTIONS (before artifact write, per cell) — REGIME-CONDITIONAL TABLE:
- all cells: grid-landing offsets of duplicated pairs recorded at step 0 (the
  offset-dependence data the tick-2 correction demands); named-stream seeds + generator ids
  receipted; per-step batch content hash matches the cross-cell reference; optimizer stepped
  AND the grown FF block specifically shows nonzero cumulative master-view update by step 5
  (global-delta-only is not sufficient — a dead grown block fakes A1);
- fake-quant cells (nearest + SR): assert quantized view ≠ master view somewhere;
- SR-resident cells: assert every master entry is grid-resident (master IS the quantized
  representation — the fake-quant assertion is structurally unsatisfiable here and is
  replaced, not waived);
- fp32 cells: quantizer assertions recorded N/A;
- ε>0 cells: assert master views differ by the expected ε at injection; shared/independent
  cells: the realized-draw assertion above.
BUDGET: ≤0.5 GPU-h total (18 cells × ~90s); co-resident ≤2 GiB; nvidia-smi preflight;
KILL-THEN-LAUNCH never applies (no competing job may be killed for this — it WAITS).
ARTIFACT: one JSON per cell (cell id, pins, assertions, metric series, verdict
UNTIED/TIED/GRAY vs pre-registered sign) + one summary MD with the 18-cell sign table vs
predictions. Failed assertions ⇒ FAILED-ENGAGEMENT receipt, no metrics artifact.

## muP BUILDER AUDIT (read-only, 0 GPU-h)

Read the production model-builder + optimizer construction code paths: record whether ANY
width-dependent scaling of init variance, per-layer LR, or attention temperature exists
(muP or otherwise). Output: a table (component | width-scaling found | file:line | class:
muP-complete / partial / absent). No conclusion beyond the table — the table feeds the
transfer-law gap analysis (tick-2 adversary: "no covering parametrization receipt").

## Execution order + ownership
1. muP audit (haiku lane, read-only) + P5 harness authorship (builder lane; CPU-first, GPU
   only for the 1.22B forward if needed, behind the standard interlock) — dispatchable now.
2. P1 tier-0 after P5's pins land (P5's live-object pin read informs P1's quantizer hookup);
   GPU window serialized behind expc1 live leg + any W2 leg.
3. Results → tick-4 synthesis; signs feed the certification protocol doc.
