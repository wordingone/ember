# Sleep-consolidation mechanism — spec v0 (#35)

Concretizes the KEEP-BURNING annex (SDEK three timescales) into triggers,
artifacts, and gates. Known failure modes stay named: catastrophic
forgetting + loss of plasticity under continual training (Dohare et al.,
Nature 2024). v0 principle: pay compute to sidestep forgetting
(retrain-from-base on the full ledger) until receipts justify anything
cheaper. Nothing in this spec launches; round preregs (e.g. docs/
r2-prereg.md) instantiate it.

## Timescale 1 — continuous (awake; no weights touched)

- **What:** ledger appends (verified episodes with frontier annotations),
  state-file transitions, posterior updates (per-task s/n), calibration
  elicitations. Cost ≈ 0; runs inside sampling/eval jobs already.
- **Trigger:** every event; no gate beyond V (+ ext-verify where covered).
- **Measurable AC:** ledger integrity receipts — kernel_replay-style
  cross-check (samples↔ledger↔receipt agreement) passes per round; the
  ledger is APPEND-ONLY (quarantine lives at build, never deletion — the
  eng-#21 rule is a T1 invariant).

## Timescale 2 — sleep consolidation (periodic; episodes → adapter)

- **Trigger (v0):** completion of a sampling round (Phase S of the round
  prereg). No wall-clock or growth-threshold triggers in v0 — rounds ARE
  the sleep events; round-1's 196.73 corrected bits produced a
  control-beating gain, so no bits floor gates the trigger either.
- **What burns:** fresh adapter trained FROM BASE on the FULL ext-clean
  ledger (all rounds pooled, bits-weighted caps). Retraining-from-base is
  the v0 anti-forgetting mechanism: the ledger is the replay buffer, and
  full replay sidesteps Dohare-class plasticity loss by construction.
- **Objective:** whatever the latest round verdict promoted (currently
  MTP-aux pending the r2 REPRODUCE/PARAM-ARTIFACT cell; plain SFT is
  receipted-flat and cannot be the consolidation objective again).
- **Gates (all receipts, per round):** G1 paired at the binding k (k=24
  from #29) vs base AND matched control; t5-class harm non-regression on
  the powered surface; deletion = adapter-unload floor check. Fail any →
  the adapter is NOT promoted to "current consolidated state"; the ledger
  keeps growing (T1 never blocks on T2 failure).
- **Cross-world rule:** once the ledger spans >1 world (HumanEval+
  admission, #46), per-world heldout deltas are computed separately and a
  replay-mix arm (world-proportional) joins the round arms; single-world
  pooling is receipted-dangerous (ARC seed → coding harm, t5 round-1).

## Timescale 3 — durable burn (rare; adapter → merged core)

- **Trigger (v0, conservative):** the SAME consolidation recipe passes its
  full T2 gate set in TWO CONSECUTIVE rounds (stability before
  durability). No schedule-based burns.
- **What burns:** merge_and_unload of the passing adapter into a new base
  checkpoint; the old base is retained on disk (rollback is a file move,
  never a retrain).
- **Gates:** full three-test on the MERGED core (held-out transfer vs the
  pre-merge base; matched control = the pre-merge base + adapter, which
  the merge must EQUAL within CI — merge-fidelity receipt; deletion =
  rollback to retained base reproduces the old floor); t5-class harm at
  the powered surface; next-round floor from the merged core ≥ floor from
  base+adapter (persistence-across-sessions made measurable).
- **Plasticity guard:** after a burn, the next round's frontier-stratum
  yield (bits/episode on dead/frontier cracks) is compared to the
  pre-burn round; a collapse in new-frontier yield = plasticity-loss
  signal → burns freeze, fp-class investigation issue minted.

## Ownership + enforcement hooks

T2/T3 gate chains are invariant-1 territory in docs/nck-spec-v0.md: the
promote path requires the gate receipts schema-validated; no transition
without a receipt (invariant 4). Round preregs cite this spec; deviations
go through the audit-§6 deviation registry.
