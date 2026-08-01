# Publishability adjudication v1 — the clause-7 mechanism

*Status: BINDING (drafted 2026-07-03; ratified same day by acting-operator ruling R5,
receipts/acceptance/acting-operator-ruling-2-20260703.json, under the operator's 2026-07-03
delegation directive — reversible on one operator word). Operationalizes GOAL.md §1 clause 7
("unanimously and undeniably publishable as a field level contribution") — which named no
adjudication mechanism and was therefore unfalsifiable in both directions (contract-integrity
audit 2026-07-03, docs/audit/goal-audit-20260703.md row G-s1-7). This spec makes the clause
STRICTER, never softer: every leg below is conjunctive, and no leg substitutes for another.*

## 0. What "unanimously and undeniably" means here

Clause 7 flips only when ALL FIVE legs hold simultaneously on the SAME frozen draft, evidenced
by receipts, closed by an operator acceptance object. Prose enthusiasm, partial passes, and
"almost" have no standing. A draft that fails any leg is NOT publishable-per-clause-7, full stop.

## 1. Leg A — adversarial referee panel (the "unanimously" operator)

- **Panel:** ≥5 independent referee passes over the full frozen draft, each a distinct lens:
  (1) methods/statistics, (2) novelty vs the dated literature grounding, (3) claims-vs-receipts
  fidelity, (4) reproducibility (could a hostile reader re-execute?), (5) clarity/presentation.
- **Blind + adversarial:** panelists never see each other's verdicts, prior rounds' verdicts, or
  authorship framing; each prompt's stated job is *"find the reason this paper is NOT
  publishable at a top venue."* Agent panels follow the standing agent-class rail (cheap models;
  at most one terminal frontier verdict leg).
- **Output (typed, per panelist):** verdict ∈ {ACCEPT, MINOR, MAJOR, REJECT} + enumerated
  defects, each anchored to a section/claim.
- **Unanimity =** across a SINGLE full round: zero REJECT, zero MAJOR, and every MINOR either
  cured or explicitly waived by the operator in the acceptance object. Verdicts from different
  rounds never combine — cures re-enter a fresh full round (§6).

## 2. Leg B — claims audit (the "undeniably" floor)

Every quantitative or capability claim in the draft resolves to a @paper/claims-evidence-map.md
row whose receipt is RE-OPENED and re-verified at adjudication time (no caching of trust). The
map's own rule is load-bearing here: a claim not in the table is not made. Zero unmapped claims,
zero ABSENT-slot claims stated as results (RESULT-GATED honesty per @paper/outline.md). Both
`paper/claims-evidence-map.md` and `paper/outline.md` are absent as of 2026-08-01 in this
contract tree (authored on the pre-registration lane, not yet merged to master).

## 3. Leg C — field-level delta (the "field level contribution" test)

- The contribution is stated as a **falsifiable delta against the dated grounding negatives**
  (@docs/grounding/self-improvement-2026.md, @docs/grounding/local-fm-2026.md), re-swept ≤30
  days before any submission per the publication spec (@docs/spec/publication-v1.md, re-sweep
  clause; all three paths cited in this item are absent as of 2026-08-01 in this contract tree,
  unmerged to master).
- The research-focus test of GOAL.md section 1b applies under the **inclusive reading** (R4,
  same receipt): a contribution is research if it is a statement about — or an instrument
  constitutive of — one of the two formal objects. Instruments remain subject to this leg's
  delta bar: "we built a tool" without a receipted, falsifiable field-delta still fails.
- Mechanized floor: `scripts/check_publication_gate.py` conjuncts green (board-wired execution
  of that checker is queued mechanism work — the audit's Class-2 cure; until wired, a fresh
  manual execution receipt is required per adjudication round).

## 4. Leg D — experience leg (the reader's chair)

The paper is read END-TO-END as its recipient — a busy, skeptical field reviewer — side-by-side
with 2–3 named exemplar papers of the venue's best recent work, and a **wince-list receipt** is
produced unprompted: every place the draft reads worse than the exemplars (structure, figures,
notation, prose). Each wince item is cured or operator-waived. An adjudication round with an
empty wince-list and no exemplar comparison receipt is INVALID — silence means nobody looked
(maintainer rule: last-leg-experience-gate, 2026-07-03).

## 5. Leg E — operator acceptance object

Final authority: an acceptance receipt `receipts/acceptance/publishability-<ts>.json` signed by
the operator — or by the maintainer as acting-operator under the 2026-07-03 delegation, with the
acting-operator provenance stated in the object and loud same-turn disclosure — listing the
receipt paths of legs A–D for the exact frozen draft sha. Clause 7 flips on this object and
nothing else.

## 6. Cure loop + convergence discipline

Defects found in any leg → cures land → the ENTIRE panel round re-runs fresh (new panel
instances, no memory of prior rounds). Passing = one fully clean round. If three consecutive
full rounds fail to converge, the state is escalated to the operator with the defect trace —
the bar is never lowered to force convergence.

## 7. Anti-self-deception rails

Receipts-only throughout; panel prompts forbid deference ("the maintainer believes X" never
appears); no panelist output is summarized-by-the-maintainer into the record — verdict files are
stored verbatim; the adjudication receipts are public-repo artifacts (subject to the standing
redaction contract), so a hostile external reader can audit the adjudication itself.
