# DT-3 scale-probe — pre-registration (FROZEN before any receipt)

**Status:** frozen 2026-06-16 (the lead, seat), BEFORE the probe (or even DT-1's run)
produces a number — anti-goalpost / freeze-target-before-iterating, the same
discipline as `delta-rule-diagnostic-prereg.md` (DT-1) and
`v0-multimodal-floor-probe-prereg.md`. Companion to DT-1 (the parity diagnostic
this scales up) and `ember-owned-substrate-diagnostic.md` (the owned-substrate
program). DT-1's verdict map names this doc explicitly: **"PASS (either arm) →
owned-update path PROCEEDS … next = scale probe."** This freezes that scale
probe so, the instant DT-1 passes, the scale verdict is mechanical — not
re-litigated live under "it nearly held."

## Question

DT-1 measures whether ember's owned **delta-rule fused local update**
(`W -= eta·outer(prediction_error, input)`, no backprop chain) matches or beats
autograd-`backward()` on next-token loss at EQUAL 4090 wall-clock, at **10–50M
params**. DT-3 asks the scaling question that a 10–50M PASS leaves open:

> **Does that equal-wall-clock parity HOLD as the owned update is scaled from
> the DT-1 regime (10–50M) up to the 0.37B launch core size — or does the gap
> vs backprop WIDEN with scale?**

The failure mode being measured: a local/shallow update rule can win at small
scale yet degrade as depth/width grow, because the local error signal reaches
deep weights less effectively than a global reverse sweep. "Wins at 50M" does
not entail "wins at 0.37B." DT-3 measures the *trajectory of the gap*, not a
single point.

## WHEN — trigger + scale ladder (frozen)

- **Trigger:** DT-1 PASS (either arm). DT-3 does NOT run on a DT-1 FAIL (owned
  update is already shelved for round-1 in that case). `GATED: DT-1 diagnostic PASS`.

> **[SUPERSEDED 2026-07-10]** This trigger is gated closed per errata issue #670: the DT-1 PASS receipt is void as learning/GDN evidence (chance-level, out-of-band, missing DT-6 gate fields). DT-3 must not run from this receipt. The owned-substrate diagnostic may restart with a valid DT-1 receipt under the DT-6 gate.
- **Scale ladder (frozen):** S = {**10M, 50M, ~150M, 0.37B**} params — spanning
  the DT-1 regime through the launch core size (the §IV multimodal config is
  0.37B; the owned-substrate replacement, if it earns it, targets that size).
  The 0.37B point is the contract; the intermediate points establish the trend.
- Each scale runs at **EQUAL 4090 wall-clock** (DT-1's budget rule — the local
  rule runs more steps in the same time because it skips the ~500ms backward).

## ARMS — inherited from DT-1's verdict (one variable: scale)

- **Owned arm:** the delta-rule fused-update LM block, in the arm that PASSED
  DT-1 (WARM-init if DT-1 ended "WARM PASS / COLD FAIL"; either if both passed).
  Arm selection is INHERITED, not re-chosen — DT-3 changes scale only.
- **Reference arm:** the same architecture trained by autograd `backward()` +
  the borrowed optimizer (AdamW/Muon per `fp44-multimodal-optimizer-decision.md`)
  — the baseline the owned substrate must not fall behind (owned-substrate
  diagnostic: "the c04/PyTorch receipts … become the baseline the owned
  substrate must beat").
- Identical data stream, identical wall-clock budget, ≥2 seeds per cell.

## METRIC — the gap trajectory (mechanical)

At each scale s, at equal wall-clock, measure next-token loss for both arms and
define the **relative gap**:

    gap(s) = ( loss_owned(s) − loss_reference(s) ) / loss_reference(s)

gap(s) ≤ 0 ⟺ owned is at-or-better than backprop at scale s. DT-1's PASS band
(≤10% relative, or lower) is the per-scale band; DT-3's verdict is on gap(s)
across the WHOLE ladder. Report gap at each s, the per-cell seed spread, and the
fitted slope d·gap/d·log(params).

## BANDS — mechanical PASS / FAIL / INCONCLUSIVE (frozen)

Let the per-scale band be DT-1's: **τ = 0.10** relative.

- **PASS → owned substrate SCALES:** gap(s) ≤ τ for ALL s up to and including
  0.37B (owned never falls >10% behind backprop at any probed scale). The owned
  fused-update is a candidate optimizer/runtime for the 0.37B-class owned-substrate
  build. If, in addition, the slope is flat or negative, the candidacy is strong;
  a positive slope that nonetheless stays under τ at 0.37B is a PASS-with-caveat
  (documented extrapolation: where the trend would breach τ beyond 0.37B — the
  E2B-surpass scaling question, not this verdict's).
- **FAIL → owned substrate does NOT scale (at this method):** gap(s) > τ at some
  s ≤ 0.37B with a non-decreasing trend → the owned update breaks at scale s*.
  Record s* as the documented owned-substrate scale ceiling. The 0.37B build
  uses the borrowed optimizer (already the v0 plan — see below); DT-3 bounds
  *where* the owned method would need work, it does not block anything shipping.
- **INCONCLUSIVE → one bounded extension:** a single-scale breach within seed
  noise, or a non-monotone blip (gap > τ at one s but ≤ τ at the next larger s).
  Action: add seeds at the breaching scale OR insert one intermediate scale
  point, re-run ONCE, then PASS/FAIL mechanically. Bounded, not open-ended.

τ, the scale ladder, the seed floor, and the equal-wall-clock rule are frozen
here; the verdict is the mechanical output of the receipt against them.

## VERDICT → ACTION

| Verdict | Action |
|---|---|
| PASS | Owned fused-update is a 0.37B-class candidate → spec the owned-substrate build (the DT-5 runtime-axis scope becomes live: what ember owns above cuBLAS/tensors). The borrowed-optimizer launch is unaffected; the owned path becomes a *future* replacement with a receipted scaling basis. |
| FAIL | Owned update shelved at scale; record s* (the break point) in the owned-substrate diagnostic. v0 + the 0.37B launch ship on the borrowed optimizer (unchanged). Successor (more owned-substrate work vs accept-borrowed) = the maintainer's call, not a silent extend. |
| INCONCLUSIVE | One bounded extension (seeds or one scale point), then PASS/FAIL mechanically. |

## Relationship to the launch (no blocking dependency)

v0 and the 0.37B multimodal launch ship on the **borrowed optimizer** regardless
(config-spec §IV; `fp44-multimodal-optimizer-decision.md`). DT-3 informs the
**owned-substrate replacement** of that optimizer — a separate, later track. A
DT-3 FAIL does NOT block the launch; a DT-3 PASS does not gate it either. This
is deliberately decoupled so the earn-the-run critical path never waits on the
owned-substrate program. (DT-3 itself is gated behind DT-1, which is behind the
multimodal readiness — so DT-3 fires well after the launch.)

## Loop-economics framing (inherited from DT-1, an agent 15051 — additive)

The equal-wall-clock gap at each scale IS the loop-economics gate at that scale:
it measures verified next-token learning per 4090 GPU-hour, not "the model ran."
A PASS means the owned fused-update delivers equal-or-better verified learning
signal per wall-clock GPU-hour than backprop *at the launch scale* — the whole
point of owning the optimizer/runtime under the single-4090 residency constraint.
A merely-runnable owned core that loses this gap at scale is a FAIL by design.

## Citation lineage (required, per policy)

Inherits DT-1's lineage (`docs/citation-policy-search-to-ember.md`): delta-rule
forward model — DIRECT prior **Widrow & Hoff (1960)** LMS/delta rule; upstream
Hebb (1949), Rosenblatt (1958). DT-3's [UNIQUE] element (validated by no one):
**local fused-update × scaling to 0.37B next-token LM** — The Search ran these
rules on toy tasks only; the scale trajectory at LM-pretrain size is ember's own
open question, borrowed from no prior result.

## Ownership (routable action-contract)

- **Spec (frozen): the lead (seat)** — this doc; no further seat action until DT-1 passes.
- **Run the probe at the scale ladder: the engineer** — at the DT-3 trigger (DT-1 PASS),
  as an owned-substrate run-step; emit the gap(s) receipt; the verdict is
  mechanical against §BANDS.
- **Routing status: `GATED: DT-1 diagnostic PASS`** — deliberately un-routed until
  DT-1 passes (which is itself behind multimodal readiness). Frozen seat output,
  not pending work, until then.

Per user direction.
