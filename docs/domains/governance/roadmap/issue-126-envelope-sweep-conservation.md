# Issue #126 energy-envelope sweep conservation

Status: `SUPERSEDED_NOT_PLANNED` becomes effective only after independent
exact-head review, green required checks, and merge of this carrier. This file
does not claim that the registered sweep ran.

Public-master basis: `aa569a9f53ce4caacd7f958a1f37c01a8c434e3f`.

## Accepted transfers

- Sole energy-envelope authority EMBER-02/#1116:
  https://github.com/wordingone/ember/issues/1116#issuecomment-5225437082
- EMBER-05/#1119 growth-arm consumer cross-link:
  https://github.com/wordingone/ember/issues/1119#issuecomment-5225437129
- Bidirectional #126 bridge:
  https://github.com/wordingone/ember/issues/126#issuecomment-5225439220

Both canonical owners remain OPEN. #1116 owns the envelope and measurement
contract; #1119 may supply or consume a growth-arm point without creating a
second energy authority.

## Historical record and current boundary

Issue #126 registered a W1/c03/C14-era dispatch surface for the P1 energy law.
The frozen source is `docs/domains/governance/spec/p1-envelope-sweep-prereg-v1.md` (Git blob
`23bf10cfe4ee2e2ab3c8b83f300dac6762dadd95`). The current tree contains only
`receipts/p1-envelope-sweep/20260708T144213Z-point3.json` (Git blob
`faf0968cd832b9e91fcf134bb2ee2d62fe26634b`), which identifies itself as issue
`#118`, point 3, `dry_run=false`. It is historical execution evidence for one
old-scale point, not an eight-point fit, current owned 3B result, or #126
completion.

Issue #118 is closed as `not_planned`. Its ruling
`docs/roadmap/issue-118-energy-law-conservation.md` (Git blob
`e527d17a7fc6eac711c5e5cafeddeffdd1fcb1f5`) and accepted #1116 transfer
https://github.com/wordingone/ember/issues/1116#issuecomment-5221234668 retire
the old W1/c03/C14 execution subjects while retaining the current 3B envelope,
H-MLI, raw-power, uncertainty, negative-result, and rollback obligations.

Only that duplicate historical dispatch vehicle retires. The scientific
contract below remains open under #1116, with #1119 as growth-arm consumer.

## Lossless surviving contract

1. **Eight-point arithmetic.** Preserve the historical inventory exactly:
   point 1 was the banked W1-control derived receipt; point 2 was the terminal
   growth-arm point of the #123-governed lineage; points 3-8 were six fresh c03
   runs at `0.1x`, `0.2x`, `0.5x`, `1.0x` replicate, `2.0x`, and `4.0x`
   historical `E0`, spanning 1.6 orders of magnitude. These identities are
   provenance, not admissible current-3B points. The current program requires
   at least eight governed points per arm and at least one order of magnitude
   on the first admissible current owned 3B lineage, with a newly measured
   current baseline rather than the W1 scalar.
2. **Dated non-relaxing migration.** Because the first governed historical
   point ran, migration from c03/RTX 4090/#115/#53-era subjects to current
   Ember Lab requires a dated, disclosed, never-threshold-relaxing amendment
   before a new run. The frozen file and receipt remain immutable. No old point
   may be silently relabelled current.
3. **LR and run independence.** Every fresh point uses the same peak LR and a
   cosine decay to 10% of peak over exactly that point's token budget, with
   warmup `min(2% of budget, registered absolute warmup)`. No mid-run schedule
   edits are allowed. Each score is terminal `C = -L_val` on the exact pinned,
   decontaminated heldout at the final step of a separately scheduled run,
   never a checkpoint sampled from one long run. A diverged point remains in
   the table and is excluded only by the frozen `final loss > initial loss`
   rule.
4. **Identity and decontamination.** Every point binds the current owned 3B
   source, executable, model/config, tokenizer, corpus manifest, heldout bytes,
   evaluator, seed, data order, optimizer, schedule, hardware, driver,
   power-limit, run/job/lease/process identity, and current decontamination
   ruling. Missing, stale, malformed, foreign, contaminated, or substituted
   identity refuses admission.
5. **Measured instrumentation.** Every point carries the registered section
   6b fields, including `adm_fingerprint`,
   `c_functional_id=neg_val_loss_v1`, measured wall-clock `e_gpu_hours`,
   lever class, and `claim_type=envelope-point`, plus raw measured-power
   custody: sampling cadence and gaps, trace hash, watts, Joules, tokens,
   active FLOPs, MFU, VRAM, wall time, and exact sampler/source identity.
   Estimates cannot replace measurements; missing sampler evidence fails
   closed.
6. **Frozen fit and holdout.** Fit the registered exponential form on points
   1-7 and reserve point 8, the `4.0x` point, as holdout. Report its residual
   rather than substituting in-sample R-squared; report leave-one-out
   diagnostics, pairs bootstrap with 10,000 resamples for the exponent
   interval, registered infinity-norm/alpha correlation, residuals, outliers,
   and confidence intervals.
7. **Verdict grammar.** Emit exactly `ENVELOPE-FIT-PASS` when the holdout
   absolute residual is within the bootstrap 95% band,
   `ENVELOPE-FIT-FAIL` when outside, or `ENVELOPE-UNDERPOWERED` when a point
   is missing or diverged. An honest FAIL is terminal. A rerun requires a
   dated amendment and may not erase the original result.
8. **H-MLI null/lever rider.** Preserve two independently seeded `1.0x`
   control replicates as the null pair and one matched `1.0x` lever run for
   the registered L1 `torch.compile` trajectory-preserving candidate.
   Preserve the fixed token axis, EMA smoothing half-life of 2,000 steps, and
   TOST margin `k = 2 * control-pair SD`. If the named historical lever cannot
   execute on the current stack, the run refuses or receives a dated
   non-relaxing amendment before launch; it is never silently substituted.
9. **Growth-arm relationship.** #1119 owns admissible current growth-arm
   science that can supply or consume an envelope point. It does not own a
   second energy envelope, and historical #123/C8 output grants no current
   point, `BOOTSTRAP_PASS`, or growth result.
10. **Negatives, rollback, and custody.** Preserve diverged, missing-sampler,
    contamination, identity-drift, schedule-drift, non-crossing, malformed,
    foreign-run, interruption, deletion, rollback, and negative-result
    evidence. Reopen on any failed binding, relaxed threshold, changed heldout
    or fit family, missing point, or result that cannot be independently
    reopened from content-addressed bytes.

## Authority and falsifier

#1116 and its current Ember Lab governed runner/custody path are the sole
envelope and measurement authority. #1119 is only the growth-arm consumer.
The closure falsifier remains a current owned 3B, independently reopenable
eight-point package satisfying every arithmetic, instrumentation, fit,
holdout, H-MLI, identity, negative, and rollback clause above.

`NO_NEW_PARALLEL_AUTHORITY`: this ruling adds no launcher, daemon, runner,
sampler, ledger, corpus, evaluator, fit, or receipt family.

## Claim boundary

- `completion_credit=false`
- `scientific_execution_credit=false`
- `acquisition_credit=false`
- `result_credit=false`
- `gpu_credit=false`
- `training_credit=false`
- `checkpoint_credit=false`
- `capability_credit=false`
- `milestone_credit=false`

No eight-point envelope, current 3B point, fit, holdout verdict, H-MLI result,
energy law, efficiency result, training result, checkpoint, capability,
sufficient-pretraining result, `BOOTSTRAP_PASS`, or milestone completion is
claimed.
