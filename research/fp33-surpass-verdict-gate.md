# fp-33 — E2B-surpass conjunction-verdict gate (the goal's terminal gate)

**Pre-registered before any leg receipt exists** (fp-39/fp-44 discipline). Scorer:
`scripts/fp33_surpass_verdict.py` (`FP33_SURPASS_VERDICT_SELFTEST_PASS`, 17 cases).
Contract frozen in `docs/fp33-surpass-prereg-v1.md`; this doc holds the receipt
schema + the decision-machine notes. Decision logic is FROZEN in the scorer.

## Why this gate exists

The ember GOAL has **two** completion conditions. (1) `scripts/ember_tally.py`
reads 100% on `docs/ember-completeness.md`. (2) **an S5 E2B-surpass receipt
exists.** This scorer produces (2): it reads the seven leg receipts and computes

    SURPASS = A1 ∧ A2 ∧ A3 ∧ B1 ∧ B2 ∧ B3 ∧ B4

emitting the verdict as a committed receipt (`--emit` →
`receipts/fp33-surpass-verdict-<ts>.json`). The individual leg *harnesses*
(`scripts/fp33_*`) measure each bar; nothing aggregated them into the frozen
conjunction until now. The means (base pick / training plan) gate elsewhere
(#255) and never touch this verdict.

## The frozen decision rule (per leg)

Statistics block (verbatim from the prereg): paired bootstrap over tasks, 10,000
resamples, 95% CI on per-task delta (ember − E2B). "In ember's favor" = CI
excludes 0 with positive mean. "Parity-or-better" = CI lower bound > −MDE (run-time
recorded) OR excludes 0 in ember's favor. Binary duty episodes → McNemar exact,
p<0.05. Matched compute: each paired side within 10% on wall/gpu_s/tokens, else the
receipt is **INVALID** (re-run, never reinterpret).

| leg | bar | PASS condition in scorer |
|---|---|---|
| **A1** floor-world paired | CI excludes 0 in ember's favor | bootstrap CI lo > 0 |
| **A2** accumulation differential (THE thesis bar) | ember 3-test PASS AND (E2B 3-test FAIL **or** transfer-Δ CI excludes 0) | Path-2 (ember 3-test, E2B not) **or** Path-1 (both 3-test, paired Δ CI lo>0) |
| **A3** public slices (parity floor) | MBPP **and** GSM8K-200 both parity-or-better | each slice CI lo > −MDE |
| **B1** answers-when-spoken-to | ember ≥4/5 AND ember > E2B (McNemar if both imperfect) | counts + McNemar p<0.05 when both <5 |
| **B2** agency | ember ≥4/5 obligated AND ember > E2B | completion counts |
| **B3** duty battery (20 ep, paired) | ember strictly better, McNemar p<0.05 | b>c AND mcnemar_exact(b,c)<0.05 |
| **B4** evals-through-harness | binary: receipt exists | receipt_exists ∧ dispatched_through_harness |

Verdict roll-up: **SURPASS** = all seven PASS. Any **PENDING** (no receipt yet)
or **INVALID** (compute-mismatch / malformed) → **INCOMPLETE** (today's honest
pre-pretrain state: 7 PENDING). Otherwise → **SHORTFALL** with a
`measured_distance` array (which bar failed + numeric distance), per the GOAL
CALIBRATION block. Shortfall on 2026-06-22 = distance receipt, loop continues;
only the user moves the date/bar.

## Expected per-leg receipt schema (loader is tolerant)

Each leg lands as `receipts/*.json` carrying a `leg` field. Paired legs carry a
`compute` block `{ember:{wall_s,gpu_s,tokens}, e2b:{...}}` (the matched-10% gate).

```
A1: {leg:"A1", floor_set_manifest_sha, per_task_delta:[...], compute:{...}}
    (per_task_delta = ember−E2B per task; or per_task_ember[]/per_task_e2b[])
A2: {leg:"A2", ember_three_test:{held_out_transfer,matched_control,deletion},
     e2b_three_test:{...}, per_task_delta:[...transfer Δ...], compute:{...}}
A3: {leg:"A3", slices:{mbpp:{per_task_delta:[...],mde}, gsm8k200:{...,mde}},
     compute:{...}}
B1: {leg:"B1", ember_correct:int(/5), e2b_correct:int, discordant:{b,c}?}
B2: {leg:"B2", ember_done:int(/5), e2b_done:int}
B3: {leg:"B3", episodes:20, discordant:{b,c}}   # b=ember✓/E2B✗, c=ember✗/E2B✓
B4: {leg:"B4", receipt_exists:true, dispatched_through_harness:true}
```

Multiple receipts for one leg → latest by filename wins. Missing leg → PENDING.

## Path after the verdict

- **SURPASS** → emit the receipt; completion-condition #2 satisfied; `ember_tally`
  reads it.
- **INCOMPLETE** → which legs are PENDING/INVALID; the gated tasks (B-legs behind
  the NC-K harness + ember ckpt resident; A-legs behind pretrain) stay open.
- **SHORTFALL** → measured-distance receipt; the accumulation loop continues
  unchanged toward the failed bars.

## Determinism

Pure stdlib. Bootstrap RNG seeded (`BOOTSTRAP_SEED=33`) → CI reproducible across
runs. McNemar exact via `math.comb` (no scipy). The analyze/selftest paths are
time-free (CI-safe); only `--emit` stamps a UTC timestamp.
