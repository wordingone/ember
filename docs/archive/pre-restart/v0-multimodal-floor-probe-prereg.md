# v0 multimodal pilot — checkpoint-1 image-grounded floor-probe (kill-#6), FROZEN

**Status:** authored 2026-06-16 (the lead, seat). Frozen BEFORE the authorized run exists
(anti-goalpost / freeze-target-before-iterating). **This is the canonical MR-8 spec** — it
adopts the concrete ablation mechanism proven by the ER-4 harness (PR #443) and the b-multi-1
held-out, fixes the CC3M-leakage hole, and adds the real-tokenizer requirement; it SUPERSEDES
the copy the engineer bundled into PR #443 (which the seat reclaimed — edit requires the lead). Companion to
`pretrain-launch-authorization-brief-multimodal.md` (the authorization),
`v0-multimodal-token-budget-decision.md` (N + budget), and `ember-floor-contract.md`
(row 47 = the promote/kill condition this doc operationalizes).

This freezes the **checkpoint-1 kill-criterion #6** verdict so that, when the run is
authorized and reaches checkpoint-1, "continue vs halt" is computed **mechanically against
this spec** — never re-interpreted live. It is the multimodal analogue of
`delta-rule-diagnostic-prereg.md`: question, arms, measured criterion, pass/fail/inconclusive
bands, verdict→action map, all fixed before the receipt exists.

## 0. Why kill-#6 needs a frozen probe

The whole pilot's success bar (floor-contract row 47) is **image-grounded verify-rate >
text-only control**. The risk the pilot measures: a 0.37B encoder-free model may train to a
fine *text* model that **ignores the image tokens** (the loss descends on text alone — 65.45%
of the launch mix is text). If grounding never emerges, every governed-day after checkpoint-1
is wasted. Kill-#6 is the early halt. Without a frozen probe, "is it grounding yet?" gets
re-litigated live at checkpoint-1 under sunk-cost pressure — exactly the goalpost-move this
doc forbids.

## 1. WHEN — checkpoint-1

- **checkpoint-1 = the first checkpoint at a FIXED token count ≈ 10% of the 1-governed-day
  floor ≈ 75M tokens** (≈ 2.4 governed hours at FINAL N tok/s 8,627). Early enough that a halt
  saves ~90% of the pilot budget; late enough that a 0.37B model has seen ~0.2M sequences.
- Exact step is read from the WSD schedule at launch and recorded in the probe receipt; the
  **token count is the contract**, not a step number (schedule-agnostic).

## 2. ARMS — one variable: image present vs absent

Identical checkpoint, identical decoding, identical probe items. The ONLY difference is the
image.

- **Grounded arm:** input = `[DELIM_START, patches×n, DELIM_END, caption]` (the matched pair,
  exactly the ER-2d launch format). Full multimodal forward — soft-tokens spliced, Locks 1–4
  active (`inputs_embeds=soft_tokens, span_boundaries=[(1,1+n)]`).
- **Control arm:** the SAME `input_ids` (image-placeholder tokens present, length identical),
  but the image **content** ablated — no soft-token splice, no bidirectional image mask, no 2D
  RoPE (`inputs_embeds=None, span_boundaries=[]`); the placeholder positions receive only their
  vocabulary embedding. Position/length are held constant; only image *content* is removed. This
  is the concrete implementable form proven faithful by the ER-4 harness (`_compute_nll_pair`,
  PR #443): it isolates "does the image content help," not "does the sequence shape change."

## 3. METRIC — paired ΔNLL (sensitive at low competence; mechanical)

At checkpoint-1 a 0.37B model is barely trained; a **generative** verify-rate would be
near-zero in both arms (noise). The floor-contract's verify-rate is the **end-of-run** promote
bar. The **checkpoint-1** kill-#6 gate uses the far more sensitive, fully-deterministic signal:

    per-item ΔNLL = NLL(caption | image ABSENT) − NLL(caption | image PRESENT)

ΔNLL > 0 ⟺ the image makes the caption more predictable ⟺ the model is using the image.
This is paired (per probe item), needs no sampling (deterministic forward passes), and detects
grounding **before** the model can generate correct answers. Report mean ΔNLL, median ΔNLL,
the paired-test p-value, and the fraction of items with ΔNLL > 0.

## 4. PROBE SET — held-out, DISJOINT-BY-CONSTRUCTION, frozen

- **N = 500–1,000 matched pairs**, a HELD-OUT set whose every pair is **EXCLUDED from the CC3M
  training stream by URL+hash blocklist**; the exclusion manifest is frozen in the probe receipt
  BEFORE the run. Disjointness is by construction, not by assumption. Captions are real (same
  encoder-free patch format as training).
- **The local b-multi-1 500-pair set is eligible as the held-out probe — but ONLY with its 500
  source URLs/hashes added to the stream's exclusion list.** b-multi-1 was acquired AS 500 CC3M
  pairs (PR #436); since the run STREAMS CC3M, it is *not* automatically disjoint — the
  "b-multi-1 is not part of CC3M" justification is FALSE and must not be relied on. Exclude its
  URLs from the stream and it is a valid, real, curated held-out set; if exclusion cannot be
  guaranteed, reserve a fresh ≥1,000-pair CC3M split as the held-out manifest instead.
- **Tokenization (checkpoint-1 requirement, frozen here):** the probe MUST encode captions with
  the SAME tokenizer the run trained on. ER-4's `ord(c) % vocab` is a mechanism-proof shortcut
  (random weights → tokenizer irrelevant); at the real checkpoint-1 it would make ΔNLL
  meaningless.
- N ≥ 500 paired items gives ample power for a paired signed-rank test at the ε below.

## 5. BANDS — mechanical PASS / FAIL / INCONCLUSIVE

Let ε = **0.02 nats/token** minimum effect size (a small but non-trivial grounding effect;
frozen here, not chosen post-hoc).

- **PASS → CONTINUE:** mean ΔNLL > 0, paired Wilcoxon signed-rank **p < 0.01**, AND median
  ΔNLL ≥ ε. Grounding is present and non-trivial → run continues to the authorized budget.
- **FAIL → HALT (kill-#6):** mean ΔNLL ≤ 0, OR not significant at p < 0.01. The image is not
  moving the caption distribution → grounding absent → **halt, do not spend the remaining
  budget.** Write the kill receipt.
- **INCONCLUSIVE → one bounded extension:** significant (p < 0.01) but median ΔNLL < ε
  (grounding present but trivially weak). Action: train to **checkpoint-1b = 2× tokens (≈150M)**
  and re-run this exact probe ONCE. If still < ε → treat as FAIL (fail-safe halt). Bounded, not
  open-ended.

ε, N, p-threshold, and the checkpoint-1 token count are frozen by this doc. The verdict is the
mechanical output of the receipt against these numbers — no live re-interpretation.

## 6. VERDICT → ACTION

| Verdict | Action |
|---|---|
| PASS | Continue to the authorized budget (1-day pilot, or up to the 9.9-day Chinchilla ceiling per the maintainer). End-of-run success bar reverts to the floor-contract verify-rate > control. |
| FAIL | Halt. Kill receipt (`receipts/`). The pilot is a **receipted negative** — grounding did not emerge at this scale/budget. Successor per floor-contract row 47: a dedicated multimodal rung / more budget = **the maintainer's call, not a silent extend** (never-reduce-scope in reverse). |
| INCONCLUSIVE | One bounded extension to checkpoint-1b (2× tokens), re-probe once, then PASS/FAIL mechanically. |

## 7. Anti-goalpost + linkages

- **Frozen before the run.** This is the freeze-target discipline that fixed precondition-1
  and the budget framework: the verdict criterion exists before the receipt, so checkpoint-1 is
  mechanical, not a sunk-cost negotiation.
- **#33 linkage:** "image-grounded verify" IS the emit-pointer grounding interface —
  `resolve(query, image-address-space) → grounded answer`. ΔNLL > 0 is the first empirical
  signal that grounding-by-attention-over-image-keys emerges at v0 scale. A PASS is weak
  positive evidence for the transferable-attention-resolver hypothesis (#33 ADVANCE-d); a FAIL
  bounds where grounding needs more scale — both feed `world-model-compiler-decision.md`.
- **Staleness (flagged for the maintainer, not rewritten here):** floor-contract row 47 still frames
  encoder-free multimodal TRAINING as RE-STAGED / post-v0; the maintainer's 06-14 reactivation made it the
  v0 launch target. This prereg operates on the operative intent; the row-47 reconciliation is
  the maintainer's (carried in the budget doc + the brief).

## Ownership (routable action-contract)

- **Spec (frozen): the lead (seat)** — this doc; no further seat action until the run is authorized.
- **Run the probe at checkpoint-1: the engineer**, as an integral step of the authorized run (emit the
  ΔNLL receipt; the verdict is mechanical against §5).
- **Routing status: `GATED: the maintainer-launch-authorization`** — deliberately un-routed until the maintainer
  authorizes the run (`EMBER_GATE_AUTHORIZED=1`). On authorization, this becomes an the engineer run-step
  (President dispatches alongside the launch); until then it is frozen seat output, not pending
  work.

Per user direction.
