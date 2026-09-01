# W2 pre-registration v1 — from-scratch-at-width vs grow, rung-2 scale (the post-W1 redirect)

**Status: FROZEN at authorship (2026-07-04, maintainer). GPU-gated behind the C-E2B endgame
(one-model queue). No arm may start before the held-out decontamination leg (§4) completes.**

## 1. What W1 established and what it did not

W1 (receipt `receipts/ember-c-scale/w1-collapse-control-20260704T144548Z.json` — absent as of
2026-08-01 in this contract tree, unlanded to master, claim L3,
public issue #82 closed-landed): a width-matched from-scratch control under the matched recipe
reached the grown model's capability point (eval 7.28125 on the sha-pinned held-out batch) by
its FIRST eval cadence at step 100, giving token ratio ≤ 1,638,400/12,550,144 = **0.1305 —
an UPPER bound** (coarse eval cadence; true crossing may be earlier). Contamination was
disclosed (69,811 window matches) with bias direction FAVORING the grow arm, so L3 is
conservative-valid. Consequence already recorded in CONTINUITY: the frozen rung-2 grow spec is
CONTRADICTED AT FOUNDATION and must not execute as-is.

What W1 did NOT establish: (a) scale-persistence — the result is rung-1 scale; the growth
literature's standard claim is that growth economics improve with scale; (b) a tight ratio —
0.1305 is cadence-limited from above; (c) anything about DEPTH growth (W1 tested width).

## 2. W2 question (single, pre-registered)

At rung-2 scale (2× the rung-1 target width), does from-scratch-at-width still reach the
grown model's capability point in ≤ X% of the grow path's tokens?

**Arms.**
- **G (grow):** net2net width-expand the W1 from-scratch control (step-100 checkpoint,
  sha-verified) to 2× width, then continue-train under the matched recipe.
- **S (scratch):** identical architecture at 2× width, random init (seeded), same recipe.

**Matched recipe = W1's:** muon split, MTP aux weight 0.3 / 2 heads, cosine+warmup,
cut_ce_chunked; identical data order per arm (same seed for the sampler); identical eval
battery and cadence.

## 3. Pre-registered claim ladder

- **L0:** both arms complete their token budget B with coherent receipts (spend fields, eval
  series, checkpoint shas). B = the grow arm's projected tokens-to-capability-point × 1.5,
  derived from rung-1 measurements before launch and written into the launch receipt.
- **L1:** capability-point crossing measured for both arms on the decontaminated held-out
  (§4) at DENSE early cadence (every 25 steps until crossing, then every 100).
- **L2:** ratio = tokens_S(crossing) / tokens_G(crossing) reported with cadence-width error
  bars (the interval between the crossing eval and the previous eval).
- **L3 (headline):** ratio ≤ 0.5 ⇒ W1's redirect GENERALIZES to rung-2 (growth ladder stays
  contradicted; C-SCALE proceeds from-scratch-at-width). ratio ≥ 1.0 ⇒ W1 was
  scale-local; growth economics recover at rung-2 (redirect REVOKED, disclosed on #29).
  0.5 < ratio < 1.0 ⇒ indeterminate band: neither claim; W3 designs the discriminating run.
  Thresholds frozen now, before any data.

## 4. Decontamination precondition (cures W1's disclosed defect)

Before either arm launches: rebuild the held-out eval batch with window-level dedup against
the FULL training corpus (the W1 procedure that found 69,811 matches, run as a FILTER this
time, not a post-hoc check). The decontaminated batch is sha-pinned in this doc's companion
receipt before launch; `contamination_recheck` must report 0 matches or the launch gate
refuses.

## 5. Rails

One-model-resident; governor caps + commit-margin assert (chunked-hash lesson applied);
receipts-only; both arms' receipts carry spend fields per §7 of the receipt conventions;
control-authorship separation — the S arm's config is derived mechanically from the G arm's
architecture dump, never hand-tuned; no mid-run recipe edits (a divergence aborts the run,
receipted, restart both arms).

## 6. Relation to C-SCALE

C-SCALE's operating-capability-point bar (>3e9) is NOT claimed by W2 at any outcome. W2 only
selects the PATH (scratch-at-width vs grow) for the scale program's next rungs. The apex
program remains public issue #29; W2's outcome lands there either way, including a revoked
redirect.
