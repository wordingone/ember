# fp-41 — Graded-probe density A/B spec v1 (the powered hardening of fp-40)

**Status:** FROZEN spec, trigger-gated. Pre-staged per the wait-window queue; the
powered run executes ONLY if the c04/pretrain outcome proves **density-sensitive**
(fp-40 successor condition — not run speculatively). Successor issue: #372.

## The problem fp-40 found

The density A/B verdict (DENSITY_CONFIRMED, +33.33pp) was **statistically
underpowered via pseudoreplication** (`research/fp40-density-power-audit.md`): the
wcode probe is **binary pass/fail per prompt**, and empirically every cell rate is
exactly 0.0 or 1.0 (bimodal). So 400 prompts re-measure ONE trained model 400 times
(correlated → 1); the real unit is the **seed** (n=3), and seed-level Fisher gives
p=0.50 (even a 3/3-vs-0/3 sweep only reaches p=0.05). The prompt count manufactured
an illusion of power.

## The fix: a graded probe so within-cell prompts carry real information

Replace the binary per-prompt outcome with a **continuous competence score in
[0,1]** so within-cell prompt variance is informative and the 400 prompts genuinely
reduce the per-seed estimator variance (~1/√n), instead of collapsing to one bit.

**Chosen metric (deterministic, receipts-clean, no model judge):** per-prompt
**fractional test-pass** — each W-code prompt carries K frozen unit tests; the score
is `(tests passed)/K ∈ [0,1]`. Continuous, reproducible, no perplexity proxy and no
LLM grader (receipts-only-truth holds). Rejected alternatives: ref-completion
log-prob (proxy, not capability), BLEU/edit-distance (rewards surface form), rubric
+ model-judge (violates receipts-only).

This converts the 0/1 cell rate into a graded per-seed **mean score** `s̄_seed =
mean_p (passed_p / K_p)`, whose sampling variance over 400 prompts is real.

## Powered design (frozen before any run)

- **Arms:** arm_a = bulk (code_fraction 0.581), arm_b = curated (1.0) — unchanged.
- **Seeds:** ≥5 per arm (was 3). Seed = independent training run = the unit of the
  density test; the graded probe adds within-seed power, more seeds add between-seed
  power. Both are needed; neither alone sufficed in fp-40.
- **Probe:** N=400 W-code prompts, each with K≥4 frozen unit tests; pass-fraction per
  prompt. Tests pinned by content hash (no test drift between arms/seeds).
- **Estimator:** per-seed mean graded score; arm score = mean over seeds.
- **Decision rule (paired across the shared seed schedule):** permutation test
  (10k perms) on `mean(s̄_b) − mean(s̄_a)`, one-sided (curated ≥ bulk), α=0.05.
  Report the effect with a bootstrap CI. MDE computed from the observed per-seed
  std BEFORE unblinding the arm labels (power-helper, fp-27 precedent).
- **Verdict vocabulary (frozen):** D-GRADED-CONF (CI excludes 0, lower bound >0) /
  D-GRADED-FLAT (CI spans 0) / D-GRADED-REVERSED (upper bound <0). FLAT is a power
  statement, NOT a null (fp-40 discipline).

## What this does NOT do

Does **not** retro-tighten the frozen `density_ab_verdict.py` rule (CONFIRMED→D-CONF
stays as-is; tightening post-data = goalpost-moving). fp-41 is a SEPARATE, powered
re-measurement run if and only if density-sensitivity is demonstrated downstream.
The directional prior from fp-40 (curated crossed in 1/3 seeds, bulk in 0/3) stands
on its own terms until then.

## Companion artifact (built at execution time, not now)

`scripts/fp41_graded_density_verdict.py` — consumes the graded per-seed scores,
runs the frozen permutation test, emits the D-GRADED verdict + receipt. Selftest:
permutation p on synthetic graded arms (known separation → known p). Built when the
trigger fires, against this frozen spec.

## Trigger (precise)

Runs iff a downstream gate shows the c04/pretrain outcome is **sensitive to the
density axis** — i.e. D-CONF vs D-BELOW would change the architecture pick or the
token budget. Until then the directional prior + the two hedges (2.2B route cap +
user-owned ≤1-day pretrain bar) suffice, per fp-40.
