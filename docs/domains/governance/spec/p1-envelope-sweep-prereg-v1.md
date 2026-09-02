# P1 envelope-sweep pre-registration v1 (2026-07-05)

Status: PRE-REGISTRATION, written before any sweep run fires. Governs the runs that take the P1
achieved envelope from 1 receipted point to the energy-law-theory-v1.md §7.2 floor (≥8 points
per arm at pinned ADM spanning ≥1 OoM in E, EXP fit + holdout + bootstrap/profile CIs).
Amendments after the first governed sweep run launches: dated, disclosed, never
threshold-relaxing. Public record: filed alongside issue #118 (program) — this doc freezes the
run-level protocol #118 items 2/5 reference.

## 1. Point inventory plan (8-point floor arithmetic)

| # | Source | E (rel. to W1-control budget E₀) | Status |
|---|---|---|---|
| 1 | W1 control (derived retrofit, banked) | 1.0× | RECEIPTED (triage) |
| 2 | Growth-arm pair of the same lineage (#123-governed run terminal) | ~1.0× | queued (GPU q. item 2) |
| 3–8 | This sweep: six from-scratch runs at c03 shape | 0.1×, 0.2×, 0.5×, 1.0×(replicate), 2.0×, 4.0× | THIS DOC |

Span check: 0.1×→4.0× = 1.6 OoM ≥ 1 OoM ✓ (§7.2). Point 6 (1.0× replicate, fresh seed) doubles
as the variance anchor for CI width and as the H-MLI null-control's second replicate (§4).

## 2. Frozen run protocol (every sweep point)

- **ADM pin**: c03 shape, pinned hardware (RTX 4090 sm89), corpus manifest sha via
  src/ember/governance/scripts/manifest_sha.py at launch, DECONTAMINATED held-out eval batch (the #115-cured
  builder's sha-pinned output; contamination_recheck=0 echoed in every receipt), governor 0.80 +
  margin assert + orphan sweep, one GPU job at a time.
- **LR-schedule matching rule (the §1 "LR-matched-to-budget" requirement, made concrete)**:
  cosine decay to 10% of peak over EXACTLY that run's token budget, with warmup = min(2% of
  budget, the c03 recipe's absolute warmup); peak LR identical across points. No mid-run
  schedule edits; a run that diverges is reported as a diverged point (kept in the table,
  excluded from fit only by the pre-stated rule: final loss > initial loss).
- **Scoring**: C = −L_val on the pinned held-out at the FINAL step of the budget (§1 envelope
  definition: separate scheduled runs, terminal capability at spent E — never mid-run
  checkpoints of one long run).
- **Instrumentation at birth**: full §6b fields (adm_fingerprint, c_functional_id=
  neg_val_loss_v1, e_gpu_hours measured wall, lever_class, claim_type=envelope-point) +
  joules.py sampling → power_qualifier="measured" on every point (#118 item 4 satisfied for the
  whole sweep, not one point).

## 3. Fit + verdict grammar (pre-stated, §7.2)

- Fit the EXP exponent form from energy-law-theory-v1 §4 on points 1–7; point 8 (4.0×) is the
  HOLDOUT — fit quality is judged by holdout residual, not in-sample R².
- Bootstrap CIs: resample points (leave-one-out + pairs bootstrap, 10k) for exponent CI;
  L∞-α correlation reported per §7.2.
- Verdict tokens: ENVELOPE-FIT-PASS (holdout |residual| within the bootstrap 95% band),
  ENVELOPE-FIT-FAIL (outside), ENVELOPE-UNDERPOWERED (any point diverged/missing → no fit
  claim). An honest FAIL is a terminal receipt; re-runs require a dated amendment.

## 4. H-MLI receipt #1 rides the sweep (marginal cost ≈ 1 run)

Null-control pair for lever L1 (torch.compile, trajectory-preserving candidate): points 4 (1.0×)
and 6 (1.0× replicate) ARE the two control replicates (seed-varied, matched shape/budget); one
additional lever arm run at 1.0× WITH L1 enabled completes the H-MLI trio. EMA smoothing
half-life 2000 steps, TOST equivalence margin k = 2× the control-pair SD, token-axis
precondition per energy-law-theory-v1 §3. Total sweep cost: 7 runs (6 sweep + 1 lever arm).

## 5. Budget + sequencing

E₀ = the W1 control's measured e_gpu_hours (0.067478 gpu-h — small pilot scale): the full sweep
at c03 ≈ 7 runs × ≤4×E₀ each ≈ well under one GPU-day — schedulable INSIDE gaps of the main GPU
queue (#53 order), never displacing W1-control/v3/C14 legs. Precondition: #115 cure landed +
decontaminated batch sha (same gate as everything else). Receipts home:
receipts/p1-envelope-sweep/<UTC>-point<k>.json + one fit receipt citing this doc by path+sha.
