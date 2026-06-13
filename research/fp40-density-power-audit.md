# fp-40 — Density A/B unit-of-analysis audit (pseudoreplication)

**Question:** the density A/B verdict (DENSITY-AB-VERDICT, `density-ab-verdict-20260613T043948Z`)
returned **DENSITY_CONFIRMED** at delta = 33.33pp, read as decisive because the
spec (#359 / `docs/c04-token-budget-v1.md` F-4) sized **n=400 prompts → 3.85pp MDE**
and 33.33 ≫ 3.85. Is that confirmation statistically real, and is it safe to drive
the c04 pick → pretrain commit?

**Finding: no — it is directionally correct but statistically underpowered, and the
"33pp ≫ 3.85pp MDE" reasoning is a pseudoreplication error.**

## The probe is bimodal → the unit is the seed, not the prompt

Every one of the 12 observed rates (6 cells × {50pct, 100pct}) is **exactly 0.0 or
1.0**. A graded model at, say, 0.5 competence would give ~200/400; getting exactly
0/400 or 400/400 in every cell means each trained model's pass-probability is ~0 or
~1. So the 400 prompts do **not** supply 400 independent trials of the density
effect — they re-measure **one trained model** 400 times, correlated to ~1. The unit
of analysis for the *density comparison* is the **seed** (an independent training
run), not the prompt.

| | spec's claim | reality |
|---|---|---|
| unit | 400 prompts | 3 seeds per arm |
| outcome | graded rate | binary cell (crossed / did not) |
| MDE | 3.85pp | n/a — a 2×2 of crossings |

## Honest seed-level power

Seed-level data: arm_b (curated) crossed in **1 of 3** seeds, arm_a (bulk) in **0 of 3**.
Fisher exact (hypergeometric) one-sided p for "arm_b ≥ observed crossings":

- observed **1/3 vs 0/3 → p = 0.50** (cannot reject the null)
- best case **3/3 vs 0/3 → p = 0.05** (even a clean sweep is only borderline)

With 3 seeds and a binary probe the experiment is **structurally underpowered**: the
prompt count manufactured an illusion of power. (Receipt:
`fp39-density-power-audit-20260613T051216Z.json`; computation `scripts/fp39_density_power_audit.py`,
selftest `FP39_POWER_AUDIT_SELFTEST_PASS` validates the hypergeometric on 4 known cases.)

## Consequence — does NOT rewrite the frozen rule

`density_ab_verdict.py` was frozen pre-data assuming `wcode_rate` is a graded
continuous metric, so it maps CONFIRMED → D-CONF. This audit does **not** retro-tighten
that rule (frozen pre-data; tightening post-data is goalpost-moving). It registers a
**deviation**: D-CONF here is a **directional prior favouring curated**, not powered
evidence. The c04 pick consuming D-CONF must treat it as such. The hedges that make an
underpowered D-CONF non-catastrophic:

1. the route table caps the optimistic L10-FULL corner at **budget ≤ 2.2B**, and
2. the pretrain dispatch is a **user-owned ≤1-governed-day bar** — a further gate.

The directional finding stands on its own terms: curated crossed the capability
threshold in 1/3 seeds, bulk in 0/3 — consistent with the density hypothesis, just not
powered.

## Successor — fp-41 (hardening, gated)

If the c04/pretrain outcome proves **sensitive** to the density axis (i.e. D-CONF vs
D-BELOW would change the architecture pick or the budget), run a **powered** density
A/B: a **graded probe** (so within-cell prompts add real power) + **more seeds**. Gated
on demonstrated downstream density-sensitivity — not run speculatively, since the
directional prior + the two hedges may already suffice.
